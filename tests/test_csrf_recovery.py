import json
from pathlib import Path
import re
import time

import pytest
from itsdangerous import TimestampSigner, URLSafeTimedSerializer

from conftest import LINK, post


def token(client):
    return re.search(r'name="csrf_token" value="([^"]+)"', client.get('/').get_data(as_text=True))[1]


def expired_token(web, client, monkeypatch):
    token(client)
    with client.session_transaction() as session:
        raw = session['csrf_token']
    with monkeypatch.context() as patch:
        patch.setattr(TimestampSigner, 'get_timestamp', lambda self: int(time.time()) - 3601)
        return URLSafeTimedSerializer(web.app.secret_key, salt='wtf-csrf-token').dumps(raw)


def test_effective_csrf_lifetime_stays_finite(web):
    assert web.app.config['WTF_CSRF_TIME_LIMIT'] == 3600
    assert web.app.config['WTF_CSRF_ENABLED'] is True
    assert web.app.config['WTF_CSRF_CHECK_DEFAULT'] is True
    assert web.app.config['PERMANENT_SESSION_LIFETIME'].total_seconds() == 30 * 86400
    assert web.app.config['SESSION_REFRESH_EACH_REQUEST'] is True


@pytest.mark.parametrize('kind', ['invalid', 'expired', 'missing'])
def test_logged_in_csrf_failure_redirects_without_execution(web, logged_in, monkeypatch, caplog, kind):
    previous = token(logged_in)
    csrf = expired_token(web, logged_in, monkeypatch) if kind == 'expired' else 'invalid'
    sensitive = 'private-node-uuid-vless://do-not-log'
    body = dict(batch_nodes=sensitive, password='private-password-do-not-log')
    if kind != 'missing':
        body['csrf_token'] = csrf

    def forbidden(*args, **kwargs):
        pytest.fail('Rejected CSRF must never enter generation or create links')

    monkeypatch.setitem(web.app.view_functions, 'process_config', forbidden)
    monkeypatch.setattr(web.yaml_utils, 'process_yaml_config', forbidden)
    before = {p: p.read_bytes() for directory in (web.DIR_OUTPUTS, web.DIR_UPLOADS, web.DIR_BACKUPS, web.DIR_STATE)
              for p in Path(directory).rglob('*') if p.is_file()}
    response = logged_in.post('/process', data=body)
    assert response.status_code == 303 and response.location == '/'
    with logged_in.session_transaction() as session:
        assert session['logged_in']
        assert sensitive not in json.dumps(dict(session))
        assert body['password'] not in json.dumps(dict(session))
        assert 'csrf_token' not in session
    page = logged_in.get('/')
    html = page.get_data(as_text=True)
    assert page.status_code == 200 and 'id="process-form"' in html
    assert '安全令牌已刷新' in html and '如有草稿' in html
    assert 'ERROR LOG' not in html and '表单已过期或安全令牌无效' not in html
    assert 'draft.js' in html
    current = re.search(r'name="csrf_token" value="([^"]+)"', html)[1]
    assert current != previous
    assert '安全令牌已刷新' not in logged_in.get('/').get_data(as_text=True)
    after = {p: p.read_bytes() for directory in (web.DIR_OUTPUTS, web.DIR_UPLOADS, web.DIR_BACKUPS, web.DIR_STATE)
             for p in Path(directory).rglob('*') if p.is_file()}
    assert after == before
    assert sensitive not in caplog.text and body['password'] not in caplog.text
    assert sensitive not in (Path(web.DIR_LOGS) / 'app.log').read_text()
    assert body['password'] not in (Path(web.DIR_LOGS) / 'app.log').read_text()
    # The newly minted token really validates, not just renders differently.
    result = logged_in.post('/parse-nodes', data={'csrf_token': current, 'batch_nodes': LINK})
    assert result.status_code == 200 and result.json['nodes']


@pytest.mark.parametrize('path', ['/login', '/process'])
@pytest.mark.parametrize('kind', ['invalid', 'expired'])
def test_logged_out_and_login_csrf_recover_without_loop(web, client, monkeypatch, path, kind):
    csrf = expired_token(web, client, monkeypatch) if kind == 'expired' else 'invalid'
    response = client.post(path, data={'csrf_token': csrf, 'password': 'test 密码'}, follow_redirects=True)
    assert len(response.history) == 1 and response.history[0].status_code == 303
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="password"' in html and '请重新登录' in html
    assert '如有草稿，将在登录后自动恢复' in html and 'ERROR LOG' not in html
    with client.session_transaction() as session:
        assert not session.get('logged_in')
        assert 'test 密码' not in json.dumps(dict(session), ensure_ascii=False)
    login = post(client, '/login', {'password': 'test 密码'}, follow_redirects=True)
    assert login.status_code == 200 and 'draft-status' in login.get_data(as_text=True)
    assert '请重新登录' not in login.get_data(as_text=True)


def test_invalidated_auth_session_and_csrf_recover_to_login(web, logged_in):
    with logged_in.session_transaction() as session:
        session['auth_version'] = -1
    response = logged_in.post('/process', data={'csrf_token': 'invalid'}, follow_redirects=True)
    assert response.status_code == 200 and len(response.history) == 1
    assert 'id="password"' in response.get_data(as_text=True)


def test_expired_parse_returns_recoverable_json_then_valid_retry(web, logged_in, monkeypatch):
    csrf = expired_token(web, logged_in, monkeypatch)
    response = logged_in.post('/parse-nodes', data={'csrf_token': csrf, 'batch_nodes': LINK})
    assert response.status_code == 400 and response.is_json
    assert response.json['code'] == 'csrf_failed'
    assert 'refresh or log in again' in response.json['error']
    assert LINK not in response.get_data(as_text=True)
    assert not list(Path(web.DIR_OUTPUTS).iterdir())
    assert post(logged_in, '/parse-nodes', {'batch_nodes': LINK}).status_code == 200
