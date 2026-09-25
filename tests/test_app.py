import io
import time
from pathlib import Path

import pytest

from conftest import LINK, post


def test_login_failure_logout(web, client):
    assert client.get('/').status_code == 200
    assert post(client, '/login', {'password': 'wrong'}).status_code == 302
    with client.session_transaction() as s:
        assert not s.get('logged_in')
    post(client, '/login', {'password': 'test 密码'})
    with client.session_transaction() as s:
        assert s['logged_in']
    post(client, '/logout')
    with client.session_transaction() as s:
        assert not s.get('logged_in')


@pytest.mark.parametrize('upload', [False, True])
def test_process_download_subscription_delete(web, logged_in, upload):
    data = {'batch_nodes': 'US|test|' + LINK, 'special_groups': '🎥 奈飞节点'}
    if upload:
        data['yaml_file'] = (io.BytesIO(b'rules: [MATCH,DIRECT]\n'), 'custom.yaml')
    response = post(logged_in, '/process', data)
    assert response.status_code == 302
    with logged_in.session_transaction() as s:
        context = s['page_context']
    assert context['result'], context['error_messages']
    filename = context['output_filename']
    anonymous = web.app.test_client()
    token = web.generate_download_token(filename)
    assert anonymous.get('/download/' + filename).status_code == 403
    assert anonymous.get('/download/' + filename + '?token=' + token).status_code == 200
    assert anonymous.get('/sub/' + token + '/' + filename).status_code == 200
    slug = web.build_short_subscription_slug(filename)
    assert anonymous.get('/s/' + slug).status_code == 200
    assert anonymous.get('/s/' + slug + 'bad').status_code == 403
    backup_files = list(Path(web.DIR_BACKUPS).iterdir())
    post(logged_in, '/delete-temp', dict(output_filename=filename, upload_filename=context['upload_filename']))
    assert anonymous.get('/s/' + slug).status_code == 404
    assert all(p.exists() for p in backup_files)


def test_invalid_upload_extension(logged_in):
    post(logged_in, '/process', {'batch_nodes': 'US|test|' + LINK,
                               'yaml_file': (io.BytesIO(b'{}'), 'bad.txt')})
    with logged_in.session_transaction() as s:
        assert s['page_context']['error_messages']


def test_size_limit(web, logged_in):
    web.app.config['MAX_CONTENT_LENGTH'] = 1024
    response = post(logged_in, '/process', {'yaml_file': (io.BytesIO(b'a' * 2048), 'big.yaml')})
    assert response.status_code in (302, 413)
    with logged_in.session_transaction() as s:
        assert '50MB' in str(s['page_context']['error_messages'])
    assert not list(Path(web.DIR_UPLOADS).iterdir())


@pytest.mark.parametrize('length', [8, 12, 64])
def test_legacy_download_signatures(web, length):
    filename = 'tim_20260602_1.yaml'
    token = web.generate_download_token(filename)[:length]
    assert web.is_valid_download_token(filename, token)
    assert not web.is_valid_download_token('other.yaml', token)
    assert web.parse_short_subscription_slug(filename[:-5] + '-' + token) == (filename, token)


def test_cleanup_retention(web):
    for directory in (web.DIR_UPLOADS, web.DIR_OUTPUTS, web.DIR_BACKUPS):
        old, new = Path(directory) / 'old.yaml', Path(directory) / 'new.yaml'
        old.write_text('{}')
        new.write_text('{}')
        import os
        os.utime(old, (time.time() - 9 * 86400,) * 2)
    Path(web.CLEANUP_MARKER).unlink()
    web.cleanup_old_files()
    for directory in (web.DIR_UPLOADS, web.DIR_OUTPUTS, web.DIR_BACKUPS):
        assert not (Path(directory) / 'old.yaml').exists()
        assert (Path(directory) / 'new.yaml').exists()


@pytest.mark.p0
@pytest.mark.parametrize('path', ['/login', '/logout', '/change-password', '/process', '/delete-temp'])
def test_csrf_required(logged_in, path):
    assert logged_in.post(path).status_code == 400


@pytest.mark.p0
def test_logout_get_cannot_mutate_session(logged_in):
    assert logged_in.get('/logout').status_code == 405
    with logged_in.session_transaction() as s:
        assert s['logged_in']


@pytest.mark.p0
def test_untrusted_forwarding_and_http_default(web):
    with web.app.test_request_context('/', base_url='http://localhost:8899', headers={
            'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'attacker.example'}):
        url = web.build_download_url('tim_20260602_1.yaml')
    assert url.startswith('http://localhost:8899/s/')
    client = web.app.test_client()
    response = client.get('/', headers={'X-Forwarded-For': '192.0.2.99'})
    assert response.status_code == 200
    from werkzeug.middleware.proxy_fix import ProxyFix
    assert not isinstance(web.app.wsgi_app, ProxyFix)


@pytest.mark.p0
def test_unicode_token_returns_403(web, client):
    assert client.get('/download/test.yaml?token=密码').status_code == 403


def test_explicit_base_url(web, monkeypatch):
    monkeypatch.setattr(web, 'DOWNLOAD_BASE_URL', 'https://public.example/panel')
    with web.app.test_request_context('/'):
        assert web.build_download_url('tim_20260602_1.yaml').startswith('https://public.example/panel/s/')


@pytest.mark.p0
def test_login_rotates_session(client):
    with client.session_transaction() as s:
        s['old_marker'] = True
    post(client, '/login', {'password': 'test 密码'})
    with client.session_transaction() as s:
        assert s['logged_in'] and 'old_marker' not in s


def test_legacy_base64_password_and_change(web, monkeypatch, logged_in):
    new = 'new 密码 $ symbols'
    post(logged_in, '/change-password', {'current_password': 'test 密码', 'new_password': new,
                                        'confirm_password': new})
    with logged_in.session_transaction() as s:
        assert not s.get('logged_in')
    assert web.auth_store.authenticate(new)
    assert new not in web.auth_store.path.read_text()
    assert not (Path(web.BASE_DIR) / '.env').exists()
    assert web.auth_store.path.stat().st_mode & 0o777 == 0o600
    post(logged_in, '/login', {'password': new})
    with logged_in.session_transaction() as s:
        assert s['logged_in']


@pytest.mark.parametrize('current,new,confirm', [('wrong', 'new', 'new'), ('test 密码', '', ''),
                                              ('test 密码', 'new', 'different')])
def test_password_failure_keeps_existing_password(web, logged_in, current, new, confirm):
    post(logged_in, '/change-password', {'current_password': current, 'new_password': new,
                                        'confirm_password': confirm})
    assert web.auth_store.authenticate('test 密码')
    assert not (Path(web.BASE_DIR) / '.env').exists()


def test_forwarded_host_ignored_in_generated_links(web, logged_in):
    post(logged_in, '/process', {'batch_nodes': 'US|test|' + LINK}, headers={
        'X-Forwarded-Host': 'attacker.example', 'X-Forwarded-Proto': 'https'})
    with logged_in.session_transaction() as s:
        url = s['page_context']['download_url']
    assert url.startswith('http://localhost/s/')


def test_trusted_proxy_https_links(web, logged_in):
    from werkzeug.middleware.proxy_fix import ProxyFix
    # Exercise the same one-hop wrapper enabled by TRUST_PROXY_HEADERS=true.
    web.app.wsgi_app = ProxyFix(web.app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    post(logged_in, '/process', {'batch_nodes': 'US|test|' + LINK,
                               'yaml_file': (io.BytesIO(b'{}'), 'config.yaml')}, headers={
        'X-Forwarded-Host': 'public.example', 'X-Forwarded-Proto': 'https',
        'Referer': 'https://public.example/'})
    with logged_in.session_transaction() as s:
        assert s['page_context']['download_url'].startswith('https://public.example/s/')


def test_sensitive_errors_and_logs(web, logged_in):
    secret = 'private-token-value'
    response = post(logged_in, '/process', {'batch_nodes': 'US|test|vless://id@example.com:' + secret},
                    follow_redirects=True)
    assert secret not in response.get_data(as_text=True)
    assert secret not in (Path(web.DIR_LOGS) / 'app.log').read_text()


def test_tampered_csrf_rejected(client):
    response = client.post('/login', data={'password': 'test 密码', 'csrf_token': 'invalid'})
    assert response.status_code == 400
    with client.session_transaction() as s:
        assert not s.get('logged_in')


def test_cookie_security_defaults(web, client):
    response = post(client, '/login', {'password': 'test 密码'})
    cookie = response.headers['Set-Cookie']
    assert 'HttpOnly' in cookie and 'SameSite=Lax' in cookie and 'Expires=' in cookie
    assert web.app.config['PERMANENT_SESSION_LIFETIME'].total_seconds() == 43200


def test_password_change_invalidates_all_sessions_and_download_bypass(web):
    a, b = web.app.test_client(), web.app.test_client()
    for browser in (a, b):
        post(browser, '/login', {'password': 'test 密码'})
    (Path(web.DIR_OUTPUTS) / 'private.yaml').write_text('{}')
    assert b.get('/download/private.yaml').status_code == 200
    post(a, '/change-password', {'current_password': 'test 密码', 'new_password': 'new password',
                                'confirm_password': 'new password'})
    with a.session_transaction() as session:
        assert not session.get('logged_in')
    assert b.get('/download/private.yaml').status_code == 403
    with b.session_transaction() as session:
        assert not session.get('logged_in')
    post(b, '/login', {'password': 'test 密码'})
    with b.session_transaction() as session:
        assert not session.get('logged_in')
    post(b, '/login', {'password': 'new password'})
    with b.session_transaction() as session:
        assert session['logged_in'] and session['auth_version'] == 2


def test_cleanup_never_removes_auth_state(web):
    import os
    path = web.auth_store.path
    before = path.read_bytes()
    os.utime(path, (time.time() - 30 * 86400,) * 2)
    Path(web.CLEANUP_MARKER).unlink()
    web.cleanup_old_files()
    assert path.read_bytes() == before


def test_runtime_password_change_does_not_touch_env(web, logged_in):
    env = Path(web.BASE_DIR) / '.env'
    original = b'SECRET_KEY=not-for-runtime-reading\nAPP_PASSWORD=legacy\n'
    env.write_bytes(original)
    env.chmod(0o400)
    post(logged_in, '/change-password', {'current_password': 'test 密码', 'new_password': 'new',
                                        'confirm_password': 'new'})
    assert web.auth_store.authenticate('new')
    assert env.read_bytes() == original
