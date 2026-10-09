"""Linux syscall/root proof on temporary synthetic fixtures only."""
import errno
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from conftest import ROOT
from scripts import backup_catalog as catalog
from scripts import backup_create as writer
from scripts import backup_verify as verifier
from test_backup_catalog import fixture, register, verify, enrolled, freeze, OPERATION
from test_backup_create_linux import SECCOMP_CHILD

pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux catalog native gate')


def emit(capsys,label,proof):
    with capsys.disabled():print(label+': PASS '+json.dumps(proof,sort_keys=True),flush=True)


def test_linux_catalog_publication_real_fsync_and_inode(fixture,monkeypatch,capsys):
    native=writer.publication_function();actual=os.fsync;synced=[];identities=[]
    def sync(fd):
        identity=writer.identity(os.fstat(fd));actual(fd);synced.append(identity)
    def publish(fd,stage,name):
        before=writer.identity(os.stat(stage,dir_fd=fd,follow_symlinks=False))
        assert before in synced and before[2]==stat.S_IFREG
        native(fd,stage,name)
        after=writer.identity(os.stat(name,dir_fd=fd,follow_symlinks=False))
        assert before==after;identities.append(after)
    monkeypatch.setattr(os,'fsync',sync);monkeypatch.setattr(writer,'publication_function',lambda:publish)
    sid=enrolled(fixture)
    assert len(identities)==1 and writer.identity(fixture['catalog'].stat()) in synced
    assert verify(fixture,sid)['verification_status']=='TRUSTED_SCOPE_VERIFIED'
    emit(capsys,'CATALOG_LINUX_PUBLICATION',dict(no_replace=True,file_fsync=True,directory_fsync=True,inode_preserved=True,real_verifier=True,restore_proven=False))


def test_linux_catalog_other_process_collision_and_kernel_nofollow(fixture,monkeypatch,capsys):
    native=writer.publication_function();before=[]
    child="""import os,sys
fd=int(sys.argv[1]);path=sys.argv[2]
f=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
os.write(f,b'external-record');os.fsync(f);os.close(f);os.fsync(fd)
"""
    def race(fd,stage,name):
        subprocess.run([sys.executable,'-c',child,str(fd),name],pass_fds=(fd,),check=True,timeout=15,capture_output=True)
        before.append((name,verifier.fingerprint(os.stat(name,dir_fd=fd,follow_symlinks=False))))
        native(fd,stage,name)
    monkeypatch.setattr(writer,'publication_function',lambda:race)
    result=register(fixture);assert result['registration_status']=='NOT_REGISTERED' and 'DESTINATION_EXISTS' in result['validation_codes']
    assert result['cleanup_status']=='CLEANED'
    name,info=before[0];path=fixture['catalog']/name
    assert verifier.fingerprint(path.stat())==info and path.read_bytes()==b'external-record'
    link=fixture['catalog']/'file-link';link.symlink_to(name)
    with catalog.root_directory(fixture['catalog']) as (fd,_):
        with pytest.raises(OSError) as error:os.open('file-link',catalog.flags(),dir_fd=fd)
        assert error.value.errno==errno.ELOOP
    emit(capsys,'CATALOG_LINUX_COLLISION_NOFOLLOW',dict(other_process=True,no_overwrite=True,own_stage_cleaned=True,kernel_nofollow=True,restore_proven=False))


def test_linux_catalog_enosys_no_fallback(fixture,capsys):
    # Reuse the unchanged, already-audited real filter/probes/tripwires prefix.
    prefix=SECCOMP_CHILD.split("source_before=tree_state(parent/'source')")[0]
    tail=r'''
from scripts import backup_catalog as catalog
snapshot_before=tree_state(parent/'snapshot')
result=catalog.execute('register',parent/'catalog',snapshot=parent/'snapshot',representation=parent/'source',
    expected_digest=sys.argv[2],operation_id='a'*32,profile='manifest-v1-declared-scope',completed_offline=True)
require(result['registration_status']=='NOT_REGISTERED' and result['publication_status']=='NOT_PUBLISHED','CATALOG_PUBLISHED')
require('NO_REPLACE_UNAVAILABLE' in result['validation_codes'],'CATALOG_REFUSAL_NOT_PROVEN')
require(result['cleanup_status']=='CLEANED' and not list((parent/'catalog').iterdir()),'CATALOG_RESIDUE')
require(tree_state(parent/'snapshot')==snapshot_before,'SNAPSHOT_CHANGED')
require(verifier.fingerprint((parent/'raw-target').stat())==target_before,'EXTERNAL_TARGET_CHANGED')
emit(dict(result='PASS',kernel_errno='ENOSYS',raw_errno=diagnostic['raw_errno'],wrapper_errno=diagnostic['wrapper_errno'],
    real_catalog=True,no_fallback=True,tripwires_proven=len(ordinary_numbers),own_stage_cleaned=True,
    snapshot_unchanged=True,restore_proven=False))
'''
    before=freeze(fixture['snapshot'])
    result=subprocess.run([sys.executable,'-c',prefix+tail,str(fixture['catalog'].parent),fixture['digest']],
        cwd=ROOT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,timeout=30)
    assert len(result.stdout)<=8192
    proofs=[json.loads(line) for line in result.stdout.splitlines()]
    assert result.returncode==0,'CATALOG_ENOSYS_GATE_NOT_PROVEN'
    assert len(proofs)==2 and proofs[0]['raw_errno']==errno.ENOSYS and proofs[0]['filter_intercepted'] is True
    assert proofs[1]['no_fallback'] and proofs[1]['real_catalog'] and proofs[1]['own_stage_cleaned']
    assert freeze(fixture['snapshot'])==before and not list(fixture['catalog'].iterdir())
    emit(capsys,'CATALOG_LINUX_ENOSYS',proofs[1])


def test_linux_root_catalog_blocks_service_writer(fixture,capsys):
    code=r'''import json,os,errno,sys
from pathlib import Path
from scripts import backup_catalog as c
parent=Path(sys.argv[1]);digest=sys.argv[2];uid=int(sys.argv[3]);gid=int(sys.argv[4])
try:
    for p in [parent,*parent.rglob('*')]:os.chown(p,0,0)
    from scripts import backup_create as w
    snapshot=parent/'root-snapshot'
    created=w.create(parent/'source',snapshot,'UPDATER_SNAPSHOT')
    assert created['creation_status']=='CREATED'
    independent_digest=created['MANIFEST_SHA256']  # Independent Writer handoff, not read from snapshot.
    result=c.execute('register',parent/'catalog',snapshot=snapshot,representation=parent/'source',
        expected_digest=independent_digest,operation_id='a'*32,profile='manifest-v1-declared-scope',completed_offline=True)
    assert result['registration_status']=='REGISTERED' and result['protection_model']=='ROOT_PRIVATE'
    sid=result['snapshot_id'];record=parent/'catalog'/(sid+'.json')
    assert record.stat().st_uid==record.stat().st_gid==0
    import stat
    assert stat.S_IMODE(record.stat().st_mode)==0o600 and stat.S_IMODE((parent/'catalog').stat().st_mode)==0o700
    assert c.execute('verify',parent/'catalog',snapshot=snapshot,snapshot_id=sid)['verification_status']=='TRUSTED_SCOPE_VERIFIED'
    with c.root_directory(parent/'catalog') as (fd,_):
        pid=os.fork()
        if pid==0:
            os.setgroups([]);os.setgid(12345);os.setuid(12345)
            refused=0
            for name,flags in [(sid+'.json',os.O_RDONLY|os.O_NOFOLLOW),('service-created',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW)]:
                try:opened=os.open(name,flags,0o600,dir_fd=fd)
                except OSError as error:
                    if error.errno==errno.EACCES:refused+=1
                else:os.close(opened)
            os._exit(0 if refused==2 else 99)
        _,status=os.waitpid(pid,0);assert os.WIFEXITED(status) and os.WEXITSTATUS(status)==0
    os.chown(record,12345,12345)
    bad=c.execute('verify',parent/'catalog',snapshot=snapshot,snapshot_id=sid)
    assert bad['verification_status']=='NOT_VERIFIED' and 'UNSAFE_CATALOG_OWNERSHIP_OR_PERMISSION' in bad['validation_codes']
    os.chown(record,0,0);os.chown(parent/'catalog',12345,12345)
    bad=c.execute('inspect',parent/'catalog');assert 'UNSAFE_PRIVATE_ROOT' in bad['validation_codes']
    print(json.dumps(dict(result='PASS',root_owned=True,private_modes=True,service_read_refused=True,service_write_refused=True,
        foreign_record_owner_refused=True,foreign_catalog_owner_refused=True,real_verifier=True,restore_proven=False)))
finally:
    for p in [parent,*parent.rglob('*')]:os.chown(p,uid,gid)
'''
    result=subprocess.run(['sudo','-n',sys.executable,'-B','-c',code,str(fixture['catalog'].parent),fixture['digest'],str(os.geteuid()),str(os.getegid())],
        cwd=ROOT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,timeout=30)
    assert result.returncode==0,'CATALOG_ROOT_GATE_NOT_PROVEN'
    proof=json.loads(result.stdout);assert proof['root_owned'] and proof['service_write_refused'] and proof['real_verifier']
    emit(capsys,'CATALOG_LINUX_ROOT',proof)
