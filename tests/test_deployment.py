"""Execute the real scripts with temp paths and fake external system commands.

This tests control flow and data preservation, not Ubuntu/systemd integration.
The root check alone is disabled in a test copy. Never touch /opt, /etc or /root.
"""
import os
from pathlib import Path
import subprocess
import sys
import shutil

import pytest

from conftest import ROOT


@pytest.mark.parametrize('script_name', ['install.sh', 'update.sh'])
def test_production_readiness_timeout_is_explicit(script_name):
    script = (ROOT / script_name).read_text()
    assert 'if ! wait_for_application 30; then' in script
    assert 'if ! wait_for_application; then' not in script


def test_fixed_subscription_survives_upgrade_and_backup(deployment):
    from core.fixed_subscriptions import FixedSubscriptions
    from core import generator
    from conftest import LINK
    installed, source, service, events, env, run = deployment
    store = FixedSubscriptions(installed / 'state')
    config = dict(yaml_source='custom', batch_nodes='US|Preserved|' + LINK,
                  aux_nodes=[], node_overrides={}, special_groups=[])
    entry = store.save(None, 'Preserved', 'preserved', config,
                       generator.parse_form_nodes({'batch_nodes':config['batch_nodes']}),
                       source / 'unused.yaml', b'proxies: []\nproxy-groups: []\nrules: []\n',
                       sources=[dict(type='uploaded', name='Office', enabled=True, format='raw')],
                       uploads={0:(LINK+'#Tokyo-upload').encode()})
    source_id = entry['sources'][1]['id']
    payload = store._payload(entry, source_id)
    slug = store.slug(entry); before = store.resolve(slug)
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert FixedSubscriptions(installed / 'state').resolve(slug) == before
    assert FixedSubscriptions(installed / 'state')._payload(entry, source_id) == payload
    backups = list(installed.parent.glob('upgrade-backup-*/state'))
    assert len(backups) == 1 and FixedSubscriptions(backups[0]).resolve(slug) == before
    assert FixedSubscriptions(backups[0])._payload(entry, source_id) == payload
    result = run('uninstall.sh', input_text='y\n\n')
    assert result.returncode == 0, result.stdout + result.stderr
    uninstall_backup = next(installed.parent.glob('uninstall-backup-*'))
    assert FixedSubscriptions(uninstall_backup / 'state').resolve(slug) == before
    assert FixedSubscriptions(uninstall_backup / 'state')._payload(entry, source_id) == payload


def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/usr/bin/env bash\nset -eu\n' + text)
    path.chmod(0o700)


@pytest.fixture
def deployment(tmp_path):
    installed, source, commands = [tmp_path / name for name in ('installed', 'source', 'commands')]
    for directory in (installed, source, commands):
        directory.mkdir()
    shutil.copytree(ROOT / 'core', source / 'core', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(ROOT / 'scripts', source / 'scripts')
    shutil.copy2(ROOT / 'VERSION', source / 'VERSION')
    (source / 'app.py').write_text('VERSION = "new"\n')
    shutil.copy2(ROOT / 'requirements.txt', source / 'requirements.txt')
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
               TMPDIR=str(tmp_path), TEST_PIP_FAIL='0', TEST_HEALTH_FAIL='0',
               TEST_ACCOUNT=str(tmp_path / 'account.db'), TEST_PYTHON=sys.executable)
    (commands / 'python3').symlink_to(sys.executable)
    executable(commands / 'systemctl', '''echo "systemctl $*" >> "$TEST_EVENTS"
if [[ "$1" == is-active ]]; then exit "${TEST_INACTIVE:-0}"; fi
if [[ "$1" == stop && "$2" == "${TEST_FAIL_STOP:-}" ]]; then exit 1; fi
if [[ "$1" == stop && "$2" == clash-yaml-manager-refresh.service && -n "${TEST_STOP_MARKER:-}" ]]; then
  echo stopped > "$TEST_STOP_MARKER"
fi
''')
    executable(commands / 'journalctl', 'echo "journalctl $*" >> "$TEST_EVENTS"\n')
    executable(commands / 'curl', '''echo "curl $*" >> "$TEST_EVENTS"
count_file="${TEST_EVENTS}.attempts"
count=0
[[ ! -f "$count_file" ]] || read -r count < "$count_file"
count=$((count + 1))
echo "$count" > "$count_file"
if (( count <= ${TEST_FAIL_FIRST:-0} )); then
  echo 'curl: (7) Failed to connect' >&2
  exit 7
fi
echo "${TEST_HTTP_STATUS:-200}"
exit "$TEST_HEALTH_FAIL"
''')
    executable(commands / 'sleep', ':\n')
    executable(commands / 'apt-get', 'echo apt-get >> "$TEST_EVENTS"\n')
    executable(installed / 'venv/bin/pip', 'echo "pip $*" >> "$TEST_EVENTS"\nexit "$TEST_PIP_FAIL"\n')
    executable(installed / 'venv/bin/python', 'exec "$TEST_PYTHON" "$@"\n')
    executable(commands / 'getent', '''[[ -f "$TEST_ACCOUNT" ]] || exit 2
if [[ "$1" == passwd ]]; then
  cat "$TEST_ACCOUNT"
else
  echo clashyaml:x:998:
fi
''')
    executable(commands / 'id', '[[ -f "$TEST_ACCOUNT" ]] || exit 1\necho 998\n')
    executable(commands / 'useradd', '''echo "useradd $*" >> "$TEST_EVENTS"
echo 'clashyaml:x:998:998:Clash YAML Manager service:/nonexistent:/usr/sbin/nologin' > "$TEST_ACCOUNT"
''')
    executable(commands / 'userdel', 'echo "userdel $*" >> "$TEST_EVENTS"\nrm "$TEST_ACCOUNT"\n')
    executable(commands / 'pgrep', 'exit 1\n')
    executable(commands / 'chown', 'echo "chown $*" >> "$TEST_EVENTS"\n')

    def run(script_name='update.sh', cwd=None, input_text=None):
        script = (ROOT / script_name).read_text()
        assert 'if [[ "${EUID}" -ne 0 ]]; then' in script
        script = script.replace('if [[ "${EUID}" -ne 0 ]]; then', 'if false; then')
        script = script.replace('INSTALL_DIR="/opt/clash-yaml-manager"', f'INSTALL_DIR="{installed}"')
        script = script.replace('SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"', f'SERVICE_FILE="{service}"')
        script = script.replace('/root/${SERVICE_NAME}-update-backup-', str(tmp_path / 'upgrade-backup-'))
        script = script.replace('/root/${SERVICE_NAME}-backup-', str(tmp_path / 'uninstall-backup-'))
        script = script.replace('${SCRIPT_DIR}/scripts/deploy-common.sh', str(ROOT / 'scripts/deploy-common.sh'))
        path = tmp_path / ('run-' + script_name)
        path.write_text(script)
        return subprocess.run(['bash', str(path)], cwd=cwd or source, env=env,
                              input=input_text, capture_output=True, text=True, timeout=20)
    return installed, source, service, events, env, run


def test_upgrade_preserves_data_and_checks_health(deployment):
    installed, source, service, events, env, run = deployment
    original = {p.relative_to(installed): p.read_bytes() for p in installed.rglob('*')
                if p.is_file() and p.name not in ('app.py', 'pip', 'python')}
    result = run()
    assert result.returncode == 0, result.stderr + result.stdout
    assert (installed / 'app.py').read_text() == (source / 'app.py').read_text()
    assert (installed / 'VERSION').read_bytes() == (source / 'VERSION').read_bytes()
    assert not (installed / '.venv').exists()
    for path, content in original.items():
        expected = content.replace(b'APP_PASSWORD_B64=dGVzdA==\n', b'') if path == Path('.env') else content
        assert (installed / path).read_bytes() == expected
    from core.security import AuthStore
    assert AuthStore(installed / 'state').authenticate('test')
    assert (installed / 'outputs').stat().st_mode & 0o777 == 0o700
    assert (installed / 'app.py').stat().st_mode & 0o777 == 0o644
    assert (installed / 'core').stat().st_mode & 0o777 == 0o755
    assert (installed / '.env').stat().st_mode & 0o777 == 0o600
    assert 'UMask=0077' in service.read_text()
    assert 'User=clashyaml' in service.read_text() and 'Group=clashyaml' in service.read_text()
    assert 'User=root' not in service.read_text()
    assert 'NoNewPrivileges=true' in service.read_text() and 'PrivateTmp=true' in service.read_text()
    assert f'WorkingDirectory={installed}' in service.read_text()
    assert f'ExecStart={installed}/venv/bin/gunicorn' in service.read_text()
    assert '--no-control-socket' in service.read_text()
    assert 'Environment=HOME=' not in service.read_text()
    assert '${APP_PORT}' in service.read_text()
    log = events.read_text()
    assert log.index('pip install') < log.index('systemctl stop')
    assert log.index('systemctl daemon-reload') < log.index('systemctl restart') < log.index('curl')
    assert 'useradd --system --user-group' in log
    assert f'chown -hR root:root {installed}/core' in log
    assert f'chown -h clashyaml:clashyaml {installed}/state' in log
    assert f'chown -R clashyaml:clashyaml {installed}\n' not in log
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
    installed, _, _, events, env, run = deployment
    env['TEST_HEALTH_FAIL'] = '1'
    result = run()
    assert result.returncode != 0
    assert '回滚' in result.stderr and '升级完成。' not in result.stdout
    assert 'systemctl restart' in events.read_text()
    assert 'Health check FAILED' in result.stderr
    assert 'systemctl status clash-yaml-manager --no-pager -l' in events.read_text()
    assert 'journalctl -u clash-yaml-manager -n 50 --no-pager' in events.read_text()
    backup = next(installed.parent.glob('upgrade-backup-*'))
    assert str(backup) in result.stderr
    assert (backup / '.env').exists() and (backup / 'venv/bin/pip').exists()
    assert (backup / 'app.py').read_text() == 'VERSION = "old"\n'


def test_reinstall_never_touches_existing_install(deployment):
    installed, _, _, events, _, run = deployment
    original = (installed / '.env').read_bytes()
    result = run('install.sh')
    assert result.returncode != 0 and not events.exists()
    assert (installed / '.env').read_bytes() == original


@pytest.mark.parametrize('password,channel,health_failure', [('a','local',False), ('1','local',False),
                                             ('密','local',False), ('!','local',False),
                                             (' leading trailing ','local',False), (' ','local',False),
                                             ('test-main','main',False), ('test-stable','stable',False),
                                             ('failure-main','main',True), ('failure-stable','stable',True)])
def test_fresh_install_default_url_and_private_files(deployment, password, channel, health_failure):
    installed, source, service, events, env, run = deployment
    previous = installed.with_name('previous')
    installed.rename(previous)
    service.unlink()
    commands = Path(env['PATH'].split(os.pathsep)[0])
    (commands / 'python3').unlink()  # remove test symlink before writing a wrapper
    env['TEST_PYTHON'] = sys.executable
    env['TEST_FAKE_PIP'] = str(previous / 'venv/bin/pip')
    env['TEST_FAKE_PYTHON'] = str(previous / 'venv/bin/python')
    executable(commands / 'python3', '''if [[ "$1" == -m && "$2" == venv ]]; then
  mkdir -p "$3/bin"
  cp "$TEST_FAKE_PIP" "$3/bin/pip"
  cp "$TEST_FAKE_PYTHON" "$3/bin/python"
  exit 0
fi
exec "$TEST_PYTHON" "$@"
''')
    executable(commands / 'ss', ':\n')
    if channel != 'local':
        from core.install_info import make_install_info
        import json
        version = (source / 'VERSION').read_text().strip()
        metadata = source.parent / 'incoming.json'
        metadata.write_text(json.dumps(make_install_info(channel, version, 'a'*40, 'v'+version if channel == 'stable' else None)))
        env['CLASH_DEPLOY_METADATA'] = str(metadata)
    env['TEST_FAIL_FIRST'] = '2'
    env['TEST_HEALTH_FAIL'] = '1' if health_failure else '0'
    result = run('install.sh', input_text='\n\n' + password + '\n')
    if health_failure:
        assert result.returncode != 0
        assert 'Health check FAILED' in result.stderr
        assert '安装成功' not in result.stdout
        assert 'systemctl status clash-yaml-manager --no-pager -l' in events.read_text()
        assert 'journalctl -u clash-yaml-manager -n 50 --no-pager' in events.read_text()
        return
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.index('attempt 3/30: PASS') < result.stdout.index('安装成功')
    assert 'curl: (7)' not in result.stderr
    configuration = (installed / '.env').read_text()
    assert 'APP_PORT=8899\n' in configuration
    assert 'DOWNLOAD_URL_SCHEME=\n' in configuration
    assert 'TRUST_PROXY_HEADERS=false\n' in configuration
    assert 'DO_NOT_COPY' not in configuration
    assert 'APP_PASSWORD' not in configuration
    assert 'CLASH_DEPLOY_METADATA' not in configuration
    from core.install_info import read_install_info
    assert read_install_info(installed)['channel'] == channel
    assert (installed / 'INSTALLATION.json').stat().st_mode & 0o777 == 0o644
    from core.security import AuthStore
    assert AuthStore(installed / 'state').authenticate(password)
    for setting in ('UPLOAD_RETENTION_HOURS=1', 'OUTPUT_RETENTION_HOURS=24',
                    'CLEANUP_INTERVAL_HOURS=1', 'BACKUP_RETENTION_DAYS=7'):
        assert setting in (installed / '.env').read_text()
    assert (installed / 'VERSION').read_bytes() == (source / 'VERSION').read_bytes()
    assert (installed / '.env').stat().st_mode & 0o777 == 0o600
    assert (installed / 'outputs').stat().st_mode & 0o777 == 0o700
    assert 'UMask=0077' in service.read_text()
    assert 'User=clashyaml' in service.read_text() and 'Group=clashyaml' in service.read_text()
    assert '--no-control-socket' in service.read_text() and 'User=root' not in service.read_text()
    assert 'NoNewPrivileges=true' in service.read_text() and 'PrivateTmp=true' in service.read_text()
    assert 'Environment=HOME=' not in service.read_text()
    assert not (installed / '.venv').exists()
    assert_refresh_units(installed, service, events)


def test_uninstall_keep_data_choice(deployment):
    installed, _, service, _, _, run = deployment
    result = run('uninstall.sh', input_text='n\n')
    assert result.returncode == 0, result.stderr
    assert not service.exists()
    assert (installed / '.env').exists()
    assert (installed / 'outputs/keep').read_text() == 'preserved\n'


def assert_refresh_units(installed, service, events):
    import configparser
    oneshot = Path(str(service).removesuffix('.service') + '-refresh.service')
    timer = Path(str(service).removesuffix('.service') + '-refresh.timer')
    config = configparser.ConfigParser(interpolation=None, strict=True)
    config.optionxform = str
    config.read(oneshot)
    assert dict(config['Service']) == dict(Type='oneshot', User='clashyaml', Group='clashyaml', UMask='0077',
        NoNewPrivileges='true',PrivateTmp='true',Environment='PYTHONDONTWRITEBYTECODE=1',
        WorkingDirectory=str(installed),EnvironmentFile=str(installed/'.env'),
        ExecStart=f'{installed}/venv/bin/python -m core.auto_refresh --once',TimeoutStartSec='20min')
    config.read(timer)
    assert dict(config['Timer']) == dict(OnBootSec='2min',OnUnitActiveSec='5min',AccuracySec='30s',
        RandomizedDelaySec='30s',Persistent='true',Unit='clash-yaml-manager-refresh.service')
    assert config['Install']['WantedBy'] == 'timers.target'
    assert oneshot.stat().st_mode & 0o777 == timer.stat().st_mode & 0o777 == 0o644
    log = events.read_text()
    assert log.index('systemctl daemon-reload') < log.index('systemctl enable --now clash-yaml-manager-refresh.timer')
    assert log.index('systemctl enable --now clash-yaml-manager-refresh.timer') < log.index('systemctl restart clash-yaml-manager')
    return oneshot, timer


def test_refresh_upgrade_backup_stop_order_and_keep_state_uninstall(deployment):
    installed, _, service, events, env, run = deployment
    oneshot = Path(str(service)+'-refresh.service'); timer = Path(str(service)+'-refresh.timer')
    oneshot.write_text('old refresh service\n'); timer.write_text('old timer\n')
    (installed/'state').mkdir(mode=0o700)
    marker = installed/'state/stop-marker'; env['TEST_STOP_MARKER'] = str(marker)
    result = run(); assert result.returncode == 0, result.stdout+result.stderr
    assert_refresh_units(installed, service, events)
    log = events.read_text()
    assert log.index('systemctl stop clash-yaml-manager-refresh.timer') < log.index('systemctl stop clash-yaml-manager-refresh.service')
    assert log.index('systemctl stop clash-yaml-manager-refresh.service') < log.index('systemctl stop clash-yaml-manager\n')
    backup = next(installed.parent.glob('upgrade-backup-*'))
    assert (backup/oneshot.name).read_text() == 'old refresh service\n'
    assert (backup/timer.name).read_text() == 'old timer\n'
    assert (backup/'state/stop-marker').read_text() == 'stopped\n'
    result = run('uninstall.sh',input_text='n\n'); assert result.returncode == 0, result.stderr
    assert not oneshot.exists() and not timer.exists() and not service.exists()
    assert marker.read_text() == 'stopped\n'
    log = events.read_text().split('systemctl enable --now clash-yaml-manager-refresh.timer')[-1]
    assert log.index('systemctl stop clash-yaml-manager-refresh.timer') < log.index('systemctl disable clash-yaml-manager-refresh.timer')
    assert log.index('systemctl disable clash-yaml-manager-refresh.timer') < log.index('systemctl stop clash-yaml-manager-refresh.service')
    assert log.index('systemctl stop clash-yaml-manager-refresh.service') < log.index('systemctl stop clash-yaml-manager\n')


@pytest.mark.parametrize('script', ['update.sh', 'uninstall.sh'])
@pytest.mark.parametrize('unit', ['clash-yaml-manager-refresh.timer', 'clash-yaml-manager-refresh.service'])
def test_refresh_stop_failure_aborts_before_state_backup_or_code_delete(deployment, script, unit):
    installed, _, _, events, env, run = deployment
    env['TEST_FAIL_STOP'] = unit
    result = run(script,input_text='y\ny\n'); assert result.returncode != 0
    assert (installed/'app.py').read_text() == 'VERSION = "old"\n'
    assert 'systemctl stop clash-yaml-manager\n' not in events.read_text()
    assert not list(installed.parent.glob('upgrade-backup-*/state'))


def test_refresh_real_systemd_verify_if_available(deployment):
    # Run only against temp fixture units; never register/start anything on the host.
    installed, _, service, events, _, run = deployment
    result = run(); assert result.returncode == 0, result.stderr
    oneshot, timer = assert_refresh_units(installed, service, events)
    analyze = shutil.which('systemd-analyze')
    if analyze:
        # Unit filenames must match the timer's explicit Unit= target for verification.
        directory = service.parent/'verify'; directory.mkdir()
        shutil.copy2(oneshot,directory/'clash-yaml-manager-refresh.service')
        shutil.copy2(timer,directory/'clash-yaml-manager-refresh.timer')
        result = subprocess.run([analyze,'verify',str(directory/'clash-yaml-manager-refresh.service'),
            str(directory/'clash-yaml-manager-refresh.timer')],capture_output=True,text=True,timeout=15)
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('script', ['install.sh', 'update.sh', 'remote-install.sh', 'remote-update.sh', 'uninstall.sh', 'scripts/deploy-common.sh'])
def test_shell_syntax(script):
    result = subprocess.run(['bash', '-n', str(ROOT / script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_upgrade_preserves_existing_state_and_ignores_source_state(deployment):
    installed, source, _, _, _, run = deployment
    from core.security import AuthStore
    store = AuthStore(installed / 'state')
    original = store.initialize({'APP_PASSWORD': 'current state password'})
    (installed / 'state/login_attempts.json').write_text('{"version": 1, "ips": {}}')
    (source / 'state').mkdir()
    (source / 'state/auth.json').write_text('untrusted source state')
    before = store.path.read_bytes()
    result = run()
    assert result.returncode == 0, result.stderr
    assert store.path.read_bytes() == before
    assert store.authenticate('current state password')['auth_version'] == original['auth_version']
    assert not store.authenticate('test')
    assert (installed / 'state/login_attempts.json').exists()
    backup = next(installed.parent.glob('upgrade-backup-*'))
    assert (backup / 'state/auth.json').read_bytes() == before


def test_script_migration_failure_preserves_env_and_old_code(deployment):
    installed, _, _, events, _, run = deployment
    original = b'APP_PASSWORD_HASH=not-a-hash\nAPP_PORT=8899\nSECRET_KEY=unchanged\n'
    (installed / '.env').write_bytes(original)
    result = run()
    assert result.returncode != 0
    assert (installed / '.env').read_bytes() == original
    assert (installed / 'app.py').read_text() == 'VERSION = "old"\n'
    assert 'systemctl restart' not in events.read_text()
    assert '回滚' in result.stderr


def test_existing_unrelated_user_is_never_repurposed(deployment):
    installed, _, _, events, env, run = deployment
    Path(env['TEST_ACCOUNT']).write_text('clashyaml:x:998:998:Other app:/other:/bin/bash\n')
    result = run()
    assert result.returncode != 0
    assert 'systemctl stop' not in events.read_text()
    assert 'useradd' not in events.read_text() and 'userdel' not in events.read_text()
    assert (installed / 'app.py').read_text() == 'VERSION = "old"\n'


@pytest.mark.parametrize('choice', ['n\n', 'y\n\n'])
def test_uninstall_managed_user_and_auth_state(deployment, choice):
    installed, _, _, events, env, run = deployment
    assert run().returncode == 0
    before = (installed / 'state/auth.json').read_bytes()
    result = run('uninstall.sh', input_text=choice)
    assert result.returncode == 0, result.stderr
    if choice.startswith('n'):
        assert (installed / 'state/auth.json').read_bytes() == before
        assert Path(env['TEST_ACCOUNT']).exists()
        assert 'userdel' not in events.read_text()
    else:
        assert not installed.exists()
        assert not Path(env['TEST_ACCOUNT']).exists()
        log = events.read_text()
        assert log.rindex('systemctl stop') < log.index('userdel clashyaml')
        backup = next(installed.parent.glob('uninstall-backup-*'))
        assert (backup / 'state/auth.json').read_bytes() == before
        assert (backup / '.env').exists() and (backup / 'outputs/keep').exists()
        assert (backup / 'VERSION').exists() and (backup / 'INSTALLATION.json').exists()


def test_uninstall_never_deletes_unmanaged_user(deployment):
    installed, _, _, events, env, run = deployment
    Path(env['TEST_ACCOUNT']).write_text('clashyaml:x:998:998:Other app:/other:/bin/bash\n')
    result = run('uninstall.sh', input_text='y\nn\n')
    assert result.returncode == 0, result.stderr
    assert not installed.exists() and Path(env['TEST_ACCOUNT']).exists()
    assert 'userdel' not in events.read_text()


def test_low_port_grants_only_bind_capability(deployment):
    installed, _, service, _, _, run = deployment
    path = installed / '.env'
    path.write_text(path.read_text().replace('APP_PORT=8899', 'APP_PORT=80'))
    result = run()
    assert result.returncode == 0, result.stderr
    assert 'User=clashyaml' in service.read_text()
    assert 'AmbientCapabilities=CAP_NET_BIND_SERVICE' in service.read_text()
    assert 'CapabilityBoundingSet=CAP_NET_BIND_SERVICE' in service.read_text()


def test_gunicorn_flag_and_dependency_floor_are_compatible(deployment):
    from packaging.requirements import Requirement
    requirement = next(Requirement(line) for line in (ROOT / 'requirements.txt').read_text().splitlines()
                       if line.lower().startswith('gunicorn'))
    assert str(requirement.specifier) == '>=25.1.0'
    assert not any(version in requirement.specifier for version in ('21.2.0', '22.0.0', '23.0.0', '25.0.0'))
    installed, source, service, events, _, run = deployment
    (installed / 'requirements.txt').write_text('gunicorn>=21.2.0\n')
    result = run()
    assert result.returncode == 0, result.stderr
    assert '--no-control-socket' in service.read_text()
    assert (installed / 'requirements.txt').read_bytes() == (ROOT / 'requirements.txt').read_bytes()
    log = events.read_text()
    assert log.index(f'pip install -r {source}/requirements.txt') < log.index('systemctl restart')


@pytest.mark.parametrize('fail_first', [0, 1, 2, 5])
@pytest.mark.parametrize('channel', ['stable', 'main'])
def test_update_waits_for_readiness_in_both_channels(deployment, fail_first, channel):
    import json
    from core.install_info import make_install_info, read_install_info
    installed, source, _, _, env, run = deployment
    version = (source / 'VERSION').read_text().strip()
    incoming = source.parent / 'incoming.json'
    incoming.write_text(json.dumps(make_install_info(channel, version, 'b'*40,
                                                    'v'+version if channel == 'stable' else None)))
    env.update(CLASH_DEPLOY_METADATA=str(incoming), TEST_FAIL_FIRST=str(fail_first))
    result = run()
    assert result.returncode == 0, result.stderr
    assert result.stdout.count('not ready') == fail_first
    assert result.stdout.index(f'attempt {fail_first + 1}/30: PASS') < result.stdout.index('升级完成。')
    assert 'curl: (7)' not in result.stderr
    assert read_install_info(installed)['channel'] == channel


@pytest.mark.parametrize('failure_env', [dict(TEST_HEALTH_FAIL='7'), dict(TEST_INACTIVE='3'),
                                       dict(TEST_HTTP_STATUS='500'), dict(TEST_HTTP_STATUS='302')])
def test_readiness_failures_never_report_update_success(deployment, failure_env):
    _, _, _, events, env, run = deployment
    env.update(failure_env)
    result = run()
    assert result.returncode != 0
    assert 'Health check FAILED' in result.stderr and '回滚' in result.stderr
    assert ': PASS' not in result.stdout and '升级完成' not in result.stdout
    assert result.stdout.count('not ready') == 30
    assert 'http://127.0.0.1:8899/healthz' in events.read_text()


def test_readiness_deadline_counts_slow_http_attempts(deployment):
    """A slow response must not restart the budget or become a late success."""
    installed, _, _, _, env, _ = deployment
    commands = Path(env['PATH'].split(os.pathsep)[0])
    executable(commands / 'curl', '/bin/sleep 2\necho 200\n')
    result = subprocess.run(['bash', '-c', 'source "$1"; wait_for_application 1',
                             'health-test', str(ROOT / 'scripts/deploy-common.sh')],
                            env=dict(env, INSTALL_DIR=str(installed), SERVICE_NAME='clash-yaml-manager',
                                     APP_PORT='8899'), capture_output=True, text=True, timeout=5)
    assert result.returncode != 0
    assert 'Health check FAILED' in result.stderr
    assert ': PASS' not in result.stdout
    assert result.stdout.count('not ready') == 1


def test_readiness_curl_timeout_is_bounded_by_remaining_budget(deployment):
    installed, _, _, events, env, _ = deployment
    env['TEST_HEALTH_FAIL'] = '28'
    result = subprocess.run(['bash', '-c', 'source "$1"; wait_for_application 1',
                             'health-test', str(ROOT / 'scripts/deploy-common.sh')],
                            env=dict(env, INSTALL_DIR=str(installed), SERVICE_NAME='clash-yaml-manager',
                                     APP_PORT='8899'), capture_output=True, text=True, timeout=5)
    assert result.returncode != 0
    assert '--max-time 1' in events.read_text()
    assert '--connect-timeout 1' in events.read_text()
    assert '--noproxy *' in events.read_text()
    assert 'Health check FAILED' in result.stderr
