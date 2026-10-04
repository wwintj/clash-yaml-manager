"""Loopback-only Fixed UX scenarios in run_preview_browser's disposable app copy."""
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import threading
from unittest.mock import patch


@contextmanager
def fixed_ux_server(module):
    from core import generator, node_health, proxy_health
    from core.state import write_json

    root = Path(module.BASE_DIR)
    assert root.name.startswith('clash-preview-browser-'), 'Never seed a real runtime'
    store = module.fixed_subscriptions
    base = b'proxies: []\nproxy-groups: []\nrules: ["MATCH,DIRECT"]\n'
    state = {'entries': [], 'secrets': [], 'scenario': 'empty'}
    specs = [
        ('Alpha Active', 'alpha-first', 'active', 2, 2000, 2),
        ('Beta Disabled', 'beta-disabled', 'disabled', 10, 2000, 1),
        ('Gamma Active', 'gamma-active', 'active', 1, 3000, 0),
        ('Alpha Active', 'alpha-second', 'disabled', 2, 2000, 0),
        ('Tokyo 東京', 'tokyo-unicode', 'active', 3, 1000, 0),
        ('Long ' + 'L' * 123, 'long-' + 'p' * 59, 'active', 3, 4000, 3),
    ]

    def reset():
        # This context is only used by the last suite in a throwaway copied app.
        shutil.rmtree(store.directory)
        store.directory.mkdir(mode=0o700)
        for name in ('fixed_subscriptions.json', 'node_health.json', 'proxy_health.json'):
            (Path(module.DIR_STATE) / name).unlink(missing_ok=True)
        state.update(entries=[], secrets=[])

    def metadata():
        entries = store.list()
        return dict(scenario=state['scenario'], entries=[
            dict(name=item['name'], prefix=item['prefix'], status=item['status'],
                 nodes=item['node_count'], updated=item['updated_at'],
                 sources=len(item['sources']) - 1, url='/s/' + store.slug(item))
            for item in entries], secrets=state['secrets'])

    def snapshot():
        files = {}
        for name in ('fixed_subscriptions.json', 'node_health.json', 'proxy_health.json'):
            path = Path(module.DIR_STATE) / name
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        return dict(files=files, count=len(store.list()))

    def seed(count):
        reset()
        choices = list(specs)
        for index in range(6, count):
            choices.append((f'Subscription {index:02d}', f'sample-{index:02d}',
                            'disabled' if index % 3 == 0 else 'active', index % 10 + 1,
                            5000 + index, index % 3))
        for index, (name, prefix, status, nodes, at, source_count) in enumerate(choices[:count]):
            batch = []
            for node_index in range(nodes):
                node_name = f'PRIVATE_FIXED_UX_NODE_{index}_{node_index}'
                password = f'PRIVATE_FIXED_UX_PASSWORD_{index}_{node_index}'
                server = f'private-health-{index}-{node_index}.example'
                batch.append(f'US|{node_name}|trojan://{password}@{server}:443')
                state['secrets'].extend((node_name, password, server))
            source = dict(yaml_source='custom', batch_nodes='\n'.join(batch),
                          aux_nodes=[], node_overrides={}, special_groups=[])
            external = []
            for source_index in range(source_count):
                secret = f'PRIVATE_REMOTE_UX_{index}_{source_index}'
                state['secrets'].append(secret)
                external.append(dict(type='remote_url', name=f'External {source_index + 1}',
                                     url=f'https://source.example/sub?token={secret}', enabled=False,
                                     format='raw', refresh_interval_seconds=None))
            parsed = generator.parse_form_nodes(dict(batch_nodes=source['batch_nodes'],
                                                     aux_nodes='[]', node_overrides='{}'))
            entry = store.save(None, name, prefix, source, parsed, module.DEFAULT_YAML_PATH,
                               custom=base, sources=external, clock=lambda at=at: 1791100800 + at)
            if status == 'disabled':
                with patch('core.fixed_subscriptions.time.time', return_value=1791100800 + at):
                    store.action(entry['id'], 'disable')
            state['entries'].append(entry)
        assert len(store.list()) == count

    def health():
        endpoint = dict(version=2, subscriptions={})
        probe_url = 'https://private-probe.example/PRIVATE_FIXED_UX_PROBE'
        state['secrets'].extend((probe_url, 'PRIVATE_FIXED_UX_PROBE'))
        proxy = {'version': 2, 'global': dict(proxy_health.DEFAULT_PROBE, url=probe_url),
                 'subscriptions': {}}
        endpoint_modes = [('healthy', 'healthy'), ('suspect',), ('unhealthy',),
                          ('stale',), (), ('healthy', 'healthy', 'healthy')]
        proxy_modes = [(), ('healthy',), ('unhealthy',), ('unsupported', 'unsupported'),
                       (), ('healthy', 'healthy', 'healthy')]
        for index, saved in enumerate(state['entries']):
            entry = store.get(saved['id'])
            _, payload = store.snapshot(entry['id'])
            nodes = node_health.extract(payload)
            for data, kind, statuses in ((endpoint, node_health, endpoint_modes[index]),
                                         (proxy, proxy_health, proxy_modes[index])):
                if not statuses:
                    continue
                item = kind.empty_entry()
                item.update(mode='manual', last_check_at=1791100900)
                if index == 2:
                    item.update(mode='automatic', interval_seconds=900, next_check_at=1791101800)
                for node, status in zip(nodes, statuses):
                    fingerprint = node['fingerprint'] if status != 'stale' else 'a' * 64
                    state['secrets'].append(fingerprint)
                    if status in ('healthy', 'stale'):
                        record = dict(status='healthy', consecutive_failures=0, latency_ms=38,
                                      last_checked_at=1791100900, last_success_at=1791100900, error=None)
                    elif status == 'unsupported':
                        record = dict(status='unsupported', consecutive_failures=0, latency_ms=None,
                                      last_checked_at=1791100900, last_success_at=None,
                                      error='unsupported_config')
                    else:
                        record = dict(status=status, consecutive_failures=1 if status == 'suspect' else 3,
                                      latency_ms=None, last_checked_at=1791100900, last_success_at=None,
                                      error='connection_refused' if kind is node_health else 'proxy_failed')
                    item['nodes'][fingerprint] = record
                data['subscriptions'][entry['id']] = item
        assert node_health.valid_state(endpoint)
        assert proxy_health.valid_state(proxy)
        write_json(Path(module.DIR_STATE) / 'node_health.json', endpoint)
        write_json(Path(module.DIR_STATE) / 'proxy_health.json', proxy)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, value):
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            scenario = self.rfile.read(int(self.headers['Content-Length'])).decode()
            if scenario == 'empty':
                reset()
            elif scenario in ('populated', 'many'):
                seed(6 if scenario == 'populated' else 50)
            elif scenario == 'health':
                assert len(store.list()) == 6
                health()
            elif scenario in ('missing', 'corrupt'):
                for name in ('node_health.json', 'proxy_health.json'):
                    path = Path(module.DIR_STATE) / name
                    if scenario == 'missing':
                        path.unlink(missing_ok=True)
                    else:
                        path.write_bytes(b'PRIVATE_FIXED_UX_CORRUPT_STATE')
                        path.chmod(0o600)
                        state['secrets'].append('PRIVATE_FIXED_UX_CORRUPT_STATE')
            else:
                self.send_error(400)
                return
            state['scenario'] = scenario
            self.reply(metadata())

        def do_GET(self):
            self.reply(snapshot() if self.path == '/snapshot' else metadata())

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield dict(FIXED_UX_TEST_CONTROL=f'http://127.0.0.1:{server.server_port}/')
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
