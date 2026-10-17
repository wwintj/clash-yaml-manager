"""D3-P1: isolated synthetic protocol; real v1 verifier stays unchanged."""
import base64
import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import attestation_synthetic as p
from scripts import recovery_package as package
from test_recovery_package import offline, created
from test_recovery_inspect import snapshot


@pytest.fixture
def case(offline, tmp_path):
    controller = p.Controller()
    event = controller.start(1000, [])  # Inventory is empty before real Writer creation.
    controller.advance(event, 'QUIET_ATTESTED', 1001)
    # The genuine Writer runs after the SYNTHETIC capture starts; no live source.
    report, root, manifest, record = created(offline)
    assert report['publication'] == 'PACKAGE_AND_RECORD_DURABLE'
    controller.installation['declaration_sha256'] = hashlib.sha256(
        p.canonical(manifest['installation_binding'])).hexdigest()
    managed = offline[2]
    fd = os.open(managed, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        reader = p.FixtureReader(fd, package.verify)
        binding = reader.binding(report['operation_id'])
        controller.advance(event, 'PACKAGE_DURABLE', 1002, binding, durable=True)
        controller.advance(event, 'RECORD_DURABLE', 1003, binding, durable=True)
        raw = controller.issue(event, reader, 1004, 1104)
        # Outside the v1 managed tree; temporary, private, explicitly synthetic.
        namespace = tmp_path / 'synthetic-attestations'; namespace.mkdir(mode=0o700)
        path = namespace / 'attestation.json'
        output = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(output, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        parent = os.open(namespace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        controller.complete(event, raw, durable=True)
        nonce = os.urandom(16).hex()
        current = dict(origin='SYNTHETIC', installation=copy.deepcopy(controller.installation),
                       key_id=controller.key_id, nonce=nonce, observed_at=1020)
        yield dict(controller=controller, event=event, reader=reader, raw=raw, root=root,
                   record=record, operation=report['operation_id'], managed=managed,
                   path=path, nonce=nonce, current=current)
    finally:
        os.close(fd)


def run(case, **overrides):
    controller = case['controller']
    args = dict(raw=case['raw'], reader=case['reader'], operation=case['operation'],
                keys={controller.key_id: dict(secret=controller.secret, active=True)},
                events=controller.events, controller=controller.controller,
                current=case['current'], nonce=case['nonce'], now=1020)
    args.update(overrides)
    return p.verify(**args)


def assert_limits(answer):
    for field in ('CAPTURE_EVENT_ORIGIN_TRUSTED', 'INSTALLATION_CONTINUITY_VERIFIED',
                  'CAPTURE_INSTALLATION_CONTINUITY_VERIFIED', 'ASSESSMENT_SUPPORTED',
                  'RUNTIME_REQUIREMENTS_READY', 'RESTORE_PLAN_READY', 'RESTORE_PROVEN',
                  'RESTORE_APPLY_IMPLEMENTED', 'AUTO_PRUNE_IMPLEMENTED'):
        assert answer[field] is False
    assert answer['scope'] == 'SYNTHETIC_ONLY'


def assert_refusal(answer, code, reached):
    assert answer['code'] == code, answer
    assert reached in answer['stages'], answer
    assert not answer['SYNTHETIC_INSTALLATION_CONTINUITY_VERIFIED']
    assert_limits(answer)


def resign(case, change):
    payload = copy.deepcopy(p.parse(case['raw'])['payload'])
    change(payload)
    return p.canonical(dict(payload=payload, mac=p.mac(case['controller'].secret, payload)))


def test_positive_real_v1_binding_and_readonly_scope(case):
    before = snapshot(case['managed']), snapshot(case['path'].parent)
    answer = run(case)
    assert answer['code'] == 'SYNTHETIC_CONTINUITY_VERIFIED'
    assert answer['CRYPTOGRAPHIC_BINDING_VALID']
    assert answer['SYNTHETIC_CAPTURE_EVENT_ORIGIN_VALID']
    assert answer['SYNTHETIC_INSTALLATION_CONTINUITY_VERIFIED']
    assert answer['stages'][-1] == 'EXIT_REVALIDATION_COMPLETED'
    assert_limits(answer)
    assert (snapshot(case['managed']), snapshot(case['path'].parent)) == before
    # No secret, input path or authentication material in the report.
    encoded = json.dumps(answer)
    assert case['controller'].secret.hex() not in encoded
    assert str(case['managed']) not in encoded


def test_different_process_same_temporary_controlled_identity(case):
    c = case['controller']
    transport = dict(raw=base64.b64encode(case['raw']).decode(), operation=case['operation'],
                     secret=base64.b64encode(c.secret).decode(), key_id=c.key_id, events=c.events,
                     controller=c.controller, current=case['current'], nonce=case['nonce'],
                     managed=str(case['managed']))
    program = '''
import base64,json,os,sys
sys.path.insert(0, 'tests')
import attestation_synthetic as p
from scripts import recovery_package as package, recovery_io as io
x=json.load(sys.stdin)
# Trusted synthetic child policy only, no environment or product CLI override.
io.ROOT_UID=os.geteuid(); io.ROOT_GID=os.getegid(); io.MANAGED_ROOT=x['managed']
fd=os.open(x['managed'],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try:
    answer=p.verify(base64.b64decode(x['raw']),p.FixtureReader(fd,package.verify),x['operation'],
       {x['key_id']:dict(secret=base64.b64decode(x['secret']),active=True)},x['events'],
       x['controller'],x['current'],x['nonce'],1020)
    print(json.dumps(answer,sort_keys=True))
finally:
    os.close(fd)
'''
    completed = subprocess.run([sys.executable, '-B', '-c', program], input=json.dumps(transport),
                               cwd=Path(__file__).resolve().parents[1], capture_output=True,
                               text=True, timeout=10)
    assert completed.returncode == 0
    answer = json.loads(completed.stdout)
    assert answer['code'] == 'SYNTHETIC_CONTINUITY_VERIFIED'
    assert answer['SYNTHETIC_INSTALLATION_CONTINUITY_VERIFIED']
    assert c.secret.hex() not in completed.stdout + completed.stderr
    assert transport['secret'] not in completed.stdout + completed.stderr
    assert_limits(answer)


@pytest.mark.parametrize('kind', ['package', 'record', 'blob'])
def test_replaced_material_is_rejected_after_mac(case, kind):
    if kind == 'package':
        old = case['root'].with_name('detached-synthetic-package')
        case['root'].rename(old)
        import shutil
        shutil.copytree(old, case['root'])
    elif kind == 'record':
        raw = case['record'].read_bytes()
        case['record'].rename(case['record'].with_name('detached-synthetic-record'))
        case['record'].write_bytes(raw); case['record'].chmod(0o600)
    else:
        blob = next((case['root'] / 'blobs').iterdir())
        blob.write_bytes(b'SYNTHETIC_CHANGED')
    answer = run(case)
    expected = 'BINDING_MISMATCH' if kind == 'record' else 'PACKAGE_NOT_VERIFIED'
    assert_refusal(answer, expected, 'MAC_VALIDATED')


@pytest.mark.parametrize('kind,code', [('digest', 'BINDING_MISMATCH'), ('operation', 'OPERATION_MISMATCH'),
                                      ('installation', 'EVENT_ORIGIN_MISMATCH'), ('event', 'EVENT_MISSING'),
                                      ('controller', 'EVENT_ORIGIN_MISMATCH')])
def test_resigned_claims_do_not_manufacture_event_authority(case, kind, code):
    def change(value):
        if kind == 'digest': value['binding']['manifest_sha256'] = '0'*64
        if kind == 'operation': value['binding']['operation_id'] = '0'*32
        if kind == 'installation': value['installation']['epoch'] = '0'*32
        if kind == 'event': value['event']['id'] = '0'*32
        if kind == 'controller': value['controller']['id'] = '0'*32
    answer = run(case, raw=resign(case, change))
    assert answer['CRYPTOGRAPHIC_BINDING_VALID']  # Even key-holder re-signing is not provenance.
    assert not answer['SYNTHETIC_CAPTURE_EVENT_ORIGIN_VALID']
    assert_refusal(answer, code, 'MAC_VALIDATED')


def test_device_inode_bindings_are_local_not_portable(case):
    raw = resign(case, lambda v: v['binding']['package'].update(
        device=v['binding']['package']['device'] + 1))
    answer = run(case, raw=raw)
    assert answer['CRYPTOGRAPHIC_BINDING_VALID']
    assert_refusal(answer, 'BINDING_MISMATCH', 'V1_VERIFICATION_STARTED')
    # This is a binding negative, NOT a real cross-filesystem or Linux mount exercise.


@pytest.mark.parametrize('kind,code', [('unknown', 'UNKNOWN_KEY'), ('revoked', 'KEY_REVOKED'),
                                     ('wrong_secret', 'MAC_INVALID'), ('mac', 'MAC_INVALID')])
def test_keys_and_mac_fail_closed(case, kind, code):
    c = case['controller']; keys = {c.key_id: dict(secret=c.secret, active=True)}
    raw = case['raw']
    if kind == 'unknown': keys = {}
    elif kind == 'revoked': keys[c.key_id]['active'] = False
    elif kind == 'wrong_secret': keys[c.key_id]['secret'] = os.urandom(32)
    else:
        envelope = p.parse(raw)
        envelope['mac'] = ('0' if envelope['mac'][0] != '0' else '1') + envelope['mac'][1:]
        raw = p.canonical(envelope)
    answer = run(case, keys=keys, raw=raw)
    assert not answer['CRYPTOGRAPHIC_BINDING_VALID']
    assert_refusal(answer, code, 'SCHEMA_VALIDATED')


@pytest.mark.parametrize('kind,code', [('expired', 'EVIDENCE_EXPIRED'), ('future', 'EVIDENCE_EXPIRED'),
                                     ('incomplete', 'INCOMPLETE_EVENT'), ('posthoc', 'EVENT_MISSING'),
                                     ('nonce', 'NONCE_MISMATCH'), ('stale', 'STALE_OBSERVATION'),
                                     ('installation', 'INSTALLATION_MISMATCH'), ('different_key', 'INSTALLATION_MISMATCH')])
def test_time_event_and_current_installation_are_independent(case, kind, code):
    current = copy.deepcopy(case['current']); events = copy.deepcopy(case['controller'].events)
    now = 1020
    if kind == 'expired': now = 1104
    elif kind == 'future': now = 1003
    elif kind == 'incomplete': events[case['event']]['phase'] = 'RECORD_DURABLE'
    elif kind == 'posthoc': events = {}  # Old signed bytes alone are not a historical capture event.
    elif kind == 'nonce': current['nonce'] = '0'*32
    elif kind == 'stale': current['observed_at'] = 980
    elif kind == 'installation': current['installation']['epoch'] = '0'*32
    else: current['key_id'] = p.Controller().key_id
    answer = run(case, current=current, events=events, now=now)
    assert answer['CRYPTOGRAPHIC_BINDING_VALID']
    assert_refusal(answer, code, 'MAC_VALIDATED')


def test_full_identity_and_key_clone_is_indistinguishable_not_physical_proof(case):
    clone = p.Controller()  # Independent identity initially, then copied software state.
    assert clone.key_id != case['controller'].key_id
    for attribute in ('secret', 'key_id', 'installation', 'controller', 'events'):
        setattr(clone, attribute, copy.deepcopy(getattr(case['controller'], attribute)))
    assert clone.secret == case['controller'].secret
    # Material remains the valid fixture: NOT an actual filesystem/VPS clone exercise.
    answer = run(case, keys={clone.key_id: dict(secret=clone.secret, active=True)},
                 current=copy.deepcopy(case['current']), events=clone.events, controller=clone.controller)
    assert answer['SYNTHETIC_INSTALLATION_CONTINUITY_VERIFIED']
    assert_limits(answer)  # No production/physical-host claim, even on software match.
    print('CLONE_LIMITATION=NOT_DISTINGUISHABLE_WITH_COPIED_SOFTWARE_STATE')


@pytest.mark.parametrize('phase', ['CAPTURE_STARTED', 'QUIET_ATTESTED', 'PACKAGE_DURABLE'])
def test_issuance_requires_record_durable_and_known_event(case, phase):
    c = case['controller']; event = c.start(1000, [])
    if phase != 'CAPTURE_STARTED': c.advance(event, 'QUIET_ATTESTED', 1001)
    if phase == 'PACKAGE_DURABLE': c.advance(event, 'PACKAGE_DURABLE', 1002, case['reader'].binding(case['operation']), durable=True)
    with pytest.raises(p.Refusal) as error:
        c.issue(event, case['reader'], 1004, 1104)
    assert error.value.code == 'INCOMPLETE_EVENT'
    with pytest.raises(p.Refusal) as error:
        c.issue('0'*32, case['reader'], 1004, 1104)
    assert error.value.code == 'EVENT_MISSING'


def test_preexisting_package_cannot_be_enrolled_as_new_capture(case):
    c = case['controller']; event = c.start(1010, [case['operation']])
    c.advance(event, 'QUIET_ATTESTED', 1011)
    with pytest.raises(p.Refusal) as error:
        c.advance(event, 'PACKAGE_DURABLE', 1012, case['reader'].binding(case['operation']), durable=True)
    assert error.value.code == 'POSTHOC_CAPTURE_REFUSED'
    assert c.events[event]['phase'] == 'QUIET_ATTESTED'


@pytest.mark.parametrize('phase', ['PACKAGE_DURABLE', 'RECORD_DURABLE'])
def test_uncertain_publication_or_crash_cannot_be_acknowledged(case, phase):
    c = case['controller']; event = c.start(1000, [])
    c.advance(event, 'QUIET_ATTESTED', 1001)
    binding = case['reader'].binding(case['operation'])
    if phase == 'RECORD_DURABLE': c.advance(event, 'PACKAGE_DURABLE', 1002, binding, durable=True)
    before = copy.deepcopy(c.events[event])
    with pytest.raises(p.Refusal) as error:
        c.advance(event, phase, 1003, binding, durable=False)
    assert error.value.code == 'DURABILITY_NOT_ATTESTED'
    assert c.events[event] == before


def test_missing_record_cannot_be_signed(case):
    c = case['controller']
    c.events[case['event']]['phase'] = 'RECORD_DURABLE'
    case['record'].unlink()
    with pytest.raises(p.Refusal) as error:
        c.issue(case['event'], case['reader'], 1004, 1104)
    assert error.value.code == 'PACKAGE_NOT_VERIFIED'


def test_issuance_io_failure_is_sanitized_without_completion(case, monkeypatch):
    c = case['controller']; c.events[case['event']]['phase'] = 'RECORD_DURABLE'
    def broken(*args, **kwargs): raise OSError(errno.EIO, 'SYNTHETIC_KEY_DETAIL_MUST_NOT_ECHO')
    monkeypatch.setattr(case['reader'], 'read', broken)
    with pytest.raises(p.Refusal) as error:
        c.issue(case['event'], case['reader'], 1004, 1104)
    assert error.value.code == str(error.value) == 'IO_FAILED'
    assert c.events[case['event']]['phase'] == 'RECORD_DURABLE'


def test_issued_mac_without_completion_is_not_event_authority(case):
    case['controller'].events[case['event']]['phase'] = 'ATTESTATION_ISSUED'
    answer = run(case)
    assert answer['CRYPTOGRAPHIC_BINDING_VALID']
    assert not answer['SYNTHETIC_CAPTURE_EVENT_ORIGIN_VALID']
    assert_refusal(answer, 'INCOMPLETE_EVENT', 'FILES_BOUND')


@pytest.mark.parametrize('kind', ['not_durable', 'bad_mac'])
def test_capture_completion_requires_separate_valid_ack(case, kind):
    c = case['controller']; c.events[case['event']]['phase'] = 'ATTESTATION_ISSUED'
    raw = case['raw']
    if kind == 'bad_mac':
        envelope = p.parse(raw); envelope['mac'] = '0'*64; raw = p.canonical(envelope)
    with pytest.raises(p.Refusal) as error:
        c.complete(case['event'], raw, durable=kind != 'not_durable')
    assert error.value.code == ('DURABILITY_NOT_ATTESTED' if kind == 'not_durable' else 'MAC_INVALID')
    assert c.events[case['event']]['phase'] == 'ATTESTATION_ISSUED'


def test_rotation_retained_mac_key_does_not_preserve_installation_authority(case):
    rotated = p.Controller()
    current = copy.deepcopy(case['current'])
    current.update(key_id=rotated.key_id, installation=rotated.installation)
    answer = run(case, current=current)
    assert answer['CRYPTOGRAPHIC_BINDING_VALID'] and answer['SYNTHETIC_CAPTURE_EVENT_ORIGIN_VALID']
    assert_refusal(answer, 'INSTALLATION_MISMATCH', 'SYNTHETIC_EVENT_VALIDATED')


@pytest.mark.parametrize('kind,code', [('algorithm', 'INVALID_ALGORITHM'), ('domain', 'WRONG_DOMAIN'),
                                     ('protocol', 'WRONG_DOMAIN'), ('origin', 'INVALID_ORIGIN'),
                                     ('version', 'UNSUPPORTED_VERSION'), ('extra', 'INVALID_SCHEMA'),
                                     ('missing', 'INVALID_SCHEMA'), ('order', 'INVALID_SEQUENCE')])
def test_schema_and_downgrade_refusal_before_mac(case, kind, code):
    def change(v):
        if kind == 'algorithm': v['algorithm'] = 'SHA256'
        if kind == 'domain': v['domain'] = 'OTHER_PROTOCOL'
        if kind == 'protocol': v['protocol'] = 'production-attestation-v1'
        if kind == 'origin': v['event']['origin'] = 'OBSERVED_TRUSTED_HOST_FACT'
        if kind == 'version': v['schema_version'] = 2
        if kind == 'extra': v['public_key'] = 'UNTRUSTED_SYNTHETIC_KEY'
        if kind == 'missing': del v['key_id']
        if kind == 'order': v['event']['quiet_at'] = 1005
    answer = run(case, raw=resign(case, change))
    assert answer['code'] == code and not answer['CRYPTOGRAPHIC_BINDING_VALID']
    assert_limits(answer)


@pytest.mark.parametrize('kind,code', [('whitespace', 'NON_CANONICAL'), ('duplicate', 'DUPLICATE_KEY'),
                                     ('huge_bytes', 'RESOURCE_LIMIT'), ('huge_int', 'RESOURCE_LIMIT'),
                                     ('nan', 'INVALID_JSON'), ('float', 'INVALID_JSON'),
                                     ('depth', 'RESOURCE_LIMIT'), ('missing', 'ATTESTATION_MISSING')])
def test_bounded_unique_json(case, kind, code):
    if kind == 'whitespace': raw = case['raw'] + b'\n'
    elif kind == 'duplicate': raw = b'{"mac":"a","mac":"b"}'
    elif kind == 'huge_bytes': raw = b'x'*(p.MAX_BYTES+1)
    elif kind == 'huge_int': raw = ('{"x":'+str(10**1000)+'}').encode()
    elif kind == 'nan': raw = b'{"x":NaN}'
    elif kind == 'float': raw = b'{"x":1.0}'
    elif kind == 'depth': raw = b'{"x":'*8 + b'1' + b'}'*8
    else: raw = None
    answer = run(case, raw=raw)
    assert answer['code'] == code and not answer['CRYPTOGRAPHIC_BINDING_VALID']
    assert_limits(answer)


@pytest.mark.parametrize('kind', ['eio', 'record_change'])
def test_exit_barrier_io_and_mutation(case, monkeypatch, kind):
    reached = []
    def hook():
        reached.append('MUTATION_BARRIER')
        if kind == 'eio':
            def broken(*args, **kwargs): raise OSError(errno.EIO, 'SYNTHETIC_SECRET_NEVER_ECHO')
            monkeypatch.setattr(case['reader'], 'read', broken)
        else:
            # Keep canonical v1 bytes, but replace the Record inode at the barrier.
            raw = case['record'].read_bytes()
            case['record'].rename(case['record'].with_name('detached-synthetic-record'))
            case['record'].write_bytes(raw); case['record'].chmod(0o600)
    answer = run(case, hook=hook)
    assert reached == ['MUTATION_BARRIER']
    assert_refusal(answer, 'IO_FAILED' if kind == 'eio' else 'INPUT_CHANGED', 'EXIT_REVALIDATION_REACHED')
    assert 'SYNTHETIC_SECRET_NEVER_ECHO' not in json.dumps(answer)


def test_no_production_import_and_canonical_roundtrip(case):
    envelope = p.parse(case['raw'])
    assert p.canonical(envelope) == case['raw']
    assert set(case['root'].iterdir()) == {case['root']/'manifest.json', case['root']/'blobs'}
    assert set(case['managed'].iterdir()) == {case['managed']/'packages', case['managed']/'records'}
    root = Path(__file__).resolve().parents[1]
    for path in [root/'app.py', *(root/'core').glob('*.py'), *(root/'scripts').glob('*.py')]:
        assert 'attestation_synthetic' not in path.read_text()
