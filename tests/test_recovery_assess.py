"""D2 data-only synthetic assessment: real Writer, Record, Verifier and IO.

Hooks run only in this test process; no production provider/ownership overrides.
"""
import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest

from scripts import recovery_assess as assess, recovery_assess_data as data
from scripts import recovery_assess_evidence as evidence
from scripts import recovery_inspect as inspect, recovery_io as io, recovery_manifest as schema
from scripts import recovery_package as package
from scripts.backup_audit import AuditFault
from test_recovery_package import offline, created
from test_recovery_inspect import AUTH, scene, snapshot

CFG = b'home = /usr/bin\nversion = 3.12.0\ninclude-system-site-packages = false\nexecutable = /usr/bin/python3\n'
WHEEL = b'Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: cp312-cp312-manylinux_2_17_x86_64\n'


@pytest.fixture
def prepared(offline, tmp_path):
    (offline[0] / 'venv/pyvenv.cfg').write_bytes(CFG)
    return scene.__wrapped__(offline, tmp_path)


def write(root, name, value):
    path = root / name
    parent = root
    for component in Path(name).parts[:-1]:
        parent /= component
        parent.mkdir(exist_ok=True, mode=0o700)
    path.write_bytes(value if type(value) is bytes else schema.canonical(value))
    path.chmod(0o600)


def recreate(offline, prepared):
    result, root, manifest, record = created(offline)
    return (result['operation_id'], root, record, manifest, *prepared[4:])


def run(prepared):
    return assess.assess(prepared[0], str(prepared[4]))


def refused(result, code, stage):
    assert result['code'] == code, result
    assert stage in result['phases'], result
    assert not any(result[flag] for flag in inspect.FLAGS)
    assert not result['ASSESSMENT_SUPPORTED'] and not result['RESTORE_APPLY_IMPLEMENTED']
    assert result['binding'] is None


def test_completed_partial_assessment_preserves_all_data_and_false_ready(prepared):
    before = snapshot(prepared[4]), snapshot(prepared[6])
    result = run(prepared)
    assert result['code'] == 'ASSESSMENT_BLOCKED', result
    assert all(result[flag] for flag in inspect.FLAGS[:4])
    assert not any(result[flag] for flag in inspect.FLAGS[4:])
    assert not result['ASSESSMENT_SUPPORTED'] and not result['RESTORE_APPLY_IMPLEMENTED']
    assert result['runtime_compatibility'] == result['state_compatibility'] == 'PARTIAL'
    assert result['phases'][-1] == 'EXIT_REVALIDATION_COMPLETED'
    assert result['tool']['baseline_commit'] == evidence.BASELINE
    assert len(result['tool']['source_sha256']) == 64
    assert result['binding']['manifest_sha256'] == json.loads(prepared[2].read_bytes())['manifest_sha256']
    assert len(result['binding']['target_evidence_sha256']) == 64
    assert 'SAME_HOST_BINDING_NOT_PROVEN' in result['blockers']
    assert 'EXTENDED_METADATA_NOT_CAPTURED' in result['blockers']
    assert 'EXACT_FILESYSTEM_RESTORE_UNSUPPORTED' in result['blockers']
    assert 'EXACT_TRUSTED_APPLICATION_IDENTITY_NOT_PROVEN' in result['blockers']
    assert result['policy']['execution_authorized'] is False
    assert 'PRESERVE_LIVE_RUNTIME' in result['policy']['restrictions']
    assert inspect.dry_run(prepared[0], str(prepared[4]))['restore_material_classes'] == [
        'APPLICATION', 'VENV', 'CONFIGURATION', 'DEFAULT', 'UNITS']
    assert (snapshot(prepared[4]), snapshot(prepared[6])) == before
    rendered = assess.render(result).decode()
    for secret in ('SYNTHETIC_SECRET', AUTH['password_hash'], str(prepared[4]), 'SECRET_KEY'):
        assert secret not in rendered


@pytest.mark.parametrize('key,value,code', [
    ('os', 'Darwin', 'RUNTIME_IDENTITY_MISMATCH'),
    ('architecture', 'arm64', 'RUNTIME_IDENTITY_MISMATCH'),
    ('python_version', '3.13', 'RUNTIME_IDENTITY_MISMATCH'),
    ('python_abi', 'cpython-313', 'PYTHON_ABI_MISMATCH')])
def test_runtime_identity_rejected_at_runtime_stage(prepared, key, value, code):
    prepared[5]['runtime'][key] = value
    write(prepared[4], 'environment.json', prepared[5])
    refused(run(prepared), code, 'RUNTIME_ANALYSIS_STARTED')


@pytest.mark.parametrize('change,code', [
    ('prefix', 'INSTALL_PREFIX_MISMATCH'), ('version', 'CROSS_VERSION_NOT_PROVEN'),
    ('links', 'BROKEN_EXTERNAL_LINK')])
def test_target_binding_and_external_links(prepared, change, code):
    env = prepared[5]
    if change == 'prefix': env['install_path'] = '/another/install'
    elif change == 'version': env['current_identity'].update(version='1.7.0', tag='v1.7.0')
    else: env['external_python'] = []
    write(prepared[4], 'environment.json', env)
    refused(run(prepared), code, 'TARGET_VALIDATED')


@pytest.mark.parametrize('raw,code', [
    (CFG + b'home = /usr/bin\n', 'INVALID_VENV_CONFIG'),
    (b'home = /usr/bin\n', 'INVALID_VENV_CONFIG'),
    (CFG.replace(b'false', b'true'), 'SYSTEM_SITE_PACKAGES_UNSUPPORTED'),
    (CFG.replace(b'/usr/bin', b'/elsewhere'), 'VENV_PREFIX_MISMATCH'),
    (CFG.replace(b'3.12.0', b'3.13.0'), 'PYTHON_VERSION_MISMATCH'),
    (CFG + b'unknown = yes\n', 'INVALID_VENV_CONFIG'),
    (b'x' * (data.MAX_TEXT + 1), 'ANALYSIS_BYTE_LIMIT'),
    (b'\xff', 'INVALID_TEXT')])
def test_bounded_cfg_data_rejected_after_real_package_verification(offline, prepared, raw, code):
    write(offline[0], 'venv/pyvenv.cfg', raw)
    candidate = recreate(offline, prepared)
    refused(run(candidate), code, 'RUNTIME_ANALYSIS_STARTED')


def elf(machine=62):
    raw = bytearray(64)
    raw[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHI', raw, 16, 3, machine, 1)
    struct.pack_into('<H', raw, 52, 64)
    return bytes(raw)


@pytest.mark.parametrize('raw,code', [(elf(183), 'ELF_ARCHITECTURE_MISMATCH'),
                                     (b'invalid', 'INVALID_ELF_HEADER')])
def test_matching_wheel_does_not_hide_bad_native_binary(offline, prepared, raw, code):
    write(offline[0], 'venv/lib/demo.dist-info/WHEEL', WHEEL)
    write(offline[0], 'venv/lib/demo.so', raw)
    refused(run(recreate(offline, prepared)), code, 'RUNTIME_ANALYSIS_STARTED')


@pytest.mark.parametrize('raw,code', [
    (WHEEL.replace(b'cp312', b'cp313'), 'WHEEL_ABI_MISMATCH'),
    (WHEEL.replace(b'manylinux_2_17_x86_64', b'macosx_14_0_x86_64'), 'WHEEL_PLATFORM_MISMATCH'),
    (WHEEL + b'Wheel-Version: 1.0\n', 'INVALID_WHEEL_METADATA'),
    (b'Wheel-Version: 1.0\n', 'INVALID_WHEEL_METADATA')])
def test_wheel_negative_metadata(offline, prepared, raw, code):
    write(offline[0], 'venv/lib/demo.dist-info/WHEEL', raw)
    refused(run(recreate(offline, prepared)), code, 'RUNTIME_ANALYSIS_STARTED')


def test_compatible_native_headers_still_leave_closure_unknown(offline, prepared):
    write(offline[0], 'venv/lib/demo.dist-info/WHEEL', WHEEL)
    write(offline[0], 'venv/lib/demo.dist-info/METADATA', b'Metadata-Version: 2.1\nName: demo\nVersion: 1.0\n')
    write(offline[0], 'venv/lib/demo.so', elf())
    result = run(recreate(offline, prepared))
    assert result['code'] == 'ASSESSMENT_BLOCKED', result
    assert any(c['check'] == 'native_header' and c['status'] == 'PARTIAL' for c in result['checks'])
    assert any(c['check'] == 'system_libraries_cpu_loader' and c['status'] == 'UNKNOWN' for c in result['checks'])
    assert not result['RUNTIME_REQUIREMENTS_READY']


@pytest.mark.parametrize('path,raw,code', [
    ('venv/lib/canary.pth', b'import canary\n', 'EXECUTABLE_PTH_UNSUPPORTED'),
    ('venv/lib/canary.pth', b'../escape\n', 'PTH_PATH_UNSUPPORTED'),
    ('venv/lib/sitecustomize.py', b'raise AssertionError("DO_NOT_RUN")', 'EXECUTABLE_STARTUP_UNSUPPORTED'),
    ('venv/bin/pip', b'#!/another/venv/bin/python\nraise AssertionError("DO_NOT_RUN")', 'VENV_PREFIX_MISMATCH')])
def test_startup_data_never_executed(offline, prepared, path, raw, code):
    write(offline[0], path, raw)
    candidate = recreate(offline, prepared)
    before = snapshot(candidate[6]), snapshot(candidate[4])
    refused(run(candidate), code, 'RUNTIME_ANALYSIS_STARTED')
    assert (snapshot(candidate[6]), snapshot(candidate[4])) == before


def test_application_pip_and_configuration_canaries_not_executed(offline, prepared, tmp_path):
    marker = tmp_path / 'CANARY_EXECUTED'
    program = ('from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("EXECUTED")\n').encode()
    write(offline[0], 'application/app.py', program)
    write(offline[0], 'venv/bin/pip', b'#!/opt/clash-yaml-manager/venv/bin/python\n' + program)
    write(offline[0], 'configuration/.env', b'APP_PASSWORD=CANARY_PASSWORD\nSECRET_KEY=CANARY_SECRET\n' + program)
    result = run(recreate(offline, prepared))
    assert result['code'] == 'ASSESSMENT_BLOCKED', result
    assert not marker.exists()
    assert 'CANARY_PASSWORD' not in assess.render(result).decode()
    assert 'CANARY_SECRET' not in assess.render(result).decode()


SID, REV, SOURCE = 'c'*32, 'd'*32, 'e'*32
TOKEN = 'F'*22
HOME = 'state/fixed_subscriptions/' + SID + '/' + REV


def fixed_state():
    return dict(version=6, subscriptions={SID: dict(id=SID, revision=REV, status='active', token=TOKEN,
                sources=[dict(id=SOURCE, type='manual', enabled=True)])}, retired_tokens=[])


def add_fixed(root):
    write(root, 'state/fixed_subscriptions.json', fixed_state())
    for name in ('base.yaml', 'current.yaml'):
        write(root, HOME + '/' + name, b'proxies: []\n')


def test_fixed_valid_closure_and_current_auth_rotation(offline, prepared):
    add_fixed(offline[0]); add_fixed(prepared[4])
    candidate = recreate(offline, prepared)
    write(prepared[4], 'state/auth.json', dict(AUTH, auth_version=2, password_hash=AUTH['password_hash'][:-1]+'c'))
    result = run(candidate)
    assert result['code'] == 'ASSESSMENT_BLOCKED', result
    assert 'STATE_DATA_ANALYZED' in result['phases']
    assert not result['RESTORE_PLAN_READY']


@pytest.mark.parametrize('change,code', [
    ('missing_revision', 'MISSING_REFERENCE'), ('missing_cache', 'MISSING_REFERENCE'),
    ('cache_mismatch', 'DIGEST_MISMATCH'), ('retired_active', 'REVOCATION_INCONSISTENT'),
    ('auth_instance', 'REVOCATION_INCONSISTENT'), ('auth_version', 'REVOCATION_INCONSISTENT'),
    ('auth_hash', 'REVOCATION_INCONSISTENT'), ('tombstone', 'REVOCATION_INCONSISTENT'),
    ('geoip_hash', 'DIGEST_MISMATCH'), ('geoip_size', 'DIGEST_MISMATCH'),
    ('health_reference', 'MISSING_REFERENCE'), ('health_schedule', 'INVALID_SCHEMA'),
    ('unknown_schema', 'UNSUPPORTED_VERSION'), ('unknown_component', 'UNEXPECTED_COMPONENT')])
def test_state_negative_real_analysis_stage(offline, prepared, monkeypatch, change, code):
    source, target = offline[0], prepared[4]
    add_fixed(source); add_fixed(target)
    if change == 'missing_cache':
        value = fixed_state()
        value['subscriptions'][SID]['sources'].append(dict(id='f'*32, type='uploaded', enabled=True))
        write(target, 'state/fixed_subscriptions.json', value)
    elif change == 'missing_revision': (target / HOME / 'base.yaml').unlink()
    elif change == 'cache_mismatch': write(target, HOME + '/current.yaml', b'proxies: [changed]\n')
    elif change == 'retired_active':
        value = fixed_state(); value['retired_tokens'] = [hashlib.sha256(TOKEN.encode()).hexdigest()]
        write(target, 'state/fixed_subscriptions.json', value)
    elif change.startswith('auth_'):
        value = dict(AUTH, auth_version=2)
        write(source, 'state/auth.json', value)
        current = dict(value)
        if change == 'auth_instance': current['instance_id'] = 'f'*32
        elif change == 'auth_version': current['auth_version'] = 1
        else: current['password_hash'] = current['password_hash'][:-1]+'c'
        write(target, 'state/auth.json', current)
    elif change == 'tombstone':
        write(source, 'state/temporary_links.json', dict(version=1, links={'T'*16: None}))
        write(target, 'state/temporary_links.json', dict(version=1, links={}))
    elif change.startswith('geoip_'):
        raw = b'SYNTHETIC_MMDB'
        write(target, 'state/geoip/active.mmdb', raw)
        meta = dict(database_type='GeoLite2-Country', size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), uploaded_at=1)
        meta['sha256' if change == 'geoip_hash' else 'size'] = '0'*64 if change == 'geoip_hash' else len(raw)+1
        write(target, 'state/settings.json', dict(version=1, geoip=meta))
    elif change.startswith('health_'):
        key = 'f'*32 if change == 'health_reference' else SID
        item = dict(mode='off', interval_seconds=None, next_check_at=None, scheduler_failures=0,
                    check_revision=0, last_trigger=None, last_job_result=None, nodes={})
        if change == 'health_schedule': item['mode'] = 'automatic'
        write(target, 'state/node_health.json', dict(version=2, subscriptions={key: item}))
    elif change == 'unknown_schema':
        value = fixed_state(); value['version'] = 7
        write(target, 'state/fixed_subscriptions.json', value)
    else: write(target, 'state/unknown/new.json', b'{}')
    candidate = recreate(offline, prepared)
    before = snapshot(candidate[6]), snapshot(target)
    trace = []
    original_state, original_role = data.state_checks, schema.role
    def traced_state(*args):
        trace.append('D2_STATE_ENTERED')
        return original_state(*args)
    def traced_role(path, kind):
        if path != 'state/unknown/new.json':
            return original_role(path, kind)
        assert trace == ['D2_STATE_ENTERED']
        trace.append('UNKNOWN_ALLOWLIST_ENTERED')
        try:
            return original_role(path, kind)
        except AuditFault as error:
            assert error.code == 'UNEXPECTED_COMPONENT'
            trace.append('UNKNOWN_ALLOWLIST_REJECTED')
            raise
    monkeypatch.setattr(data, 'state_checks', traced_state)
    monkeypatch.setattr(schema, 'role', traced_role)
    result = run(candidate)
    # Reachability is checked before the refusal code, so an early refusal fails.
    assert 'PACKAGE_VERIFIED' in result['phases']
    assert 'TARGET_VALIDATED' in result['phases']
    assert 'RUNTIME_DATA_ANALYZED' in result['phases']
    assert 'STATE_ANALYSIS_STARTED' in result['phases']
    assert trace == (['D2_STATE_ENTERED', 'UNKNOWN_ALLOWLIST_ENTERED', 'UNKNOWN_ALLOWLIST_REJECTED']
                     if change == 'unknown_component' else ['D2_STATE_ENTERED'])
    refused(result, code, 'STATE_ANALYSIS_STARTED')
    assert (snapshot(candidate[6]), snapshot(target)) == before
    print(json.dumps(dict(case=change, code=result['code'], phases=result['phases'], trace=trace,
                          ready=False, inputs_unchanged=True), sort_keys=True))


@pytest.mark.parametrize('path,expected', [('state/auth.json', 'STATE'),
    ('state/unknown/new.json', 'UNEXPECTED_COMPONENT'), ('outside/data.json', 'OUT_OF_SCOPE')])
def test_state_allowlist_exact_contract(path, expected):
    if expected == 'STATE':
        assert schema.role(path, 'file') == 'STATE'
    else:
        with pytest.raises(AuditFault) as failure:
            schema.role(path, 'file')
        assert failure.value.code == expected


def test_known_component_reaches_real_d2_auth_analysis(prepared, monkeypatch):
    observed = []
    original = data.auth
    def traced_auth(raw):
        value = original(raw)
        observed.append('AUTH_DATA_VALIDATED')
        return value
    monkeypatch.setattr(data, 'auth', traced_auth)
    before = snapshot(prepared[4]), snapshot(prepared[6])
    result = run(prepared)
    assert observed == ['AUTH_DATA_VALIDATED', 'AUTH_DATA_VALIDATED']
    assert result['code'] == 'ASSESSMENT_BLOCKED'
    assert 'STATE_DATA_ANALYZED' in result['phases']
    assert result['phases'][-1] == 'EXIT_REVALIDATION_COMPLETED'
    assert all(result[flag] for flag in inspect.FLAGS[:4])
    assert not any(result[flag] for flag in inspect.FLAGS[4:])
    assert not result['RESTORE_APPLY_IMPLEMENTED']
    assert (snapshot(prepared[4]), snapshot(prepared[6])) == before
    print(json.dumps(dict(case='known_auth', trace=observed, phases=result['phases'],
                          code=result['code'], ready=False, inputs_unchanged=True), sort_keys=True))


def test_geoip_temporary_links_notifications_and_schedulers_basic_closure(prepared):
    target = prepared[4]
    raw = b'SYNTHETIC_MMDB'
    write(target, 'state/geoip/active.mmdb', raw)
    write(target, 'state/settings.json', dict(version=1, geoip=dict(database_type='GeoLite2-Country',
        size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), uploaded_at=1)))
    write(target, 'outputs/live.yaml', b'proxies: []')
    write(target, 'state/temporary_links.json', dict(version=1, links={'T'*16: dict(filename='live.yaml', created_at=1, expires_at=2)}))
    write(target, 'state/login_attempts.json', dict(version=1, ips={'synthetic': dict(failures=[1], blocked_until=2)}))
    write(target, 'state/notifications.json', dict(version=1, revision=0, telegram=dict(enabled=False),
        events=dict(source_refresh=False, endpoint_health=False, proxy_health=False, scheduler=False),
        delivery=dict(last_attempt_at=None, last_success_at=None)))
    result = run(prepared)
    assert result['code'] == 'ASSESSMENT_BLOCKED', result
    assert 'STATE_DATA_ANALYZED' in result['phases']
    assert 'T'*16 not in assess.render(result).decode()


@pytest.mark.parametrize('kind,code', [('directory', 'UNSAFE_STORED_METADATA'),
                                     ('target', 'OBJECT_CHANGED'), ('eio', 'IO_FAILED')])
def test_final_revalidation_and_io_errors_clear_success_flags(prepared, monkeypatch, kind, code):
    reached = []
    original = data.state_checks
    def mutation(*args):
        value = original(*args)
        reached.append('STATE_VALIDATED_MUTATION_INJECTED')
        if kind == 'directory': (prepared[6] / 'records').chmod(0o777)
        elif kind == 'target': write(prepared[4], 'outputs/kept', b'CHANGED')
        else: raise OSError(errno.EIO, 'SYNTHETIC_SECRET_NOT_PRINTED')
        return value
    monkeypatch.setattr(data, 'state_checks', mutation)
    try:
        result = run(prepared)
        refused(result, code, 'STATE_ANALYSIS_STARTED')
        assert reached == ['STATE_VALIDATED_MUTATION_INJECTED']
        if kind != 'eio': assert 'FINAL_REVALIDATION_REJECTED' in result['phases']
        assert 'SYNTHETIC_SECRET' not in assess.render(result).decode()
    finally:
        (prepared[6] / 'records').chmod(0o700)


def test_material_resource_limit_fails_closed_at_real_analysis(prepared, monkeypatch):
    monkeypatch.setattr(assess, 'MAX_ANALYSIS_BYTES', 1)
    refused(run(prepared), 'ANALYSIS_BYTE_LIMIT', 'TARGET_VALIDATED')


def test_evidence_sources_and_synthetic_cannot_promote():
    observed = evidence.ProcessHostFactsProvider().observe()
    assert observed['values']['os'] and observed['values']['python_version']
    assert observed['scope'] == 'PROCESS_RUNTIME_ONLY_NOT_TARGET_RUNTIME'
    assert evidence.summarize(observed)['origin'] == 'OBSERVED_TRUSTED_HOST_FACT'
    for origin in ('SYNTHETIC_DECLARED', 'OPERATOR_DECLARED'):
        synthetic = dict(origin=origin, source='IN_PROCESS_SYNTHETIC_FIXTURE' if origin.startswith('SYNTHETIC')
                         else 'OPERATOR_DECLARATION', acquired_at=evidence.now(), values={'os': 'Linux'})
        assert evidence.summarize(synthetic)['origin'] == origin
        synthetic['origin'] = 'OBSERVED_TRUSTED_HOST_FACT'
        with pytest.raises(AuditFault, match='INVALID_EVIDENCE'):
            evidence.summarize(synthetic)
    stale = dict(observed, acquired_at='2020-01-01T00:00:00+00:00')
    with pytest.raises(AuditFault, match='STALE_EVIDENCE'): evidence.summarize(stale)


@pytest.mark.parametrize('tag', sorted(evidence.RELEASE_PINS))
def test_independent_accepted_release_pin_is_not_package_digest(tag):
    version = tag[1:]
    identity = dict(version=version, channel='stable', tag=tag, commit=evidence.RELEASE_PINS[tag][1])
    result = evidence.PinnedLocalReleaseProvider().observe(identity, io.Budget())
    assert result['origin'] == 'VERIFIED_TRUSTED_RELEASE_FACT'
    assert result['application']['application/VERSION'] == hashlib.sha256(version.encode() + b'\n').hexdigest()
    assert 'application/app.py' in result['application']
    wrong = dict(identity, commit='3'*40)
    assert evidence.PinnedLocalReleaseProvider().observe(wrong, io.Budget())['origin'] == 'UNKNOWN'


def test_cli_is_standalone_has_no_provider_override_and_no_app_import():
    proc = subprocess.run([sys.executable, '-B', '-m', 'scripts.recovery_assess', '--help'],
                          cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0
    assert '--target-fixture' in proc.stdout
    for override in ('--provider', '--uid', '--managed-root', '--host-facts', '--apply'):
        assert override not in proc.stdout


def test_link_escape_rejected_by_unchanged_verifier_before_analysis(prepared):
    root, manifest = prepared[1], copy.deepcopy(prepared[3])
    next(e for e in manifest['entries'] if e['path'] == 'venv/bin/python')['link_target'] = '../../../escape'
    (root / 'manifest.json').write_bytes(schema.canonical(manifest))
    refused(run(prepared), 'LINK_ESCAPE', 'PACKAGE_VERIFICATION_STARTED')
