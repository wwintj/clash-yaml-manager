import importlib.util
import logging
import os
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LINK = 'vless://11111111-1111-4111-8111-111111111111@example.com:443?type=tcp'


def local_guard_copy(text, root):
    """Trusted test-copy policy only; production has no path/owner override."""
    return (text.replace("GUARD_ROOT = '/var/lib/clash-yaml-manager-deployment'", f'GUARD_ROOT = {str(root)!r}')
            .replace('GUARD_UID = 0', f'GUARD_UID = {os.getuid()}')
            .replace('GUARD_GID = 0', f'GUARD_GID = {os.getgid()}')
            .replace("guard_require(os.geteuid() == 0, 'DEPLOYMENT_GUARD_ROOT_REQUIRED')",
                     "guard_require(True, 'DEPLOYMENT_GUARD_ROOT_REQUIRED')"))


@pytest.fixture
def isolated_guard(tmp_path, monkeypatch):
    from scripts import deployment_guard as guard
    monkeypatch.setattr(guard, 'GUARD_ROOT', str(tmp_path / 'deployment-guard'))
    monkeypatch.setattr(guard, 'GUARD_UID', os.getuid())
    monkeypatch.setattr(guard, 'GUARD_GID', os.getgid())
    monkeypatch.setattr(guard, 'guard_require_root', lambda: None)
    return guard


@pytest.fixture
def node():
    return dict(name='🇺🇸 Test', type='vless', server='example.com', port=443,
                uuid='11111111-1111-4111-8111-111111111111')


@pytest.fixture
def web(tmp_path, monkeypatch):
    # Import-time logging/cleanup must never touch the checkout's runtime data.
    for name in ('app.py', 'VERSION', 'mihomo-manifest.json'):
        shutil.copy2(ROOT / name, tmp_path / name)
    for name in ('templates', 'static', 'defaults'):
        shutil.copytree(ROOT / name, tmp_path / name)
    monkeypatch.setenv('APP_PASSWORD', 'test 密码')
    monkeypatch.setenv('SECRET_KEY', 'test-only-fixed-secret')
    for name in ('APP_PASSWORD_B64', 'APP_PASSWORD_HASH', 'DOWNLOAD_BASE_URL',
                 'DOWNLOAD_URL_SCHEME', 'TRUST_PROXY_HEADERS', 'COOKIE_SECURE'):
        monkeypatch.delenv(name, raising=False)
    root_logger = logging.getLogger()
    handlers, level = root_logger.handlers[:], root_logger.level
    spec = importlib.util.spec_from_file_location('isolated_app', tmp_path / 'app.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.app.config.update(TESTING=True)
    yield module
    for handler in root_logger.handlers:
        if handler not in handlers:
            handler.close()
    root_logger.handlers[:] = handlers
    root_logger.setLevel(level)


def post(client, path, data=None, **kwargs):
    html = client.get('/').get_data(as_text=True)
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    values = dict(data or {})
    if match:
        values['csrf_token'] = match.group(1)
    return client.post(path, data=values, **kwargs)


@pytest.fixture
def client(web):
    return web.app.test_client()


@pytest.fixture
def logged_in(client):
    assert post(client, '/login', {'password': 'test 密码'}).status_code == 302
    return client
