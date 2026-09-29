"""Test-only HTTP source: production SSRF policy has no private-network override."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
from unittest.mock import patch


@contextmanager
def external_source_server():
    from core import source_fetch, node_probe
    state = {'mode':'initial', 'health':'success'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def do_POST(self):
            mode = self.rfile.read(int(self.headers['Content-Length'])).decode()
            if mode.startswith('health-'):
                state['health'] = mode.removeprefix('health-')
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
        assert host=='external-source.test'
        return [(socket.AF_INET,0,('8.8.8.8',port))]
    def probe(server, port):
        # Test-only deterministic TCP outcomes. Production has no destination bypass.
        return dict(latency_ms=37.6 if state['health']=='success' else None,
                    error=None if state['health']=='success' else 'connection_refused')
    try:
        with patch.object(source_fetch,'_PinnedConnection',FixtureConnection), patch.object(source_fetch,'_resolve',resolve), patch.object(node_probe,'probe',probe):
            yield dict(EXTERNAL_TEST_URL=f'http://external-source.test:{server.server_port}/sub?token=PRIVATE',
                       EXTERNAL_TEST_CONTROL=f'http://127.0.0.1:{server.server_port}/')
    finally:
        server.shutdown(); worker.join(5); server.server_close()
