"""Local CI auditor tests and real non-privileged barrier controls, not Linux proof."""
import copy
import json
from pathlib import Path
import stat
import xml.etree.ElementTree as ET

import pytest
from ruamel.yaml import YAML

from conftest import ROOT
from test_recovery_inspect import scene, offline
from test_recovery_inspect_linux import CASES, case_id, exercise, expected_code, RACE_PHASES, POSITIVE_PHASES
import recovery_ci_evidence as evidence


LOCAL_CASES = [c for c in CASES if c['kind'] in ('positive', 'permission')
               or (c['kind'] == 'ancestor' and c['field'] == 'mode')]


@pytest.mark.parametrize('case', LOCAL_CASES, ids=case_id)
def test_local_real_permission_barrier(scene, tmp_path, monkeypatch, case):
    proof = exercise(case, scene, tmp_path, monkeypatch, {})
    assert proof['result'] == 'PASS' and proof['actual_code'] == expected_code(case)
    assert proof['phases'] == (POSITIVE_PHASES if case['kind'] == 'positive' else RACE_PHASES)
    # This proves the common barrier/exit path, NOT root chown or Linux execution.
    print('LOCAL_REACHABILITY=' + json.dumps({'test_id': proof['test_id'],
          'phases': proof['phases'], 'actual_code': proof['actual_code'], 'result': 'PASS'}))


def test_workflow_uses_named_steps_and_opt_in_sha_binding():
    workflow = YAML(typ='safe').load((ROOT / '.github/workflows/release-candidate.yml').read_text())
    inputs = workflow['on']['workflow_dispatch']['inputs']
    assert inputs['phase_c_evidence']['type'] == 'boolean' and inputs['phase_c_evidence']['default'] is False
    steps = workflow['jobs']['validate']['steps']
    by_name = {s['name']: s for s in steps if 'name' in s}
    assert by_name['Validate without publication']['run'] == 'python scripts/release.py --validate-only'
    assert by_name['Validate without publication']['if'] == '${{ !inputs.phase_c_evidence }}'
    preparation = by_name['Prepare Phase C evidence']
    assert preparation['env']['EXPECTED_SHA'] == '${{ inputs.ref }}'
    assert 'test "$GITHUB_SHA" = "$EXPECTED_SHA"' in preparation['run']
    assert 'test "$(git rev-parse HEAD)" = "$EXPECTED_SHA"' in preparation['run']
    assert 'sudo -n true' in preparation['run'] and 'test "$(id -u)" -ne 0' in preparation['run']
    assert by_name['Validate with Phase C evidence']['env']['PYTEST_ADDOPTS'].startswith('-x --junitxml=')
    assert 'release.py --validate-only' in by_name['Validate with Phase C evidence']['run']
    assert 'sudo ' not in by_name['Validate with Phase C evidence']['run']
    assert 'recovery_ci_evidence.py' in by_name['Verify Phase C evidence paths']['run']
    assert by_name['Preserve Phase C evidence']['if'] == '${{ always() && inputs.phase_c_evidence }}'
    assert steps[0]['with']['ref'] == "${{ inputs.ref || 'main' }}"


def test_expected_nodes_and_stage_contract_are_complete():
    required = json.loads((ROOT / 'tests/recovery_ci_expected.json').read_text())
    assert len(required['linux_only']) == 31 and len(set(required['linux_only'])) == 31
    assert len(required['phase_b_c']) == 144 and len(required['directory_security']) == 25
    assert len(required['directory_paths']) == 23
    assert len(required['local_ci']) == len(set(required['local_ci'])) == 58
    assert required['minimum_full_tests'] == 4338
    nodes = {'tests/test_recovery_inspect_linux.py::test_linux_root_recovery_race[' + case_id(c) + ']': c for c in CASES}
    assert len(nodes) == 26 and required['native'] == nodes


def json_native(case):
    """Synthetic JSON ONLY to test the auditor; never emitted as native evidence."""
    initial = dict(device=1, inode=2, kind=stat.S_IFDIR, mode=0o700, uid=0, gid=0)
    final = dict(initial)
    if case['kind'] != 'positive':
        final[case['field']] = 0o777 if case['field'] == 'mode' else 12345
    return dict(test_id=case_id(case), result='PASS', platform='linux', kernel='unit-json',
                euid=0, egid=0, initial=initial, final=final, injected=final,
                cleanup_complete=True, valid_reverse_control=True, readonly=True,
                production_accessed=False, restore_apply=False, prune=False,
                verified=case['kind'] == 'positive' and case['entry'] == 'verify',
                trust_anchor=case['kind'] == 'positive', all_trust_flags_false=case['kind'] != 'positive',
                phases=POSITIVE_PHASES if case['kind'] == 'positive' else RACE_PHASES,
                mutation_syscall=None if case['kind'] == 'positive' else 'fchmod' if case['field'] == 'mode' else 'fchown',
                expected_code=expected_code(case), actual_code=expected_code(case))


@pytest.mark.parametrize('case', CASES, ids=case_id)
def test_auditor_accepts_each_well_formed_json_contract(case):
    evidence.verify_native(json_native(case), case)


@pytest.mark.parametrize('change', ['missing_entry', 'early_refusal', 'not_linux', 'not_root',
    'unsafe_initial', 'different_inode', 'fake_syscall', 'wrong_code', 'trust_true',
    'missing_cleanup', 'reader_repaired', 'restore', 'prune'])
def test_auditor_rejects_incomplete_or_unsafe_json(change):
    case = next(c for c in CASES if c['kind'] == 'owner' and c['field'] == 'uid')
    proof = copy.deepcopy(json_native(case))
    if change == 'missing_entry': proof['phases'] = RACE_PHASES[1:]
    elif change == 'early_refusal': proof['phases'] = ['ENTRY_REJECTED']
    elif change == 'not_linux': proof['platform'] = 'darwin'
    elif change == 'not_root': proof['egid'] = 1
    elif change == 'unsafe_initial': proof['initial']['mode'] = 0o777
    elif change == 'different_inode': proof['final']['inode'] = 3
    elif change == 'fake_syscall': proof['mutation_syscall'] = 'monkeypatch'
    elif change == 'wrong_code': proof['actual_code'] = 'PERMISSION_DENIED'
    elif change == 'trust_true': proof['trust_anchor'] = True
    elif change == 'missing_cleanup': proof['cleanup_complete'] = False
    elif change == 'reader_repaired': proof['injected'] = dict(proof['final'], uid=0)
    elif change == 'restore': proof['restore_apply'] = True
    elif change == 'prune': proof['prune'] = True
    with pytest.raises(evidence.EvidenceError): evidence.verify_native(proof, case)


def junit(path, nodes, refused=None):
    root = ET.Element('testsuite')
    for node in nodes:
        filename, name = node.split('::')
        case = ET.SubElement(root, 'testcase', classname=filename[:-3].replace('/', '.'), name=name)
        if node == refused: ET.SubElement(case, 'skipped', type='pytest.xfail')
    ET.ElementTree(root).write(path)


def test_junit_skip_and_duplicate_cannot_be_pass(tmp_path):
    path = tmp_path / 'junit.xml'
    node = 'tests/test_recovery_inspect_linux.py::test_linux_root_recovery_race[unit]'
    junit(path, [node], refused=node)
    assert evidence.passed_nodes(path)[node] is False
    junit(path, [node, node])
    with pytest.raises(evidence.EvidenceError): evidence.passed_nodes(path)


@pytest.mark.parametrize('change', ['none', 'sha', 'missing_native', 'duplicate_native', 'skipped', 'missing_phase'])
def test_end_to_end_auditor_requires_sha_nodes_and_proofs(tmp_path, change):
    # Tiny fabricated reports exercise audit parsing only, no Linux PASS claim.
    case = CASES[0]
    native = 'tests/test_recovery_inspect_linux.py::test_linux_root_recovery_race[' + case_id(case) + ']'
    directory = 'tests/test_recovery_directory_security.py::unit'
    required = dict(minimum_full_tests=2, linux_only=[], phase_b_c=[], native={native: case},
                    directory_security=[directory], directory_paths={'unit': RACE_PHASES})
    for name in ('input.sha', 'workflow.sha', 'checkout.sha', 'validated.sha'):
        (tmp_path / name).write_text('a' * 40)
    junit(tmp_path / 'full.xml', [native, directory], refused=native if change == 'skipped' else None)
    junit(tmp_path / 'focused.xml', [directory])
    line = 'RECOVERY_LINUX_NATIVE=' + json.dumps(json_native(case)) + '\n'
    (tmp_path / 'validate.log').write_text('' if change == 'missing_native' else line * (2 if change == 'duplicate_native' else 1))
    (tmp_path / 'focused.log').write_text('SECURITY_PATH_PROOF=' + json.dumps(dict(test='unit', trust=False,
        phases=['ENTRY_REJECTED'] if change == 'missing_phase' else RACE_PHASES)) + '\n')
    if change == 'sha': (tmp_path / 'workflow.sha').write_text('b' * 40)
    if change == 'none': assert evidence.audit(tmp_path, required)['result'] == 'PASS'
    else:
        with pytest.raises(evidence.EvidenceError): evidence.audit(tmp_path, required)
