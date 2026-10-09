"""Real kernel locks and updater control flow on isolated, synthetic installs.

The local UID policy is a trusted test-copy adaptation, never an environment
switch in the production guard. Linux root/private ownership is proved separately.
"""
import errno
import json
import os
from pathlib import Path
import shutil
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time

import pytest

from conftest import ROOT, local_guard_copy
from scripts import deployment_guard as guard
from test_deployment import deployment, executable

START = '29edecab2da5fadb0025afe80f117959021635ab'


def wait_path(path, child):
    end = time.monotonic() + 15
    while not path.exists():
        assert child.poll() is None, child.communicate()
        assert time.monotonic() < end, 'Synthetic process barrier timed out'
        time.sleep(0.02)


def test_persistent_private_lock_and_stale_file(isolated_guard):
    g = isolated_guard
    with g.held_deployment_guard() as held:
        root = Path(g.GUARD_ROOT); lock = root / g.GUARD_NAME
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        assert stat.S_IMODE(lock.stat().st_mode) == 0o600
        assert lock.stat().st_uid == g.GUARD_UID and lock.stat().st_gid == g.GUARD_GID
        assert lock.read_bytes() == b''
        identity = g.guard_identity(lock.stat())
        with pytest.raises(g.DeploymentGuardError, match='CONFLICT') as refused:
            g.guard_acquire()
        assert refused.value.exit_code == 75
        assert g.current_deployment_guard() is held
    os.utime(lock, (1, 1))
    with g.held_deployment_guard():
        assert g.guard_identity(lock.stat()) == identity
        assert lock.read_bytes() == b''
    assert lock.exists()  # No unlink/recreate, PID or age interpretation.


@pytest.mark.parametrize('fault', ['root-mode', 'root-symlink', 'file-mode', 'file-symlink', 'hardlink', 'fifo', 'socket', 'directory', 'payload', 'ancestor'])
def test_unsafe_objects_refused_without_repair(isolated_guard, tmp_path, fault):
    g = isolated_guard
    with g.held_deployment_guard():
        pass
    root = Path(g.GUARD_ROOT); lock = root / g.GUARD_NAME
    external = tmp_path / 'external'; external.write_bytes(b'outside'); external.chmod(0o600)
    connected = None
    short = None
    if fault == 'root-mode': root.chmod(0o755)
    elif fault == 'root-symlink':
        root.rename(tmp_path / 'moved'); root.symlink_to(tmp_path / 'moved', target_is_directory=True)
    elif fault == 'file-mode': lock.chmod(0o644)
    elif fault == 'ancestor': tmp_path.chmod(0o777)
    else:
        lock.unlink()  # External attack in a fixture; the guard never unlinks.
        if fault == 'file-symlink': lock.symlink_to(external)
        elif fault == 'hardlink': os.link(external, lock)
        elif fault == 'fifo': os.mkfifo(lock, 0o600)
        elif fault == 'socket':
            short = tempfile.TemporaryDirectory(prefix='cym-', dir='/tmp')
            short_socket = Path(short.name) / 's'
            connected = socket.socket(socket.AF_UNIX); connected.bind(str(short_socket))
            short_socket.rename(lock)
        elif fault == 'directory': lock.mkdir(mode=0o600)
        elif fault == 'payload': lock.write_bytes(b'not a lock'); lock.chmod(0o600)
    before = (root.lstat().st_mode, lock.lstat().st_mode, lock.lstat().st_ino)
    try:
        with pytest.raises(g.DeploymentGuardError): g.guard_acquire()
        assert (root.lstat().st_mode, lock.lstat().st_mode, lock.lstat().st_ino) == before
        assert external.read_bytes() == b'outside'
    finally:
        if connected: connected.close()
        if short: short.cleanup()
        tmp_path.chmod(0o700)


@pytest.mark.parametrize('owner', ['GUARD_UID', 'GUARD_GID'])
def test_untrusted_owner_policy_refused(isolated_guard, monkeypatch, owner):
    g = isolated_guard
    with g.held_deployment_guard(): pass
    monkeypatch.setattr(g, owner, getattr(g, owner) + 10000)
    with pytest.raises(g.DeploymentGuardError): g.guard_acquire()


def test_replaced_inode_detected_and_second_updater_still_excluded(isolated_guard):
    g = isolated_guard
    held = g.guard_acquire()
    try:
        lock = Path(g.GUARD_ROOT) / g.GUARD_NAME
        lock.rename(lock.with_name('externally-moved'))
        lock.touch(mode=0o600)
        with pytest.raises(g.DeploymentGuardError, match='CHANGED'): held.validate()
        with pytest.raises(g.DeploymentGuardError, match='CONFLICT'): g.guard_acquire()
    finally: held.close()


@pytest.mark.parametrize('value', ['', '1:2', '3:3', '-1:4', '3', '9:99999999999', '٣:٤', '99998:99999', 'true'])
def test_environment_is_not_admission(isolated_guard, value):
    with pytest.raises(guard.DeploymentGuardError): isolated_guard.guard_inherited({guard.GUARD_ENV: value})


def test_forged_fresh_descriptors_cannot_bypass_holder(isolated_guard):
    g = isolated_guard
    with g.held_deployment_guard():
        directory = g.guard_open_root()
        lock = os.open(g.GUARD_NAME, g.guard_flags(), dir_fd=directory)
        try:
            with pytest.raises(g.DeploymentGuardError, match='CONFLICT'):
                g.guard_inherited({g.GUARD_ENV: f'{directory}:{lock}'})
        finally: os.close(lock); os.close(directory)


def test_child_handoff_does_not_unlock_parent(isolated_guard, tmp_path):
    g = isolated_guard
    helper = tmp_path / 'helper.py'
    helper.write_text(local_guard_copy((ROOT / 'scripts/deployment_guard.py').read_text(), g.GUARD_ROOT))
    with g.held_deployment_guard() as held:
        result = subprocess.run([sys.executable, '-B', str(helper), '--check-inherited'],
                                env=held.environment(os.environ), pass_fds=(held.directory, held.lock),
                                capture_output=True, timeout=10)
        assert result.returncode == 0, result.stderr
        with pytest.raises(g.DeploymentGuardError, match='CONFLICT'): g.guard_acquire()
    with g.held_deployment_guard(): pass


@pytest.mark.parametrize('failure', [errno.ENOSPC, errno.EIO, errno.EACCES])
def test_fsync_failure_releases_without_deleting_lock(isolated_guard, monkeypatch, failure):
    g = isolated_guard
    def fail(fd): raise OSError(failure, 'synthetic error')
    with monkeypatch.context() as patch:
        patch.setattr(g.os, 'fsync', fail)
        with pytest.raises(g.DeploymentGuardError, match='UNAVAILABLE'): g.guard_acquire()
    with g.held_deployment_guard(): pass
    assert (Path(g.GUARD_ROOT) / g.GUARD_NAME).exists()


def test_exception_releases_guard(isolated_guard):
    g = isolated_guard
    with pytest.raises(KeyboardInterrupt):
        with g.held_deployment_guard(): raise KeyboardInterrupt
    with g.held_deployment_guard(): pass


def test_symlink_ancestor_and_directory_replacement_refused(isolated_guard, tmp_path, monkeypatch):
    g = isolated_guard
    real = tmp_path / 'real'; real.mkdir(mode=0o700)
    alias = tmp_path / 'alias'; alias.symlink_to(real, target_is_directory=True)
    with monkeypatch.context() as patch:
        patch.setattr(g, 'GUARD_ROOT', str(alias / 'guard'))
        with pytest.raises(g.DeploymentGuardError): g.guard_acquire()
        assert not (real / 'guard').exists()
    held = g.guard_acquire()
    try:
        root = Path(g.GUARD_ROOT); root.rename(tmp_path / 'moved-root')
        root.mkdir(mode=0o700)
        with pytest.raises(g.DeploymentGuardError, match='CHANGED'): held.validate()
    finally: held.close()


def test_killed_supervisor_does_not_admit_while_child_still_holds_fds(isolated_guard, tmp_path):
    g = isolated_guard
    helper = tmp_path / 'helper.py'
    helper.write_text(local_guard_copy((ROOT / 'scripts/deployment_guard.py').read_text(), g.GUARD_ROOT))
    ready, release, done = [tmp_path / name for name in ('ready','release','done')]
    script = tmp_path / 'child.sh'
    script.write_text(f"#!/bin/bash\ntouch '{ready}'\nfor ((i=0;i<750;i++)); do\n if [[ -f '{release}' ]]; then touch '{done}'; exit 0; fi\n /bin/sleep .02\ndone\nexit 99\n")
    parent = subprocess.Popen([sys.executable,'-B',str(helper),'--run-update',str(script)],
                              stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        wait_path(ready,parent)
        parent.kill(); parent.wait(timeout=5)
        with pytest.raises(g.DeploymentGuardError, match='CONFLICT'): g.guard_acquire()
    finally:
        release.touch(); parent.communicate(timeout=10)
    assert done.exists()
    with g.held_deployment_guard(): pass


def remote_program(fixture, tmp_path, metadata_pause=False):
    installed, source, _, _, env, run = fixture
    # Execute the real update.sh (temporary paths, external command doubles)
    # as the remote child, then run the real post-update metadata finalizer.
    update = run(prepare_only=True)
    program = tmp_path / 'remote.py'
    program.write_text(f'''import argparse,json,os,sys
from pathlib import Path
sys.path.insert(0,{str(ROOT)!r})
from scripts import deployment_guard as g,remote_lifecycle as life
from tests_placeholder import unused
'''.replace('from tests_placeholder import unused\n', '') + f'''
g.GUARD_ROOT={str(tmp_path / 'deployment-guard')!r}
g.GUARD_UID={os.getuid()};g.GUARD_GID={os.getgid()}
g.guard_require_root=lambda:None
life.os.geteuid=lambda:0
installed=Path({str(installed)!r});source=Path({str(source)!r})
def fetch(url,path):
    if '/releases/' in url:path.write_text(json.dumps(dict(tag_name='v1.7.0',draft=False,prerelease=False)))
    else:path.write_text(json.dumps(dict(sha='a'*40)))
life.extract_archive=lambda *args:source
# Use the actual FD-passing implementation, never a test "already locked" flag.
(source/'update.sh').write_bytes(Path({str(update)!r}).read_bytes())
original=life.write_install_info
def write(path,info):
    if path==installed and {metadata_pause!r}:
        Path({str(tmp_path / 'metadata-ready')!r}).touch()
        import time
        end=time.monotonic()+15
        while not Path({str(tmp_path / 'release')!r}).exists():
            if time.monotonic()>end:raise RuntimeError('test barrier')
            time.sleep(.02)
    return original(path,info)
life.write_install_info=write
args=argparse.Namespace(channel='stable',version=None,allow_downgrade=False,resolve_only=False)
try:life.run_lifecycle('update',args,installed,fetch)
except g.DeploymentGuardError as error:
    print(error.code,file=sys.stderr);sys.exit(error.exit_code)
''')
    return [sys.executable, '-B', str(program)]


def start_direct(fixture):
    _, source, _, _, env, run = fixture
    return subprocess.Popen(['bash', str(run(prepare_only=True))], cwd=source, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def start_remote(fixture, tmp_path, metadata_pause=False):
    _, source, _, _, env, _ = fixture
    return subprocess.Popen(remote_program(fixture, tmp_path, metadata_pause), cwd=source, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


@pytest.mark.parametrize('first_mode,second_mode', [('direct','direct'),('direct','remote'),('remote','direct'),('remote','remote')])
def test_concurrent_updaters_reject_before_any_deployment_side_effect(deployment, tmp_path, first_mode, second_mode):
    installed, source, _, events, env, _ = deployment
    (installed / 'VERSION').write_text('1.0.0\n')
    ready, release = tmp_path / 'pip-ready', tmp_path / 'release'
    pip = installed / 'venv/bin/pip'
    executable(pip, f'''echo "pip $*" >> "$TEST_EVENTS"
touch '{ready}'
for ((i=0;i<750;i++)); do [[ ! -f '{release}' ]] || exit 0; /bin/sleep .02; done
exit 99
''')
    first = start_direct(deployment) if first_mode == 'direct' else start_remote(deployment, tmp_path)
    try:
        wait_path(ready, first)
        before = {p.relative_to(installed): p.read_bytes() for p in installed.rglob('*') if p.is_file()}
        backups = list(tmp_path.glob('upgrade-backup-*')); log = events.read_bytes()
        second = start_direct(deployment) if second_mode == 'direct' else start_remote(deployment, tmp_path)
        out, error = second.communicate(timeout=10)
        assert second.returncode == 75, out + error
        assert 'DEPLOYMENT_GUARD_CONFLICT' in error
        assert 'backup' not in out.lower() and '备份' not in out
        assert events.read_bytes() == log and list(tmp_path.glob('upgrade-backup-*')) == backups
        assert {p.relative_to(installed): p.read_bytes() for p in installed.rglob('*') if p.is_file()} == before
        assert not (installed / 'state/auth.json').exists()  # No migration entered.
    finally:
        release.touch(); out, error = first.communicate(timeout=20)
    assert first.returncode == 0, out + error
    assert events.read_text().count('pip install') == 1
    assert 'systemctl restart clash-yaml-manager\n' in events.read_text()


def test_remote_metadata_window_remains_locked(deployment, tmp_path):
    installed, _, _, events, _, _ = deployment
    (installed / 'VERSION').write_text('1.0.0\n')
    first = start_remote(deployment, tmp_path, metadata_pause=True)
    try:
        wait_path(tmp_path / 'metadata-ready', first)
        assert 'systemctl restart clash-yaml-manager\n' in events.read_text()
        assert (installed / 'VERSION').read_text().strip() == '1.7.0'
        before = (installed / 'INSTALLATION.json').read_bytes()
        log = events.read_bytes()
        second = start_direct(deployment)
        out, error = second.communicate(timeout=10)
        assert second.returncode == 75, out + error
        assert (installed / 'INSTALLATION.json').read_bytes() == before and events.read_bytes() == log
    finally:
        (tmp_path / 'release').touch(); out, error = first.communicate(timeout=20)
    assert first.returncode == 0, out + error
    assert json.loads((installed / 'INSTALLATION.json').read_text())['commit'] == 'a'*40


@pytest.mark.parametrize('termination', ['normal', 'kill'])
def test_process_exit_releases_persistent_inode(isolated_guard, tmp_path, termination):
    g = isolated_guard
    helper = tmp_path / 'guard.py'
    helper.write_text(local_guard_copy((ROOT / 'scripts/deployment_guard.py').read_text(), g.GUARD_ROOT))
    program = tmp_path / 'holder.py'
    program.write_text("import guard,time\nwith guard.held_deployment_guard():\n print('held',flush=True)\n time.sleep(0.2 if __import__('sys').argv[1]=='normal' else 20)\n")
    child = subprocess.Popen([sys.executable, '-B', str(program), termination], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'held'
        inode = (Path(g.GUARD_ROOT) / g.GUARD_NAME).stat().st_ino
        with pytest.raises(g.DeploymentGuardError, match='CONFLICT'): g.guard_acquire()
        if termination == 'kill': child.kill()
        child.wait(timeout=5)
        with g.held_deployment_guard(): assert (Path(g.GUARD_ROOT) / g.GUARD_NAME).stat().st_ino == inode
    finally:
        if child.poll() is None: child.kill(); child.wait()
        child.stdout.close()


def test_default_off_script_body_and_legacy_cp_a_order_unchanged():
    old = subprocess.run(['git','show',START+':update.sh'],cwd=ROOT,capture_output=True,text=True,check=True).stdout
    current = (ROOT / 'update.sh').read_text()
    insertion = current[current.index('# Admission precedes'):current.index('source "${CURRENT_DIR}/scripts/deploy-common.sh"')]
    assert current.replace(insertion, '', 1) == old
    assert 'backup_create' not in current and 'backup_collect' not in current


@pytest.mark.parametrize('pip_failure', ['0','1'])
def test_default_off_end_to_end_matches_start_revision(tmp_path, monkeypatch, pip_failure):
    # Independent synthetic instances, same auth identity/password hash. Compare
    # observable commands, legacy backup contents, env/runtime/unit preservation.
    from test_deployment import deployment as fixture
    from core.security import AuthStore
    old = subprocess.run(['git','show',START+':update.sh'],cwd=ROOT,capture_output=True,text=True,check=True).stdout
    instances=[]
    for name in ('old','new'):
        parent=tmp_path/name;parent.mkdir(mode=0o700)
        data=fixture.__wrapped__(parent)
        installed,_,_,_,env,_=data
        env['TEST_PIP_FAIL']=pip_failure
        instances.append(data)
    auth=AuthStore(instances[0][0]/'state');auth.initialize({'APP_PASSWORD':'test'})
    state=(instances[0][0]/'state/auth.json').read_bytes()
    shutil.copytree(instances[0][0]/'state', instances[1][0]/'state', dirs_exist_ok=True)
    for data in instances:
        (data[0]/'state').mkdir(exist_ok=True);(data[0]/'state/auth.json').write_bytes(state)
        (data[0]/'.env').write_text('APP_PORT=8899\nSECRET_KEY=old-key\n')
    def record(data, script):
        installed,source,service,events,env,run=data
        result=run(script_text=script)
        parent=installed.parent
        backup=next(parent.glob('upgrade-backup-*'))
        def normalize(text):
            return re.sub(r'\.health-units\.[A-Za-z0-9]+', '.health-units.STAGE',
                          text.replace(str(backup),'BACKUP').replace(str(parent),'FIXTURE'))
        def tree(directory):
            return {str(p.relative_to(directory)):(normalize(p.read_text()),stat.S_IMODE(p.stat().st_mode))
                    for p in directory.rglob('*') if p.is_file() and '__pycache__' not in p.parts
                    and p.name != 'deployment_guard.py'}
        return result.returncode,normalize(events.read_text()),tree(backup),normalize(service.read_text()),(installed/'.env').read_bytes()
    baseline=record(instances[0],old)
    actual=record(instances[1],None)
    assert actual==baseline
