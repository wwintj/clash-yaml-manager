"""Controlled endpoint probes and auxiliary-state invariants; no public networking."""
import copy
import errno
import io
import json
import logging
import os
import socket
import subprocess
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from ruamel.yaml import YAML

from core import auto_refresh, node_health as health, node_probe, source_fetch
from core.node_health import HealthError, NodeHealth
from core.state import StateError, file_lock, read_private_bytes, write_json
from conftest import LINK, post
from test_fixed_subscriptions import BASE, base, parsed, save, source, store
from test_external_sources import external_save, payload, remote, response
from test_deployment import deployment


def proxy(**changes):
    return dict(dict(name='US Endpoint',type='vless',server='endpoint.example',port=443,
                     uuid='11111111-1111-4111-8111-111111111111'),**changes)


def yaml_bytes(nodes):
    stream = io.StringIO(); YAML().dump(dict(proxies=nodes), stream)
    return stream.getvalue().encode()


@pytest.fixture
def observer(store):
    state = dict(now=1_800_000_000,calls=[],error=None)
    def probe(server, port):
        state['calls'].append((server,port))
        return dict(error=state['error'],latency_ms=None if state['error'] else 37.6)
    state['health'] = NodeHealth(store,clock=lambda:state['now'],probe=probe)
    return state


def checked(store, base, observer):
    entry = save(store, base)
    observer['health'].settings(entry['id'],'manual')
    observer['health'].check(entry['id'])
    return entry


@pytest.mark.parametrize('changes', [dict(),dict(name='Renamed'),dict(**{'ws-opts':{'headers':{'a':'1','b':'2'}}})])
def test_fingerprint_deterministic_and_config_order_independent(changes):
    config = proxy(**changes)
    assert health.fingerprint(config) == health.fingerprint(dict(reversed(list(config.items()))))
    renamed = dict(config,name='Other')
    assert health.fingerprint(config) == health.fingerprint(renamed)
    assert len(health.fingerprint(config)) == 64 and config['uuid'] not in health.fingerprint(config)


@pytest.mark.parametrize('changes',[dict(server='other.example'),dict(port=8443),dict(uuid='different'),
    dict(type='vmess'),dict(network='ws'),dict(tls=True),dict(servername='sni.example'),dict(alpn=['h2']),
    {'ws-opts':{'path':'/other'}},{'reality-opts':{'public-key':'test-public','short-id':'test-id'}},
    {'client-fingerprint':'chrome'}])
def test_connection_config_changes_identity(changes):
    assert health.fingerprint(proxy()) != health.fingerprint(proxy(**changes))


@pytest.mark.parametrize('nodes',[[],[dict(type='ss',server='127.0.0.1',port=22)],
    [proxy(),dict(type='future-protocol')],[proxy(type='vmess')]])
def test_extract_ignores_unsupported_types(nodes):
    result = health.extract(yaml_bytes(nodes))
    assert len(result) == sum(n['type'] in ('vmess','vless') for n in nodes)


@pytest.mark.parametrize('change',[dict(server=''),dict(server=None),dict(port=True),dict(port='443'),
    dict(port=0),dict(port=65536)])
def test_invalid_supported_endpoint_fails_without_probe(change):
    with pytest.raises(HealthError,match='unavailable'): health.extract(yaml_bytes([proxy(**change)]))


@pytest.mark.parametrize('bad',[b'proxies: [',b'proxies: nope',b'!!python/object/apply:os.system [PRIVATE]',
    b'proxies: &a [{type: vless, name: n, server: s, port: 443, cycle: *a}]'])
def test_unsafe_yaml_extraction_is_sanitized(bad):
    with pytest.raises(HealthError) as error: health.extract(bad)
    assert 'PRIVATE' not in str(error.value)


@pytest.mark.parametrize('name', ['endpoint.example:443','443','11111111-1111-4111-8111-111111111111',
    'vless://PRIVATE','https://provider.example/?token=PRIVATE'])
def test_names_cannot_smuggle_endpoint_or_credentials_into_health_table(name):
    assert health.extract(yaml_bytes([proxy(name=name)]))[0]['name'] == 'Node 1'


def test_fixed_bearer_token_in_node_name_is_masked_in_health_rows(store,base):
    entry = save(store,base)
    save(store,base,entry['id'],source(entry['token']))
    rows = NodeHealth(store).describe(entry['id'])['rows']
    assert len(rows) == 1 and entry['token'] not in rows[0]['name']


@pytest.fixture
def transport(monkeypatch):
    state = dict(dns=[],connect=[],closed=0,error=None,addresses=['8.8.8.8'])
    def dns(command, **kwargs):
        server, port = json.loads(kwargs['input']); state['dns'].append(server)
        assert 0 < kwargs['timeout'] <= 3
        return SimpleNamespace(stdout=json.dumps([(socket.AF_INET6 if ':' in ip else socket.AF_INET,
            socket.SOCK_STREAM,6,'',[ip,port]) for ip in state['addresses']]))
    class FakeSocket:
        def __init__(self,*args): state['socket_args'] = args
        def settimeout(self,value): assert 0 < value <= 3; state['timeout'] = value
        def connect(self,address):
            state['connect'].append(address)
            if state['error']: raise state['error']
        def close(self): state['closed'] += 1
        def send(self,*args): pytest.fail('TCP probe sent application data')
        sendall = send
    monkeypatch.setattr(source_fetch.subprocess,'run',dns)
    monkeypatch.setattr(node_probe.socket,'socket',FakeSocket)
    monkeypatch.setattr(node_probe.socket,'getaddrinfo',lambda *a,**kw:pytest.fail('second DNS lookup'))
    return state


@pytest.mark.parametrize('address',['8.8.8.8','2606:4700:4700::1111'])
def test_public_ipv4_ipv6_and_direct_pinned_socket(transport,monkeypatch,address):
    transport['addresses'] = [address]
    for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
        monkeypatch.setenv(key,'http://PRIVATE.invalid:9')
    result = node_probe.probe('endpoint.example',443)
    assert result['error'] is None and result['latency_ms'] >= 0
    assert transport['dns'] == ['endpoint.example'] and transport['connect'] == [(address,443)]
    assert transport['closed'] == 1 and transport['socket_args'][1] == socket.SOCK_STREAM


@pytest.mark.parametrize('address',['127.0.0.1','::1','10.0.0.1','172.16.0.1','172.31.255.255',
    '192.168.0.1','169.254.1.1','169.254.169.254','0.0.0.0','::','224.0.0.1','ff02::1',
    '240.0.0.1','192.0.2.1','198.51.100.1','203.0.113.1','fe80::1','fc00::1',
    '::ffff:127.0.0.1','2002:7f00:1::','2606:4700:4700::1111%eth0'])
def test_private_literal_rejected_before_socket(transport,address):
    assert node_probe.probe(address,443)['error'] == 'blocked_address'
    assert not transport['connect'] and not transport['dns']


def test_mixed_dns_rejects_entire_answer(transport):
    transport['addresses'] = ['8.8.8.8','10.0.0.1']
    assert node_probe.probe('endpoint.example',443)['error'] == 'blocked_address'
    assert not transport['connect']


def test_one_blocked_node_does_not_prevent_other_public_probe(store,base,transport):
    config = source(); config['batch_nodes'] = '\n'.join((
        f'US|Public|{LINK.replace("example.com","8.8.8.8")}',
        f'US|Blocked|{LINK.replace("example.com","127.0.0.1")}'))
    entry = save(store,base,config=config); old = store._content(entry,'current.yaml')
    worker = NodeHealth(store); worker.settings(entry['id'],'manual'); worker.check(entry['id'])
    rows = worker.describe(entry['id'])['rows']
    assert [r['status'] for r in rows] == ['healthy','suspect']
    assert rows[1]['error'] == 'blocked_address'
    assert transport['connect'] == [('8.8.8.8',443)] and store.resolve(store.slug(entry)) == old


@pytest.mark.parametrize('address',['8.8.8.8','2606:4700:4700::1111'])
def test_literal_skips_dns(transport,address):
    assert node_probe.probe(address,443)['error'] is None
    assert transport['dns'] == [] and transport['connect'] == [(address,443)]


@pytest.mark.parametrize('exception,code', [(socket.timeout('PRIVATE endpoint'),'timeout'),
    (OSError(errno.ECONNREFUSED,'PRIVATE'),'connection_refused'),
    (OSError(errno.ENETUNREACH,'PRIVATE'),'network_unreachable'),
    (OSError(errno.EHOSTUNREACH,'PRIVATE'),'network_unreachable'),
    (OSError(errno.ETIMEDOUT,'PRIVATE'),'timeout'),
    (OSError(errno.EIO,'PRIVATE'),'connect_failed')])
def test_tcp_failures_sanitized_and_closed(transport,exception,code):
    transport['error'] = exception
    result = node_probe.probe('endpoint.example',443)
    assert result == dict(error=code,latency_ms=None) and transport['closed'] == 1
    assert 'PRIVATE' not in json.dumps(result)


@pytest.mark.parametrize('exception,code',[(subprocess.TimeoutExpired(['PRIVATE'],3),'timeout'),
    (subprocess.CalledProcessError(1,['PRIVATE']),'dns_failed'),(OSError('PRIVATE'),'dns_failed')])
def test_dns_deadline_failure_sanitized(monkeypatch,exception,code):
    def fail(*args,**kwargs): raise exception
    monkeypatch.setattr(source_fetch.subprocess,'run',fail)
    assert node_probe.probe('endpoint.example',443) == dict(error=code,latency_ms=None)


@pytest.mark.parametrize('server',['endpoint.example%zone','user@host','http://host','host\nPRIVATE','[::1]'])
def test_invalid_host_syntax_never_connects(transport,server):
    assert node_probe.probe(server,443)['error'] is not None and not transport['connect']


@pytest.mark.parametrize('end,latency',[(10.038,38),(9.9,0)])
def test_latency_uses_monotonic_connect_only(transport,end,latency):
    values = iter((1,2,10,end))
    resolver = lambda *args:[(socket.AF_INET,6,('8.8.8.8',443))]
    result = node_probe.probe('endpoint.example',443,resolver=resolver,monotonic=lambda:next(values))
    assert result['error'] is None and round(result['latency_ms']) == latency


def test_dns_consumes_same_three_second_budget_without_connect(transport):
    values = iter((10,14))
    result = node_probe.probe('endpoint.example',443,resolver=lambda *a:[(socket.AF_INET,6,('8.8.8.8',443))],
                             monotonic=lambda:next(values))
    assert result['error'] == 'timeout' and not transport['connect']


def test_default_off_no_health_file_no_network_no_fixed_mutation(store,base,observer):
    entry = save(store,base); before = store.path.read_bytes(); current = store._content(entry,'current.yaml')
    description = observer['health'].describe(entry['id'])
    assert description['mode'] == 'off' and description['counts']['unknown'] == 1
    assert not observer['health'].path.exists() and observer['calls'] == []
    with pytest.raises(HealthError,match='Enable Manual'): observer['health'].check(entry['id'])
    assert store.path.read_bytes() == before and store._content(entry,'current.yaml') == current


def test_failure_threshold_success_reset_and_no_exclusion(store,base,observer,caplog):
    caplog.set_level(logging.INFO)
    entry = save(store,base); worker = observer['health']; worker.settings(entry['id'],'manual')
    fixed_before = store.path.read_bytes(); current = store._content(entry,'current.yaml'); slug = store.slug(entry)
    observer['error'] = 'connection_refused'
    for count,status in enumerate(('suspect','suspect','unhealthy','unhealthy'),1):
        observer['now'] += 1; worker.check(entry['id']); row = worker.describe(entry['id'])['rows'][0]
        assert row['status'] == status and row['consecutive_failures'] == count
        assert row['latency_ms'] is None and row['last_success_at'] is None
        assert store.path.read_bytes() == fixed_before and store._content(entry,'current.yaml') == current
    observer['error'] = None; observer['now'] += 1; worker.check(entry['id'])
    row = worker.describe(entry['id'])['rows'][0]
    assert row['status'] == 'healthy' and row['consecutive_failures'] == 0 and row['error'] is None
    assert row['last_success_at'] == row['last_checked_at'] == observer['now'] and row['latency_ms'] == 37.6
    observer['error'] = 'timeout'; observer['now'] += 1; worker.check(entry['id'])
    assert worker.describe(entry['id'])['rows'][0]['last_success_at'] == observer['now']-1
    worker.settings(entry['id'],'off')
    assert store.path.read_bytes() == fixed_before and store.resolve(slug) == current
    raw = worker.path.read_bytes(); assert worker.path.stat().st_mode & 0o777 == 0o600
    assert worker.lock.stat().st_mode & 0o777 == 0o600
    for secret in ('example.com',LINK,'11111111-1111-4111-8111-111111111111',entry['token'],'vmess://','vless://'):
        assert secret.encode() not in raw and secret not in caplog.text
    for fp in json.loads(raw)['subscriptions'][entry['id']]['nodes']: assert fp not in caplog.text


def test_name_rename_reuses_health_config_change_unknown_and_next_check_prunes(store,base,observer):
    entry = checked(store,base,observer); worker = observer['health']
    original = json.loads(worker.path.read_bytes())['subscriptions'][entry['id']]['nodes']
    renamed = save(store,base,entry['id'],source('Renamed'))
    assert worker.describe(entry['id'])['rows'][0]['status'] == 'healthy'
    changed = source('Changed'); changed['batch_nodes'] = changed['batch_nodes'].replace('example.com','other.example')
    save(store,base,entry['id'],changed)
    assert worker.describe(entry['id'])['rows'][0]['status'] == 'unknown'
    assert json.loads(worker.path.read_bytes())['subscriptions'][entry['id']]['nodes'] == original
    worker.check(entry['id'])
    new = json.loads(worker.path.read_bytes())['subscriptions'][entry['id']]['nodes']
    assert len(new) == 1 and not set(new) & set(original)


@pytest.mark.parametrize('action',['disable','delete'])
def test_removed_source_nodes_are_hidden_then_pruned(store,base,response,observer,action):
    response['payload'] = payload('Tokyo-remote').replace(b'@example.com:', b'@remote.example:')
    entry = external_save(store,base,sources=[remote()]); worker = observer['health']
    worker.settings(entry['id'],'manual'); worker.check(entry['id'])
    before = json.loads(worker.path.read_bytes())['subscriptions'][entry['id']]['nodes']
    assert len(before) == 2
    store.source_action(entry['id'],action,base,entry['sources'][1]['id'])
    visible = worker.describe(entry['id'])
    assert visible['total'] == 1 and visible['counts']['healthy'] == 1
    assert json.loads(worker.path.read_bytes())['subscriptions'][entry['id']]['nodes'] == before
    worker.check(entry['id'])
    after = json.loads(worker.path.read_bytes())['subscriptions'][entry['id']]['nodes']
    assert len(after) == 1 and set(after) < set(before)


@pytest.mark.parametrize('count',[256,257])
def test_node_limit_enforced_before_probe_state_unchanged(store,base,observer,count):
    config = source(); config['batch_nodes'] = '\n'.join(f'US|Node {i}|{LINK.replace("example.com",str(i)+".example")}' for i in range(count))
    entry = save(store,base,config=config); worker = observer['health']; worker.settings(entry['id'],'manual')
    old = worker.path.read_bytes()
    if count == 257:
        with pytest.raises(HealthError,match='up to 256'): worker.check(entry['id'])
        assert worker.path.read_bytes() == old and observer['calls'] == []
    else:
        worker.check(entry['id']); assert worker.describe(entry['id'])['total'] == 256


def test_bounded_parallel_workers_not_sequential_or_unbounded(store,base):
    config = source(); config['batch_nodes'] = '\n'.join(f'US|Node {i}|{LINK.replace("example.com",str(i)+".example")}' for i in range(32))
    entry = save(store,base,config=config); lock = threading.Lock(); started = threading.Event(); resume = threading.Event()
    state = dict(active=0,maximum=0,calls=0)
    def probe(*args):
        with lock:
            state['active'] += 1; state['calls'] += 1; state['maximum'] = max(state['maximum'],state['active'])
            if state['active'] == 16: started.set()
        assert resume.wait(5)
        with lock: state['active'] -= 1
        return dict(latency_ms=1,error=None)
    worker = NodeHealth(store,probe=probe); worker.settings(entry['id'],'manual'); errors = []
    def run():
        try: worker.check(entry['id'])
        except BaseException as error: errors.append(error)
    thread = threading.Thread(target=run); thread.start()
    try: assert started.wait(3), 'checks were sequential'
    finally: resume.set(); thread.join(5)
    assert not errors and state['maximum'] == 16 and state['calls'] == 32


@pytest.mark.parametrize('mutation',['save','auto','refresh','source-disable','delete','regenerate','disable','off','other-check'])
def test_network_outside_fixed_lock_and_conflict_rules(store,base,response,observer,monkeypatch,mutation):
    entry = external_save(store,base,sources=[remote(refresh_interval_seconds=900)],clock=lambda:observer['now'])
    worker = observer['health']; worker.settings(entry['id'],'manual'); worker.check(entry['id'])
    before = worker.path.read_bytes(); slug = store.slug(entry); public = store.resolve(slug)
    started, resume, completed = threading.Event(),threading.Event(),threading.Event(); errors = []
    def probe(*args): started.set(); assert resume.wait(5); return dict(latency_ms=2,error=None)
    worker.probe = probe
    def check():
        try: worker.check(entry['id'])
        except BaseException as error: errors.append(error)
    thread = threading.Thread(target=check); thread.start(); assert started.wait(3)
    request_errors = []
    def request():
        try:
            assert store.resolve(slug) == public
            if mutation == 'save':
                external_save(store,base,entry,source('New manual'),sources=entry['sources'][1:],refresh=set())
            elif mutation == 'auto':
                observer['now'] += 900; response['payload'] = payload('London auto')
                assert auto_refresh.run_once(store,base,clock=lambda:observer['now']) == 0
            elif mutation == 'refresh': store.source_action(entry['id'],'refresh-all',base)
            elif mutation == 'source-disable': store.source_action(entry['id'],'disable',base,entry['sources'][1]['id'])
            elif mutation == 'off': NodeHealth(store).settings(entry['id'],'off')
            elif mutation == 'other-check':
                NodeHealth(store,probe=lambda *a:dict(error=None,latency_ms=10)).check(entry['id'])
            else: store.action(entry['id'],mutation)
        except BaseException as error: request_errors.append(error)
        finally: completed.set()
    other = threading.Thread(target=request); other.start()
    try: assert completed.wait(2), 'Fixed or Health lock was held over network'
    finally: resume.set(); thread.join(5); other.join(5)
    assert not request_errors
    if mutation in ('regenerate','disable'):
        assert errors == [] and worker.describe(entry['id'])['counts']['healthy'] == 2
    else:
        assert len(errors) == 1 and isinstance(errors[0],HealthError)
        assert errors[0].code == ('health_conflict' if mutation in ('off','other-check') else 'conflict')
        if mutation not in ('delete','off','other-check'): assert worker.path.read_bytes() == before
    if mutation == 'save': assert b'New manual' in store.resolve(slug)
    if mutation == 'auto': assert b'London auto' in store.resolve(slug)


@pytest.mark.parametrize('bad',['json','schema','state-mode','state-symlink','state-fifo','state-directory',
    'lock-mode','lock-symlink','lock-fifo'])
def test_auxiliary_corruption_unavailable_but_fixed_and_healthz_work(web,logged_in,monkeypatch,bad):
    from test_fixed_views import create
    entry = create(web,logged_in); store = web.fixed_subscriptions; worker = NodeHealth(store)
    worker.settings(entry['id'],'manual'); path = worker.path
    if bad == 'json': path.write_text('PRIVATE broken json')
    if bad == 'schema': write_json(path,dict(version=99,subscriptions={}))
    if bad.endswith('mode'):
        target = worker.lock if bad == 'lock-mode' else path
        target.chmod(0o644)
    if bad.endswith('symlink'):
        target = worker.lock if bad == 'lock-symlink' else path
        target.unlink(); target.symlink_to(store.path)
    if bad.endswith('fifo'):
        target = worker.lock if bad == 'lock-fifo' else path
        target.unlink(); os.mkfifo(target,0o600)
    if bad == 'state-directory': path.unlink(); path.mkdir(mode=0o700)
    public = '/s/'+store.slug(entry)
    assert web.app.test_client().get(public).status_code == 200
    assert web.app.test_client().get('/healthz').status_code == 200
    started = time.monotonic(); page = logged_in.get(f'/fixed-subscriptions/{entry["id"]}/edit')
    assert time.monotonic()-started < 2 and page.status_code == 200
    assert b'Health state unavailable.' in page.data and b'PRIVATE broken json' not in page.data
    monkeypatch.setattr(node_probe,'probe',lambda *a:pytest.fail('corrupt state caused network'))
    assert post(logged_in,f'/fixed-subscriptions/{entry["id"]}/health/check').status_code == 303
    assert web.app.test_client().get(public).status_code == 200


@pytest.mark.parametrize('mode',['before','after'])
def test_health_write_failure_preserves_auxiliary_and_fixed_state(web,logged_in,monkeypatch,mode):
    from test_fixed_views import create
    entry = create(web,logged_in); store = web.fixed_subscriptions; worker = NodeHealth(store)
    worker.settings(entry['id'],'manual'); before = worker.path.read_bytes(); fixed_before = store.path.read_bytes()
    monkeypatch.setattr(node_probe,'probe',lambda *a:dict(latency_ms=1,error=None))
    original = health.write_json
    def fail(path,value):
        if mode == 'after': original(path,value)
        raise OSError('PRIVATE disk secret')
    with monkeypatch.context() as injection:
        injection.setattr(health,'write_json',fail)
        result = post(logged_in,f'/fixed-subscriptions/{entry["id"]}/health/check',follow_redirects=True)
    assert b'Health results could not be saved.' in result.data and b'PRIVATE disk secret' not in result.data
    assert worker.path.read_bytes() == before and store.path.read_bytes() == fixed_before
    assert web.app.test_client().get('/s/'+store.slug(entry)).status_code == 200


@pytest.mark.parametrize('corrupt',[False,True])
def test_delete_cleanup_is_auxiliary_and_never_rolls_back(store,base,observer,monkeypatch,corrupt):
    entry = checked(store,base,observer); worker = observer['health']
    if corrupt: worker.path.write_text('PRIVATE corruption')
    store.action(entry['id'],'delete')
    assert store.get(entry['id']) is None and store.resolve(store.slug(entry)) is None
    if corrupt: assert worker.path.read_text() == 'PRIVATE corruption'
    else: assert entry['id'] not in json.loads(worker.path.read_bytes())['subscriptions']


def test_health_read_prunes_stale_subscription_after_failed_cleanup(store,base,observer,monkeypatch):
    entry = checked(store,base,observer)
    with patch.object(NodeHealth,'remove',side_effect=RuntimeError('PRIVATE cleanup')):
        store.action(entry['id'],'delete')
    new = save(store,base); observer['health'].describe(new['id'])
    assert entry['id'] not in json.loads(observer['health'].path.read_bytes())['subscriptions']


def test_health_cleanup_does_not_wait_on_busy_auxiliary_lock(store,base,observer):
    entry = checked(store,base,observer)
    with file_lock(observer['health'].lock):
        store.action(entry['id'],'delete')
    assert store.get(entry['id']) is None


def test_health_mode_post_auth_csrf_only_and_ui_secrecy(web,logged_in,monkeypatch,caplog):
    from test_fixed_views import create
    entry = create(web,logged_in); store = web.fixed_subscriptions; key = entry['id']; worker = NodeHealth(store)
    root = f'/fixed-subscriptions/{key}/health/'
    fixed_before = store.path.read_bytes()
    for operation in ('settings','check'):
        assert logged_in.get(root+operation).status_code == 405
        assert web.app.test_client().post(root+operation).status_code in (302,303)
        assert logged_in.post(root+operation).status_code == 303
    assert not worker.path.exists()
    assert post(logged_in,root+'settings',{'mode':'automatic'}).status_code == 303 and not worker.path.exists()
    assert post(logged_in,root+'settings',{'mode':'manual'}).status_code == 303
    monkeypatch.setattr(node_probe,'probe',lambda *a:dict(error=None,latency_ms=37.6))
    assert post(logged_in,root+'check').status_code == 303
    page = logged_in.get(f'/fixed-subscriptions/{key}/edit')
    section = page.data.split(b'<section id="node-health"')[1].split(b'</section>')[0]
    assert b'HEALTHY' in section and b'38 ms' in section and b'Last Success' in section
    assert b'Endpoint reachability only.' in section and b'does not verify proxy authentication' in section
    assert store.path.read_bytes() == fixed_before
    for secret in (b'example.com',b'11111111-1111-4111-8111-111111111111',LINK.encode(),entry['token'].encode()):
        assert secret not in section and secret not in worker.path.read_bytes() and secret.decode() not in caplog.text
    for fp in json.loads(worker.path.read_bytes())['subscriptions'][key]['nodes']:
        assert fp.encode() not in section


def test_check_uses_current_yaml_not_form_or_provider(store,base,response,observer,monkeypatch):
    entry = external_save(store,base,sources=[remote()]); worker = observer['health']; worker.settings(entry['id'],'manual')
    monkeypatch.setattr(source_fetch,'fetch',lambda *a:pytest.fail('Check Now fetched provider'))
    monkeypatch.setattr(store,'save',lambda *a,**k:pytest.fail('Check Now generated revision'))
    worker.check(entry['id'])
    assert len(observer['calls']) == 1  # Identical config under two names is probed once.
    assert worker.describe(entry['id'])['total'] == 2 and store.get(entry['id'])['revision'] == entry['revision']


def test_health_state_survives_upgrade_and_uninstall_state_backup(deployment):
    from core.fixed_subscriptions import FixedSubscriptions
    from core import generator
    installed, src, service, events, env, run = deployment
    store = FixedSubscriptions(installed/'state'); config = dict(source(),yaml_source='custom')
    entry = store.save(None,'Health','health',config,parsed(config),src/'unused',BASE)
    worker = NodeHealth(store,probe=lambda *a:dict(error=None,latency_ms=5))
    worker.settings(entry['id'],'manual'); worker.check(entry['id']); before = worker.path.read_bytes()
    result = run(); assert result.returncode == 0, result.stdout+result.stderr
    assert worker.path.read_bytes() == before
    backup = next(installed.parent.glob('upgrade-backup-*'))
    assert (backup/'state/node_health.json').read_bytes() == before
    result = run('uninstall.sh',input_text='y\n\n'); assert result.returncode == 0, result.stderr
    backup = next(installed.parent.glob('uninstall-backup-*'))
    assert (backup/'state/node_health.json').read_bytes() == before


@pytest.mark.parametrize('field,value',[('status','PRIVATE'),('consecutive_failures',True),
    ('consecutive_failures',-1),('latency_ms',float('nan')),('latency_ms',-1),
    ('last_checked_at',float('inf')),('last_success_at',-1),('error','PRIVATE endpoint'),
    ('server','PRIVATE endpoint')])
def test_health_record_corruption_fails_closed_does_not_reset(store,base,observer,field,value):
    entry = checked(store,base,observer); worker = observer['health']
    data = json.loads(worker.path.read_bytes()); record = next(iter(data['subscriptions'][entry['id']]['nodes'].values()))
    record[field] = value; write_json(worker.path,data); old = worker.path.read_bytes()
    with pytest.raises(HealthError): worker.describe(entry['id'])
    assert worker.path.read_bytes() == old and store.resolve(store.slug(entry))


@pytest.mark.parametrize('invalid',[b'{"version":1,"version":1,"subscriptions":{}}',
    b'{"version":1,"subscriptions":{},"extra":NaN}'])
def test_ambiguous_json_fails_closed(store,base,observer,invalid):
    entry = checked(store,base,observer); worker = observer['health']
    worker.path.write_bytes(invalid)
    with pytest.raises(HealthError): worker.describe(entry['id'])
    assert worker.path.read_bytes() == invalid and store.resolve(store.slug(entry))


def test_unexpected_probe_failure_is_sanitized_and_does_not_commit(store,base,observer):
    entry = checked(store,base,observer); worker = observer['health']; before = worker.path.read_bytes()
    def fail(*args): raise RuntimeError('PRIVATE endpoint and UUID')
    worker.probe = fail
    with pytest.raises(HealthError,match='could not be completed') as error: worker.check(entry['id'])
    assert 'PRIVATE' not in str(error.value) and worker.path.read_bytes() == before
    assert store.resolve(store.slug(entry))


def test_private_state_reader_rejects_device_inode_without_reading(tmp_path,monkeypatch):
    import stat
    import core.state as state
    path = tmp_path/'private'; path.write_bytes(b'PRIVATE'); path.chmod(0o600)
    monkeypatch.setattr(state.os,'fstat',lambda fd:SimpleNamespace(st_mode=stat.S_IFCHR|0o600))
    with pytest.raises(StateError): read_private_bytes(path)


def test_private_state_reader_caps_size_without_mutation(tmp_path):
    path = tmp_path/'private'; path.write_bytes(b'PRIVATE'); path.chmod(0o600)
    with pytest.raises(StateError): read_private_bytes(path,max_bytes=3)
    assert path.read_bytes() == b'PRIVATE'
