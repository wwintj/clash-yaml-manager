"""Test-only HTTP source: production SSRF policy has no private-network override."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
from unittest.mock import patch


@contextmanager
def external_source_server(app_module=None):
    from core import source_fetch, node_probe, mihomo_probe, geoip
    from types import SimpleNamespace
    from core.mihomo_manager import ManagedMihomo
    state = {'mode':'initial', 'health':'success', 'proxy_engine':'not-installed', 'proxy_result':'success'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def do_POST(self):
            mode = self.rfile.read(int(self.headers['Content-Length'])).decode()
            if mode.startswith('https-') and app_module is not None:
                import json, os
                from pathlib import Path
                from core import https_metadata
                path = Path(app_module.BASE_DIR)/https_metadata.NAME
                path.unlink(missing_ok=True)
                configured = mode in ('https-configured','https-manual')
                for key,value in dict(APP_BIND_HOST='127.0.0.1' if configured else '0.0.0.0',
                    COOKIE_SECURE=configured,TRUST_PROXY_HEADERS=configured,
                    DOWNLOAD_URL_SCHEME='https' if configured else '',
                    DOWNLOAD_BASE_URL='https://example.com' if configured else '').items():
                    setattr(app_module,key,value)
                if mode == 'https-configured':
                    info=dict(version=1,managed=True,domain='example.com',configured_at='2026-09-30T00:00:00+00:00',
                        cert_mode='certbot-webroot',app_port=8899,nginx_config_sha256='a'*64,hook_sha256='b'*64,unit_sha256='c'*64,
                        managed_settings=https_metadata.managed_settings('example.com'),
                        previous_backup='/root/clash-yaml-manager-https-backup-20260930_000000.abcdef')
                    path.write_text(json.dumps(info));path.chmod(0o640)
                if mode == 'https-invalid':
                    path.write_text('{"SECRET_KEY":"PRIVATE_METADATA_SECRET", "email":"PRIVATE_EMAIL@example.com"}');path.chmod(0o640)
            elif mode.startswith('health-'):
                state['health'] = mode.removeprefix('health-')
            elif mode == 'proxy-run-error':
                state['proxy_result'] = 'engine-error'
            elif mode.startswith('proxy-engine-'):
                state['proxy_engine'] = mode.removeprefix('proxy-engine-')
            elif mode.startswith('proxy-'):
                state['proxy_result'] = mode.removeprefix('proxy-')
            else:
                state['mode'] = mode
            self.send_response(204); self.end_headers()

        def do_GET(self):
            if state['mode']=='failure': status, body = 503, b'PRIVATE failure details'
            elif state['mode']=='invalid': status, body = 200, b'invalid PRIVATE payload'
            else:
                name = 'Tokyo initial' if state['mode']=='initial' else 'London recovered'
                status = 200
                body = ('proxies:\n- name: '+name+'\n  type: vless\n  server: 192.0.2.1\n'
                        '  port: 443\n  uuid: test-only-credential\n').encode()
            self.send_response(status); self.send_header('Content-Length',str(len(body)))
            self.end_headers(); self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True); worker.start()
    from core import https_metadata
    import os
    original_metadata_read = https_metadata.read
    def fixture_metadata_read(directory):
        return original_metadata_read(directory,owner_uid=os.getuid(),group_gid=os.getgid())
    original=source_fetch._PinnedConnection
    class FixtureConnection(original):
        def connect(self):
            assert self.host=='external-source.test'
            assert self.addresses[0][2][0]=='8.8.8.8'
            self.addresses=[(socket.AF_INET,0,('127.0.0.1',server.server_port))]
            super().connect()
    def resolve(host,port,deadline):
        assert host in ('external-source.test','www.gstatic.com','probe.example')
        return [(socket.AF_INET,0,('8.8.8.8',port))]
    def probe(server, port):
        # Test-only deterministic TCP outcomes. Production has no destination bypass.
        return dict(latency_ms=37.6 if state['health']=='success' else None,
                    error=None if state['health']=='success' else 'connection_refused')
    def engine_status(self, **kwargs):
        return dict(status='COMPATIBLE' if state['proxy_engine']=='compatible' else 'NOT INSTALLED',
                    required='v1.19.31',
                    installed='v1.19.31' if state['proxy_engine']=='compatible' else None,
                    architecture='amd64',cpu_level='v2',preferred_build='amd64-v2',
                    build='amd64-v2' if state['proxy_engine']=='compatible' else None)
    def proxy_run(binary, nodes, settings, directory):
        if state['proxy_result']=='engine-error':
            raise mihomo_probe.ProbeEngineError('PRIVATE controller failure')
        results = {}
        for node in nodes:
            if state['proxy_result'] in ('middle-failure', 'two-failures'):
                failed = node['config']['server'] in (('8.8.4.4',) if state['proxy_result']=='middle-failure' else ('8.8.4.4','1.1.1.1'))
                kind = 'failure' if failed else 'success'
            else:
                kind={'success':'success','failure':'failure','unsupported':'unsupported'}[state['proxy_result']]
            results[node['fingerprint']]=dict(kind=kind,latency_ms=38 if kind=='success' else None,
                error={'success':None,'failure':'proxy_failed','unsupported':'unsupported_config'}[kind])
        return results
    class SyntheticGeoIPReader:
        def __init__(self, payload):
            if payload not in (b'SYNTHETIC:SG',b'SYNTHETIC:TW'): raise ValueError('PRIVATE invalid test database')
            self.code=payload.decode().split(':')[1]
        def metadata(self):return SimpleNamespace(database_type='Synthetic-Country',ip_version=6)
        def get(self,address):return {'country':{'iso_code':self.code}}
        def close(self):pass
    try:
        with patch.object(https_metadata,'read',fixture_metadata_read), patch.object(geoip,'open_reader',SyntheticGeoIPReader), patch.object(source_fetch,'_PinnedConnection',FixtureConnection), patch.object(source_fetch,'_resolve',resolve), patch.object(node_probe,'probe',probe), patch.object(ManagedMihomo,'status',engine_status), patch.object(mihomo_probe,'run',proxy_run):
            yield dict(EXTERNAL_TEST_URL=f'http://external-source.test:{server.server_port}/sub?token=PRIVATE',
                       EXTERNAL_TEST_CONTROL=f'http://127.0.0.1:{server.server_port}/')
    finally:
        server.shutdown(); worker.join(5); server.server_close()
