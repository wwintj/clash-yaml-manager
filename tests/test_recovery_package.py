"""Real synthetic POSIX fixtures; no live installation or privilege-policy CLI bypass."""
import copy
from contextlib import ExitStack
import errno
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import shutil
import sys
import tempfile

import pytest

from scripts import recovery_manifest as schema, recovery_io as io, recovery_package as package
from scripts.backup_audit import AuditFault


@pytest.fixture
def offline(tmp_path, monkeypatch):
    # Trusted in-process test policy only. Production constants remain root/fixed path.
    monkeypatch.setattr(io, 'ROOT_UID', os.geteuid())
    monkeypatch.setattr(io, 'ROOT_GID', os.getegid())
    monkeypatch.setattr(io, 'MANAGED_ROOT', str(tmp_path / 'managed'))
    source = tmp_path / 'offline'
    source.mkdir(mode=0o700)
    for root in schema.ROOTS:
        (source / root).mkdir(mode=0o755)
    for name in ('core', 'scripts', 'templates', 'static'):
        (source / 'application' / name).mkdir(mode=0o755)
    (source / 'venv/bin').mkdir(mode=0o755)
    identity = dict(version='1.8.0', channel='stable', commit='3'*40, tag='v1.8.0')
    control = dict(source_identity=identity, target_identity=dict(identity, version='1.9.0', tag='v1.9.0'),
                   installation_binding=dict(origin='ROOT_OPERATOR_DECLARATION', install_path='/opt/clash-yaml-manager', system_id='synthetic-system'),
                   account_roles=dict(root=dict(name='root', uid=os.geteuid(), gid=os.getegid(), origin='ROOT_OPERATOR_DECLARATION'),
                                      service=dict(name='clashyaml', uid=os.geteuid()+1, gid=os.getegid()+1, origin='ROOT_OPERATOR_DECLARATION')),
                   runtime_requirements=dict(os='Linux', architecture='x86_64', python_version='3.12', python_abi='cpython-312',
                                             system_libraries=['libc.so.6'], origin='ROOT_OPERATOR_DECLARATION'), offline_quiet=True)
    installation = dict(channel='stable', base_version='1.8.0', commit='3'*40, tag='v1.8.0',
                        installed_at='2026-10-10T00:00:00+00:00', source='github-release')
    files = {'application/app.py': b'raise RuntimeError("DO NOT EXECUTE")\n',
             'application/VERSION': b'1.8.0\n', 'application/INSTALLATION.json': schema.canonical(installation),
             'application/requirements.txt': b'Flask==3.1.0\n',
             'application/scripts/tool.py': b'print("DO NOT IMPORT")\n',
             'venv/pyvenv.cfg': b'home = /usr/bin\n', 'venv/bin/helper': b'#!/bin/sh\nexit 99\n',
             'configuration/.env': b'APP_PASSWORD=SYNTHETIC_SECRET_DO_NOT_ECHO\nSECRET_KEY=fixture-only\n',
             'configuration/.service-account': b'clashyaml\n', 'default/default.yaml': b'proxies: []\nrules: []\n',
             'units/clash-yaml-manager.service': b'[Service]\nExecStart=/not/to/execute\n', 'state/auth.json': b'{"schema_version":1}\n',
             'state/.last_cleanup': b'0\n'}
    for name, data in files.items():
        (source / name).write_bytes(data)
        (source / name).chmod(0o755 if name == 'venv/bin/helper' else 0o644)
    (source / 'venv/bin/python').symlink_to('python3')
    (source / 'venv/bin/python3').symlink_to('/usr/bin/python3')
    (source / io.CONTROL).write_bytes(schema.canonical(control))
    (source / io.CONTROL).chmod(0o600)
    return source, control, Path(io.MANAGED_ROOT)


def created(offline):
    source, _, managed = offline
    result = package.create(str(source))
    assert result['code'] == 'CREATED', result
    operation = result['operation_id']
    root = managed / 'packages' / operation
    manifest = schema.parse((root / 'manifest.json').read_bytes())
    return result, root, manifest, managed / 'records' / (operation+'.json')


def test_real_package_and_readonly_verifier(offline, capsys):
    source, _, managed = offline
    before = {str(p.relative_to(source)): (p.lstat().st_mode, p.lstat().st_uid, p.lstat().st_gid, p.lstat().st_mtime_ns,
                                         os.readlink(p) if p.is_symlink() else p.read_bytes() if p.is_file() else None)
              for p in source.rglob('*')}
    result, root, manifest, record = created(offline)
    assert result['PACKAGE_CREATED'] and result['PACKAGE_VERIFIED'] and result['TRUST_ANCHOR_VERIFIED']
    assert 'UPGRADE_SUCCEEDED' not in result and result['RESTORE_PROVEN'] is False
    after = {str(p.relative_to(source)): (p.lstat().st_mode, p.lstat().st_uid, p.lstat().st_gid, p.lstat().st_mtime_ns,
                                        os.readlink(p) if p.is_symlink() else p.read_bytes() if p.is_file() else None)
             for p in source.rglob('*')}
    assert after == before
    bytes_before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    accepted = package.verify(result['operation_id'])
    assert accepted['STRUCTURAL_VALID'] and accepted['CONTENT_INTEGRITY_VALID'] and accepted['TRUST_ANCHOR_VERIFIED']
    assert accepted['RECOVERY_REQUIREMENTS_NOT_EVALUATED'] and accepted['RESTORE_PROVEN'] is False
    assert {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()} == bytes_before
    assert record.parent != root and json.loads(record.read_bytes())['manifest_sha256'] == hashlib.sha256((root / 'manifest.json').read_bytes()).hexdigest()
    assert manifest['retention'] == schema.RETENTION and manifest['retention']['completed_at'] is None
    for p in [managed, *managed.rglob('*')]:
        assert not p.is_symlink()
        assert stat.S_IMODE(p.stat().st_mode) == (0o700 if p.is_dir() else 0o600)
    assert 'SYNTHETIC_SECRET' not in capsys.readouterr().out + json.dumps(result) + json.dumps(accepted)


def test_original_executable_and_venv_link_metadata(offline):
    _, root, manifest, _ = created(offline)
    nodes = {e['path']: e for e in manifest['entries']}
    assert nodes['venv/bin/helper']['original']['mode'] == '0755'
    assert stat.S_IMODE((root / 'blobs' / nodes['venv/bin/helper']['blob']).stat().st_mode) == 0o600
    assert nodes['venv/bin/python']['link_target'] == 'python3'
    assert nodes['venv/bin/python3']['link_type'] == 'absolute'
    assert all(nodes[p]['blob'] is None for p in ('venv/bin/python', 'venv/bin/python3'))
    assert manifest['capture_evidence']['external_python_links'] == [dict(path='venv/bin/python', target='/usr/bin/python3'), dict(path='venv/bin/python3', target='/usr/bin/python3')]
    assert manifest['capture_evidence']['extended_metadata'] == 'NOT_CAPTURED_RESTORE_UNSUPPORTED'
    assert manifest['account_roles']['service']['origin'] == 'ROOT_OPERATOR_DECLARATION'
    assert nodes['state/auth.json']['original']['metadata_origin'] == 'OBSERVED_OFFLINE_FIXTURE'


@pytest.mark.parametrize('target,code', [('../../../outside', 'LINK_ESCAPE'), ('missing', 'INVALID_LINK_TARGET'),
                                      ('python', 'LINK_CYCLE'), ('/etc/passwd', 'EXTERNAL_LINK_REFUSED'),
                                      ('//usr/bin/python3', 'INVALID_LINK'), ('bad\\target', 'INVALID_LINK')])
def test_bad_venv_links(offline, target, code):
    source, _, _ = offline
    link = source / 'venv/bin/python3'
    link.unlink(); link.symlink_to(target)
    result = package.create(str(source))
    assert result['code'] == code
    assert not result['PACKAGE_CREATED'] and not result['TRUST_ANCHOR_VERIFIED']


def test_internal_directory_link_is_metadata_only(offline):
    source, _, _ = offline
    (source / 'venv/lib').mkdir()
    (source / 'venv/lib64').symlink_to('lib')
    _, _, manifest, _ = created(offline)
    assert any(e['path'] == 'venv/lib64' and e['kind'] == 'symlink' and e['link_target'] == 'lib' for e in manifest['entries'])


@pytest.mark.parametrize('name', ['application/app.py', 'configuration/.env', 'state/auth.json', 'units/clash-yaml-manager.service'])
def test_non_venv_symlink_refused(offline, name):
    source, _, _ = offline
    (source / name).unlink(); (source / name).symlink_to('/etc/passwd')
    result = package.create(str(source))
    assert result['code'] == 'OUT_OF_SCOPE'
    assert result['cleanup'] == 'NOT_CREATED'


@pytest.mark.parametrize('kind,code', [('hardlink', 'HARDLINK_REFUSED'), ('fifo', 'SPECIAL_FILE_REFUSED'), ('socket', 'SPECIAL_FILE_REFUSED')])
def test_real_special_objects(offline, kind, code):
    source, _, _ = offline
    with ExitStack() as stack:
        if kind == 'socket':
            # AF_UNIX has a small address buffer: keep the entire offline tree
            # under a short private root, with links copied without traversal.
            parent = '/private/tmp' if sys.platform == 'darwin' else '/tmp'
            short_root = stack.enter_context(tempfile.TemporaryDirectory(prefix='cp-', dir=parent))
            # Darwin inherits the parent's group, even without setgid. Set the
            # private fixture root's group before creating its descendants.
            fd = os.open(short_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                info = os.fstat(fd)
                assert info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700
                os.fchown(fd, -1, os.getegid())
                assert os.fstat(fd).st_gid == os.getegid()
            finally:
                os.close(fd)
            short_source = Path(short_root) / 's'
            shutil.copytree(source, short_source, symlinks=True)
            source = short_source
            for path in [source, *source.rglob('*')]:
                info = path.lstat()
                assert (info.st_uid, info.st_gid) == (io.ROOT_UID, io.ROOT_GID)
        name = source / 'venv/extra'
        if kind == 'hardlink':
            os.link(source / 'venv/pyvenv.cfg', name)
        elif kind == 'fifo':
            os.mkfifo(name)
        else:
            encoded = os.fsencode(name)
            assert len(encoded) <= 80  # Conservative margin, including full path.
            sock = stack.enter_context(socket.socket(socket.AF_UNIX))
            sock.bind(encoded)
            assert stat.S_ISSOCK(name.lstat().st_mode)
            print(f'SOCKET_FIXTURE path={name} bytes={len(encoded)}')
            def metadata(path):
                if not path.exists() and not path.is_symlink():
                    return dict(path=str(path), status='NOT_CREATED', realpath=os.path.realpath(path))
                info = path.lstat()
                return dict(path=str(path), realpath=os.path.realpath(path),
                            mode=f'{stat.S_IMODE(info.st_mode):04o}', uid=info.st_uid,
                            gid=info.st_gid, device=info.st_dev, type=stat.S_IFMT(info.st_mode))
            print('SOCKET_METADATA ' + json.dumps(dict(uid=os.getuid(), gid=os.getgid(),
                  groups=os.getgroups(), expected_uid=io.ROOT_UID, expected_gid=io.ROOT_GID,
                  objects={key: metadata(path) for key, path in {
                      'fixture_root': Path(short_root), 'source_root': source,
                      'control': source / io.CONTROL, 'socket_parent': name.parent,
                      'socket': name, 'writer_staging_parent': Path(io.MANAGED_ROOT) / 'packages'
                  }.items()}), sort_keys=True))
        result = package.create(str(source))
        assert result['code'] == code and not result['TRUST_ANCHOR_VERIFIED']
        if kind == 'socket':
            print(f'SOCKET_WRITER code={result["code"]} trust_anchor_verified={result["TRUST_ANCHOR_VERIFIED"]}')


@pytest.mark.parametrize('mutation,code', [('unknown', 'INVALID_SCHEMA'), ('traversal', 'INVALID_PATH'),
                                         ('duplicate_path', 'INVALID_ORDER'), ('missing', 'MISSING_REQUIRED'),
                                         ('order', 'INVALID_ORDER'), ('root', 'INVALID_SCHEMA'), ('bool_uid', 'INVALID_SCHEMA')])
def test_schema_negative(offline, mutation, code):
    _, _, manifest, _ = created(offline)
    candidate = copy.deepcopy(manifest)
    if mutation == 'unknown': candidate['future'] = True
    if mutation == 'traversal': candidate['entries'][0]['path'] = '../application'
    if mutation == 'duplicate_path': candidate['entries'].append(candidate['entries'][-1])
    if mutation == 'missing': candidate['entries'] = [e for e in candidate['entries'] if e['path'] != 'state/auth.json']
    if mutation == 'order': candidate['entries'].reverse()
    if mutation == 'root': candidate['roots']['other'] = 'UNKNOWN'
    if mutation == 'bool_uid': candidate['entries'][0]['original']['uid'] = True
    with pytest.raises(AuditFault) as failure:
        schema.validate(candidate)
    assert failure.value.code == code


def test_canonical_and_duplicate_gate(offline):
    _, _, manifest, _ = created(offline)
    raw = schema.canonical(manifest)
    assert schema.validate(schema.parse(raw)) == manifest
    for data, code in [(raw+b'\n', 'NON_CANONICAL_MANIFEST'), (b'{"a":1,"a":2}', 'DUPLICATE_KEY'),
                       (b'{"x":NaN}', 'INVALID_JSON'), (b'{'*2000, 'INVALID_JSON')]:
        with pytest.raises(AuditFault) as failure: schema.parse(data)
        assert failure.value.code == code


@pytest.mark.parametrize('mutation,code', [('content', 'CONTENT_DIGEST_MISMATCH'), ('extra', 'PAYLOAD_CLOSURE'),
                                         ('missing', 'PAYLOAD_CLOSURE'), ('permissions', 'UNSAFE_STORED_METADATA'),
                                         ('blob_link', 'UNSAFE_FILE'), ('anchor', 'MANIFEST_DIGEST_MISMATCH'),
                                         ('binding', 'RECORD_BINDING_MISMATCH'), ('inode', 'RECORD_BINDING_MISMATCH'),
                                         ('canonical_tamper', 'MANIFEST_DIGEST_MISMATCH'), ('noncanonical', 'NON_CANONICAL_MANIFEST')])
def test_real_verifier_rejections(offline, mutation, code):
    result, root, manifest, record_file = created(offline)
    file = next(e for e in manifest['entries'] if e['kind'] == 'file')
    blob = root / 'blobs' / file['blob']
    original_anchor = record_file.read_bytes()
    if mutation == 'content': blob.write_bytes(b'altered')
    if mutation == 'extra': (root / 'blobs/extra').write_bytes(b'junk')
    if mutation == 'missing': blob.unlink()
    if mutation == 'permissions': blob.chmod(0o644)
    if mutation == 'blob_link': blob.unlink(); blob.symlink_to('/etc/passwd')
    if mutation in ('anchor', 'binding', 'inode'):
        record = schema.parse(original_anchor)
        if mutation == 'anchor': record['manifest_sha256'] = '0'*64
        if mutation == 'binding': record['target_identity'] = dict(record['target_identity'], version='2.0.0', tag='v2.0.0')
        if mutation == 'inode': record['package_inode'] += 1
        record_file.write_bytes(schema.canonical(record))
    if mutation == 'canonical_tamper':
        manifest['target_identity'] = dict(manifest['target_identity'], version='2.0.0', tag='v2.0.0')
        schema.validate(manifest)
        (root / 'manifest.json').write_bytes(schema.canonical(manifest))
    if mutation == 'noncanonical': (root / 'manifest.json').write_bytes((root / 'manifest.json').read_bytes()+b'\n')
    rejected = package.verify(result['operation_id'])
    assert rejected['code'] == code, rejected
    assert not rejected['TRUST_ANCHOR_VERIFIED'] and not rejected['RESTORE_PROVEN']
    if mutation not in ('anchor', 'binding', 'inode'): assert record_file.read_bytes() == original_anchor


@pytest.mark.parametrize('which', ['missing', 'unknown', 'ownership', 'quiet', 'control_permission'])
def test_source_admission(offline, which):
    source, control, managed = offline
    if which == 'missing': (source / 'configuration/.env').unlink()
    if which == 'unknown': (source / 'surprise').write_bytes(b'no')
    if which == 'ownership': control['account_roles']['root']['uid'] += 99
    if which == 'quiet': control['offline_quiet'] = False
    (source / io.CONTROL).write_bytes(schema.canonical(control))
    if which == 'control_permission': (source / io.CONTROL).chmod(0o644)
    expected = dict(missing='MISSING_REQUIRED', unknown='OUT_OF_SCOPE', ownership='UNSAFE_OWNERSHIP',
                    quiet='OFFLINE_QUIET_REQUIRED', control_permission='UNSAFE_STORED_METADATA')[which]
    assert package.create(str(source))['code'] == expected
    assert not managed.exists()


@pytest.mark.parametrize('fault', [errno.ENOSPC, errno.EIO, errno.EACCES])
def test_write_faults_keep_private_staging_no_cleanup(offline, monkeypatch, fault):
    source, _, managed = offline
    def fail(*args, **kwargs): raise OSError(fault, 'SYNTHETIC_SECRET_DO_NOT_ECHO')
    monkeypatch.setattr(io, 'write_all', fail)
    # No cleanup implementation is authorized; even a failing unlink must not run.
    monkeypatch.setattr(os, 'unlink', lambda *a, **k: pytest.fail('unauthorized cleanup'))
    result = package.create(str(source))
    assert result['code'] == {errno.ENOSPC:'DISK_FULL', errno.EIO:'IO_FAILED', errno.EACCES:'PERMISSION_DENIED'}[fault]
    assert result['cleanup'] == 'PRIVATE_STAGING_RETAINED_ON_FAILURE'
    assert not result['PACKAGE_CREATED'] and not result['TRUST_ANCHOR_VERIFIED']
    assert 'SYNTHETIC_SECRET' not in json.dumps(result)
    assert (managed / 'packages' / ('.stage-'+result['operation_id'])).is_dir()
    assert not list((managed / 'records').iterdir())


def test_fsync_failure_after_copy_retains_staging(offline, monkeypatch):
    source, _, managed = offline
    original_write, original_fsync = io.write_all, os.fsync
    copied = []
    def write(*args): original_write(*args); copied.append(True)
    def fsync(fd):
        if copied: raise OSError(errno.EIO, 'injected fsync')
        return original_fsync(fd)
    monkeypatch.setattr(io, 'write_all', write); monkeypatch.setattr(os, 'fsync', fsync)
    result = package.create(str(source))
    assert result['code'] == 'IO_FAILED' and result['cleanup'] == 'PRIVATE_STAGING_RETAINED_ON_FAILURE'
    assert not result['TRUST_ANCHOR_VERIFIED']
    assert list((managed / 'packages').iterdir())


def test_source_mutation_refused(offline, monkeypatch):
    source, _, _ = offline
    original, changed = io.stream, []
    def stream(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get('target') is not None and not changed:
            (source / 'application/app.py').write_bytes(b'changed during capture')
            changed.append(True)
        return result
    monkeypatch.setattr(io, 'stream', stream)
    result = package.create(str(source))
    assert changed and result['code'] == 'OBJECT_CHANGED' and not result['TRUST_ANCHOR_VERIFIED']


def test_collision_never_overwrites(offline, monkeypatch):
    source, _, managed = offline
    operation = 'a'*32
    monkeypatch.setattr(package.secrets, 'token_hex', lambda n: operation)
    first = package.create(str(source)); assert first['code'] == 'CREATED'
    record = (managed / 'records' / (operation+'.json')).read_bytes()
    second = package.create(str(source))
    assert second['code'] == 'DESTINATION_EXISTS' and not second['TRUST_ANCHOR_VERIFIED']
    assert (managed / 'records' / (operation+'.json')).read_bytes() == record
    assert package.verify(operation)['TRUST_ANCHOR_VERIFIED']


def test_staging_collision_not_owned(offline, monkeypatch):
    source, _, managed = offline
    operation = 'b'*32
    managed.mkdir(mode=0o700)
    (managed / 'packages').mkdir(mode=0o700); (managed / 'records').mkdir(mode=0o700)
    stage = managed / 'packages' / ('.stage-'+operation); stage.mkdir(mode=0o700)
    sentinel = stage / 'sentinel'; sentinel.write_bytes(b'EXTERNAL_OBJECT')
    monkeypatch.setattr(package.secrets, 'token_hex', lambda n: operation)
    result = package.create(str(source))
    assert result['code'] == 'DESTINATION_EXISTS' and result['cleanup'] == 'NOT_CREATED'
    assert sentinel.read_bytes() == b'EXTERNAL_OBJECT'


def test_publication_uncertain_preserved(offline, monkeypatch):
    source, _, managed = offline
    publish = package.publication_function()
    def uncertain(parent, staging, destination):
        publish(parent, staging, destination)
        raise OSError(errno.EIO, 'post-rename failure')
    monkeypatch.setattr(package, 'publication_function', lambda: uncertain)
    result = package.create(str(source))
    assert result['code'] == 'IO_FAILED' and result['publication'] == 'UNCERTAIN_UNTIL_DURABLE_IDENTITY_CHECK'
    assert (managed / 'packages' / result['operation_id']).is_dir()
    assert not result['TRUST_ANCHOR_VERIFIED'] and not list((managed / 'records').iterdir())


def test_no_replace_unavailable_before_staging(offline, monkeypatch):
    source, _, managed = offline
    def unavailable(): raise AuditFault('NO_REPLACE_UNAVAILABLE')
    monkeypatch.setattr(package, 'publication_function', unavailable)
    assert package.create(str(source))['code'] == 'NO_REPLACE_UNAVAILABLE'
    assert not managed.exists()


@pytest.mark.parametrize('limit,code', [('MAX_ENTRIES', 'ENTRY_LIMIT'), ('MAX_FILE_BYTES', 'FILE_BYTE_LIMIT'),
                                     ('MAX_TOTAL_BYTES', 'TOTAL_BYTE_LIMIT'), ('MAX_SECONDS', 'TIME_LIMIT'),
                                     ('MAX_DEPTH', 'DEPTH_LIMIT'), ('MAX_JSON_BYTES', 'JSON_BYTE_LIMIT')])
def test_explicit_resource_limits(offline, monkeypatch, limit, code):
    source, _, _ = offline
    monkeypatch.setattr(schema, limit, 1 if limit != 'MAX_SECONDS' else -1)
    result = package.create(str(source))
    assert result['code'] == code and not result['TRUST_ANCHOR_VERIFIED']


def test_interrupted_staging_is_not_swept(offline, monkeypatch):
    source, _, managed = offline
    def interrupted(*args): raise KeyboardInterrupt
    monkeypatch.setattr(io, 'write_all', interrupted)
    result = package.create(str(source))
    assert result['code'] == 'INTERRUPTED_STAGING_OR_PUBLICATION_UNCERTAIN'
    assert (managed / 'packages' / ('.stage-'+result['operation_id'])).is_dir()
    assert not list((managed / 'records').iterdir())


def test_no_environment_management_override(offline, monkeypatch):
    source, _, managed = offline
    monkeypatch.setenv('CLASH_RECOVERY_ROOT', '/unexpected')
    monkeypatch.setenv('CLASH_RECOVERY_UID', '12345')
    result = package.create(str(source))
    assert result['code'] == 'CREATED' and managed.is_dir()


@pytest.mark.parametrize('change,code', [('device', 'CROSS_FILESYSTEM'), ('owner', 'UNSAFE_OWNERSHIP'),
                                      ('special', 'SPECIAL_FILE_REFUSED')])
def test_stat_security_gates(offline, monkeypatch, change, code):
    source, _, _ = offline
    original = os.stat
    class Changed:
        def __init__(self, info): self.info = info
        def __getattr__(self, name):
            if change == 'device' and name == 'st_dev': return self.info.st_dev+1
            if change == 'owner' and name == 'st_uid': return self.info.st_uid+99
            if change == 'special' and name == 'st_mode': return stat.S_IFCHR | 0o600
            return getattr(self.info, name)
    def altered(name, *args, **kwargs):
        result = original(name, *args, **kwargs)
        return Changed(result) if name == 'app.py' and kwargs.get('dir_fd') is not None else result
    monkeypatch.setattr(os, 'stat', altered)
    assert package.create(str(source))['code'] == code


def test_cli_output_is_bounded_and_secret_free(offline, capsys):
    source, _, _ = offline
    assert package.main(['create', '--source', str(source)]) == 0
    output = capsys.readouterr().out
    assert len(output) < 2048 and 'SYNTHETIC_SECRET' not in output
    result = json.loads(output)
    assert package.main(['verify', '--operation-id', result['operation_id']]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified['TRUST_ANCHOR_VERIFIED'] and verified['RECOVERY_REQUIREMENTS_NOT_EVALUATED']


def test_root_and_managed_permission_boundaries(offline, monkeypatch):
    source, _, managed = offline
    monkeypatch.setattr(io, 'ROOT_UID', os.geteuid()+10)
    assert package.create(str(source))['code'] == 'ROOT_REQUIRED'
    monkeypatch.setattr(io, 'ROOT_UID', os.geteuid())
    result, _, _, _ = created(offline)
    managed.chmod(0o755)
    assert package.verify(result['operation_id'])['code'] == 'UNSAFE_STORED_METADATA'


def test_undeclared_symlink_ancestors_and_group_writes(offline, tmp_path):
    source, _, _ = offline
    linked = tmp_path / 'source-link'; linked.symlink_to(source, target_is_directory=True)
    assert package.create(str(linked))['code'] == 'UNSAFE_PATH'
    (source / 'application/app.py').chmod(0o666)
    assert package.create(str(source))['code'] == 'UNSAFE_SOURCE_MODE'


@pytest.mark.parametrize('operation', ['../escape', 'A'*32, '', '0'*31, '0'*33])
def test_verifier_operation_path_validation(offline, operation):
    assert package.verify(operation)['code'] == 'INVALID_SCHEMA'
