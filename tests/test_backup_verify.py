"""Offline Manifest v1 fixtures only; this helper is not a backup writer."""
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys

import pytest

from conftest import ROOT
from scripts import backup_manifest as protocol
from scripts import backup_verify as verifier


SECRET = 'manifest-fixture-secret-勿輸出'
TOKEN = 'manifest-fixture-bearer-token'
PASSWORD_HASH = 'manifest-fixture-password-hash'
URI = 'trojan://fixture-password@example.invalid:443'
URL = 'https://example.invalid/s/' + TOKEN


def metadata(path):
    info = path.stat()
    return dict(mode=f'{stat.S_IMODE(info.st_mode):04o}', uid=info.st_uid, gid=info.st_gid)


def encode(value):
    """Test negative fixtures independently of the protocol's schema checks."""
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode('ascii')


def publish(root, value):
    raw = encode(value)
    (root / protocol.MANIFEST_NAME).write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def fixture_manifest(root, exclusions=()):
    """Only synthetic tmp_path trees. Never used by the CLI or deployment."""
    entries = []
    excluded = set(exclusions)
    for folder, directories, names in os.walk(root, followlinks=False):
        folder = Path(folder)
        relative = folder.relative_to(root).as_posix()
        if folder != root:
            entries.append(dict(path=relative, type='directory', size=None, sha256=None, **metadata(folder)))
        if relative in excluded:
            directories[:] = []
            continue
        for name in names:
            path = folder / name
            relative_file = path.relative_to(root).as_posix()
            if relative_file == protocol.MANIFEST_NAME:
                continue
            data = path.read_bytes()
            entries.append(dict(path=relative_file, type='file', size=len(data),
                                sha256=hashlib.sha256(data).hexdigest(), **metadata(path)))
    entries.sort(key=lambda item: item['path'].encode('utf-8'))
    return dict(schema_version=1, snapshot_type='UPDATER_SNAPSHOT',
                snapshot_scope='DECLARED_EXCLUSIONS' if excluded else 'FULL_TREE',
                root_metadata=metadata(root), entries=entries,
                exclusions=[dict(path=p, reason='VENV_NOT_VERIFIED') for p in sorted(excluded)])


@pytest.fixture
def snapshot(tmp_path):
    root = tmp_path / 'offline-fixture'
    (root / 'data').mkdir(parents=True)
    (root / 'empty-directory').mkdir()
    (root / 'VERSION').write_bytes(b'1.7.0\n')
    (root / 'app.py').write_text('raise RuntimeError("never execute backup code")\n')
    (root / 'data/auth.json').write_text(json.dumps(dict(password_hash=PASSWORD_HASH, secret=SECRET,
                                                       token=TOKEN, node=URI, url=URL)))
    (root / 'data' / (SECRET + '.bin')).write_bytes(b'\x00\xff' + SECRET.encode())
    manifest = fixture_manifest(root)
    raw = protocol.canonical_bytes(manifest)
    (root / protocol.MANIFEST_NAME).write_bytes(raw)
    return root, manifest, hashlib.sha256(raw).hexdigest()


def safe_output(report, root=None):
    for output in (verifier.render(report), verifier.render(report, True)):
        for secret in (SECRET, TOKEN, PASSWORD_HASH, URI, URL, str(root) if root else 'private-absolute-path'):
            assert secret not in output
    assert report['restore_proven'] is False


def not_verified(report, code):
    assert report['verification_status'] == 'NOT_VERIFIED'
    assert report['file_hash_match'] is False
    assert report['declared_scope_verified'] is False
    assert report['full_file_coverage'] is False
    assert code in report['validation_codes']
    safe_output(report)


def frozen_tree(root):
    values = {}
    for folder, _, names in os.walk(root, followlinks=False):
        folder = Path(folder)
        values[folder.relative_to(root).as_posix()] = (verifier.fingerprint(folder.lstat()), None)
        for name in names:
            path = folder / name
            values[path.relative_to(root).as_posix()] = (verifier.fingerprint(path.lstat()),
                os.readlink(path) if path.is_symlink() else path.read_bytes())
    return values


def test_valid_full_coverage_stable_and_read_only(snapshot, monkeypatch):
    root, manifest, anchor = snapshot
    before = frozen_tree(root)
    def fail(*args, **kwargs):
        pytest.fail('verifier attempted mutation or execution')
    for name in ('chmod', 'chown', 'fchmod', 'fchown', 'mkdir', 'unlink', 'remove', 'rename', 'replace', 'system'):
        monkeypatch.setattr(os, name, fail)
    monkeypatch.setattr(subprocess, 'run', fail)
    original_open = os.open
    def readonly(name, flags, *args, **kwargs):
        assert flags & os.O_ACCMODE == os.O_RDONLY
        assert not flags & (os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        assert flags & os.O_NOFOLLOW and flags & os.O_NONBLOCK
        return original_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', readonly)
    first = verifier.verify(root, anchor)
    assert verifier.verify(root, anchor) == first
    assert first['verification_status'] == 'TRUSTED_SCOPE_VERIFIED'
    assert all(first[key] is True for key in ('file_hash_match', 'manifest_digest_match',
               'trust_anchor_verified', 'declared_scope_verified', 'full_file_coverage'))
    assert frozen_tree(root) == before
    safe_output(first, root)


def test_missing_anchor_only_internal_consistency(snapshot):
    root, _, _ = snapshot
    report = verifier.verify(root)
    assert report['verification_status'] == 'INTERNALLY_CONSISTENT'
    assert report['file_hash_match'] is True
    assert report['manifest_digest_match'] is None
    assert report['trust_anchor_verified'] is False
    assert 'TRUST_ANCHOR_NOT_PROVIDED' in report['validation_codes']
    assert 'TRUST_ANCHOR_VERIFIED' not in report['validation_codes']
    safe_output(report, root)


def test_one_byte_corruption_and_anchor_are_distinct(snapshot):
    root, _, anchor = snapshot
    path = root / 'data/auth.json'
    data = path.read_bytes()
    path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    report = verifier.verify(root, anchor)
    not_verified(report, 'FILE_DIGEST_MISMATCH')
    assert report['manifest_digest_match'] is report['trust_anchor_verified'] is True


def test_deleted_file(snapshot):
    root, _, anchor = snapshot
    (root / 'VERSION').unlink()
    not_verified(verifier.verify(root, anchor), 'LISTED_ENTRY_MISSING')


def test_extra_unlisted_file(snapshot):
    root, _, anchor = snapshot
    (root / SECRET).write_text(SECRET)
    report = verifier.verify(root, anchor)
    not_verified(report, 'UNLISTED_ENTRY')
    safe_output(report, root)


def test_modified_manifest_external_binding(snapshot):
    root, manifest, anchor = snapshot
    manifest['snapshot_type'] = 'UI_OVERLAY_BACKUP'
    publish(root, manifest)
    not_verified(verifier.verify(root, anchor), 'MANIFEST_DIGEST_MISMATCH')


def test_wrong_external_digest(snapshot):
    root, _, _ = snapshot
    report = verifier.verify(root, '0' * 64)
    not_verified(report, 'MANIFEST_DIGEST_MISMATCH')
    assert report['manifest_digest_match'] is report['trust_anchor_verified'] is False


def test_self_consistent_rewrite_does_not_authenticate_itself(snapshot):
    root, _, original_anchor = snapshot
    (root / 'VERSION').write_bytes(b'0.0.0\n')
    publish(root, fixture_manifest(root))
    report = verifier.verify(root)
    assert report['verification_status'] == 'INTERNALLY_CONSISTENT'
    assert report['trust_anchor_verified'] is False
    not_verified(verifier.verify(root, original_anchor), 'MANIFEST_DIGEST_MISMATCH')


def test_same_directory_digest_is_never_auto_trusted(snapshot):
    root, _, anchor = snapshot
    (root / 'expected.sha256').write_text(anchor)
    report = verifier.verify(root)
    not_verified(report, 'UNLISTED_ENTRY')
    assert report['trust_anchor_verified'] is False
    publish(root, fixture_manifest(root))  # Listed as ordinary fixture data, still not a trust anchor.
    report = verifier.verify(root)
    assert report['verification_status'] == 'INTERNALLY_CONSISTENT'
    assert report['trust_anchor_verified'] is False


def test_duplicate_entry(snapshot):
    root, manifest, _ = snapshot
    manifest['entries'].append(copy.deepcopy(manifest['entries'][0]))
    publish(root, manifest)
    not_verified(verifier.verify(root), 'DUPLICATE_PATH')


@pytest.mark.parametrize('path', ['/absolute', '../outside', 'data/../outside', './VERSION',
    'data//file', 'data/', 'data/./file', 'C:/file', 'data\\file', 'data/ file', 'data/file ',
    'data/file.', 'data/e\u0301', 'data/\x00file', 'data/\ud800', protocol.MANIFEST_NAME],
    ids=['absolute', 'parent', 'nested-parent', 'dot-prefix', 'empty-part', 'trailing-slash',
         'dot-part', 'windows-absolute', 'backslash', 'leading-space', 'trailing-space',
         'trailing-dot', 'non-nfc', 'control', 'surrogate', 'self-reference'])
def test_noncanonical_or_traversal_paths(snapshot, path):
    root, manifest, _ = snapshot
    manifest['entries'][0]['path'] = path
    publish(root, manifest)
    report = verifier.verify(root)
    not_verified(report, 'MANIFEST_SELF_REFERENCE' if path == protocol.MANIFEST_NAME else 'NON_CANONICAL_PATH')


@pytest.mark.parametrize('mutation, code', [
    ('unsupported-version', 'UNSUPPORTED_SCHEMA_VERSION'), ('boolean-version', 'INVALID_MANIFEST_SCHEMA'),
    ('unknown-field', 'INVALID_MANIFEST_SCHEMA'), ('unsafe-type', 'UNSAFE_MANIFEST_TYPE'),
    ('bad-digest', 'MALFORMED_DIGEST'), ('negative-size', 'INVALID_FILE_SIZE'),
    ('boolean-size', 'INVALID_FILE_SIZE'), ('bad-mode', 'INVALID_PERMISSION_METADATA'),
    ('boolean-owner', 'INVALID_PERMISSION_METADATA'), ('directory-digest', 'INVALID_DIRECTORY_ENTRY'),
    ('unsorted', 'NON_CANONICAL_ENTRY_ORDER'), ('missing-parent', 'INVALID_ENTRY_HIERARCHY'),
])
def test_malformed_schema(snapshot, mutation, code):
    root, manifest, _ = snapshot
    file_entry = next(item for item in manifest['entries'] if item['type'] == 'file')
    if mutation == 'unsupported-version': manifest['schema_version'] = 2
    elif mutation == 'boolean-version': manifest['schema_version'] = True
    elif mutation == 'unknown-field': manifest[SECRET] = SECRET
    elif mutation == 'unsafe-type': file_entry['type'] = 'symlink'
    elif mutation == 'bad-digest': file_entry['sha256'] = SECRET
    elif mutation == 'negative-size': file_entry['size'] = -1
    elif mutation == 'boolean-size': file_entry['size'] = True
    elif mutation == 'bad-mode': file_entry['mode'] = '4755'
    elif mutation == 'boolean-owner': file_entry['uid'] = True
    elif mutation == 'directory-digest': next(e for e in manifest['entries'] if e['type'] == 'directory')['sha256'] = '0' * 64
    elif mutation == 'unsorted': manifest['entries'].reverse()
    elif mutation == 'missing-parent': manifest['entries'] = [e for e in manifest['entries'] if e['path'] != 'data']
    publish(root, manifest)
    not_verified(verifier.verify(root), code)


@pytest.mark.parametrize('raw', [b'{', b'\xff', b'{"schema_version":1,"schema_version":1}',
    b'{"x":NaN}', b'{"x":Infinity}'], ids=['truncated', 'utf8', 'duplicate-json-key', 'nan', 'infinity'])
def test_malformed_json(snapshot, raw):
    root, _, _ = snapshot
    (root / protocol.MANIFEST_NAME).write_bytes(raw)
    report = verifier.verify(root)
    not_verified(report, 'DUPLICATE_JSON_KEY' if b'schema_version' in raw else 'INVALID_MANIFEST_JSON')


@pytest.mark.parametrize('formatting', ['newline', 'indent', 'utf8-literal', 'bom'])
def test_canonical_bytes_required(snapshot, formatting):
    root, manifest, _ = snapshot
    raw = encode(manifest)
    if formatting == 'newline': raw += b'\n'
    elif formatting == 'indent': raw = json.dumps(manifest, indent=2).encode()
    elif formatting == 'utf8-literal': raw = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    else: raw = b'\xef\xbb\xbf' + raw
    (root / protocol.MANIFEST_NAME).write_bytes(raw)
    not_verified(verifier.verify(root), 'INVALID_MANIFEST_JSON' if formatting == 'bom' else 'NON_CANONICAL_MANIFEST')


def test_symlink_never_followed(snapshot, tmp_path, monkeypatch):
    root, _, anchor = snapshot
    outside = tmp_path / 'outside-secret'
    outside.write_text(SECRET)
    path = root / 'data/auth.json'
    path.unlink()
    path.symlink_to(outside)
    original_open = os.open
    def guarded(name, flags, *args, **kwargs):
        assert name not in ('auth.json', str(outside))
        return original_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', guarded)
    not_verified(verifier.verify(root, anchor), 'UNSAFE_OBJECT')


def test_hardlink_rejected(snapshot, tmp_path):
    root, _, anchor = snapshot
    os.link(root / 'VERSION', tmp_path / 'external-hardlink')
    not_verified(verifier.verify(root, anchor), 'UNSAFE_OBJECT')


@pytest.mark.parametrize('object_kind', ['fifo', 'socket', 'directory'])
def test_special_object_or_wrong_type(snapshot, monkeypatch, object_kind):
    root, _, anchor = snapshot
    path = root / 'data/auth.json'
    path.unlink()
    server = None
    if object_kind == 'fifo': os.mkfifo(path)
    elif object_kind == 'socket':
        monkeypatch.chdir(root)
        server = socket.socket(socket.AF_UNIX)
        server.bind('data/auth.json')
    else: path.mkdir()
    try:
        not_verified(verifier.verify(root, anchor), 'FILE_TYPE_MISMATCH' if object_kind == 'directory' else 'UNSAFE_OBJECT')
    finally:
        if server: server.close()


def test_device_rejected_without_open(snapshot, monkeypatch):
    root, _, anchor = snapshot
    original_stat, original_open = os.stat, os.open
    def device(name, *args, **kwargs):
        info = original_stat(name, *args, **kwargs)
        if name == 'auth.json':
            values = list(info)
            values[0] = stat.S_IFCHR | 0o600
            return os.stat_result(values)
        return info
    def guarded(name, flags, *args, **kwargs):
        assert name != 'auth.json'
        return original_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'stat', device)
    monkeypatch.setattr(os, 'open', guarded)
    not_verified(verifier.verify(root, anchor), 'UNSAFE_OBJECT')


def test_venv_exclusion_explicitly_has_no_full_coverage(snapshot, monkeypatch):
    root, _, _ = snapshot
    (root / 'venv/bin').mkdir(parents=True)
    (root / 'venv/bin/python').symlink_to(sys.executable)
    manifest = fixture_manifest(root, exclusions=('venv',))
    anchor = publish(root, manifest)
    original_open = os.open
    def no_venv_read(name, flags, *args, **kwargs):
        assert name not in ('venv', 'bin', 'python', sys.executable)
        return original_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', no_venv_read)
    report = verifier.verify(root, anchor)
    assert report['verification_status'] == 'TRUSTED_SCOPE_VERIFIED'
    assert report['declared_scope_verified'] is report['file_hash_match'] is True
    assert report['full_file_coverage'] is False
    assert 'EXCLUDED_CONTENT_NOT_VERIFIED' in report['validation_codes']
    safe_output(report, root)


def test_venv_is_not_silently_ignored(snapshot):
    root, manifest, _ = snapshot
    (root / 'venv').mkdir()
    (root / 'venv/python').symlink_to(sys.executable)
    manifest['entries'].append(dict(path='venv', type='directory', size=None, sha256=None, **metadata(root / 'venv')))
    manifest['entries'].sort(key=lambda item: item['path'].encode())
    anchor = publish(root, manifest)
    not_verified(verifier.verify(root, anchor), 'UNSAFE_OBJECT')


@pytest.mark.parametrize('case, code', [
    ('missing-root', 'INVALID_EXCLUSION'), ('duplicate', 'DUPLICATE_EXCLUSION'),
    ('included-child', 'EXCLUSION_CONFLICT'), ('full-tree', 'INVALID_SNAPSHOT_SCOPE'),
    ('empty-exclusions', 'INVALID_SNAPSHOT_SCOPE'), ('bad-reason', 'INVALID_EXCLUSION'),
])
def test_exclusion_schema(snapshot, case, code):
    root, manifest, _ = snapshot
    manifest['snapshot_scope'] = 'DECLARED_EXCLUSIONS'
    manifest['exclusions'] = [dict(path='empty-directory', reason='OUT_OF_SCOPE')]
    if case == 'missing-root': manifest['exclusions'][0]['path'] = 'missing'
    elif case == 'duplicate': manifest['exclusions'] *= 2
    elif case == 'included-child': manifest['exclusions'][0]['path'] = 'data'
    elif case == 'full-tree': manifest['snapshot_scope'] = 'FULL_TREE'
    elif case == 'empty-exclusions': manifest['exclusions'] = []
    else: manifest['exclusions'][0]['reason'] = SECRET
    publish(root, manifest)
    not_verified(verifier.verify(root), code)


def test_chunked_large_binary_file(snapshot, monkeypatch):
    root, _, _ = snapshot
    (root / 'large.bin').write_bytes(b'\x00\xff' * (1024 * 1024))
    anchor = publish(root, fixture_manifest(root))
    original_read, sizes = os.read, []
    def bounded(fd, size):
        assert 0 < size <= verifier.CHUNK_BYTES
        sizes.append(size)
        return original_read(fd, size)
    monkeypatch.setattr(os, 'read', bounded)
    assert verifier.verify(root, anchor)['verification_status'] == 'TRUSTED_SCOPE_VERIFIED'
    assert sizes.count(verifier.CHUNK_BYTES) >= 32


@pytest.mark.parametrize('limit, value, code', [
    ('MAX_FILE_BYTES', 1, 'FILE_BYTE_LIMIT'), ('MAX_TOTAL_BYTES', 1, 'TOTAL_BYTE_LIMIT'),
    ('MAX_ENTRIES', 2, 'ENTRY_LIMIT'), ('MAX_DEPTH', 0, 'DEPTH_LIMIT'),
    ('MAX_SECONDS', -1, 'TIME_LIMIT'),
])
def test_resource_limits_never_partial_success(snapshot, monkeypatch, limit, value, code):
    root, _, anchor = snapshot
    monkeypatch.setattr(verifier, limit, value)
    not_verified(verifier.verify(root, anchor), code)


def test_oversized_manifest_not_read(snapshot, monkeypatch):
    root, _, _ = snapshot
    monkeypatch.setattr(protocol, 'MAX_MANIFEST_BYTES', 8)
    monkeypatch.setattr(os, 'read', lambda *args: pytest.fail('oversized manifest was read'))
    not_verified(verifier.verify(root), 'MANIFEST_SIZE_LIMIT')


@pytest.mark.parametrize('change', ['replace', 'symlink', 'fifo'])
def test_concurrent_replacement_between_stat_and_open(snapshot, monkeypatch, change):
    root, _, anchor = snapshot
    original_open = os.open
    changed = False
    def racing(name, flags, *args, **kwargs):
        nonlocal changed
        if name == 'VERSION' and not changed:
            path = root / 'VERSION'
            data = path.read_bytes()
            path.unlink()
            if change == 'replace': path.write_bytes(data)
            elif change == 'symlink': path.symlink_to(root / 'data/auth.json')
            else: os.mkfifo(path)
            changed = True
        return original_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', racing)
    report = verifier.verify(root, anchor)
    not_verified(report, 'UNSAFE_PATH' if change == 'symlink' else 'BACKUP_CHANGED')


def test_changed_after_hashing_detected(snapshot, monkeypatch):
    root, _, anchor = snapshot
    original = verifier.Verifier.consume
    def racing(self, fd, path, records, collect=False):
        data = original(self, fd, path, records, collect)
        if path == ('VERSION',):
            (root / 'VERSION').write_bytes(b'0.0.0\n')
        return data
    monkeypatch.setattr(verifier.Verifier, 'consume', racing)
    not_verified(verifier.verify(root, anchor), 'BACKUP_CHANGED')


def test_permission_error_sanitized(snapshot, monkeypatch):
    root, _, anchor = snapshot
    original_open = os.open
    def denied(name, flags, *args, **kwargs):
        if name == 'auth.json': raise PermissionError(13, SECRET, str(root / SECRET))
        return original_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', denied)
    not_verified(verifier.verify(root, anchor), 'PERMISSION_DENIED')


@pytest.mark.parametrize('field', ['mode', 'uid', 'gid'])
def test_metadata_matches_actual(snapshot, field):
    root, manifest, _ = snapshot
    actual = manifest['root_metadata'][field]
    manifest['root_metadata'][field] = ('0777' if actual == '0000' else '0000') if field == 'mode' else (actual + 1) % (2**32 - 1)
    anchor = publish(root, manifest)
    not_verified(verifier.verify(root, anchor), 'PERMISSION_METADATA_MISMATCH')


def test_legacy_missing_manifest_no_creation(snapshot):
    root, _, _ = snapshot
    (root / protocol.MANIFEST_NAME).unlink()
    before = frozen_tree(root)
    not_verified(verifier.verify(root), 'MANIFEST_MISSING')
    assert frozen_tree(root) == before


def test_live_installation_refused_before_open(monkeypatch):
    monkeypatch.setattr(os, 'open', lambda *args, **kwargs: pytest.fail('live tree opened'))
    not_verified(verifier.verify('/opt/clash-yaml-manager/state'), 'LIVE_INSTALLATION_REFUSED')


def test_root_symlink_refused(snapshot, tmp_path):
    root, _, _ = snapshot
    link = tmp_path / 'link'
    link.symlink_to(root, target_is_directory=True)
    not_verified(verifier.verify(link), 'UNSAFE_ROOT_PATH')


def test_deterministic_serialization_and_golden_vector():
    value = dict(schema_version=1, snapshot_type='UI_OVERLAY_BACKUP', snapshot_scope='FULL_TREE',
                 root_metadata=dict(mode='0700', uid=0, gid=0), entries=[], exclusions=[])
    golden = (b'{"entries":[],"exclusions":[],"root_metadata":{"gid":0,"mode":"0700","uid":0},'
              b'"schema_version":1,"snapshot_scope":"FULL_TREE","snapshot_type":"UI_OVERLAY_BACKUP"}')
    assert protocol.canonical_bytes(value) == golden
    reordered = {key: value[key] for key in reversed(value)}
    reordered['root_metadata'] = dict(reversed(list(value['root_metadata'].items())))
    assert protocol.canonical_bytes(reordered) == golden
    assert protocol.load_manifest(golden) == value
    assert b'\n' not in golden and not golden.startswith(b'\xef\xbb\xbf')


def test_json_schema_contract_matches_protocol():
    schema = json.loads((ROOT / 'schemas/backup-manifest-v1.schema.json').read_text())
    properties, definitions = schema['properties'], schema['$defs']
    assert properties['schema_version']['const'] == protocol.SCHEMA_VERSION
    assert tuple(properties['snapshot_type']['enum']) == protocol.SNAPSHOT_TYPES
    assert tuple(properties['snapshot_scope']['enum']) == protocol.SCOPES
    assert tuple(properties['exclusions']['items']['properties']['reason']['enum']) == protocol.EXCLUSION_REASONS
    assert set(definitions['entry']['required']) == protocol.ENTRY_KEYS
    assert properties['entries']['maxItems'] + 2 == protocol.MAX_ENTRIES
    assert definitions['digest']['pattern'] == '^' + protocol.DIGEST_PATTERN + '$'
    assert definitions['mode']['pattern'] == '^' + protocol.MODE_PATTERN + '$'


@pytest.mark.parametrize('as_json', [False, True])
def test_cli_safe_output_and_read_only(snapshot, as_json):
    root, _, anchor = snapshot
    before = frozen_tree(root)
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/backup_verify.py'), '--path', str(root),
                             '--trusted-manifest-sha256', anchor] + (['--json'] if as_json else []),
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0 and not result.stderr
    for secret in (SECRET, TOKEN, PASSWORD_HASH, URI, URL, str(root), anchor):
        assert secret not in result.stdout
    if as_json: assert json.loads(result.stdout)['restore_proven'] is False
    assert frozen_tree(root) == before


def test_cli_errors_do_not_echo_secret(snapshot, capsys):
    root, _, _ = snapshot
    assert verifier.main(['--path', str(root), '--trusted-manifest-sha256', SECRET, '--json']) == 1
    assert verifier.main(['--json', '--unknown=' + SECRET]) == 64
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
    assert str(root) not in output.out


@pytest.mark.parametrize('object_kind', ['symlink', 'hardlink', 'fifo', 'directory'])
def test_manifest_control_object_unsafe_before_read(snapshot, tmp_path, monkeypatch, object_kind):
    root, _, anchor = snapshot
    path = root / protocol.MANIFEST_NAME
    outside = tmp_path / 'outside-manifest'
    outside.write_bytes(path.read_bytes())
    path.unlink()
    if object_kind == 'symlink': path.symlink_to(outside)
    elif object_kind == 'hardlink': os.link(outside, path)
    elif object_kind == 'fifo': os.mkfifo(path)
    else: path.mkdir()
    original_open = os.open
    def guarded(name, flags, *args, **kwargs):
        assert name not in (protocol.MANIFEST_NAME, str(outside))
        return original_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', guarded)
    not_verified(verifier.verify(root, anchor), 'UNSAFE_FILE')


def test_ancestor_symlink(snapshot, tmp_path):
    root, _, anchor = snapshot
    link = tmp_path / 'ancestor-link'
    link.symlink_to(root.parent, target_is_directory=True)
    not_verified(verifier.verify(link / root.name, anchor), 'UNSAFE_ROOT_PATH')


def test_chunk_growth_never_partial_verified(snapshot, monkeypatch):
    root, _, anchor = snapshot
    original_read = os.read
    inode = (root / 'VERSION').stat().st_ino
    changed = False
    def growing(fd, size):
        nonlocal changed
        piece = original_read(fd, size)
        if not changed and os.fstat(fd).st_ino == inode:
            with (root / 'VERSION').open('ab') as target:
                target.write(b'x')
            changed = True
        return piece
    monkeypatch.setattr(os, 'read', growing)
    not_verified(verifier.verify(root, anchor), 'BACKUP_CHANGED')


def test_manifest_changed_after_read(snapshot, monkeypatch):
    root, _, anchor = snapshot
    original = verifier.Verifier.consume
    def racing(self, fd, path, records, collect=False):
        raw = original(self, fd, path, records, collect)
        if collect:
            (root / protocol.MANIFEST_NAME).write_bytes(raw + b'\n')
        return raw
    monkeypatch.setattr(verifier.Verifier, 'consume', racing)
    not_verified(verifier.verify(root, anchor), 'BACKUP_CHANGED')


@pytest.mark.parametrize('case, code', [('entries', 'ENTRY_LIMIT'), ('depth', 'DEPTH_LIMIT'), ('path-bytes', 'PATH_LIMIT')])
def test_protocol_resource_limits(snapshot, case, code):
    root, manifest, _ = snapshot
    if case == 'entries': manifest['entries'] = manifest['entries'][:1] * protocol.MAX_ENTRIES
    elif case == 'depth': manifest['entries'][0]['path'] = '/'.join(['part'] * (protocol.MAX_DEPTH + 1))
    else: manifest['entries'][0]['path'] = 'a' * (protocol.MAX_PATH_BYTES + 1)
    publish(root, manifest)
    not_verified(verifier.verify(root), code)


def test_cli_disables_local_bytecode_writes(snapshot, tmp_path):
    import shutil
    root, _, anchor = snapshot
    cli = tmp_path / 'cli'
    cli.mkdir()
    for name in ('backup_verify.py', 'backup_manifest.py', 'backup_audit.py'):
        shutil.copy2(ROOT / 'scripts' / name, cli / name)
    environment = dict(os.environ)
    environment.pop('PYTHONDONTWRITEBYTECODE', None)
    result = subprocess.run([sys.executable, str(cli / 'backup_verify.py'), '--path', str(root),
                             '--trusted-manifest-sha256', anchor, '--json'],
                            env=environment, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0 and not result.stderr
    assert not (cli / '__pycache__').exists()


def test_empty_regular_file_hash(snapshot):
    root, _, _ = snapshot
    (root / 'empty.bin').write_bytes(b'')
    anchor = publish(root, fixture_manifest(root))
    report = verifier.verify(root, anchor)
    assert report['verification_status'] == 'TRUSTED_SCOPE_VERIFIED'
    assert report['full_file_coverage'] is True


def test_deterministic_failure_independent_of_scandir_order(snapshot, monkeypatch):
    from contextlib import contextmanager
    root, _, anchor = snapshot
    (root / 'A-directory' / Path(*(['nested'] * verifier.MAX_DEPTH))).mkdir(parents=True)
    os.mkfifo(root / 'Z-fifo')
    first = verifier.verify(root, anchor)
    not_verified(first, 'DEPTH_LIMIT')
    original = os.scandir
    @contextmanager
    def reversed_scan(fd):
        with original(fd) as scan:
            entries = list(scan)
        yield iter(reversed(entries))
    monkeypatch.setattr(os, 'scandir', reversed_scan)
    assert verifier.verify(root, anchor) == first
