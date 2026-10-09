"""Synthetic sidecar integration, retained legacy data and conservative gates."""
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

import pytest

from conftest import ROOT
from scripts import backup_sidecar_update as adapter
from scripts import backup_catalog as catalog, backup_collect as collector
from scripts import backup_create as writer, backup_verify as verifier
from test_backup_collect import offline, frozen, json_file, SECRET
from test_deployment import deployment, executable

START = '874ab75b78d50a4941d5d0a2abb0ceba38ca9f13'


def inactive(unit):
    values = dict(LoadState='loaded', ActiveState='inactive', SubState='dead', Job='')
    if unit.endswith('.service'):
        values.update(MainPID='0', ControlPID='0', ControlGroup='', Slice='system.slice',
                      KillMode='control-group', Result='success')
    return '\n'.join(k + '=' + v for k, v in values.items()) + '\n'


@pytest.fixture
def context(offline, isolated_guard, monkeypatch, tmp_path):
    legacy, _ = offline
    (legacy / collector.SOURCE_CONTROL).unlink()  # Adapter must author it itself.
    cg = tmp_path / 'cgroup'; cg.mkdir(mode=0o700)
    (cg / 'system.slice').mkdir(mode=0o700)
    (cg / 'cgroup.controllers').write_text('cpu memory pids\n')
    side = tmp_path / 'sidecars'
    monkeypatch.setattr(adapter, 'EXECUTOR_UID', os.geteuid())
    monkeypatch.setattr(adapter, 'EXECUTOR_GID', os.getegid())
    monkeypatch.setattr(adapter, 'SUPPORTED_QUIET_PLATFORM', True)
    monkeypatch.setattr(adapter, 'SIDECAR_ROOT', str(side))
    monkeypatch.setattr(adapter, 'CGROUP_ROOT', str(cg))
    monkeypatch.delenv('CLASH_DEPLOY_METADATA', raising=False)
    commands = []
    def command(args, maximum=8192):
        commands.append(args)
        if args[:2] == ['systemctl', 'show']:
            return inactive(args[2])
        if args[0] in ('systemctl', 'ps'):
            return ''
        raise AssertionError('Unexpected synthetic command')
    monkeypatch.setattr(adapter, 'bounded_command', command)
    with isolated_guard.held_deployment_guard() as held:
        monkeypatch.setenv('CLASH_DEPLOYMENT_GUARD_FDS', f'{held.directory}:{held.lock}')
        yield dict(legacy=legacy, installed=legacy, source=legacy, side=side, cg=cg,
                   held=held, commands=commands)


def run(context, mode='STRICT', external='YES'):
    return adapter.run(str(context['legacy']), str(context['installed']), mode, external, str(context['source']))


def snapshot(context, report):
    return context['side'] / 'operations' / report['operation_id'] / 'snapshot'


def assert_blocked(report, code):
    assert report['UPGRADE_STATUS'] == 'BLOCKED', report
    assert code in report['validation_codes'], report
    assert report['restore_proven'] is False
    assert SECRET not in json.dumps(report)


def test_real_public_pipeline_preserves_legacy_and_private_scope(context):
    legacy = context['legacy']; before = frozen(legacy)
    (legacy / 'venv').mkdir(mode=0o755)
    (legacy / 'venv/python').symlink_to('/never-followed')
    before = frozen(legacy)
    result = run(context)
    assert result['UPGRADE_STATUS'] == 'PERMITTED_NOT_COMPLETED', result
    assert result['SIDECAR_STATUS'] == result['CATALOG_STATUS'] == 'TRUSTED_SCOPE_VERIFIED'
    assert frozen(legacy) == before
    snap = snapshot(context, result)
    assert verifier.verify(snap, result['manifest_sha256'])['verification_status'] == 'TRUSTED_SCOPE_VERIFIED'
    record = catalog.load_record((context['side'] / 'catalog' / (result['snapshot_id'] + '.json')).read_bytes())
    assert record['manifest_sha256'] == result['manifest_sha256']
    assert record['operation_id'] == result['operation_id']
    assert record['operator_claims']['target_identity']['channel'] == 'local'
    assert record['snapshot_binding']['inode'] == snap.stat().st_ino
    assert (snap / '.env').read_bytes() == (legacy / '.env').read_bytes()
    assert not (snap / 'venv').exists()
    capture = json.loads((snap / adapter.CAPTURE_FILE).read_bytes())
    assert capture['metadata_origin'] == 'LEGACY_BACKUP_NOT_LIVE_FILESYSTEM'
    assert capture['source_ownership_ledger_origin'] == 'ADAPTER_OFFLINE_SOURCE'
    assert capture['target_identity_is'] == 'PRE_MIGRATION_OPERATOR_CLAIM'
    assert capture['atomic_snapshot'] is False
    scope = json.loads((snap / collector.SCOPE_FILE).read_bytes())
    assert 'INSTALLATION.json' in scope['missing_optional']
    assert scope['writer_full_tree_means'] == 'COLLECTED_REPRESENTATION_ONLY'
    for path in [snap, *snap.rglob('*')]:
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)
    assert SECRET not in json.dumps(result) and str(legacy) not in json.dumps(result)
    with pytest.raises(adapter.guard.DeploymentGuardError):
        adapter.guard.guard_acquire()  # Adapter closed only duplicated references.


@pytest.mark.parametrize('mode', ['OPTIONAL', 'STRICT'])
@pytest.mark.parametrize('fault', ['missing-required', 'unknown-state', 'unknown-envelope'])
def test_ordinary_refusal_never_claims_verified(context, mode, fault):
    root = context['legacy']
    if fault == 'missing-required': (root / 'defaults/default.yaml').unlink()
    if fault == 'unknown-state': json_file(root / 'state/unknown.json', {'version': 1})
    if fault == 'unknown-envelope': json_file(root / 'state/auth.json', {'version': 999})
    before = frozen(root)
    result = run(context, mode)
    assert result['UPGRADE_STATUS'] == ('BLOCKED' if mode == 'STRICT' else 'PERMITTED_WITH_SIDECAR_FAILURE_NOT_COMPLETED')
    assert result['SIDECAR_STATUS'] == 'FAILED' and result['CATALOG_STATUS'] == 'NOT_RUN'
    assert frozen(root) == before and not snapshot(context, result).exists()


@pytest.mark.parametrize('mode', ['OPTIONAL', 'STRICT'])
@pytest.mark.parametrize('fault', ['active', 'failed', 'missing', 'unknown', 'check-error', 'job', 'pid', 'cgroup', 'manual', 'background'])
def test_quiet_gate_is_global_and_records_refusal(context, monkeypatch, mode, fault):
    original = adapter.bounded_command
    def command(args, maximum=8192):
        if args[:2] == ['systemctl', 'show'] and args[2] == adapter.UNITS[0]:
            text = inactive(args[2])
            if fault == 'active': return text.replace('inactive', 'active')
            if fault == 'failed': return text.replace('inactive', 'failed')
            if fault == 'missing': return text.replace('loaded', 'not-found')
            if fault == 'unknown': return text.replace('loaded', 'error')
            if fault == 'check-error': raise adapter.AuditFault('CHECK_ERROR')
            if fault == 'job': return text.replace('Job=\n', 'Job=7\n')
            if fault == 'pid': return text.replace('MainPID=0', 'MainPID=12')
        if args[0] == 'ps' and fault == 'background': return '123 1 /usr/bin/python -m core.auto_health --once\n'
        return original(args, maximum)
    monkeypatch.setattr(adapter, 'bounded_command', command)
    if fault == 'cgroup':
        group = context['cg'] / 'system.slice' / adapter.UNITS[0]
        group.mkdir(mode=0o700); (group / 'cgroup.events').write_text('populated 1\n')
    result = run(context, mode, 'NO' if fault == 'manual' else 'YES')
    assert result['UPGRADE_STATUS'] == 'BLOCKED'
    assert not context['side'].exists()  # No capture or fake quiet declaration.
    assert result['quiet_evidence'] is not None
    if fault in ('active', 'failed', 'missing', 'unknown'):
        assert result['quiet_evidence']['units'][adapter.UNITS[0]]['classification'] == {'active':'ACTIVE','failed':'FAILED','missing':'MISSING','unknown':'UNKNOWN'}[fault]


@pytest.mark.parametrize('mode', ['OPTIONAL', 'STRICT'])
@pytest.mark.parametrize('fault', ['headroom', 'enospc', 'writer-read-failed', 'unsafe-owner', 'source-mutation'])
def test_global_failures_never_optional(context, monkeypatch, mode, fault):
    if fault == 'headroom':
        monkeypatch.setattr(adapter, 'headroom', lambda *args: adapter.require(False, 'HEADROOM_INSUFFICIENT'))
        code = 'HEADROOM_INSUFFICIENT'
    elif fault == 'enospc':
        def fail(*args, **kwargs): raise OSError(errno.ENOSPC, 'synthetic secret')
        monkeypatch.setattr(adapter, 'private_child', fail); code = 'DISK_FULL'
    elif fault == 'writer-read-failed':
        def fail(*args):
            result = writer.empty_report(); result['validation_codes'] = ['READ_FAILED']; return result
        monkeypatch.setattr(writer, 'create', fail); code = 'READ_FAILED'
    elif fault == 'unsafe-owner':
        monkeypatch.setattr(adapter, 'EXECUTOR_GID', os.getegid() + 1000); code = 'ROOT_REQUIRED'
    else:
        original = adapter.LegacySubset.copy
        def copy(engine, root, output, selected):
            original(engine, root, output, selected)
            (context['legacy'] / 'VERSION').write_bytes(b'1.6.0\n')
        monkeypatch.setattr(adapter.LegacySubset, 'copy', copy); code = 'BACKUP_CHANGED'
    assert_blocked(run(context, mode), code)


@pytest.mark.parametrize('mode', ['OPTIONAL', 'STRICT'])
@pytest.mark.parametrize('stage_name,code,published', [
    ('writer', 'NO_REPLACE_UNAVAILABLE', False), ('writer', 'UNSUPPORTED_PLATFORM', False),
    ('writer', 'VERIFICATION_FAILED', False),
    ('writer', 'PUBLISHED_RESULT_NOT_CONFIRMED', True), ('writer', 'CLEANUP_FAILED', False),
    ('catalog_register', 'CATALOG_FULL', False), ('catalog_register', 'VERIFICATION_FAILED', False),
    ('catalog_register', 'PUBLISHED_RESULT_NOT_CONFIRMED', True),
    ('catalog_verify', 'MANIFEST_DIGEST_MISMATCH', True)])
def test_pipeline_failure_matrix_preserves_published_objects(context, monkeypatch, mode, stage_name, code, published):
    original_writer = writer.create; original_catalog = catalog.execute
    def fail_writer(*args):
        result = original_writer(*args) if published else writer.empty_report()
        result.update(creation_status='FAILED', MANIFEST_SHA256=None,
                      validation_codes=[code], cleanup_status='FAILED' if code == 'CLEANUP_FAILED' else 'NOT_ATTEMPTED_PUBLISHED' if published else 'CLEANED')
        return result
    def fail_catalog(action, *args, **kwargs):
        if ('catalog_' + action) == stage_name:
            result = original_catalog(action, *args, **kwargs) if published else catalog.report_empty(action)
            result.update(registration_status='NOT_REGISTERED', verification_status='NOT_VERIFIED', validation_codes=[code])
            return result
        return original_catalog(action, *args, **kwargs)
    if stage_name == 'writer': monkeypatch.setattr(writer, 'create', fail_writer)
    else: monkeypatch.setattr(catalog, 'execute', fail_catalog)
    before = frozen(context['legacy'])
    result = run(context, mode)
    assert result['UPGRADE_STATUS'] == ('BLOCKED' if mode == 'STRICT' else 'PERMITTED_WITH_SIDECAR_FAILURE_NOT_COMPLETED'), result
    assert code in result['validation_codes']
    assert frozen(context['legacy']) == before
    assert snapshot(context, result).exists() is (stage_name != 'writer' or published)
    if published and stage_name == 'catalog_register':
        assert len(list((context['side'] / 'catalog').glob('*.json'))) == 1
    assert result['SIDECAR_STATUS'] != 'TRUSTED_SCOPE_VERIFIED'


@pytest.mark.parametrize('mode', ['OPTIONAL', 'STRICT'])
def test_real_verifier_rejects_manifest_changed_after_writer_handoff(context, monkeypatch, mode):
    create = writer.create
    injection = {}
    def tamper(*args):
        result = create(*args)
        assert result['creation_status'] == 'CREATED'
        manifest = Path(args[1]) / writer.protocol.MANIFEST_NAME
        original = manifest.read_bytes()
        trusted_digest = result['MANIFEST_SHA256']
        assert hashlib.sha256(original).hexdigest() == trusted_digest
        value = writer.protocol.load_manifest(original)
        assert value['snapshot_type'] == 'UPDATER_SNAPSHOT'
        value['snapshot_type'] = 'UI_OVERLAY_BACKUP'
        rewritten = writer.protocol.canonical_bytes(value)
        assert writer.protocol.load_manifest(rewritten) == value
        assert rewritten != original and hashlib.sha256(rewritten).hexdigest() != trusted_digest
        manifest.write_bytes(rewritten)
        injection.update(snapshot=Path(args[1]), bytes=rewritten, digest=trusted_digest,
                         stored=frozen(Path(args[1])))
        assert result['MANIFEST_SHA256'] == trusted_digest  # Never replace Writer handoff.
        return result
    monkeypatch.setattr(writer, 'create', tamper)
    result = run(context, mode)
    assert 'MANIFEST_DIGEST_MISMATCH' in result['validation_codes']
    assert 'CANONICAL_SERIALIZATION_MATCH' in result['validation_codes']
    assert 'NON_CANONICAL_MANIFEST' not in result['validation_codes']
    assert result['UPGRADE_STATUS'] == ('BLOCKED' if mode == 'STRICT' else 'PERMITTED_WITH_SIDECAR_FAILURE_NOT_COMPLETED')
    assert result['CATALOG_STATUS'] == 'NOT_RUN'
    assert result['SIDECAR_STATUS'] == 'FAILED'
    assert snapshot(context, result).exists()
    assert not list((context['side'] / 'catalog').glob('*.json'))
    assert result['manifest_sha256'] == injection['digest']
    assert frozen(injection['snapshot']) == injection['stored']
    refused = verifier.verify(injection['snapshot'], injection['digest'])
    assert refused['verification_status'] == 'NOT_VERIFIED'
    assert refused['manifest_digest_match'] is refused['trust_anchor_verified'] is False
    assert 'MANIFEST_DIGEST_MISMATCH' in refused['validation_codes']


@pytest.mark.parametrize('fault', ['symlink', 'hardlink', 'fifo', 'unsafe-mode', 'untrusted-declaration'])
def test_offline_source_refusals_do_not_repair_or_delete(context, fault):
    root = context['legacy']
    target = root / 'state/auth.json'
    if fault == 'symlink':
        outside = root.parent / 'original'
        target.rename(outside); target.symlink_to(outside)
    elif fault == 'hardlink': os.link(target, root / 'linked')
    elif fault == 'fifo': target.unlink(); os.mkfifo(target, 0o600)
    elif fault == 'unsafe-mode': target.chmod(0o644)
    else: json_file(root / collector.SOURCE_CONTROL, {'writers_quiet': True})
    info = target.lstat()
    result = run(context)
    assert result['UPGRADE_STATUS'] == 'BLOCKED'
    assert verifier.fingerprint(target.lstat()) == verifier.fingerprint(info)
    assert not snapshot(context, result).exists()


def without_hook(text):
    return re.sub(r'(?m)^\s*# BEGIN VERIFIED SIDECAR[^\n]*\n.*?^\s*# END VERIFIED SIDECAR[^\n]*\n', '', text, flags=re.S)


def test_exact_start_off_body_and_hook_position():
    baseline = subprocess.check_output(['git', 'show', START + ':update.sh'], cwd=ROOT).decode()
    current = (ROOT / 'update.sh').read_text()
    assert without_hook(current) == baseline
    assert current.index('backup_private_state "${INSTALL_DIR}/state"') < current.index('# BEGIN VERIFIED SIDECAR HOOK') < current.index('-m core.migrate')
    assert 'SIDECAR_ROOT' not in baseline


@pytest.mark.parametrize('unit', adapter.UNITS)
def test_each_missing_unit_refuses_and_no_scheduler_mutations(context, monkeypatch, unit):
    original = adapter.bounded_command
    def command(args, maximum=8192):
        if args[:3] == ['systemctl', 'show', unit]:
            return inactive(unit).replace('loaded', 'not-found')
        return original(args, maximum)
    monkeypatch.setattr(adapter, 'bounded_command', command)
    assert_blocked(run(context, 'OPTIONAL'), 'QUIET_GATE_REFUSED')
    assert all(c[1] in ('show', 'list-jobs') for c in context['commands'] if c[0] == 'systemctl')


@pytest.mark.parametrize('fault', ['permission', 'copy', 'fsync', 'collision', 'interrupted', 'file-budget', 'time-budget'])
def test_adapter_failure_boundaries_preserve_source(context, monkeypatch, fault):
    source = context['legacy']; before = frozen(source)
    if fault == 'permission':
        def fail(*args, **kwargs): raise PermissionError(errno.EACCES, 'synthetic')
        monkeypatch.setattr(adapter.LegacySubset, 'inventory', fail)
    elif fault == 'copy':
        def fail(*args, **kwargs): raise OSError(errno.EIO, 'synthetic')
        monkeypatch.setattr(adapter.LegacySubset, 'copy', fail)
    elif fault == 'fsync':
        def fail(*args): raise OSError(errno.EIO, 'synthetic')
        monkeypatch.setattr(os, 'fsync', fail)
    elif fault == 'collision':
        root=context['side'];(root/'operations'/('a'*32)).mkdir(parents=True,mode=0o700)
        root.chmod(0o700);(root/'operations').chmod(0o700)
        (root/'operations'/('a'*32)/'foreign').write_bytes(b'leave alone')
        monkeypatch.setattr(adapter.secrets, 'token_hex', lambda *args:'a'*32)
    elif fault == 'interrupted':
        def fail(*args, **kwargs): raise KeyboardInterrupt
        monkeypatch.setattr(adapter.LegacySubset, 'copy', fail)
    elif fault == 'file-budget':
        (source/'state/geoip').mkdir(mode=0o700)
        (source/'state/geoip/active.mmdb').write_bytes(b'x'*(17*1024*1024))
        (source/'state/geoip/active.mmdb').chmod(0o600)
        before=frozen(source)
    else:
        monkeypatch.setattr(adapter.LegacySubset, 'tick', lambda *args: adapter.require(False, 'TIME_LIMIT'))
    result=run(context)
    assert result['UPGRADE_STATUS']=='BLOCKED' and result['SIDECAR_STATUS']!='TRUSTED_SCOPE_VERIFIED'
    assert frozen(source)==before
    if fault=='collision':assert (context['side']/'operations'/('a'*32)/'foreign').read_bytes()==b'leave alone'


@pytest.mark.parametrize('failure', ['0', '1'])
def test_off_end_to_end_exact_start_legacy_bytes_modes_ownership_and_events(tmp_path, failure):
    from core.security import AuthStore
    baseline = subprocess.check_output(['git', 'show', START + ':update.sh'], cwd=ROOT).decode()
    instances = []
    for name in ('baseline', 'candidate'):
        parent = tmp_path / name; parent.mkdir(mode=0o700)
        fixture = deployment.__wrapped__(parent)
        fixture[4]['TEST_PIP_FAIL'] = failure
        fixture[4].pop('CLASH_BACKUP_SIDECAR_MODE', None)
        instances.append(fixture)
    auth = AuthStore(instances[0][0] / 'state'); auth.initialize({'APP_PASSWORD':'test'})
    shutil.copytree(instances[0][0] / 'state', instances[1][0] / 'state')
    reports = []
    for data, script in zip(instances, (baseline, None)):
        installed, source, service, events, env, execute = data
        (installed / '.env').write_text('APP_PORT=8899\nSECRET_KEY=old-key\n')
        outcome = execute(script_text=script)
        backup = next(installed.parent.glob('upgrade-backup-*'))
        def normalize(raw):
            return re.sub(rb'\.health-units\.[A-Za-z0-9]+', b'.health-units.STAGE',
                          raw.replace(str(backup).encode(), b'BACKUP').replace(str(installed.parent).encode(), b'FIXTURE'))
        tree = {str(p.relative_to(backup)):(normalize(p.read_bytes()) if p.is_file() else None,
                stat.S_IMODE(p.stat().st_mode),p.stat().st_uid,p.stat().st_gid)
                for p in [backup, *backup.rglob('*')]}
        reports.append((outcome.returncode, normalize(events.read_bytes()), tree, normalize(service.read_bytes()), (installed / '.env').read_bytes()))
        assert 'SIDECAR_STATUS' not in outcome.stdout + outcome.stderr
        assert not list(installed.parent.glob('sidecars*'))
    assert reports[0] == reports[1]
