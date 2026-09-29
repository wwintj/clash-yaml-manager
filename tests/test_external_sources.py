import copy
import io
import json
import multiprocessing
import threading
from unittest.mock import patch

import pytest
from ruamel.yaml import YAML

from core import fixed_subscriptions as fixed, source_fetch
from core.source_errors import SourceError
from core.state import StateError, write_json
from conftest import LINK, post
from test_fixed_subscriptions import BASE, base, parsed, save, source, store


def remote(name='Airport', **changes):
    return dict(dict(type='remote_url', name=name, enabled=True, format='auto',
                     url='https://source.example/sub?token=PRIVATE'), **changes)


def uploaded(name='Office', **changes):
    return dict(dict(type='uploaded', name=name, enabled=True, format='auto'), **changes)


def payload(*names):
    return '\n'.join(LINK + '#' + name for name in names).encode()


def external_save(store, base, entry=None, config=None, sources=None, uploads=None, **kwargs):
    config = config if config is not None else source()
    return store.save(entry['id'] if entry else None, 'Home', 'home', config, parsed(config),
                      base, sources=sources, uploads=uploads, **kwargs)


@pytest.fixture
def response(monkeypatch):
    state = {'payload':payload('Tokyo-remote'), 'calls':[]}
    def fetch(url):
        state['calls'].append(url)
        if 'error' in state: raise SourceError(state['error'])
        return state['payload']
    monkeypatch.setattr(source_fetch, 'fetch', fetch)
    return state


def test_seven_node_order_country_groups_and_self_contained_revision(store, base, response):
    response['payload'] = payload('Tokyo-A','Singapore-B','Mystery-C')
    config = source(); config['batch_nodes'] += '\nJP|Tokyo-manual|' + LINK
    entry = external_save(store, base, config=config, sources=[remote(), uploaded()],
                          uploads={1:payload('Germany-upload','London-upload')})
    result = YAML(typ='safe').load(store.resolve(store.slug(entry)))
    assert [node['name'] for node in result['proxies']] == [
        '🇺🇸 First','🇯🇵 Tokyo-manual','🇯🇵 Tokyo-A','🇸🇬 Singapore-B','🌐 Mystery-C','🇩🇪 Germany-upload','🇬🇧 London-upload']
    assert entry['node_count'] == 7 and [s['node_count'] for s in entry['sources']] == [2,3,2]
    assert any(g['name'] == '🌐 其他节点' and g['proxies'] == ['🌐 Mystery-C'] for g in result['proxy-groups'])
    assert store._content(entry,'base.yaml') == BASE
    assert store._payload(entry, entry['sources'][1]['id']) == response['payload']
    assert store._payload(entry, entry['sources'][2]['id']) == payload('Germany-upload','London-upload')
    assert json.loads(store.path.read_bytes())['version'] == 2
    for path in store.state.rglob('*'):
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)


@pytest.mark.parametrize('failure', ['http_500','timeout','invalid_payload','unicode_payload'])
def test_last_good_with_new_manual_and_recovery_same_url(store, base, response, failure):
    entry = external_save(store, base, sources=[remote()]); slug = store.slug(entry)
    old_payload = store._payload(entry, entry['sources'][1]['id'])
    if failure == 'invalid_payload': response['payload'] = b'PRIVATE invalid'
    elif failure == 'unicode_payload': response['payload'] = '无效内容'.encode()
    else: response['error'] = failure
    new = external_save(store, base, entry, source('Changed Manual'), sources=entry['sources'][1:])
    assert store.slug(new) == slug and new['revision'] != entry['revision']
    assert b'Changed Manual' in store.resolve(slug) and b'Tokyo-remote' in store.resolve(slug)
    assert new['sources'][1]['using_cache'] and new['sources'][1]['last_error']
    assert store._payload(new, entry['sources'][1]['id']) == old_payload
    assert not (store.directory / entry['id'] / entry['revision']).exists()
    response.pop('error',None); response['payload'] = payload('London-recovered')
    recovered = store.source_action(new['id'],'refresh-all',base)
    assert store.slug(recovered) == slug and b'London-recovered' in store.resolve(slug)
    assert not recovered['sources'][1]['using_cache'] and recovered['sources'][1]['last_error'] is None


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('bad', ['fetch','parse','upload'])
def test_first_failure_never_commits_partial_source(store, base, response, existing, bad):
    entry = save(store,base) if existing else None
    old = store.path.read_bytes() if existing else None
    sources, uploads = [remote()], {}
    if bad == 'fetch': response['error'] = 'connection'
    if bad == 'parse': response['payload'] = b'invalid PRIVATE'
    if bad == 'upload': sources, uploads = [uploaded()], {0:b'invalid PRIVATE'}
    with pytest.raises(SourceError): external_save(store,base,entry,sources=sources,uploads=uploads)
    assert (store.path.read_bytes() if store.path.exists() else None) == old
    assert not list(store.state.glob('.fixed-candidate-*'))
    if existing: assert store.get(entry['id'])['sources'] == entry['sources']
    else: assert list(store.directory.iterdir()) == []


@pytest.mark.parametrize('change', [dict(url='https://new.example/?token=OTHER'), dict(format='clash')])
def test_changed_url_or_format_failure_preserves_config_and_cache(store, base, response, change):
    entry = external_save(store,base,sources=[remote()]); old = store.path.read_bytes()
    sources = copy.deepcopy(entry['sources'][1:]); sources[0].update(change)
    response['error'] = 'connection'
    with pytest.raises(SourceError): external_save(store,base,entry,sources=sources)
    assert store.path.read_bytes() == old
    assert store._payload(entry,sources[0]['id']) == payload('Tokyo-remote')


def test_bad_upload_replacement_preserves_old_and_empty_upload_reuses(store, base):
    entry = external_save(store,base,sources=[uploaded()],uploads={0:payload('Germany-upload')})
    old = store._content(entry,'current.yaml'); previous = store.path.read_bytes()
    with pytest.raises(SourceError):
        external_save(store,base,entry,sources=entry['sources'][1:],uploads={0:b'not valid'})
    assert store.path.read_bytes() == previous and store._content(entry,'current.yaml') == old
    new = external_save(store,base,entry,sources=entry['sources'][1:])
    assert store._payload(new,entry['sources'][1]['id']) == payload('Germany-upload')


@pytest.mark.parametrize('mode', ['before','after'])
def test_metadata_failure_after_successful_fetch_keeps_selected_cache(store, base, response, monkeypatch, mode):
    entry = external_save(store,base,sources=[remote()]); old = store.path.read_bytes()
    response['payload'] = payload('Berlin-replacement')
    original = fixed.write_json
    def fail(path, value):
        if mode == 'after': original(path,value)
        raise OSError('PRIVATE disk details')
    with monkeypatch.context() as injection:
        injection.setattr(fixed,'write_json',fail)
        with pytest.raises(StateError): store.source_action(entry['id'],'refresh-all',base)
    assert store.path.read_bytes() == old
    assert store._payload(entry,entry['sources'][1]['id']) == payload('Tokyo-remote')
    assert b'Tokyo-remote' in store.resolve(store.slug(entry))


def test_refresh_one_all_enable_disable_and_delete(store, base, response):
    # Distinct source node names avoid an unrelated duplicate rejection.
    def fetch(url):
        response['calls'].append(url)
        return payload('Tokyo-A' if '/a' in url else 'Berlin-B')
    with patch.object(source_fetch,'fetch',fetch):
        entry = external_save(store,base,sources=[remote('A',url='https://source.example/a'),
            remote('B',url='https://source.example/b')])
        a,b = entry['sources'][1:]; slug=store.slug(entry)
        response['calls'].clear()
        entry=store.source_action(entry['id'],'refresh',base,a['id'])
        assert response['calls'] == [a['url']]
        response['calls'].clear()
        entry=store.source_action(entry['id'],'refresh-all',base)
        assert response['calls'] == [a['url'],b['url']]
        response['calls'].clear()
        entry=store.source_action(entry['id'],'disable',base,a['id'])
        assert response['calls'] == [] and entry['node_count'] == 2
        assert store._payload(entry,a['id']) == payload('Tokyo-A')
        entry=store.source_action(entry['id'],'refresh-all',base)
        assert response['calls'] == [b['url']]
        response['calls'].clear()
        entry=store.source_action(entry['id'],'enable',base,a['id'])
        assert response['calls'] == [a['url']] and entry['node_count'] == 3
        entry=store.source_action(entry['id'],'delete',base,b['id'])
        assert store.slug(entry) == slug and entry['node_count'] == 2 and len(entry['sources']) == 2


def test_external_only_empty_manual_and_delete_last_source_fails(store, base, response):
    entry=external_save(store,base,config=dict(source(),batch_nodes=''),sources=[remote()])
    assert entry['node_count'] == 1 and entry['sources'][0]['node_count'] == 0
    old=store.path.read_bytes()
    for action in ('disable','delete'):
        with pytest.raises(SourceError,match='No supported'): store.source_action(entry['id'],action,base,entry['sources'][1]['id'])
        assert store.path.read_bytes() == old


def test_duplicate_across_sources_blocks_generation(store, base, response):
    response['payload']=payload('First')
    # Match the explicit manual country flag in the remote remark.
    response['payload']=payload('🇺🇸 First')
    with pytest.raises(SourceError,match='Duplicate node name'): external_save(store,base,sources=[remote()])
    assert store.list() == []


@pytest.mark.parametrize('mutation', ['edit','disable','regenerate','delete'])
def test_network_outside_lock_public_reads_and_optimistic_conflict(store, base, response, monkeypatch, mutation):
    entry=external_save(store,base,sources=[remote()]); slug=store.slug(entry)
    old=store.resolve(slug); started=threading.Event(); resume=threading.Event(); errors=[]
    def slow(url):
        started.set(); assert resume.wait(5)
        return payload('Berlin-stale')
    def run():
        try: store.source_action(entry['id'],'refresh-all',base)
        except BaseException as error: errors.append(error)
    monkeypatch.setattr(source_fetch,'fetch',slow)
    worker=threading.Thread(target=run); worker.start(); assert started.wait(3)
    # Another request must read AND mutate before fetch resumes. A held flock
    # causes this thread to miss the timeout, so the test also checks responsiveness.
    completed=threading.Event()
    def other_request():
        try:
            assert store.resolve(slug) == old
            if mutation=='edit':
                config=source('Concurrent Edit')
                store.save(entry['id'],'Home','home',config,parsed(config),base,
                           sources=entry['sources'][1:],refresh=set())
            else: store.action(entry['id'],mutation)
        finally: completed.set()
    other=threading.Thread(target=other_request); other.start()
    try: assert completed.wait(2), 'registry lock was held during network fetch'
    finally: resume.set(); worker.join(5); other.join(5)
    assert len(errors)==1 and isinstance(errors[0],SourceError) and errors[0].code=='conflict'
    assert not list(store.state.glob('.fixed-candidate-*'))
    if mutation=='edit': assert b'Concurrent Edit' in store.resolve(slug)
    else: assert store.resolve(slug) is None


def test_public_reads_never_fetch_and_access_stats_do_not_conflict(store,base,response,monkeypatch):
    entry=external_save(store,base,sources=[remote()]); calls=len(response['calls'])
    assert store.resolve(store.slug(entry)); assert len(response['calls'])==calls
    def fetch(url):
        # Advances access metadata while snapshot is in flight.
        with patch.object(fixed.time,'time',return_value=entry['updated_at']+65):
            assert store.resolve(store.slug(entry))
        return payload('Berlin-new')
    monkeypatch.setattr(source_fetch,'fetch',fetch)
    new=store.source_action(entry['id'],'refresh-all',base)
    assert new['last_access_at']>=entry['updated_at']+65 and b'Berlin-new' in store.resolve(store.slug(new))


def test_v1_migration_preserves_url_bytes_manual_and_fails_closed(store,base,monkeypatch):
    config=source(); config['node_overrides']={}
    entry=save(store,base,config=config); old=store._content(entry,'current.yaml')
    data=json.loads(store.path.read_text()); data['version']=1
    data['subscriptions'][entry['id']].pop('sources'); write_json(store.path,data)
    before=store.path.read_bytes()
    migrated=store.get(entry['id'])
    assert migrated['sources'][0]['id']==entry['id'] and migrated['sources'][0]['type']=='manual'
    assert store.path.read_bytes()==before
    assert store.resolve(store.slug(entry))==old
    assert json.loads(store.path.read_text())['version']==1
    with monkeypatch.context() as injection:
        injection.setattr(fixed,'write_json',lambda *a: (_ for _ in ()).throw(OSError('fail migration')))
        with pytest.raises(StateError): save(store,base,entry['id'],source('New'))
    assert store.resolve(store.slug(entry))==old and json.loads(store.path.read_text())['version']==1
    changed=save(store,base,entry['id'],source('New'))
    assert store.slug(changed)==store.slug(entry) and changed['sources'][0]['id']==entry['id']
    assert b'New' in store.resolve(store.slug(entry)) and json.loads(store.path.read_text())['version']==2


@pytest.mark.parametrize('field,value',[('id','../bad'),('id','a'*32),('name',''),('name','x'*129),
    ('enabled','false'),('format','unknown'),('type','manual')])
def test_reject_invalid_source_config(store,base,response,field,value):
    values=remote(); values[field]=value
    with pytest.raises(SourceError): external_save(store,base,sources=[values])


def test_duplicate_source_names_and_new_internal_ids(store,base,response):
    with pytest.raises(SourceError): external_save(store,base,sources=[remote(),remote()])
    entry=external_save(store,base,sources=[remote()])
    import uuid
    for item in entry['sources']: assert uuid.UUID(item['id']).version==4


@pytest.mark.parametrize('target',['directory','file'])
def test_payload_symlink_fails_closed(store,base,response,tmp_path,target):
    entry=external_save(store,base,sources=[remote()])
    root=store.directory/entry['id']/entry['revision']/'sources'/entry['sources'][1]['id']
    path=root if target=='directory' else root/'payload.bin'
    path.rename(path.with_name(path.name+'-old')); path.symlink_to(base)
    with pytest.raises(StateError): store.source_action(entry['id'],'refresh-all',base)
    assert b'Tokyo-remote' in store.resolve(store.slug(entry))


def test_source_views_auth_csrf_status_secrecy_and_upload(web,logged_in,response,caplog):
    config=dict(name='External',yaml_source='custom',yaml_file=(io.BytesIO(BASE),'base.yaml'),
                batch_nodes='',sources=json.dumps([remote(),uploaded()]),
                source_file_1=(io.BytesIO(payload('Germany-upload')),'../../PRIVATE.yaml'))
    assert post(logged_in,'/fixed-subscriptions/new',config).status_code==303
    entry=web.fixed_subscriptions.list()[0]; key=entry['id']; identifier=entry['sources'][1]['id']
    page=logged_in.get(f'/fixed-subscriptions/{key}/edit')
    assert b'PRIVATE' in page.data and b'Current source file: saved' in page.data
    assert b'PRIVATE' not in logged_in.get('/fixed-subscriptions').data
    assert page.headers['Referrer-Policy']=='no-referrer' and page.headers['Cache-Control']=='no-store'
    for route in [f'/fixed-subscriptions/{key}/sources/refresh-all']+[
            f'/fixed-subscriptions/{key}/sources/{identifier}/{action}' for action in ('refresh','disable','enable','delete')]:
        before=web.fixed_subscriptions.path.read_bytes()
        assert logged_in.get(route).status_code==405
        assert web.app.test_client().post(route).status_code in (302,303)
        assert logged_in.post(route).status_code==303
        assert web.fixed_subscriptions.path.read_bytes()==before
    response['error']='http_500'
    assert post(logged_in,f'/fixed-subscriptions/{key}/sources/refresh-all').status_code==303
    page=logged_in.get(f'/fixed-subscriptions/{key}/edit')
    assert b'Cached' in page.data and b'Using last successful data.' in page.data
    assert 'PRIVATE' not in caplog.text
    assert b'../../PRIVATE.yaml' not in web.fixed_subscriptions.path.read_bytes()


def test_custom_base_external_reuse(store,base,response):
    config=dict(source(),yaml_source='custom')
    entry=external_save(store,base,config=config,sources=[remote()],custom=BASE)
    base.unlink()
    changed=store.source_action(entry['id'],'refresh-all',base)
    assert store._content(changed,'base.yaml')==BASE


def test_format_change_parse_failure_and_disabled_config_edit(store,base,response):
    entry=external_save(store,base,sources=[remote()]); old=store.path.read_bytes()
    requested=copy.deepcopy(entry['sources'][1:]); requested[0]['format']='clash'
    with pytest.raises(SourceError): external_save(store,base,entry,sources=requested)
    assert store.path.read_bytes()==old
    requested[0].update(format='auto',url='https://new.example/sub',enabled=False)
    calls=len(response['calls'])
    with pytest.raises(SourceError): external_save(store,base,entry,sources=requested)
    assert store.path.read_bytes()==old and len(response['calls'])==calls


def test_new_disabled_remote_never_fetches_then_enable_fetches(store,base,response):
    entry=external_save(store,base,sources=[remote(enabled=False)])
    assert response['calls']==[] and entry['sources'][1]['last_success_at'] is None
    entry=store.source_action(entry['id'],'enable',base,entry['sources'][1]['id'])
    assert len(response['calls'])==1 and entry['node_count']==2


def test_failed_generation_blocks_source_deletion(store,base,response,monkeypatch):
    entry=external_save(store,base,sources=[remote()]); before=store.path.read_bytes()
    monkeypatch.setattr(fixed.generator,'generate',lambda *a:dict(success=False))
    with pytest.raises(fixed.GenerationError): store.source_action(entry['id'],'delete',base,entry['sources'][1]['id'])
    assert store.path.read_bytes()==before and b'Tokyo-remote' in store._content(entry,'current.yaml')


@pytest.mark.parametrize('field,value',[('id','../outside'),('last_error','PRIVATE URL'),
    ('warnings',['PRIVATE URI']),('last_attempt_at',float('nan')),('node_count',True),
    ('enabled',1),('type','other'),('url','http://user:PRIVATE@example.com/')])
def test_corrupt_v2_source_schema_fails_closed(store,base,response,field,value):
    entry=external_save(store,base,sources=[remote()])
    data=json.loads(store.path.read_bytes()); data['subscriptions'][entry['id']]['sources'][1][field]=value
    write_json(store.path,data); before=store.path.read_bytes()
    with pytest.raises(StateError): store.get(entry['id'])
    assert store.path.read_bytes()==before


def test_two_refresh_candidates_never_collect_each_other(store,base,response,monkeypatch):
    entry=external_save(store,base,sources=[remote()]); both=threading.Barrier(2); outcomes=[]
    def fetch(url):
        both.wait(timeout=5)
        return payload('Tokyo-concurrent')
    monkeypatch.setattr(source_fetch,'fetch',fetch)
    def run():
        try: outcomes.append(store.source_action(entry['id'],'refresh-all',base))
        except SourceError as error: outcomes.append(error.code)
    threads=[threading.Thread(target=run) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(5); assert not thread.is_alive()
    assert len([r for r in outcomes if isinstance(r,dict)])==1 and 'conflict' in outcomes
    assert b'Tokyo-concurrent' in store.resolve(store.slug(entry))
    assert len(list((store.directory/entry['id']).iterdir()))==1


def test_v1_auxiliary_and_overrides_survive_migration(store,base):
    from core.parser import node_key
    config=source()
    config['aux_nodes']=[dict(country='JP',name='Tokyo aux',link=LINK)]
    config['node_overrides']={node_key(config['batch_nodes']):dict(name='Edited',country='GB')}
    entry=save(store,base,config=config)
    data=json.loads(store.path.read_bytes()); data['version']=1
    data['subscriptions'][entry['id']].pop('sources'); write_json(store.path,data)
    migrated=store.get(entry['id'])
    assert migrated['aux_nodes']==config['aux_nodes'] and migrated['node_overrides']==config['node_overrides']
    result=external_save(store,base,migrated,config,sources=[])
    assert result['aux_nodes']==config['aux_nodes'] and result['node_overrides']==config['node_overrides']
    assert b'Edited' in store._content(result,'current.yaml') and b'Tokyo aux' in store._content(result,'current.yaml')


def test_source_action_conflict_after_delete_shows_retry_notice(web,logged_in,response,monkeypatch):
    data=dict(name='Conflict',yaml_source='custom',yaml_file=(io.BytesIO(BASE),'base.yaml'),
              batch_nodes='',sources=json.dumps([remote()]))
    assert post(logged_in,'/fixed-subscriptions/new',data).status_code==303
    store=web.fixed_subscriptions; entry=store.list()[0]
    def fetch(url):
        store.action(entry['id'],'delete')
        return payload('Tokyo-stale')
    monkeypatch.setattr(source_fetch,'fetch',fetch)
    result=post(logged_in,f'/fixed-subscriptions/{entry["id"]}/sources/refresh-all',follow_redirects=True)
    assert result.status_code==200 and b'Subscription changed while refreshing. Please retry.' in result.data
    assert store.list()==[]


def test_separate_worker_refresh_cannot_overwrite_parent_edit(store,base,response,monkeypatch):
    entry=external_save(store,base,sources=[remote()])
    ctx=multiprocessing.get_context('fork'); started=ctx.Event(); resume=ctx.Event(); result=ctx.Queue()
    def slow(url):
        started.set()
        if not resume.wait(5): raise SourceError('timeout')
        return payload('Tokyo-stale-process')
    def refresh():
        try:
            fixed.FixedSubscriptions(store.state).source_action(entry['id'],'refresh-all',base)
            result.put('unexpected commit')
        except SourceError as error: result.put(error.code)
    monkeypatch.setattr(source_fetch,'fetch',slow)
    worker=ctx.Process(target=refresh); worker.start()
    try:
        assert started.wait(3)
        assert b'Tokyo-remote' in store.resolve(store.slug(entry))
        config=source('Parent edit')
        store.save(entry['id'],entry['name'],entry['prefix'],config,parsed(config),base,
                   sources=entry['sources'][1:],refresh=set())
    finally:
        resume.set(); worker.join(8)
    assert worker.exitcode==0 and result.get(timeout=2)=='conflict'
    assert b'Parent edit' in store.resolve(store.slug(entry))
