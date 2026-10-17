"""Native Linux root races on private fixtures; never a production restore."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import recovery_inspect as inspect, recovery_io as io
from test_recovery_inspect import offline, scene, snapshot

pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'),
                              reason='Linux real root ownership and permission gate')

ENTRY = ['ENTRY_VALIDATED', 'TRUSTED_DIRECTORY_OPENED', 'RECORD_VERIFICATION_COMPLETED']
RACE_PHASES = ENTRY + ['MUTATION_INJECTED', 'EXIT_REVALIDATION_REACHED', 'EXIT_REVALIDATION_REJECTED']
POSITIVE_PHASES = ENTRY + ['EXIT_REVALIDATION_REACHED', 'EXIT_REVALIDATION_VALIDATED']
CASES = ([dict(kind='positive', directory='records', field='none', entry=e) for e in ('verify', 'dry_run')]
         + [dict(kind='owner', directory=d, field=f, entry=e)
            for d in ('records', 'packages', 'managed') for f in ('uid', 'gid') for e in ('verify', 'dry_run')]
         + [dict(kind='permission', directory=d, field='mode', entry=e)
            for d in ('records', 'packages', 'managed') for e in ('verify', 'dry_run')]
         + [dict(kind='ancestor', directory='ancestor', field=f, entry=e)
            for f in ('mode', 'uid', 'gid') for e in ('verify', 'dry_run')])


def case_id(case):
    return '-'.join(case[k] for k in ('kind', 'directory', 'field', 'entry'))


def expected_code(case):
    if case['kind'] == 'positive':
        return 'VERIFIED' if case['entry'] == 'verify' else 'PLAN_BLOCKED'
    if case['kind'] == 'ancestor':
        return 'OBJECT_CHANGED' if case['field'] == 'gid' else 'UNSAFE_ANCESTOR'
    return 'UNSAFE_STORED_METADATA'


def metadata(info):
    return dict(device=info.st_dev, inode=info.st_ino, kind=stat.S_IFMT(info.st_mode),
                mode=stat.S_IMODE(info.st_mode), uid=info.st_uid, gid=info.st_gid)


def exercise(case, data, base, hooks, proof):
    """Shared real check path; Mac only exercises non-ownership control cases."""
    operation, _, _, _, target, _, managed = data
    if case['kind'] == 'ancestor':
        ancestor = base / 'trusted-ancestor'
        child = ancestor / 'child'
        ancestor.mkdir(mode=0o700)
        child.mkdir(mode=0o700)
        relocated = child / 'managed'
        managed.rename(relocated)
        managed = relocated
        hooks.setattr(io, 'MANAGED_ROOT', str(managed))
        changed = ancestor
    else:
        changed = managed if case['directory'] == 'managed' else managed / case['directory']
    held = os.open(changed, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    initial = os.fstat(held)
    phases = []
    proof.update(test_id=case_id(case), platform=sys.platform, kernel=platform.release(),
                 euid=os.geteuid(), egid=os.getegid(), initial=metadata(initial), phases=phases,
                 expected_code=expected_code(case), actual_code=None, result='FAIL',
                 mutation_syscall=None, production_accessed=False, restore_apply=False, prune=False)
    try:
        assert stat.S_ISDIR(initial.st_mode) and stat.S_IMODE(initial.st_mode) == 0o700
        assert initial.st_uid == io.ROOT_UID == os.geteuid()
        assert initial.st_gid == io.ROOT_GID == os.getegid()
        before = snapshot(managed), snapshot(target)
        # A valid, complete reverse control precedes every injection.
        assert inspect.verify(operation)['code'] == 'VERIFIED'
        control = inspect.dry_run(operation, str(target))
        assert control['code'] == 'PLAN_BLOCKED' and not control['RESTORE_PLAN_READY']
        assert not control['RESTORE_PROVEN'] and not control['apply_implemented']
        assert (snapshot(managed), snapshot(target)) == before
        proof['valid_reverse_control'] = True
        original_state, original_exit = inspect.package_state, io.revalidate_directory
        observed = []

        def after_record_verification(fd, manifest, budget):
            result = original_state(fd, manifest, budget)
            if not observed:
                # inspect_fd reaches here only AFTER canonical/Record/digest/content binding.
                phases.extend(ENTRY)
                if case['kind'] != 'positive':
                    if case['field'] == 'mode':
                        os.fchmod(held, 0o777)
                        proof['mutation_syscall'] = 'fchmod'
                    else:
                        assert os.geteuid() == os.getegid() == io.ROOT_UID == io.ROOT_GID == 0
                        os.fchown(held, 12345 if case['field'] == 'uid' else 0,
                                  12345 if case['field'] == 'gid' else 0)
                        proof['mutation_syscall'] = 'fchown'
                    changed_info = os.fstat(held)  # real kernel stat, never patched
                    assert (changed_info.st_dev, changed_info.st_ino) == (initial.st_dev, initial.st_ino)
                    if case['field'] == 'mode':
                        assert stat.S_IMODE(changed_info.st_mode) == 0o777
                    elif case['field'] == 'uid':
                        assert (changed_info.st_uid, changed_info.st_gid) == (12345, 0)
                    else:
                        assert (changed_info.st_uid, changed_info.st_gid) == (0, 12345)
                    proof['injected'] = metadata(changed_info)
                    phases.append('MUTATION_INJECTED')
                observed.append((snapshot(managed), snapshot(target)))
            return result

        def observe_real_exit(parent, name, fd, old, **kwargs):
            current = os.fstat(fd)
            if (current.st_dev, current.st_ino) != (initial.st_dev, initial.st_ino):
                return original_exit(parent, name, fd, old, **kwargs)
            assert phases == (ENTRY if case['kind'] == 'positive' else ENTRY + ['MUTATION_INJECTED'])
            assert kwargs.get('ancestry' if case['kind'] == 'ancestor' else 'stored') is True
            phases.append('EXIT_REVALIDATION_REACHED')
            try:
                result = original_exit(parent, name, fd, old, **kwargs)
            except inspect.AuditFault:
                phases.append('EXIT_REVALIDATION_REJECTED')
                raise
            phases.append('EXIT_REVALIDATION_VALIDATED')
            return result

        hooks.setattr(inspect, 'package_state', after_record_verification)
        hooks.setattr(io, 'revalidate_directory', observe_real_exit)
        result = inspect.verify(operation) if case['entry'] == 'verify' else inspect.dry_run(operation, str(target))
        proof.update(actual_code=result['code'], verified=result['code'] == 'VERIFIED',
                     trust_anchor=result['TRUST_ANCHOR_VERIFIED'],
                     all_trust_flags_false=not any(result[f] for f in inspect.FLAGS),
                     same_object=metadata(os.fstat(held))['inode'] == initial.st_ino,
                     final=metadata(os.fstat(held)))
        assert result['code'] == expected_code(case)
        assert phases == (POSITIVE_PHASES if case['kind'] == 'positive' else RACE_PHASES)
        assert observed and (snapshot(managed), snapshot(target)) == observed[0]
        assert not result['RESTORE_PROVEN'] and not result['RESTORE_PLAN_READY']
        if case['kind'] == 'positive':
            assert all(result[f] for f in inspect.FLAGS[:4])
        else:
            assert not any(result[f] for f in inspect.FLAGS)
            # Verifier must leave injected metadata alone, not silently repair it.
            assert proof['final'] == proof['injected']
        proof.update(result='PASS', readonly=True)
        return proof
    finally:
        # Operate only on our still-open inode. No pathname chown/chmod or symlink traversal.
        try:
            if case['kind'] != 'positive':
                if case['field'] != 'mode' and os.geteuid() == 0:
                    os.fchown(held, initial.st_uid, initial.st_gid)
                os.fchmod(held, stat.S_IMODE(initial.st_mode))
        finally:
            os.close(held)


def native_main(identifier):
    proof = {'test_id': identifier, 'result': 'FAIL', 'actual_code': None, 'phases': [],
             'platform': sys.platform, 'kernel': platform.release(),
             'euid': os.geteuid(), 'egid': os.getegid()}
    try:
        assert sys.platform.startswith('linux')
        assert os.geteuid() == os.getegid() == io.ROOT_UID == io.ROOT_GID == 0
        assert shutil.rmtree.avoids_symlink_attacks, 'FD_RELATIVE_CLEANUP_REQUIRED'
        case = next(c for c in CASES if case_id(c) == identifier)
        # No host account/service changes; ONLY this new root-private /tmp subtree.
        with tempfile.TemporaryDirectory(prefix='cym-c-native-', dir='/tmp') as temporary:
            base = Path(temporary)
            assert stat.S_IMODE(base.lstat().st_mode) == 0o700
            with pytest.MonkeyPatch.context() as hooks:
                data = scene.__wrapped__(offline.__wrapped__(base, hooks), base)
                assert io.ROOT_UID == io.ROOT_GID == 0
                exercise(case, data, base, hooks, proof)
        proof['cleanup_complete'] = True
    except Exception as error:
        # Fixed metadata only; never emit arbitrary exception text/traceback/configuration.
        proof.update(result='FAIL', error_type=type(error).__name__)
    print(json.dumps(proof, sort_keys=True), flush=True)
    return 0 if proof['result'] == 'PASS' else 1


@pytest.mark.parametrize('case', CASES, ids=case_id)
def test_linux_root_recovery_race(case, capsys):
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--native-case', case_id(case)]
    if os.geteuid() != 0:
        command = ['sudo', '-n', *command]
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=45,
                                env={'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1',
                                     'PYTHONNOUSERSITE': '1'})
    except (OSError, subprocess.TimeoutExpired) as error:
        pytest.fail('ROOT_NATIVE_EXECUTION_BLOCKED: ' + type(error).__name__)
    try:
        proof = json.loads(result.stdout)
    except ValueError:
        pytest.fail('ROOT_NATIVE_PROOF_MISSING')
    with capsys.disabled():
        print('RECOVERY_LINUX_NATIVE=' + json.dumps(proof, sort_keys=True), flush=True)
    assert result.returncode == 0 and proof['result'] == 'PASS', 'ROOT_NATIVE_GATE_NOT_PROVEN'
    assert proof['test_id'] == case_id(case) and proof['platform'].startswith('linux')
    assert proof['euid'] == proof['egid'] == 0 and proof['cleanup_complete']
    assert proof['valid_reverse_control'] and proof['readonly'] and not proof['production_accessed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-case', choices=[case_id(c) for c in CASES], required=True)
    raise SystemExit(native_main(parser.parse_args().native_case))
