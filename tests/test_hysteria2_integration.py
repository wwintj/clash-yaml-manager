"""Hysteria2 through shared Generate/Diff/Fixed/refresh/GeoIP/Health paths."""
import io
import json
from pathlib import Path
import socket
from urllib.parse import quote

import pytest
from ruamel.yaml import YAML

from core import auto_refresh, generator, parser, source_parser, node_health
from conftest import LINK, post
from test_trojan_protocol import TROJAN, yaml_bytes
from test_hysteria2_protocol import PASSWORD, OBFS, HY2, hy2_uri
from test_ss_protocol import SS as OLD_SS
from test_parser import vmess
from test_yaml_diff import SOURCE, fields, body, apply_diff, ROUTE
from test_fixed_subscriptions import base, store, source, save
from test_external_sources import external_save, uploaded, remote, response
from test_auto_refresh import clock
from test_geoip import readers, database
from test_node_health import observer as endpoint_observer
from test_proxy_health import observer as proxy_observer


@pytest.mark.parametrize('yaml_source',['default','custom'])
@pytest.mark.parametrize('mode',['replace','merge'])
@pytest.mark.parametrize('policy,country', [('preserve','off'),('select','manual'),
    ('url-test','literal-ip'),('fallback','manual'),('load-balance','literal-ip')])
def test_exact_diff_generate_download_mixed_aux_policy(web,logged_in,readers,yaml_source,mode,policy,country):
    web.geoip_store.upload('country.mmdb',io.BytesIO(b'SYNTHETIC:SG'))
    unknown=hy2_uri(host='8.8.8.8')
    batch='US|VM|'+vmess()+'\nOpaque|'+unknown+'\nSG|VL|'+LINK+'\n'+TROJAN+'#Tokyo-TJ\n'+OLD_SS+'#Singapore-SS'
    parsed=generator.parse_form_nodes({'batch_nodes':batch})
    key=parsed['preview'][1]['key']
    edits={key:{'name':'Edited Ω','country':'TW'}} if country=='manual' else {}
    values=fields(yaml_source,policy,edits,'literal-ip' if country=='literal-ip' else 'off',batch)
    values['node_update_mode']=mode
    values['aux_nodes']=json.dumps([dict(country='UNKNOWN',name='Aux-HY2',link=hy2_uri(query='?obfs=salamander&obfs-password='+quote(OBFS,safe='')))])
    values['special_groups']=web.DEFAULT_SPECIAL_GROUPS[:2]
    preview=post(logged_in,ROUTE,body(values))
    assert preview.status_code==200,preview.json
    original=SOURCE if yaml_source=='custom' else Path(web.DEFAULT_YAML_PATH).read_text()
    expected=apply_diff(original,preview.json['diff']).encode()
    actual=post(logged_in,'/process',body(values));assert actual.status_code==302
    with logged_in.session_transaction() as session: context=session['page_context']
    assert not context['error_messages']
    generated=Path(web.DIR_OUTPUTS,context['output_filename']).read_bytes()
    assert generated==expected and logged_in.get(context['download_url']).data==expected
    result=YAML(typ='safe').load(generated)
    if yaml_source=='default':assert len(result['rules'])==10410
    new=result['proxies'][-6:]
    assert [node['type'] for node in new]==['vmess','hysteria2','vless','trojan','ss','hysteria2']
    assert all(node['password']==PASSWORD for node in new if node['type']=='hysteria2')
    assert new[-1]['obfs-password']==OBFS
    if yaml_source=='custom':assert len(result['proxies'])==(7 if mode=='merge' else 6)
    country_group=next(group for group in result['proxy-groups'] if group['name']=='🌐 其他节点')
    assert new[-1]['name'] in country_group['proxies']
    if country=='manual':assert new[1]['name']=='🇹🇼 Edited Ω'
    elif country=='literal-ip':assert new[1]['name']=='🇸🇬 Opaque'
    else:assert new[1]['name']=='🌐 Opaque'
    if policy!='preserve':
        for group in result['proxy-groups']:
            if group['name'] in web.DEFAULT_SPECIAL_GROUPS[:2]:
                assert group['type']==policy
                assert new[1]['name'] in group['proxies']


def test_parse_http_and_warning_logs_do_not_expose_password(web,logged_in,caplog):
    values=dict(batch_nodes=PASSWORD.strip()+' '+OBFS.strip()+'|'+HY2+'\nUS|Bad|'+HY2+'&unknown=TEST_ONLY_invalid',aux_nodes='[]')
    response=post(logged_in,'/parse-nodes',values)
    assert response.status_code==200
    assert PASSWORD.strip() not in json.dumps(response.json, ensure_ascii=False) and PASSWORD.strip() not in caplog.text
    assert '[password hidden]' in response.text
    assert 'Invalid Hysteria2' in response.json['errors'][0]
    assert OBFS.strip() not in response.text and OBFS.strip() not in caplog.text


def test_merge_hysteria2_collision_fixed_message(web,logged_in):
    values=fields(batch='UNKNOWN|old|'+HY2);values['node_update_mode']='merge'
    # UNKNOWN adds a flag, so use the exact display name produced by the parser.
    source=SOURCE.replace('name: old,','name: "🌐 old",').replace('proxies: [old, DIRECT]','proxies: ["🌐 old", DIRECT]')
    response=post(logged_in,ROUTE,body(values,source))
    assert response.status_code==400 and response.json['error']=='Node name already exists in source YAML.'
    assert not list(Path(web.DIR_OUTPUTS).iterdir())


def test_fixed_manual_batch_aux_edit_stable_url_schema(store,base):
    config=source();config['batch_nodes']='US|HY2|'+HY2
    config['aux_nodes']=[dict(country='JP',name='Aux',link=hy2_uri(scheme='hy2'))]
    entry=save(store,base,config=config);slug=store.slug(entry)
    result=YAML(typ='safe').load(store.resolve(slug))
    assert [node['type'] for node in result['proxies']]==['hysteria2','hysteria2']
    assert [node['password'] for node in result['proxies']]==[PASSWORD,PASSWORD]
    key=generator.parse_form_nodes({'batch_nodes':config['batch_nodes']})['preview'][0]['key']
    config['node_overrides']={key:{'country':'TW','name':'Edited'}}
    new=save(store,base,entry['id'],config=config)
    assert store.slug(new)==slug and new['token']==entry['token'] and new['revision']!=entry['revision']
    assert '🇹🇼 Edited'.encode() in store.resolve(slug)
    assert json.loads(store.path.read_text())['version']==6


@pytest.mark.parametrize('format',['raw','base64','clash','auto'])
def test_fixed_uploaded_external_formats_order_schema(store,base,format):
    import base64
    payload=(HY2+'#Tokyo-Remote').encode()
    if format=='base64':payload=base64.b64encode(payload)
    elif format=='clash':payload=yaml_bytes([parser.parse_hysteria2_link(HY2,'Tokyo-Remote')])
    entry=external_save(store,base,sources=[uploaded(format=format)],uploads={0:payload})
    slug=store.slug(entry);result=YAML(typ='safe').load(store.resolve(slug))
    assert [node['type'] for node in result['proxies']]==['vless','hysteria2']
    assert result['proxies'][1]['password']==PASSWORD
    assert entry['sources'][1]['node_count']==1 and store._payload(entry,entry['sources'][1]['id'])==payload
    assert json.loads(store.path.read_text())['version']==6


def test_auto_refresh_vmess_vless_to_mixed_last_good_transaction(store,base,response,clock):
    response['payload']=(vmess(ps='US-VM')+'\n'+LINK+'#London-VL').encode()
    entry=external_save(store,base,sources=[remote(refresh_interval_seconds=900)],clock=clock)
    slug=store.slug(entry)
    response['payload'] += ('\n'+TROJAN+'#Tokyo-TJ\n'+HY2+'#Singapore-SS').encode()
    clock.now=entry['sources'][1]['next_refresh_at'];assert auto_refresh.run_once(store,base,clock)==0
    good=store.get(entry['id']);item=good['sources'][1]
    assert good['revision']!=entry['revision'] and store.slug(good)==slug
    assert item['refresh_history'][-1]['node_count']==4 and item['next_refresh_at']==clock.now+900
    content=store.resolve(slug);cache=store._payload(good,item['id'])
    assert [node['type'] for node in YAML(typ='safe').load(content)['proxies']]==['vless','vmess','vless','trojan','hysteria2']
    response['payload']=(HY2+'&ech=TEST_ONLY_invalid').encode()
    clock.now=item['next_refresh_at'];assert auto_refresh.run_once(store,base,clock)==0
    bad=store.get(entry['id']);failed=bad['sources'][1]
    assert failed['using_cache'] and failed['consecutive_failures']==1 and failed['next_refresh_at']==clock.now+300
    assert store.slug(bad)==slug and store.resolve(slug)==content and store._payload(bad,item['id'])==cache
    response['payload']=(HY2+'#Singapore-Recovered').encode()
    clock.now=failed['next_refresh_at'];assert auto_refresh.run_once(store,base,clock)==0
    recovered=store.get(entry['id'])
    assert store.slug(recovered)==slug and not recovered['sources'][1]['using_cache']
    assert recovered['sources'][1]['next_refresh_at']==clock.now+900
    assert recovered['sources'][1]['consecutive_failures']==0
    assert store._payload(recovered,item['id'])==response['payload']


@pytest.mark.parametrize('manual,name,server,code,origin', [
    ('TW','Tokyo','8.8.8.8','TW','Manual'),('', 'Tokyo','8.8.8.8','JP','Name Detection'),
    ('','Opaque','8.8.8.8','SG','GeoIP'),('','Opaque','2606:4700:4700::1111','SG','GeoIP'),
    ('','Opaque','example.com','UNKNOWN','Unknown'),('','Opaque','192.0.2.1','UNKNOWN','Unknown'),
])
def test_geoip_priority_public_literals_only(database,readers,monkeypatch,manual,name,server,code,origin):
    def forbidden(*a,**k):raise AssertionError('no DNS')
    monkeypatch.setattr(socket,'getaddrinfo',forbidden)
    host='['+server+']' if ':' in server else server
    uri=hy2_uri(host=host)
    text=(manual+'|' if manual else '')+name+'|'+uri
    with database.lookup('literal-ip') as lookup:
        parsed=parser.parse_batch_nodes(text,country_lookup=lookup)
        imported=source_parser.parse((uri+'#'+name).encode(),'raw',lookup)
    assert parsed['preview'][0]['country']==code and parsed['preview'][0]['source']==origin
    assert imported['nodes'][0]['password']==PASSWORD
    if origin in ('Manual','Name Detection','Unknown'):assert not readers['calls'] or manual


def test_controlled_endpoint_health_password_safe_no_business_changes(store,base,endpoint_observer):
    entry=save(store,base,config=dict(source(),batch_nodes=PASSWORD.strip()+' '+OBFS.strip()+'|'+HY2))
    before=store.path.read_bytes();content=store._content(entry,'current.yaml')
    worker=endpoint_observer['health'];worker.settings(entry['id'],'manual');worker.check(entry['id'])
    assert endpoint_observer['calls']==[('example.com',443)]
    shown=worker.describe(entry['id'])
    assert shown['counts']['healthy']==1 and PASSWORD.strip() not in json.dumps(shown,ensure_ascii=False)
    assert PASSWORD.strip() not in worker.path.read_text()
    assert store.path.read_bytes()==before and store._content(entry,'current.yaml')==content


def test_controlled_full_proxy_uses_existing_runner_status_schema(store,base,proxy_observer):
    entry=save(store,base,config=dict(source(),batch_nodes=PASSWORD.strip()+' '+OBFS.strip()+'|'+HY2))
    worker=proxy_observer['worker'];worker.settings(entry['id'],'manual',True)
    before=store.path.read_bytes();content=store._content(entry,'current.yaml')
    worker.check(entry['id']);shown=worker.describe(entry['id'])
    assert proxy_observer['calls'][-1][0]==1 and shown['counts']['healthy']==1
    assert PASSWORD.strip() not in json.dumps(shown,ensure_ascii=False) and PASSWORD.strip() not in worker.path.read_text()
    proxy_observer.update(kind='failure',error='proxy_failed')
    for _ in range(3):proxy_observer['now']+=1;worker.check(entry['id'])
    assert worker.describe(entry['id'])['counts']['unhealthy']==1
    assert store.path.read_bytes()==before and store._content(entry,'current.yaml')==content


@pytest.mark.parametrize('route', ['/parse-nodes', ROUTE, '/process'])
def test_hysteria2_auth_csrf_rejected_without_private_output(web, logged_in, caplog, route):
    values=fields('default', batch=PASSWORD.strip()+' '+OBFS.strip()+'|'+HY2)
    anonymous=web.app.test_client()
    rejected=post(anonymous, route, values)
    assert rejected.status_code == (401 if route == ROUTE else 302)
    assert PASSWORD.strip() not in rejected.text
    for token in [None, 'invalid']:
        data=dict(values)
        if token is not None:data['csrf_token']=token
        rejected=logged_in.post(route, data=data)
        assert rejected.status_code == (303 if route == '/process' else 400)
        assert PASSWORD.strip() not in rejected.text
    assert not list(Path(web.DIR_OUTPUTS).iterdir())
    assert PASSWORD.strip() not in caplog.text


def test_hysteria2_merge_preserves_arbitrary_source_proxy_objects_and_topology():
    from test_merge_mode import BASE
    from core import yaml_utils
    data=yaml_utils.load_yaml_text(BASE);original=yaml_utils.load_yaml_text(BASE)
    sequence=data['proxies'];objects=list(sequence)
    parsed=parser.parse_batch_nodes('US|New-HY2|'+HY2)
    result=yaml_utils.transform_yaml_config(data, parsed['nodes'], parsed['countries'], ['media'], node_update_mode='merge')
    assert result['success'],result['errors']
    assert data['proxies'] is sequence and all(data['proxies'][i] is obj for i,obj in enumerate(objects))
    assert data['proxies'][-1]['password']==PASSWORD
    restored=yaml_utils.load_yaml_text(yaml_utils.serialize_yaml(data))
    assert restored['proxies'][:6]==original['proxies']
    assert [p['type'] for p in restored['proxies'][:6]]==['trojan','ss','hysteria2','wireguard','vendor-proxy','vless']
    assert data['x-node-copy'] is objects[0] and objects[0].anchor.value=='old_a'
    for key in original:
        if key not in ('proxies','proxy-groups'):assert data[key]==original[key]
    assert not yaml_utils.validate_proxy_references(restored)


@pytest.mark.parametrize('format',['raw','base64','clash'])
@pytest.mark.parametrize('scheme',['hysteria2','hy2'])
def test_remote_auto_refresh_unchanged_cache_bad_update_and_recovery(store,base,response,clock,format,scheme,caplog):
    import base64
    from urllib.parse import quote
    uri=hy2_uri(scheme=scheme,query='?obfs=gecko&obfs-password='+quote(OBFS,safe=''))
    def encoded(name):
        raw=(uri+'#'+name).encode()
        if format=='base64':return base64.urlsafe_b64encode(raw).rstrip(b'=')
        if format=='clash':return yaml_bytes([parser.parse_hysteria2_link(uri,name)])
        return raw
    response['payload']=encoded('Tokyo-Remote')
    entry=external_save(store,base,sources=[remote(format=format,refresh_interval_seconds=900)],clock=clock)
    slug=store.slug(entry);revision=entry['revision'];content=store.resolve(slug)
    clock.now=entry['sources'][1]['next_refresh_at'];assert auto_refresh.run_once(store,base,clock)==0
    same=store.get(entry['id'])
    # Source refresh retains its existing transaction semantics: a fresh
    # revision holds updated source metadata even when YAML bytes are equal.
    assert same['revision']!=revision and store.resolve(slug)==content
    response['payload']=encoded('Singapore-Changed')
    clock.now=same['sources'][1]['next_refresh_at'];assert auto_refresh.run_once(store,base,clock)==0
    good=store.get(entry['id']);assert good['revision']!=revision and store.slug(good)==slug
    content=store.resolve(slug);cache=store._payload(good,good['sources'][1]['id'])
    invalid=(uri+'&ech=VERY_PRIVATE_SECRET_123').encode()
    if format=='base64':invalid=base64.urlsafe_b64encode(invalid).rstrip(b'=')
    elif format=='clash':invalid=yaml_bytes([dict(parser.parse_hysteria2_link(uri,'Test'), **{'ech-opts':{'config':'VERY_PRIVATE_SECRET_123'}})])
    response['payload']=invalid
    clock.now=good['sources'][1]['next_refresh_at'];assert auto_refresh.run_once(store,base,clock)==0
    bad=store.get(entry['id']);item=bad['sources'][1]
    assert item['using_cache'] and item['last_error']=='invalid'
    assert store.resolve(slug)==content
    assert store._payload(bad,item['id'])==cache
    displayed=json.dumps(item['refresh_history'])+str(item['warnings'])+str(item['last_error'])+caplog.text
    assert PASSWORD.strip() not in displayed and OBFS.strip() not in displayed and 'VERY_PRIVATE_SECRET_123' not in displayed
    response['payload']=encoded('London-Recovered')
    clock.now=item['next_refresh_at'];assert auto_refresh.run_once(store,base,clock)==0
    recovered=store.get(entry['id']);assert not recovered['sources'][1]['using_cache'] and store.slug(recovered)==slug


@pytest.mark.parametrize('kind',['select','url-test','fallback','load-balance'])
@pytest.mark.parametrize('status,age,minimum,excluded',[
    ('unhealthy',0,1,True),('unhealthy',172801,1,False),('suspect',0,1,False),('unhealthy',0,3,False)])
def test_hysteria2_health_policy_conservative_candidates(kind,status,age,minimum,excluded):
    from core import health_policy, policy_engine
    from core.node_identity import fingerprint
    from test_health_policy import NOW, observation, settings
    from test_policy_engine import config
    nodes=[parser.parse_hysteria2_link(HY2,'A'), parser.parse_hysteria2_link(hy2_uri(password='TEST_ONLY_B'),'B')]
    countries=[dict(node_name=n['name'],group='country') for n in nodes]
    data={'proxies':nodes,'proxy-groups':[dict(name='country',type=kind,proxies=['A','B']),dict(name='media',type=kind,proxies=['A','B'])]}
    policy=policy_engine.normalize(config(kind,kind))
    results=health_policy.apply(data,nodes,countries,['media'],policy,settings(min_candidates=minimum),
        dict(available=True,records={fingerprint(nodes[0]):observation(status=status,age=age)}),NOW)
    should_exclude=excluded and kind!='select'
    assert data['proxy-groups'][0]['proxies']==(['B'] if should_exclude else ['A','B'])
    assert data['proxy-groups'][1]['proxies']==(['B'] if should_exclude else ['A','B'])
    assert data['proxies']==nodes
    assert results['candidates_excluded']==(2 if should_exclude else 0)


def test_hysteria2_health_policy_unchanged_yaml_keeps_revision(store,base,proxy_observer):
    from test_health_policy import settings
    from test_policy_engine import config
    values=dict(source(),batch_nodes='US|A|'+HY2+'\nUS|B|'+hy2_uri(password='TEST_ONLY_B'),
        policy_config=config('fallback','select'),health_policy=settings(min_candidates=1))
    entry=save(store,base,config=values)
    worker=proxy_observer['worker'];worker.settings(entry['id'],'manual',True);worker.check(entry['id'])
    entry=store.get(entry['id']);before=store.resolve(store.slug(entry))
    assert store.reconcile_health_policy(entry['id'],clock=lambda:1800000000)=='unchanged'
    after=store.get(entry['id'])
    assert after['revision']==entry['revision'] and store.resolve(store.slug(after))==before


def test_manual_refresh_and_link_regeneration_reuse_hysteria2_content(store,base):
    entry=save(store,base,config=dict(source(),batch_nodes='US|Test|'+HY2))
    slug=store.slug(entry);content=store.resolve(slug)
    refreshed=store.source_action(entry['id'],'refresh-all',base)
    assert store.resolve(slug)==content and store.slug(refreshed)==slug
    assert refreshed['revision']!=entry['revision']
    regenerated=store.action(entry['id'],'regenerate')
    assert store.slug(regenerated)!=slug and store.resolve(store.slug(regenerated))==content


def test_new_hysteria2_validation_display_is_english():
    from core.ui import display_message
    assert display_message('第 1 个节点 Hysteria2 配置无效。')=='Item 1 has invalid Hysteria2 configuration.'
