"""Real authoritative commits with controlled provider/probe/Telegram doubles."""
import copy
import logging
from contextlib import ExitStack
import json

import pytest

from core import auto_refresh, auto_health, notification_events as events, generator, telegram
from core.notifications import Notifications
from core.source_errors import SourceError
from core.state import file_lock
from test_fixed_subscriptions import store, base, save, source
from test_external_sources import response, external_save, remote
from test_auto_refresh import clock, scheduled
from test_auto_health import observers, configure, state, scan
from test_notifications import TOKEN, CHAT, PREFS


@pytest.fixture
def deliveries(store, monkeypatch):
    calls = []
    def send(self, token, chat, message):
        assert (token,chat) == (TOKEN,CHAT)
        # Independent nonblocking descriptors prove every feature and singleton
        # lock has been released at the actual transport boundary.
        with ExitStack() as stack:
            for name in ('fixed_subscriptions','node_health','proxy_health','proxy_probe',
                         'auto_refresh','auto_health','notifications'):
                path = store.state/(name+'.lock')
                if path.exists(): stack.enter_context(file_lock(path,blocking=False,strict=True))
        assert store.counts()['total'] >= 1
        calls.append(message)
        return 'success'
    monkeypatch.setattr(telegram.Telegram,'send',send)
    Notifications(store.state).save(True,PREFS,TOKEN,CHAT)
    return calls


def test_source_cached_incident_repeat_recovery_and_batch(store,base,response,clock,deliveries,caplog):
    caplog.set_level(logging.INFO)
    entries = [scheduled(store,base,clock) for _ in range(2)]
    good = [store.snapshot(entry['id'])[1] for entry in entries]
    response['error'] = 'http_500'
    for _ in range(2):
        clock.now = max(store.get(entry['id'])['sources'][1]['next_refresh_at'] for entry in entries)
        assert auto_refresh.run_once(store,base,clock) == 0
        assert len(deliveries) == 1
        for index,entry in enumerate(entries):
            current = store.get(entry['id']); item = current['sources'][1]
            assert item['consecutive_failures'] > 0 and item['using_cache']
            assert store.snapshot(entry['id'])[1] == good[index]
    assert deliveries[0].count('Source Refresh incident.') == 2
    assert 'last-good cache may be in use' in deliveries[0]
    response.pop('error')
    for _ in range(2):
        clock.now = max(store.get(entry['id'])['sources'][1]['next_refresh_at'] for entry in entries)
        assert auto_refresh.run_once(store,base,clock) == 0 and len(deliveries) == 2
    assert deliveries[1].count('Source Refresh recovery.') == 2
    for secret in (TOKEN,CHAT,entries[0]['token'],entries[0]['sources'][1]['url'],'11111111-1111-4111-8111-111111111111'):
        assert secret not in '\n'.join(deliveries) and secret not in caplog.text


def test_source_failed_candidate_postcommit_boundary_and_conflict(store,base,response,clock,deliveries,monkeypatch):
    entry = scheduled(store,base,clock); good = store.snapshot(entry['id'])[1]
    original = generator.generate
    monkeypatch.setattr(generator,'generate',lambda *a,**k:dict(success=False))
    clock.now += 900
    assert auto_refresh.run_once(store,base,clock) == 0 and len(deliveries) == 1
    assert store.snapshot(entry['id'])[1] == good
    assert store.get(entry['id'])['sources'][1]['consecutive_failures'] == 1
    monkeypatch.setattr(generator,'generate',original)
    monkeypatch.setattr(store,'refresh_sources',lambda *a,**k: (_ for _ in ()).throw(SourceError('conflict')))
    clock.now += 900
    assert auto_refresh.run_once(store,base,clock) == 0 and len(deliveries) == 1


@pytest.mark.parametrize('kind',['endpoint','proxy'])
def test_health_unhealthy_boundary_real_jobs_dedupe_no_node_data(store,base,observers,deliveries,kind,caplog):
    config = source(); config['batch_nodes'] += '\nJP|PRIVATE_SECOND|vless://22222222-2222-4222-8222-222222222222@private-server.example:444?type=tcp'
    entry = save(store,base,config=config); worker = observers[kind]; configure(worker,entry['id'])
    failed = set()
    def endpoint(server,port): return dict(error='timeout' if port in failed else None,latency_ms=None if port in failed else 10)
    def proxy(binary,nodes,settings,directory):
        return {node['fingerprint']:dict(kind='failure' if node['config']['port'] in failed else 'success',
            error='proxy_failed' if node['config']['port'] in failed else None,
            latency_ms=None if node['config']['port'] in failed else 10) for node in nodes}
    worker.probe = endpoint
    if kind == 'proxy': worker.runner = proxy
    before = store.path.read_bytes(); yaml_before = store.snapshot(entry['id'])[1]
    caplog.set_level(logging.INFO)
    def run(count):
        for _ in range(count):
            observers['now'] = state(worker,entry['id'])['next_check_at']; assert scan(store,observers) == 0
    run(1); assert not deliveries  # UNKNOWN -> healthy
    failed.add(443); run(2); assert not deliveries  # SUSPECT only
    run(1); assert len(deliveries) == 1
    failed.add(444); run(3); assert len(deliveries) == 1  # 1 -> 2
    failed.remove(443); run(1); assert len(deliveries) == 1  # 2 -> 1
    failed.clear(); run(2); assert len(deliveries) == 2 and 'recovery.' in deliveries[-1]
    assert store.path.read_bytes() == before and store.snapshot(entry['id'])[1] == yaml_before
    for record in state(worker,entry['id'])['nodes']:
        assert record not in '\n'.join(deliveries)
    for secret in (TOKEN, CHAT, entry['token'], 'PRIVATE_SECOND', 'example.com', 'private-server.example',
                   '11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222', 'vless://'):
        assert secret not in '\n'.join(deliveries) and secret not in caplog.text


@pytest.mark.parametrize('kind',['endpoint','proxy'])
def test_scheduler_job_incident_repeat_recovery_authoritative(store,base,observers,deliveries,kind):
    key = save(store,base)['id']; worker = observers[kind]; configure(worker,key)
    original = worker.probe if kind == 'endpoint' else worker.runner
    def failure(*args): raise RuntimeError('PRIVATE exception details')
    if kind == 'endpoint': worker.probe = failure
    else: worker.runner = failure
    for failures in (1,2):
        observers['now'] = state(worker,key)['next_check_at']; assert scan(store,observers) == 0
        assert state(worker,key)['scheduler_failures'] == failures and len(deliveries) == 1
    assert 'Scheduler incident' in deliveries[0] and 'Result: error' in deliveries[0]
    if kind == 'endpoint': worker.probe = original
    else: worker.runner = original
    for _ in range(2):
        observers['now'] = state(worker,key)['next_check_at']; assert scan(store,observers) == 0
        assert state(worker,key)['scheduler_failures'] == 0 and len(deliveries) == 2
    assert 'Scheduler recovery' in deliveries[1] and 'PRIVATE' not in '\n'.join(deliveries)


def test_multiple_health_events_one_post_after_all_locks(store,base,observers,deliveries):
    key = save(store,base)['id']; endpoint, proxy = observers['endpoint'],observers['proxy']
    configure(endpoint,key,'manual',None); configure(proxy,key)
    observers['endpoint_error']='timeout'; observers['proxy_result']='failure'
    endpoint.check(key); endpoint.check(key)
    for _ in range(3): proxy.check(key)
    assert not deliveries  # Manual jobs do not alert.
    observers['engine']='NOT INSTALLED'; observers['now']=state(proxy,key)['next_check_at'];scan(store,observers)
    assert len(deliveries) == 1 and 'Scheduler incident' in deliveries[0]
    deliveries.clear(); observers['engine']='COMPATIBLE'; observers['proxy_result']='success'
    configure(endpoint,key)
    observers['now']=max(state(endpoint,key)['next_check_at'],state(proxy,key)['next_check_at']);scan(store,observers)
    assert len(deliveries) == 1
    for phrase in ('Endpoint Health incident','Full Proxy Health recovery','Scheduler recovery'):
        assert phrase in deliveries[0]


def test_busy_conflict_unsupported_no_incident(store,base,observers,deliveries):
    key=save(store,base)['id']; worker=observers['proxy']; configure(worker,key)
    observers['now']+=900
    with file_lock(worker.job_lock,blocking=False,strict=True): assert scan(store,observers) == 0
    assert state(worker,key)['last_job_result']=='busy' and state(worker,key)['scheduler_failures']==0
    assert not deliveries
    before=state(worker,key)
    with events.collect([]) as ignored:
        assert worker._record_failed_job(key,before,'conflict')
    assert not deliveries and state(worker,key)['scheduler_failures']==0
    observers['proxy_result']='unsupported'; observers['now']=state(worker,key)['next_check_at'];scan(store,observers)
    assert not deliveries and next(iter(state(worker,key)['nodes'].values()))['status']=='unsupported'


@pytest.mark.parametrize('scanner',['refresh','health'])
@pytest.mark.parametrize('broken',['corrupt','disabled','category','delivery','bookkeeping'])
def test_auxiliary_failures_never_change_authoritative_scan_result(store,base,response,clock,observers,deliveries,monkeypatch,scanner,broken):
    if scanner == 'refresh': entry=scheduled(store,base,clock); response['error']='http_500'; clock.now+=900
    else:
        entry=save(store,base); configure(observers['proxy'],entry['id']); observers['engine']='NOT INSTALLED';observers['now']+=900
    authority = Notifications(store.state)
    if broken == 'corrupt': authority.path.write_bytes(b'PRIVATE corrupt'); raw=authority.path.read_bytes()
    elif broken == 'disabled': authority.save(False,PREFS)
    elif broken == 'category': authority.save(True,{key:False for key in PREFS})
    elif broken == 'delivery': monkeypatch.setattr(telegram.Telegram,'send',lambda *args: (_ for _ in ()).throw(RuntimeError('PRIVATE'+TOKEN)))
    else: monkeypatch.setattr(Notifications,'_commit',lambda *args: (_ for _ in ()).throw(RuntimeError('PRIVATE write failed')))
    result = auto_refresh.run_once(store,base,clock) if scanner == 'refresh' else scan(store,observers)
    assert result == 0
    if scanner == 'refresh': assert store.get(entry['id'])['sources'][1]['consecutive_failures']==1
    else: assert state(observers['proxy'],entry['id'])['scheduler_failures']==1
    if broken in ('corrupt','disabled','category','delivery'): assert not deliveries
    else: assert len(deliveries)==1
    if broken == 'corrupt': assert authority.path.read_bytes()==raw


def test_manual_refresh_no_automatic_delivery(store,base,response,clock,deliveries):
    entry=scheduled(store,base,clock); response['error']='http_500'
    store.source_action(entry['id'],'refresh-all',base,clock=clock)
    assert not deliveries


def test_critical_state_scan_does_not_attempt_delivery(store,base,deliveries,monkeypatch):
    monkeypatch.setattr(store,'list',lambda: (_ for _ in ()).throw(RuntimeError('PRIVATE critical')))
    for scanner in (lambda:auto_refresh.run_once(store,base),lambda:auto_health.run_once(store)):
        with pytest.raises(RuntimeError): scanner()
    assert not deliveries


def test_message_sanitization_aggregate_only_and_truncation():
    secrets=['https://user:password@example.test/private?token=SECRET','vmess://PRIVATE_URI','vless://PRIVATE_URI',
             '11111111-1111-4111-8111-111111111111','-fs_ABCDEFGHIJKLMNOPQRSTUV','192.0.2.123','private-server.example',TOKEN]
    label='Office\n\r\x00  '+ ' '.join(secrets)
    batch=[]
    with events.collect(batch):
        events.boundary('endpoint_health',0,1,8,label,1_800_000_000)
    assert len(batch)==1 and '\n' not in batch[0].label and len(batch[0].label)<=96
    text=events.message(batch)
    for secret in secrets: assert secret not in text and secret not in repr(batch)
    text=events.message(batch*100)
    assert len(text)<=3500 and 'additional events omitted' in text


@pytest.mark.parametrize('kind',events.CATEGORIES)
@pytest.mark.parametrize('before,after,transition',[(0,0,None),(0,1,'incident'),(1,2,None),(2,1,None),(1,0,'recovery')])
def test_boundary_collection(kind,before,after,transition):
    batch=[]
    with events.collect(batch): events.boundary(kind,before,after,8,'Office',1_800_000_000)
    assert len(batch)==bool(transition)
    if transition: assert batch[0].transition==transition


def test_context_collector_cannot_leak_into_other_thread():
    import threading
    batch=[]
    with events.collect(batch):
        worker=threading.Thread(target=lambda:events.boundary('scheduler',0,1,1,'Other',1_800_000_000))
        worker.start();worker.join(2)
        events.boundary('scheduler',0,1,1,'Main',1_800_000_000)
    assert len(batch)==1 and batch[0].label=='Main'


@pytest.mark.parametrize('kind',['endpoint','proxy'])
def test_failed_health_commit_never_emits_observation_event(store,base,observers,deliveries,monkeypatch,kind):
    key=save(store,base)['id'];worker=observers[kind];configure(worker,key)
    observers['endpoint_error']='timeout';observers['proxy_result']='failure'
    worker.check(key);worker.check(key);raw=worker.path.read_bytes()
    monkeypatch.setattr(worker,'_commit',lambda *args: (_ for _ in ()).throw(OSError('PRIVATE write failure')))
    observers['now']=state(worker,key)['next_check_at'];assert scan(store,observers)==0
    assert worker.path.read_bytes()==raw and not deliveries


def test_source_credentials_and_malicious_label_not_transmitted(store,base,response,clock,deliveries,caplog):
    from test_fixed_subscriptions import parsed
    config=source();url='https://example.test/private?token=SECRET'
    name='Office\nhttps://l.test/x vmess://S vless://S 11111111-1111-4111-8111-111111111111 -fs_ABCDEFGHIJKLMNOPQRSTUV'
    entry=store.save(None,name,'office',config,parsed(config),base,
        sources=[remote(url=url,refresh_interval_seconds=900)],clock=clock)
    caplog.set_level(logging.INFO);response['error']='http_500';clock.now+=900
    assert auto_refresh.run_once(store,base,clock)==0 and len(deliveries)==1
    for secret in (url,'user:password','example.test','token=SECRET','https://l.test/x',
        'vmess://S','vless://S','11111111-1111-4111-8111-111111111111','ABCDEFGHIJKLMNOPQRSTUV'):
        assert secret not in deliveries[0] and secret not in caplog.text


def test_source_event_never_copies_url_credentials():
    url='https://user:password@example.test/private?token=SECRET'
    before=dict(name='Office', sources=[dict(enabled=True,type='remote_url',consecutive_failures=0,url=url)])
    after=copy.deepcopy(before);after['sources'][0]['consecutive_failures']=1
    batch=[]
    with events.collect(batch): events.source(before,after,1_800_000_000)
    assert len(batch)==1
    for secret in (url,'user:password','example.test','SECRET'):
        assert secret not in repr(batch) and secret not in events.message(batch)
    assert set(vars(batch[0])) == {'kind','transition','label','count','total','result','at'}
