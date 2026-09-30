"""Authoritative config, immutable revisions, source and health races (offline)."""
import json
import re
import threading
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from core import auto_refresh, policy_engine as policy, refresh_schedule
from core.fixed_subscriptions import GenerationError
from core.source_errors import SourceError
from core.state import StateError, write_json
from conftest import LINK, post
from test_fixed_subscriptions import base, save, source, store
from test_external_sources import external_save, payload, remote, response, uploaded
from test_auto_health import observers, configure, state
from test_policy_engine import config


def selected(store, entry):
    from ruamel.yaml import YAML
    data=YAML(typ='safe').load(store.snapshot(entry['id'])[1])
    return {g['name']:g for g in data['proxy-groups']}


@pytest.mark.parametrize('version',[1,2,3])
def test_legacy_registry_read_migration_does_not_write_or_regenerate(store,base,response,version):
    entry=external_save(store,base,sources=[remote(refresh_interval_seconds=900)] if version>1 else [])
    key=entry['id'];files=store.directory/key/entry['revision']
    original_files={str(p.relative_to(files)):p.read_bytes() for p in files.rglob('*') if p.is_file()}
    data=json.loads(store.path.read_bytes());data['version']=version
    row=data['subscriptions'][key];row.pop('policy_config')
    if version==1:row.pop('sources')
    if version==2:
        for s in row['sources']:
            for field in refresh_schedule.FIELDS:s.pop(field,None)
    write_json(store.path,data);before=store.path.read_bytes();response['calls'].clear()
    migrated=store.get(key)
    assert migrated['policy_config']==policy.defaults()
    assert migrated['revision']==entry['revision'] and store.slug(migrated)==store.slug(entry)
    assert store.snapshot(key)[1]==original_files['current.yaml']
    assert store.list()==[migrated] and store.path.read_bytes()==before and not response['calls']
    assert {str(p.relative_to(files)):p.read_bytes() for p in files.rglob('*') if p.is_file()}==original_files
    # Public access statistics may write, but must not promote the schema.
    assert store.resolve(store.slug(entry))==original_files['current.yaml']
    raw=json.loads(store.path.read_bytes())
    assert raw['version']==version and 'policy_config' not in raw['subscriptions'][key]
    store.action(key,'disable');assert json.loads(store.path.read_bytes())['version']==5
    assert store.get(key)['policy_config']==policy.defaults()


@pytest.mark.parametrize('bad',[None,[],{},dict(policy.defaults(),extra=True),config('unknown'),config('fallback',tolerance=50)])
def test_v4_invalid_policy_state_fails_closed_no_reset(store,base,bad):
    entry=save(store,base);data=json.loads(store.path.read_bytes())
    data['subscriptions'][entry['id']]['policy_config']=bad;write_json(store.path,data)
    before=store.path.read_bytes()
    with pytest.raises(StateError):store.get(entry['id'])
    assert store.path.read_bytes()==before


@pytest.mark.parametrize('kind',policy.TYPES)
def test_fixed_save_revision_same_slug_and_exact_type_transitions(store,base,kind):
    custom='''proxy-groups:
- {name: '🇺🇸 美国节点', type: fallback, proxies: [DIRECT], url: 'http://client.local/check', interval: 111, lazy: false, icon: kept}
rules: ['MATCH,🇺🇸 美国节点']
'''.encode()
    fields=dict(source(),yaml_source='custom',policy_config=policy.defaults())
    first=save(store,base,config=fields,custom=custom);slug=store.slug(first)
    fields['policy_config']=config(kind)
    changed=save(store,base,first['id'],fields)
    assert changed['revision']!=first['revision'] and store.slug(changed)==slug and changed['token']==first['token']
    assert changed['policy_config']==policy.normalize(config(kind))
    group=selected(store,changed)['🇺🇸 美国节点']
    assert group['icon']=='kept'
    if kind=='preserve':assert group['type']=='fallback' and group['interval']==111 and 'DIRECT' in group['proxies']
    elif kind=='select':assert group['type']=='select' and 'DIRECT' in group['proxies'] and not set(policy.AUTO_FIELDS)&set(group)
    else:assert group['type']==kind and group['proxies']==['🇺🇸 First']


def test_fixed_sequential_transitions_preserve_rebuilds_authoritative_base(store,base):
    custom="proxy-groups: [{name: '🇺🇸 美国节点', type: select, proxies: [DIRECT], icon: kept}]\n".encode()
    fields=dict(source(),yaml_source='custom');entry=save(store,base,config=fields,custom=custom)
    original=store.snapshot(entry['id'])[1];slug=store.slug(entry)
    for kind in ['url-test','fallback','load-balance','select','preserve']:
        fields['policy_config']=config(kind)
        entry=save(store,base,entry['id'],fields)
        assert store.slug(entry)==slug and store._content(entry,'base.yaml')==custom
        group=selected(store,entry)['🇺🇸 美国节点']
        assert ('tolerance' in group)==(kind=='url-test') and ('strategy' in group)==(kind=='load-balance')
    assert store.snapshot(entry['id'])[1]==original


@pytest.mark.parametrize('operation',['refresh','refresh-all','auto','disable','enable','delete-uploaded'])
def test_source_reconstruction_keeps_policy_and_changes_only_current_candidates(store,base,response,operation):
    fields=source();fields['batch_nodes']='';fields['policy_config']=config('url-test','fallback')
    fields['special_groups']=['media']
    response['payload']=payload('Taiwan-A','Taiwan-B')
    entry=external_save(store,base,config=fields,sources=[remote(refresh_interval_seconds=900),uploaded()],
        uploads={1:payload('Singapore-upload')},clock=lambda:1_800_000_000)
    slug=store.slug(entry);identifier=entry['sources'][1]['id']
    response['payload']=payload('Taiwan-C','Taiwan-D')
    if operation=='auto':
        assert auto_refresh.run_once(store,base,clock=lambda:1_800_000_900)==0
        new=store.get(entry['id'])
    elif operation=='delete-uploaded':new=store.source_action(entry['id'],'delete',base,entry['sources'][2]['id'])
    else:new=store.source_action(entry['id'],operation,base,identifier if operation!='refresh-all' else None)
    assert new['policy_config']==entry['policy_config'] and store.slug(new)==slug
    current=selected(store,new)
    if operation in ('refresh','refresh-all','auto','enable'):
        assert current['🇹🇼 台湾节点']['proxies']==['🇹🇼 Taiwan-C','🇹🇼 Taiwan-D']
        assert b'Taiwan-A' not in store.snapshot(new['id'])[1]
    for g in current.values():
        if g['name']=='media':assert g['type']=='fallback' and g['proxies']==[n['name'] for n in YAML(typ='safe').load(store.snapshot(new['id'])[1])['proxies']]


@pytest.mark.parametrize('failure',['timeout','invalid','generation','metadata'])
def test_refresh_cache_and_transaction_failures_keep_policy_payload_and_last_good(store,base,response,monkeypatch,failure):
    fields=source();fields['batch_nodes']='';fields['policy_config']=config('url-test')
    response['payload']=payload('Taiwan-A','Taiwan-B')
    entry=external_save(store,base,config=fields,sources=[remote()]);slug=store.slug(entry)
    previous=store.snapshot(entry['id']);cache=store._payload(entry,entry['sources'][1]['id'])
    from core import fixed_subscriptions as fixed, generator
    if failure=='timeout':response['error']='timeout'
    elif failure=='invalid':response['payload']=b'PRIVATE INVALID'
    elif failure=='generation':monkeypatch.setattr(generator,'generate',lambda *args:{'success':False})
    else:
        def fail(*args):raise OSError('PRIVATE disk details')
        monkeypatch.setattr(fixed,'write_json',fail)
    if failure in ('generation','metadata'):
        with pytest.raises((GenerationError,StateError)):
            store.source_action(entry['id'],'refresh-all',base)
        assert store.snapshot(entry['id'])==previous
    else:
        new=store.source_action(entry['id'],'refresh-all',base)
        assert new['sources'][1]['using_cache'] and new['policy_config']==entry['policy_config']
        assert store.snapshot(entry['id'])[1]==previous[1]
        assert store._payload(new,entry['sources'][1]['id'])==cache
    assert store.slug(store.get(entry['id']))==slug


@pytest.mark.parametrize('kind',['endpoint','proxy'])
@pytest.mark.parametrize('trigger',['manual','auto'])
def test_policy_only_save_preserves_observations_and_conflicts_paused_health(store,base,observers,kind,trigger):
    entry=save(store,base);key=entry['id'];worker=observers[kind]
    configure(worker,key);worker.check(key)
    before=state(worker,key);slug=store.slug(entry)
    observations=worker.describe(key)['rows']
    started,resume=threading.Event(),threading.Event();errors=[]
    original=worker.probe if kind=='endpoint' else worker.runner
    def pause(*args):started.set();assert resume.wait(5);return original(*args)
    if kind=='endpoint':worker.probe=pause
    else:worker.runner=pause
    if trigger=='auto':observers['now']+=900
    def run():
        try:worker.check(key,trigger=trigger)
        except Exception as error:errors.append(error)
    thread=threading.Thread(target=run);thread.start();assert started.wait(2)
    try:
        fields=dict(source(),policy_config=config('url-test','fallback'))
        changed=save(store,base,key,fields)
        assert state(worker,key)==before # Policy save never mutates schedule/observations.
        assert worker.describe(key)['rows']==observations
        assert store.slug(changed)==slug and selected(store,changed)['🇺🇸 美国节点']['type']=='url-test'
    finally:resume.set();thread.join(5)
    assert not thread.is_alive() and len(errors)==1 and errors[0].code=='conflict'
    after=state(worker,key)
    assert after['nodes']==before['nodes'] and after['scheduler_failures']==before['scheduler_failures']
    assert store.get(key)['revision']==changed['revision']
    assert worker.describe(key)['rows']==observations


@pytest.mark.parametrize('winner',['policy','refresh'])
def test_policy_save_and_auto_provider_refresh_never_overwrite_newer_config(store,base,response,monkeypatch,winner):
    from core import source_fetch
    response['payload']=payload('Taiwan-A','Taiwan-B')
    fields=source();fields['batch_nodes']='';fields['policy_config']=config('select')
    entry=external_save(store,base,config=fields,sources=[remote(refresh_interval_seconds=900)],clock=lambda:1_800_000_000)
    started,resume=threading.Event(),threading.Event();errors=[]
    def fetch(url):
        if threading.current_thread().name=='policy-race':
            started.set();assert resume.wait(5)
            return payload('Taiwan-stale')
        return payload('Taiwan-C','Taiwan-D')
    monkeypatch.setattr(source_fetch,'fetch',fetch)
    changed_fields=dict(fields,policy_config=config('fallback'))
    def stale():
        try:
            if winner=='policy':store.refresh_sources(entry,[entry['sources'][1]['id']],base,clock=lambda:1_800_000_900)
            else:external_save(store,base,entry,changed_fields,sources=entry['sources'][1:],expected=entry)
        except Exception as error:errors.append(error)
    thread=threading.Thread(target=stale,name='policy-race');thread.start();assert started.wait(2)
    try:
        if winner=='policy':new=external_save(store,base,entry,changed_fields,sources=entry['sources'][1:],expected=entry)
        else:
            assert auto_refresh.run_once(store,base,clock=lambda:1_800_000_900)==0
            new=store.get(entry['id'])
    finally:resume.set();thread.join(5)
    assert not thread.is_alive() and len(errors)==1 and isinstance(errors[0],SourceError) and errors[0].code=='conflict'
    assert store.get(entry['id'])==new and store.slug(new)==store.slug(entry)
    group=selected(store,new)['🇹🇼 台湾节点']
    assert group['type']==('fallback' if winner=='policy' else 'select')
    assert group['proxies']==['🇹🇼 Taiwan-C','🇹🇼 Taiwan-D']
    assert store._payload(new,entry['sources'][1]['id'])==payload('Taiwan-C','Taiwan-D')


def test_bad_node_observations_are_never_filtered_or_ranked_by_policy(store,base,observers):
    fields=source();fields['batch_nodes']+='\nUS|Second|'+LINK.replace('example.com','second.example')
    entry=save(store,base,config=fields);worker=observers['endpoint'];configure(worker,entry['id'])
    observers['endpoint_error']='connect_failed'
    for _ in range(3):worker.check(entry['id'])
    assert worker.describe(entry['id'])['counts']['unhealthy']==2
    old=worker.path.read_bytes()
    fields['policy_config']=config('fallback')
    new=save(store,base,entry['id'],fields)
    assert selected(store,new)['🇺🇸 美国节点']['proxies']==['🇺🇸 First','🇺🇸 Second']
    assert worker.path.read_bytes()==old


@pytest.mark.parametrize('kind',policy.TYPES)
def test_normal_generate_uses_existing_temporary_security(web,logged_in,kind):
    values=dict(batch_nodes='US|Node|'+LINK,policy_country_groups_type=kind)
    response=post(logged_in,'/process',values,follow_redirects=True)
    assert response.status_code==200
    match=re.search(rb'id="download-url"[^>]+value="([^"]+)"',response.data);assert match
    url=match.group(1).decode();path='/t/'+url.rsplit('/t/',1)[1]
    public=web.app.test_client().get(path);assert public.status_code==200
    from ruamel.yaml import YAML
    group=next(g for g in YAML(typ='safe').load(public.data)['proxy-groups'] if g['name']=='🇺🇸 美国节点')
    assert group['type']==('select' if kind=='preserve' else kind)
    assert web.app.test_client().get(path+'invalid').status_code==404


def test_fixed_form_restores_saved_and_failed_policy_public_s_is_atomic(web,logged_in):
    from test_fixed_views import create
    first=create(web,logged_in,policy_country_groups_type='url-test',policy_country_groups_url='http://client.local/check',
        policy_country_groups_interval='600',policy_country_groups_lazy='false',policy_country_groups_tolerance='70')
    store=web.fixed_subscriptions;path=f'/fixed-subscriptions/{first["id"]}/edit';slug=store.slug(first)
    page=logged_in.get(path).data
    assert b'value="url-test" selected' in page and b'value="600"' in page and b'value="70"' in page
    before=store.snapshot(first['id'])
    response=post(logged_in,path,dict(name='Changed',prefix=first['prefix'],yaml_source='custom',batch_nodes='TW|Changed|'+LINK,
        policy_country_groups_type='url-test',policy_country_groups_url='http://client.local/edited',policy_country_groups_interval='0',
        policy_country_groups_lazy='false',policy_country_groups_tolerance='80',
        aux_nodes=json.dumps([dict(country='SG',name='Keep failed auxiliary',link=LINK)])))
    assert response.status_code==400 and b'value="0"' in response.data and b'value="80"' in response.data
    assert b'http://client.local/edited' in response.data and b'Keep failed auxiliary' in response.data
    assert store.snapshot(first['id'])==before
    changed=dict(name='Changed',prefix=first['prefix'],yaml_source='custom',batch_nodes='TW|Changed|'+LINK,
        policy_country_groups_type='load-balance')
    assert post(logged_in,path,changed).status_code==303
    public=web.app.test_client().get('/s/'+slug)
    assert public.status_code==200 and public.data==store.snapshot(first['id'])[1]
    assert b'load-balance' in public.data and b'round-robin' in public.data and b'Changed' in public.data
    assert store.slug(store.get(first['id']))==slug


def test_normal_invalid_policy_redisplayed_without_session_persistence(web,logged_in):
    values=dict(batch_nodes='US|Node|'+LINK,policy_country_groups_type='url-test',
        policy_country_groups_interval='0',policy_country_groups_url='http://client.local/check')
    response=post(logged_in,'/process',values)
    assert response.status_code==400 and b'value="0"' in response.data and b'http://client.local/check' in response.data
    assert not list(Path(web.DIR_OUTPUTS).glob('*.yaml'))
    with logged_in.session_transaction() as session:assert 'client.local' not in str(dict(session))
    assert b'value="preserve" selected' in logged_in.get('/').data


def test_fixed_empty_candidate_failure_preserves_committed_revision(store,base):
    first=save(store,base,config=dict(source(),policy_config=config('url-test','fallback'),special_groups=['media']))
    old=store.snapshot(first['id']);registry=store.path.read_bytes();slug=store.slug(first)
    empty=dict(source(),batch_nodes='',policy_config=config('url-test','fallback'),special_groups=['media'])
    with pytest.raises(SourceError):save(store,base,first['id'],empty)
    assert store.snapshot(first['id'])==old and store.path.read_bytes()==registry
    assert store.slug(store.get(first['id']))==slug
