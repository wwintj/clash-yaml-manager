"""All networking is loopback in tests, behind DNS + pinned-socket doubles."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import ssl
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from core import source_fetch as fetcher
from core.source_errors import SourceError


@pytest.fixture
def network(monkeypatch):
    routes, seen, connections, resolutions = {}, [], [], []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def do_GET(self):
            seen.append((self.path, dict(self.headers)))
            rule = routes.get(self.path, {})
            try:
                if rule.get('slow_headers'):
                    for byte in b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok':
                        self.wfile.write(bytes([byte])); self.wfile.flush(); time.sleep(.01)
                    return
                self.send_response(rule.get('status', 200))
                payload = rule.get('body', b'valid payload')
                if not rule.get('stream'):
                    self.send_header('Content-Length', str(rule.get('length', len(payload))))
                for key, value in rule.get('headers', {}).items(): self.send_header(key, value)
                self.end_headers()
                if rule.get('delay'): time.sleep(.2)
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    original_socket = socket.socket
    class PinnedSocket(original_socket):
        def connect(self, address):
            connections.append(address)
            assert address[0] == '8.8.8.8', 'transport must receive the validated numeric address'
            return super().connect(('127.0.0.1', server.server_port))
    def dns(args, **kwargs):
        host, port = json.loads(kwargs['input']); resolutions.append(host)
        assert kwargs['timeout'] <= fetcher.TOTAL_TIMEOUT
        addresses = ['127.0.0.1'] if host in ('private.example', 'localhost') else ['8.8.8.8']
        if host == 'mixed.example': addresses.append('10.0.0.1')
        return SimpleNamespace(stdout=json.dumps([(socket.AF_INET, socket.SOCK_STREAM, 6, '', [ip, port]) for ip in addresses]))
    monkeypatch.setattr(fetcher.subprocess, 'run', dns)
    monkeypatch.setattr(fetcher.socket, 'socket', PinnedSocket)
    # A second hostname lookup in the request process is forbidden.
    monkeypatch.setattr(fetcher.socket, 'getaddrinfo', lambda *a, **kw: pytest.fail('second DNS lookup'))
    yield SimpleNamespace(routes=routes, seen=seen, connections=connections, resolutions=resolutions,
                          url=f'http://source.example:{server.server_port}', port=server.server_port)
    server.shutdown(); worker.join(2); server.server_close()


def test_pinned_connection_original_host_minimal_headers_proxy_isolation(network, monkeypatch):
    for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
        monkeypatch.setenv(key, 'http://private.example:9999')
    assert fetcher.fetch(network.url + '/?token=PRIVATE') == b'valid payload'
    assert network.resolutions == ['source.example']
    assert network.connections == [('8.8.8.8', network.port)]
    path, headers = network.seen[0]
    assert path == '/?token=PRIVATE'
    assert headers['Host'] == f'source.example:{network.port}'
    assert headers['Connection'] == 'close'
    assert set(headers) == {'Host','Accept-Encoding','User-Agent','Accept','Connection'}


@pytest.mark.parametrize('host', ['127.0.0.1','10.0.0.1','172.16.1.1','192.168.1.1',
    '[::1]','[fe80::1]','[ff02::1]','[::]','0.0.0.0','169.254.169.254',
    '224.0.0.1','240.0.0.1','192.0.2.1','198.51.100.1','203.0.113.1',
    '[::ffff:127.0.0.1]','[2002:7f00:1::]','private.example','mixed.example','localhost'])
def test_non_global_and_mixed_dns_rejected(network, host):
    with pytest.raises(SourceError, match='not public'): fetcher.fetch(f'http://{host}/')
    assert network.connections == []


@pytest.mark.parametrize('url', ['file:///etc/passwd','ftp://source.example/', 'gopher://source.example/',
    'data:text/plain,secret','unix:///socket', 'http://user:PRIVATE@source.example/',
    'https://:PRIVATE@source.example/', 'http://source.example:0/',
    'http://source.example/\r\nAuthorization:PRIVATE','http://[fe80::1%25en0]/'])
def test_invalid_urls(network, url):
    with pytest.raises(SourceError) as error: fetcher.fetch(url)
    assert 'PRIVATE' not in str(error.value)
    assert network.connections == []


@pytest.mark.parametrize('status', [301,302,303,307,308])
def test_relative_and_public_redirects(network, status):
    network.routes['/one'] = {'status':status, 'headers':{'Location':'/two'}}
    network.routes['/two'] = {'status':status, 'headers':{'Location':'http://other.example/three'}}
    assert fetcher.fetch(network.url + '/one') == b'valid payload'
    assert network.resolutions == ['source.example','source.example','other.example']
    assert len(network.connections) == 3


@pytest.mark.parametrize('target', ['http://127.0.0.1/','http://private.example/',
    'http://user:SECRET@source.example/', 'file:///etc/passwd'])
def test_redirect_revalidates(network, target):
    network.routes['/'] = {'status':302,'headers':{'Location':target}}
    with pytest.raises(SourceError): fetcher.fetch(network.url)
    assert len(network.connections) == 1


def test_redirect_limit(network):
    network.routes['/'] = {'status':302,'headers':{'Location':'/'}}
    with pytest.raises(SourceError, match='redirect'): fetcher.fetch(network.url)
    assert len(network.connections) == 4


@pytest.mark.parametrize('status', [201,204,403,404,500])
def test_status_never_echoes_body(network, status):
    network.routes['/'] = {'status':status,'body':b'SECRET response'}
    with pytest.raises(SourceError, match=f'HTTP {status}') as error: fetcher.fetch(network.url)
    assert 'SECRET' not in str(error.value)


@pytest.mark.parametrize('stream', [True, False])
def test_response_limit(network, monkeypatch, stream):
    monkeypatch.setattr(fetcher, 'MAX_PAYLOAD', 64)
    network.routes['/'] = {'stream':stream,'body':b'x'*65}
    with pytest.raises(SourceError, match='too large'): fetcher.fetch(network.url)


@pytest.mark.parametrize('case', ['delay','slow_headers'])
def test_total_budget_includes_slow_headers_and_body(network, monkeypatch, case):
    monkeypatch.setattr(fetcher, 'TOTAL_TIMEOUT', .05)
    network.routes['/'] = {case:True}
    start = time.monotonic()
    with pytest.raises(SourceError, match='timed out'): fetcher.fetch(network.url)
    assert time.monotonic() - start < .5


def test_dns_timeout_and_error_are_sanitized(monkeypatch):
    for exception, code in [(subprocess.TimeoutExpired(['PRIVATE'], 1), 'timeout'),
                            (subprocess.CalledProcessError(1, ['PRIVATE']), 'dns')]:
        def failed(*a, **kw): raise exception
        monkeypatch.setattr(fetcher.subprocess, 'run', failed)
        with pytest.raises(SourceError) as error: fetcher.fetch('https://source.example/?token=PRIVATE')
        assert error.value.code == code and 'PRIVATE' not in str(error.value)


def test_tls_requires_ca_and_original_sni(network, monkeypatch):
    context = ssl.create_default_context()
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    seen = []
    def wrap(sock, server_hostname):
        seen.append(server_hostname)
        raise ssl.SSLCertVerificationError('PRIVATE certificate details')
    monkeypatch.setattr(context, 'wrap_socket', wrap)
    monkeypatch.setattr(fetcher.ssl, 'create_default_context', lambda: context)
    with pytest.raises(SourceError, match='TLS verification failed') as error:
        fetcher.fetch(network.url.replace('http:', 'https:') + '/?secret=PRIVATE')
    assert seen == ['source.example'] and 'PRIVATE' not in str(error.value)


def test_truncated_response_and_encoding(network):
    network.routes['/'] = {'length':200, 'body':b'short'}
    with pytest.raises(SourceError): fetcher.fetch(network.url)
    network.routes['/'] = {'headers':{'Content-Encoding':'gzip'}}
    with pytest.raises(SourceError, match='encoding'): fetcher.fetch(network.url)


def test_connect_timeout_closes_socket(monkeypatch):
    events = []
    class FakeSocket:
        def settimeout(self, value): events.append(('timeout',value))
        def connect(self, address): raise TimeoutError('PRIVATE')
        def close(self): events.append('closed')
    monkeypatch.setattr(fetcher.socket, 'socket', lambda *args: FakeSocket())
    with pytest.raises(SourceError, match='timed out'): fetcher.fetch('http://8.8.8.8/')
    assert events[0][1] <= 5 and events[-1] == 'closed'


@pytest.mark.parametrize('address', ['8.8.8.8','2606:4700:4700::1111'])
def test_global_literal_resolution_does_not_use_dns(monkeypatch,address):
    monkeypatch.setattr(fetcher.subprocess,'run',lambda *a,**kw: pytest.fail('literal address queried DNS'))
    approved=fetcher._resolve(address,443,time.monotonic()+15)
    assert approved[0][2]==(address,443)
