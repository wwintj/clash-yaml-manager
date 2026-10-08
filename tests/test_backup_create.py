"""Synthetic quiet offline trees only. Independent anchor storage is a fixture simulation."""
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

from conftest import ROOT
from scripts import backup_create as writer
from scripts import backup_manifest as protocol
from scripts import backup_verify as verifier


SECRET = 'writer-fixture-password-token-勿輸出'


@pytest.fixture
def offline(tmp_path):
    parent = tmp_path / 'private-parent'
    parent.mkdir(mode=0o700)
    source = parent / 'source'
    source.mkdir(mode=0o700)
    (source / 'data').mkdir(mode=0o750)
    (source / 'empty').mkdir(mode=0o700)
    (source / 'VERSION').write_bytes(b'1.7.0\n')
    (source / '.env').write_bytes(b'\x00\xff' + SECRET.encode())
    (source / 'app.py').write_text('raise RuntimeError("snapshot code must not execute")\n')
    (source / 'data' / (SECRET + '.bin')).write_bytes(b'\x00\xff' + SECRET.encode())
    (source / 'app.py').chmod(0o755)
    return source, parent / 'snapshot'


def run(offline, **kwargs):
    source, destination = offline
    return writer.create(source, destination, 'UPDATER_SNAPSHOT', **kwargs)


def frozen(root):
    values = {}
    for folder, dirs, names in os.walk(root, followlinks=False):
        folder = Path(folder)
        values[folder.relative_to(root).as_posix()] = (verifier.fingerprint(folder.lstat()), None)
        for name in names:
            path = folder / name
            values[path.relative_to(root).as_posix()] = (verifier.fingerprint(path.lstat()), path.read_bytes())
    return values


def safe(report, offline):
    assert report['restore_proven'] is False
    assert report['trust_anchor_verified'] is False
    for output in (writer.render(report), writer.render(report, True)):
        assert SECRET not in output
        assert str(offline[0]) not in output
        assert str(offline[1]) not in output


def failed(report, offline, code, cleanup='CLEANED'):
    assert report['creation_status'] == 'FAILED'
    assert report['MANIFEST_SHA256'] is None
    assert code in report['validation_codes']
    assert report['publication_status'] == 'NOT_PUBLISHED'
    assert not offline[1].exists()
    assert report['cleanup_status'] == cleanup
    if cleanup == 'FAILED':
        assert 'CLEANUP_FAILED' in report['validation_codes']
        assert report['residual_staging_name'].startswith('.backup-create-')
        assert (offline[1].parent / report['residual_staging_name']).exists()
    else:
        assert report['residual_staging_name'] is None
        assert not list(offline[1].parent.glob('.backup-create-*'))
    safe(report, offline)


def test_create_actual_verifier_and_canonical_stored_metadata(offline, monkeypatch):
    source, destination = offline
    before = frozen(source)
    calls = []
    actual = verifier.verify
    def observed(path, *args, **kwargs):
        result = actual(path, *args, **kwargs)
        calls.append((Path(path).name, result))
        return result
    monkeypatch.setattr(verifier, 'verify', observed)
    report = run(offline)
    assert report['creation_status'] == 'CREATED'
    assert report['publication_status'] == 'PUBLISHED'
    assert report['cleanup_status'] == 'NOT_NEEDED'
    assert report['retained_destination'] is False
    assert len(calls) == 2 and calls[0][0].startswith('.backup-create-') and calls[1][0] == destination.name
    assert all(item[1]['verification_status'] == 'INTERNALLY_CONSISTENT' for item in calls)
    raw = (destination / protocol.MANIFEST_NAME).read_bytes()
    manifest = protocol.load_manifest(raw)
    assert raw == protocol.canonical_bytes(manifest)
    assert report['MANIFEST_SHA256'] == hashlib.sha256(raw).hexdigest()
    assert manifest['snapshot_scope'] == 'FULL_TREE' and manifest['exclusions'] == []
    assert manifest['root_metadata'] == writer.metadata(destination.stat())
    assert manifest['root_metadata']['mode'] == '0700'
    assert [e['path'] for e in manifest['entries']] == sorted([e['path'] for e in manifest['entries']], key=lambda p: p.encode())
    for entry in manifest['entries']:
        stored = destination / entry['path']
        assert {k:entry[k] for k in ('mode', 'uid', 'gid')} == writer.metadata(stored.stat())
        if entry['type'] == 'file':
            assert entry['mode'] == '0600'
            assert entry['size'] == stored.stat().st_size
            assert entry['sha256'] == hashlib.sha256(stored.read_bytes()).hexdigest()
            assert stored.read_bytes() == (source / entry['path']).read_bytes()
        else:
            assert entry['mode'] == '0700' and entry['size'] is None and entry['sha256'] is None
    assert (destination / 'empty').is_dir() and not list((destination / 'empty').iterdir())
    assert (destination / protocol.MANIFEST_NAME).stat().st_mode & 0o777 == 0o600
    assert frozen(source) == before
    safe(report, offline)


@pytest.mark.parametrize('snapshot_type', protocol.SNAPSHOT_TYPES)
def test_snapshot_types(offline, snapshot_type):
    report = writer.create(*offline, snapshot_type)
    assert report['creation_status'] == 'CREATED'
    assert protocol.load_manifest((offline[1] / protocol.MANIFEST_NAME).read_bytes())['snapshot_type'] == snapshot_type


def test_independently_saved_fixture_anchor_and_one_byte_corruption(offline):
    report = run(offline)
    assert report['creation_status'] == 'CREATED'
    destination = offline[1]
    assert verifier.verify(destination)['verification_status'] == 'INTERNALLY_CONSISTENT'
    # Separate protected fixture file simulates handoff, not a production trust store.
    anchor_file = destination.parent / 'independent-fixture-anchor'
    anchor_file.write_text(report['MANIFEST_SHA256'])
    anchor_file.chmod(0o600)
    expected = anchor_file.read_text()
    trusted = verifier.verify(destination, expected)
    assert trusted['verification_status'] == 'TRUSTED_SCOPE_VERIFIED'
    assert trusted['trust_anchor_verified'] is True
    path = destination / 'VERSION'
    path.write_bytes(b'2' + path.read_bytes()[1:])
    corrupt = verifier.verify(destination, expected)
    assert corrupt['verification_status'] == 'NOT_VERIFIED'
    assert 'FILE_DIGEST_MISMATCH' in corrupt['validation_codes']
    assert corrupt['trust_anchor_verified'] is True
    assert corrupt['restore_proven'] is False


def test_deterministic_manifest_for_identical_sources(offline):
    first = run(offline)
    other = offline[1].parent / 'second'
    second = writer.create(offline[0], other, 'UPDATER_SNAPSHOT')
    assert first['creation_status'] == second['creation_status'] == 'CREATED'
    assert first['MANIFEST_SHA256'] == second['MANIFEST_SHA256']
    assert (offline[1] / protocol.MANIFEST_NAME).read_bytes() == (other / protocol.MANIFEST_NAME).read_bytes()


def test_chunked_copy_and_partial_writes(offline, monkeypatch):
    payload = b'ab\x00\xff' * (writer.CHUNK_BYTES // 4 + 23)
    (offline[0] / 'large').write_bytes(payload * 3)
    actual_read, actual_write = os.read, os.write
    lengths = []
    def bounded(fd, amount):
        assert amount <= writer.CHUNK_BYTES
        lengths.append(amount)
        return actual_read(fd, amount)
    def partial(fd, value):
        return actual_write(fd, value[:max(1, len(value) // 2)])
    monkeypatch.setattr(os, 'read', bounded)
    monkeypatch.setattr(os, 'write', partial)
    report = run(offline)
    assert report['creation_status'] == 'CREATED'
    assert writer.CHUNK_BYTES in lengths
    assert (offline[1] / 'large').read_bytes() == payload * 3


@pytest.mark.parametrize('reason', protocol.EXCLUSION_REASONS)
def test_explicit_exclusion_omits_payload_never_follows_venv(offline, reason):
    source = offline[0]
    venv = source / 'venv'
    venv.mkdir(mode=0o700)
    (venv / 'python').symlink_to('/nonexistent-external-python')
    (venv / 'secret').write_text(SECRET)
    report = run(offline, exclusions=[dict(path='venv', reason=reason)])
    assert report['creation_status'] == 'CREATED'
    manifest = protocol.load_manifest((offline[1] / protocol.MANIFEST_NAME).read_bytes())
    assert manifest['snapshot_scope'] == 'DECLARED_EXCLUSIONS'
    assert manifest['exclusions'] == [dict(path='venv', reason=reason)]
    assert (offline[1] / 'venv').is_dir() and not list((offline[1] / 'venv').iterdir())
    assert report['verification']['full_file_coverage'] is False
    assert 'EXCLUDED_CONTENT_NOT_VERIFIED' in report['verification']['validation_codes']
    assert (venv / 'python').is_symlink() and (venv / 'secret').read_text() == SECRET


def test_venv_without_explicit_exclusion_fails(offline):
    (offline[0] / 'venv').mkdir(mode=0o700)
    (offline[0] / 'venv/python').symlink_to('/nonexistent-external-python')
    failed(run(offline), offline, 'UNSAFE_OBJECT', 'NOT_NEEDED')


@pytest.mark.parametrize('exclusions,code', [
    ([dict(path='../bad', reason='OUT_OF_SCOPE')], 'NON_CANONICAL_PATH'),
    ([dict(path='missing', reason='OUT_OF_SCOPE')], 'INVALID_EXCLUSION'),
    ([dict(path='VERSION', reason='OUT_OF_SCOPE')], 'INVALID_EXCLUSION'),
    ([dict(path='data', reason='BAD')], 'INVALID_EXCLUSION'),
    ([dict(path='data', reason='OUT_OF_SCOPE')] * 2, 'DUPLICATE_EXCLUSION'),
    ([dict(path='data', reason='OUT_OF_SCOPE'), dict(path='data/nested', reason='OUT_OF_SCOPE')], 'EXCLUSION_CONFLICT'),
])
def test_invalid_exclusions(offline, exclusions, code):
    failed(run(offline, exclusions=exclusions), offline, code, 'NOT_NEEDED')


@pytest.mark.parametrize('object_type', ['file', 'directory', 'symlink'])
def test_existing_destination_never_overwritten(offline, object_type):
    source, destination = offline
    if object_type == 'file':
        destination.write_text(SECRET)
    elif object_type == 'directory':
        destination.mkdir(mode=0o700)
        (destination / 'original').write_text(SECRET)
    else:
        destination.symlink_to(source, target_is_directory=True)
    before = verifier.fingerprint(destination.lstat())
    report = run(offline)
    assert report['creation_status'] == 'FAILED' and 'DESTINATION_EXISTS' in report['validation_codes']
    assert report['cleanup_status'] == 'NOT_NEEDED'
    assert verifier.fingerprint(destination.lstat()) == before
    if object_type == 'directory':
        assert (destination / 'original').read_text() == SECRET
    safe(report, offline)


@pytest.mark.parametrize('race_kind', ['empty-directory', 'file', 'symlink'])
def test_real_no_replace_publication_race(offline, monkeypatch, race_kind):
    actual = writer.publication_function()
    def raced(parent_fd, stage, name):
        if race_kind == 'empty-directory':
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        elif race_kind == 'file':
            offline[1].write_text(SECRET)
        else:
            os.symlink('source', name, dir_fd=parent_fd)
        actual(parent_fd, stage, name)
    monkeypatch.setattr(writer, 'publication_function', lambda: raced)
    report = run(offline)
    assert report['creation_status'] == 'FAILED' and 'DESTINATION_EXISTS' in report['validation_codes']
    assert report['publication_status'] == 'NOT_PUBLISHED' and report['cleanup_status'] == 'CLEANED'
    assert not list(offline[1].parent.glob('.backup-create-*'))
    if race_kind == 'empty-directory':
        assert offline[1].is_dir() and list(offline[1].iterdir()) == []
    elif race_kind == 'file':
        assert offline[1].read_text() == SECRET
    else:
        assert offline[1].is_symlink() and os.readlink(offline[1]) == 'source'
    safe(report, offline)


@pytest.mark.parametrize('root', ['source', 'parent'])
def test_symlink_root_or_ancestor_rejected(offline, root):
    link = offline[1].parent / 'link'
    target = offline[0] if root == 'source' else offline[1].parent
    link.symlink_to(target, target_is_directory=True)
    paths = (link, offline[1]) if root == 'source' else (offline[0], link / 'snapshot')
    report = writer.create(*paths, 'UPDATER_SNAPSHOT')
    assert report['creation_status'] == 'FAILED'
    assert 'UNSAFE_ROOT_PATH' in report['validation_codes']
    assert report['cleanup_status'] == 'NOT_NEEDED'
    assert not offline[1].exists()


@pytest.mark.parametrize('object_type', ['symlink', 'broken-link', 'directory-link', 'fifo', 'hardlink', 'socket'])
def test_unsafe_source_objects_never_opened(offline, object_type, monkeypatch):
    path = offline[0] / 'unsafe'
    connection = None
    if object_type in ('symlink', 'broken-link', 'directory-link'):
        path.symlink_to(offline[0] / ('VERSION' if object_type == 'symlink' else 'data' if object_type == 'directory-link' else 'absent'))
    elif object_type == 'fifo':
        os.mkfifo(path)
    elif object_type == 'hardlink':
        os.link(offline[0] / 'VERSION', path)
    else:
        connection = socket.socket(socket.AF_UNIX)
        # AF_UNIX paths are short; chdir affects only this synthetic fixture.
        monkeypatch.chdir(offline[0])
        connection.bind('unsafe')
    actual = os.open
    def guarded(name, *args, **kwargs):
        assert name != 'unsafe'
        return actual(name, *args, **kwargs)
    monkeypatch.setattr(os, 'open', guarded)
    try:
        failed(run(offline), offline, 'UNSAFE_OBJECT', 'NOT_NEEDED')
    finally:
        if connection:
            connection.close()


@pytest.mark.parametrize('mode', [0o755, 0o770, 0o777])
def test_destination_parent_must_be_private(offline, mode):
    offline[1].parent.chmod(mode)
    failed(run(offline), offline, 'UNSAFE_DESTINATION_PARENT', 'NOT_NEEDED')


def test_unsafe_source_directory(offline):
    (offline[0] / 'data').chmod(0o777)
    failed(run(offline), offline, 'UNSAFE_SOURCE_DIRECTORY', 'NOT_NEEDED')


def test_read_permission_failure(offline):
    if os.geteuid() == 0:
        pytest.skip('root bypasses ordinary DAC read permissions')
    (offline[0] / 'VERSION').chmod(0)
    failed(run(offline), offline, 'PERMISSION_DENIED')


@pytest.mark.parametrize('mutation', ['append', 'replace', 'symlink', 'fifo'])
def test_source_changed_during_chunk_copy(offline, monkeypatch, mutation):
    actual = writer.Writer.write_all
    fired = False
    def mutate(self, fd, data):
        nonlocal fired
        actual(self, fd, data)
        if fired:
            return
        fired = True
        path = offline[0] / '.env'  # First copied file in UTF-8 order.
        if mutation == 'append':
            with path.open('ab') as stream:
                stream.write(b'change')
        elif mutation == 'replace':
            replacement = offline[0] / 'replacement'
            replacement.write_bytes(b'replaced')
            replacement.replace(path)
        else:
            path.unlink()
            if mutation == 'symlink':
                path.symlink_to(offline[0] / 'VERSION')
            else:
                os.mkfifo(path)
    monkeypatch.setattr(writer.Writer, 'write_all', mutate)
    failed(run(offline), offline, 'BACKUP_CHANGED')


@pytest.mark.parametrize('mutation', ['add', 'remove', 'mode', 'root-replace'])
def test_source_postcopy_set_metadata_and_root_changes(offline, monkeypatch, mutation):
    actual = writer.Writer.copy
    def mutate(self, fd, records):
        actual(self, fd, records)
        source = offline[0]
        if mutation == 'add':
            (source / 'extra').write_bytes(b'new')
        elif mutation == 'remove':
            (source / 'VERSION').unlink()
        elif mutation == 'mode':
            (source / 'VERSION').chmod(0o600)
        else:
            source.rename(source.parent / 'moved-source')
            source.mkdir(mode=0o700)
    monkeypatch.setattr(writer.Writer, 'copy', mutate)
    failed(run(offline), offline, 'BACKUP_CHANGED')


def test_source_changes_during_actual_verification(offline, monkeypatch):
    actual = verifier.verify
    def change(path):
        result = actual(path)
        assert result['verification_status'] == 'INTERNALLY_CONSISTENT'
        (offline[0] / 'VERSION').write_bytes(b'2.7.0\n')
        return result
    monkeypatch.setattr(verifier, 'verify', change)
    failed(run(offline), offline, 'BACKUP_CHANGED')


@pytest.mark.parametrize('limit,value,code', [
    ('MAX_FILE_BYTES', 1, 'FILE_BYTE_LIMIT'),
    ('MAX_TOTAL_BYTES', 1, 'TOTAL_BYTE_LIMIT'),
    ('MAX_ENTRIES', 2, 'ENTRY_LIMIT'),
    ('MAX_DEPTH', 1, 'DEPTH_LIMIT'),
    ('MAX_SECONDS', -1, 'TIME_LIMIT'),
])
def test_writer_resource_limits_no_publication(offline, monkeypatch, limit, value, code):
    monkeypatch.setattr(writer, limit, value)
    failed(run(offline), offline, code, 'NOT_NEEDED')


def test_control_bytes_count_towards_total_budget(offline, monkeypatch):
    total = sum(p.stat().st_size for p in offline[0].rglob('*') if p.is_file())
    monkeypatch.setattr(writer, 'MAX_TOTAL_BYTES', total + 10)
    failed(run(offline), offline, 'TOTAL_BYTE_LIMIT')


def test_actual_verifier_budget_failure_blocks_publication(offline, monkeypatch):
    actual = verifier.verify
    def bounded(path):
        with monkeypatch.context() as context:
            context.setattr(verifier, 'MAX_TOTAL_BYTES', 1)
            return actual(path)
    monkeypatch.setattr(verifier, 'verify', bounded)
    report = run(offline)
    failed(report, offline, 'VERIFICATION_FAILED')
    assert 'TOTAL_BYTE_LIMIT' in report['verification']['validation_codes']


@pytest.mark.parametrize('corruption,code,cleanup', [
    ('extra', 'UNLISTED_ENTRY', 'FAILED'),
    ('missing', 'LISTED_ENTRY_MISSING', 'FAILED'),
    ('corrupt', 'FILE_DIGEST_MISMATCH', 'CLEANED'),
])
def test_actual_verifier_detects_copied_tree_damage(offline, monkeypatch, corruption, code, cleanup):
    actual = verifier.verify
    def damaged(path):
        root = Path(path)
        if corruption == 'extra':
            (root / 'unowned-extra').write_text(SECRET)
        elif corruption == 'missing':
            (root / 'VERSION').unlink()
        else:
            file = root / 'VERSION'
            file.write_bytes(b'2' + file.read_bytes()[1:])
        return actual(path)
    monkeypatch.setattr(verifier, 'verify', damaged)
    report = run(offline)
    failed(report, offline, 'VERIFICATION_FAILED', cleanup)
    assert code in report['verification']['validation_codes']
    if corruption == 'extra':
        assert (offline[1].parent / report['residual_staging_name'] / 'unowned-extra').read_text() == SECRET


def test_manifest_generation_failure(offline, monkeypatch):
    def fail(*args):
        raise protocol.ManifestError('MANIFEST_SIZE_LIMIT')
    monkeypatch.setattr(protocol, 'canonical_bytes', fail)
    failed(run(offline), offline, 'MANIFEST_SIZE_LIMIT')


def test_rename_failure(offline, monkeypatch):
    def fail(*args):
        raise OSError(errno.EIO, SECRET)
    monkeypatch.setattr(writer, 'publication_function', lambda: fail)
    failed(run(offline), offline, 'READ_FAILED')


@pytest.mark.parametrize('stage', ['file', 'directory', 'parent-before', 'parent-after'])
def test_fsync_failure_boundary_and_retained_publication(offline, monkeypatch, stage):
    actual = os.fsync
    parent_id = writer.identity(offline[1].parent.stat())
    parent_calls = 0
    def fail(fd):
        nonlocal parent_calls
        info = os.fstat(fd)
        if writer.identity(info) == parent_id:
            parent_calls += 1
            if stage == 'parent-before' and parent_calls == 1 or stage == 'parent-after' and parent_calls == 2:
                raise OSError(errno.EIO, SECRET)
        elif stage == 'file' and stat.S_ISREG(info.st_mode) or stage == 'directory' and stat.S_ISDIR(info.st_mode):
            raise OSError(errno.EIO, SECRET)
        actual(fd)
    monkeypatch.setattr(os, 'fsync', fail)
    report = run(offline)
    if stage == 'parent-after':
        assert report['creation_status'] == 'FAILED' and report['publication_status'] == 'PUBLISHED'
        assert report['cleanup_status'] == 'NOT_ATTEMPTED_PUBLISHED'
        assert report['retained_destination'] is True
        assert 'PUBLISHED_RESULT_NOT_CONFIRMED' in report['validation_codes']
        assert verifier.verify(offline[1])['verification_status'] == 'INTERNALLY_CONSISTENT'
        assert not list(offline[1].parent.glob('.backup-create-*'))
        safe(report, offline)
    else:
        failed(report, offline, 'READ_FAILED')


def test_cleanup_failure_report_retains_only_owned_staging(offline, monkeypatch):
    other = offline[1].parent / 'existing-backup'
    other.mkdir(mode=0o700)
    (other / 'original').write_text(SECRET)
    before = frozen(other)
    def broken_manifest(*args):
        raise protocol.ManifestError('MANIFEST_SIZE_LIMIT')
    def deny(*args, **kwargs):
        raise PermissionError(errno.EACCES, SECRET)
    monkeypatch.setattr(protocol, 'canonical_bytes', broken_manifest)
    monkeypatch.setattr(os, 'unlink', deny)
    failed(run(offline), offline, 'MANIFEST_SIZE_LIMIT', 'FAILED')
    assert frozen(other) == before


def test_cleanup_does_not_remove_replacement_inode(offline, monkeypatch):
    actual = verifier.verify
    def replaced(path):
        root = Path(path)
        replacement = root / 'unowned'
        replacement.write_bytes(b'replacement')
        replacement.replace(root / 'VERSION')
        return actual(path)
    monkeypatch.setattr(verifier, 'verify', replaced)
    report = run(offline)
    failed(report, offline, 'VERIFICATION_FAILED', 'FAILED')
    assert (offline[1].parent / report['residual_staging_name'] / 'VERSION').read_bytes() == b'replacement'


def test_staging_name_collision_never_cleaned(offline, monkeypatch):
    monkeypatch.setattr(writer.secrets, 'token_hex', lambda count: '0' * 32)
    original = offline[1].parent / ('.backup-create-' + '0' * 32)
    original.mkdir(mode=0o700)
    (original / 'original').write_text(SECRET)
    before = frozen(original)
    report = run(offline)
    assert report['creation_status'] == 'FAILED' and report['cleanup_status'] == 'NOT_NEEDED'
    assert frozen(original) == before
    assert not offline[1].exists()


def test_unsupported_publication_stops_before_any_write(offline, monkeypatch):
    def unavailable():
        raise writer.AuditFault('NO_REPLACE_UNAVAILABLE')
    monkeypatch.setattr(writer, 'publication_function', unavailable)
    failed(run(offline), offline, 'NO_REPLACE_UNAVAILABLE', 'NOT_NEEDED')


@pytest.mark.parametrize('bad_path', ['../snapshot', '/opt/clash-yaml-manager', '/opt/clash-yaml-manager/new', 'new/', '.'])
def test_unsafe_destination_paths_rejected(offline, bad_path):
    report = writer.create(offline[0], bad_path, 'UPDATER_SNAPSHOT')
    assert report['creation_status'] == 'FAILED' and report['cleanup_status'] == 'NOT_NEEDED'
    assert not offline[1].exists()


def test_live_source_refused_before_open(offline, monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail('known live source must not be opened')
    monkeypatch.setattr(os, 'open', fail)
    report = writer.create('/opt/clash-yaml-manager/state', offline[1], 'UPDATER_SNAPSHOT')
    assert report['creation_status'] == 'FAILED'
    assert 'LIVE_INSTALLATION_REFUSED' in report['validation_codes']


def test_destination_inside_source_refused(offline):
    report = writer.create(offline[0], offline[0] / 'new', 'UPDATER_SNAPSHOT')
    assert report['creation_status'] == 'FAILED' and 'OVERLAPPING_PATHS' in report['validation_codes']
    assert not (offline[0] / 'new').exists()


def test_existing_manifest_source_not_rewritten(offline):
    (offline[0] / protocol.MANIFEST_NAME).write_text(SECRET)
    before = frozen(offline[0])
    failed(run(offline), offline, 'MANIFEST_SELF_REFERENCE', 'NOT_NEEDED')
    assert frozen(offline[0]) == before


def test_device_and_filesystem_boundary_preflight(offline, monkeypatch):
    actual = os.stat
    for altered, code in [('device', 'UNSAFE_OBJECT'), ('filesystem', 'FILESYSTEM_BOUNDARY')]:
        def fake(path, *args, **kwargs):
            info = actual(path, *args, **kwargs)
            if path == 'VERSION' and kwargs.get('dir_fd') is not None:
                values = {n:getattr(info, n) for n in dir(info) if n.startswith('st_')}
                if altered == 'device':
                    values['st_mode'] = stat.S_IFCHR | 0o600
                else:
                    values['st_dev'] += 1
                return SimpleNamespace(**values)
            return info
        with monkeypatch.context() as context:
            context.setattr(os, 'stat', fake)
            failed(run(offline), offline, code, 'NOT_NEEDED')


def test_cli_no_pycache_safe_output_and_exit_codes(offline, tmp_path):
    cli = tmp_path / 'cli'
    cli.mkdir()
    for name in ('backup_create.py', 'backup_verify.py', 'backup_manifest.py', 'backup_audit.py'):
        shutil.copyfile(ROOT / 'scripts' / name, cli / name)
    env = dict(os.environ)
    env.pop('PYTHONDONTWRITEBYTECODE', None)
    command = [sys.executable, str(cli / 'backup_create.py'), '--source', str(offline[0]),
               '--destination', str(offline[1]), '--snapshot-type', 'UPDATER_SNAPSHOT', '--json']
    result = subprocess.run(command, capture_output=True, text=True, env=env, check=True)
    report = json.loads(result.stdout)
    assert report['creation_status'] == 'CREATED' and result.stderr == ''
    safe(report, offline)
    assert not (cli / '__pycache__').exists()
    again = subprocess.run(command, capture_output=True, text=True, env=env)
    assert again.returncode == 1 and 'DESTINATION_EXISTS' in json.loads(again.stdout)['validation_codes']
    invalid = subprocess.run(command + ['--secret', SECRET], capture_output=True, text=True, env=env)
    assert invalid.returncode == 64 and SECRET not in invalid.stdout + invalid.stderr


def test_empty_file_is_hashed_and_stored(offline):
    (offline[0] / 'zero-bytes').write_bytes(b'')
    report = run(offline)
    assert report['creation_status'] == 'CREATED'
    manifest = protocol.load_manifest((offline[1] / protocol.MANIFEST_NAME).read_bytes())
    entry = next(e for e in manifest['entries'] if e['path'] == 'zero-bytes')
    assert entry['size'] == 0 and entry['sha256'] == hashlib.sha256(b'').hexdigest()


def test_postcopy_corruption_cannot_be_authenticated_by_new_manifest(offline, monkeypatch):
    actual = writer.Writer.copy
    def corrupt(self, source_fd, records):
        actual(self, source_fd, records)
        with self.owned_directory() as fd:
            target = os.open('VERSION', os.O_WRONLY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                os.write(target, b'2')
            finally:
                os.close(target)
    monkeypatch.setattr(writer.Writer, 'copy', corrupt)
    failed(run(offline), offline, 'STORED_BYTES_MISMATCH')


def test_write_failure_is_private_and_cleaned(offline, monkeypatch):
    def deny(*args, **kwargs):
        raise OSError(errno.ENOSPC, SECRET)
    monkeypatch.setattr(os, 'write', deny)
    failed(run(offline), offline, 'READ_FAILED')


def test_manifest_file_creation_failure(offline, monkeypatch):
    actual = os.open
    def deny(name, flags, *args, **kwargs):
        if name == protocol.MANIFEST_NAME and flags & os.O_CREAT:
            raise PermissionError(errno.EACCES, SECRET)
        return actual(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', deny)
    failed(run(offline), offline, 'PERMISSION_DENIED')


def test_postpublication_verification_failure_retains_destination(offline, monkeypatch):
    actual = verifier.verify
    def damage(path):
        root = Path(path)
        if root.name == offline[1].name:
            (root / 'VERSION').write_bytes(b'2.7.0\n')
        return actual(path)
    monkeypatch.setattr(verifier, 'verify', damage)
    report = run(offline)
    assert report['creation_status'] == 'FAILED' and report['publication_status'] == 'PUBLISHED'
    assert report['retained_destination'] is True and report['cleanup_status'] == 'NOT_ATTEMPTED_PUBLISHED'
    assert report['verification']['verification_status'] == 'NOT_VERIFIED'
    assert report['MANIFEST_SHA256'] is None
    assert 'FILE_DIGEST_MISMATCH' in report['verification']['validation_codes']
    safe(report, offline)


def test_rename_published_then_interrupted_is_reported(offline, monkeypatch):
    actual = writer.publication_function()
    def interrupted(*args):
        actual(*args)
        raise KeyboardInterrupt
    monkeypatch.setattr(writer, 'publication_function', lambda: interrupted)
    report = run(offline)
    assert report['creation_status'] == 'FAILED' and 'CREATION_INTERRUPTED' in report['validation_codes']
    assert report['publication_status'] == 'PUBLISHED' and report['retained_destination'] is True
    assert report['cleanup_status'] == 'NOT_ATTEMPTED_PUBLISHED'
    assert verifier.verify(offline[1])['verification_status'] == 'INTERNALLY_CONSISTENT'


def test_destination_parent_replaced_is_detected_without_writing_replacement(offline, monkeypatch):
    actual = writer.Writer.copy
    parent = offline[1].parent
    moved = parent.parent / 'moved-private-parent'
    def replace(self, source_fd, records):
        actual(self, source_fd, records)
        parent.rename(moved)
        parent.mkdir(mode=0o700)
        (parent / 'unrelated').write_text(SECRET)
    monkeypatch.setattr(writer.Writer, 'copy', replace)
    report = run(offline)
    assert report['creation_status'] == 'FAILED'
    assert report['cleanup_status'] == 'CLEANED'
    assert not (moved / 'snapshot').exists() and not list(moved.glob('.backup-create-*'))
    assert [p.name for p in parent.iterdir()] == ['unrelated']
    assert (parent / 'unrelated').read_text() == SECRET


def test_cleanup_interruption_explicitly_reports_residue(offline, monkeypatch):
    def fail(*args):
        raise protocol.ManifestError('MANIFEST_SIZE_LIMIT')
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(protocol, 'canonical_bytes', fail)
    monkeypatch.setattr(os, 'unlink', interrupted)
    failed(run(offline), offline, 'MANIFEST_SIZE_LIMIT', 'FAILED')


def test_staging_root_replacement_not_cleaned_as_owned(offline, monkeypatch):
    actual = verifier.verify
    moved = None
    def replace(path):
        nonlocal moved
        root = Path(path)
        result = actual(path)
        moved = root.parent / 'moved-own-staging'
        root.rename(moved)
        root.mkdir(mode=0o700)
        (root / 'unowned').write_text(SECRET)
        return result
    monkeypatch.setattr(verifier, 'verify', replace)
    report = run(offline)
    failed(report, offline, 'STAGING_CHANGED', 'FAILED')
    assert (offline[1].parent / report['residual_staging_name'] / 'unowned').read_text() == SECRET
    assert moved.is_dir()


def test_stored_permission_change_rejected(offline, monkeypatch):
    actual = writer.Writer.copy
    def change(self, source_fd, records):
        actual(self, source_fd, records)
        with self.owned_directory() as folder:
            os.chmod('VERSION', 0o644, dir_fd=folder, follow_symlinks=False)
    monkeypatch.setattr(writer.Writer, 'copy', change)
    failed(run(offline), offline, 'STAGING_CHANGED')


def test_unsafe_source_path_refused(offline):
    report = writer.create(str(offline[0]) + '/../source', offline[1], 'UPDATER_SNAPSHOT')
    assert report['creation_status'] == 'FAILED' and 'INVALID_PATH' in report['validation_codes']
    assert report['cleanup_status'] == 'NOT_NEEDED'


def test_destination_inspection_failure_reports_possible_staging_residue(offline, monkeypatch):
    actual_stat = os.stat
    fired = False
    def publish(*args):
        nonlocal fired
        fired = True
        raise OSError(errno.EIO, SECRET)
    def denied(path, *args, **kwargs):
        if fired and path == offline[1].name and kwargs.get('dir_fd') is not None:
            raise PermissionError(errno.EACCES, SECRET)
        return actual_stat(path, *args, **kwargs)
    monkeypatch.setattr(writer, 'publication_function', lambda: publish)
    monkeypatch.setattr(os, 'stat', denied)
    report = run(offline)
    assert report['creation_status'] == 'FAILED'
    assert report['publication_status'] == 'UNCERTAIN'
    assert report['cleanup_status'] == 'NOT_ATTEMPTED_UNCERTAIN'
    assert report['retained_destination'] is True
    assert (offline[1].parent / report['residual_staging_name']).is_dir()
    safe(report, offline)


def test_source_code_and_environment_never_executed(offline, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('writer attempted execution')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(os, 'system', forbidden)
    report = run(offline)
    assert report['creation_status'] == 'CREATED'
    assert (offline[1] / '.env').read_bytes() == (offline[0] / '.env').read_bytes()


def test_all_source_file_opens_are_readonly_no_follow(offline, monkeypatch):
    source_directories = {writer.identity(p.stat()) for p in (offline[0], offline[0] / 'data', offline[0] / 'empty')}
    actual = os.open
    def guarded(name, mode, *args, **kwargs):
        if kwargs.get('dir_fd') is not None and writer.identity(os.fstat(kwargs['dir_fd'])) in source_directories:
            assert mode & os.O_ACCMODE == os.O_RDONLY
            assert mode & os.O_NOFOLLOW and mode & os.O_NONBLOCK
            assert not mode & (os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        return actual(name, mode, *args, **kwargs)
    monkeypatch.setattr(os, 'open', guarded)
    assert run(offline)['creation_status'] == 'CREATED'


def test_handle_close_error_never_reports_creation_success(offline, monkeypatch):
    actual = os.close
    publication_started = False
    own_root = None
    actual_publish = writer.publication_function()
    def publish(parent, stage, name):
        nonlocal publication_started, own_root
        own_root = writer.identity(os.stat(stage, dir_fd=parent, follow_symlinks=False))
        actual_publish(parent, stage, name)
        publication_started = True
    def close(fd):
        info = os.fstat(fd)
        actual(fd)
        if publication_started and writer.identity(info) == own_root:
            raise OSError(errno.EIO, SECRET)
    monkeypatch.setattr(writer, 'publication_function', lambda: publish)
    monkeypatch.setattr(os, 'close', close)
    report = run(offline)
    assert report['creation_status'] == 'FAILED' and report['publication_status'] == 'PUBLISHED'
    assert report['retained_destination'] is True
    assert report['MANIFEST_SHA256'] is None
    safe(report, offline)
