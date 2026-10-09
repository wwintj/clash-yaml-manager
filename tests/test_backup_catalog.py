"""Synthetic catalog fixtures; no live state, accounts, deployment or restore."""
import errno
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys

import pytest

from conftest import ROOT
from scripts import backup_catalog as catalog
from scripts import backup_collect as collector
from scripts import backup_create as writer
from scripts import backup_manifest as protocol
from scripts import backup_verify as verifier

SECRET = 'synthetic-password-token-勿輸出'
OPERATION = 'a' * 32


def freeze(path):
    return {p.relative_to(path).as_posix(): (verifier.fingerprint(p.lstat()),
            p.read_bytes() if stat.S_ISREG(p.lstat().st_mode) else None)
            for p in [path, *path.rglob('*')]}


@pytest.fixture
def fixture(tmp_path):
    parent = tmp_path / 'private'; parent.mkdir(mode=0o700)
    source = parent / 'source'; source.mkdir(mode=0o700)
    (source / 'data').write_bytes(SECRET.encode()); (source / 'VERSION').write_bytes(b'1.7.0\n')
    snapshot = parent / 'snapshot'
    result = writer.create(source, snapshot, 'UPDATER_SNAPSHOT')
    assert result['creation_status'] == 'CREATED'
    cat = parent / 'catalog'; cat.mkdir(mode=0o700)
    return dict(catalog=cat, snapshot=snapshot, source=source, digest=result['MANIFEST_SHA256'])


def register(fixture, **changes):
    args = dict(action='register', catalog=fixture['catalog'], snapshot=fixture['snapshot'],
                representation=fixture['source'], expected_digest=fixture['digest'],
                operation_id=OPERATION, profile='manifest-v1-declared-scope', completed_offline=True)
    args.update(changes)
    return catalog.execute(**args)


def verify(fixture, snapshot_id, **changes):
    args = dict(action='verify', catalog=fixture['catalog'], snapshot=fixture['snapshot'], snapshot_id=snapshot_id)
    args.update(changes)
    return catalog.execute(**args)


def enrolled(fixture):
    result = register(fixture)
    assert result['registration_status'] == 'REGISTERED', result
    return result['snapshot_id']


def refused(result, code):
    assert code in result['validation_codes'], result
    assert result['restore_proven'] is False
    assert SECRET not in json.dumps(result)


def test_registration_canonical_and_readonly_inspect_verify(fixture):
    before = freeze(fixture['snapshot']); source = freeze(fixture['source'])
    result = register(fixture); sid = result['snapshot_id']
    assert result['registration_status'] == 'REGISTERED', result
    record = fixture['catalog'] / (sid + '.json'); raw = record.read_bytes()
    value = catalog.load_record(raw)
    assert raw == catalog.canonical_record(value) and b'\n' not in raw
    assert value['manifest_sha256'] == fixture['digest'] and value['snapshot_id'] == sid
    assert value['operation_id'] == OPERATION and value['restore_proven'] is False
    assert value['snapshot_binding']['path_sha256'] == hashlib.sha256(str(fixture['snapshot']).encode()).hexdigest()
    assert value['snapshot_binding']['inode'] == fixture['snapshot'].stat().st_ino
    assert value['verified_facts']['snapshot_provenance_authenticated'] is False
    assert value['verified_facts']['expected_digest_origin']=='OPERATOR_ARGUMENT'
    assert value['operator_claims']['independent_digest_handoff'] is True
    assert str(fixture['snapshot']).encode() not in raw and SECRET.encode() not in raw
    assert stat.S_IMODE(record.stat().st_mode) == 0o600 and record.stat().st_uid == os.geteuid()
    assert stat.S_IMODE(fixture['catalog'].stat().st_mode) == 0o700
    cat_before = freeze(fixture['catalog'])
    inspected = catalog.execute('inspect', fixture['catalog'], snapshot_id=sid)
    assert inspected['inspection_status'] == 'CATALOG_INSPECTED'
    assert inspected['catalog_record_valid'] and inspected['record_found']
    assert 'SNAPSHOT_EXISTENCE_NOT_CHECKED' in inspected['validation_codes']
    result = verify(fixture, sid)
    assert result['verification_status'] == 'TRUSTED_SCOPE_VERIFIED', result
    for key in ('record_found','catalog_record_valid','snapshot_identity_match','manifest_digest_match','declared_scope_verified','trusted_scope_verified'):
        assert result[key] is True
    assert freeze(fixture['snapshot']) == before and freeze(fixture['source']) == source
    assert freeze(fixture['catalog']) == cat_before
    assert result['protection_model'] == ('ROOT_PRIVATE' if os.geteuid() == os.getegid() == 0 else 'LOCAL_UID_FIXTURE')


def test_collector_writer_catalog_verifier_e2e_and_tampering(tmp_path, capsys):
    parent = tmp_path / 'private'; parent.mkdir(mode=0o700)
    source = parent / 'source'; source.mkdir(mode=0o700)
    (source / 'defaults').mkdir(); (source / 'state').mkdir(mode=0o700)
    (source / '.env').write_bytes(('APP_PASSWORD=  '+SECRET+'  \n').encode()); (source / '.env').chmod(0o600)
    (source / 'VERSION').write_bytes(b'1.7.0\n')
    (source / 'defaults/default.yaml').write_bytes((ROOT / 'defaults/default.yaml').read_bytes())
    for name, value in [(collector.SOURCE_CONTROL,dict(schema_version=1,profile=collector.PROFILE,offline=True,writers_quiet=True,service_account=None)),
                        ('state/auth.json',dict(version=1,password_hash=SECRET))]:
        path=source/name; path.write_text(json.dumps(value)); path.chmod(0o600)
    rep=parent/'representation';snap=parent/'snapshot';cat=parent/'catalog';cat.mkdir(mode=0o700)
    assert collector.collect(source,rep,collector.PROFILE)['collection_status']=='COLLECTED'
    created=writer.create(rep,snap,'UPDATER_SNAPSHOT');assert created['creation_status']=='CREATED'
    fixture=dict(catalog=cat,snapshot=snap,source=rep,digest=created['MANIFEST_SHA256'])
    result=register(fixture,profile=collector.PROFILE);assert result['registration_status']=='REGISTERED',result
    assert verify(fixture,result['snapshot_id'])['verification_status']=='TRUSTED_SCOPE_VERIFIED'
    (snap/'.env').write_bytes(b'tampered')
    rejected=verify(fixture,result['snapshot_id'])
    refused(rejected,'NOT_VERIFIED');assert not rejected['trusted_scope_verified']
    with capsys.disabled():
        print('CATALOG_E2E: PASS '+json.dumps(dict(collector=True,writer=True,manifest_version=1,catalog=True,
              real_verifier=True,tampered_snapshot_refused=True,restore_proven=False),sort_keys=True))


@pytest.mark.parametrize('changes',[
    {'expected_digest':'0'*64},{'expected_digest':'bad'},{'completed_offline':False},
    {'operation_id':'../secret'},{'operation_id':True},{'profile':'unknown'},
    {'original_identity':{'password':SECRET}},{'target_identity':{'url':'https://'+SECRET}}])
def test_invalid_registration_and_digest_no_mutation(fixture,changes):
    before=freeze(fixture['snapshot']);cat=freeze(fixture['catalog'])
    result=register(fixture,**changes)
    assert result['registration_status']=='NOT_REGISTERED'
    assert freeze(fixture['snapshot'])==before and freeze(fixture['catalog'])==cat
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize('component',['data',protocol.MANIFEST_NAME])
def test_tampered_snapshot_or_manifest(fixture,component):
    sid=enrolled(fixture);path=fixture['snapshot']/component
    path.write_bytes(path.read_bytes()+b'X')
    result=verify(fixture,sid);refused(result,'NOT_VERIFIED')
    assert not result['trusted_scope_verified']


def test_valid_but_rewritten_manifest_cannot_replace_catalog_anchor(fixture):
    sid=enrolled(fixture);path=fixture['snapshot']/'data';path.write_bytes(b'rewritten')
    manifest=protocol.load_manifest((fixture['snapshot']/protocol.MANIFEST_NAME).read_bytes())
    entry=next(e for e in manifest['entries'] if e['path']=='data')
    entry.update(size=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    (fixture['snapshot']/protocol.MANIFEST_NAME).write_bytes(protocol.canonical_bytes(manifest))
    assert verifier.verify(fixture['snapshot'])['verification_status']=='INTERNALLY_CONSISTENT'
    result=verify(fixture,sid);refused(result,'MANIFEST_DIGEST_MISMATCH')
    assert result['manifest_digest_match'] is False and not result['trusted_scope_verified']


@pytest.mark.parametrize('transform',[lambda b:b[:-1],lambda b:b+b'\n',lambda b:b'{}',lambda b:b'{"password":"secret"}',lambda b:b'not json'])
def test_truncated_malformed_noncanonical_record(fixture,transform):
    sid=enrolled(fixture);path=fixture['catalog']/(sid+'.json');path.write_bytes(transform(path.read_bytes()))
    result=verify(fixture,sid);refused(result,'NOT_VERIFIED');assert not result['catalog_record_valid']


def test_tampered_record_digest_is_not_verified(fixture):
    sid=enrolled(fixture);path=fixture['catalog']/(sid+'.json');value=catalog.load_record(path.read_bytes())
    value['manifest_sha256']='0'*64;path.write_bytes(catalog.canonical_record(value))
    result=verify(fixture,sid);refused(result,'MANIFEST_DIGEST_MISMATCH')
    assert not result['trusted_scope_verified']  # Same-owner rewrite is outside protection threat model.


def test_missing_snapshot_and_unanchored(fixture):
    unknown='b'*32
    refused(verify(fixture,unknown),'UNANCHORED')
    refused(verify(fixture,unknown,catalog=fixture['catalog'].parent/'missing-catalog'),'UNANCHORED')
    sid=enrolled(fixture)
    fixture['snapshot'].rename(fixture['snapshot'].with_name('moved'))
    result=verify(fixture,sid);refused(result,'MISSING_SNAPSHOT');assert result['record_found']
    assert (fixture['catalog']/(sid+'.json')).exists()


def test_location_and_inode_binding(fixture):
    sid=enrolled(fixture);moved=fixture['snapshot'].with_name('moved')
    fixture['snapshot'].rename(moved)
    refused(verify(fixture,sid,snapshot=moved),'SNAPSHOT_IDENTITY_MISMATCH')


def test_duplicate_operation_and_association(fixture):
    sid=enrolled(fixture);before=freeze(fixture['catalog'])
    refused(register(fixture),'DUPLICATE_OPERATION_ID')
    refused(register(fixture,operation_id='c'*32),'DUPLICATE_SNAPSHOT_ASSOCIATION')
    assert freeze(fixture['catalog'])==before and (fixture['catalog']/(sid+'.json')).exists()


def test_duplicate_snapshot_id(fixture,monkeypatch):
    sid=enrolled(fixture);monkeypatch.setattr(catalog.secrets,'token_hex',lambda _:sid)
    before=freeze(fixture['catalog']);refused(register(fixture,operation_id='b'*32),'DUPLICATE_SNAPSHOT_ID')
    assert freeze(fixture['catalog'])==before


@pytest.mark.parametrize('root',['catalog','snapshot','source'])
def test_root_and_ancestor_symlinks(fixture,root):
    target=fixture[root];link=target.with_name('link');link.symlink_to(target,target_is_directory=True)
    changes={'catalog':link} if root=='catalog' else {'snapshot':link} if root=='snapshot' else {'representation':link}
    result=register(fixture,**changes);refused(result,'UNSAFE_ROOT_PATH')
    ancestor=target.parent.with_name('ancestor');ancestor.symlink_to(target.parent,target_is_directory=True)
    changes[next(iter(changes))]=ancestor/target.name
    refused(register(fixture,**changes),'UNSAFE_ROOT_PATH')


@pytest.mark.parametrize('root',['catalog','snapshot','source'])
@pytest.mark.parametrize('mode',[0o755,0o770,0o1700])
def test_private_root_permissions(fixture,root,mode):
    fixture[root].chmod(mode);refused(register(fixture),'UNSAFE_PRIVATE_ROOT')


@pytest.mark.parametrize('location',['snapshot','source'])
def test_catalog_inside_snapshot_or_representation_refused(fixture,location):
    nested=fixture[location]/'catalog';nested.mkdir(mode=0o700)
    refused(register(fixture,catalog=nested),'CATALOG_NOT_INDEPENDENT')


def test_known_staging_snapshot_refused(fixture):
    staged=fixture['snapshot'].with_name('.backup-create-'+'f'*32);fixture['snapshot'].rename(staged)
    refused(register(fixture,snapshot=staged),'UNPUBLISHED_STAGING_REFUSED')


@pytest.mark.parametrize('object_type',['symlink','hardlink','fifo','socket','directory'])
def test_catalog_unsafe_objects(fixture,object_type,monkeypatch):
    path=fixture['catalog']/('b'*32+'.json');sock=None
    if object_type=='symlink':path.symlink_to(fixture['snapshot']/'data')
    elif object_type=='hardlink':os.link(fixture['snapshot']/'data',path)
    elif object_type=='fifo':os.mkfifo(path,0o600)
    elif object_type=='directory':path.mkdir(mode=0o700)
    else:
        monkeypatch.chdir(fixture['catalog']);sock=socket.socket(socket.AF_UNIX);sock.bind(path.name)
    try:refused(catalog.execute('inspect',fixture['catalog']),'UNSAFE_CATALOG_OBJECT')
    finally:
        if sock is not None:sock.close()


@pytest.mark.parametrize('mode',[0o644,0o660,0o4600])
def test_unsafe_record_permissions(fixture,mode):
    sid=enrolled(fixture);(fixture['catalog']/(sid+'.json')).chmod(mode)
    refused(verify(fixture,sid),'UNSAFE_CATALOG_OWNERSHIP_OR_PERMISSION')


def test_unknown_catalog_entry_not_opened(fixture,monkeypatch):
    (fixture['catalog']/'unknown').write_bytes(SECRET.encode())
    actual=os.open
    def guarded(path,*args,**kwargs):
        assert path!='unknown';return actual(path,*args,**kwargs)
    monkeypatch.setattr(os,'open',guarded)
    refused(catalog.execute('inspect',fixture['catalog']),'UNEXPECTED_CATALOG_OBJECT')


def test_staging_residue_not_read_or_removed(fixture,monkeypatch):
    stage=fixture['catalog']/('.catalog-stage-'+'b'*32+'.tmp');stage.write_bytes(b'partial secret');stage.chmod(0o600)
    before=freeze(fixture['catalog']);actual=os.open
    def guarded(path,*args,**kwargs):
        assert path!=stage.name;return actual(path,*args,**kwargs)
    monkeypatch.setattr(os,'open',guarded)
    inspected=catalog.execute('inspect',fixture['catalog'])
    assert inspected['inspection_status']=='CATALOG_INSPECTED' and inspected['counts']['staging_residue']==1
    refused(inspected,'STAGING_RESIDUE');refused(register(fixture),'STAGING_RESIDUE')
    assert freeze(fixture['catalog'])==before


@pytest.mark.parametrize('failure',[errno.ENOSPC,errno.EIO,'zero','interrupt'])
def test_write_failures_cleanup_and_snapshot_unchanged(fixture,monkeypatch,failure):
    before=freeze(fixture['snapshot'])
    def fail(*args):
        if failure=='interrupt':raise KeyboardInterrupt
        if failure=='zero':return 0
        raise OSError(failure,SECRET)
    monkeypatch.setattr(os,'write',fail)
    result=register(fixture);assert result['registration_status']=='NOT_REGISTERED'
    assert result['cleanup_status']=='CLEANED' and not list(fixture['catalog'].iterdir())
    assert freeze(fixture['snapshot'])==before and SECRET not in json.dumps(result)


def test_prepublication_fsync_failure(fixture,monkeypatch):
    actual=os.fsync
    def fail(fd):
        if stat.S_ISREG(os.fstat(fd).st_mode):raise OSError(errno.EIO,SECRET)
        actual(fd)
    monkeypatch.setattr(os,'fsync',fail)
    result=register(fixture);assert result['registration_status']=='NOT_REGISTERED'
    assert result['cleanup_status']=='CLEANED' and not list(fixture['catalog'].iterdir())


def test_postpublication_fsync_failure_retains(fixture,monkeypatch):
    actual=os.fsync
    def fail(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):raise OSError(errno.EIO,SECRET)
        actual(fd)
    monkeypatch.setattr(os,'fsync',fail)
    result=register(fixture);assert result['registration_status']=='NOT_REGISTERED'
    assert result['publication_status']=='PUBLISHED' and result['retained_record']
    assert result['cleanup_status']=='NOT_ATTEMPTED_PUBLISHED' and len(list(fixture['catalog'].glob('*.json')))==1


def test_native_publication_then_interruption_retains(fixture,monkeypatch):
    native=writer.publication_function()
    def interrupted(fd,stage,name):native(fd,stage,name);raise KeyboardInterrupt
    monkeypatch.setattr(writer,'publication_function',lambda:interrupted)
    result=register(fixture);refused(result,'REGISTRATION_INTERRUPTED')
    assert result['retained_record'] and result['publication_status']=='PUBLISHED'
    assert len(list(fixture['catalog'].glob('*.json')))==1


def test_native_collision_preserves_external_record(fixture,monkeypatch):
    native=writer.publication_function();external=[]
    def race(fd,stage,name):
        path=fixture['catalog']/name;path.write_bytes(b'external');path.chmod(0o600)
        external.append((path,verifier.fingerprint(path.stat())));native(fd,stage,name)
    monkeypatch.setattr(writer,'publication_function',lambda:race)
    result=register(fixture);refused(result,'DESTINATION_EXISTS');assert result['cleanup_status']=='CLEANED'
    path,info=external[0];assert path.read_bytes()==b'external' and verifier.fingerprint(path.stat())==info


def test_cleanup_identity_mismatch_retains_replacement(fixture,monkeypatch):
    actual=catalog.Catalog.write_stage;foreign=[]
    def changed(self,fd,raw):
        actual(self,fd,raw)
        path=fixture['catalog']/self.stage_name;path.rename(path.with_name('moved-own-stage'))
        path.write_bytes(b'foreign');path.chmod(0o600);foreign.append(path)
        raise OSError(errno.EIO,SECRET)
    monkeypatch.setattr(catalog.Catalog,'write_stage',changed)
    result=register(fixture);refused(result,'CLEANUP_FAILED')
    assert result['cleanup_status']=='FAILED' and foreign[0].read_bytes()==b'foreign'


@pytest.mark.parametrize('point',['before-verifier','after-stage','after-publish'])
def test_source_mutation_during_enrollment(fixture,monkeypatch,point):
    if point=='before-verifier':
        actual=verifier.verify
        def mutate(*args,**kwargs):
            (fixture['snapshot']/'data').write_bytes(b'changed');return actual(*args,**kwargs)
        monkeypatch.setattr(verifier,'verify',mutate)
    elif point=='after-stage':
        actual=catalog.Catalog.write_stage
        def mutate(self,fd,raw):
            actual(self,fd,raw);(fixture['snapshot']/'data').write_bytes(b'changed')
        monkeypatch.setattr(catalog.Catalog,'write_stage',mutate)
    else:
        actual=writer.publication_function()
        def mutate(fd,stage,name):
            actual(fd,stage,name);(fixture['snapshot']/'data').write_bytes(b'changed')
        monkeypatch.setattr(writer,'publication_function',lambda:mutate)
    result=register(fixture);assert result['registration_status']=='NOT_REGISTERED'
    assert result['retained_record'] is (point=='after-publish')
    assert result['cleanup_status']==('NOT_ATTEMPTED_PUBLISHED' if point=='after-publish' else 'NOT_NEEDED' if point=='before-verifier' else 'CLEANED')


@pytest.mark.parametrize('limit,value,code',[('MAX_RECORD_BYTES',100,'RECORD_SIZE_LIMIT'),('MAX_READ_BYTES',1,'TOTAL_READ_LIMIT'),
    ('MAX_ENTRIES',0,'CATALOG_ENTRY_LIMIT'),('MAX_STAGING',0,'STAGING_CAPACITY_LIMIT'),('MAX_SECONDS',-1,'TIME_LIMIT'),
    ('MAX_LOCATION_BYTES',1,'LOCATION_LIMIT'),('MAX_LOCATION_PARTS',1,'LOCATION_LIMIT')])
def test_resource_limits_fail_closed(fixture,monkeypatch,limit,value,code):
    if limit=='MAX_ENTRIES':(fixture['catalog']/('b'*32+'.json')).write_bytes(b'{}')
    if limit=='MAX_STAGING':
        p=fixture['catalog']/('.catalog-stage-'+'b'*32+'.tmp');p.write_bytes(b'');p.chmod(0o600)
    monkeypatch.setattr(catalog,limit,value)
    result=register(fixture);refused(result,code);assert result['registration_status']=='NOT_REGISTERED'


def test_full_128_records_refuse_without_pruning(fixture):
    sid=enrolled(fixture);template=catalog.load_record((fixture['catalog']/(sid+'.json')).read_bytes())
    for n in range(1,128):
        value=json.loads(json.dumps(template));new=f'{n:032x}'
        value.update(snapshot_id=new,operation_id=f'{n+256:032x}')
        value['snapshot_binding'].update(path_sha256=f'{n:064x}',inode=n)
        path=fixture['catalog']/(new+'.json');path.write_bytes(catalog.canonical_record(value));path.chmod(0o600)
    before=freeze(fixture['catalog']);refused(register(fixture,operation_id='c'*32),'CATALOG_FULL')
    assert len(list(fixture['catalog'].iterdir()))==128 and freeze(fixture['catalog'])==before


def test_nonblocking_lock_refuses_concurrent_registration(fixture):
    import fcntl
    with catalog.root_directory(fixture['catalog']) as (fd,_):
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        refused(register(fixture),'CATALOG_BUSY')
    assert register(fixture)['registration_status']=='REGISTERED'


def test_two_processes_same_operation_only_one_record(fixture):
    code="""import json,sys
from scripts import backup_catalog as c
r=c.execute('register',sys.argv[1],snapshot=sys.argv[2],representation=sys.argv[3],expected_digest=sys.argv[4],operation_id=sys.argv[5],profile='manifest-v1-declared-scope',completed_offline=True)
print(json.dumps(r))
"""
    args=[sys.executable,'-c',code,str(fixture['catalog']),str(fixture['snapshot']),str(fixture['source']),fixture['digest'],OPERATION]
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
    children=[subprocess.Popen(args,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env) for _ in range(2)]
    results=[]
    for child in children:
        output,error=child.communicate(timeout=30);assert child.returncode==0 and not error;results.append(json.loads(output))
    assert sum(r['registration_status']=='REGISTERED' for r in results)==1
    loser=next(r for r in results if r['registration_status']!='REGISTERED')
    assert set(loser['validation_codes']) & {'CATALOG_BUSY','DUPLICATE_OPERATION_ID'}
    assert len(list(fixture['catalog'].glob('*.json')))==1


def test_killed_staging_is_not_automatically_cleaned(fixture):
    code="""import os,sys
from scripts import backup_catalog as c
actual=c.Catalog.write_stage
def killed(self,fd,raw):actual(self,fd,raw);os._exit(77)
c.Catalog.write_stage=killed
c.execute('register',sys.argv[1],snapshot=sys.argv[2],representation=sys.argv[3],expected_digest=sys.argv[4],operation_id=sys.argv[5],profile='manifest-v1-declared-scope',completed_offline=True)
"""
    args=[sys.executable,'-c',code,str(fixture['catalog']),str(fixture['snapshot']),str(fixture['source']),fixture['digest'],OPERATION]
    child=subprocess.run(args,cwd=ROOT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),capture_output=True,timeout=30)
    assert child.returncode==77 and not list(fixture['catalog'].glob('*.json'))
    before=freeze(fixture['catalog']);refused(register(fixture),'STAGING_RESIDUE');assert freeze(fixture['catalog'])==before


@pytest.mark.parametrize('arguments',[[],['inspect','--catalog','../'+SECRET],['register','--catalog',SECRET],
    ['verify','--catalog',SECRET,'--snapshot',SECRET,'--snapshot-id',SECRET],['inspect','--catalog',SECRET,'--original-identity',SECRET],
    ['inspect','--catalog',SECRET,'--bad',SECRET]])
def test_cli_bad_arguments_redacted(arguments,capsys):
    status=catalog.main(arguments);out=capsys.readouterr()
    assert status in (1,64) and SECRET not in out.out and not out.err
    assert json.loads(out.out)['restore_proven'] is False


def test_live_path_refused_before_open(monkeypatch):
    def no_open(*args,**kwargs):raise AssertionError('LIVE_OPEN')
    monkeypatch.setattr(os,'open',no_open)
    result=catalog.execute('inspect','/opt/clash-yaml-manager/state')
    refused(result,'LIVE_INSTALLATION_REFUSED')


def test_invalid_api_action_never_echoes_input(fixture):
    result=catalog.execute(SECRET,fixture['catalog'])
    refused(result,'INVALID_ACTION');assert result['action']=='INVALID_ACTION'


@pytest.mark.parametrize('location',['catalog','snapshot','source'])
def test_path_traversal(fixture,location):
    key={'catalog':'catalog','snapshot':'snapshot','source':'representation'}[location]
    refused(register(fixture,**{key:str(fixture[location])+'/../'+SECRET}),'INVALID_PATH')


def test_scope_requires_collector_metadata(fixture):
    refused(register(fixture,profile='updater-sidecar-v1'),'COLLECTOR_SCOPE_MISSING')


def test_fixed_safe_identity_claims_are_distinguished(fixture):
    identity=dict(channel='stable',base_version='1.7.0',commit='a'*40,tag='v1.7.0',installed_at='2026-10-09T00:00:00+00:00',source='github-release')
    result=register(fixture,original_identity=identity,target_identity=identity)
    assert result['registration_status']=='REGISTERED'
    value=catalog.load_record((fixture['catalog']/(result['snapshot_id']+'.json')).read_bytes())
    assert value['operator_claims']['original_identity']==identity
    assert value['snapshot_claims']['installed_identity'] is None
    assert value['verified_facts']['snapshot_provenance_authenticated'] is False


@pytest.mark.parametrize('field,value',[
    ('schema_version',True),('schema_version',2),('snapshot_id','../secret'),('operation_id','bad'),
    ('manifest_sha256','bad'),('restore_proven',True),('enrolled_at','secret'),('enrolled_at','2026-99-09T00:00:00.000000Z'),
    ('snapshot_binding',{}),('operator_claims',{}),('snapshot_claims',{}),('verified_facts',{}),('password',SECRET)])
def test_record_schema_strict(fixture,field,value):
    sid=enrolled(fixture);path=fixture['catalog']/(sid+'.json');record=json.loads(path.read_bytes())
    record[field]=value;path.write_text(json.dumps(record,sort_keys=True,separators=(',',':')))
    result=verify(fixture,sid);refused(result,'NOT_VERIFIED');assert not result['catalog_record_valid']


def test_record_filename_association(fixture):
    sid=enrolled(fixture);(fixture['catalog']/(sid+'.json')).rename(fixture['catalog']/('b'*32+'.json'))
    refused(verify(fixture,sid),'RECORD_FILENAME_MISMATCH')


def test_catalog_relocation_refused(fixture):
    sid=enrolled(fixture);moved=fixture['catalog'].with_name('moved-catalog');fixture['catalog'].rename(moved)
    refused(verify(fixture,sid,catalog=moved),'CATALOG_BINDING_MISMATCH')


@pytest.mark.parametrize('field,value,code',[('st_uid',999999,'UNSAFE_CATALOG_OWNERSHIP_OR_PERMISSION'),
    ('st_gid',999999,'UNSAFE_CATALOG_OWNERSHIP_OR_PERMISSION'),('st_dev',999999,'FILESYSTEM_BOUNDARY'),
    ('st_mode',stat.S_IFCHR|0o600,'UNSAFE_CATALOG_OBJECT'),('st_mode',stat.S_IFBLK|0o600,'UNSAFE_CATALOG_OBJECT')])
def test_unsafe_record_owner_or_device_not_opened(fixture,monkeypatch,field,value,code):
    from types import SimpleNamespace
    sid=enrolled(fixture);name=sid+'.json';actual=os.stat;opened=os.open
    def changed(path,*args,**kwargs):
        info=actual(path,*args,**kwargs)
        if path==name:
            result=SimpleNamespace(**{k:getattr(info,k) for k in dir(info) if k.startswith('st_')})
            setattr(result,field,value);return result
        return info
    def guarded(path,*args,**kwargs):
        assert path!=name;return opened(path,*args,**kwargs)
    monkeypatch.setattr(os,'stat',changed);monkeypatch.setattr(os,'open',guarded)
    refused(verify(fixture,sid),code)


def test_permission_denied_redacted(fixture,monkeypatch):
    sid=enrolled(fixture);actual=os.open
    def denied(path,*args,**kwargs):
        if path==sid+'.json':raise PermissionError(errno.EACCES,SECRET)
        return actual(path,*args,**kwargs)
    monkeypatch.setattr(os,'open',denied);refused(verify(fixture,sid),'PERMISSION_DENIED')


def test_missing_manifest_is_not_misreported_as_missing_snapshot(fixture):
    sid=enrolled(fixture);(fixture['snapshot']/protocol.MANIFEST_NAME).unlink()
    result=verify(fixture,sid);refused(result,'MANIFEST_MISSING');assert 'MISSING_SNAPSHOT' not in result['validation_codes']


def test_duplicate_json_keys_refused(fixture):
    sid=enrolled(fixture);path=fixture['catalog']/(sid+'.json');raw=path.read_bytes()
    path.write_bytes(b'{"schema_version":1,'+raw[1:]);refused(verify(fixture,sid),'INVALID_RECORD_CONTENT')


def test_stage_collision_never_owned_or_deleted(fixture,monkeypatch):
    actual=os.open;external=[]
    def collided(path,*args,**kwargs):
        if str(path).startswith('.catalog-stage-') and args[0]&os.O_CREAT:
            fd=actual(path,*args,**kwargs);os.write(fd,b'external');os.close(fd)
            external.append(fixture['catalog']/path);raise FileExistsError(errno.EEXIST,SECRET)
        return actual(path,*args,**kwargs)
    monkeypatch.setattr(os,'open',collided)
    result=register(fixture);refused(result,'STAGING_COLLISION')
    assert result['cleanup_status']=='NOT_NEEDED' and external[0].read_bytes()==b'external'


def test_interruption_before_stage_identity_preserves_unknown_inode(fixture,monkeypatch):
    actual=os.open;leaked=[]
    def interrupted(path,*args,**kwargs):
        fd=actual(path,*args,**kwargs)
        if str(path).startswith('.catalog-stage-') and args[0]&os.O_CREAT:
            leaked.append(fd);raise KeyboardInterrupt
        return fd
    monkeypatch.setattr(os,'open',interrupted)
    try:
        result=register(fixture);refused(result,'REGISTRATION_INTERRUPTED');refused(result,'CLEANUP_FAILED')
        assert result['residual_staging_name'] and (fixture['catalog']/result['residual_staging_name']).exists()
    finally:
        for fd in leaked:os.close(fd)


def test_postpublication_record_changed_refuses_success(fixture,monkeypatch):
    actual=writer.publication_function()
    def changed(fd,stage,name):
        actual(fd,stage,name);(fixture['catalog']/name).write_bytes(b'bad')
    monkeypatch.setattr(writer,'publication_function',lambda:changed)
    result=register(fixture);assert result['registration_status']=='NOT_REGISTERED' and result['retained_record']
    assert result['publication_status']=='PUBLISHED'


def test_cli_registration_then_verification(fixture,capsys):
    status=catalog.main(['register','--catalog',str(fixture['catalog']),'--snapshot',str(fixture['snapshot']),
        '--representation',str(fixture['source']),'--operation-id',OPERATION,'--scope-profile','manifest-v1-declared-scope',
        '--expected-manifest-sha256',fixture['digest'],'--completed-offline-snapshot'])
    result=json.loads(capsys.readouterr().out);assert status==0 and result['registration_status']=='REGISTERED'
    assert catalog.main(['verify','--catalog',str(fixture['catalog']),'--snapshot',str(fixture['snapshot']),
                          '--snapshot-id',result['snapshot_id']])==0
    output=capsys.readouterr();assert SECRET not in output.out and not output.err


@pytest.mark.parametrize('action',['register','verify','inspect'])
def test_final_catalog_handle_close_failure_never_reports_success(fixture,monkeypatch,action):
    sid=enrolled(fixture) if action!='register' else None
    actual=os.close;inode=fixture['catalog'].stat().st_ino;directory_closes=[0]
    def close(fd):
        info=os.fstat(fd)
        if info.st_ino==inode:
            directory_closes[0]+=1
            # root_directory opens a temporary check fd for every root_check.
            # Fail at closure only after the report's operation completed.
            import inspect
            for frame in inspect.stack():
                result=frame.frame.f_locals.get('report')
                if isinstance(result,dict) and (result.get('registration_status')=='REGISTERED' or result.get('verification_status')=='TRUSTED_SCOPE_VERIFIED' or result.get('inspection_status')=='CATALOG_INSPECTED'):
                    actual(fd);raise OSError(errno.EIO,SECRET)
        actual(fd)
    monkeypatch.setattr(os,'close',close)
    result=register(fixture) if action=='register' else verify(fixture,sid) if action=='verify' else catalog.execute('inspect',fixture['catalog'])
    assert result['registration_status']!='REGISTERED' and result['verification_status']!='TRUSTED_SCOPE_VERIFIED' and result['inspection_status']!='CATALOG_INSPECTED'
    assert SECRET not in json.dumps(result)


def test_extracted_identity_bytes_must_match_anchored_manifest(fixture,monkeypatch):
    identity=dict(channel='stable',base_version='1.7.0',commit='a'*40,tag='v1.7.0',installed_at='2026-10-09T00:00:00+00:00',source='github-release')
    (fixture['source']/'INSTALLATION.json').write_text(json.dumps(identity))
    fixture['snapshot']=fixture['source'].parent/'with-identity'
    created=writer.create(fixture['source'],fixture['snapshot'],'UPDATER_SNAPSHOT')
    assert created['creation_status']=='CREATED';fixture['digest']=created['MANIFEST_SHA256']
    path=fixture['snapshot']/'INSTALLATION.json';original=path.read_bytes();actual=catalog.Catalog.read
    changed=dict(identity,base_version='1.6.0',tag='v1.6.0')
    def temporarily_changed(self,fd,name,limit):
        if name=='INSTALLATION.json':
            path.write_text(json.dumps(changed))
            try:return actual(self,fd,name,limit)
            finally:path.write_bytes(original)
        return actual(self,fd,name,limit)
    monkeypatch.setattr(catalog.Catalog,'read',temporarily_changed)
    result=register(fixture);refused(result,'METADATA_DIGEST_MISMATCH')
    assert result['registration_status']=='NOT_REGISTERED' and not list(fixture['catalog'].iterdir())
    assert path.read_bytes()==original


def test_snapshot_installed_identity_is_a_separate_digest_bound_claim(fixture):
    identity=dict(channel='stable',base_version='1.7.0',commit='a'*40,tag='v1.7.0',installed_at='2026-10-09T00:00:00+00:00',source='github-release')
    (fixture['source']/'INSTALLATION.json').write_text(json.dumps(identity))
    fixture['snapshot']=fixture['source'].parent/'with-identity'
    created=writer.create(fixture['source'],fixture['snapshot'],'UPDATER_SNAPSHOT')
    assert created['creation_status']=='CREATED';fixture['digest']=created['MANIFEST_SHA256']
    sid=enrolled(fixture);value=catalog.load_record((fixture['catalog']/(sid+'.json')).read_bytes())
    assert value['snapshot_claims']['installed_identity']==identity
    assert value['operator_claims']['original_identity'] is None and value['operator_claims']['target_identity'] is None
    assert value['verified_facts']['snapshot_provenance_authenticated'] is False
    assert verify(fixture,sid)['verification_status']=='TRUSTED_SCOPE_VERIFIED'
