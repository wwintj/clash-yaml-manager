"""Test-only HTTP source: production SSRF policy has no private-network override."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
from unittest.mock import patch


@contextmanager
def external_source_server():
    from core import source_fetch, node_probe, mihomo_probe, geoip
    from types import SimpleNamespace
    from core.mihomo_manager import ManagedMihomo
    state = {'mode':'initial', 'health':'success', 'proxy_engine':'not-installed', 'proxy_result':'success'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def do_POST(self):
            mode = self.rfile.read(int(self.headers['Content-Length'])).decode()
            if mode.startswith('health-'):
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
        with patch.object(geoip,'open_reader',SyntheticGeoIPReader), patch.object(source_fetch,'_PinnedConnection',FixtureConnection), patch.object(source_fetch,'_resolve',resolve), patch.object(node_probe,'probe',probe), patch.object(ManagedMihomo,'status',engine_status), patch.object(mihomo_probe,'run',proxy_run):
            yield dict(EXTERNAL_TEST_URL=f'http://external-source.test:{server.server_port}/sub?token=PRIVATE',
                       EXTERNAL_TEST_CONTROL=f'http://127.0.0.1:{server.server_port}/')
    finally:
        server.shutdown(); worker.join(5); server.server_close()
