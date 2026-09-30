"""Offline private-state, UI, transport and concurrency acceptance."""
import copy
import json
import os
from pathlib import Path
import socket
import ssl
import threading
import time
from types import SimpleNamespace

import pytest

from core import notification_events as events, notifications as module, telegram
from core.notifications import Notifications, NotificationError, defaults, validate
from core.state import write_json
from conftest import post
from test_deployment import deployment

TOKEN = '123456789:TEST_ONLY_BOT_TOKEN_abcdefghijklmnopqrstuvwxyz'
CHAT = '-1009876543210'
PREFS = {key: True for key in events.CATEGORIES}


@pytest.fixture
def authority(tmp_path):
    state = tmp_path / 'state'; state.mkdir(mode=0o700)
    calls = []
    sender = SimpleNamespace(send=lambda *args: calls.append(args) or 'success')
    return Notifications(state, clock=lambda: 1_800_000_000, transport=sender), calls


def configured(authority, enabled=True):
    store, calls = authority
    store.save(enabled, PREFS, TOKEN, CHAT)
    return store, calls


def event(kind='endpoint_health', transition='incident'):
    return events.Event(kind, transition, 'Office', 1, 8, 'success', 1_800_000_000)


def test_missing_read_off_no_files_or_transport(authority, monkeypatch):
    store, calls = authority
    monkeypatch.setattr(module, 'Telegram', lambda: pytest.fail('off initialized transport'))
    assert not store.status()['enabled'] and not store.enabled()
    assert store.deliver([event()]) is None
    assert list(store.state.iterdir()) == [] and calls == []


def test_credentials_private_retention_revision_mask_remove(authority):
    store, calls = configured(authority)
    raw = store.path.read_bytes(); data = json.loads(raw)
    assert data['version'] == 1 and data['revision'] == 1
    for path in (store.path, store.lock):
        info = path.stat(); assert info.st_mode & 0o777 == 0o600
        assert (info.st_uid, info.st_gid) == (os.geteuid(), os.getegid())
    assert TOKEN not in repr(store.status()) and CHAT not in repr(store.status())
    assert store.status()['chat_masked'] == '••••3210'
    store.save(True, PREFS); assert store.path.read_bytes() == raw
    preferences = dict(PREFS, scheduler=False)
    store.save(False, preferences)
    assert store._read()[0]['telegram'] == dict(enabled=False, bot_token=TOKEN, chat_id=CHAT)
    assert store.deliver([event()]) is None
    assert store.deliver(test=True) == 'success' and len(calls) == 1
    store.remove(); data = store._read()[0]
    assert data['revision'] == 3 and data['telegram'] == defaults()['telegram']
    assert data['events'] == preferences and store.deliver(test=True) == 'config'
    assert len(calls) == 1


@pytest.mark.parametrize('token', [' ', TOKEN+' ', 'https://example.test', '123:/bad', '123:short',
    '0:'+'A'*20, True, 123, '123:'+'A'*181, '123:'+'A'*20+'?secret', '123:'+'A'*20+'\n'])
def test_invalid_token_preserves_bytes(authority, token):
    store, _ = configured(authority); raw = store.path.read_bytes()
    with pytest.raises(NotificationError): store.save(True, PREFS, token, '')
    assert store.path.read_bytes() == raw


@pytest.mark.parametrize('chat', [' ', CHAT+' ', '@name', 'https://example.test', '0', '-0', '01', '+1',
    '9223372036854775808', '-9223372036854775809', '1\n', 123, True, '1.2'])
def test_invalid_chat_preserves_bytes(authority, chat):
    store, _ = configured(authority); raw = store.path.read_bytes()
    with pytest.raises(NotificationError): store.save(True, PREFS, '', chat)
    assert store.path.read_bytes() == raw


@pytest.mark.parametrize('chat', ['1', '-1', '1234', '-1234', '12345', CHAT, '9223372036854775807'])
def test_valid_numeric_destinations_masked(authority, chat):
    store, _ = authority; store.save(False, PREFS, TOKEN, chat)
    assert chat not in store.status()['chat_masked']
    assert store._read()[0]['telegram']['chat_id'] == chat


@pytest.mark.parametrize('path,value', [
    (('extra',), True), (('version',), True), (('version',), 2), (('revision',), True), (('revision',), -1),
    (('revision',), 2**63), (('telegram','extra'), 'SECRET'), (('telegram','enabled'), 'true'),
    (('telegram','bot_token'), 'invalid'), (('telegram','chat_id'), 123), (('events','extra'), True),
    (('events','scheduler'), 1), (('delivery','extra'), 'SECRET'), (('delivery','last_result'), 'SECRET'),
    (('delivery','last_error'), 'https://SECRET'), (('delivery','last_attempt_at'), True),
    (('delivery','last_attempt_at'), float('nan')), (('delivery','last_attempt_at'), -1),
    (('delivery','last_success_at'), float('inf'))])
def test_strict_v1_corrupt_no_repair_no_send(authority, path, value):
    store, calls = authority; data = defaults(); target = data
    for key in path[:-1]: target = target[key]
    target[path[-1]] = value
    write_json(store.path, data); raw = store.path.read_bytes()
    with pytest.raises(NotificationError): store.status()
    with pytest.raises(NotificationError): store.save(False, PREFS)
    assert store.deliver([event()]) is None and store.deliver(test=True) == 'config'
    assert store.path.read_bytes() == raw and calls == []


@pytest.mark.parametrize('raw', [b'{}', b'PRIVATE bad JSON', b'{"version":1,"version":1}', b'[]', b'"SECRET"', b'x'*65537])
def test_malformed_and_duplicate_state(authority, raw):
    store, calls = authority; store.path.write_bytes(raw); store.path.chmod(0o600)
    with pytest.raises(NotificationError): store.status()
    assert store.deliver(test=True) == 'config' and not calls and store.path.read_bytes() == raw


@pytest.mark.parametrize('name', ['notifications.json', 'notifications.lock'])
@pytest.mark.parametrize('kind', ['symlink', 'broken-link', 'fifo', 'directory', 'public', 'readonly', 'owner', 'group'])
def test_unsafe_files_rejected_nonblocking_without_repair(authority, monkeypatch, name, kind):
    store, calls = authority; path = store.state / name
    if kind in ('symlink', 'broken-link'):
        target = store.state / 'target'
        if kind == 'symlink': write_json(target, defaults())
        path.symlink_to(target)
    elif kind == 'fifo': os.mkfifo(path, 0o600)
    elif kind == 'directory': path.mkdir(mode=0o700)
    else:
        write_json(path, defaults()); path.chmod(0o644 if kind == 'public' else 0o400 if kind == 'readonly' else 0o600)
    if kind in ('owner', 'group'):
        monkeypatch.setattr(module.os, 'geteuid' if kind == 'owner' else 'getegid', lambda: 99999999)
    before = path.lstat(); started = time.monotonic()
    with pytest.raises(NotificationError): store.status()
    assert store.deliver(test=True) == 'config' and not calls
    with pytest.raises(NotificationError): store.save(False, PREFS)
    assert time.monotonic() - started < 1
    assert path.lstat().st_mode == before.st_mode


@pytest.mark.parametrize('stage', ['before', 'after'])
@pytest.mark.parametrize('existing', [True, False])
def test_atomic_failure_restores_old_credentials(authority, monkeypatch, stage, existing):
    store, _ = configured(authority) if existing else authority
    raw = store.path.read_bytes() if existing else None
    original = module.write_json
    def failed(path, value):
        if stage == 'after': original(path, value)
        raise OSError('PRIVATE write error')
    monkeypatch.setattr(module, 'write_json', failed)
    with pytest.raises(NotificationError): store.save(False, PREFS, '999:'+ 'B'*30, '123456')
    assert (store.path.read_bytes() if store.path.exists() else None) == raw
    assert not list(store.state.glob('.notifications.json-*'))


@pytest.mark.parametrize('result', ['success', *telegram.ERRORS, 'PRIVATE raw failure'])
def test_delivery_safe_bookkeeping_and_failure_retains_config(authority, result):
    store, calls = configured(authority)
    store.transport.send = lambda *args: calls.append(args) or result
    expected = result if result in ('success', *telegram.ERRORS) else 'network'
    assert store.deliver(test=True) == expected and len(calls) == 1
    data = store._read()[0]
    assert data['revision'] == 1 and data['telegram']['bot_token'] == TOKEN
    assert data['delivery']['last_attempt_at'] == 1_800_000_000
    assert data['delivery']['last_result'] == ('success' if expected == 'success' else 'failure')
    assert data['delivery']['last_error'] == (None if expected == 'success' else expected)
    assert data['delivery']['last_success_at'] == (1_800_000_000 if expected == 'success' else None)
    assert 'PRIVATE' not in repr(data['delivery'])
    assert calls[0][2].startswith('Clash YAML Manager test notification.')


@pytest.mark.parametrize('mutation', ['remove', 'save'])
def test_config_race_send_unlocked_and_newer_revision_wins(authority, mutation):
    store, calls = configured(authority); started, resume = threading.Event(), threading.Event()
    def paused(*args):
        calls.append(args); started.set(); assert resume.wait(3); return 'success'
    store.transport.send = paused
    results = []; thread = threading.Thread(target=lambda: results.append(store.deliver(test=True)))
    thread.start(); assert started.wait(2)
    try:
        if mutation == 'remove': Notifications(store.state).remove()
        else: Notifications(store.state).save(False, dict(PREFS, scheduler=False), '999:'+'B'*30, '1234567')
        raw = store.path.read_bytes()
        assert store.status()['enabled'] is False
    finally: resume.set(); thread.join(3)
    assert results == ['success'] and store.path.read_bytes() == raw and len(calls) == 1
    assert json.loads(raw)['revision'] == 2


def test_delivery_write_failure_no_retry(authority, monkeypatch):
    store, calls = configured(authority); raw = store.path.read_bytes()
    monkeypatch.setattr(store, '_commit', lambda *args: (_ for _ in ()).throw(NotificationError()))
    assert store.deliver([event()]) == 'success'
    assert len(calls) == 1 and store.path.read_bytes() == raw


def test_category_disabled_and_transport_exception_safe(authority):
    store, calls = configured(authority); store.save(True, dict(PREFS, endpoint_health=False))
    assert store.deliver([event()]) is None and not calls
    def fail(*args): raise RuntimeError(TOKEN + CHAT)
    store.transport.send = fail
    assert store.deliver(test=True) == 'network'
    assert store.status()['delivery']['last_error'] == 'network'


@pytest.fixture
def connection(monkeypatch):
    state = dict(status=200, body=b'{"ok":true}', calls=[], closed=0, timeouts=[])
    class Socket:
        def settimeout(self, value): state['timeouts'].append(value)
        def shutdown(self, how): state['shutdown'] = True
    class Response:
        status = 200
        length = None
        def isclosed(self): return not state['body']
        def read1(self, limit):
            part = state['body'][:limit]; state['body'] = state['body'][limit:]; return part
    class Connection:
        def __init__(self, deadline): self.sock = Socket()
        def request(self, *args, **kwargs):
            state['calls'].append((args, kwargs))
            if state.get('error'): raise state['error']
        def getresponse(self):
            response = Response(); response.status = state['status']; return response
        def close(self): state['closed'] += 1
    monkeypatch.setattr(telegram, 'DirectConnection', Connection)
    return state


@pytest.mark.parametrize('status', [301, 302, 307, 400, 401, 403, 429, 500, 503])
def test_transport_http_no_redirect_body_read(connection, status):
    connection['status'] = status; connection['body'] = b'PRIVATE CHAT response'
    assert telegram.Telegram().send(TOKEN, CHAT, 'test') == 'http'
    assert len(connection['calls']) == 1 and connection['body'] == b'PRIVATE CHAT response'
    assert connection['closed'] == 1


@pytest.mark.parametrize('body,result', [(b'{"ok":true}', 'success'), (b'{"ok":false,"description":"PRIVATE"}', 'api'),
    (b'{"ok":1}', 'invalid_response'), (b'{}', 'invalid_response'), (b'[]', 'invalid_response'),
    (b'PRIVATE non JSON', 'invalid_response'), (b'\xff', 'invalid_response'), (b'x'*65537, 'invalid_response'),
    (b'{"ok":true,"ok":false}', 'invalid_response'), (b'{"ok":true,"value":NaN}', 'invalid_response')])
def test_transport_response_validation_and_bounded_read(connection, body, result):
    connection['body'] = body
    assert telegram.Telegram().send(TOKEN, CHAT, 'test') == result
    args, kwargs = connection['calls'][0]
    assert args == ('POST', '/bot'+TOKEN+'/sendMessage')
    assert json.loads(kwargs['body']) == dict(chat_id=CHAT, text='test', disable_web_page_preview=True)
    assert all(0 < value <= 5 for value in connection['timeouts']) and connection['closed'] == 1


@pytest.mark.parametrize('error,result', [(TimeoutError('SECRET'), 'timeout'), (ssl.SSLError('SECRET'), 'tls'),
    (socket.gaierror('SECRET'), 'network'), (OSError('SECRET'), 'network')])
def test_transport_errors_safe(connection, error, result):
    connection['error'] = error
    assert telegram.Telegram().send(TOKEN, CHAT, 'test') == result and connection['closed'] == 1


def test_transport_fixed_host_verified_context_no_proxies(monkeypatch):
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'): monkeypatch.setenv(name, 'http://SECRET@example.test')
    connection = telegram.DirectConnection(time.monotonic()+5)
    assert connection.host == 'api.telegram.org' and connection.port == 443
    assert connection._context.check_hostname and connection._context.verify_mode == ssl.CERT_REQUIRED
    assert connection._tunnel_host is None
    connection.close()


def test_dns_deadline_bounded_without_late_post(monkeypatch):
    done = threading.Event(); seen = []
    def blocked(host, port, **kwargs): seen.append((host, port)); done.wait(1); return []
    monkeypatch.setattr(telegram.socket, 'getaddrinfo', blocked)
    start = time.monotonic()
    try:
        with pytest.raises(TimeoutError): telegram.resolve(start+0.03)
        assert time.monotonic()-start < 0.3 and seen == [('api.telegram.org',443)]
    finally: done.set()


@pytest.mark.parametrize('field,value', [('token','https://example.test'), ('chat','@name'), ('text',''), ('text','x'*3501)])
def test_transport_bad_input_no_connection(monkeypatch, field, value):
    monkeypatch.setattr(telegram, 'DirectConnection', lambda *args: pytest.fail('invalid input connected'))
    args = dict(token=TOKEN, chat=CHAT, text='test'); args[field] = value
    assert telegram.Telegram().send(**args) == 'config'


def form(**values):
    return dict(enabled='on', bot_token=TOKEN, chat_id=CHAT, **{key:'on' for key in PREFS}, **values)


@pytest.mark.parametrize('path', ['/settings/notifications', '/settings/notifications/test', '/settings/notifications/remove'])
def test_notification_routes_auth_csrf_post_only(web, logged_in, monkeypatch, path):
    monkeypatch.setattr(telegram.Telegram, 'send', lambda *args: pytest.fail('unauthorized send'))
    anonymous = web.app.test_client()
    assert anonymous.get('/settings').status_code == 302
    assert anonymous.post(path).status_code in (302,303)
    assert logged_in.get(path).status_code == 405
    assert logged_in.post(path, data=form()).status_code == 303
    assert not (Path(web.DIR_STATE)/'notifications.json').exists()


def test_settings_default_get_zero_network_no_state(web, logged_in, monkeypatch):
    from core import source_fetch, node_probe, mihomo_probe
    import subprocess
    def forbidden(*args, **kwargs): pytest.fail('Settings GET performed network/subprocess')
    for obj, attr in [(socket,'getaddrinfo'),(socket,'create_connection'),(telegram.Telegram,'send'),
                      (source_fetch,'fetch'),(node_probe,'probe'),(mihomo_probe,'run'),(subprocess,'run')]:
        monkeypatch.setattr(obj,attr,forbidden)
    response = logged_in.get('/settings'); html = response.get_data(as_text=True)
    assert response.status_code == 200 and 'id="notifications"' in html and 'href="#notifications"' in html
    assert 'Disabled' in html and 'Not configured' in html
    assert response.headers['Cache-Control'] == 'no-store' and response.headers['Referrer-Policy'] == 'no-referrer'
    assert not list(Path(web.DIR_STATE).glob('notifications.*'))


def test_settings_save_test_remove_secret_absence_and_unrelated_stability(web, logged_in, monkeypatch, caplog):
    from test_fixed_views import create
    from core import node_health
    entry = create(web, logged_in); state = Path(web.DIR_STATE)
    node_health.NodeHealth(web.fixed_subscriptions).settings(entry['id'], 'manual')
    web.proxy_health.settings(entry['id'], 'manual', True)
    # Include auxiliary private fixtures without asking Settings to parse them.
    for name in ('temporary_links.json', 'auth.json', 'geoip-preservation.mmdb'):
        path = state/name
        if not path.exists(): path.write_bytes(b'PRIVATE preserved'); path.chmod(0o600)
    (Path(web.BASE_DIR)/'HTTPS_DEPLOYMENT.json').write_bytes(b'PRIVATE HTTPS fixture')
    def snapshot():
        return {str(path.relative_to(Path(web.BASE_DIR))): path.read_bytes() for path in Path(web.BASE_DIR).rglob('*')
                if path.is_file() and path.suffix != '.lock' and path.name != 'notifications.json'
                and '__pycache__' not in path.parts and 'logs' not in path.parts}
    before = snapshot(); calls = []
    monkeypatch.setattr(telegram.Telegram, 'send', lambda self,*args: calls.append(args) or 'success')
    assert post(logged_in, '/settings/notifications', form()).status_code == 303 and not calls
    html = logged_in.get('/settings').get_data(as_text=True)
    assert TOKEN not in html and CHAT not in html and entry['token'] not in html
    assert '••••3210' in html and 'id="telegram-token"' in html and 'type="password"' in html
    assert 'name="bot_token" class="form-control terminal-input" type="password" autocomplete="new-password" maxlength="201" value=""' in html
    raw = (state/'notifications.json').read_bytes()
    invalid = form(); invalid['bot_token'] = 'https://PRIVATE_INVALID'; invalid['chat_id']='@PRIVATE'
    assert post(logged_in,'/settings/notifications',invalid).status_code == 303
    assert (state/'notifications.json').read_bytes() == raw
    assert 'PRIVATE_INVALID' not in logged_in.get('/settings').get_data(as_text=True)
    assert post(logged_in,'/settings/notifications/test', {'bot_token':'UNSAVED_SECRET','chat_id':'1'}).status_code == 303
    assert len(calls) == 1 and calls[0][:2] == (TOKEN,CHAT) and 'UNSAVED' not in calls[0][2]
    monkeypatch.setattr(telegram.Telegram,'send',lambda *args: (_ for _ in ()).throw(RuntimeError(TOKEN+CHAT+'PRIVATE_BODY')))
    assert post(logged_in,'/settings/notifications/test').status_code == 303
    html = logged_in.get('/settings').get_data(as_text=True)
    assert 'Telegram test failed.' in html and 'network' in html and 'Enabled' in html
    assert post(logged_in,'/settings/notifications/remove').status_code == 303
    data = Notifications(state)._read()[0]
    assert data['telegram'] == defaults()['telegram'] and data['events'] == PREFS
    assert snapshot() == before
    for secret in (TOKEN,CHAT,entry['token'],'PRIVATE_BODY','UNSAVED_SECRET','test-only-fixed-secret'):
        assert secret not in html and secret not in caplog.text


def test_corrupt_settings_isolated_no_echo_no_repair(web, logged_in):
    path = Path(web.DIR_STATE)/'notifications.json'; path.write_bytes(b'PRIVATE corrupt token'); path.chmod(0o600)
    html = logged_in.get('/settings').get_data(as_text=True)
    assert 'Configuration unavailable' in html and 'PRIVATE corrupt token' not in html
    for section in ('overview','geoip','health','runtime'): assert 'id="'+section+'"' in html
    assert 'id="notification-settings"' not in html and path.read_bytes() == b'PRIVATE corrupt token'


def test_notifications_update_private_backup_and_uninstall_preserved(deployment):
    installed, source, service, log, env, run = deployment
    state = installed/'state'; state.mkdir(mode=0o700,exist_ok=True); state.chmod(0o700)
    path = state/'notifications.json'; data = defaults(); data['telegram'].update(bot_token=TOKEN,chat_id=CHAT)
    write_json(path,data); raw = path.read_bytes()
    result = run(); assert result.returncode == 0, result.stdout+result.stderr
    assert path.read_bytes() == raw and path.stat().st_mode & 0o777 == 0o600
    backup = next(installed.parent.glob('upgrade-backup-*'))/'state/notifications.json'
    assert backup.read_bytes() == raw and backup.stat().st_mode & 0o777 == 0o600
    result = run('uninstall.sh',input_text='y\n\n'); assert result.returncode == 0, result.stdout+result.stderr
    backup = next(installed.parent.glob('uninstall-backup-*'))/'state/notifications.json'
    assert backup.read_bytes() == raw and backup.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('part', ['headers', 'body'])
def test_total_http_deadline_interrupts_slow_headers_and_close_response(monkeypatch, part):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            try:
                headers = b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\n'
                if part == 'body': self.wfile.write(headers); self.wfile.flush()
                for byte in (headers if part == 'headers' else b'') + b'{"ok":true}':
                    self.wfile.write(bytes([byte])); self.wfile.flush(); time.sleep(0.01)
            except OSError: pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True); worker.start()
    monkeypatch.setattr(telegram,'TIMEOUT',0.08)
    monkeypatch.setattr(telegram,'resolve',lambda deadline:[(socket.AF_INET,socket.SOCK_STREAM,0,'',('127.0.0.1',server.server_port))])
    # TLS handshake is a controlled double. Production's verified context is
    # separately asserted; this local HTTP server exercises real socket deadlines.
    def wrapped(self,sock,**kwargs):
        assert kwargs['server_hostname']=='api.telegram.org'
        assert self.check_hostname and self.verify_mode==ssl.CERT_REQUIRED
        return sock
    monkeypatch.setattr(ssl.SSLContext,'wrap_socket',wrapped)
    start=time.monotonic()
    try:
        assert telegram.Telegram().send(TOKEN,CHAT,'test')=='timeout'
        assert time.monotonic()-start<0.4
    finally:
        server.shutdown();worker.join(2);server.server_close()


def test_connection_close_success_retains_response_socket(monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200);self.send_header('Content-Length','11');self.end_headers();self.wfile.write(b'{"ok":true}')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    monkeypatch.setattr(telegram,'resolve',lambda deadline:[(socket.AF_INET,socket.SOCK_STREAM,0,'',('127.0.0.1',server.server_port))])
    monkeypatch.setattr(ssl.SSLContext,'wrap_socket',lambda self,sock,**kw:sock)
    try: assert telegram.Telegram().send(TOKEN,CHAT,'test')=='success'
    finally: server.shutdown();worker.join(2);server.server_close()


@pytest.mark.parametrize('enabled,prefs,token,chat', [(True,PREFS,'',''), (1,PREFS,TOKEN,CHAT),
    (True,dict(PREFS,scheduler=1),TOKEN,CHAT),(False,{},TOKEN,CHAT),
    (False,dict(PREFS,custom_endpoint=True),TOKEN,CHAT)])
def test_invalid_effective_configuration_no_creation(authority,enabled,prefs,token,chat):
    store,calls=authority
    with pytest.raises(NotificationError): store.save(enabled,prefs,token,chat)
    assert not store.path.exists() and not calls


def _notification_save_worker(directory, chat, barrier, results):
    try:
        barrier.wait(timeout=8)
        Notifications(directory).save(False, PREFS, '', chat)
        results.put(True)
    except Exception:
        results.put(False)


def test_multiworker_saves_serialized_no_partial_credentials(authority):
    import multiprocessing
    store,_=configured(authority)
    context=multiprocessing.get_context('spawn'); barrier=context.Barrier(2); results=context.Queue()
    workers=[context.Process(target=_notification_save_worker,args=(str(store.state),chat,barrier,results))
             for chat in ('1234567','7654321')]
    for worker in workers: worker.start()
    try:
        assert [results.get(timeout=12) for _ in workers]==[True,True]
    finally:
        for worker in workers:
            worker.join(4)
            if worker.is_alive(): worker.terminate();worker.join(2)
    assert all(worker.exitcode==0 for worker in workers)
    data=store._read()[0]
    assert data['revision']==3 and data['telegram']['bot_token']==TOKEN
    assert data['telegram']['chat_id'] in ('1234567','7654321') and not data['telegram']['enabled']


def test_older_delivery_cannot_overwrite_newer_attempt(authority):
    store,calls=configured(authority); started,resume=threading.Event(),threading.Event()
    def paused(*args): started.set();assert resume.wait(3);return 'network'
    store.transport.send=paused
    thread=threading.Thread(target=lambda:store.deliver(test=True));thread.start();assert started.wait(2)
    try:
        newer=Notifications(store.state,clock=lambda:1_800_000_001,transport=SimpleNamespace(send=lambda *args:'success'))
        assert newer.deliver(test=True)=='success'; raw=store.path.read_bytes()
    finally: resume.set();thread.join(3)
    assert store.path.read_bytes()==raw and store.status()['delivery']['last_result']=='success'


@pytest.mark.parametrize('invalid', [{'enabled':'true'}, {'scheduler':'false'}, {'endpoint':'https://PRIVATE'},
    {'chat_id':'@PRIVATE'}, {'bot_token':'PRIVATE_INVALID'}])
def test_invalid_form_safe_no_echo_unchanged(web,logged_in,invalid):
    values=form();assert post(logged_in,'/settings/notifications',values).status_code==303
    path=Path(web.DIR_STATE)/'notifications.json';raw=path.read_bytes(); values.update(invalid)
    assert post(logged_in,'/settings/notifications',values).status_code==303
    assert path.read_bytes()==raw
    html=logged_in.get('/settings').get_data(as_text=True)
    assert 'PRIVATE' not in html
