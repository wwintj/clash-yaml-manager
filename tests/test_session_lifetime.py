"""Real signed-cookie Flask clients on disposable state, with controlled clocks."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import importlib.util
import logging
import os
from pathlib import Path
import subprocess
import sys

import flask.sessions
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
import pytest

from conftest import ROOT, post
from core.session_config import lifetime_days


@pytest.mark.parametrize('value,expected', [(None,30),('1',1),('30',30),('3650',3650),('0001',1)])
def test_lifetime_valid(value, expected):
    assert lifetime_days(value) == expected


@pytest.mark.parametrize('value', ['', '0', '-1', '3651', '9999', '10000', '9'*5000,
    'NaN', 'inf', '1.0', '1e3', '+1', ' 30', '30 ', '３０', '١', '1\n',
    'PRIVATE_CONFIGURATION_VALUE', True, 30, float('nan'), [], {}])
def test_lifetime_rejects_invalid_without_echo(value):
    with pytest.raises(ValueError) as error:
        lifetime_days(value)
    assert str(error.value) == 'SESSION_LIFETIME_DAYS must be an integer from 1 to 3650.'


@pytest.mark.parametrize('value', ['0','3651','NaN','PRIVATE_CONFIGURATION_VALUE','9'*5000])
def test_invalid_configuration_stops_before_runtime_initialization(tmp_path, value):
    # Importing invalid configuration never reaches checkout runtime initialization.
    (tmp_path/'app.py').write_bytes((ROOT/'app.py').read_bytes())
    result = subprocess.run([sys.executable, '-c', 'import app'], cwd=tmp_path,
        env=dict(os.environ, PYTHONPATH=str(ROOT), SESSION_LIFETIME_DAYS=value),
        text=True, capture_output=True, timeout=10)
    assert result.returncode != 0
    assert result.stderr.strip() == 'SESSION_LIFETIME_DAYS must be an integer from 1 to 3650.'
    assert not any((tmp_path/name).exists() for name in ('state','logs','uploads','outputs','backups'))


@pytest.fixture
def clock(monkeypatch):
    current = [2_000_000_000]
    class ClockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(current[0], tz)
    monkeypatch.setattr(flask.sessions, 'datetime', ClockDateTime)
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda self: current[0])
    return current


def cookie(client):
    return client.get_cookie('session')


def serializer(web):
    return web.app.session_interface.get_signing_serializer(web.app)


@pytest.mark.parametrize('web,days', [({},30),({'SESSION_LIFETIME_DAYS':'1'},1),
    ({'SESSION_LIFETIME_DAYS':'3650'},3650)], indirect=['web'])
def test_actual_login_cookie_and_server_age_match(web, client, clock, days):
    assert web.SESSION_LIFETIME_DAYS == days
    assert web.app.permanent_session_lifetime == timedelta(days=days)
    response = post(client, '/login', {'password':'test 密码'})
    assert response.status_code == 302
    saved = cookie(client)
    assert saved.expires == datetime.fromtimestamp(clock[0], timezone.utc) + timedelta(days=days)
    assert saved.http_only and saved.same_site == 'Lax' and not saved.secure
    data = serializer(web).loads(saved.value, max_age=days*86400)
    assert data['logged_in'] and data['_permanent']
    assert 'password' not in data and 'test 密码' not in str(data)
    clock[0] += days*86400
    # Boundary accepted by both itsdangerous and the real request path.
    assert serializer(web).loads(saved.value, max_age=days*86400)['logged_in']
    boundary = web.app.test_client(); boundary.set_cookie('session', saved.value)
    assert b'id="process-form"' in boundary.get('/').data
    clock[0] += 1
    with pytest.raises(SignatureExpired):
        serializer(web).loads(saved.value, max_age=days*86400)
    stale = web.app.test_client(); stale.set_cookie('session', saved.value)
    assert b'id="password"' in stale.get('/').data
    assert stale.get('/api/csrf-token', headers={'X-CSRF-Refresh':'1'}).status_code == 401


@pytest.mark.parametrize('web', [{'COOKIE_SECURE':'true'}], indirect=True)
def test_https_cookie_attributes_and_refresh(web, client):
    response = post(client, '/login', {'password':'test 密码'}, base_url='https://localhost',
                    headers={'Referer':'https://localhost/'})
    assert response.status_code == 302
    saved = cookie(client)
    assert saved.secure and saved.http_only and saved.same_site == 'Lax'
    fresh = client.get('/api/csrf-token', base_url='https://localhost',
        headers={'X-CSRF-Refresh':'1','Origin':'https://localhost','Sec-Fetch-Site':'same-origin'})
    assert fresh.status_code == 200
    denied = client.post('/parse-nodes', base_url='https://localhost', data={'csrf_token':fresh.json['csrf_token']})
    assert denied.status_code == 400  # Existing HTTPS Referer check remains enabled.


@pytest.mark.parametrize('web,days', [({},30),({'SESSION_LIFETIME_DAYS':'3650'},3650)], indirect=['web'])
def test_activity_renews_expiration_and_signature(web, client, clock, days):
    post(client, '/login', {'password':'test 密码'})
    original = cookie(client).value
    clock[0] += days*86400 - 10
    active = client.get('/settings')
    assert active.status_code == 200
    renewed = cookie(client)
    assert renewed.value != original
    assert renewed.expires == datetime.fromtimestamp(clock[0], timezone.utc) + timedelta(days=days)
    clock[0] += 20
    with pytest.raises(SignatureExpired):
        serializer(web).loads(original, max_age=days*86400)
    assert client.get('/settings').status_code == 200
    assert web.app.config['SESSION_REFRESH_EACH_REQUEST'] is True


@contextmanager
def another_worker(web, name):
    # Re-import the installed app against the same private synthetic state/key.
    logger = logging.getLogger(); handlers, level = logger.handlers[:], logger.level
    spec = importlib.util.spec_from_file_location(name, Path(web.BASE_DIR)/'app.py')
    worker = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(worker)
        worker.app.config['TESTING'] = True
        yield worker
    finally:
        for handler in logger.handlers:
            if handler not in handlers:
                handler.close()
        logger.handlers[:], logger.level = handlers, level


@pytest.mark.parametrize('web', [{}, {'SESSION_LIFETIME_DAYS':'3650'}], indirect=True)
def test_shared_key_workers_and_restart_accept_existing_cookie(web, client):
    post(client, '/login', {'password':'test 密码'})
    saved = cookie(client).value
    auth = (Path(web.DIR_STATE)/'auth.json').read_bytes()
    for name in ('second_gunicorn_worker', 'restarted_application'):
        with another_worker(web, name) as worker:
            assert worker.app.secret_key == web.app.secret_key
            other = worker.app.test_client(); other.set_cookie('session',saved)
            assert other.get('/settings').status_code == 200
            assert other.get('/api/csrf-token',headers={'X-CSRF-Refresh':'1'}).status_code == 200
    assert (Path(web.DIR_STATE)/'auth.json').read_bytes() == auth


def test_pre_configuration_session_format_compatible(web, client, clock):
    auth = web.auth_store.read()
    # Existing v1.7 session keys, signed with the unchanged serializer and key.
    value = serializer(web).dumps(dict(_permanent=True, logged_in=True,
        auth_version=auth['auth_version'], auth_instance=auth['instance_id']))
    client.set_cookie('session', value)
    assert client.get('/settings').status_code == 200
    assert client.get('/api/csrf-token',headers={'X-CSRF-Refresh':'1'}).status_code == 200


@pytest.mark.parametrize('web', [{'SESSION_LIFETIME_DAYS':'3650'}], indirect=True)
def test_logout_current_browser_and_password_revocation(web, client):
    second = web.app.test_client()
    for browser in (client,second): post(browser,'/login',{'password':'test 密码'})
    assert post(client,'/logout').status_code == 302
    assert client.get('/api/csrf-token',headers={'X-CSRF-Refresh':'1'}).status_code == 401
    assert second.get('/settings').status_code == 200
    post(client,'/login',{'password':'test 密码'})
    # Every character of the non-empty replacement remains meaningful.
    replacement = ' 新密碼 Ω '
    post(client,'/change-password',dict(current_password='test 密码',new_password=replacement,
        confirm_password=replacement))
    for browser in (client,second):
        assert browser.get('/api/csrf-token',headers={'X-CSRF-Refresh':'1'}).status_code == 401
    assert web.auth_store.authenticate(replacement)
    assert not web.auth_store.authenticate(replacement.strip())


@pytest.mark.parametrize('field', ['auth_version','auth_instance'])
def test_auth_identity_rechecked_before_token_refresh(web, logged_in, field):
    with logged_in.session_transaction() as session:
        session[field] = 'invalid'
    response = logged_in.get('/api/csrf-token',headers={'X-CSRF-Refresh':'1'})
    assert response.status_code == 401 and 'csrf_token' not in response.json


def test_secret_key_change_rejects_old_login(web, logged_in, monkeypatch):
    saved = cookie(logged_in).value
    monkeypatch.setattr(web.app,'secret_key','different-synthetic-key')
    with pytest.raises(BadSignature): serializer(web).loads(saved)
    response = logged_in.get('/api/csrf-token',headers={'X-CSRF-Refresh':'1'})
    assert response.status_code == 401
    assert b'id="password"' in logged_in.get('/').data


@pytest.mark.parametrize('web,expected', [({},'30 days'),({'SESSION_LIFETIME_DAYS':'1'},'1 day'),
    ({'SESSION_LIFETIME_DAYS':'3650'},'3650 days')], indirect=['web'])
def test_runtime_reports_effective_lifetime(web, logged_in, expected):
    assert web.settings_runtime()['session_lifetime'] == expected
    assert f'data-runtime="session_lifetime">{expected}<' in logged_in.get('/settings').text
    # Projection follows the actual Flask lifetime rather than a stale env constant.
    web.app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=2)
    assert web.settings_runtime()['session_lifetime'] == '2 days'


def test_real_gunicorn_workers_and_process_restart_share_login(web, logged_in):
    """Two real worker processes and a new master accept the same signed cookie."""
    from concurrent.futures import ThreadPoolExecutor
    import socket
    import time
    from urllib.request import Request, urlopen
    # Test-copy instrumentation only, never add a worker PID endpoint to the app.
    app_file = Path(web.BASE_DIR)/'app.py'
    with app_file.open('a') as output:
        output.write('\n@app.after_request\ndef synthetic_worker_identity(response):\n'
                     '    if request.headers.get("X-Test-Probe") == "1": time.sleep(.05)\n'
                     '    response.headers["X-Test-Worker"] = str(os.getpid())\n    return response\n'
                     'with open(os.path.join(os.environ["SYNTHETIC_READY"],str(os.getpid())),"w"): pass\n')
    saved = cookie(logged_in).value
    state = (Path(web.DIR_STATE)/'auth.json').read_bytes()
    env = dict(os.environ, SECRET_KEY=web.app.secret_key,
               PYTHONPATH=str(ROOT), SESSION_LIFETIME_DAYS='30')
    observed = []
    for iteration in range(2):
        readiness = Path(web.BASE_DIR)/f'worker-ready-{iteration}'; readiness.mkdir()
        env['SYNTHETIC_READY'] = str(readiness)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0)); listener.listen(128)
            port = listener.getsockname()[1]
            error_log = Path(web.BASE_DIR)/'gunicorn-test.log'
            with error_log.open('ab') as errors:
                process = subprocess.Popen([sys.executable,'-m','gunicorn','--workers','2',
                    '--bind',f'fd://{listener.fileno()}','app:app'], cwd=web.BASE_DIR,
                    env=env, pass_fds=(listener.fileno(),), stdout=subprocess.DEVNULL, stderr=errors)
                try:
                    def check(_):
                        req = Request(f'http://127.0.0.1:{port}/api/csrf-token',
                            headers={'Cookie':'session='+saved,'X-CSRF-Refresh':'1','X-Test-Probe':'1'})
                        with urlopen(req,timeout=5) as response:
                            assert response.status == 200 and b'csrf_token' in response.read()
                            return response.headers['X-Test-Worker']
                    deadline = time.monotonic()+15
                    while len(list(readiness.iterdir())) != 2:
                        assert process.poll() is None and time.monotonic() < deadline
                        time.sleep(.05)
                    check(0)
                    with ThreadPoolExecutor(max_workers=8) as pool:
                        pids = set(pool.map(check,range(24)))
                    assert len(pids) == 2
                    observed.append(pids)
                finally:
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=5)
    assert observed[0].isdisjoint(observed[1])
    assert (Path(web.DIR_STATE)/'auth.json').read_bytes() == state
