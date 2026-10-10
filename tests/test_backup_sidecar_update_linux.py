"""Root native pipeline on /tmp only; systemctl/network/account command doubles.

No real services, accounts, /opt, guard path, backups or VPS are accessed.
"""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time

import pytest

from conftest import ROOT

pytestmark = pytest.mark.skipif(not sys.platform.startswith('linux'), reason='Linux root sidecar integration gate')


def native_fixture(parent):
    from test_deployment import deployment, executable
    from core.security import AuthStore
    data = deployment.__wrapped__(parent)
    installed, source, old_service, events, env, execute = data
    # Only trusted test-copy path relocation; root checks/FD/flock stay real.
    helper = source / 'scripts/deployment_guard.py'
    helper.write_text((ROOT / 'scripts/deployment_guard.py').read_text().replace(
        "GUARD_ROOT = '/var/lib/clash-yaml-manager-deployment'", f'GUARD_ROOT = {str(parent / "deployment-guard")!r}'))
    adapter = source / 'scripts/backup_sidecar_update.py'
    adapter.write_text(adapter.read_text().replace("SIDECAR_ROOT = '/root/clash-yaml-manager-sidecars'", f'SIDECAR_ROOT = {str(parent / "sidecars")!r}')
                       .replace("CGROUP_ROOT = '/sys/fs/cgroup'", f'CGROUP_ROOT = {str(parent / "cgroup")!r}'))
    cg = parent / 'cgroup'; cg.mkdir(mode=0o700)
    (cg / 'system.slice').mkdir(mode=0o700)
    (cg / 'cgroup.controllers').write_text('cpu memory pids\n')
    commands = parent / 'commands'
    (commands / 'ps').unlink(missing_ok=True)
    executable(commands / 'ps', "printf '1 0 synthetic-init\\n'\n")
    # Track real control-flow transitions in an isolated synthetic systemd model.
    (commands / 'systemctl').write_text('#!' + sys.executable + '\n' + r'''
import json,os,sys
from pathlib import Path
args=sys.argv[1:];events=Path(os.environ['TEST_EVENTS'])
with events.open('a') as out:out.write('systemctl '+' '.join(args)+'\n')
statefile=events.with_suffix('.states')
states=json.loads(statefile.read_text()) if statefile.exists() else {}
command=args[0]
rest=[a for a in args[1:] if not a.startswith('--')]
unit=rest[0] if rest else ''
if unit and '.' not in unit:unit+='.service'
if command in ('stop','start','restart'):
    states[unit]='inactive' if command=='stop' else 'active'
    statefile.write_text(json.dumps(states))
elif command=='enable' and '--now' in args:
    states[unit]='active';statefile.write_text(json.dumps(states))
elif command=='show':
    active=states.get(unit,'active');load='loaded'
    fault=os.environ.get('TEST_QUIET_FAULT')
    if unit=='clash-yaml-manager.service' and fault:
        if fault=='missing':load='not-found'
        else:active=fault
    values=dict(LoadState=load,ActiveState=active,SubState='dead',Job='')
    if unit.endswith('.service'):
        values.update(MainPID='0',ControlPID='0',ControlGroup='',Slice='system.slice',KillMode='control-group',Result='success')
    print('\n'.join(k+'='+v for k,v in values.items()))
elif command=='list-jobs':pass
elif command=='is-active':
    active=states.get(unit,'active')
    if '--quiet' not in args:print(active)
    sys.exit(0 if active=='active' else 3)
''')
    (commands / 'systemctl').chmod(0o700)
    service = parent / 'clash-yaml-manager.service'
    service.write_text(old_service.read_text())
    for suffix in ('refresh.service', 'refresh.timer', 'health.service', 'health.timer'):
        (parent / ('clash-yaml-manager-' + suffix)).write_text('[Unit]\n[Service]\n[Timer]\n')
    installed.joinpath('VERSION').write_text('1.6.0\n')
    AuthStore(installed / 'state').initialize({'APP_PASSWORD':'test'})
    (installed / '.env').chmod(0o600)
    (installed / '.service-account').write_text('clashyaml:12345:12345\n')
    (installed / '.service-account').chmod(0o600)
    Path(env['TEST_ACCOUNT']).write_text('clashyaml:x:12345:12345:Clash YAML Manager service:/nonexistent:/usr/sbin/nologin\n')
    for item in (installed / 'state').rglob('*'):
        os.chown(item,12345,12345)
    os.chown(installed / 'state',12345,12345)
    env.update(CLASH_BACKUP_SIDECAR_MODE='STRICT',CLASH_BACKUP_EXTERNAL_WRITERS_QUIET='YES',
               PYTHONDONTWRITEBYTECODE='1')
    script = execute(prepare_only=True)
    script.write_text(script.read_text().replace(f'SERVICE_FILE="{old_service}"', f'SERVICE_FILE="{service}"')
                      .replace('if false; then', 'if [[ "${EUID}" -ne 0 ]]; then', 1))
    return installed,source,service,events,env,script


def reports(result):
    values=[]
    for line in (result.stdout+'\n'+result.stderr).splitlines():
        if line.startswith('{'):
            item=json.loads(line)
            if 'SIDECAR_STATUS' in item:values.append(item)
    return values


def execute_native(data):
    installed,source,_,_,env,script=data
    return subprocess.run(['bash',str(script)],cwd=source,env=env,capture_output=True,text=True,timeout=45)


def native_case(case):
    from test_backup_collect import frozen
    from test_deployment import executable
    from test_deployment_guard import wait_path
    assert os.geteuid()==os.getegid()==0
    with tempfile.TemporaryDirectory(prefix='cym-sidecar-native-',dir='/tmp') as temporary:
        parent=Path(temporary);data=native_fixture(parent)
        installed,source,service,events,env,script=data
        old_app=(installed/'app.py').read_bytes();old_env=(installed/'.env').read_bytes()
        if case.startswith('competition-'):
            mode=case.split('-',1)[1];env['CLASH_BACKUP_SIDECAR_MODE']=mode
            ready=parent/'pip-ready';release=parent/'release'
            executable(installed/'venv/bin/pip',f'''echo "pip $*" >> "$TEST_EVENTS"
touch '{ready}'
for ((i=0;i<750;i++)); do [[ ! -f '{release}' ]] || exit 0; /bin/sleep .02; done
exit 99
''')
            first=subprocess.Popen(['bash',str(script)],cwd=source,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                wait_path(ready,first)
                before=frozen(installed);log=events.read_bytes();backups=list(parent.glob('upgrade-backup-*'))
                for second_mode in ('OFF','OPTIONAL','STRICT'):
                    second_env=dict(env,CLASH_BACKUP_SIDECAR_MODE=second_mode)
                    # Real remote parent/current shared guard, refused before its
                    # fetch/extract doubles or child/new metadata can run.
                    program=parent/'contender.py'
                    program.write_text(f'''import argparse,sys
sys.path.insert(0,{str(ROOT)!r})
from scripts import deployment_guard as g,remote_lifecycle as life
from pathlib import Path
g.GUARD_ROOT={str(parent/'deployment-guard')!r}
args=argparse.Namespace(channel='main',version=None,allow_downgrade=False,resolve_only=False)
def forbidden(*args):raise AssertionError('REMOTE_ADMITTED')
try:life.run_lifecycle('update',args,Path({str(installed)!r}),forbidden,forbidden)
except g.DeploymentGuardError as error:sys.exit(error.exit_code)
''')
                    result=subprocess.run([sys.executable,'-B',str(program)],cwd=source,env=second_env,capture_output=True,text=True,timeout=10)
                    assert result.returncode==75
                    assert frozen(installed)==before and events.read_bytes()==log and list(parent.glob('upgrade-backup-*'))==backups
            finally:
                release.touch();out,error=first.communicate(timeout=45)
            assert first.returncode==0,(out,error)
            print(json.dumps(dict(case=case,root=True,guard_competition=True,all_modes_same_lock=True,production=False)))
            return
        if case=='off':env.pop('CLASH_BACKUP_SIDECAR_MODE')
        if case.startswith('optional'):env['CLASH_BACKUP_SIDECAR_MODE']='OPTIONAL'
        if case.endswith('ordinary-failure'):
            # Valid orphan cache grammar; no registry pointer or runtime schema
            # is changed. Legacy retains all bytes, subset resource gate refuses.
            cache=installed/'state/fixed_subscriptions'/('a'*32)/('b'*32)/'sources'/('c'*32)
            cache.mkdir(parents=True,mode=0o700)
            for directory in [cache,*cache.parents]:
                if directory==installed/'state':break
                directory.chmod(0o700)
            (cache/'payload.bin').write_bytes(b'x'*(17*1024*1024))
            (cache/'payload.bin').chmod(0o600)
        if case=='quiet-missing':env['TEST_QUIET_FAULT']='missing'
        if case=='manual-conflict':env['CLASH_BACKUP_EXTERNAL_WRITERS_QUIET']='NO'
        if case=='mixed-owner-refusal':os.chown(installed/'state/auth.json',12346,12346)
        # Faults are trusted test-copy injections, absent from production adapter.
        if case in ('catalog-anchor','published-uncertain','enospc','crash'):
            adapter=source/'scripts/backup_sidecar_update.py'
            injection=''
            if case=='catalog-anchor':
                injection=r'''
_catalog_execute=catalog.execute
def _fault_catalog(action,*args,**kwargs):
    result=_catalog_execute(action,*args,**kwargs)
    if action=='register' and result['registration_status']=='REGISTERED':
        from pathlib import Path
        record=Path(args[0])/(result['snapshot_id']+'.json')
        value=catalog.load_record(record.read_bytes());value['manifest_sha256']='0'*64
        record.write_bytes(catalog.canonical_record(value))
    return result
catalog.execute=_fault_catalog
'''
            elif case=='published-uncertain':
                injection=r'''
_verify_stage=writer.Writer.verify_stage
def _fault_verify(self,path):
    if self.published:raise AuditFault('VERIFICATION_FAILED')
    return _verify_stage(self,path)
writer.Writer.verify_stage=_fault_verify
'''
            elif case=='enospc':
                injection=r'''
_write_all=writer.Writer.write_all
def _fault_write(self,*args):
    if type(self) is writer.Writer:raise OSError(errno.ENOSPC,'synthetic disk full')
    return _write_all(self,*args)
writer.Writer.write_all=_fault_write
'''
                env['CLASH_BACKUP_SIDECAR_MODE']='OPTIONAL'
            elif case=='crash':
                injection=f'''
_writer_copy=writer.Writer.copy
def _fault_copy(self,*args):
    _writer_copy(self,*args)
    if type(self) is not writer.Writer:return
    from pathlib import Path
    Path({str(parent/'writer-ready')!r}).write_text(str(os.getpid()))
    while True:time.sleep(.02)
writer.Writer.copy=_fault_copy
'''
            adapter.write_text(adapter.read_text().replace("if __name__ == '__main__':\n    raise SystemExit(main())",injection+"\nif __name__ == '__main__':\n    raise SystemExit(main())"))
        if case=='crash':
            child=subprocess.Popen(['bash',str(script)],cwd=source,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                wait_path(parent/'writer-ready',child)
                os.kill(int((parent/'writer-ready').read_text()),9)
                out,error=child.communicate(timeout=15)
            finally:
                if child.poll() is None:child.kill();child.communicate()
            assert child.returncode!=0 and 'PUBLICATION_STATUS=UNCERTAIN' in error
            assert list((parent/'sidecars').glob('operations/*/.backup-create-*'))
            assert (installed/'app.py').read_bytes()==old_app and (installed/'.env').read_bytes()==old_env
            assert not list((parent/'sidecars/catalog').glob('*.json'))
            from scripts import deployment_guard as guard
            guard.GUARD_ROOT=str(parent/'deployment-guard')
            with guard.held_deployment_guard():pass
            print(json.dumps(dict(case=case,root=True,crash_preserved=True,legacy_retained=True,production=False)))
            return
        enosys=None
        if case=='enosys':
            from test_backup_create_linux import SECCOMP_CHILD
            old_arguments=sys.argv
            sys.argv=['native-seccomp',str(parent)]
            scope={}
            try:exec(SECCOMP_CHILD.split("source_before=tree_state(parent/'source')")[0],scope)
            finally:sys.argv=old_arguments
            enosys=scope['diagnostic']
        if case=='remote-success':
            from core.version import normalize_tag, read_version
            release_tag=normalize_tag(read_version(source/'VERSION'))
            (source/'update.sh').write_bytes(script.read_bytes())
            ready=parent/'metadata-ready';release=parent/'metadata-release'
            program=parent/'remote.py'
            program.write_text(f'''import argparse,json,sys,time
from pathlib import Path
sys.path.insert(0,{str(ROOT)!r})
from scripts import deployment_guard as g,remote_lifecycle as life
g.GUARD_ROOT={str(parent/'deployment-guard')!r}
source=Path({str(source)!r});installed=Path({str(installed)!r})
def fetch(url,path):
    path.write_text(json.dumps(dict(tag_name={release_tag!r},draft=False,prerelease=False) if '/releases/' in url else dict(sha='a'*40)))
life.extract_archive=lambda *args:source
original=life.write_install_info
def finalize(path,info):
    if path==installed:
        Path({str(ready)!r}).touch()
        deadline=time.monotonic()+30
        while not Path({str(release)!r}).exists():
            if time.monotonic()>deadline:raise AssertionError('METADATA_BARRIER_TIMEOUT')
            time.sleep(.02)
    return original(path,info)
life.write_install_info=finalize
args=argparse.Namespace(channel='stable',version=None,allow_downgrade=False,resolve_only=False)
life.run_lifecycle('update',args,installed,fetch)
''')
            child=subprocess.Popen([sys.executable,'-B',str(program)],cwd=source,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                wait_path(ready,child)
                before=frozen(installed);log=events.read_bytes()
                contender=execute_native(data)
                assert contender.returncode==75
                assert frozen(installed)==before and events.read_bytes()==log
            finally:
                release.touch();out,error=child.communicate(timeout=45)
            result=subprocess.CompletedProcess([],child.returncode,out,error)
        else:
            result=execute_native(data)
        evidence=reports(result)
        if case=='manual-conflict':
            assert result.returncode==1
            assert 'EXTERNAL_WRITERS_QUIET_REQUIRED' in result.stderr
            assert not list(parent.glob('upgrade-backup-*'))
            assert not (parent/'sidecars').exists() and not events.exists()
            assert (installed/'app.py').read_bytes()==old_app and (installed/'.env').read_bytes()==old_env
            print(json.dumps(dict(case=case,root=True,early_admission=True,production=False)))
            return
        successful=case in ('off','optional-success','strict-success','optional-ordinary-failure','remote-success')
        assert (result.returncode==0)==successful,(case,result.returncode,result.stdout,result.stderr)
        legacy=list(parent.glob('upgrade-backup-*'));assert len(legacy)==1
        assert (legacy[0]/'.env').read_bytes()==old_env and (legacy[0]/'app.py').read_bytes()==old_app
        assert (legacy[0]/'venv/bin/pip').exists()
        assert stat.S_IMODE(legacy[0].stat().st_mode)==0o700
        if case=='off':
            assert not evidence and not (parent/'sidecars').exists()
        else:
            assert evidence and evidence[-1]['restore_proven'] is False
            report=evidence[-1]
            assert report['LEGACY_BACKUP_STATUS']=='COMPLETE_BY_UPDATER_HANDOFF'
            if case in ('optional-success','strict-success','remote-success'):
                assert report['SIDECAR_STATUS']==report['CATALOG_STATUS']=='TRUSTED_SCOPE_VERIFIED'
                snapshot=parent/'sidecars/operations'/report['operation_id']/'snapshot'
                ledger=json.loads((snapshot/'SOURCE_OWNERSHIP.json').read_bytes())
                auth=next(i for i in ledger['original_entries'] if i['path']=='state/auth.json')
                assert auth['original']['uid']==auth['original']['gid']==12345
                assert (legacy[0]/'state/auth.json').stat().st_uid==12345
                assert snapshot.stat().st_uid==0 and stat.S_IMODE(snapshot.stat().st_mode)==0o700
                assert report['quiet_evidence']['units']['clash-yaml-manager.service']['classification']=='INACTIVE'
                assert (installed/'defaults/default.yaml').read_bytes()==(legacy[0]/'defaults/default.yaml').read_bytes()
                if case=='remote-success':
                    identity=json.loads((installed/'INSTALLATION.json').read_bytes())
                    assert identity['commit']=='a'*40 and identity['channel']=='stable'
                    record=json.loads((parent/'sidecars/catalog'/(report['snapshot_id']+'.json')).read_bytes())
                    assert record['operator_claims']['target_identity']==identity
            if not successful:
                assert report['UPGRADE_STATUS']=='BLOCKED'
                assert (installed/'app.py').read_bytes()==old_app and (installed/'.env').read_bytes()==old_env
                assert 'systemctl restart clash-yaml-manager\n' not in events.read_text()
            if case=='published-uncertain':
                assert report['PUBLICATION_STATUS']['writer']=='PUBLISHED'
                assert list((parent/'sidecars').glob('operations/*/snapshot'))
                assert not list((parent/'sidecars/catalog').glob('*.json'))
            if case=='catalog-anchor':
                assert 'MANIFEST_DIGEST_MISMATCH' in report['validation_codes']
                assert list((parent/'sidecars/catalog').glob('*.json'))
            if case=='enospc':assert 'READ_FAILED' in report['validation_codes']
            if case=='enosys':
                assert enosys['raw_errno']==38 and enosys['filter_intercepted']
                assert 'NO_REPLACE_UNAVAILABLE' in report['validation_codes']
                assert report['PUBLICATION_STATUS']['collector']=='NOT_PUBLISHED'
        print(json.dumps(dict(case=case,root=True,real_pipeline=case in ('optional-success','strict-success'),
                             legacy_retained=True,upgrade_success=successful,kernel_enosys=enosys is not None,production=False)))


@pytest.mark.parametrize('case', ['off','optional-success','strict-success','optional-ordinary-failure',
    'strict-ordinary-failure','quiet-missing','manual-conflict','mixed-owner-refusal',
    'catalog-anchor','published-uncertain','enospc','enosys','crash','remote-success',
    'competition-OFF','competition-OPTIONAL','competition-STRICT'])
def test_linux_root_updater_sidecar(case,capsys):
    code=f"import sys;sys.path.insert(0,{str(ROOT/'tests')!r});from test_backup_sidecar_update_linux import native_case;native_case(sys.argv[1])"
    command=[sys.executable,'-B','-c',code,case]
    if os.geteuid()!=0:command=['sudo','-n',*command]
    result=subprocess.run(command,cwd=ROOT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,timeout=90)
    assert result.returncode==0,'ROOT_SIDECAR_NATIVE_NOT_PROVEN: '+result.stderr
    proof=json.loads(result.stdout.splitlines()[-1]);assert proof['root'] and proof['production'] is False
    with capsys.disabled():print('SIDECAR_LINUX_ROOT: PASS '+json.dumps(proof,sort_keys=True),flush=True)
