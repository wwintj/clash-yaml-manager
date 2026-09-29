"""Full-proxy auxiliary-state tests with controlled engine/controller outcomes."""
import copy
import json
import logging
import os
from pathlib import Path
import socket
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core import auto_refresh, mihomo_probe, node_health, proxy_health, source_fetch
from core.mihomo_manager import ManagedMihomo
from core.proxy_health import DEFAULT_PROBE, ProxyHealth, ProxyHealthError
from core.state import file_lock, write_json
from conftest import LINK, post
from test_fixed_subscriptions import base, save, source, store
from test_external_sources import external_save, payload, remote, response
from test_fixed_views import create
from test_deployment import deployment


def public_resolver(host,port,deadline):
    if host == 'mixed.example':
        return [(socket.AF_INET,0,('8.8.8.8',port)),(socket.AF_INET,0,('10.0.0.1',port))]
    return [(socket.AF_INET,0,('8.8.8.8',port))]


@pytest.fixture
def observer(store):
    state = dict(now=1_800_000_000,calls=[],kind='success',error=None,latency=42)
    engine = SimpleNamespace(binary=Path('/fixture/mihomo'),
        status=lambda:dict(status='COMPATIBLE',required='v1.19.31',installed='v1.19.31',architecture='amd64'))
    def run(binary,nodes,settings,directory):
        assert binary == engine.binary and directory == store.state
        state['calls'].append((len(nodes),copy.deepcopy(settings)))
        return {node['fingerprint']:dict(kind=state['kind'],error=state['error'],
                                         latency_ms=state['latency'] if state['kind']=='success' else None)
                for node in nodes}
    state['worker'] = ProxyHealth(store,engine=engine,runner=run,clock=lambda:state['now'],resolver=public_resolver)
    return state


def checked(store,base,observer):
    entry = save(store,base)
    observer['worker'].settings(entry['id'],'manual',True)
    observer['worker'].check(entry['id'])
    return entry


def test_off_default_optional_engine_and_no_mutation(store,base,observer):
    entry = save(store,base); worker = observer['worker']
    fixed = store.path.read_bytes(); yaml = store._content(entry,'current.yaml')
    shown = worker.describe(entry['id'])
    assert shown['mode']=='off' and shown['counts']['unknown']==1
    assert not worker.path.exists() and observer['calls']==[]
    with pytest.raises(ProxyHealthError,match='Enable Manual'):
        worker.check(entry['id'])
    assert store.path.read_bytes()==fixed and store._content(entry,'current.yaml')==yaml


def test_mode_settings_global_override_and_url_stability(store,base,observer):
    entry = save(store,base); worker = observer['worker']; old=store.path.read_bytes()
    yaml=store._content(entry,'current.yaml')
    worker.set_global(dict(url='https://probe.example/status',expected_status=205,timeout_ms=5000))
    worker.settings(entry['id'],'manual',True); worker.check(entry['id'])
    assert observer['calls'][-1][1]['expected_status']==205
    custom=dict(url='https://other.example/probe',expected_status=204,timeout_ms=10000)
    worker.settings(entry['id'],'manual',False,custom); worker.check(entry['id'])
    assert observer['calls'][-1][1]==custom
    worker.settings(entry['id'],'off',True)
    assert worker.describe(entry['id'])['effective']['expected_status']==205
    assert store.path.read_bytes()==old and store._content(entry,'current.yaml')==yaml


def test_changing_effective_probe_target_invalidates_old_observations(store,base,observer):
    entry=checked(store,base,observer); worker=observer['worker']; key=entry['id']
    assert worker.describe(key)['rows'][0]['status']=='healthy'
    worker.set_global(dict(url='https://probe.example/next',expected_status=204,timeout_ms=8000))
    assert worker.describe(key)['rows'][0]['status']=='unknown'
    worker.check(key)
    custom=dict(url='https://other.example/check',expected_status=205,timeout_ms=5000)
    worker.settings(key,'manual',False,custom)
    assert worker.describe(key)['rows'][0]['status']=='unknown'
    worker.check(key)
    worker.set_global(dict(url='https://probe.example/another',expected_status=204,timeout_ms=8000))
    assert worker.describe(key)['rows'][0]['status']=='healthy'
    worker.settings(key,'manual',True)
    assert worker.describe(key)['rows'][0]['status']=='unknown'


@pytest.mark.parametrize('url',[
    'http://8.8.8.8/test','file:///etc/passwd','ftp://8.8.8.8/file','https://localhost/',
    'https://127.0.0.1/','https://[::1]/','https://10.0.0.1/','https://172.16.0.1/',
    'https://192.168.1.1/','https://169.254.169.254/','https://224.0.0.1/',
    'https://192.0.2.1/','https://user:pass@8.8.8.8/','https://8.8.8.8/?token=PRIVATE',
    'https://8.8.8.8/#fragment','https://8.8.8.8:0/','https://mixed.example/',
    r'https://8.8.8.8\@evil.example/',
])
def test_probe_target_blocks_unsafe_or_ambiguous_url(url,observer):
    settings=dict(DEFAULT_PROBE,url=url)
    with pytest.raises(ProxyHealthError,match='public HTTPS'):
        observer['worker'].set_global(settings)
    assert not observer['worker'].path.exists()


def test_valid_public_https_and_invalid_numeric_settings(observer):
    worker=observer['worker']
    worker.set_global(dict(url='https://probe.example:8443/status',expected_status=299,timeout_ms=15000))
    assert worker._read()[0]['global']['url']=='https://probe.example:8443/status'
    for field,value in [('expected_status',True),('expected_status',600),('timeout_ms',False),
                        ('timeout_ms',2999),('timeout_ms',15001)]:
        with pytest.raises(ProxyHealthError):
            worker.set_global(dict(DEFAULT_PROBE,**{field:value}))


def test_failure_threshold_reset_unsupported_and_no_exclusion(store,base,observer,caplog):
    caplog.set_level(logging.INFO)
    entry=save(store,base); worker=observer['worker']; key=entry['id']
    worker.settings(key,'manual',True)
    fixed=store.path.read_bytes(); current=store._content(entry,'current.yaml')
    observer.update(kind='failure',error='proxy_failed')
    for count,status in enumerate(('suspect','suspect','unhealthy','unhealthy'),1):
        observer['now']+=1; worker.check(key)
        row=worker.describe(key)['rows'][0]
        assert row['status']==status and row['consecutive_failures']==count
        assert row['latency_ms'] is None
        assert store._content(entry,'current.yaml')==current
    observer.update(kind='success',error=None)
    observer['now']+=1; worker.check(key)
    row=worker.describe(key)['rows'][0]
    assert row['status']=='healthy' and row['consecutive_failures']==0
    assert row['latency_ms']==42 and row['last_success_at']==observer['now']
    observer.update(kind='unsupported',error='unsupported_config')
    observer['now']+=1; worker.check(key)
    row=worker.describe(key)['rows'][0]
    assert row['status']=='unsupported' and row['consecutive_failures']==0
    assert row['last_success_at']==observer['now']-1
    assert store.path.read_bytes()==fixed and store._content(entry,'current.yaml')==current
    raw=worker.path.read_bytes()
    for secret in ('example.com',LINK,entry['token'],'11111111-1111-4111-8111-111111111111','/fixture/mihomo'):
        assert secret.encode() not in raw and secret not in caplog.text
    assert worker.path.stat().st_mode & 0o777==0o600 and worker.lock.stat().st_mode & 0o777==0o600


def test_engine_error_and_invalid_runner_outcome_do_not_penalize(store,base,observer):
    entry=checked(store,base,observer); worker=observer['worker']; before=worker.path.read_bytes()
    worker.runner=lambda *a:(_ for _ in ()).throw(mihomo_probe.ProbeEngineError('PRIVATE secret'))
    with pytest.raises(ProxyHealthError,match='engine could not complete'):
        worker.check(entry['id'])
    assert worker.path.read_bytes()==before
    worker.runner=lambda *a:{'not-fingerprint':dict(kind='failure',error='proxy_failed')}
    with pytest.raises(ProxyHealthError,match='engine could not complete'):
        worker.check(entry['id'])
    assert worker.path.read_bytes()==before


def test_fingerprint_rename_config_change_and_prune(store,base,observer):
    entry=checked(store,base,observer); worker=observer['worker']; original=worker._read()[0]['subscriptions'][entry['id']]['nodes']
    save(store,base,entry['id'],source('Renamed'))
    assert worker.describe(entry['id'])['rows'][0]['status']=='healthy'
    config=source('Changed'); config['batch_nodes']=config['batch_nodes'].replace('example.com','other.example')
    save(store,base,entry['id'],config)
    assert worker.describe(entry['id'])['rows'][0]['status']=='unknown'
    worker.check(entry['id'])
    new=worker._read()[0]['subscriptions'][entry['id']]['nodes']
    assert len(new)==1 and not set(new)&set(original)


@pytest.mark.parametrize('count',[256,257])
def test_256_limit_before_engine_and_state_mutation(store,base,observer,count):
    config=source(); config['batch_nodes']='\n'.join(
        f'US|Node {i}|{LINK.replace("example.com",str(i)+".example")}' for i in range(count))
    entry=save(store,base,config=config); worker=observer['worker']; worker.settings(entry['id'],'manual',True)
    before=worker.path.read_bytes()
    if count==257:
        with pytest.raises(ProxyHealthError,match='up to 256'):
            worker.check(entry['id'])
        assert observer['calls']==[] and worker.path.read_bytes()==before
    else:
        worker.check(entry['id']); assert worker.describe(entry['id'])['total']==256


def test_global_singleton_busy_without_second_probe(store,base,observer):
    entry=save(store,base); worker=observer['worker']; worker.settings(entry['id'],'manual',True)
    with file_lock(worker.job_lock):
        with pytest.raises(ProxyHealthError,match='already running'):
            worker.check(entry['id'])
    assert observer['calls']==[]


@pytest.mark.parametrize('mutation',['save','auto','delete','regenerate','disable','off','global'])
def test_network_outside_fixed_lock_revision_and_settings_conflicts(
        store,base,response,observer,mutation):
    entry=external_save(store,base,sources=[remote(refresh_interval_seconds=900)],clock=lambda:observer['now'])
    worker=observer['worker']; worker.settings(entry['id'],'manual',True); worker.check(entry['id'])
    before=worker.path.read_bytes(); slug=store.slug(entry); public=store.resolve(slug)
    started,resume,completed=threading.Event(),threading.Event(),threading.Event(); errors=[]; request_errors=[]
    def paused(binary,nodes,settings,directory):
        started.set(); assert resume.wait(5)
        return {n['fingerprint']:dict(kind='success',error=None,latency_ms=10) for n in nodes}
    worker.runner=paused
    def check():
        try: worker.check(entry['id'])
        except BaseException as error: errors.append(error)
    thread=threading.Thread(target=check); thread.start(); assert started.wait(3)
    def mutate():
        try:
            assert store.resolve(slug)==public
            if mutation=='save':
                external_save(store,base,entry,source('Changed'),sources=entry['sources'][1:],refresh=set())
            elif mutation=='auto':
                observer['now']+=900; response['payload']=payload('London auto')
                assert auto_refresh.run_once(store,base,clock=lambda:observer['now'])==0
            elif mutation=='off':
                worker.settings(entry['id'],'off',True)
            elif mutation=='global':
                worker.set_global(dict(url='https://other.example/generate_204',expected_status=204,timeout_ms=8000))
            else: store.action(entry['id'],mutation)
        except BaseException as error: request_errors.append(error)
        finally: completed.set()
    other=threading.Thread(target=mutate); other.start()
    try: assert completed.wait(2),'Fixed lock held across proxy probe'
    finally: resume.set(); thread.join(5); other.join(5)
    assert not request_errors
    if mutation in ('regenerate','disable'):
        assert not errors and worker.describe(entry['id'])['counts']['healthy']==2
    else:
        assert len(errors)==1 and isinstance(errors[0],ProxyHealthError)
        assert errors[0].code==('health_conflict' if mutation in ('off','global') else 'conflict')
        if mutation in ('save','auto'): assert worker.path.read_bytes()==before
    if mutation=='auto': assert b'London auto' in store.resolve(slug)


@pytest.mark.parametrize('bad',['json','schema','state-mode','state-symlink','state-fifo',
    'lock-mode','lock-symlink','lock-fifo'])
def test_corrupt_auxiliary_state_does_not_break_fixed_endpoint_or_healthz(web,logged_in,bad):
    entry=create(web,logged_in); store=web.fixed_subscriptions; worker=ProxyHealth(store)
    worker.settings(entry['id'],'manual',True)
    path=worker.path
    if bad=='json': path.write_text('PRIVATE broken json')
    if bad=='schema': write_json(path,dict(version=99,subscriptions={}))
    if bad.endswith('mode'):
        (worker.lock if bad=='lock-mode' else path).chmod(0o644)
    if bad.endswith('symlink'):
        target=worker.lock if bad=='lock-symlink' else path
        target.unlink(); target.symlink_to(store.path)
    if bad.endswith('fifo'):
        target=worker.lock if bad=='lock-fifo' else path
        target.unlink(); os.mkfifo(target,0o600)
    public='/s/'+store.slug(entry)
    assert web.app.test_client().get(public).status_code==200
    assert web.app.test_client().get('/healthz').status_code==200
    page=logged_in.get(f'/fixed-subscriptions/{entry["id"]}/edit')
    assert page.status_code==200 and b'Proxy health state unavailable.' in page.data
    assert b'PRIVATE broken json' not in page.data
    assert node_health.NodeHealth(store).describe(entry['id'])['mode']=='off'


@pytest.mark.parametrize('mode',['before','after'])
def test_proxy_state_write_failure_restores_old_and_fixed(web,logged_in,monkeypatch,mode):
    entry=create(web,logged_in); store=web.fixed_subscriptions; key=entry['id']
    worker=ProxyHealth(store); worker.settings(key,'manual',True)
    before=worker.path.read_bytes(); fixed=store.path.read_bytes()
    monkeypatch.setattr(ManagedMihomo,'status',lambda self:dict(status='COMPATIBLE'))
    monkeypatch.setattr(source_fetch,'_resolve',public_resolver)
    monkeypatch.setattr(mihomo_probe,'run',lambda binary,nodes,settings,state:{
        n['fingerprint']:dict(kind='success',error=None,latency_ms=5) for n in nodes})
    original=proxy_health.write_json
    def fail(path,value):
        if mode=='after': original(path,value)
        raise OSError('PRIVATE disk detail')
    with monkeypatch.context() as patcher:
        patcher.setattr(proxy_health,'write_json',fail)
        result=post(logged_in,f'/fixed-subscriptions/{key}/proxy-health/check',follow_redirects=True)
    assert b'Proxy health results could not be saved.' in result.data
    assert b'PRIVATE disk detail' not in result.data
    assert worker.path.read_bytes()==before and store.path.read_bytes()==fixed
    assert web.app.test_client().get('/s/'+store.slug(entry)).status_code==200


def test_delete_cleanup_and_uninstall_backup(store,base,observer,deployment):
    entry=checked(store,base,observer); worker=observer['worker']
    store.action(entry['id'],'delete')
    assert entry['id'] not in worker._read()[0]['subscriptions']
    installed,source,_,_,_,run=deployment
    installed_state=installed/'state'; installed_state.mkdir(mode=0o700)
    (installed_state/'proxy_health.json').write_bytes(b'private auxiliary fixture')
    scratch=installed_state/'.proxy-probe-stale'
    scratch.mkdir(mode=0o700)
    (scratch/'config.yaml').write_text('PRIVATE temporary Mihomo credentials')
    result=run(); assert result.returncode==0,result.stdout+result.stderr
    assert (installed_state/'proxy_health.json').read_bytes()==b'private auxiliary fixture'
    assert (scratch/'config.yaml').exists()
    backup=next(installed.parent.glob('upgrade-backup-*/state/proxy_health.json'))
    assert backup.read_bytes()==b'private auxiliary fixture'
    assert not list(installed.parent.glob('upgrade-backup-*/state/.proxy-probe-*'))
    result=run('uninstall.sh',input_text='y\n\n')
    assert result.returncode==0,result.stderr
    backup=next(installed.parent.glob('uninstall-backup-*/state/proxy_health.json'))
    assert backup.read_bytes()==b'private auxiliary fixture'
    assert not list(installed.parent.glob('uninstall-backup-*/state/.proxy-probe-*'))


def test_web_auth_csrf_engine_status_and_no_secret_html(web,logged_in,monkeypatch):
    entry=create(web,logged_in); key=entry['id']; worker=ProxyHealth(web.fixed_subscriptions)
    root=f'/fixed-subscriptions/{key}/proxy-health/'
    page=logged_in.get(f'/fixed-subscriptions/{key}/edit')
    section=page.data.split(b'<section id="proxy-health"')[1].split(b'</section>')[0]
    assert b'NOT INSTALLED' in section and b'Check Proxies Now' not in section
    assert b'Proxy health is relative' not in section  # Copy uses a complete target-relative sentence.
    for operation in ('settings','check'):
        assert logged_in.get(root+operation).status_code==405
        assert web.app.test_client().post(root+operation).status_code in (302,303)
        assert logged_in.post(root+operation).status_code==303
    assert not worker.path.exists()
    assert post(logged_in,root+'settings',{'mode':'manual','scope':'global'}).status_code==303
    monkeypatch.setattr(ManagedMihomo,'status',lambda self:dict(status='COMPATIBLE',
        required='v1.19.31',installed='v1.19.31',architecture='arm64'))
    monkeypatch.setattr(source_fetch,'_resolve',public_resolver)
    monkeypatch.setattr(mihomo_probe,'run',lambda binary,nodes,settings,state:{
        n['fingerprint']:dict(kind='success',error=None,latency_ms=38) for n in nodes})
    assert post(logged_in,root+'check').status_code==303
    page=logged_in.get(f'/fixed-subscriptions/{key}/edit')
    section=page.data.split(b'<section id="proxy-health"')[1].split(b'</section>')[0]
    assert b'HEALTHY' in section and b'38 ms' in section
    for secret in (LINK.encode(),entry['token'].encode(),b'example.com',b'11111111-1111-4111-8111-111111111111'):
        assert secret not in section and secret not in worker.path.read_bytes()
    assert b'v1.19.31' in section
