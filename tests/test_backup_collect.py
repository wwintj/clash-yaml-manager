"""Offline synthetic fixtures only; no live install, system accounts or restore."""
import errno
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

from conftest import ROOT
from scripts import backup_collect as collector
from scripts import backup_create as writer
from scripts import backup_verify as verifier
from scripts import backup_manifest as protocol

SECRET = 'collector-password-token-勿輸出'


def json_file(path, value):
    path.write_text(json.dumps(value), encoding='utf-8')
    path.chmod(0o600)


@pytest.fixture
def offline(tmp_path):
    parent = tmp_path / 'private'
    parent.mkdir(mode=0o700)
    source = parent / 'source'
    source.mkdir(mode=0o700)
    (source / 'defaults').mkdir(mode=0o755)
    (source / 'state').mkdir(mode=0o700)
    (source / '.env').write_bytes(('APP_PASSWORD=  ' + SECRET + '  \n').encode())
    (source / '.env').chmod(0o600)
    (source / 'VERSION').write_bytes(b'1.7.0\n')
    (source / 'defaults/default.yaml').write_bytes(b'proxies: []\nrules: []\n')
    json_file(source / collector.SOURCE_CONTROL, dict(schema_version=1, profile=collector.PROFILE,
             offline=True, writers_quiet=True, service_account=None))
    json_file(source / 'state/auth.json', dict(version=1, auth_version=3,
             instance_id='a' * 32, password_hash=SECRET))
    return source, parent / 'representation'


def run(offline):
    return collector.collect(*offline, collector.PROFILE)


def frozen(root):
    values = {}
    for folder, _, names in os.walk(root, followlinks=False):
        folder = Path(folder)
        values[folder.relative_to(root).as_posix()] = (verifier.fingerprint(folder.lstat()), None)
        for name in names:
            path = folder / name
            info = path.lstat()
            values[path.relative_to(root).as_posix()] = (verifier.fingerprint(info),
                path.read_bytes() if stat.S_ISREG(info.st_mode) else None)
    return values


def refusal(report, offline, code, cleanup='NOT_NEEDED'):
    assert report['collection_status'] == 'FAILED'
    assert report['publication_status'] == 'NOT_PUBLISHED'
    assert code in report['validation_codes']
    assert report['cleanup_status'] == cleanup
    assert not offline[1].exists()
    if cleanup != 'FAILED':
        assert not list(offline[1].parent.glob('.backup-collect-*'))
    assert report['restore_proven'] is False and report['trust_anchor_verified'] is False
    text = json.dumps(report)
    assert SECRET not in text and str(offline[0]) not in text and str(offline[1]) not in text


def test_collector_to_unchanged_writer_manifest_verifier(offline, capsys):
    source, destination = offline
    sid, revision, provider = 'a' * 32, 'b' * 32, 'c' * 32
    root = source / 'state/fixed_subscriptions' / sid / revision
    (root / 'sources' / provider).mkdir(parents=True, mode=0o700)
    for path in (source / 'state/fixed_subscriptions', root.parent, root, root / 'sources'):
        path.chmod(0o700)
    for path in (root / 'base.yaml', root / 'current.yaml', root / 'sources' / provider / 'payload.bin'):
        path.write_bytes(SECRET.encode()); path.chmod(0o600)
    json_file(source / 'state/fixed_subscriptions.json', dict(version=6, subscriptions={}, retired_tokens=[]))
    (source / 'venv').mkdir(mode=0o755)
    (source / 'venv/system-python').symlink_to('/not-opened')
    (source / 'app.py').write_text('raise RuntimeError("must not execute")')
    (source / 'state/auth.lock').write_bytes(b''); (source / 'state/auth.lock').chmod(0o600)
    (source / 'state/.proxy-probe-synthetic').mkdir(mode=0o700)
    (source / 'state/.proxy-probe-synthetic/secret').write_text(SECRET)
    before = frozen(source)
    result = run(offline)
    assert result['collection_status'] == 'COLLECTED'
    assert frozen(source) == before
    assert (destination / '.env').read_bytes() == (source / '.env').read_bytes()
    assert not (destination / 'venv').exists() and not (destination / 'app.py').exists()
    assert not (destination / 'state/auth.lock').exists()
    scope = json.loads((destination / collector.SCOPE_FILE).read_bytes())
    assert scope['source_scope'] == 'ALLOWLIST_SUBSET'
    assert scope['writer_full_tree_means'] == 'COLLECTED_REPRESENTATION_ONLY'
    assert scope['atomic_source_snapshot'] is False and scope['business_closure_verified'] is False
    assert scope['restore_proven'] is False
    assert {x['reason'] for x in scope['omitted_roots']} == {'OUT_OF_SCOPE', 'LOCK_NOT_COLLECTED', 'EPHEMERAL_NOT_COLLECTED'}
    ledger = json.loads((destination / collector.OWNERSHIP_FILE).read_bytes())
    original = next(x for x in ledger['original_entries'] if x['path'] == 'defaults')
    assert original['original']['mode'] == '0755' and original['role'] == 'OPERATOR_CONFIGURATION'
    assert ledger['restore_mapping_applied'] is False
    for path in (destination, *destination.rglob('*')):
        info = path.lstat()
        assert info.st_uid == os.geteuid() and info.st_gid == os.getegid()
        assert stat.S_IMODE(info.st_mode) == (0o700 if path.is_dir() else 0o600)
    snapshot = destination.parent / 'snapshot'
    published = writer.create(destination, snapshot, 'UPDATER_SNAPSHOT')
    assert published['creation_status'] == 'CREATED'
    manifest = protocol.load_manifest((snapshot / protocol.MANIFEST_NAME).read_bytes())
    assert manifest['snapshot_scope'] == 'FULL_TREE' and manifest['schema_version'] == 1
    assert {collector.SCOPE_FILE, collector.OWNERSHIP_FILE} <= {x['path'] for x in manifest['entries']}
    verified = verifier.verify(snapshot)
    assert verified['verification_status'] == 'INTERNALLY_CONSISTENT'
    assert verified['file_hash_match'] is True and verified['declared_scope_verified'] is True
    assert verified['restore_proven'] is False
    with capsys.disabled():
        print('COLLECTOR_WRITER_VERIFIER: PASS ' + json.dumps(dict(profile=collector.PROFILE,
              manifest_version=1, collected_representation_only=True, restore_proven=False)))


@pytest.mark.parametrize('relative', ['COLLECTOR_SOURCE.json', '.env', 'VERSION', 'defaults/default.yaml', 'state/auth.json'])
def test_missing_required_refuses(offline, relative):
    (offline[0] / relative).unlink()
    refusal(run(offline), offline, 'MISSING_REQUIRED_COMPONENT')


def test_missing_optional_explicitly_recorded(offline):
    assert run(offline)['collection_status'] == 'COLLECTED'
    scope = json.loads((offline[1] / collector.SCOPE_FILE).read_bytes())
    assert 'INSTALLATION.json' in scope['missing_optional']
    assert 'state/fixed_subscriptions.json' in scope['missing_optional']


@pytest.mark.parametrize('path', ['unknown-' + SECRET, 'state/unreviewed', 'defaults/extra.yaml',
                                  'state/fixed_subscriptions/bad-id', 'state/geoip/other.mmdb'])
def test_unknown_path_refused_before_payload_open(offline, path, monkeypatch):
    target = offline[0] / path
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.write_bytes(SECRET.encode()); target.chmod(0o600)
    actual = os.open
    def guard(name, flags, *args, **kwargs):
        assert os.fspath(name) != target.name, 'UNKNOWN_PAYLOAD_OPENED'
        return actual(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', guard)
    refusal(run(offline), offline, 'UNEXPECTED_COMPONENT')


@pytest.mark.parametrize('object_type', ['symlink', 'hardlink', 'fifo', 'socket'])
def test_unsafe_objects_refused_without_following_or_blocking(offline, object_type, monkeypatch):
    path = offline[0] / 'state/auth.json'
    path.unlink()
    sock = None
    if object_type == 'symlink': path.symlink_to(offline[0] / '.env')
    elif object_type == 'hardlink': os.link(offline[0] / '.env', path)
    elif object_type == 'fifo': os.mkfifo(path, 0o600)
    else:
        monkeypatch.chdir(path.parent)
        sock = socket.socket(socket.AF_UNIX); sock.bind(path.name)
    try:
        refusal(run(offline), offline, 'UNSAFE_OBJECT')
    finally:
        if sock is not None: sock.close()


@pytest.mark.parametrize('component,mode,code', [('state', 0o755, 'UNSAFE_SOURCE_PERMISSION'),
    ('state/auth.json', 0o644, 'UNSAFE_SOURCE_PERMISSION'), ('.env', 0o660, 'UNSAFE_SOURCE_PERMISSION'),
    ('defaults', 0o777, 'UNSAFE_SOURCE_PERMISSION'), ('defaults/default.yaml', 0o4644, 'UNSAFE_SOURCE_PERMISSION'),
    ('COLLECTOR_SOURCE.json', 0o644, 'UNTRUSTED_SOURCE_DECLARATION'), ('.', 0o755, 'UNSAFE_SOURCE_ROOT')])
def test_unsafe_permission_rejected(offline, component, mode, code):
    (offline[0] / component).chmod(mode)
    refusal(run(offline), offline, code)


@pytest.mark.parametrize('field,value', [('offline', False), ('writers_quiet', False), ('schema_version', True), ('profile', 'other')])
def test_trusted_quiet_declaration_is_required(offline, field, value):
    path = offline[0] / collector.SOURCE_CONTROL
    data = json.loads(path.read_bytes()); data[field] = value; json_file(path, data)
    refusal(run(offline), offline, 'OFFLINE_QUIET_NOT_ATTESTED')


def test_duplicate_or_secret_declaration_not_echoed(offline):
    path = offline[0] / collector.SOURCE_CONTROL
    path.write_bytes((' {"offline":true,"offline":"' + SECRET + '"}').encode())
    refusal(run(offline), offline, 'INVALID_COMPONENT_CONTENT')


@pytest.mark.parametrize('valid', [True, False])
def test_conditional_installation_metadata_matches_version(offline, valid):
    json_file(offline[0] / 'INSTALLATION.json', dict(channel='stable', base_version='1.7.0' if valid else '1.6.0',
        commit='a' * 40, tag='v1.7.0', installed_at='2026-10-09T00:00:00+00:00', source='github-release'))
    result = run(offline)
    if valid: assert result['collection_status'] == 'COLLECTED'
    else: refusal(result, offline, 'INVALID_INSTALLATION_METADATA')


def test_future_state_schema_refused(offline):
    json_file(offline[0] / 'state/auth.json', dict(version=999))
    refusal(run(offline), offline, 'UNSUPPORTED_STATE_ENVELOPE')


def test_unsafe_owner_refused_even_when_readable(offline, monkeypatch):
    actual = os.stat
    def foreign(path, *args, **kwargs):
        info = actual(path, *args, **kwargs)
        if path == 'auth.json' and 'dir_fd' in kwargs:
            fields = {name: getattr(info, name) for name in dir(info) if name.startswith('st_')}
            fields['st_uid'] = os.geteuid() + 12345
            return SimpleNamespace(**fields)
        return info
    monkeypatch.setattr(os, 'stat', foreign)
    refusal(run(offline), offline, 'UNSAFE_SOURCE_OWNERSHIP')


def test_cross_filesystem_refused(offline, monkeypatch):
    actual = os.stat
    def boundary(path, *args, **kwargs):
        info = actual(path, *args, **kwargs)
        if path == 'auth.json' and 'dir_fd' in kwargs:
            fields = {name: getattr(info, name) for name in dir(info) if name.startswith('st_')}
            fields['st_dev'] += 1
            return SimpleNamespace(**fields)
        return info
    monkeypatch.setattr(os, 'stat', boundary)
    refusal(run(offline), offline, 'FILESYSTEM_BOUNDARY')


def test_permission_denied_is_safe_failure(offline, monkeypatch):
    actual = os.open
    def denied(path, options, *args, **kwargs):
        if path == 'auth.json' and options & os.O_WRONLY == 0:
            raise PermissionError(errno.EACCES, SECRET)
        return actual(path, options, *args, **kwargs)
    monkeypatch.setattr(os, 'open', denied)
    refusal(run(offline), offline, 'PERMISSION_DENIED')


@pytest.mark.parametrize('mutation', ['bytes', 'replacement', 'new_entry'])
def test_source_mutation_refuses_and_cleans_owned_stage(offline, monkeypatch, mutation):
    actual = collector.Collector.copy
    def mutate(self, fd, records):
        actual(self, fd, records)
        if mutation == 'bytes': (offline[0] / '.env').write_bytes(b'changed')
        elif mutation == 'replacement':
            (offline[0] / '.env').unlink(); (offline[0] / '.env').write_bytes(b'changed')
            (offline[0] / '.env').chmod(0o600)
        else: (offline[0] / 'state/unexpected').write_bytes(b'changed')
    monkeypatch.setattr(collector.Collector, 'copy', mutate)
    refusal(run(offline), offline, 'UNEXPECTED_COMPONENT' if mutation == 'new_entry' else 'BACKUP_CHANGED', 'CLEANED')


@pytest.mark.parametrize('existing', ['directory', 'file', 'symlink'])
def test_destination_collision_never_overwrites(offline, existing):
    path = offline[1]
    if existing == 'directory': path.mkdir(mode=0o700)
    elif existing == 'file': path.write_bytes(SECRET.encode())
    else: path.symlink_to(offline[0])
    before = verifier.fingerprint(path.lstat())
    result = run(offline)
    assert result['collection_status'] == 'FAILED' and 'DESTINATION_EXISTS' in result['validation_codes']
    assert verifier.fingerprint(path.lstat()) == before
    assert not list(path.parent.glob('.backup-collect-*'))


@pytest.mark.parametrize('fault,code', [('disk', 'DISK_FULL'), ('copy', 'READ_FAILED'),
                                      ('zero_write', 'WRITE_FAILED'), ('interrupt', 'COLLECTION_INTERRUPTED')])
def test_write_failure_cleanup_preserves_source_and_unrelated(offline, monkeypatch, fault, code):
    sentinel = offline[1].parent / 'unrelated-backup'
    sentinel.write_bytes(SECRET.encode()); sentinel.chmod(0o600)
    before, sentinel_before = frozen(offline[0]), verifier.fingerprint(sentinel.stat())
    if fault == 'zero_write': monkeypatch.setattr(os, 'write', lambda *_: 0)
    else:
        def fail(*_):
            if fault == 'interrupt': raise KeyboardInterrupt
            raise OSError(errno.ENOSPC if fault == 'disk' else errno.EIO, SECRET)
        monkeypatch.setattr(collector.Collector, 'write_all', fail)
    refusal(run(offline), offline, code, 'CLEANED')
    assert frozen(offline[0]) == before
    assert sentinel.read_bytes() == SECRET.encode() and verifier.fingerprint(sentinel.stat()) == sentinel_before


def test_fsync_failure_cleans_before_publication(offline, monkeypatch):
    def fail(_): raise OSError(errno.EIO, SECRET)
    monkeypatch.setattr(os, 'fsync', fail)
    refusal(run(offline), offline, 'READ_FAILED', 'CLEANED')


def test_failure_after_publication_retains_unconfirmed_destination(offline, monkeypatch):
    actual = writer.publication_function
    def function():
        publish = actual()
        def publish_then_fail(*args):
            publish(*args)
            raise OSError(errno.EIO, SECRET)
        return publish_then_fail
    monkeypatch.setattr(writer, 'publication_function', function)
    result = run(offline)
    assert result['collection_status'] == 'FAILED' and result['publication_status'] == 'PUBLISHED'
    assert result['retained_destination'] is True and result['cleanup_status'] == 'NOT_ATTEMPTED_PUBLISHED'
    assert offline[1].exists()


def test_cleanup_identity_mismatch_preserves_replacement(offline, monkeypatch):
    foreign = []
    def fail(self, fd, data):
        stage = offline[1].parent / self.stage_name
        path = stage / '.env'
        path.rename(stage / 'own-moved-file')
        path.write_bytes(b'foreign-object')
        foreign.append((path, verifier.fingerprint(path.stat())))
        raise OSError(errno.EIO, SECRET)
    monkeypatch.setattr(collector.Collector, 'write_all', fail)
    result = run(offline)
    refusal(result, offline, 'READ_FAILED', 'FAILED')
    assert 'CLEANUP_FAILED' in result['validation_codes']
    path, before = foreign[0]
    assert path.read_bytes() == b'foreign-object' and verifier.fingerprint(path.stat()) == before


@pytest.mark.parametrize('constant,value,code', [('MAX_ENTRIES', 8, 'ENTRY_LIMIT'),
    ('MAX_DEPTH', 1, 'DEPTH_LIMIT'), ('MAX_FILE_BYTES', 1, 'FILE_BYTE_LIMIT'),
    ('MAX_TOTAL_BYTES', 1, 'TOTAL_BYTE_LIMIT'), ('MAX_READ_BYTES', 1, 'TOTAL_READ_LIMIT'),
    ('MAX_SECONDS', -1, 'TIME_LIMIT'), ('MAX_METADATA_BYTES', 1, 'METADATA_SIZE_LIMIT')])
def test_explicit_resource_limits_never_truncate_success(offline, monkeypatch, constant, value, code):
    monkeypatch.setattr(collector, constant, value)
    refusal(run(offline), offline, code)


def test_killed_staging_is_not_published_or_auto_deleted_on_next_run(offline):
    code = '''import os,sys
from scripts import backup_collect as c
c.Collector.write_all=lambda *args:os._exit(77)
c.collect(sys.argv[1],sys.argv[2],c.PROFILE)
'''
    before = frozen(offline[0])
    child = subprocess.run([sys.executable, '-c', code, *map(str, offline)], cwd=ROOT,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), capture_output=True, timeout=15)
    assert child.returncode == 77 and not offline[1].exists()
    stages = list(offline[1].parent.glob('.backup-collect-*'))
    assert len(stages) == 1 and stat.S_IMODE(stages[0].stat().st_mode) == 0o700
    residual = frozen(stages[0])
    assert run(offline)['collection_status'] == 'COLLECTED'
    assert frozen(stages[0]) == residual and frozen(offline[0]) == before


@pytest.mark.parametrize('arguments', [[], ['--source', SECRET], ['--not-supported', SECRET],
    ['--source', '/opt/clash-yaml-manager', '--destination', SECRET, '--profile', collector.PROFILE],
    ['--sou', SECRET, '--destination', SECRET, '--profile', collector.PROFILE]])
def test_cli_fixed_output_no_secret_paths_or_pycache(tmp_path, arguments):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/backup_collect.py'), *arguments],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode in (1, 64)
    assert SECRET not in result.stdout + result.stderr and not result.stderr
    assert not list(tmp_path.rglob('__pycache__'))


@pytest.mark.parametrize('target', ['/opt/clash-yaml-manager', '/opt/clash-yaml-manager/state'])
def test_known_live_source_refused_without_open(offline, monkeypatch, target):
    actual = os.open
    def guard(path, *args, **kwargs):
        assert path != '/opt', 'LIVE_PATH_OPENED'
        return actual(path, *args, **kwargs)
    monkeypatch.setattr(os, 'open', guard)
    result = collector.collect(target, offline[1], collector.PROFILE)
    assert result['collection_status'] == 'FAILED' and 'LIVE_INSTALLATION_REFUSED' in result['validation_codes']


def test_real_publication_race_preserves_empty_destination(offline, monkeypatch):
    actual = writer.publication_function
    collision = []
    def function():
        publish = actual()
        def race(fd, stage, name):
            os.mkdir(name, 0o700, dir_fd=fd)
            collision.append(verifier.fingerprint(offline[1].stat()))
            publish(fd, stage, name)
        return race
    monkeypatch.setattr(writer, 'publication_function', function)
    result = run(offline)
    assert result['collection_status'] == 'FAILED' and 'DESTINATION_EXISTS' in result['validation_codes']
    assert result['cleanup_status'] == 'CLEANED' and result['publication_status'] == 'NOT_PUBLISHED'
    assert verifier.fingerprint(offline[1].stat()) == collision[0] and not list(offline[1].iterdir())
    assert not list(offline[1].parent.glob('.backup-collect-*'))


@pytest.mark.parametrize('path_kind', ['source_root', 'source_ancestor', 'destination_ancestor'])
def test_symbolic_path_roots_and_ancestors_rejected(offline, tmp_path, path_kind):
    source, destination = offline
    alias = tmp_path / 'alias'
    if path_kind == 'source_root': alias.symlink_to(source); source = alias
    elif path_kind == 'source_ancestor': alias.symlink_to(source.parent); source = alias / 'source'
    else: alias.symlink_to(destination.parent); destination = alias / destination.name
    result = collector.collect(source, destination, collector.PROFILE)
    assert result['collection_status'] == 'FAILED' and 'UNSAFE_ROOT_PATH' in result['validation_codes']
    assert not offline[1].exists()


@pytest.mark.parametrize('mode', [0o755, 0o770, 0o2770])
def test_unsafe_destination_parent_not_repaired(offline, mode):
    parent = offline[1].parent
    parent.chmod(mode)
    refusal(run(offline), offline, 'UNSAFE_DESTINATION_PARENT')
    assert stat.S_IMODE(parent.stat().st_mode) == mode


def test_destination_under_source_refused(offline):
    result = collector.collect(offline[0], offline[0] / 'new', collector.PROFILE)
    assert 'OVERLAPPING_PATHS' in result['validation_codes'] and result['collection_status'] == 'FAILED'


@pytest.mark.parametrize('uid,gid', [(0, 1000), (True, 1000), (1000, False), (1000, 0), (2**32 - 1, 1000)])
def test_invalid_service_numeric_identity_refused(offline, uid, gid):
    path = offline[0] / collector.SOURCE_CONTROL
    value = json.loads(path.read_bytes()); value['service_account'] = dict(name='clashyaml', uid=uid, gid=gid)
    json_file(path, value)
    refusal(run(offline), offline, 'INVALID_SERVICE_IDENTITY')


def test_nonroot_cannot_opt_in_arbitrary_mixed_owners(offline, monkeypatch):
    # The gate is checked before any foreign state payload open.
    path = offline[0] / collector.SOURCE_CONTROL
    value = json.loads(path.read_bytes()); value['service_account'] = dict(name='clashyaml', uid=12345, gid=12345)
    json_file(path, value)
    actual_uid, actual_gid = os.geteuid(), os.getegid()
    # Source root must still match the real executor, so only intercept the later root gate.
    calls = [0]
    def uid():
        calls[0] += 1
        return actual_uid if calls[0] <= 3 else (actual_uid or 501)
    if actual_uid != 0:
        refusal(run(offline), offline, 'MIXED_OWNER_REQUIRES_ROOT')
    else:
        monkeypatch.setattr(os, 'geteuid', uid)
        result = run(offline)
        assert result['collection_status'] == 'FAILED'
        assert 'MIXED_OWNER_REQUIRES_ROOT' in result['validation_codes']
    assert os.getegid() == actual_gid


@pytest.mark.parametrize('object_mode', [stat.S_IFCHR, stat.S_IFBLK])
def test_device_objects_are_never_opened(offline, monkeypatch, object_mode):
    actual = os.stat
    def device(path, *args, **kwargs):
        info = actual(path, *args, **kwargs)
        if path == 'auth.json' and 'dir_fd' in kwargs:
            fields = {name: getattr(info, name) for name in dir(info) if name.startswith('st_')}
            fields['st_mode'] = object_mode | 0o600
            return SimpleNamespace(**fields)
        return info
    monkeypatch.setattr(os, 'stat', device)
    refusal(run(offline), offline, 'UNSAFE_OBJECT')


def test_time_exhaustion_after_copy_still_cleans_owned_stage(offline, monkeypatch):
    actual = collector.Collector.copy
    def exhaust(self, fd, records):
        actual(self, fd, records)
        self.started -= collector.MAX_SECONDS + 1
    monkeypatch.setattr(collector.Collector, 'copy', exhaust)
    refusal(run(offline), offline, 'TIME_LIMIT', 'CLEANED')


def test_unknown_profile_does_not_open_source(offline, monkeypatch):
    def forbidden(*_, **__): raise AssertionError('NO_SOURCE_OPEN_ALLOWED')
    monkeypatch.setattr(os, 'open', forbidden)
    result = collector.collect(offline[0], offline[1], SECRET)
    assert result['collection_status'] == 'FAILED' and 'INVALID_PROFILE' in result['validation_codes']
    assert SECRET not in json.dumps(result)


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux root-compatible synthetic fixture gate')
def test_linux_real_mixed_owner_fixture_and_writer_pipeline(offline, capsys):
    # GitHub Ubuntu has passwordless sudo. Only this fixture's ownership changes;
    # no accounts, live paths, systemd, configuration or production access.
    code = r'''import json,os,stat,sys
from pathlib import Path
from scripts import backup_collect as c,backup_create as w,backup_verify as v
source=Path(sys.argv[1]);destination=Path(sys.argv[2]);uid=int(sys.argv[3]);gid=int(sys.argv[4])
parent=source.parent
try:
    for p in [parent,*parent.rglob('*')]:os.chown(p,0,0)
    for p in [source/'state',*(source/'state').rglob('*')]:os.chown(p,12345,12345)
    declaration=json.loads((source/c.SOURCE_CONTROL).read_bytes())
    declaration['service_account']=dict(name='clashyaml',uid=12345,gid=12345)
    (source/c.SOURCE_CONTROL).write_text(json.dumps(declaration))
    marker=source/'.service-account';marker.write_bytes(b'clashyaml:12345:12345\n');marker.chmod(0o600)
    before={str(p.relative_to(source)):v.fingerprint(p.stat()) for p in [source,*source.rglob('*')]}
    result=c.collect(source,destination,c.PROFILE)
    assert result['collection_status']=='COLLECTED'
    assert before=={str(p.relative_to(source)):v.fingerprint(p.stat()) for p in [source,*source.rglob('*')]}
    ledger=json.loads((destination/c.OWNERSHIP_FILE).read_bytes())
    entry=next(x for x in ledger['original_entries'] if x['path']=='state/auth.json')
    assert entry['original']['uid']==12345 and entry['original']['gid']==12345
    assert ledger['collected_owner']==dict(uid=0,gid=0) and ledger['restore_mapping_applied'] is False
    assert all(p.stat().st_uid==0 and p.stat().st_gid==0 for p in [destination,*destination.rglob('*')])
    snapshot=parent/'root-snapshot'
    assert w.create(destination,snapshot,'UPDATER_SNAPSHOT')['creation_status']=='CREATED'
    assert v.verify(snapshot)['verification_status']=='INTERNALLY_CONSISTENT'
    marker.unlink()
    missing=c.collect(source,parent/'missing-marker-refused',c.PROFILE)
    assert missing['collection_status']=='FAILED' and 'SERVICE_MARKER_REQUIRED' in missing['validation_codes']
    marker.write_bytes(b'clashyaml:12346:12345\n');marker.chmod(0o600)
    mismatch=c.collect(source,parent/'mismatched-marker-refused',c.PROFILE)
    assert mismatch['collection_status']=='FAILED' and 'SERVICE_IDENTITY_MISMATCH' in mismatch['validation_codes']
    marker.write_bytes(b'clashyaml:12345:12345\n')
    os.chown(source/'state/auth.json',12346,12345)
    refused=c.collect(source,parent/'foreign-refused',c.PROFILE)
    assert refused['collection_status']=='FAILED' and 'UNSAFE_SOURCE_OWNERSHIP' in refused['validation_codes']
    assert not (parent/'foreign-refused').exists()
    print(json.dumps(dict(result='PASS',real_mixed_ownership=True,root_compatible=True,
          unexpected_owner_refused=True,marker_required=True,marker_match_checked=True,writer_verifier=True,restore_proven=False)))
finally:
    for p in [parent,*parent.rglob('*')]:os.chown(p,uid,gid)
'''
    result = subprocess.run(['sudo', '-n', sys.executable, '-c', code, *map(str, offline), str(os.geteuid()), str(os.getegid())],
                            cwd=ROOT, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, 'LINUX_ROOT_FIXTURE_GATE_NOT_PROVEN'
    proof = json.loads(result.stdout)
    assert proof['result'] == 'PASS' and proof['real_mixed_ownership'] is True
    assert proof['unexpected_owner_refused'] is True and proof['writer_verifier'] is True
    with capsys.disabled():
        print('COLLECTOR_MIXED_OWNER_NATIVE: PASS ' + json.dumps(proof, sort_keys=True))


def test_stage_name_collision_is_never_owned_or_cleaned(offline, monkeypatch):
    monkeypatch.setattr(collector.secrets, 'token_hex', lambda _: 'd' * 32)
    existing = offline[1].parent / ('.backup-collect-' + 'd' * 32)
    existing.mkdir(mode=0o700); (existing / 'external').write_bytes(SECRET.encode())
    before = frozen(existing)
    result = run(offline)
    assert result['collection_status'] == 'FAILED' and 'STAGING_NAME_COLLISION' in result['validation_codes']
    assert result['cleanup_status'] == 'NOT_NEEDED' and result['residual_staging_name'] is None
    assert frozen(existing) == before and not offline[1].exists()


def test_interrupted_mkdir_without_inode_ledger_never_blindly_deletes(offline, monkeypatch):
    actual = os.mkdir
    def interrupted(name, *args, **kwargs):
        actual(name, *args, **kwargs)
        if str(name).startswith('.backup-collect-'):
            raise KeyboardInterrupt
    monkeypatch.setattr(os, 'mkdir', interrupted)
    result = run(offline)
    assert result['collection_status'] == 'FAILED' and 'COLLECTION_INTERRUPTED' in result['validation_codes']
    assert result['cleanup_status'] == 'FAILED' and 'CLEANUP_FAILED' in result['validation_codes']
    assert result['residual_staging_name'].startswith('.backup-collect-')
    residual = offline[1].parent / result['residual_staging_name']
    assert residual.is_dir() and not list(residual.iterdir()) and not offline[1].exists()


def test_collector_limits_reserve_room_for_existing_manifest_contract():
    assert collector.MAX_ENTRIES <= verifier.MAX_ENTRIES
    assert collector.MAX_DEPTH <= verifier.MAX_DEPTH
    assert collector.MAX_FILE_BYTES <= verifier.MAX_FILE_BYTES
    assert collector.MAX_TOTAL_BYTES <= verifier.MAX_TOTAL_BYTES
    assert 2 * collector.MAX_METADATA_BYTES < protocol.MAX_MANIFEST_BYTES


def test_stock_default_bytes_collected_without_transform(offline):
    original = (ROOT / 'defaults/default.yaml').read_bytes()
    (offline[0] / 'defaults/default.yaml').write_bytes(original)
    assert run(offline)['collection_status'] == 'COLLECTED'
    assert hashlib.sha256((offline[1] / 'defaults/default.yaml').read_bytes()).hexdigest() == 'bc24dc51c528f7410c7e566f91c82883d2a2574ae3b359847e7ecfd854190576'


def test_untracked_staging_object_is_preserved_on_cleanup_failure(offline, monkeypatch):
    actual = collector.Collector.copy
    outsider = []
    def inject(self, fd, records):
        actual(self, fd, records)
        path = offline[1].parent / self.stage_name / 'external-object'
        path.write_bytes(b'unrelated'); path.chmod(0o600)
        outsider.append((path, verifier.fingerprint(path.stat())))
    monkeypatch.setattr(collector.Collector, 'copy', inject)
    result = run(offline)
    refusal(result, offline, 'STAGING_CHANGED', 'FAILED')
    path, before = outsider[0]
    assert path.read_bytes() == b'unrelated' and verifier.fingerprint(path.stat()) == before


def test_stored_byte_corruption_refused_before_publication(offline, monkeypatch):
    actual = collector.Collector.copy
    before = frozen(offline[0])
    def corrupt(self, fd, records):
        actual(self, fd, records)
        path = offline[1].parent / self.stage_name / '.env'
        data = path.read_bytes()
        path.write_bytes(b'X' + data[1:])
    monkeypatch.setattr(collector.Collector, 'copy', corrupt)
    refusal(run(offline), offline, 'STORED_BYTES_MISMATCH', 'CLEANED')
    assert frozen(offline[0]) == before


def test_post_publication_fsync_failure_retains_result(offline, monkeypatch):
    actual = os.fsync
    def fail_after_publication(fd):
        if offline[1].exists(): raise OSError(errno.EIO, SECRET)
        actual(fd)
    monkeypatch.setattr(os, 'fsync', fail_after_publication)
    result = run(offline)
    assert result['collection_status'] == 'FAILED' and result['publication_status'] == 'PUBLISHED'
    assert result['cleanup_status'] == 'NOT_ATTEMPTED_PUBLISHED' and result['retained_destination'] is True
    assert offline[1].exists()
