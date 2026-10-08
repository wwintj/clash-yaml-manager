"""Synthetic backup contracts: no runtime imports, accounts, services or VPS."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from conftest import ROOT
from scripts import backup_audit as audit


SECRET = 'fixture-private-secret-勿輸出'
TOKEN = 'fixture-subscription-bearer-token'
URI = 'vless://fixture-credential@example.invalid:443'
URL = 'https://example.invalid/s/' + TOKEN
HASH = 'fixture-password-hash'


def put(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding='utf-8')
    return path


def identity(version='1.7.0'):
    return dict(channel='stable', base_version=version, commit='a' * 40,
                tag='v' + version, installed_at='2026-10-08T00:00:00+00:00', source='github-release')


@pytest.fixture
def updater(tmp_path):
    root = tmp_path / 'clash-yaml-manager-update-backup-20261008_120000.ABC123'
    root.mkdir()
    put(root, 'VERSION', '1.7.0\n')
    put(root, 'INSTALLATION.json', json.dumps(identity()))
    put(root, '.env', 'SECRET_KEY="' + SECRET + '"\nAPP_PASSWORD="  密碼  "\n')
    put(root, 'defaults/default.yaml', 'proxies: []\nrules: []\n')
    put(root, 'app.py', 'raise RuntimeError("' + SECRET + '")\n')
    put(root, 'core/state.py', 'raise RuntimeError("' + SECRET + '")\n')
    put(root, 'templates/index.html', '<html>overlay</html>\n')
    put(root, 'static/ui.css', ':root { color: black; }\n')
    put(root, 'requirements.txt', 'Flask>=3.0\n')
    put(root, 'state/auth.json', json.dumps(dict(password_hash=HASH, auth_version=SECRET)))
    put(root, 'state/fixed_subscriptions.json', json.dumps(dict(token=TOKEN, url=URL, node=URI)))
    put(root, 'state/' + TOKEN + '.json', json.dumps(dict(secret=SECRET)))
    put(root, audit.UNIT + '.service', '[Unit]\nDescription=fixture\n[Service]\nExecStart=/not/executed\n')
    for category in ('refresh', 'health'):
        put(root, audit.UNIT + '-' + category + '.service', '[Unit]\n[Service]\nExecStart=/not/executed\n')
        put(root, audit.UNIT + '-' + category + '.timer', '[Unit]\n[Timer]\nOnCalendar=daily\n')
    (root / 'venv/bin').mkdir(parents=True)
    (root / 'venv/bin/python').symlink_to(sys.executable)
    put(root, 'scripts/tool.py', 'raise RuntimeError("never executed")\n')
    return root


def component(report, name):
    return next(item for item in report['components'] if item['component'] == name)


def codes(report):
    return set(report['validation_codes']) | {code for c in report['components'] for code in c['validation_codes']}


def private_output(report, root=None):
    for output in (audit.render(report), audit.render(report, True)):
        for secret in (SECRET, TOKEN, URI, URL, HASH, str(root) if root else 'do-not-print-this-path'):
            assert secret not in output
        assert 'restore_proven' in output
    assert report['restore_proven'] is False


def frozen_tree(root):
    """Non-atime metadata + bytes; don't dereference venv or any unsafe link."""
    result = {}
    for directory, _, names in os.walk(root, followlinks=False):
        folder = Path(directory)
        result[str(folder.relative_to(root))] = (audit.fingerprint(folder.lstat()), None)
        for name in names:
            path = folder / name
            info = path.lstat()
            result[str(path.relative_to(root))] = (audit.fingerprint(info),
                os.readlink(path) if path.is_symlink() else path.read_bytes())
    return result


def test_complete_updater_and_read_only_bytes_metadata(updater, monkeypatch):
    before = frozen_tree(updater)
    def no_mutation(*args, **kwargs):
        pytest.fail('audit attempted mutation')
    for name in ('chmod', 'chown', 'fchmod', 'fchown', 'mkdir', 'unlink', 'remove', 'rename', 'replace', 'system'):
        monkeypatch.setattr(os, name, no_mutation)
    report = audit.audit(updater)
    assert report['backup_type'] == audit.UPDATER
    assert report['structural_status'] == 'STRUCTURALLY_COMPLETE'
    assert frozen_tree(updater) == before
    assert component(report, 'VENV')['validation_codes'] == ['VENV_CONTENTS_NOT_INSPECTED']
    assert 'NO_TRUSTED_MANIFEST' in codes(report)
    assert 'BUSINESS_SCHEMA_NOT_CHECKED' in codes(report)
    assert 'CONTENT_SEMANTICS_NOT_CHECKED' in codes(report)
    assert component(report, 'OUTPUTS')['requirement'] == 'NOT_APPLICABLE'
    private_output(report, updater)


@pytest.mark.parametrize('name, category', [
    ('VERSION', 'VERSION'), ('.env', 'ENVIRONMENT'), ('app.py', 'APPLICATION'),
    ('defaults/default.yaml', 'DEFAULT_YAML'), ('templates/index.html', 'TEMPLATES'),
    ('static/ui.css', 'STATIC'), ('requirements.txt', 'DEPENDENCY_SPEC'),
    (audit.UNIT + '.service', 'SERVICE_UNIT'),
])
def test_missing_required(updater, name, category):
    (updater / name).unlink()
    report = audit.audit(updater)
    assert report['structural_status'] == 'STRUCTURALLY_INCOMPLETE'
    assert component(report, category)['status'] == 'MISSING'
    assert 'MISSING_REQUIRED' in codes(report)
    private_output(report, updater)


@pytest.mark.parametrize('name, category', [
    ('INSTALLATION.json', 'INSTALLATION_METADATA'),
    (audit.UNIT + '-refresh.timer', 'REFRESH_UNITS'),
    (audit.UNIT + '-health.service', 'HEALTH_UNITS'),
])
def test_missing_optional_not_whole_backup_failure(updater, name, category):
    (updater / name).unlink()
    report = audit.audit(updater)
    assert report['structural_status'] == 'STRUCTURALLY_COMPLETE'
    assert component(report, category)['requirement'] == 'OPTIONAL'
    assert component(report, category)['status'] == 'MISSING'
    assert 'MISSING_OPTIONAL' in codes(report)


def test_uninstall_data_only(tmp_path):
    root = tmp_path / 'clash-yaml-manager-backup-20261008_120000'
    put(root, '.env', 'SECRET_KEY=' + SECRET)
    put(root, 'state/auth.json', json.dumps(dict(password_hash=HASH)))
    put(root, 'outputs/' + TOKEN + '.yaml', 'opaque generated private data ' + URI)
    (root / 'backups').mkdir()
    before = frozen_tree(root)
    report = audit.audit(root)
    assert report['backup_type'] == audit.UNINSTALL
    assert report['structural_status'] == 'STRUCTURALLY_COMPLETE'
    assert component(report, 'APPLICATION')['status'] == 'NOT_APPLICABLE'
    assert component(report, 'SERVICE_UNIT')['status'] == 'NOT_APPLICABLE'
    assert component(report, 'VERSION')['status'] == 'MISSING'
    assert component(report, 'PRIOR_BACKUPS')['status'] == 'PRESENT'
    assert frozen_tree(root) == before
    private_output(report, root)


def test_ui_only(tmp_path):
    root = tmp_path / 'clash-yaml-manager-v1.7-ui-acceptance-20261008-120000'
    put(root, 'VERSION', '1.7.0\n')
    put(root, 'templates/index.html', 'fixture template')
    put(root, 'static/ui.css', 'fixture CSS')
    put(root, 'baseline.json', SECRET)  # Not claimed to be an original trusted manifest.
    report = audit.audit(root)
    assert report['backup_type'] == audit.OVERLAY
    assert report['structural_status'] == 'STRUCTURALLY_COMPLETE'
    assert component(report, 'STATE')['requirement'] == 'NOT_APPLICABLE'
    assert component(report, 'ENVIRONMENT')['requirement'] == 'NOT_APPLICABLE'
    private_output(report, root)


@pytest.mark.parametrize('name', ['manual-backup', 'clash-yaml-manager-update-backup-random',
    'clash-yaml-manager-v1.7-production-20261008-120000-ABC123'])
def test_unknown_never_reads_contents(tmp_path, monkeypatch, name):
    root = tmp_path / name
    put(root, 'state/auth.json', SECRET)
    monkeypatch.setattr(os, 'read', lambda *a: pytest.fail('unknown layout read private contents'))
    report = audit.audit(root)
    assert report['backup_type'] == report['structural_status'] == 'UNKNOWN'
    private_output(report, root)


def test_ambiguous_named_uninstall_is_unknown(tmp_path):
    root = tmp_path / 'clash-yaml-manager-backup-20261008_120000'
    put(root, '.env', SECRET)
    put(root, 'app.py', 'print("not a data-only backup")')
    assert audit.audit(root)['backup_type'] == 'UNKNOWN'


@pytest.mark.parametrize('target', ['missing', 'external'])
def test_symlink_not_followed(updater, tmp_path, monkeypatch, target):
    external = put(tmp_path, 'private-external', SECRET)
    path = updater / '.env'
    path.unlink()
    path.symlink_to(external if target == 'external' else tmp_path / 'nonexistent')
    original_open = os.open
    def guarded(name, flags, *args, **kwargs):
        assert name not in (str(external), '.env')
        return original_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', guarded)
    report = audit.audit(updater)
    assert report['structural_status'] == 'UNSAFE'
    assert component(report, 'ENVIRONMENT')['status'] == 'UNSAFE'
    private_output(report, updater)


@pytest.mark.parametrize('ancestor', [False, True])
def test_root_or_ancestor_symlink(tmp_path, updater, ancestor):
    link = tmp_path / 'link'
    link.symlink_to(updater.parent if ancestor else updater, target_is_directory=True)
    report = audit.audit(link / updater.name if ancestor else link)
    assert report['structural_status'] == 'UNSAFE'
    assert 'UNSAFE_ROOT_PATH' in codes(report)


@pytest.mark.parametrize('object_kind', ['fifo', 'socket', 'directory'])
def test_special_object_or_directory_in_file_position(updater, monkeypatch, object_kind):
    path = updater / '.env'
    path.unlink()
    server = None
    if object_kind == 'fifo':
        os.mkfifo(path)
    elif object_kind == 'socket':
        server = socket.socket(socket.AF_UNIX)
        monkeypatch.chdir(updater)  # AF_UNIX has a short path limit on macOS/Linux.
        server.bind('.env')
    else:
        path.mkdir()
        put(path, SECRET, SECRET)
    original_open = os.open
    def guarded(name, flags, *args, **kwargs):
        assert name != '.env'
        return original_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', guarded)
    try:
        report = audit.audit(updater)
        assert report['structural_status'] == 'UNSAFE'
        private_output(report, updater)
    finally:
        if server:
            server.close()


def test_nested_state_symlink_and_hardlink(updater, tmp_path):
    external = put(tmp_path, 'external-secret', SECRET)
    link = updater / 'state' / SECRET
    link.symlink_to(external)
    assert audit.audit(updater)['structural_status'] == 'UNSAFE'
    link.unlink()
    os.link(external, link)
    assert audit.audit(updater)['structural_status'] == 'UNSAFE'


@pytest.mark.parametrize('name, content', [
    ('INSTALLATION.json', '{"' + SECRET + '":'),
    ('INSTALLATION.json', json.dumps(dict(password=SECRET))),
    ('INSTALLATION.json', json.dumps(identity('1.6.0'))),
    ('state/auth.json', '{"password_hash":"' + HASH + '",'),
    ('state/auth.json', '{"password":1,"password":2}'),
    ('state/auth.json', '{"x":NaN}'),
    ('VERSION', '1.7.0\n' + SECRET),
    ('app.py', 'def ' + SECRET),
    (audit.UNIT + '.service', SECRET),
    ('.env', ''),
], ids=['broken-json', 'wrong-schema', 'version-mismatch', 'broken-state',
        'duplicate-key', 'nonstandard-json', 'invalid-version', 'invalid-python',
        'invalid-unit', 'empty-env'])
def test_invalid_content_not_valid_by_existence(updater, name, content):
    put(updater, name, content)
    report = audit.audit(updater)
    assert report['structural_status'] == 'STRUCTURALLY_INCOMPLETE'
    assert any(item['status'] == 'INVALID' for item in report['components'])
    private_output(report, updater)


def test_oversized_file_bounded_and_not_read(updater, monkeypatch):
    put(updater, 'state/auth.json', SECRET + 'x' * audit.MAX_FILE_BYTES)
    original_open = os.open
    def guarded(name, flags, *args, **kwargs):
        assert name != 'auth.json'
        return original_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', guarded)
    report = audit.audit(updater)
    assert report['structural_status'] == 'STRUCTURALLY_INCOMPLETE'
    assert 'FILE_SIZE_LIMIT' in codes(report)
    private_output(report, updater)


def test_permission_denied_sanitized(updater, monkeypatch):
    original_open = os.open
    def denied(name, flags, *args, **kwargs):
        if name == '.env':
            raise PermissionError(13, SECRET, str(updater / '.env'))
        return original_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', denied)
    report = audit.audit(updater)
    assert report['structural_status'] == 'STRUCTURALLY_INCOMPLETE'
    assert 'PERMISSION_DENIED' in codes(report)
    private_output(report, updater)


@pytest.mark.parametrize('change', ['write', 'replace', 'symlink'])
def test_changed_during_inspection_detected(updater, monkeypatch, change):
    original = audit.Inspector.read
    changed = False
    def racing(self, fd, path, records):
        nonlocal changed
        data = original(self, fd, path, records)
        if path == ('VERSION',) and not changed:
            target = updater / 'VERSION'
            if change == 'write':
                target.write_text('1.6.0\n')
            else:
                target.unlink()
                if change == 'replace':
                    target.write_bytes(data)
                else:
                    target.symlink_to(updater / '.env')
            changed = True
        return data
    monkeypatch.setattr(audit.Inspector, 'read', racing)
    report = audit.audit(updater)
    assert report['structural_status'] == 'UNSAFE'
    assert 'BACKUP_CHANGED' in codes(report)
    private_output(report, updater)


def test_file_swapped_between_stat_and_open_never_followed(updater, monkeypatch):
    original_open = os.open
    def racing(name, flags, *args, **kwargs):
        if name == '.env':
            path = updater / '.env'
            path.unlink()
            path.symlink_to(updater / 'state/auth.json')
        return original_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', racing)
    report = audit.audit(updater)
    assert report['structural_status'] == 'UNSAFE'
    private_output(report, updater)


@pytest.mark.parametrize('limit, value, code', [
    ('MAX_ENTRIES', 5, 'ENTRY_LIMIT'), ('MAX_DEPTH', 0, 'DEPTH_LIMIT'),
    ('MAX_TOTAL_BYTES', 8, 'TOTAL_READ_LIMIT'), ('MAX_SECONDS', -1, 'TIME_LIMIT'),
])
def test_resource_limits_fail_closed(updater, monkeypatch, limit, value, code):
    monkeypatch.setattr(audit, limit, value)
    report = audit.audit(updater)
    assert report['structural_status'] != 'STRUCTURALLY_COMPLETE'
    assert code in codes(report)
    private_output(report, updater)


def test_known_live_installation_refused_before_open(monkeypatch):
    monkeypatch.setattr(os, 'open', lambda *args, **kwargs: pytest.fail('live tree opened'))
    report = audit.audit('/opt/clash-yaml-manager/state')
    assert report['structural_status'] == 'UNSAFE'
    assert 'LIVE_INSTALLATION_REFUSED' in codes(report)


def test_only_read_only_open_flags(updater, monkeypatch):
    original_open = os.open
    def guarded(name, flags, *args, **kwargs):
        assert flags & os.O_ACCMODE == os.O_RDONLY
        assert not flags & (os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        assert flags & os.O_NOFOLLOW
        assert flags & os.O_NONBLOCK
        return original_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', guarded)
    assert audit.audit(updater)['structural_status'] == 'STRUCTURALLY_COMPLETE'


@pytest.mark.parametrize('as_json', [False, True])
def test_cli_exit_and_safe_output(updater, as_json):
    before = frozen_tree(updater)
    completed = subprocess.run([sys.executable, str(ROOT / 'scripts/backup_audit.py'), '--path', str(updater)]
                              + (['--json'] if as_json else []), capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0 and not completed.stderr
    for secret in (SECRET, TOKEN, URI, URL, HASH, str(updater)):
        assert secret not in completed.stdout
    if as_json:
        assert json.loads(completed.stdout)['restore_proven'] is False
    else:
        assert 'restore_proven: false' in completed.stdout
    assert frozen_tree(updater) == before


def test_cli_argparse_errors_do_not_echo_credentials(capsys):
    assert audit.main(['--json', '--secret=' + SECRET]) == 64
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    assert json.loads(captured.out)['validation_codes'] == ['INVALID_ARGUMENTS']


@pytest.mark.parametrize('path', ['x/../private', '\x00' + SECRET], ids=['parent-traversal', 'null-byte'])
def test_invalid_paths_are_sanitized(path):
    report = audit.audit(path)
    assert 'INVALID_PATH' in codes(report)
    private_output(report)


def test_path_resource_limit_before_open(monkeypatch):
    monkeypatch.setattr(os, 'open', lambda *args, **kwargs: pytest.fail('oversized path opened'))
    assert 'PATH_LIMIT' in codes(audit.audit('/' + '/'.join(['fixture'] * 65)))


def test_device_not_opened(updater, monkeypatch):
    import stat
    original_stat = os.stat
    def device(name, *args, **kwargs):
        info = original_stat(name, *args, **kwargs)
        if name == 'auth.json':
            fields = list(info)
            fields[0] = stat.S_IFCHR | 0o600
            return os.stat_result(fields)
        return info
    original_open = os.open
    def guarded(name, flags, *args, **kwargs):
        assert name != 'auth.json'
        return original_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'stat', device)
    monkeypatch.setattr(os, 'open', guarded)
    report = audit.audit(updater)
    assert report['structural_status'] == 'UNSAFE'
    private_output(report, updater)


@pytest.mark.parametrize('name', ['core', 'venv', 'state'])
def test_directory_component_cannot_be_link(updater, tmp_path, name):
    # Keep original synthetic material without deleting any backup data.
    (updater / name).rename(tmp_path / ('original-' + name))
    (updater / name).symlink_to(tmp_path / ('original-' + name), target_is_directory=True)
    assert audit.audit(updater)['structural_status'] == 'UNSAFE'


def test_missing_and_empty_state_required(updater, tmp_path):
    (updater / 'state').rename(tmp_path / 'original-state')
    report = audit.audit(updater)
    assert report['structural_status'] == 'STRUCTURALLY_INCOMPLETE'
    assert component(report, 'STATE')['status'] == 'MISSING'
    (updater / 'state').mkdir()
    report = audit.audit(updater)
    assert report['structural_status'] == 'STRUCTURALLY_INCOMPLETE'
    assert 'REQUIRED_CONTENT_ABSENT' in codes(report)


def test_growth_during_read_bounded_and_detected(updater, monkeypatch):
    original_read = os.read
    grew = False
    def grow(fd, size):
        nonlocal grew
        data = original_read(fd, size)
        if not grew:
            with (updater / 'VERSION').open('ab') as target:
                target.write(b'\n')
            grew = True
        return data
    monkeypatch.setattr(os, 'read', grow)
    report = audit.audit(updater)
    assert report['structural_status'] == 'UNSAFE'
    assert 'BACKUP_CHANGED' in codes(report)


def test_directory_entry_added_during_inspection(updater, monkeypatch):
    original = audit.Inspector.read
    def race(self, fd, path, records):
        data = original(self, fd, path, records)
        if path == ('VERSION',):
            put(updater, SECRET, SECRET)
        return data
    monkeypatch.setattr(audit.Inspector, 'read', race)
    report = audit.audit(updater)
    assert report['structural_status'] == 'UNSAFE'
    private_output(report, updater)


def test_cli_status_codes(updater, tmp_path, capsys):
    (updater / 'VERSION').unlink()
    assert audit.main(['--path', str(updater), '--json']) == 1
    (updater / '.env').unlink()
    os.mkfifo(updater / '.env')
    assert audit.main(['--path', str(updater), '--json']) == 2
    unknown = tmp_path / 'unknown'
    unknown.mkdir()
    assert audit.main(['--path', str(unknown), '--json']) == 3
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
    assert str(updater) not in output.out
