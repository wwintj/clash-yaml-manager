"""S1: real data pipeline, canonical numeric refusal and no-execution canaries."""
import hashlib
import json

import pytest

from scripts import recovery_assess as assess, recovery_assess_data as data
from scripts import recovery_inspect as inspect, recovery_manifest as schema
from scripts.backup_audit import AuditFault
from test_recovery_package import offline
from test_recovery_inspect import scene, snapshot, AUTH
from test_recovery_assess import CFG, write

MAX_EPOCH = 253402300799
CASES = [
    ('huge-1001', 10**1000, False), ('huge-2001', 10**2000, False),
    ('negative-huge', -10**1000, False), ('max-int', MAX_EPOCH, True),
    ('over-max-int', MAX_EPOCH+1, False), ('zero-int', 0, True), ('one-int', 1, True),
    ('negative-int', -1, False), ('bool-true', True, False), ('bool-false', False, False),
    ('numeric-string', '123', False), ('zero-float', 0.0, True),
    ('fraction', 0.25, True), ('max-float', float(MAX_EPOCH), True),
    ('negative-float', -0.25, False), ('over-max-float', MAX_EPOCH+0.5, False),
    ('nan', float('nan'), False), ('positive-infinity', float('inf'), False),
    ('negative-infinity', float('-inf'), False),
]


@pytest.fixture
def timestamp_scene(offline, tmp_path):
    source = offline[0]
    marker = tmp_path / 'BACKUP_CODE_EXECUTED'
    program = ('from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("EXECUTED")\n').encode()
    write(source, 'venv/pyvenv.cfg', CFG)
    write(source, 'application/app.py', program)
    write(source, 'venv/bin/pip', b'#!/opt/clash-yaml-manager/venv/bin/python\n' + program)
    return scene.__wrapped__(offline, tmp_path), marker


@pytest.mark.parametrize('label,value,valid', CASES, ids=[c[0] for c in CASES])
def test_geoip_timestamp_pipeline(timestamp_scene, monkeypatch, label, value, valid):
    fixture, marker = timestamp_scene
    target = fixture[4]
    raw_database = b'SYNTHETIC_PRIVATE_MMDB'
    metadata = dict(database_type='SYNTHETIC_PRIVATE_KIND', size=len(raw_database),
                    sha256=hashlib.sha256(raw_database).hexdigest(), uploaded_at=value)
    # Non-standard JSON constants are deliberately untrusted bytes. Never use
    # the canonical serializer to emit them; the real parser must reject them.
    raw = json.dumps(dict(version=1, geoip=metadata), allow_nan=True).encode()
    write(target, 'state/geoip/active.mmdb', raw_database)
    write(target, 'state/settings.json', raw)
    before = snapshot(fixture[6]), snapshot(target)
    stages = []
    original_state, original_timestamp = data.state_checks, data.timestamp
    def state(*args):
        stages.append('D2_STATE_ANALYSIS_ENTERED')
        return original_state(*args)
    def timestamp(incoming):
        stages.append('D2_TIMESTAMP_VALIDATION_ENTERED')
        return original_timestamp(incoming)
    monkeypatch.setattr(data, 'state_checks', state)
    monkeypatch.setattr(data, 'timestamp', timestamp)
    result = assess.assess(fixture[0], str(target))
    assert all(stage in result['phases'] for stage in (
        'PACKAGE_VERIFIED', 'TARGET_VALIDATED', 'RUNTIME_DATA_ANALYZED', 'STATE_ANALYSIS_STARTED'))
    assert stages[0] == 'D2_STATE_ANALYSIS_ENTERED'
    nonstandard = label in ('nan', 'positive-infinity', 'negative-infinity')
    assert stages == (['D2_STATE_ANALYSIS_ENTERED'] if nonstandard else
                      ['D2_STATE_ANALYSIS_ENTERED', 'D2_TIMESTAMP_VALIDATION_ENTERED'])
    if valid:
        assert result['code'] == 'ASSESSMENT_BLOCKED', result
        assert result['phases'][-1] == 'EXIT_REVALIDATION_COMPLETED'
        assert all(result[flag] for flag in inspect.FLAGS[:4])
    else:
        assert result['code'] == ('INVALID_JSON' if nonstandard else 'INVALID_SCHEMA'), result
        assert not any(result[flag] for flag in inspect.FLAGS)
        assert result['binding'] is None
    assert not any(result[flag] for flag in inspect.FLAGS[4:])
    assert not result['ASSESSMENT_SUPPORTED'] and not result['RESTORE_APPLY_IMPLEMENTED']
    report = assess.render(result)
    assert len(report) <= assess.MAX_REPORT_BYTES
    assert schema.parse(report) == result  # Requires the real canonical contract.
    assert schema.canonical(schema.parse(report)) == report
    for secret in ('SYNTHETIC_PRIVATE_MMDB', 'SYNTHETIC_PRIVATE_KIND',
                   'SYNTHETIC_SECRET', AUTH['password_hash'], str(target), str(marker)):
        assert secret.encode() not in report
    assert (snapshot(fixture[6]), snapshot(target)) == before
    assert not marker.exists()
    print(json.dumps(dict(case=label, code=result['code'], stages=stages,
        canonical=True, inputs_unchanged=True, backup_code_executed=False,
        restore_ready=False, report_bytes=len(report)), sort_keys=True))


@pytest.mark.parametrize('label,value,valid', CASES, ids=[c[0] for c in CASES])
def test_numeric_guard_exact_types_and_boundaries(label, value, valid):
    if valid:
        assert data.timestamp(value) is None
    else:
        with pytest.raises(AuditFault) as rejection:
            data.timestamp(value)
        assert rejection.value.code == 'INVALID_SCHEMA'
