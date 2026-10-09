"""Real Linux flock, root ownership and unprivileged refusal on /tmp only."""
import json
import os
import subprocess
import sys

import pytest

from conftest import ROOT

pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux root deployment guard gate')


def test_linux_root_private_guard_and_inherited_flock(capsys):
    code = r'''
import errno,json,os,stat,sys,tempfile,subprocess
from pathlib import Path
from scripts import deployment_guard as g
with tempfile.TemporaryDirectory(prefix='cym-guard-native-',dir='/tmp') as temporary:
    parent=Path(temporary);g.GUARD_ROOT=str(parent/'guard')
    assert os.geteuid()==0 and g.GUARD_UID==g.GUARD_GID==0
    with g.held_deployment_guard() as held:
        root=Path(g.GUARD_ROOT);lock=root/g.GUARD_NAME
        assert root.stat().st_uid==root.stat().st_gid==lock.stat().st_uid==lock.stat().st_gid==0
        assert stat.S_IMODE(root.stat().st_mode)==0o700 and stat.S_IMODE(lock.stat().st_mode)==0o600
        inode=lock.stat().st_ino
        child="from scripts import deployment_guard as g;import sys;g.GUARD_ROOT=sys.argv[1];raise SystemExit(g.deployment_guard_main(['--check-inherited']))"
        ok=subprocess.run([sys.executable,'-B','-c',child,g.GUARD_ROOT],pass_fds=(held.directory,held.lock),env=held.environment(os.environ),capture_output=True,timeout=10)
        assert ok.returncode==0
        conflict="from scripts import deployment_guard as g;import sys;g.GUARD_ROOT=sys.argv[1];\ntry:g.guard_acquire()\nexcept g.DeploymentGuardError as e:sys.exit(e.exit_code)\nsys.exit(99)"
        other=subprocess.run([sys.executable,'-B','-c',conflict,g.GUARD_ROOT],capture_output=True,timeout=10)
        assert other.returncode==75
        pid=os.fork()
        if pid==0:
            os.setgroups([]);os.setgid(12345);os.setuid(12345)
            denied=0
            for name,flags in [('update.lock',os.O_RDONLY|os.O_NOFOLLOW),('new',os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW)]:
                try:fd=os.open(name,flags,0o600,dir_fd=held.directory)
                except OSError as e:
                    if e.errno==errno.EACCES:denied+=1
                else:os.close(fd)
            os._exit(0 if denied==2 else 99)
        _,status=os.waitpid(pid,0);assert os.WIFEXITED(status) and os.WEXITSTATUS(status)==0
        # Kernel no-follow, without relying only on a stat predicate.
        os.symlink('update.lock',root/'symlink')
        try:os.open('symlink',g.guard_flags(),dir_fd=held.directory)
        except OSError as e:assert e.errno==errno.ELOOP
        else:raise AssertionError('nofollow not enforced')
    with g.held_deployment_guard():assert lock.stat().st_ino==inode
    os.chown(lock,12345,12345)
    try:g.guard_acquire()
    except g.DeploymentGuardError:pass
    else:raise AssertionError('foreign owner accepted')
    os.chown(lock,0,0)
    os.chown(root,12345,12345)
    try:g.guard_acquire()
    except g.DeploymentGuardError:pass
    else:raise AssertionError('foreign root accepted')
    os.chown(root,0,0)
    print(json.dumps(dict(root_owned=True,private_modes=True,kernel_nofollow=True,real_flock=True,
        other_process_conflict=True,inherited_fd=True,parent_still_locked=True,persistent_inode=True,
        service_read_refused=True,service_write_refused=True,foreign_owner_refused=True,production_accessed=False)))
'''
    command = [sys.executable, '-B', '-c', code]
    if os.geteuid() != 0:
        command = ['sudo', '-n', *command]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    assert result.returncode == 0, 'DEPLOYMENT_GUARD_LINUX_ROOT_GATE_NOT_PROVEN: ' + result.stderr
    proof = json.loads(result.stdout)
    assert proof['real_flock'] and proof['service_write_refused'] and not proof['production_accessed']
    with capsys.disabled():
        print('DEPLOYMENT_GUARD_LINUX_ROOT: PASS ' + json.dumps(proof, sort_keys=True), flush=True)
