import pytest
import subprocess
import sys


def test_installed_gunicorn_supports_service_flag():
    from gunicorn.config import Config
    result = subprocess.run([sys.executable, '-m', 'gunicorn', '--help'],
                            text=True, capture_output=True, check=True)
    assert '--no-control-socket' in result.stdout
    config = Config()
    options = config.parser().parse_args(['--no-control-socket'])
    config.set('control_socket_disable', options.control_socket_disable)
    assert config.control_socket_disable is True


@pytest.mark.parametrize('authenticated', [False, True])
def test_healthz_is_public_and_independent_of_auth_and_cleanup(web, monkeypatch, authenticated):
    client = web.app.test_client()
    if authenticated:
        with client.session_transaction() as session:
            session['logged_in'] = True
            session['auth_version'] = -1
            session['auth_instance'] = 'stale'

    def unavailable():
        raise AssertionError('readiness must not read authentication or runtime files')

    monkeypatch.setattr(web.auth_store, 'read', unavailable)
    monkeypatch.setattr(web, 'cleanup_old_files', unavailable)
    response = client.get('/healthz')
    assert response.status_code == 200
    assert response.data == b'OK\n'  # no version, secret, path, user, token or subscription data
    assert response.mimetype == 'text/plain'
    assert response.headers['Cache-Control'] == 'no-store'
    assert 'Location' not in response.headers
    if not authenticated:
        assert 'Set-Cookie' not in response.headers
