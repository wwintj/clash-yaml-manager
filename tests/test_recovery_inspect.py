"""Read-only Phase C acceptance with real synthetic packages and descriptors."""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from scripts import recovery_inspect as inspect, recovery_io as io, recovery_manifest as schema
from scripts import recovery_package as package
from scripts.backup_audit import fingerprint
from test_recovery_package import offline, created


AUTH = dict(version=1, auth_version=1, instance_id='a'*32,
            password_hash='pbkdf2:sha256:1000000$synthetic$' + 'b'*64)


@pytest.fixture
def scene(offline, tmp_path):
    source, control, managed = offline
    (source / 'state/auth.json').write_bytes(schema.canonical(AUTH))
    result, root, manifest, record = created(offline)
    target = tmp_path / 'target'
    target.mkdir(mode=0o700)
    for name in ('state', 'configuration', 'outputs', 'uploads', 'backups', 'logs', 'bin'):
        (target / name).mkdir(mode=0o700)
    environment = dict(schema_version=1, synthetic=True,
        runtime={k: v for k, v in control['runtime_requirements'].items() if k != 'origin'},
        accounts={role: {k: v for k, v in account.items() if k != 'origin'} for role, account in control['account_roles'].items()},
        install_path=control['installation_binding']['install_path'], current_identity=control['source_identity'],
        units=['clash-yaml-manager.service'], external_python=['/usr/bin/python3'],
        free_space_bytes=10**10, filesystem_metadata='POSIX_ONLY')
    for name, data in {'environment.json': schema.canonical(environment),
        'state/auth.json': schema.canonical(AUTH), 'outputs/kept': b'LIVE_SYNTHETIC_SECRET',
        'configuration/.env': b'SECRET_KEY=SYNTHETIC_SECRET'}.items():
        (target / name).write_bytes(data); (target / name).chmod(0o600)
    return result['operation_id'], root, record, manifest, target, environment, managed


def snapshot(path):
    result = {}
    for p in [path, *path.rglob('*')]:
        info = p.lstat()
        result[str(p.relative_to(path))] = (fingerprint(info),
            os.readlink(p) if p.is_symlink() else hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
    return result


def test_full_package_verification_flags(scene):
    operation, _, _, _, _, _, _ = scene
    result = inspect.verify(operation)
    assert result['code'] == 'VERIFIED'
    assert all(result[flag] for flag in inspect.FLAGS[:4])
    assert not any(result[flag] for flag in inspect.FLAGS[4:])
    assert result['archived_state'] == 'UNKNOWN'
    assert result['capture']['quiet'] == 'OPERATOR_DECLARED_NOT_SYSTEMD_PROVEN'
    assert not result['capture']['atomic_snapshot']
    assert 'NOT_OFF_HOST' in result['trust_scope']


def test_list_status_latest_and_no_automatic_adoption(scene, capsys):
    operation, _, _, manifest, _, _, managed = scene
    orphan = managed / 'packages' / ('e'*32); orphan.mkdir(mode=0o700)
    stage = managed / 'packages' / ('.stage-'+'f'*32); stage.mkdir(mode=0o700)
    listed = inspect.list_backups()
    assert listed['code'] == 'LISTED' and listed['backups'] == [dict(operation_id=operation, verification='NOT_EVALUATED')]
    assert listed['orphan_count'] == listed['incomplete_count'] == 1
    assert not listed['TRUST_ANCHOR_VERIFIED']
    assert inspect.verify('latest')['operation_id'] == operation
    assert inspect.main(['status']) == 0
    assert json.loads(capsys.readouterr().out)['code'] == 'LISTED'
    assert inspect.main(['verify', '--id', operation]) == 0
    assert json.loads(capsys.readouterr().out)['CONTENT_INTEGRITY_VALID']
    assert manifest['retention']['completed_at'] is None


@pytest.mark.parametrize('change,code', [
    ('missing', 'PAYLOAD_CLOSURE'), ('blob', 'CONTENT_DIGEST_MISMATCH'),
    ('forged_record', 'MANIFEST_DIGEST_MISMATCH'), ('identity', 'RECORD_BINDING_MISMATCH'),
    ('canonical', 'NON_CANONICAL_MANIFEST'), ('digest', 'MANIFEST_DIGEST_MISMATCH'),
    ('traversal', 'INVALID_PATH'), ('link_escape', 'LINK_ESCAPE'),
    ('missing_required', 'MISSING_REQUIRED'), ('mode', 'UNSAFE_STORED_METADATA'),
    ('hardlink', 'UNSAFE_STORED_METADATA'), ('actual_link', 'UNSAFE_STORED_METADATA'),
    ('no_anchor', 'PATH_MISSING')])
def test_negative_real_verifier(scene, change, code):
    operation, root, record, manifest, _, _, _ = scene
    blob = root / 'blobs' / next(e['blob'] for e in manifest['entries'] if e['kind'] == 'file')
    if change == 'missing': blob.unlink()
    elif change == 'blob': blob.write_bytes(b'changed')
    elif change == 'mode': blob.chmod(0o644)
    elif change == 'hardlink': os.link(blob, root.parent / 'other-link')
    elif change == 'actual_link': blob.unlink(); blob.symlink_to('/etc/passwd')
    elif change == 'no_anchor': record.unlink()
    elif change in ('identity', 'forged_record'):
        value = schema.parse(record.read_bytes())
        if change == 'forged_record': value['manifest_sha256'] = '0'*64
        else: value['target_identity'] = dict(value['target_identity'], commit='0'*40)
        record.write_bytes(schema.canonical(value))
    else:
        raw = (root / 'manifest.json').read_bytes()
        if change == 'canonical': raw += b'\n'
        else:
            candidate = copy.deepcopy(manifest)
            if change == 'digest': candidate['target_identity']['commit'] = '0'*40
            elif change == 'traversal': candidate['entries'][0]['path'] = '../outside'
            elif change == 'link_escape':
                next(e for e in candidate['entries'] if e['path'] == 'venv/bin/python')['link_target'] = '../../../outside'
            elif change == 'missing_required':
                candidate['entries'] = [e for e in candidate['entries'] if e['path'] != 'state/auth.json']
            raw = schema.canonical(candidate)
        (root / 'manifest.json').write_bytes(raw)
    before = snapshot(root.parent.parent)
    result = inspect.verify(operation)
    assert result['code'] == code, result
    assert not any(result[flag] for flag in inspect.FLAGS)
    assert snapshot(root.parent.parent) == before


def test_dry_run_preserves_every_byte_and_metadata(scene, capsys):
    operation, _, _, _, target, _, managed = scene
    before = snapshot(target), snapshot(managed)
    result = inspect.dry_run(operation, str(target))
    assert result['code'] == 'PLAN_BLOCKED'
    assert all(result[flag] for flag in inspect.FLAGS[:4])
    assert not any(result[flag] for flag in inspect.FLAGS[4:])
    assert result['state_policy'] == 'PRESERVE_LIVE_STATE'
    assert result['state_compatibility'] == 'UNKNOWN'
    assert not result['executable'] and not result['apply_implemented']
    assert 'state' in result['preserve_live_directories']
    assert 'STATE' not in result['restore_material_classes']
    assert result['prerequisites']['python_abi'] == 'MATCH'
    assert 'ABI_AND_DEPENDENCIES_DECLARED_NOT_PROBED' in result['blockers']
    assert 'EXTENDED_METADATA_NOT_CAPTURED' in result['blockers']
    assert inspect.main(['restore', 'latest', '--dry-run', '--target-fixture', str(target)]) == 1
    text = capsys.readouterr().out + json.dumps(result)
    assert len(text) < 12000
    for secret in ('SYNTHETIC_SECRET', AUTH['password_hash'], 'SECRET_KEY', str(target)):
        assert secret not in text
    assert (snapshot(target), snapshot(managed)) == before


@pytest.mark.parametrize('field,value,check,expected', [
    ('python_abi', 'cpython-313', 'python_abi', 'MISMATCH'),
    ('python_abi', None, 'python_abi', 'UNKNOWN'),
    ('python_version', '3.13', 'python_version', 'MISMATCH'),
    ('os', 'Darwin', 'os', 'MISMATCH'), ('architecture', 'arm64', 'architecture', 'MISMATCH'),
    ('system_libraries', [], 'system_libraries', 'MISSING'),
    ('install_path', '/another/install', 'installation_path', 'MISMATCH'),
    ('units', [], 'units', 'MISSING'), ('external_python', [], 'external_python', 'MISSING'),
    ('free_space_bytes', 0, 'disk_space', 'INSUFFICIENT'),
    ('filesystem_metadata', 'EXTENDED_PRESENT', 'filesystem_metadata', 'UNSUPPORTED')])
def test_readiness_mismatches(scene, field, value, check, expected):
    operation, _, _, _, target, environment, _ = scene
    if field in environment['runtime']: environment['runtime'][field] = value
    else: environment[field] = value
    (target / 'environment.json').write_bytes(schema.canonical(environment))
    result = inspect.dry_run(operation, str(target))
    assert result['code'] == 'PLAN_BLOCKED' and result['prerequisites'][check] == expected
    assert not result['RUNTIME_REQUIREMENTS_READY'] and not result['RESTORE_PLAN_READY']


@pytest.mark.parametrize('role,field', [('root', 'uid'), ('root', 'gid'), ('service', 'uid'), ('service', 'gid')])
def test_account_identity_not_numeric_guess(scene, role, field):
    operation, _, _, _, target, environment, _ = scene
    environment['accounts'][role][field] += 1
    (target / 'environment.json').write_bytes(schema.canonical(environment))
    result = inspect.dry_run(operation, str(target))
    assert result['prerequisites']['accounts'] == 'MISMATCH' and not result['RESTORE_PLAN_READY']


@pytest.mark.parametrize('location', ['package', 'target'])
def test_invalid_state_schema_is_not_compatibility(scene, location):
    operation, root, _, manifest, target, _, _ = scene
    if location == 'target':
        (target / 'state/auth.json').write_bytes(b'{"version":99,"secret":"SYNTHETIC_SECRET"}')
    else:
        # Digest-correct but semantically invalid archived state; publish independently
        # through the Writer from an invalid synthetic fixture, not by changing anchors.
        source = root.parent.parent.parent / 'offline'
        (source / 'state/auth.json').write_bytes(b'{"version":99}')
        result = package.create(str(source)); assert result['code'] == 'CREATED'
        operation = result['operation_id']
    result = inspect.dry_run(operation, str(target))
    assert result['prerequisites']['state'] == 'INVALID_STATE_SCHEMA'
    assert not result['RESTORE_PLAN_READY']


def test_package_mutation_after_content_scan_refused(scene, monkeypatch):
    operation, root, _, _, _, _, _ = scene
    original = inspect.package_state
    def mutated(*args):
        result = original(*args)
        (root / 'blobs' / next((root / 'blobs').iterdir()).name).write_bytes(b'changed')
        return result
    monkeypatch.setattr(inspect, 'package_state', mutated)
    result = inspect.verify(operation)
    assert result['code'] == 'CONTENT_DIGEST_MISMATCH' and not result['TRUST_ANCHOR_VERIFIED']


def test_cross_filesystem_refused(scene, monkeypatch):
    operation, _, _, _, _, _, _ = scene
    original = os.stat
    class OtherDevice:
        def __init__(self, info): self.info = info
        def __getattr__(self, key): return self.info.st_dev + 1 if key == 'st_dev' else getattr(self.info, key)
    def changed(name, *args, **kwargs):
        info = original(name, *args, **kwargs)
        return OtherDevice(info) if name == 'manifest.json' and kwargs.get('dir_fd') else info
    monkeypatch.setattr(os, 'stat', changed)
    assert inspect.verify(operation)['code'] == 'CROSS_FILESYSTEM'


def test_target_mutation_during_observation_refused(scene, monkeypatch):
    operation, _, _, _, target, _, _ = scene
    original = io.stream
    changed = []
    def stream(parent, name, *args, **kwargs):
        result = original(parent, name, *args, **kwargs)
        if name == 'environment.json' and not changed:
            (target / 'outputs/kept').write_bytes(b'changed during target observation')
            changed.append(True)
        return result
    monkeypatch.setattr(io, 'stream', stream)
    result = inspect.dry_run(operation, str(target))
    assert changed and result['code'] == 'OBJECT_CHANGED' and not result['RESTORE_PLAN_READY']


def test_no_program_execution_or_package_import(scene, monkeypatch):
    operation, _, _, _, target, _, _ = scene
    def refuse(*args, **kwargs): pytest.fail('inspection must not execute a program')
    monkeypatch.setattr(os, 'system', refuse)
    monkeypatch.setattr(subprocess, 'run', refuse)
    monkeypatch.setattr(subprocess, 'Popen', refuse)
    assert inspect.verify(operation)['code'] == 'VERIFIED'
    assert inspect.dry_run(operation, str(target))['code'] == 'PLAN_BLOCKED'
    assert not any(name.startswith('application.') for name in sys.modules)


@pytest.mark.parametrize('field,value', [('units', [{}]), ('free_space_bytes', True),
                                       ('runtime', {}), ('unexpected', 'SYNTHETIC_SECRET')])
def test_target_malformed_values_fail_closed(scene, field, value):
    operation, _, _, _, target, environment, _ = scene
    environment[field] = value
    (target / 'environment.json').write_bytes(schema.canonical(environment))
    result = inspect.dry_run(operation, str(target))
    assert result['code'] == 'INVALID_SCHEMA' and not result['RESTORE_PLAN_READY']
    assert 'SYNTHETIC_SECRET' not in json.dumps(result)


@pytest.mark.parametrize('change,code', [('symlink', 'UNSAFE_STORED_METADATA'), ('permissions', 'UNSAFE_STORED_METADATA'),
                                      ('unknown', 'UNEXPECTED_TARGET_OBJECT'), ('noncanonical', 'NON_CANONICAL_MANIFEST'),
                                      ('not_synthetic', 'INVALID_TARGET_SCHEMA')])
def test_target_admission(scene, change, code):
    operation, _, _, _, target, environment, _ = scene
    if change == 'symlink': (target / 'outputs/evil').symlink_to('/etc/passwd')
    if change == 'permissions': target.chmod(0o755)
    if change == 'unknown': (target / 'unexpected').mkdir(mode=0o700)
    if change == 'noncanonical': (target / 'environment.json').write_bytes(schema.canonical(environment) + b'\n')
    if change == 'not_synthetic':
        environment['synthetic'] = False; (target / 'environment.json').write_bytes(schema.canonical(environment))
    assert inspect.dry_run(operation, str(target))['code'] == code


@pytest.mark.parametrize('value', ['/opt/clash-yaml-manager', '/root/fixture', '/var/lib/example'])
def test_no_live_target_access(scene, value, monkeypatch):
    def forbid(*args): pytest.fail('must not open prohibited target')
    monkeypatch.setattr(io, 'absolute_directory', forbid)
    with pytest.raises(inspect.AuditFault) as error: inspect.read_target(value, io.Budget())
    assert error.value.code == 'LIVE_TARGET_REFUSED'


def test_stdlib_cli_without_app_or_venv(tmp_path):
    # -S removes site packages; trusted tools are imported, never backed-up code.
    script = 'import sys; from scripts import recovery_inspect as tool; assert not any(n in sys.modules for n in ("flask", "gunicorn", "app", "core.security")); raise SystemExit(tool.main(["--help"]))'
    result = subprocess.run([sys.executable, '-B', '-S', '-c', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '{list,status,verify,restore}' in result.stdout


def test_no_apply_or_management_override_cli(scene):
    for args in (['apply'], ['restore', 'latest'], ['verify', '--root', '/tmp'], ['restore', 'latest', '--apply']):
        with pytest.raises(SystemExit) as failure: inspect.main(args)
        assert failure.value.code == 2


def test_entry_and_time_limits(scene, monkeypatch):
    operation, _, _, _, _, _, _ = scene
    monkeypatch.setattr(inspect, 'MAX_RECORDS', 0)
    assert inspect.list_backups()['code'] == 'ENTRY_LIMIT'
    monkeypatch.setattr(schema, 'MAX_SECONDS', -1)
    assert inspect.verify(operation)['code'] == 'TIME_LIMIT'
