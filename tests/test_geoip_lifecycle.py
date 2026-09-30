"""Fixed v6, cached source reconstruction, ephemeral UI and private settings."""
import copy
import io
import json
import threading
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from core import auto_refresh, generator, geoip, geoip_store, health_policy, source_fetch
from core.geoip_store import GeoIPStore
from core.state import StateError, file_lock, write_json
from conftest import LINK, post
from test_fixed_subscriptions import base, parsed, save, source, store
from test_external_sources import external_save, remote, response, uploaded
from test_geoip import readers, link
from test_policy_engine import config as policies


@pytest.fixture
def fixed_geoip(store,readers):
    database=GeoIPStore(store.state,clock=lambda:1_800_000_000)
    database.upload('country.mmdb',io.BytesIO(b'SYNTHETIC:SG'))
    return database


def fields(**changes):
    return dict(dict(source(),batch_nodes='Opaque|'+link(),country_detection={'geoip':'literal-ip'},
        policy_config=policies('url-test'),health_policy=health_policy.defaults()),**changes)


def config(store,key):
    return YAML(typ='safe').load(store.snapshot(key)[1])


def group(store,key,name='🇸🇬 狮城节点'):
    return next(g['proxies'] for g in config(store,key)['proxy-groups'] if g['name']==name)


@pytest.mark.parametrize('operation',['refresh','refresh-all','auto','enable','disable','delete'])
def test_every_source_reconstruction_keeps_geoip_and_url(store,base,response,fixed_geoip,operation):
    response['payload']=(link('1.1.1.1')+'#Opaque-remote').encode()
    entry=external_save(store,base,config=fields(),sources=[remote(refresh_interval_seconds=900),uploaded()],
        uploads={1:(link('9.9.9.9')+'#Opaque-upload').encode()},clock=lambda:1_800_000_000)
    assert group(store,entry['id'])==['🇸🇬 Opaque','🇸🇬 Opaque-remote','🇸🇬 Opaque-upload']
    identifier=entry['sources'][1]['id'];slug=store.slug(entry)
    response['payload']=(link('1.1.1.1')+'#Opaque-new').encode()
    if operation=='auto':
        assert auto_refresh.run_once(store,base,clock=lambda:1_800_000_900)==0
        changed=store.get(entry['id'])
    else:changed=store.source_action(entry['id'],operation,base,identifier if operation!='refresh-all' else None)
    assert changed['country_detection']=={'geoip':'literal-ip'} and store.slug(changed)==slug
    assert changed['policy_config']==entry['policy_config'] and changed['health_policy']==entry['health_policy']
    names=group(store,entry['id'])
    if operation in ('refresh','refresh-all','auto','enable'):assert '🇸🇬 Opaque-new' in names and '🇸🇬 Opaque-remote' not in names
    else:assert names==['🇸🇬 Opaque','🇸🇬 Opaque-upload']


@pytest.mark.parametrize('format',['raw','base64','clash'])
def test_fixed_manual_auxiliary_and_external_one_reader(store,base,response,fixed_geoip,readers,format):
    import base64
    payload=(link('1.1.1.1')+'#Opaque-source').encode()
    if format=='base64':payload=base64.b64encode(payload)
    if format=='clash':payload=b'proxies: [{name: Opaque-source, type: vless, server: 1.1.1.1, port: 443, uuid: test-only}]'
    response['payload']=payload;before=len(readers['opened'])
    field=fields(aux_nodes=[dict(country='TW',name='Manual auxiliary',link=link('9.9.9.9'))])
    entry=external_save(store,base,config=field,sources=[remote(format=format)])
    assert len(readers['opened'])==before+1 and group(store,entry['id'])==['🇸🇬 Opaque','🇸🇬 Opaque-source']
    assert group(store,entry['id'],'🇹🇼 台湾节点')==['🇹🇼 Manual auxiliary']


def test_database_replacement_removal_no_fixed_or_health_mutation_then_explicit_save(store,base,fixed_geoip):
    entry=save(store,base,config=fields());key=entry['id'];before=store.snapshot(key);registry=store.path.read_bytes();slug=store.slug(entry)
    health=store.state/'node_health.json';health.write_bytes(b'opaque historical state');health.chmod(0o600)
    fixed_geoip.upload('new.mmdb',io.BytesIO(b'SYNTHETIC:TW'))
    assert store.snapshot(key)==before and store.path.read_bytes()==registry and health.read_bytes()==b'opaque historical state'
    new=save(store,base,key,fields());assert group(store,key,'🇹🇼 台湾节点')==['🇹🇼 Opaque'] and store.slug(new)==slug
    fixed_geoip.remove();again=store.snapshot(key)
    assert store.snapshot(key)==again and store.get(key)['country_detection']=={'geoip':'literal-ip'}
    new=save(store,base,key,fields());assert config(store,key)['proxies'][0]['name']=='🌐 Opaque' and store.slug(new)==slug
    assert health.read_bytes()==b'opaque historical state'


def test_health_reconcile_preserves_geoip_uses_cached_base_and_no_network(store,base,response,fixed_geoip,monkeypatch):
    response['payload']=(link('1.1.1.1')+'#Opaque-source').encode()
    field=fields(health_policy=dict(mode='exclude-unhealthy',max_age_seconds=172800,min_candidates=2))
    entry=external_save(store,base,config=field,sources=[remote()]);key=entry['id'];before=store.snapshot(key);sources=entry['sources']
    def forbidden(*args,**kw):raise AssertionError('reconcile cannot fetch')
    monkeypatch.setattr(source_fetch,'fetch',forbidden);base.write_bytes(b'BROKEN changed default')
    assert store.reconcile_health_policy(key)=='unavailable'
    assert store.snapshot(key)[1]==before[1] and store.get(key)['revision']==entry['revision']
    assert store.get(key)['country_detection']==field['country_detection'] and store.get(key)['sources']==sources
    fixed_geoip.upload('new.mmdb',io.BytesIO(b'SYNTHETIC:TW'))
    assert store.snapshot(key)[1]==before[1]
    assert store.reconcile_health_policy(key)=='unavailable'
    assert group(store,key,'🇹🇼 台湾节点')==['🇹🇼 Opaque','🇹🇼 Opaque-source']
    assert store.slug(store.get(key))==store.slug(entry)


@pytest.mark.parametrize('version',[1,2,3,4,5])
def test_v1_v5_migration_off_preserves_every_revision_read_and_public_stats(store,base,response,fixed_geoip,version):
    entry=external_save(store,base,config=fields(),sources=[remote(refresh_interval_seconds=900)] if version>1 else [])
    key=entry['id'];data=json.loads(store.path.read_bytes());data['version']=version;row=data['subscriptions'][key]
    row.pop('country_detection')
    if version<5:row.pop('health_policy');row.pop('health_policy_audit')
    if version<4:row.pop('policy_config')
    if version==1:row.pop('sources')
    if version==2:
        from core.refresh_schedule import FIELDS
        for item in row['sources']:
            for field in FIELDS:item.pop(field,None)
    write_json(store.path,data);before=store.path.read_bytes();snapshot=store.snapshot(key)
    files={p.relative_to(store.directory):p.read_bytes() for p in (store.directory/key/entry['revision']).rglob('*') if p.is_file()}
    read=store.get(key)
    assert read['country_detection']=={'geoip':'off'} and store.slug(read)==store.slug(entry)
    assert store.path.read_bytes()==before and store.snapshot(key)==snapshot
    assert {p.relative_to(store.directory):p.read_bytes() for p in (store.directory/key/entry['revision']).rglob('*') if p.is_file()}==files
    store.resolve(store.slug(entry));raw=json.loads(store.path.read_bytes())
    assert raw['version']==version and 'country_detection' not in raw['subscriptions'][key]
    store.action(key,'disable');assert json.loads(store.path.read_bytes())['version']==6


@pytest.mark.parametrize('bad',[None,{},[],{'geoip':'dns'},{'geoip':True},{'geoip':'off','extra':True}])
def test_authoritative_v6_invalid_mode_fails_closed(store,base,bad):
    entry=save(store,base);data=json.loads(store.path.read_bytes());data['subscriptions'][entry['id']]['country_detection']=bad
    write_json(store.path,data);before=store.path.read_bytes()
    with pytest.raises(StateError):store.list()
    assert store.path.read_bytes()==before


def test_geoip_reader_never_holds_fixed_lock_and_paused_parse_does_not_block_public(store,base,fixed_geoip,readers,monkeypatch):
    entry=save(store,base,config=fields());started,resume=threading.Event(),threading.Event();result=[]
    original=readers['factory']
    def open_reader(data):
        with file_lock(store.lock,blocking=False):pass
        if threading.current_thread().name=='geoip-race':started.set();assert resume.wait(5)
        return original(data)
    monkeypatch.setattr(geoip,'open_reader',open_reader)
    thread=threading.Thread(name='geoip-race',target=lambda:result.append(save(store,base,entry['id'],fields())))
    thread.start();assert started.wait(2)
    try:assert store.resolve(store.slug(entry))==store.snapshot(entry['id'])[1]
    finally:resume.set();thread.join(5)
    assert not thread.is_alive() and len(result)==1


def test_settings_auth_csrf_status_upload_invalid_replace_and_remove(web,logged_in,readers):
    client=web.app.test_client()
    assert client.get('/settings').status_code==302
    assert client.get('/settings/upload').status_code==405 and client.get('/settings/remove').status_code==405
    assert post(client,'/settings/upload',{'geoip_file':(io.BytesIO(b'SYNTHETIC:SG'),'country.mmdb')}).status_code==302
    assert b'Not installed' in logged_in.get('/settings').data
    assert logged_in.post('/settings/upload',data={'geoip_file':(io.BytesIO(b'SYNTHETIC:SG'),'country.mmdb')}).status_code==303
    assert not web.geoip_store.path.exists() # CSRF rejected and not replayed.
    assert post(logged_in,'/settings/upload',{'geoip_file':(io.BytesIO(b'SYNTHETIC:SG'),'../../country.mmdb')}).status_code==303
    old=(web.geoip_store.path.read_bytes(),web.geoip_store.settings.read_bytes())
    page=logged_in.get('/settings');assert page.headers['Cache-Control']=='no-store' and page.headers['Referrer-Policy']=='no-referrer'
    assert b'Synthetic-Country' in page.data and b'data-geoip-status>Ready' in page.data and b'UTC' in page.data
    assert str(web.geoip_store.path).encode() not in page.data
    assert post(logged_in,'/settings/upload',{'geoip_file':(io.BytesIO(b'PRIVATE broken'),'secret.mmdb')}).status_code==400
    assert (web.geoip_store.path.read_bytes(),web.geoip_store.settings.read_bytes())==old
    assert b'PRIVATE' not in logged_in.get('/settings').data
    assert post(logged_in,'/settings/remove').status_code==303 and not web.geoip_store.path.exists()


def test_preview_generate_and_fixed_saved_mode_warning_and_errors(web,logged_in,readers):
    preview=post(logged_in,'/parse-nodes',{'batch_nodes':'Opaque|'+link(),'country_geoip':'literal-ip'}).json
    assert preview['nodes'][0]['country']=='UNKNOWN' and preview['nodes'][0]['status']=='Warning'
    page=logged_in.get('/');assert b'No GeoIP database is installed' in page.data and b'value="off" selected' in page.data
    post(logged_in,'/settings/upload',{'geoip_file':(io.BytesIO(b'SYNTHETIC:SG'),'country.mmdb')})
    preview=post(logged_in,'/parse-nodes',{'batch_nodes':'Opaque|'+link(),'country_geoip':'literal-ip'}).json
    assert preview['nodes'][0]['country']=='SG' and preview['nodes'][0]['source']=='GeoIP' and preview['nodes'][0]['status']=='Ready'
    assert '8.8.8.8' not in json.dumps(preview)
    from test_fixed_views import create
    entry=create(web,logged_in,batch_nodes='Opaque|'+link(),country_geoip='literal-ip',policy_country_groups_type='fallback')
    store=web.fixed_subscriptions;key=entry['id'];before=store.snapshot(key);path=f'/fixed-subscriptions/{key}/edit'
    assert entry['country_detection']=={'geoip':'literal-ip'} and group(store,key)==['🇸🇬 Opaque']
    bad=post(logged_in,path,dict(name=entry['name'],prefix=entry['prefix'],yaml_source='custom',batch_nodes='Opaque|'+link(),country_geoip='dns'))
    assert bad.status_code==400 and b'value="dns" selected' in bad.data and store.snapshot(key)==before
    post(logged_in,'/settings/remove');page=logged_in.get(path)
    assert b'value="literal-ip" selected' in page.data and b'No GeoIP database is installed' in page.data and store.snapshot(key)==before
    response=post(logged_in,'/process',{'batch_nodes':'Opaque|'+link(),'country_geoip':'literal-ip'},follow_redirects=True)
    assert response.status_code==200
    assert b'value="off" selected' in logged_in.get('/').data
    with logged_in.session_transaction() as data:
        assert 'country_geoip' not in str(dict(data)) and 'country_detection' not in str(dict(data))


def test_update_backup_and_uninstall_preserve_entire_geoip_state(tmp_path):
    import subprocess
    root=Path(__file__).resolve().parents[1];state=tmp_path/'state';state.mkdir(mode=0o700)
    (state/'geoip').mkdir(mode=0o700);(state/'geoip'/'active.mmdb').write_bytes(b'private administrator database')
    (state/'geoip'/'active.mmdb').chmod(0o600);(state/'settings.json').write_bytes(b'{"version":1}');(state/'settings.json').chmod(0o600)
    backup=tmp_path/'backup'
    subprocess.run(['bash','-c','source "$1"; backup_private_state "$2" "$3"','test',str(root/'scripts/deploy-common.sh'),str(state),str(backup)],check=True)
    assert (backup/'geoip'/'active.mmdb').read_bytes()==(state/'geoip'/'active.mmdb').read_bytes()
    assert (backup/'settings.json').read_bytes()==(state/'settings.json').read_bytes()
    assert (backup/'geoip'/'active.mmdb').stat().st_mode&0o777==0o600
    assert 'backup_private_state "${INSTALL_DIR}/state"' in (root/'update.sh').read_text()
    assert 'backup_private_state "${INSTALL_DIR}/state"' in (root/'uninstall.sh').read_text()


def test_geoip_country_change_preserves_proxy_identity_and_health_filtering(store,base,fixed_geoip):
    from types import SimpleNamespace
    from core.proxy_health import ProxyHealth
    from test_proxy_health import public_resolver
    clock=lambda:1_800_000_000
    batch='\n'.join(name+'|'+link(host) for name,host in [('Opaque-A','8.8.8.8'),('Opaque-B','1.1.1.1'),('Opaque-C','9.9.9.9')])
    value=fields(batch_nodes=batch,country_detection={'geoip':'off'},health_policy=dict(mode='exclude-unhealthy',max_age_seconds=172800,min_candidates=2))
    entry=store.save(None,'Geo Health','geo-health',value,parsed(value),base,clock=clock);key=entry['id']
    def runner(binary,nodes,settings,directory):
        return {node['fingerprint']:dict(kind='failure' if node['config']['server']=='1.1.1.1' else 'success',
            latency_ms=None if node['config']['server']=='1.1.1.1' else 10,
            error='proxy_failed' if node['config']['server']=='1.1.1.1' else None) for node in nodes}
    worker=ProxyHealth(store,engine=SimpleNamespace(binary=store.state/'unused',status=lambda:{'status':'COMPATIBLE'}),
        clock=clock,runner=runner,resolver=public_resolver)
    worker.settings(key,'manual',True)
    for _ in range(3):worker.check(key)
    before=worker.path.read_bytes();slug=store.slug(store.get(key))
    value['country_detection']={'geoip':'literal-ip'}
    updated=store.save(key,entry['name'],entry['prefix'],value,parsed(value),base,clock=clock)
    assert group(store,key)==['🇸🇬 Opaque-A','🇸🇬 Opaque-C']
    assert [n['name'] for n in config(store,key)['proxies']]==['🇸🇬 Opaque-A','🇸🇬 Opaque-B','🇸🇬 Opaque-C']
    assert worker.path.read_bytes()==before and worker.describe(key)['counts']['unhealthy']==1
    assert store.slug(updated)==slug and updated['health_policy_audit']['candidates_excluded']==1


def test_settings_oversized_request_recovers_on_settings_page(web,logged_in,readers):
    post(logged_in,'/settings/upload',{'geoip_file':(io.BytesIO(b'SYNTHETIC:SG'),'country.mmdb')})
    before=web.geoip_store.path.read_bytes();web.app.config['MAX_CONTENT_LENGTH']=1024
    response=post(logged_in,'/settings/upload',{'geoip_file':(io.BytesIO(b'x'*2048),'big.mmdb')})
    assert response.status_code==303 and response.headers['Location'].endswith('/settings')
    assert b'GeoIP upload too large' in logged_in.get('/settings').data and web.geoip_store.path.read_bytes()==before
