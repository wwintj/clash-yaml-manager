"""Offline checks/reconciliation, immutable Fixed revisions, lock order and races."""
import copy
import json
import logging
import os
from pathlib import Path
import socket
import threading
from types import SimpleNamespace

import pytest
from ruamel.yaml import YAML

from core import auto_health, auto_refresh, fixed_subscriptions, generator, health_policy as hp, health_schedule, node_health, source_fetch
from core.proxy_health import ProxyHealth, ProxyHealthError, unknown
from core.state import StateError, file_lock, write_json
from conftest import LINK, post
from test_fixed_subscriptions import base, parsed, save, source, store
from test_external_sources import external_save, payload, remote, response, uploaded
from test_policy_engine import config as policies
from test_proxy_health import public_resolver
from test_health_policy import settings


@pytest.fixture
def scenario(store,base):
    data=dict(now=1_800_000_000,outcomes={'b.example':'failure'},calls=[])
    fields=source();fields['batch_nodes']='\n'.join('US|'+n+'|'+LINK.replace('example.com',n.lower()+'.example') for n in ['A','B','C','D'])
    fields.update(policy_config=policies('fallback','select'),special_groups=['media'],health_policy=settings())
    entry=store.save(None,'Health policy','health-policy',fields,parsed(fields),base,clock=lambda:data['now'])
    def run(binary,nodes,settings,directory):
        data['calls'].append(copy.deepcopy(nodes))
        results={}
        for node in nodes:
            kind=data['outcomes'].get(node['config']['server'],'success')
            results[node['fingerprint']]=dict(kind=kind,latency_ms=10 if kind=='success' else None,
                error={'success':None,'failure':'proxy_failed','unsupported':'unsupported_config'}[kind])
        return results
    worker=ProxyHealth(store,engine=SimpleNamespace(binary=store.state.parent/'bin/mihomo',status=lambda:dict(status='COMPATIBLE')),
        runner=run,clock=lambda:data['now'],resolver=public_resolver)
    worker.settings(entry['id'],'manual',True)
    data.update(entry=entry,fields=fields,worker=worker)
    return data


def content(store,key):
    return YAML(typ='safe').load(store.snapshot(key)[1])


def members(store,key,name='🇺🇸 美国节点'):
    return next(g['proxies'] for g in content(store,key)['proxy-groups'] if g['name']==name)


def check_three(scenario):
    for _ in range(3):scenario['worker'].check(scenario['entry']['id'])


def resave(store,base,scenario,**changes):
    fields=copy.deepcopy(scenario['fields']);fields.update(changes)
    old=store.get(scenario['entry']['id'])
    return store.save(old['id'],old['name'],old['prefix'],fields,parsed(fields),base,clock=lambda:scenario['now'])


def test_suspect_threshold_reactive_exclusion_recovery_same_url_all_definitions_retained(store,base,scenario):
    key=scenario['entry']['id'];worker=scenario['worker'];first=store.get(key);slug=store.slug(first)
    for failures in [1,2]:
        worker.check(key)
        assert members(store,key)==['🇺🇸 A','🇺🇸 B','🇺🇸 C','🇺🇸 D']
        assert store.get(key)['revision']==first['revision'] and store.get(key)['updated_at']==first['updated_at']
        assert worker.describe(key)['counts']['suspect']==1
    worker.check(key);filtered=store.get(key)
    assert filtered['revision']!=first['revision'] and store.slug(filtered)==slug
    assert members(store,key)==['🇺🇸 A','🇺🇸 C','🇺🇸 D']
    assert members(store,key,'media')==members(store,key,'🚀 手动切换')==['🇺🇸 A','🇺🇸 B','🇺🇸 C','🇺🇸 D']
    assert [node['name'] for node in content(store,key)['proxies']]==['🇺🇸 A','🇺🇸 B','🇺🇸 C','🇺🇸 D']
    audit=filtered['health_policy_audit'];assert audit['result']=='updated' and audit['candidates_excluded']==1
    assert filtered['sources']==first['sources'] and filtered['health_policy']==first['health_policy']
    stable=store.get(key);scenario['now']+=1;worker.check(key)
    assert store.get(key)['revision']==stable['revision'] and store.get(key)['updated_at']==stable['updated_at']
    assert len(scenario['calls'][-1])==4 # Excluded nodes are still probed and can recover.
    scenario['outcomes']['b.example']='success';worker.check(key)
    recovered=store.get(key)
    assert members(store,key)==['🇺🇸 A','🇺🇸 B','🇺🇸 C','🇺🇸 D'] and store.slug(recovered)==slug
    assert recovered['revision']!=filtered['revision'] and worker.describe(key)['counts']['healthy']==4


@pytest.mark.parametrize('minimum,count,dead,expected,failopen',[(2,3,['b.example','c.example'],3,1),(2,1,['a.example'],1,1),(1,2,['b.example'],1,0)])
def test_minimum_one_node_and_fail_open_audit(store,base,scenario,minimum,count,dead,expected,failopen):
    scenario['outcomes']={host:'failure' for host in dead}
    fields=copy.deepcopy(scenario['fields']);fields['batch_nodes']='\n'.join(fields['batch_nodes'].splitlines()[:count])
    fields['health_policy']=settings(min_candidates=minimum)
    scenario['fields']=fields;resave(store,base,scenario)
    check_three(scenario);key=scenario['entry']['id']
    assert len(members(store,key))==expected
    audit=store.get(key)['health_policy_audit'];assert audit['groups_fail_open']==failopen
    if failopen:assert audit['result']=='fail-open'


@pytest.mark.parametrize('kind',['preserve','select'])
def test_manual_policy_no_reconcile_churn(store,base,scenario,kind):
    resave(store,base,scenario,policy_config=policies(kind,kind))
    before=store.get(scenario['entry']['id']);raw=store.snapshot(before['id'])[1]
    check_three(scenario)
    assert store.get(before['id'])==before and store.snapshot(before['id'])[1]==raw


def test_off_default_never_reads_health_and_preserves_policy_golden(store,base,scenario,monkeypatch):
    def forbidden(*args):raise AssertionError('Off must not read observations')
    monkeypatch.setattr(hp,'snapshot',forbidden)
    changed=resave(store,base,scenario,health_policy=hp.defaults())
    before=store.path.read_bytes();scenario['worker'].check(changed['id'])
    assert store.path.read_bytes()==before
    assert members(store,changed['id'])==['🇺🇸 A','🇺🇸 B','🇺🇸 C','🇺🇸 D']


def test_endpoint_health_cannot_exclude(store,base,scenario):
    key=scenario['entry']['id'];clock=lambda:scenario['now']
    endpoint=node_health.NodeHealth(store,clock=clock,probe=lambda *_:dict(error='connection_refused',latency_ms=None))
    endpoint.settings(key,'manual')
    for _ in range(3):endpoint.check(key)
    assert endpoint.describe(key)['counts']['unhealthy']==4
    before=store.snapshot(key)[1]
    assert store.reconcile_health_policy(key,clock=clock)=='unchanged'
    assert store.snapshot(key)[1]==before and len(members(store,key))==4


def test_periodic_stale_restore_without_new_probe_disabled_pause_and_reenable(store,base,scenario,monkeypatch):
    check_three(scenario);key=scenario['entry']['id'];slug=store.slug(store.get(key))
    fields=copy.deepcopy(scenario['fields']);fields['health_policy']=settings(max_age_seconds=3600)
    resave(store,base,scenario,health_policy=fields['health_policy'])
    before=store.get(key);calls=len(scenario['calls'])
    # Exact max-age remains excluded; scans contain no due jobs (Manual mode).
    scenario['now']+=3600
    assert auto_health.run_once(store,proxy=scenario['worker'],clock=lambda:scenario['now'])==0
    assert members(store,key)==['🇺🇸 A','🇺🇸 C','🇺🇸 D'] and store.get(key)['revision']==before['revision']
    store.action(key,'disable');snapshot=store.snapshot(key)
    scenario['now']+=1
    auto_health.run_once(store,proxy=scenario['worker'],clock=lambda:scenario['now'])
    assert store.snapshot(key)==snapshot
    store.action(key,'enable')
    auto_health.run_once(store,proxy=scenario['worker'],clock=lambda:scenario['now'])
    assert len(members(store,key))==4 and store.slug(store.get(key))==slug
    assert len(scenario['calls'])==calls


def test_auto_proxy_completion_reconciles_without_changing_health_or_source_schedule(store,base,scenario):
    worker=scenario['worker'];key=scenario['entry']['id'];worker.settings(key,'automatic',True,interval_seconds=900)
    for _ in range(3):
        scenario['now']+=900
        assert auto_health.run_once(store,proxy=worker,clock=lambda:scenario['now'])==0
    assert len(members(store,key))==3 and worker.describe(key)['counts']['unhealthy']==1
    scheduled=worker.scheduled_entries()[key]
    assert scheduled['last_job_result']=='success' and scheduled['scheduler_failures']==0
    assert scheduled['next_check_at']==scenario['now']+900
    assert store.get(key)['sources']==scenario['entry']['sources']


@pytest.mark.parametrize('fault',['missing','json','permissions','symlink','fifo','busy','read-error'])
def test_auxiliary_unavailable_always_fails_open_without_repair(store,base,scenario,monkeypatch,fault):
    check_three(scenario);key=scenario['entry']['id'];path=scenario['worker'].path
    if fault=='missing':path.unlink()
    elif fault=='json':path.write_text('{PRIVATE broken')
    elif fault=='permissions':path.chmod(0o644)
    elif fault=='symlink':
        other=path.with_suffix('.original');path.rename(other);path.symlink_to(other)
    elif fault=='fifo':path.unlink();os.mkfifo(path,0o600)
    elif fault=='read-error':
        monkeypatch.setattr(ProxyHealth,'_read',lambda *_:(_ for _ in ()).throw(OSError('PRIVATE')))
    before=path.read_bytes() if path.exists() and not path.is_fifo() else None
    if fault=='busy':
        with file_lock(scenario['worker'].lock):resave(store,base,scenario)
    else:resave(store,base,scenario)
    assert len(members(store,key))==4
    assert store.get(key)['health_policy_audit']['result']=='unavailable'
    if before is not None:assert path.read_bytes()==before
    if fault=='missing':assert not path.exists()
    if fault=='permissions':assert path.stat().st_mode&0o777==0o644
    if fault=='symlink':assert path.is_symlink()
    if fault=='fifo':assert path.is_fifo()


def test_missing_health_file_enabled_create_does_not_create_auxiliary_state(store,base):
    fields=dict(source(),policy_config=policies('url-test'),health_policy=settings())
    entry=store.save(None,'Missing','missing',fields,parsed(fields),base)
    assert len(members(store,entry['id']))==1 and not (store.state/'proxy_health.json').exists()
    assert entry['health_policy_audit']['result']=='unavailable'


@pytest.mark.parametrize('version',[1,2,3,4])
def test_v1_v4_read_migration_off_without_rewrite_or_yaml_changes(store,base,response,version):
    fields=dict(source(),policy_config=policies('url-test'))
    entry=external_save(store,base,config=fields,sources=[remote(refresh_interval_seconds=900)] if version>1 else [])
    data=json.loads(store.path.read_bytes());data['version']=version;row=data['subscriptions'][entry['id']]
    row.pop('health_policy');row.pop('health_policy_audit')
    if version<4:row.pop('policy_config')
    if version==1:row.pop('sources')
    elif version==2:
        from core.refresh_schedule import FIELDS
        for item in row['sources']:
            for field in FIELDS:item.pop(field,None)
    write_json(store.path,data);before=store.path.read_bytes();yaml=store.snapshot(entry['id'])[1]
    migrated=store.get(entry['id']);response['calls'].clear()
    assert migrated['health_policy']==hp.defaults() and migrated['health_policy_audit']==hp.audit_defaults()
    assert migrated['policy_config']==entry['policy_config'] if version==4 else migrated['policy_config']==policies()
    assert migrated['revision']==entry['revision'] and store.slug(migrated)==store.slug(entry)
    auto_health.run_once(store)
    assert store.path.read_bytes()==before and store.snapshot(entry['id'])[1]==yaml and not response['calls']
    store.resolve(store.slug(migrated));raw=json.loads(store.path.read_bytes())
    assert raw['version']==version and 'health_policy' not in raw['subscriptions'][entry['id']]
    store.action(entry['id'],'disable');assert json.loads(store.path.read_bytes())['version']==6


@pytest.mark.parametrize('field,bad',[('health_policy',None),('health_policy',{}),('health_policy',settings(min_candidates=17)),
    ('health_policy_audit',{}),('health_policy_audit',dict(hp.audit_defaults(),result='PRIVATE'))])
def test_authoritative_v5_corruption_fails_closed(store,base,scenario,field,bad):
    data=json.loads(store.path.read_bytes());data['subscriptions'][scenario['entry']['id']][field]=bad
    write_json(store.path,data);before=store.path.read_bytes()
    with pytest.raises(StateError):store.list()
    assert store.path.read_bytes()==before


@pytest.mark.parametrize('failure',['generation','metadata','after-replace','hook-error'])
def test_reconcile_failure_keeps_successful_observations_and_previous_yaml(store,base,scenario,monkeypatch,failure):
    key=scenario['entry']['id'];worker=scenario['worker']
    worker.settings(key,'automatic',True,interval_seconds=900)
    worker.check(key);worker.check(key);old=store.snapshot(key)[1];revision=store.get(key)['revision']
    if failure=='generation':monkeypatch.setattr(generator,'generate',lambda *args, **kwargs:{'success':False})
    elif failure=='hook-error':monkeypatch.setattr(store,'reconcile_health_policy',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('PRIVATE')))
    else:
        original=fixed_subscriptions.write_json
        def fail(path,data):
            if failure=='after-replace':original(path,data)
            raise OSError('PRIVATE')
        monkeypatch.setattr(fixed_subscriptions,'write_json',fail)
    scenario['now']+=900
    counts=worker.check(key,trigger='auto')
    assert counts['unhealthy']==1 and worker.describe(key)['counts']['unhealthy']==1
    assert store.snapshot(key)[1]==old and store.get(key)['revision']==revision
    schedule=worker.scheduled_entries()[key]
    assert schedule['last_job_result']=='success' and schedule['scheduler_failures']==0 and schedule['next_check_at']==scenario['now']+900
    if failure=='generation':assert store.get(key)['health_policy_audit']['result']=='error'


@pytest.mark.parametrize('failure',['engine','busy','health-commit'])
def test_failed_proxy_job_never_reconciles(store,base,scenario,monkeypatch,failure):
    key=scenario['entry']['id'];worker=scenario['worker'];before=store.snapshot(key)
    calls=[];monkeypatch.setattr(store,'reconcile_health_policy',lambda *a,**kw:calls.append(a))
    if failure=='engine':worker.engine.status=lambda:dict(status='NOT INSTALLED')
    if failure=='health-commit':monkeypatch.setattr(worker,'_commit',lambda *args:(_ for _ in ()).throw(ProxyHealthError('save')))
    if failure=='busy':
        with file_lock(worker.job_lock):
            with pytest.raises(ProxyHealthError):worker.check(key)
    else:
        with pytest.raises(ProxyHealthError):worker.check(key)
    assert not calls and store.snapshot(key)==before


def test_reconcile_uses_committed_default_base_caches_and_zero_network(store,base,response,monkeypatch):
    fields=dict(source(),batch_nodes='',policy_config=policies('fallback'),health_policy=settings())
    response['payload']=payload('Taiwan A','Taiwan B','Taiwan C')
    entry=external_save(store,base,config=fields,sources=[remote(refresh_interval_seconds=900),uploaded()],uploads={1:payload('Singapore D')})
    old_sources=copy.deepcopy(entry['sources']);old_payloads={s['id']:store._payload(entry,s['id']) for s in entry['sources'][1:]}
    original_base=store._content(entry,'base.yaml');base.write_bytes(b'BROKEN new template')
    def forbidden(*args,**kwargs):raise AssertionError('reconciliation must not fetch/probe')
    from core import node_probe, mihomo_probe
    for module,key in [(socket,'getaddrinfo'),(socket,'socket'),(source_fetch,'fetch'),(node_probe,'probe'),(mihomo_probe,'run')]:
        monkeypatch.setattr(module,key,forbidden)
    assert store.reconcile_health_policy(entry['id'])=='unavailable'
    changed=store.get(entry['id'])
    assert changed['revision']==entry['revision'] and changed['updated_at']==entry['updated_at']
    assert changed['sources']==old_sources and store._content(changed,'base.yaml')==original_base
    assert {s['id']:store._payload(changed,s['id']) for s in changed['sources'][1:]}==old_payloads


def test_periodic_bounded_oldest_first_and_eventual_coverage(store,base,monkeypatch):
    entries=[]
    for i in range(7):
        fields=dict(source(str(i)),policy_config=policies('url-test'),health_policy=settings())
        entry=store.save(None,str(i),str(i),fields,parsed(fields),base,clock=lambda:1_800_000_000+i)
        entries.append(entry)
    calls=[];original=store.reconcile_health_policy
    def traced(key,**kw):calls.append(key);return original(key,**kw)
    monkeypatch.setattr(store,'reconcile_health_policy',traced)
    for now in [1_800_001_000,1_800_002_000,1_800_003_000]:
        start=len(calls);auto_health.run_once(store,clock=lambda:now)
        assert len(calls)-start==auto_health.MAX_POLICY_RECONCILES==3
    assert set(calls)=={entry['id'] for entry in entries}
    assert calls[:3]==[entry['id'] for entry in entries[:3]]


def test_safe_log_summary_no_secrets(store,base,scenario,caplog):
    with caplog.at_level(logging.INFO):check_three(scenario)
    for secret in ['a.example','b.example',LINK,'11111111-1111-4111-8111-111111111111',scenario['entry']['token']]:
        assert secret not in caplog.text
    assert 'excluded=1' in caplog.text


def distinct_payload(*names):
    return '\n'.join(LINK.replace('example.com',name[-1].lower()+'.example')+'#'+name for name in names).encode()


@pytest.mark.parametrize('operation',['refresh','refresh-all','auto','cache'])
def test_source_refresh_uses_current_health_keeps_unknown_nodes_and_exact_configuration(store,base,response,scenario,operation):
    fields=dict(scenario['fields'],batch_nodes='')
    response['payload']=distinct_payload('US-A','US-B','US-C')
    entry=external_save(store,base,config=fields,sources=[remote(refresh_interval_seconds=900)],clock=lambda:scenario['now'])
    worker=scenario['worker'];worker.settings(entry['id'],'manual',True)
    for _ in range(3):worker.check(entry['id'])
    assert members(store,entry['id'])==['🇺🇸 US-A','🇺🇸 US-C']
    observations=worker.path.read_bytes();slug=store.slug(entry)
    response['payload']=distinct_payload('US-A','US-B','US-C','US-D')
    if operation=='cache':response['error']='timeout'
    scenario['now']+=900
    if operation=='auto':
        assert auto_refresh.run_once(store,base,clock=lambda:scenario['now'])==0
        updated=store.get(entry['id'])
    else:updated=store.source_action(entry['id'],'refresh-all' if operation in ('refresh-all','cache') else 'refresh',base,
        entry['sources'][1]['id'] if operation=='refresh' else None,clock=lambda:scenario['now'])
    assert members(store,entry['id'])==['🇺🇸 US-A','🇺🇸 US-C']+([] if operation=='cache' else ['🇺🇸 US-D'])
    assert updated['health_policy']==entry['health_policy'] and updated['policy_config']==entry['policy_config']
    assert store.slug(updated)==slug and worker.path.read_bytes()==observations
    assert updated['sources'][1]['using_cache']==(operation=='cache')
    assert len(content(store,entry['id'])['proxies'])==(3 if operation=='cache' else 4)


def test_connection_change_does_not_inherit_unhealthy_identity(store,base,scenario):
    check_three(scenario);key=scenario['entry']['id'];observations=scenario['worker'].path.read_bytes()
    fields=copy.deepcopy(scenario['fields'])
    fields['batch_nodes']=fields['batch_nodes'].replace('b.example','new-b.example')
    changed=resave(store,base,scenario,batch_nodes=fields['batch_nodes'])
    assert len(members(store,key))==4 and changed['health_policy_audit']['candidates_excluded']==0
    assert scenario['worker'].path.read_bytes()==observations
    assert scenario['worker'].describe(key)['counts']==dict(healthy=3,suspect=0,unhealthy=0,unknown=1,unsupported=0)


@pytest.mark.parametrize('winner',['policy','health-policy','disable','delete','refresh','new-health'])
def test_paused_reconcile_cannot_overwrite_newer_management_source_or_observations(store,base,scenario,response,monkeypatch,winner):
    check_three(scenario);key=scenario['entry']['id']
    if winner=='refresh':
        response['payload']=distinct_payload('US-E')
        external_save(store,base,store.get(key),scenario['fields'],sources=[remote()])
    started,resume=threading.Event(),threading.Event();result=[]
    original=generator.generate
    def paused(*args,**kwargs):
        if threading.current_thread().name=='health-policy-race':
            started.set();assert resume.wait(5)
        return original(*args,**kwargs)
    monkeypatch.setattr(generator,'generate',paused)
    thread=threading.Thread(name='health-policy-race',target=lambda:result.append(store.reconcile_health_policy(key,clock=lambda:scenario['now'])))
    thread.start();assert started.wait(2)
    try:
        # Acquiring both locks here proves generation does not hold either one.
        with file_lock(store.lock,blocking=False),file_lock(scenario['worker'].lock,blocking=False):pass
        if winner=='policy':resave(store,base,scenario,policy_config=policies('select','select'))
        elif winner=='health-policy':resave(store,base,scenario,health_policy=hp.defaults())
        elif winner in ('disable','delete'):store.action(key,winner)
        elif winner=='refresh':
            response['payload']=distinct_payload('US-F')
            store.source_action(key,'refresh-all',base)
        else:
            scenario['now']+=1;scenario['outcomes']['b.example']='success'
            scenario['worker'].check(key)
        selected=store.get(key);yaml=store.snapshot(key)[1] if selected else None
    finally:resume.set();thread.join(5)
    assert not thread.is_alive() and result==['error']
    assert store.get(key)==selected
    if selected:assert store.snapshot(key)[1]==yaml


def test_network_work_and_generation_run_with_both_state_locks_released(store,base,response,scenario,monkeypatch):
    original=source_fetch.fetch
    def available():
        with file_lock(store.lock,blocking=False),file_lock(scenario['worker'].lock,blocking=False):pass
    def fetch(url):available();return original(url)
    monkeypatch.setattr(source_fetch,'fetch',fetch)
    original_generate=generator.generate
    def generate(*args,**kw):available();return original_generate(*args,**kw)
    monkeypatch.setattr(generator,'generate',generate)
    original_resolver=scenario['worker'].resolver
    def resolve(*args):available();return original_resolver(*args)
    scenario['worker'].resolver=resolve
    original_runner=scenario['worker'].runner
    def runner(*args):available();return original_runner(*args)
    scenario['worker'].runner=runner
    external_save(store,base,store.get(scenario['entry']['id']),scenario['fields'],sources=[remote()])
    check_three(scenario)
    assert store.get(scenario['entry']['id'])['health_policy_audit']['result']!='error'


def test_fixed_then_proxy_lock_order_snapshot_guard_and_commits(store,base,scenario,monkeypatch):
    from contextlib import contextmanager
    local=threading.local();held=[]
    original_fixed=store._locked;original_proxy=ProxyHealth._locked
    @contextmanager
    def fixed_lock():
        assert not getattr(local,'proxy',False)
        with original_fixed():
            local.fixed=True
            try:yield
            finally:local.fixed=False
    @contextmanager
    def proxy_lock(observer,path,blocking=True):
        with original_proxy(observer,path,blocking):
            if path==observer.lock:
                local.proxy=True;held.append(bool(getattr(local,'fixed',False)))
                try:yield
                finally:local.proxy=False
            else:yield
    monkeypatch.setattr(store,'_locked',fixed_lock);monkeypatch.setattr(ProxyHealth,'_locked',proxy_lock)
    check_three(scenario)
    assert True in held and False in held and len(members(store,scenario['entry']['id']))==3


def test_public_fixed_and_healthz_responsive_during_paused_reconciliation(web,logged_in,monkeypatch):
    from test_fixed_views import create
    entry=create(web,logged_in,batch_nodes='US|A|'+LINK,policy_country_groups_type='url-test',health_policy_mode='exclude-unhealthy')
    fixed=web.fixed_subscriptions;url='/s/'+fixed.slug(entry);old=fixed.snapshot(entry['id'])[1]
    started,resume=threading.Event(),threading.Event();result=[];original=generator.generate
    def paused(*args,**kw):started.set();assert resume.wait(5);return original(*args,**kw)
    monkeypatch.setattr(generator,'generate',paused)
    thread=threading.Thread(target=lambda:result.append(fixed.reconcile_health_policy(entry['id'])))
    thread.start();assert started.wait(2)
    try:
        client=web.app.test_client()
        assert client.get(url).data==old and client.get('/healthz').status_code==200
    finally:resume.set();thread.join(5)
    assert not thread.is_alive() and result==['unavailable']


@pytest.mark.parametrize('invalid',[dict(health_policy_mode='invalid'),dict(health_policy_max_age_seconds='123'),dict(health_policy_min_candidates='17')])
def test_fixed_health_controls_strict_redisplay_and_auth_only(web,logged_in,invalid):
    from test_fixed_views import create
    entry=create(web,logged_in,health_policy_mode='exclude-unhealthy',health_policy_max_age_seconds='21600',health_policy_min_candidates='3')
    store=web.fixed_subscriptions;path=f'/fixed-subscriptions/{entry["id"]}/edit';old=store.snapshot(entry['id'])
    data=dict(name=entry['name'],prefix=entry['prefix'],yaml_source='custom',batch_nodes='US|Edited|'+LINK,
        aux_nodes=json.dumps([dict(country='SG',name='Keep auxiliary',link=LINK)]),health_policy_mode='exclude-unhealthy',
        health_policy_max_age_seconds='21600',health_policy_min_candidates='3',policy_country_groups_type='fallback')
    data.update(invalid);response=post(logged_in,path,data)
    assert response.status_code==400 and b'Unable to save' in response.data
    assert b'Keep auxiliary' in response.data and b'value="fallback" selected' in response.data
    for value in invalid.values():assert ('value="'+value+'"').encode() in response.data
    assert store.snapshot(entry['id'])==old
    assert b'health-policy-mode' not in logged_in.get('/').data
    public=web.app.test_client()
    assert public.get(path).status_code==302 and b'health_policy_audit' not in public.get('/s/'+store.slug(entry)).data
