"""Deterministic synthetic trust-chain regressions; never change host ownership."""
import hashlib
import json
import os
import shutil
import stat

import pytest

from test_recovery_inspect import scene, offline, snapshot
from scripts import recovery_inspect as inspect, recovery_io as io


DIRECTORY_PHASES = ['ENTRY_VALIDATED', 'TRUSTED_DIRECTORY_OPENED',
                    'RECORD_VERIFICATION_COMPLETED', 'MUTATION_INJECTED',
                    'EXIT_REVALIDATION_REACHED', 'EXIT_REVALIDATION_REJECTED']


def metadata(path):
    info = path.lstat()
    return dict(device=info.st_dev, inode=info.st_ino, kind=stat.S_IFMT(info.st_mode),
                mode=oct(stat.S_IMODE(info.st_mode)), uid=info.st_uid, gid=info.st_gid)


def observe_directory_exit(monkeypatch, identity, phases):
    original = io.revalidate_directory

    def observe(parent, name, fd, before, **kwargs):
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != identity:
            return original(parent, name, fd, before, **kwargs)
        assert phases[-1] == 'MUTATION_INJECTED', phases
        phases.append('EXIT_REVALIDATION_REACHED')
        try:
            return original(parent, name, fd, before, **kwargs)
        except inspect.AuditFault:
            phases.append('EXIT_REVALIDATION_REJECTED')
            raise

    monkeypatch.setattr(io, 'revalidate_directory', observe)


def prove_rejection(phases, result, label):
    assert phases == DIRECTORY_PHASES, phases
    assert not any(result[flag] for flag in inspect.FLAGS)
    print('SECURITY_PATH_PROOF=' + json.dumps(dict(test=label, phases=phases,
          code=result['code'], trust=result['TRUST_ANCHOR_VERIFIED']), sort_keys=True))


@pytest.mark.parametrize('entry', ['verify', 'dry_run'])
@pytest.mark.parametrize('directory,mode', [
    ('records', 0o777), ('records', 0o755), ('records', 0o770),
    ('packages', 0o777), ('managed', 0o755)])
def test_private_directory_permission_race(scene, monkeypatch, entry, directory, mode):
    operation, _, record, _, target, _, managed = scene
    changed = managed if directory == 'managed' else managed / directory
    identity = changed.stat().st_dev, changed.stat().st_ino
    trusted_digest = hashlib.sha256(record.read_bytes()).hexdigest()
    target_before = snapshot(target)
    original = inspect.package_state
    observed = {}
    phases = []
    observe_directory_exit(monkeypatch, identity, phases)

    def mutate(fd, manifest, budget):
        result = original(fd, manifest, budget)
        if not observed:
            phases.extend(DIRECTORY_PHASES[:3])
            changed.chmod(mode)
            phases.append('MUTATION_INJECTED')
            observed['managed'] = snapshot(managed)
        return result

    monkeypatch.setattr(inspect, 'package_state', mutate)
    try:
        result = inspect.verify(operation) if entry == 'verify' else inspect.dry_run(operation, str(target))
        assert observed, 'must reach the real verifier after digest/content verification'
        assert result['code'] == 'UNSAFE_STORED_METADATA', result
        prove_rejection(phases, result, f'permission:{directory}:{oct(mode)}:{entry}')
        assert (changed.stat().st_dev, changed.stat().st_ino) == identity
        assert stat.S_IMODE(changed.stat().st_mode) == mode  # reader did not repair it
        assert hashlib.sha256(record.read_bytes()).hexdigest() == trusted_digest
        assert snapshot(managed) == observed['managed']
        assert snapshot(target) == target_before
    finally:
        changed.chmod(0o700)


@pytest.mark.parametrize('directory', ['records', 'packages', 'managed'])
@pytest.mark.parametrize('field', ['st_uid', 'st_gid'])
def test_private_directory_owner_race_simulated(scene, monkeypatch, directory, field):
    # Mac safely exercises the actual fstat/private branch. Real chown remains
    # LINUX_NATIVE_PENDING; no sudo or host account changes in this test.
    operation, _, _, _, target, _, managed = scene
    changed = managed if directory == 'managed' else managed / directory
    identity = changed.stat().st_dev, changed.stat().st_ino
    before = snapshot(managed), snapshot(target)
    original_state, original_fstat = inspect.package_state, os.fstat
    active = []
    seen = []
    phases = []
    observe_directory_exit(monkeypatch, identity, phases)

    class OtherOwner:
        def __init__(self, info): self.info = info
        def __getattr__(self, key):
            return getattr(self.info, key) + 1 if key == field else getattr(self.info, key)

    def fstat(fd):
        info = original_fstat(fd)
        if active and (info.st_dev, info.st_ino) == identity:
            seen.append(field)
            return OtherOwner(info)
        return info

    def activate(fd, manifest, budget):
        result = original_state(fd, manifest, budget)
        phases.extend(DIRECTORY_PHASES[:3])
        active.append(True)
        phases.append('MUTATION_INJECTED')
        return result

    monkeypatch.setattr(os, 'fstat', fstat)
    monkeypatch.setattr(inspect, 'package_state', activate)
    result = inspect.verify(operation)
    assert active and seen, 'must reach held-FD ownership revalidation'
    assert result['code'] == 'UNSAFE_STORED_METADATA', result
    prove_rejection(phases, result, f'owner-simulation:{directory}:{field}')
    assert (snapshot(managed), snapshot(target)) == before


@pytest.mark.parametrize('directory', ['records', 'packages', 'managed'])
def test_directory_binding_replacement(scene, monkeypatch, directory):
    operation, _, _, _, target, _, managed = scene
    changed = managed if directory == 'managed' else managed / directory
    parked = changed.with_name(changed.name + '-held-original')
    original_state = inspect.package_state
    identity = changed.stat().st_dev, changed.stat().st_ino
    observed = {}
    target_before = snapshot(target)
    phases = []
    observe_directory_exit(monkeypatch, identity, phases)

    def replace(fd, manifest, budget):
        result = original_state(fd, manifest, budget)
        if not observed:
            phases.extend(DIRECTORY_PHASES[:3])
            changed.rename(parked)
            changed.mkdir(mode=0o700)
            phases.append('MUTATION_INJECTED')
            observed['changed'] = snapshot(changed)
            observed['parked'] = snapshot(parked)
        return result

    monkeypatch.setattr(inspect, 'package_state', replace)
    try:
        result = inspect.verify(operation)
        assert observed
        assert (parked.stat().st_dev, parked.stat().st_ino) == identity
        assert (changed.stat().st_dev, changed.stat().st_ino) != identity
        assert result['code'] == 'OBJECT_CHANGED', result
        prove_rejection(phases, result, f'directory-replacement:{directory}')
        assert snapshot(changed) == observed['changed']
        assert snapshot(parked) == observed['parked']
        assert snapshot(target) == target_before
    finally:
        if parked.exists():
            shutil.rmtree(changed)
            parked.rename(changed)


def test_record_identity_replacement_with_identical_digest(scene, monkeypatch):
    operation, _, record, _, target, _, managed = scene
    original = inspect.package_state
    old_identity = record.stat().st_dev, record.stat().st_ino
    digest = hashlib.sha256(record.read_bytes()).hexdigest()
    target_before = snapshot(target)
    observed = {}
    phases = []
    original_stream = io.stream

    def record_stream(parent, name, *args, **kwargs):
        if name != record.name or not observed:
            return original_stream(parent, name, *args, **kwargs)
        assert kwargs.get('expected') is not None
        phases.append('FINAL_RECORD_READ_REACHED')
        try:
            return original_stream(parent, name, *args, **kwargs)
        except inspect.AuditFault:
            phases.append('FINAL_RECORD_READ_REJECTED')
            raise

    def replace(fd, manifest, budget):
        result = original(fd, manifest, budget)
        phases.extend(DIRECTORY_PHASES[:3])
        replacement = record.with_name('replacement')
        replacement.write_bytes(record.read_bytes())
        replacement.chmod(0o600)
        os.replace(replacement, record)
        phases.append('MUTATION_INJECTED')
        observed['managed'] = snapshot(managed)
        return result

    monkeypatch.setattr(inspect, 'package_state', replace)
    monkeypatch.setattr(io, 'stream', record_stream)
    result = inspect.verify(operation)
    assert observed
    assert (record.stat().st_dev, record.stat().st_ino) != old_identity
    assert hashlib.sha256(record.read_bytes()).hexdigest() == digest
    assert result['code'] == 'OBJECT_CHANGED', result
    assert not any(result[flag] for flag in inspect.FLAGS)
    assert phases == DIRECTORY_PHASES[:4] + ['FINAL_RECORD_READ_REACHED', 'FINAL_RECORD_READ_REJECTED']
    print('SECURITY_PATH_PROOF=' + json.dumps(dict(test='record-replacement', phases=phases,
          code=result['code'], trust=result['TRUST_ANCHOR_VERIFIED']), sort_keys=True))
    assert snapshot(managed) == observed['managed'] and snapshot(target) == target_before


@pytest.mark.parametrize('change,code', [('permissions', 'UNSAFE_ANCESTOR'), ('replacement', 'OBJECT_CHANGED')])
def test_held_ancestor_revalidated(scene, tmp_path, monkeypatch, change, code):
    operation, _, _, _, target, _, managed = scene
    parent = tmp_path / 'ancestor'
    child = parent / 'child'
    child.mkdir(parents=True, mode=0o700)
    parent.chmod(0o700)
    relocated = child / 'managed'
    managed.rename(relocated)
    monkeypatch.setattr(io, 'MANAGED_ROOT', str(relocated))
    parked = tmp_path / 'held-ancestor'
    identity = parent.stat().st_dev, parent.stat().st_ino
    before = snapshot(relocated), snapshot(target)
    layers = []
    for path in reversed([child, *child.parents]):
        info = path.lstat()
        assert stat.S_ISDIR(info.st_mode)
        assert info.st_uid in (0, io.ROOT_UID)
        writable = stat.S_IMODE(info.st_mode) & 0o022
        assert not writable or (info.st_uid == 0 and info.st_mode & stat.S_ISVTX)
        layers.append(metadata(path))
    assert parent.stat().st_uid == io.ROOT_UID == os.geteuid()
    assert parent.stat().st_gid == io.ROOT_GID == os.getegid()
    assert parent.stat().st_dev == child.stat().st_dev == relocated.stat().st_dev
    # Full real Verifier entry and exit must succeed before installing hooks.
    assert inspect.verify(operation)['code'] == 'VERIFIED'
    assert (snapshot(relocated), snapshot(target)) == before
    phases = []
    observed = {}
    original = inspect.package_state
    observe_directory_exit(monkeypatch, identity, phases)

    def mutate(fd, manifest, budget):
        result = original(fd, manifest, budget)
        phases.extend(DIRECTORY_PHASES[:3])
        if change == 'permissions':
            parent.chmod(0o777)
            observed['managed'] = snapshot(relocated)
        else:
            parent.rename(parked)
            parent.mkdir(mode=0o700)
            (parent / 'child').mkdir(mode=0o700)
            observed['managed'] = snapshot(parked / 'child/managed')
        phases.append('MUTATION_INJECTED')
        return result

    monkeypatch.setattr(inspect, 'package_state', mutate)
    try:
        result = inspect.verify(operation)
        assert result['code'] == code, result
        prove_rejection(phases, result, f'ancestor:{change}')
        held = parent if change == 'permissions' else parked
        assert (held.stat().st_dev, held.stat().st_ino) == identity
        if change == 'permissions': assert stat.S_IMODE(held.stat().st_mode) == 0o777
        else: assert (parent.stat().st_dev, parent.stat().st_ino) != identity
        assert snapshot(held / 'child/managed') == observed['managed']
        assert snapshot(target) == before[1]
        print('ANCESTOR_METADATA_PROOF=' + json.dumps(dict(change=change, entry_layers=layers,
              held_exit=metadata(held), path_exit=metadata(parent)), sort_keys=True))
    finally:
        if parked.exists():
            shutil.rmtree(parent)
            parked.rename(parent)
        parent.chmod(0o700)


def test_unsafe_ancestor_before_entry_is_distinct(scene, tmp_path, monkeypatch):
    operation, _, _, _, _, _, managed = scene
    parent = tmp_path / 'unsafe-ancestor'
    parent.mkdir(mode=0o700)
    relocated = parent / 'managed'
    managed.rename(relocated)
    monkeypatch.setattr(io, 'MANAGED_ROOT', str(relocated))
    assert inspect.verify(operation)['code'] == 'VERIFIED'
    original_stream = io.stream
    phases = []

    def no_record_read(fd, name, *args, **kwargs):
        if name == operation + '.json': pytest.fail('unsafe entry must not reach Record verification')
        return original_stream(fd, name, *args, **kwargs)

    def no_state(*args): pytest.fail('unsafe entry must not reach mutation stage')

    monkeypatch.setattr(io, 'stream', no_record_read)
    monkeypatch.setattr(inspect, 'package_state', no_state)
    try:
        parent.chmod(0o777)
        before = snapshot(parent)
        phases.append('UNSAFE_BEFORE_ENTRY')
        result = inspect.verify(operation)
        assert result['code'] == 'UNSAFE_ANCESTOR'
        assert not any(result[flag] for flag in inspect.FLAGS)
        phases.append('ENTRY_REJECTED_WITHOUT_RECORD_OR_MUTATION')
        assert snapshot(parent) == before
        print('SECURITY_PATH_PROOF=' + json.dumps(dict(test='unsafe-ancestor-admission', phases=phases,
              code=result['code'], trust=result['TRUST_ANCHOR_VERIFIED']), sort_keys=True))
    finally:
        parent.chmod(0o700)


def test_stable_private_directories_and_flags(scene):
    operation, _, _, _, target, _, managed = scene
    before = snapshot(managed), snapshot(target)
    result = inspect.verify(operation)
    assert result['code'] == 'VERIFIED'
    assert all(result[flag] for flag in inspect.FLAGS[:4])
    assert not any(result[flag] for flag in inspect.FLAGS[4:])
    assert (snapshot(managed), snapshot(target)) == before


def test_exit_check_failure_cannot_publish_success(scene, monkeypatch):
    operation, _, _, _, target, _, managed = scene
    before = snapshot(managed), snapshot(target)
    original = io.revalidate_directory
    seen = []

    def refuse(parent, name, fd, info, **kwargs):
        original(parent, name, fd, info, **kwargs)
        if name == 'records':
            seen.append(name)
            raise inspect.AuditFault('OBJECT_CHANGED')

    monkeypatch.setattr(io, 'revalidate_directory', refuse)
    result = inspect.verify(operation)
    assert seen and result['code'] == 'OBJECT_CHANGED'
    assert not any(result[flag] for flag in inspect.FLAGS)
    assert (snapshot(managed), snapshot(target)) == before
