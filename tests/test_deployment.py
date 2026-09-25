"""Execute the real scripts with temp paths and fake external system commands.

This tests control flow and data preservation, not Ubuntu/systemd integration.
The root check alone is disabled in a test copy. Never touch /opt, /etc or /root.
"""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from conftest import ROOT


def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/usr/bin/env bash\nset -eu\n' + text)
    path.chmod(0o700)


@pytest.fixture
def deployment(tmp_path):
    installed, source, commands = [tmp_path / name for name in ('installed', 'source', 'commands')]
    for directory in (installed, source, commands):
        directory.mkdir()
    (source / 'core').mkdir()
    (source / 'app.py').write_text('VERSION = "new"\n')
    (source / 'requirements.txt').write_text('Flask\n')
    (source / '.env').write_text('DO_NOT_COPY=source-secret\n')
    (source / 'defaults').mkdir()
    (source / 'defaults/default.yaml').write_text('new: template\n')
    (source / '.venv').mkdir()
    (source / '.venv/unwanted').touch()
    (installed / 'app.py').write_text('VERSION = "old"\n')
    (installed / '.env').write_text('APP_PASSWORD_B64=dGVzdA==\nAPP_PORT=8899\nSECRET_KEY=old-key\n')
    for name in ('uploads', 'outputs', 'backups', 'logs', 'defaults'):
        (installed / name).mkdir()
        (installed / name / ('default.yaml' if name == 'defaults' else 'keep')).write_text('preserved\n')
    service = tmp_path / 'service'
    service.write_text('[Service]\nUser=root\n')
    events = tmp_path / 'events'
    env = os.environ.copy()
    env.update(PATH=str(commands) + os.pathsep + env['PATH'], TEST_EVENTS=str(events),
               TMPDIR=str(tmp_path), TEST_PIP_FAIL='0', TEST_HEALTH_FAIL='0')
    (commands / 'python3').symlink_to(sys.executable)
    executable(commands / 'systemctl', 'echo "systemctl $*" >> "$TEST_EVENTS"\n')
    executable(commands / 'curl', 'echo "curl" >> "$TEST_EVENTS"\nexit "$TEST_HEALTH_FAIL"\n')
    executable(commands / 'sleep', ':\n')
    executable(commands / 'apt-get', 'echo apt-get >> "$TEST_EVENTS"\n')
    executable(installed / 'venv/bin/pip', 'echo "pip $*" >> "$TEST_EVENTS"\nexit "$TEST_PIP_FAIL"\n')

    def run(script_name='update.sh', cwd=None, input_text=None):
        script = (ROOT / script_name).read_text()
        assert 'if [[ "${EUID}" -ne 0 ]]; then' in script
        script = script.replace('if [[ "${EUID}" -ne 0 ]]; then', 'if false; then')
        script = script.replace('INSTALL_DIR="/opt/clash-yaml-manager"', f'INSTALL_DIR="{installed}"')
        script = script.replace('SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"', f'SERVICE_FILE="{service}"')
        script = script.replace('/root/${SERVICE_NAME}-update-backup-', str(tmp_path / 'upgrade-backup-'))
        script = script.replace('/root/${SERVICE_NAME}-backup-', str(tmp_path / 'uninstall-backup-'))
        path = tmp_path / ('run-' + script_name)
        path.write_text(script)
        return subprocess.run(['bash', str(path)], cwd=cwd or source, env=env,
                              input=input_text, capture_output=True, text=True, timeout=20)
    return installed, source, service, events, env, run


def test_upgrade_preserves_data_and_checks_health(deployment):
    installed, source, service, events, env, run = deployment
    original = {p.relative_to(installed): p.read_bytes() for p in installed.rglob('*')
                if p.is_file() and p.name not in ('app.py', 'pip')}
    result = run()
    assert result.returncode == 0, result.stderr + result.stdout
    assert (installed / 'app.py').read_text() == (source / 'app.py').read_text()
    assert not (installed / '.venv').exists()
    for path, content in original.items():
        assert (installed / path).read_bytes() == content
    assert (installed / 'outputs').stat().st_mode & 0o777 == 0o700
    assert 'UMask=0077' in service.read_text()
    assert f'WorkingDirectory={installed}' in service.read_text()
    assert f'ExecStart={installed}/venv/bin/gunicorn' in service.read_text()
    assert '${APP_PORT}' in service.read_text()
    log = events.read_text()
    assert log.index('pip install') < log.index('systemctl stop')
    assert log.index('systemctl daemon-reload') < log.index('systemctl restart') < log.index('curl')
    backup = next(installed.parent.glob('upgrade-backup-*'))
    assert (backup / 'app.py').read_text() == 'VERSION = "old"\n'
    assert (backup / '.env').read_bytes() == original[Path('.env')]
    assert (backup / 'venv/bin/pip').exists()
    assert (backup / 'clash-yaml-manager.service').exists()


def test_same_directory_update_fails_without_modifying_files(deployment):
    installed, _, _, events, _, run = deployment
    (installed / 'requirements.txt').write_text('Flask\n')
    before = (installed / 'app.py').read_bytes()
    result = run(cwd=installed)
    assert result.returncode != 0
    assert (installed / 'app.py').read_bytes() == before
    assert not events.exists()


@pytest.mark.parametrize('bad_config', ['missing', 'APP_PORT=bad\n', 'APP_PASSWORD_B64=bad!\nAPP_PORT=8899\nSECRET_KEY=key\n'])
def test_preflight_failure_never_stops_service(deployment, bad_config):
    installed, _, _, events, _, run = deployment
    if bad_config == 'missing':
        (installed / '.env').unlink()
    else:
        (installed / '.env').write_text(bad_config)
    result = run()
    assert result.returncode != 0 and not events.exists()
    assert (installed / 'app.py').read_text() == 'VERSION = "old"\n'


def test_failed_dependencies_do_not_stop_or_replace_app(deployment):
    installed, _, _, events, env, run = deployment
    env['TEST_PIP_FAIL'] = '1'
    result = run()
    assert result.returncode != 0
    assert 'systemctl stop' not in events.read_text()
    assert (installed / 'app.py').read_text() == 'VERSION = "old"\n'
    assert '回滚' in result.stderr


def test_health_failure_reports_rollback(deployment):
    _, _, _, events, env, run = deployment
    env['TEST_HEALTH_FAIL'] = '1'
    result = run()
    assert result.returncode != 0
    assert '回滚' in result.stderr and '升级完成。' not in result.stdout
    assert 'systemctl restart' in events.read_text()


def test_reinstall_never_touches_existing_install(deployment):
    installed, _, _, events, _, run = deployment
    original = (installed / '.env').read_bytes()
    result = run('install.sh')
    assert result.returncode != 0 and not events.exists()
    assert (installed / '.env').read_bytes() == original


def test_remote_download_failure_leaves_existing_data(deployment):
    installed, _, _, events, env, run = deployment
    commands = Path(env['PATH'].split(os.pathsep)[0])
    executable(commands / 'git', 'echo "git clone failed" >> "$TEST_EVENTS"\nexit 1\n')
    sentinel = installed.parent / 'existing-temp'
    sentinel.mkdir()
    (sentinel / 'keep').write_text('keep')
    env['TMP'] = str(sentinel)  # old script would rm -rf this user-supplied path
    result = run('remote-update.sh')
    assert result.returncode != 0
    assert (sentinel / 'keep').read_text() == 'keep'
    assert (installed / 'app.py').read_text() == 'VERSION = "old"\n'
    assert 'systemctl' not in events.read_text()
    assert not list(installed.parent.glob('clash-yaml-manager-update.*'))


def test_fresh_install_default_url_and_private_files(deployment):
    installed, source, service, events, env, run = deployment
    previous = installed.with_name('previous')
    installed.rename(previous)
    service.unlink()
    commands = Path(env['PATH'].split(os.pathsep)[0])
    (commands / 'python3').unlink()  # remove test symlink before writing a wrapper
    env['TEST_PYTHON'] = sys.executable
    env['TEST_FAKE_PIP'] = str(previous / 'venv/bin/pip')
    executable(commands / 'python3', '''if [[ "$1" == -m && "$2" == venv ]]; then
  mkdir -p "$3/bin"
  cp "$TEST_FAKE_PIP" "$3/bin/pip"
  exit 0
fi
exec "$TEST_PYTHON" "$@"
''')
    executable(commands / 'ss', ':\n')
    result = run('install.sh', input_text='\ntest-install-password\n')
    assert result.returncode == 0, result.stderr + result.stdout
    configuration = (installed / '.env').read_text()
    assert 'APP_PORT=8899\n' in configuration
    assert 'DOWNLOAD_URL_SCHEME=\n' in configuration
    assert 'TRUST_PROXY_HEADERS=false\n' in configuration
    assert 'DO_NOT_COPY' not in configuration
    assert (installed / '.env').stat().st_mode & 0o777 == 0o600
    assert (installed / 'outputs').stat().st_mode & 0o777 == 0o700
    assert 'UMask=0077' in service.read_text()
    assert not (installed / '.venv').exists()


def test_uninstall_keep_data_choice(deployment):
    installed, _, service, _, _, run = deployment
    result = run('uninstall.sh', input_text='n\n')
    assert result.returncode == 0, result.stderr
    assert not service.exists()
    assert (installed / '.env').exists()
    assert (installed / 'outputs/keep').read_text() == 'preserved\n'


@pytest.mark.parametrize('script', ['install.sh', 'update.sh', 'remote-update.sh', 'uninstall.sh'])
def test_shell_syntax(script):
    result = subprocess.run(['bash', '-n', str(ROOT / script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
