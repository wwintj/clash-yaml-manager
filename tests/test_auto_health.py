"""Offline scheduling/optimistic-concurrency acceptance; no real network or units."""
import copy
import json
import logging
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import auto_health, health_schedule as schedule, mihomo_probe, node_health, proxy_health
from core.node_health import HealthError, NodeHealth
from core.proxy_health import ProxyHealth, ProxyHealthError
from core.state import file_lock, write_json
from conftest import LINK, post
from test_fixed_subscriptions import base, save, source, store
from test_node_health import yaml_bytes, proxy as node_config
from test_proxy_health import public_resolver
from test_external_sources import response
from test_mihomo_probe import fake_batch


@pytest.fixture
def observers(store):
    data = dict(now=1_800_000_000,endpoint_calls=[],proxy_calls=[],endpoint_error=None,
                proxy_result='success',engine='COMPATIBLE')
    clock = lambda:data['now']
    def probe(server,port):
        data['endpoint_calls'].append((server,port))
        return dict(error=data['endpoint_error'],latency_ms=None if data['endpoint_error'] else 10)
    def run(binary,nodes,settings,directory):
        data['proxy_calls'].append(copy.deepcopy(nodes))
        if data['proxy_result'] == 'engine':
            raise mihomo_probe.ProbeEngineError('PRIVATE controller error')
        return {n['fingerprint']:dict(kind=data['proxy_result'],latency_ms=10,
                  error='proxy_failed' if data['proxy_result']=='failure' else None) for n in nodes}
    data['endpoint'] = NodeHealth(store,clock=clock,probe=probe)
    engine = SimpleNamespace(binary=store.state.parent/'bin/mihomo',status=lambda:dict(status=data['engine']))
    data['proxy'] = ProxyHealth(store,clock=clock,engine=engine,runner=run,resolver=public_resolver)
    return data


def configure(observer,key,mode='automatic',seconds=900):
    if isinstance(observer,ProxyHealth):
        observer.settings(key,mode,True,interval_seconds=seconds)
    else:
        observer.settings(key,mode,seconds)


def state(observer,key):
    return copy.deepcopy(observer._read()[0]['subscriptions'][key])


def scan(store, observers):
    return auto_health.run_once(store,endpoint=observers['endpoint'],proxy=observers['proxy'],clock=lambda:observers['now'])


@pytest.mark.parametrize('kind',['endpoint','proxy'])
@pytest.mark.parametrize('mode',['off','manual'])
def test_v1_read_migration_preserves_modes_observations_and_file_bytes(store,base,observers,kind,mode):
    entry=save(store,base); key=entry['id']; worker=observers[kind]
    configure(worker,key,'manual',None); worker.check(key)
    data,_=worker._read(); data['version']=1
    old=data['subscriptions'][key]; old['mode']=mode
    for field in schedule.FIELDS: old.pop(field)
    write_json(worker.path,data); before=worker.path.read_bytes()
    described=worker.describe(key); migrated,_=worker._read()
    assert migrated['version']==2 and described['mode']==mode
    assert described['counts']['healthy']==1
    assert described['interval_seconds'] is described['next_check_at'] is None
    assert described['scheduler_failures']==0 and described['last_trigger'] is described['last_job_result'] is None
    assert worker.path.read_bytes()==before
    assert scan(store,observers)==0 and worker.path.read_bytes()==before
    configure(worker,key,mode,None)
    assert json.loads(worker.path.read_bytes())['version']==2


@pytest.mark.parametrize('kind',['endpoint','proxy'])
@pytest.mark.parametrize('seconds',[900,1800,3600,10800,21600,43200,86400])
def test_every_interval_opt_in_reschedules_without_network_and_same_save_preserves_due(store,base,observers,kind,seconds):
    key=save(store,base)['id']; worker=observers[kind]
    assert worker.describe(key)['mode']=='off' and not worker.path.exists()
    configure(worker,key,seconds=seconds)
    assert state(worker,key)['next_check_at']==observers['now']+seconds
    assert not observers['endpoint_calls'] and not observers['proxy_calls']
    observers['now']+=100
    configure(worker,key,seconds=seconds)
    assert state(worker,key)['next_check_at']==observers['now']-100+seconds
    new=1800 if seconds==900 else 900
    configure(worker,key,seconds=new)
    assert state(worker,key)['next_check_at']==observers['now']+new
    configure(worker,key,'manual',None)
    assert state(worker,key)['interval_seconds'] is state(worker,key)['next_check_at'] is None
    assert scan(store,observers)==0 and not observers['endpoint_calls'] and not observers['proxy_calls']


@pytest.mark.parametrize('kind',['endpoint','proxy'])
@pytest.mark.parametrize('seconds',[None,True,False,0,60,901,'900',900.0,{},-1])
def test_automatic_requires_exact_supported_integer_interval(store,base,observers,kind,seconds):
    key=save(store,base)['id'];worker=observers[kind]
    with pytest.raises((HealthError,ProxyHealthError)):
        configure(worker,key,seconds=seconds)
    assert not worker.path.exists()


@pytest.mark.parametrize('kind',['endpoint','proxy'])
def test_manual_in_automatic_reschedules_from_completion_and_auto_not_due_rejected(store,base,observers,kind):
    key=save(store,base)['id'];worker=observers[kind];configure(worker,key)
    with pytest.raises((HealthError,ProxyHealthError)) as error:worker.check(key,trigger='auto')
    assert error.value.code=='not_due'
    observers['now']+=50; worker.check(key)
    value=state(worker,key)
    assert value['last_trigger']=='manual' and value['last_job_result']=='success'
    assert value['next_check_at']==observers['now']+900 and value['scheduler_failures']==0
    assert scan(store,observers)==0
    assert len(observers[kind+'_calls'])==1
    with pytest.raises((HealthError,ProxyHealthError)):worker.check(key,trigger='arbitrary')


@pytest.mark.parametrize('kind',['endpoint','proxy'])
def test_auto_uses_saved_yaml_and_node_failure_thresholds_without_fixed_mutation(store,base,observers,kind,monkeypatch,caplog):
    entry=save(store,base);key=entry['id'];worker=observers[kind];configure(worker,key)
    fixed_before=store.path.read_bytes();slug=store.slug(entry); yaml_before=store.snapshot(key)[1]
    monkeypatch.setattr(store,'refresh_sources',lambda *a,**k:pytest.fail('health refreshed provider'))
    caplog.set_level(logging.INFO)
    if kind=='endpoint': observers['endpoint_error']='timeout'
    else: observers['proxy_result']='failure'
    for status,count in [('suspect',1),('suspect',2),('unhealthy',3)]:
        observers['now']=state(worker,key)['next_check_at']; assert scan(store,observers)==0
        value=state(worker,key); record=next(iter(value['nodes'].values()))
        assert record['status']==status and record['consecutive_failures']==count
        assert value['scheduler_failures']==0 and value['last_trigger']=='auto' and value['last_job_result']=='success'
        assert value['next_check_at']==observers['now']+900
        assert store.path.read_bytes()==fixed_before and store.snapshot(key)[1]==yaml_before and store.slug(store.get(key))==slug
    observers['endpoint_error']=None;observers['proxy_result']='success'
    observers['now']=state(worker,key)['next_check_at'];scan(store,observers)
    record=next(iter(state(worker,key)['nodes'].values()))
    assert record['status']=='healthy' and record['consecutive_failures']==0
    for secret in (entry['token'],LINK,'example.com','11111111-1111-4111-8111-111111111111'):
        assert secret not in caplog.text and secret.encode() not in worker.path.read_bytes()


def test_unsupported_proxy_is_completed_job_without_node_or_scheduler_penalty(store,base,observers):
    key=save(store,base)['id'];worker=observers['proxy'];configure(worker,key)
    observers['proxy_result']='unsupported';observers['now']+=900;scan(store,observers)
    value=state(worker,key);record=next(iter(value['nodes'].values()))
    assert record['status']=='unsupported' and record['consecutive_failures']==0
    assert value['scheduler_failures']==0 and value['last_job_result']=='success'


@pytest.mark.parametrize('engine',['NOT INSTALLED','INCOMPATIBLE','BROKEN'])
def test_unavailable_proxy_engine_backs_off_without_nodes_and_endpoint_continues(store,base,observers,engine):
    key=save(store,base)['id'];worker=observers['proxy'];configure(worker,key)
    worker.check(key); before=state(worker,key)['nodes']; observers['engine']=engine
    configure(observers['endpoint'],key)
    for failures,delay in enumerate([300,900,1800,3600,7200,21600,21600],1):
        observers['now']=state(worker,key)['next_check_at']; scan(store,observers)
        value=state(worker,key)
        assert value['nodes']==before and value['scheduler_failures']==failures
        assert value['last_job_result']=='engine_unavailable' and value['next_check_at']==observers['now']+delay
        assert value['interval_seconds']==900
    assert observers['endpoint_calls'] and len(observers['proxy_calls'])==1
    observers['engine']='COMPATIBLE';observers['now']=state(worker,key)['next_check_at'];scan(store,observers)
    value=state(worker,key)
    assert value['scheduler_failures']==0 and value['next_check_at']==observers['now']+900


@pytest.mark.parametrize('kind',['endpoint','proxy'])
def test_internal_job_failure_keeps_node_observations_and_uses_backoff(store,base,observers,kind):
    key=save(store,base)['id'];worker=observers[kind];configure(worker,key);worker.check(key)
    before=state(worker,key)['nodes']
    def fail(*args):raise KeyError('PRIVATE subsystem failure')
    if kind=='endpoint':worker.probe=fail
    else:worker.runner=fail
    observers['now']=state(worker,key)['next_check_at'];scan(store,observers)
    value=state(worker,key)
    assert value['nodes']==before and value['last_job_result']=='error' and value['scheduler_failures']==1
    assert value['next_check_at']==observers['now']+300


@pytest.mark.parametrize('kind',['endpoint','proxy'])
def test_over_256_is_whole_job_failure_without_first_256_probe(store,base,observers,kind,monkeypatch):
    entry=save(store,base);key=entry['id'];worker=observers[kind];configure(worker,key);worker.check(key)
    before=state(worker,key)['nodes']; calls=len(observers[kind+'_calls'])
    original=store.snapshot
    monkeypatch.setattr(store,'snapshot',lambda key:(original(key)[0],yaml_bytes([node_config(port=i+1) for i in range(257)])))
    observers['now']=state(worker,key)['next_check_at'];scan(store,observers)
    value=state(worker,key)
    assert value['nodes']==before and value['last_job_result']=='limit' and value['scheduler_failures']==1
    assert len(observers[kind+'_calls'])==calls


@pytest.mark.parametrize('kind',['endpoint','proxy'])
def test_disabled_pause_then_overdue_resume_preserves_config_and_observations(store,base,observers,kind):
    key=save(store,base)['id'];worker=observers[kind];configure(worker,key);worker.check(key)
    before=worker.path.read_bytes();store.action(key,'disable');observers['now']+=1800
    scan(store,observers);assert worker.path.read_bytes()==before
    assert len(observers[kind+'_calls'])==1
    store.action(key,'enable');scan(store,observers)
    assert len(observers[kind+'_calls'])==2 and state(worker,key)['last_trigger']=='auto'


def test_due_fairness_stable_ties_and_limits_4_endpoint_1_proxy(store,base,observers):
    keys=[save(store,base)['id'] for _ in range(7)]
    for key in keys:
        configure(observers['endpoint'],key);configure(observers['proxy'],key)
    # Independent due values establish ordering rather than insertion order.
    for kind in ('endpoint','proxy'):
        worker=observers[kind];data,raw=worker._read()
        for key in keys:data['subscriptions'][key]['next_check_at']=observers['now']-1
        data['subscriptions'][keys[-1]]['next_check_at']-=1
        worker._commit(data,raw)
    expected=[keys[-1]]+sorted(keys[:-1])
    assert auto_health.select_work(store.list(),observers['endpoint'].scheduled_entries(),observers['now'],4)==expected[:4]
    scan(store,observers)
    checked=lambda kind:{key for key in keys if state(observers[kind],key)['last_trigger']=='auto'}
    assert checked('endpoint')==set(expected[:4]) and checked('proxy')==set(expected[:1])
    scan(store,observers)
    assert checked('endpoint')==set(keys) and checked('proxy')==set(expected[:2])


def test_scheduler_singleton_exits_without_probes(store,base,observers,caplog):
    key=save(store,base)['id'];configure(observers['endpoint'],key);observers['now']+=900
    caplog.set_level(logging.INFO)
    with file_lock(store.state/'auto_health.lock',blocking=False,strict=True):assert scan(store,observers)==0
    assert not observers['endpoint_calls'] and 'already running' in caplog.text
    assert (store.state/'auto_health.lock').stat().st_mode & 0o777==0o600


def test_busy_retry_does_not_invalidate_the_running_manual_proxy_job(store,base,observers):
    key=save(store,base)['id'];worker=observers['proxy'];configure(worker,key);observers['now']+=900
    started,resume=threading.Event(),threading.Event();errors=[];original=worker.runner
    def paused(*args):started.set();assert resume.wait(5);return original(*args)
    worker.runner=paused
    def manual():
        try:worker.check(key)
        except Exception as error:errors.append(error)
    thread=threading.Thread(target=manual);thread.start();assert started.wait(2)
    try:
        scan(store,observers);value=state(worker,key)
        assert value['last_job_result']=='busy' and value['scheduler_failures']==0 and not value['nodes']
        assert value['next_check_at']==observers['now']+300
    finally:resume.set();thread.join(5)
    assert not errors and not thread.is_alive()
    value=state(worker,key)
    assert value['last_trigger']=='manual' and value['last_job_result']=='success' and value['next_check_at']==observers['now']+900


@pytest.mark.parametrize('kind',['endpoint','proxy'])
@pytest.mark.parametrize('mutation',['revision','interval','off','disable','delete','global'])
def test_auto_pause_releases_fixed_lock_and_discards_revision_or_settings_races(web,logged_in,kind,mutation,monkeypatch):
    from test_proxy_health import create
    entry=create(web,logged_in);store=web.fixed_subscriptions;key=entry['id'];now=[1_800_000_000]
    started,resume=threading.Event(),threading.Event();errors=[]
    def paused(*args):
        started.set();assert resume.wait(5)
        if kind=='endpoint':return dict(error=None,latency_ms=10)
        return {node['fingerprint']:dict(kind='success',latency_ms=10,error=None) for node in args[1]}
    endpoint=NodeHealth(store,clock=lambda:now[0],probe=paused)
    engine=SimpleNamespace(binary=store.state.parent/'bin/mihomo',status=lambda:dict(status='COMPATIBLE'))
    proxy=ProxyHealth(store,clock=lambda:now[0],engine=engine,runner=paused,resolver=public_resolver)
    worker=endpoint if kind=='endpoint' else proxy
    configure(worker,key);old=state(worker,key);now[0]+=900
    public=web.app.test_client();slug=store.slug(entry);before=store.snapshot(key)[1]
    def run():
        try:worker.check(key,trigger='auto')
        except Exception as error:errors.append(error)
    thread=threading.Thread(target=run);thread.start();assert started.wait(2)
    try:
        # Reads and mutations complete while the network call is paused.
        assert public.get('/s/'+slug).data==before
        assert public.get('/healthz').status_code==200
        assert logged_in.get(f'/fixed-subscriptions/{key}/edit').status_code==200
        if mutation=='revision':
            config=source('Revised');save(store,Path(web.DEFAULT_YAML_PATH) if hasattr(web,'DEFAULT_YAML_PATH') else store.state.parent/'defaults/default.yaml',key,config)
        elif mutation=='interval':configure(worker,key,seconds=1800)
        elif mutation=='off':configure(worker,key,'off',None)
        elif mutation=='global' and kind=='proxy':proxy.set_global(dict(url='https://other.example/test',expected_status=200,timeout_ms=5000))
        elif mutation=='global':configure(worker,key,seconds=3600)
        else:store.action(key,mutation)
        changed=state(worker,key) if mutation!='delete' else None
    finally:resume.set();thread.join(5)
    assert not thread.is_alive() and len(errors)==1 and isinstance(errors[0],(HealthError,ProxyHealthError))
    if mutation=='delete':
        assert key not in worker._read()[0]['subscriptions'] or worker._read()[0]['subscriptions'][key]==old
    else:
        value=state(worker,key)
        assert value['nodes']==old['nodes'] and value['scheduler_failures']==0
        if mutation=='revision':assert value['last_job_result']=='conflict' and value['next_check_at']==now[0]+300
        else:assert value==changed
    assert public.get('/healthz').status_code==200


def test_endpoint_manual_and_auto_same_clock_stale_result_never_merges(store,base,observers):
    key=save(store,base)['id'];worker=observers['endpoint'];configure(worker,key);observers['now']+=900
    started,resume=threading.Event(),threading.Event();errors=[];original=worker.probe
    def paused(*args):started.set();assert resume.wait(5);return original(*args)
    worker.probe=paused
    def automatic():
        try:worker.check(key,trigger='auto')
        except Exception as error:errors.append(error)
    thread=threading.Thread(target=automatic);thread.start();assert started.wait(2)
    worker.probe=original
    try:worker.check(key);completed=worker.path.read_bytes()
    finally:resume.set();thread.join(5)
    assert len(errors)==1 and errors[0].code=='health_conflict'
    assert worker.path.read_bytes()==completed and state(worker,key)['last_trigger']=='manual'


@pytest.mark.parametrize('corrupt',['endpoint','proxy'])
def test_corrupt_auxiliary_state_is_isolated_and_scheduler_logs_generic_only(store,base,observers,corrupt,caplog):
    key=save(store,base)['id']
    for kind in ('endpoint','proxy'):configure(observers[kind],key)
    observers[corrupt].path.write_text('PRIVATE UUID PROVIDER TOKEN corrupt json')
    observers['now']+=900;caplog.set_level(logging.INFO)
    assert scan(store,observers)==0
    other='proxy' if corrupt=='endpoint' else 'endpoint'
    assert state(observers[other],key)['last_trigger']=='auto'
    assert 'state unavailable' in caplog.text and 'PRIVATE' not in caplog.text and 'Traceback' not in caplog.text


@pytest.mark.parametrize('field,value',[('interval_seconds',None),('interval_seconds',True),('next_check_at',None),
    ('next_check_at',True),('next_check_at',float('nan')),('scheduler_failures',True),('scheduler_failures',-1),
    ('last_trigger','provider-private'),('last_job_result','PRIVATE'),('check_revision',True)])
@pytest.mark.parametrize('kind',['endpoint','proxy'])
def test_corrupt_v2_schedule_is_rejected_without_reset(store,base,observers,field,value,kind):
    key=save(store,base)['id'];worker=observers[kind];configure(worker,key)
    data,_=worker._read();data['subscriptions'][key][field]=value
    write_json(worker.path,data);before=worker.path.read_bytes()
    with pytest.raises((HealthError,ProxyHealthError)):worker.describe(key)
    assert worker.path.read_bytes()==before


@pytest.mark.parametrize('kind',['endpoint','proxy'])
def test_failed_manual_job_in_auto_does_not_move_due_or_add_scheduler_penalty(store,base,observers,kind):
    key=save(store,base)['id'];worker=observers[kind];configure(worker,key);before=worker.path.read_bytes()
    def fail(*args):raise RuntimeError('PRIVATE job failure')
    if kind=='endpoint':worker.probe=fail
    else:worker.runner=fail
    with pytest.raises((HealthError,ProxyHealthError)):worker.check(key)
    assert worker.path.read_bytes()==before


def test_health_cli_requires_once_and_sanitizes_unsafe_state(tmp_path,capsys,caplog):
    with pytest.raises(SystemExit):auto_health.main([])
    path=tmp_path/'unsafe';path.mkdir(mode=0o755);caplog.set_level(logging.INFO)
    assert auto_health.main(['--once','--state-dir',str(path)])==1
    assert 'critical state error' in caplog.text and str(path) not in caplog.text


@pytest.mark.parametrize('controller_failure',[False,True])
def test_auto_proxy_uses_existing_ephemeral_config_controller_and_cleanup(store,base,observers,monkeypatch,fake_batch,controller_failure):
    key=save(store,base)['id'];engine=observers['proxy'].engine
    worker=ProxyHealth(store,engine=engine,clock=lambda:observers['now'],resolver=public_resolver)
    observers['proxy']=worker;configure(worker,key);observers['now']+=900
    command=mihomo_probe.command
    def pinned_command(binary,*args,**kwargs):
        assert binary==engine.binary
        return command(binary,*args,**kwargs)
    monkeypatch.setattr(mihomo_probe,'command',pinned_command)
    monkeypatch.setattr(mihomo_probe,'ready',lambda *args:True)
    def answer(*args):
        if controller_failure:raise mihomo_probe.ProbeEngineError('PRIVATE controller detail')
        return dict(kind='success',latency_ms=11,error=None)
    monkeypatch.setattr(mihomo_probe,'probe_one',answer)
    assert scan(store,observers)==0
    value=state(worker,key)
    assert value['last_trigger']=='auto'
    assert fake_batch['runtime']==1 and len(fake_batch['stopped'])==1
    assert len(fake_batch['secrets'])==1 and len(fake_batch['secrets'][0])>=43
    assert not list(store.state.glob('.proxy-probe-*'))
    if controller_failure:
        assert not value['nodes'] and value['scheduler_failures']==1 and value['last_job_result']=='error'
    else:
        assert next(iter(value['nodes'].values()))['status']=='healthy' and value['last_job_result']=='success'


def test_cli_termination_unwinds_scheduler_context_and_restores_signal_handlers(store,monkeypatch,caplog):
    import signal
    from contextlib import contextmanager
    before=signal.getsignal(signal.SIGTERM);cleaned=[]
    @contextmanager
    def scope():
        try:yield
        finally:cleaned.append(True)
    def run(*args,**kwargs):
        with scope():signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
    monkeypatch.setattr(auto_health,'run_once',run);caplog.set_level(logging.INFO)
    with pytest.raises(SystemExit) as error:auto_health.main(['--once','--state-dir',str(store.state)])
    assert error.value.code==0 and cleaned==[True] and signal.getsignal(signal.SIGTERM)==before
    assert 'Automatic health stopped.' in caplog.text and 'Traceback' not in caplog.text


@pytest.mark.parametrize('kind',['endpoint','proxy'])
def test_source_automatic_refresh_revision_race_preserves_observations_and_retries(store,base,observers,response,kind):
    from core import auto_refresh
    from test_external_sources import external_save, payload, remote
    entry=external_save(store,base,sources=[remote(refresh_interval_seconds=900)],clock=lambda:observers['now'])
    key=entry['id'];worker=observers[kind];configure(worker,key);worker.check(key)
    before=state(worker,key)['nodes'];observers['now']+=900
    started,resume=threading.Event(),threading.Event();errors=[]
    original=worker.probe if kind=='endpoint' else worker.runner
    def paused(*args):started.set();assert resume.wait(5);return original(*args)
    if kind=='endpoint':worker.probe=paused
    else:worker.runner=paused
    def check():
        try:worker.check(key,trigger='auto')
        except Exception as error:errors.append(error)
    thread=threading.Thread(target=check);thread.start();assert started.wait(2)
    try:
        response['payload']=payload('Scheduled source update')
        assert auto_refresh.run_once(store,base,clock=lambda:observers['now'])==0
        newer=store.get(key);assert newer['revision']!=entry['revision']
    finally:resume.set();thread.join(5)
    assert len(errors)==1 and errors[0].code=='conflict'
    value=state(worker,key)
    assert value['nodes']==before and value['last_job_result']=='conflict' and value['scheduler_failures']==0
    assert value['next_check_at']==observers['now']+300
    assert b'Scheduled source update' in store.snapshot(key)[1]


def test_two_scheduler_scans_concurrently_only_one_probes(store,base,observers):
    key=save(store,base)['id'];worker=observers['endpoint'];configure(worker,key);observers['now']+=900
    started,resume=threading.Event(),threading.Event();results=[];original=worker.probe
    def paused(*args):started.set();assert resume.wait(5);return original(*args)
    worker.probe=paused
    thread=threading.Thread(target=lambda:results.append(scan(store,observers)))
    thread.start();assert started.wait(2)
    try:assert scan(store,observers)==0 and not observers['endpoint_calls']
    finally:resume.set();thread.join(5)
    assert results==[0] and len(observers['endpoint_calls'])==1
