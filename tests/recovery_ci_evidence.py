"""Audit exact test nodes, SHA binding and native stage proofs; no restore logic."""
import argparse
import json
from pathlib import Path
import stat
import xml.etree.ElementTree as ET


class EvidenceError(ValueError):
    pass


def require(value, code):
    if not value:
        raise EvidenceError(code)


def passed_nodes(path):
    nodes = {}
    for case in ET.parse(path).iter('testcase'):
        node = case.attrib['classname'].replace('.', '/') + '.py::' + case.attrib['name']
        require(node not in nodes, 'DUPLICATE_TEST_NODE')
        nodes[node] = not any(case.find(tag) is not None for tag in ('failure', 'error', 'skipped'))
    require(nodes, 'NO_TEST_NODES')
    return nodes


def proofs(log, marker):
    return [json.loads(line.split(marker, 1)[1]) for line in log.splitlines() if marker in line]


def verify_native(proof, case):
    from_case = '-'.join(case[k] for k in ('kind', 'directory', 'field', 'entry'))
    require(proof['test_id'] == from_case and proof['result'] == 'PASS', 'NATIVE_NOT_PASSED')
    require(proof['platform'].startswith('linux') and bool(proof['kernel']), 'NOT_LINUX')
    require(proof['euid'] == proof['egid'] == 0, 'ROOT_NOT_PROVEN')
    require(proof['cleanup_complete'] and proof['valid_reverse_control'] and proof['readonly'], 'CONTROL_OR_CLEANUP_MISSING')
    require(not proof['production_accessed'] and not proof['restore_apply'] and not proof['prune'], 'PRODUCTION_BOUNDARY')
    initial, final = proof['initial'], proof['final']
    require(initial['uid'] == initial['gid'] == 0 and initial['mode'] == 0o700, 'INITIAL_NOT_PRIVATE')
    require(initial['kind'] == final['kind'] == stat.S_IFDIR, 'NOT_DIRECTORY')
    require((initial['device'], initial['inode']) == (final['device'], final['inode']), 'OBJECT_IDENTITY_CHANGED')
    entry = ['ENTRY_VALIDATED', 'TRUSTED_DIRECTORY_OPENED', 'RECORD_VERIFICATION_COMPLETED']
    if case['kind'] == 'positive':
        expected = 'VERIFIED' if case['entry'] == 'verify' else 'PLAN_BLOCKED'
        require(proof['phases'] == entry + ['EXIT_REVALIDATION_REACHED', 'EXIT_REVALIDATION_VALIDATED'], 'POSITIVE_PATH_INCOMPLETE')
        require(initial == final and proof['mutation_syscall'] is None, 'POSITIVE_CHANGED')
        require(proof['trust_anchor'] and not proof['all_trust_flags_false'], 'POSITIVE_NOT_VERIFIED')
        require(proof['verified'] == (case['entry'] == 'verify'), 'POSITIVE_CODE_FLAG')
    else:
        expected = ('OBJECT_CHANGED' if case['field'] == 'gid' else 'UNSAFE_ANCESTOR') if case['kind'] == 'ancestor' else 'UNSAFE_STORED_METADATA'
        require(proof['phases'] == entry + ['MUTATION_INJECTED', 'EXIT_REVALIDATION_REACHED', 'EXIT_REVALIDATION_REJECTED'], 'RACE_PATH_INCOMPLETE')
        require(proof['all_trust_flags_false'] and not proof['verified'] and not proof['trust_anchor'], 'UNSAFE_SUCCESS_FLAG')
        require(final == proof['injected'], 'READER_REPAIRED_METADATA')
        if case['field'] == 'mode':
            require(proof['mutation_syscall'] == 'fchmod' and final['mode'] == 0o777, 'PERMISSION_NOT_INJECTED')
            require(final['uid'] == final['gid'] == 0, 'MODE_RACE_OWNER_CHANGED')
        else:
            require(proof['mutation_syscall'] == 'fchown', 'REAL_CHOWN_NOT_PROVEN')
            require((final['uid'], final['gid']) == ((12345, 0) if case['field'] == 'uid' else (0, 12345)), 'OWNER_NOT_INJECTED')
            require(final['mode'] == 0o700, 'OWNER_RACE_MODE_CHANGED')
    require(proof['actual_code'] == proof['expected_code'] == expected, 'WRONG_REJECTION_CODE')


def audit(base, expected):
    identities = [(base / name).read_text().strip() for name in ('input.sha', 'workflow.sha', 'checkout.sha', 'validated.sha')]
    require(len(identities[0]) == 40 and all(c in '0123456789abcdef' for c in identities[0]), 'INVALID_SHA')
    require(len(set(identities)) == 1, 'SHA_BINDING_MISMATCH')
    full, focused = passed_nodes(base / 'full.xml'), passed_nodes(base / 'focused.xml')
    require(len(full) >= expected['minimum_full_tests'] and all(full.values()), 'FULL_SUITE_INCOMPLETE_OR_SKIP')
    for node in expected['linux_only'] + expected['phase_b_c'] + list(expected['native']) + expected.get('local_ci', []):
        require(full.get(node) is True, 'REQUIRED_NODE_NOT_PASSED')
    for node in expected['directory_security']:
        require(focused.get(node) is True, 'DIRECTORY_NODE_NOT_PASSED')
    require(all(focused.values()), 'FOCUSED_FAILURE_OR_SKIP')
    native = proofs((base / 'validate.log').read_text(), 'RECOVERY_LINUX_NATIVE=')
    by_id = {p['test_id']: p for p in native}
    require(len(native) == len(by_id) == len(expected['native']), 'NATIVE_PROOFS_MISSING_OR_DUPLICATE')
    for node, case in expected['native'].items():
        key = '-'.join(case[k] for k in ('kind', 'directory', 'field', 'entry'))
        require(key in by_id, 'NATIVE_PROOF_MISSING')
        verify_native(by_id[key], case)
    paths = proofs((base / 'focused.log').read_text(), 'SECURITY_PATH_PROOF=')
    require(len(paths) == len(expected['directory_paths']), 'DIRECTORY_PROOFS_MISSING')
    require({p['test'] for p in paths} == set(expected['directory_paths']), 'DIRECTORY_PROOF_SET_MISMATCH')
    for path in paths:
        require(path['trust'] is False and path['phases'] == expected['directory_paths'][path['test']], 'DIRECTORY_PHASE_NOT_PROVEN')
    return dict(result='PASS', sha=identities[0], linux_only=len(expected['linux_only']), native=len(native), directory_paths=len(paths))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    args = parser.parse_args(argv)
    expected = json.loads(Path(__file__).with_name('recovery_ci_expected.json').read_text())
    try:
        result = audit(args.evidence, expected)
    except (EvidenceError, OSError, ValueError, KeyError, ET.ParseError) as error:
        print('LINUX_CI_EVIDENCE: FAIL ' + (str(error) if isinstance(error, EvidenceError) else type(error).__name__))
        return 1
    print('LINUX_CI_EVIDENCE: ' + json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
