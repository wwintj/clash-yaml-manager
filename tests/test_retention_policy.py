"""Retention on real disposable files; no live data, deployment or restore."""
import errno
import itertools
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest

from conftest import LINK, ROOT, post
from core import retention
from core.state import read_json
from core.temporary_links import TemporaryLinks
from test_fixed_views import create


@pytest.mark.parametrize('values', itertools.product(('timed', 'keep'), repeat=3))
def test_policy_config_independence(values):
    assert retention.policies_from_env(dict(zip(retention.POLICY_KEYS, values))) == values
    assert retention.policies_from_env({}) == ('timed',)*3


@pytest.mark.parametrize('key', retention.POLICY_KEYS)
@pytest.mark.parametrize('value', ['', ' keep', 'keep ', 'KEEP', 'forever', '0', 'NaN', 'keep\n', 'PRIVATE_VALUE'])
def test_invalid_policy_no_echo(key, value):
    with pytest.raises(ValueError, match='^Retention policies must be timed or keep.$') as error:
        retention.policies_from_env({key:value})
    assert str(error.value) == 'Retention policies must be timed or keep.'


@pytest.mark.parametrize('key', (*retention.POLICY_KEYS, 'TEMP_LINK_LIFETIME_HOURS'))
def test_invalid_startup_before_existing_file_cleanup(tmp_path, key):
    (tmp_path/'app.py').write_bytes((ROOT/'app.py').read_bytes())
    before={}
    for name in ('uploads', 'outputs', 'backups'):
        root=tmp_path/name;root.mkdir(mode=0o700)
        path=root/'old.yaml';path.write_bytes(b'synthetic preserved bytes');os.utime(path,(1,1))
        before[path]=path.read_bytes()
    result=subprocess.run([sys.executable,'-c','import app'],cwd=tmp_path,
        env=dict(os.environ,PYTHONPATH=str(ROOT),**{key:'PRIVATE_INVALID_VALUE'}),
        capture_output=True,text=True,timeout=10)
    assert result.returncode!=0 and 'PRIVATE_INVALID_VALUE' not in result.stderr+result.stdout
    assert not (tmp_path/'state').exists() and not (tmp_path/'logs').exists()
    assert all(p.read_bytes()==v for p,v in before.items())


@pytest.mark.parametrize('value,seconds', [('1',3600),('24',86400),('87600',315360000),('00001',3600)])
def test_explicit_finite_link_hours(value, seconds):
    assert retention.link_seconds_from_env({'TEMP_LINK_LIFETIME_HOURS':value},86400)==seconds


@pytest.mark.parametrize('value', ['', '0','-1','87601','1.5','inf','NaN',' 24','24 ','２４','+1','1e2','9'*5000,True,24])
def test_invalid_link_hours(value):
    with pytest.raises(ValueError,match='TEMP_LINK_LIFETIME_HOURS must be an integer from 1 to 87600.'):
        retention.link_seconds_from_env({'TEMP_LINK_LIFETIME_HOURS':value},86400)


@pytest.mark.parametrize('env,expected', [({},86400),({'OUTPUT_RETENTION_HOURS':'0.5'},1800),
    ({'FILE_RETENTION_DAYS':'7'},604800),({'OUTPUT_RETENTION_HOURS':'2','FILE_RETENTION_DAYS':'7'},7200),
    ({'OUTPUT_RETENTION_HOURS':'0'},86400),({'OUTPUT_RETENTION_HOURS':'1e308'},86400)])
def test_legacy_link_fallback_and_zero_not_keep(env,expected):
    seconds=retention.seconds_from_env(env,'OUTPUT_RETENTION_HOURS',24,'FILE_RETENTION_DAYS')
    assert retention.link_seconds_from_env(env,seconds)==expected and math.isfinite(seconds)


def old(path, now, age):
    path.write_bytes(b'proxies: []\nrules: []\n')
    os.utime(path,(now-age,now-age))
    return path


def sweep(web):
    Path(web.CLEANUP_MARKER).unlink(missing_ok=True)
    web.cleanup_old_files()


@pytest.mark.parametrize('policies', itertools.product(('timed','keep'),repeat=3))
def test_real_files_per_policy_past_expiry(web,monkeypatch,policies):
    now=time.time();paths=[]
    for directory,age in zip((web.DIR_UPLOADS,web.DIR_OUTPUTS,web.DIR_BACKUPS),(3600,86400,604800)):
        paths.append(old(Path(directory)/'expired.yaml',now,age+100))
    for key,value in zip(retention.POLICY_KEYS,policies):monkeypatch.setattr(web,key,value)
    protected={}
    for directory in (Path(web.DIR_STATE),Path(web.DIR_LOGS),Path(web.BASE_DIR)/'legacy-updater-backup',
                      Path(web.DIR_STATE)/'fixed-cache',Path(web.BASE_DIR)/'offline-snapshot',Path(web.BASE_DIR)/'catalog'):
        directory.mkdir(exist_ok=True);p=old(directory/'old.yaml',now,1000000);protected[p]=p.read_bytes()
    sweep(web)
    assert [p.exists() for p in paths]==[v=='keep' for v in policies]
    assert all(p.read_bytes()==raw for p,raw in protected.items())


def test_timed_exact_boundary_and_kept_no_scan(tmp_path,monkeypatch):
    root=tmp_path/'private';root.mkdir(mode=0o700)
    before=old(root/'before.yaml',10000,3599);boundary=old(root/'boundary.yml',10000,3600)
    assert retention.cleanup_directory(root,3600,'timed',10000)==1
    assert before.exists() and not boundary.exists()
    monkeypatch.setattr(os,'open',lambda *_a,**_k:pytest.fail('keep must not open or scan any directory'))
    assert retention.cleanup_directory(root,3600,'keep',10**12)==0


def test_unknown_and_unsafe_objects_never_deleted(tmp_path,monkeypatch):
    root=tmp_path/'private';root.mkdir(mode=0o700)
    external=old(tmp_path/'external.yaml',10000,10000)
    (root/'symlink.yaml').symlink_to(external)
    os.link(external,root/'hardlink.yaml')
    (root/'directory.yaml').mkdir()
    old(root/'unknown.json',10000,10000);old(root/'.hidden.yaml',10000,10000)
    unsafe=old(root/'unsafe.yaml',10000,10000);unsafe.chmod(0o666)
    os.mkfifo(root/'fifo.yaml')
    monkeypatch.chdir(root)
    sock=socket.socket(socket.AF_UNIX);sock.bind('socket.yaml')
    original=set(p.name for p in root.iterdir())
    try:
        assert retention.cleanup_directory(root,1,'timed',10000)==0
        assert set(p.name for p in root.iterdir())==original and external.read_bytes().startswith(b'proxies')
    finally:sock.close()


def test_symlink_and_writable_directory_refused(tmp_path):
    actual=tmp_path/'actual';actual.mkdir(mode=0o700);p=old(actual/'old.yaml',10000,10000)
    link=tmp_path/'link';link.symlink_to(actual,target_is_directory=True)
    with pytest.raises(OSError):retention.cleanup_directory(link,1,'timed',10000)
    actual.chmod(0o777)
    assert retention.cleanup_directory(actual,1,'timed',10000)==0 and p.exists()


def test_replaced_candidate_not_deleted(tmp_path,monkeypatch):
    root=tmp_path/'private';root.mkdir(mode=0o700)
    candidate=old(root/'old.yaml',10000,10000);saved=root/'original.json'
    real_open=os.open
    def swap(name,flags,*args,**kwargs):
        if name=='old.yaml' and 'dir_fd' in kwargs:
            candidate.rename(saved);old(candidate,10000,10000)
        return real_open(name,flags,*args,**kwargs)
    monkeypatch.setattr(os,'open',swap)
    assert retention.cleanup_directory(root,1,'timed',10000)==0
    assert candidate.exists() and saved.exists()


def test_entry_and_time_scan_budgets(tmp_path,monkeypatch):
    root=tmp_path/'private';root.mkdir(mode=0o700)
    for i in range(8):old(root/f'{i}.yaml',10000,10000)
    monkeypatch.setattr(retention,'MAX_SCAN_ENTRIES',3)
    assert retention.cleanup_directory(root,1,'timed',10000)==3
    assert len(list(root.iterdir()))==5
    ticks=iter([0,retention.SCAN_BUDGET_SECONDS])
    monkeypatch.setattr(retention.time,'monotonic',lambda:next(ticks))
    assert retention.cleanup_directory(root,1,'timed',10000)==0


@pytest.mark.parametrize('mode', ['owner','filesystem','fstat'])
def test_identity_refusal_preserves_real_file(tmp_path,monkeypatch,mode):
    root=tmp_path/'private';root.mkdir(mode=0o700);p=old(root/'old.yaml',10000,10000)
    if mode=='owner':monkeypatch.setattr(os,'geteuid',lambda:os.getuid()+1)
    else:
        original=retention._identity
        # Only fault identity observations; actual file bytes/metadata remain real.
        calls=[0]
        def mismatch(info):
            calls[0]+=1
            value=original(info)
            return (value[0]+1,*value[1:]) if calls[0]==(1 if mode=='filesystem' else 2) else value
        monkeypatch.setattr(retention,'_identity',mismatch)
    assert retention.cleanup_directory(root,1,'timed',10000)==0 and p.exists()


@pytest.mark.parametrize('web', [{'OUTPUT_RETENTION_POLICY':'keep'},
    {'OUTPUT_RETENTION_POLICY':'keep','TEMP_LINK_LIFETIME_HOURS':'1'},
    {'OUTPUT_RETENTION_POLICY':'keep','FILE_RETENTION_DAYS':'2'}],indirect=True)
def test_output_keep_link_still_expires_and_tombstone(web,logged_in,monkeypatch):
    assert post(logged_in,'/process',{'batch_nodes':LINK}).status_code==302
    with logged_in.session_transaction() as session:ctx=session['page_context'].copy()
    key=ctx['download_url'].rsplit('/',1)[1];entry=web.temporary_links.resolve(key)
    assert entry['expires_at']-entry['created_at']==web.TEMP_LINK_LIFETIME_SECONDS
    p=Path(web.DIR_OUTPUTS)/ctx['output_filename'];old(p,time.time(),web.OUTPUT_RETENTION_SECONDS+100)
    sweep(web);assert p.exists()
    anonymous=web.app.test_client();assert anonymous.get('/t/'+key).status_code==200
    monkeypatch.setattr(web,'cleanup_old_files',lambda:None)
    monkeypatch.setattr('core.temporary_links.time.time',lambda:entry['expires_at'])
    assert anonymous.get('/t/'+key).status_code==404 and p.exists()
    assert read_json(web.temporary_links.path)['links'][key] is None


@pytest.mark.parametrize('web',[{'OUTPUT_RETENTION_POLICY':'keep'}],indirect=True)
def test_keep_manual_deletion_revokes_and_fixed_lifecycle_unchanged(web,logged_in):
    post(logged_in,'/process',{'batch_nodes':LINK})
    with logged_in.session_transaction() as session:ctx=session['page_context'].copy()
    key=ctx['download_url'].rsplit('/',1)[1]
    post(logged_in,'/delete-temp',{'output_filename':ctx['output_filename']})
    assert not (Path(web.DIR_OUTPUTS)/ctx['output_filename']).exists()
    assert web.temporary_links.resolve(key) is None
    entry=create(web,logged_in);slug=web.fixed_subscriptions.slug(entry)
    assert web.fixed_subscriptions.resolve(slug) is not None
    before=web.fixed_subscriptions.path.read_bytes()
    sweep(web);assert web.fixed_subscriptions.path.read_bytes()==before
    assert web.fixed_subscriptions.resolve(slug) is not None
    web.fixed_subscriptions.action(entry['id'],'regenerate')
    assert web.fixed_subscriptions.resolve(slug) is None


def test_invalid_runtime_policy_checks_all_before_deletion(web,monkeypatch):
    p=old(Path(web.DIR_UPLOADS)/'old.yaml',10000,10000)
    monkeypatch.setattr(web,'BACKUP_RETENTION_POLICY','bad')
    with pytest.raises(ValueError):sweep(web)
    assert p.exists()


@pytest.mark.parametrize('web',[{key:'keep' for key in retention.POLICY_KEYS}],indirect=True)
def test_runtime_capacity_warning_safe_effective_values(web,logged_in):
    data=web.settings_runtime()
    for field in ('upload_retention','output_retention','backup_retention'):
        assert 'Keep' in data[field] and 'no age-based deletion' in data[field] and 'manage disk capacity' in data[field]
    assert '86400 seconds' in data['output_retention']
    html=logged_in.get('/settings').get_data(as_text=True)
    assert html.count('no age-based deletion')==3 and 'Temporary link lifetime: 86400 seconds' in html


@pytest.mark.parametrize('web',[{key:'keep' for key in retention.POLICY_KEYS}],indirect=True)
def test_disk_full_does_not_truncate_existing_kept_data(web,logged_in,monkeypatch):
    original=old(Path(web.DIR_OUTPUTS)/'existing.yaml',10000,10000);raw=original.read_bytes()
    from core import yaml_utils
    link=os.link
    def full(src,dst,*args,**kwargs):
        if str(dst).startswith(web.DIR_OUTPUTS):raise OSError(errno.ENOSPC,'synthetic disk full')
        return link(src,dst,*args,**kwargs)
    monkeypatch.setattr(yaml_utils.os,'link',full)
    response=post(logged_in,'/process',{'batch_nodes':LINK},follow_redirects=True)
    assert response.status_code==200 and b'id="download-url"' not in response.data
    assert original.read_bytes()==raw and list(Path(web.DIR_OUTPUTS).iterdir())==[original]


@pytest.mark.parametrize('lifetime', [0,-1,float('nan'),float('inf'),'24',None,True])
def test_temporary_link_finite_interface_no_invalid_state(tmp_path,lifetime):
    store=TemporaryLinks(tmp_path)
    with pytest.raises(ValueError):store.create('output.yaml',lifetime,now=100)
    assert not store.path.exists()


@pytest.mark.parametrize('web,expected',[({},(3600,86400,604800,3600)),
    ({'FILE_RETENTION_DAYS':'3','BACKUP_RETENTION_DAYS':'9','CLEANUP_INTERVAL_DAYS':'2'},(259200,259200,777600,172800)),
    ({'FILE_RETENTION_DAYS':'3','UPLOAD_RETENTION_HOURS':'2','OUTPUT_RETENTION_HOURS':'4','BACKUP_RETENTION_HOURS':'6'},(7200,14400,21600,3600)),
    ({'UPLOAD_RETENTION_HOURS':'0','OUTPUT_RETENTION_HOURS':'0','BACKUP_RETENTION_HOURS':'0'},(3600,86400,604800,3600))],indirect=['web'])
def test_actual_app_default_and_legacy_hours_days(web,expected):
    assert (web.UPLOAD_RETENTION_SECONDS,web.OUTPUT_RETENTION_SECONDS,web.BACKUP_RETENTION_SECONDS,web.CLEANUP_INTERVAL_SECONDS)==expected
    assert (web.UPLOAD_RETENTION_POLICY,web.OUTPUT_RETENTION_POLICY,web.BACKUP_RETENTION_POLICY)==('timed',)*3
    assert web.TEMP_LINK_LIFETIME_SECONDS==expected[1]


@pytest.mark.parametrize('replacement',['symlink','hardlink','directory'])
def test_unsafe_replacement_before_open_preserved(tmp_path,monkeypatch,replacement):
    root=tmp_path/'private';root.mkdir(mode=0o700)
    p=old(root/'old.yaml',10000,10000);external=old(tmp_path/'external.yaml',10000,10000)
    original=os.open
    def replace(name,flags,*args,**kwargs):
        if name=='old.yaml' and 'dir_fd' in kwargs:
            p.unlink()
            if replacement=='symlink':p.symlink_to(external)
            elif replacement=='hardlink':os.link(external,p)
            else:p.mkdir()
        return original(name,flags,*args,**kwargs)
    monkeypatch.setattr(os,'open',replace)
    try:assert retention.cleanup_directory(root,1,'timed',10000)==0
    except OSError:assert replacement=='symlink'
    assert p.exists() and external.read_bytes().startswith(b'proxies')


def test_cleanup_permission_failure_does_not_remove_or_revoke(web,monkeypatch):
    p=old(Path(web.DIR_OUTPUTS)/'old.yaml',10000,10000)
    key,_=web.temporary_links.create('old.yaml',now=time.time())
    original=os.unlink
    def denied(name,*args,**kwargs):
        if name=='old.yaml' and 'dir_fd' in kwargs:raise PermissionError('synthetic denied')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(os,'unlink',denied)
    sweep(web)
    assert p.exists() and web.temporary_links.resolve(key) is not None


@pytest.mark.parametrize('value',[float('nan'),float('inf'),None,'invalid',True])
def test_link_invalid_clock_cannot_publish(tmp_path,value):
    store=TemporaryLinks(tmp_path)
    with pytest.raises(ValueError):store.create('output.yaml',3600,now=value if value is not None else float('nan'))
    assert not store.path.exists()


def test_runtime_invalid_policy_never_echoes_private_value(web,monkeypatch):
    monkeypatch.setattr(web,'UPLOAD_RETENTION_POLICY','PRIVATE_POLICY_SECRET')
    projected=web.settings_runtime()
    assert projected['upload_retention']=='Unavailable'
    assert 'PRIVATE_POLICY_SECRET' not in str(projected)
