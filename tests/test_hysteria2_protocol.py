"""Official URI/pinned Mihomo subset: offline parsing, strict imports and privacy."""
import base64
import copy
import io
import json
from pathlib import Path
import socket
import subprocess
from urllib.parse import quote

import pytest
from ruamel.yaml import YAML

from core import parser, source_parser, yaml_utils, node_health, mihomo_probe
from core.node_identity import fingerprint
from core.source_errors import SourceError
from conftest import LINK
from test_parser import vmess
from test_trojan_protocol import TROJAN, yaml_bytes
from test_ss_protocol import SS
from test_yaml_diff import SOURCE

PASSWORD = ' TEST_ONLY_HY2_密:@/%40 + '
OBFS = ' TEST_ONLY_OBFS_密+%40 '


def hy2_uri(password=PASSWORD, host='example.com', port=443, scheme='hysteria2', query=''):
    auth = '' if password is None else quote(password, safe=':')+'@'
    return scheme+'://'+auth+host+(':'+str(port) if port is not None else '')+query


HY2 = hy2_uri(query='?obfs=salamander&obfs-password='+quote(OBFS,safe=''))


@pytest.mark.parametrize('scheme', ['hysteria2', 'hy2'])
@pytest.mark.parametrize('host', ['example.com','192.0.2.1','[2001:db8::1]'])
@pytest.mark.parametrize('auth', [None,'','abc+123','user1:p@ss','%2F',' 密码 ',' ','\n\t',':/@?+#'])
def test_hosts_alias_auth_exact_once(scheme,host,auth):
    uri=hy2_uri(auth,host,None,scheme)
    node=parser.parse_hysteria2_link(uri,'Test')
    expected=dict(name='Test',type='hysteria2',server=host.strip('[]'),port=443,udp=True,**{'skip-cert-verify':False})
    if auth is not None:expected['password']=auth
    assert node==expected
    assert not yaml_utils.validate_new_nodes([node])
    assert YAML(typ='safe').load(yaml_bytes([node]))['proxies'][0]==expected
    assert parser.parse_batch_nodes(uri)['nodes'][0]==dict(expected,name='🌐 Node-01')


@pytest.mark.parametrize('auth,expected',[('abc+123','abc+123'),('abc%2B123','abc+123'),
    ('user1:p%40ss','user1:p@ss'),('%252F','%2F'),('%40%3A%2F%25','@:/%')])
def test_literal_plus_and_single_decode(auth,expected):
    assert parser.parse_hysteria2_link('hy2://'+auth+'@example.com','Test')['password']==expected


@pytest.mark.parametrize('port',[1,443,65535])
def test_single_ports(port):
    assert parser.parse_hysteria2_link(hy2_uri(port=port),'Test')['port']==port


@pytest.mark.parametrize('query,extra',[
    ('/',{}),('/?',{}),('?insecure=0',{'skip-cert-verify':False}),('?insecure=1',{'skip-cert-verify':True}),
    ('?sni=tls.example',{'sni':'tls.example'}),('?sni=192.0.2.1',{'sni':'192.0.2.1'}),
    ('?pinSHA256='+'aB'*32,{'fingerprint':'aB'*32}),
    ('?pinSHA256='+'AB:'*31+'AB',{'fingerprint':'AB:'*31+'AB'}),
    ('?obfs=salamander&obfs-password='+quote(OBFS,safe=''),{'obfs':'salamander','obfs-password':OBFS}),
    ('?obfs=gecko&obfs-password=abc+123',{'obfs':'gecko','obfs-password':'abc+123'}),
])
def test_query_mapping_preserves_fields(query,extra):
    node=parser.parse_hysteria2_link(hy2_uri(query=query),'Test')
    for key,value in extra.items():assert node[key]==value
    assert not set(node)&{'up','down','uuid','tls','servername','realm-opts','ech-opts'}


@pytest.mark.parametrize('ports,first,normalized', [('443,5000-6000',443,'443,5000-6000'),
    ('5000-6000',5000,'5000-6000'),('000443,000001-000002',443,'443,1-2'),('1-65535',1,'1-65535')])
@pytest.mark.parametrize('host',['example.com','[2001:db8::1]'])
def test_hopping(ports,first,normalized,host):
    node=parser.parse_hysteria2_link(hy2_uri(host=host,port=ports),'Test')
    assert node['port']==first and node['ports']==normalized
    imported=source_parser.parse(yaml_bytes([node]),'clash')['nodes'][0]
    assert imported['port']==first and imported['ports']==normalized


@pytest.mark.parametrize('ports',['','0','65536','-1','443.0','true','443,','443,,444','6000-5000',
    '443-','1-2-3','443/444','1:2','1;2','0-1','1-65536','1-65535,1','443,'*29+'443','1'*513])
def test_hopping_invalid(ports):
    with pytest.raises(ValueError):parser.parse_hysteria2_link(hy2_uri(port=ports),'Test')


@pytest.mark.parametrize('uri',[
    'hy2://','HY2://pass@example.com','hysteria://pass@example.com','hysteria2+realm://host',
    'hysteria2+realm+http://host','hy2://pass@','hy2://pass@bad host','hy2://pass@exa\nmple.com',
    'hy2://pass@exam\\ple.com','hy2://pass@999.999.999.999','hy2://pass@[v1.example]',
    'hy2://pass@2001:db8::1','hy2://pass@[2001:db8::1]junk','hy2://pass@[fe80::1%25eth0]',
    'hy2://a@b@example.com','hy2://p%XX@example.com','hy2://p%FF@example.com',
    hy2_uri()+'/path',hy2_uri()+'#%FF',hy2_uri(host='exa%40mple.com'),
])
def test_invalid_authority_scheme_encoding(uri):
    with pytest.raises(ValueError) as error:parser.parse_hysteria2_link(uri,'Test')
    assert str(error.value)==str(parser.Hysteria2ValidationError())
    assert 'TEST_ONLY' not in repr(error.value)
    assert parser.parse_batch_nodes('Name|'+uri)['errors']


@pytest.mark.parametrize('query',[
    '?unknown=VERY_PRIVATE_SECRET_123','?sni=a&sni=b','?insecure=1&insecure=0',
    '?sni=', '?sni', '?sni=bad%20host','?insecure=true','?insecure=false','?insecure=yes',
    '?insecure=2','?insecure=','?obfs=unknown&obfs-password=VERY_PRIVATE_SECRET_123',
    '?obfs=salamander','?obfs=gecko&obfs-password=', '?obfs-password=VERY_PRIVATE_SECRET_123',
    '?obfs=&obfs-password=x','?pinSHA256=chrome','?pinSHA256=abcd','?pinSHA256=',
    '?ech=VERY_PRIVATE_SECRET_123','?realm-opts=x','?up=100','?alpn=h3','?hop-interval=30',
    '?sni=a&', '?sni=a&obfs=salamander&obfs-password=x&insecure=0&pinSHA256='+('ab'*32)+'&sni=b',
    '?obfs=salamander&obfs-password='+('x'*4097), '?sni='+('x'*16385),
])
def test_query_fail_closed_private_errors(query):
    uri=hy2_uri('VERY_PRIVATE_SECRET_123',query=query)
    with pytest.raises(ValueError) as error:parser.parse_hysteria2_link(uri,'Test')
    assert 'VERY_PRIVATE_SECRET_123' not in repr(error.value)
    result=parser.parse_batch_nodes('Safe|'+uri)
    assert not result['nodes'] and result['errors']
    assert 'VERY_PRIVATE_SECRET_123' not in json.dumps(result)
    with pytest.raises(SourceError) as error:source_parser.parse(uri.encode(),'raw')
    assert 'VERY_PRIVATE_SECRET_123' not in repr(error.value)


@pytest.mark.parametrize('fragment,name,code', [('', 'Node-01','UNKNOWN'),('#Tokyo-HY2','Tokyo-HY2','JP'),
    ('#%E6%9D%B1%E4%BA%AC%20%E2%98%83','東京 ☃','JP'),('#%252F','%2F','UNKNOWN')])
def test_fragment(fragment,name,code):
    record=parser.parse_batch_nodes(HY2+fragment)['preview'][0]
    assert record['name']==name and record['country']==code and record['protocol']=='Hysteria2'


@pytest.mark.parametrize('name',[PASSWORD.strip(),OBFS.strip(),'HY2://TEST_ONLY_SECRET@host'])
def test_preview_both_passwords_masked(name):
    parsed=parser.parse_batch_nodes(name+'|'+HY2)
    assert not parsed['errors']
    shown=json.dumps(parsed['preview'],ensure_ascii=False)
    assert PASSWORD.strip() not in shown and OBFS.strip() not in shown and 'TEST_ONLY_SECRET' not in shown
    assert parser.mask_sensitive(HY2)=='hysteria2://***'
    assert parser.mask_sensitive(HY2.replace('hysteria2://','hy2://'))=='hy2://***'


def test_mixed_manual_overrides_and_duplicate_contract():
    batch='US|VM|'+vmess()+'\nSG|VL|'+LINK+'\nJP|TJ|'+TROJAN+'\nTW|SS|'+SS+'\n'+HY2+'#Opaque\n'+hy2_uri(scheme='hy2')+'#Alias'
    parsed=parser.parse_batch_nodes(batch)
    assert [n['type'] for n in parsed['nodes']]==['vmess','vless','trojan','ss','hysteria2','hysteria2']
    key=parsed['preview'][4]['key']
    edited=parser.parse_batch_nodes(batch,{key:dict(name='Edited Ω',country='TW')})
    assert edited['preview'][4]['name']=='Edited Ω' and edited['preview'][4]['source']=='Manual'
    assert parser.parse_batch_nodes('US|Same|'+HY2+'\nUS|Same|'+LINK)['errors']==['第 2 行错误：节点名称重复，请修改名称以防止冲突。']


@pytest.mark.parametrize('format',['raw','auto','base64','base64-url','auto-base64'])
def test_sources_mixed_order(format):
    raw=(vmess(ps='US-VM')+'\n'+LINK+'#London-VL\n'+TROJAN+'#Tokyo-TJ\n'+SS+'#Singapore-SS\n'+HY2+'#Taiwan-HY2\n'+hy2_uri(scheme='hy2')+'#Alias').encode()
    payload=raw
    if format in ('base64','base64-url','auto-base64'):
        payload=(base64.urlsafe_b64encode(raw) if format=='base64-url' else base64.b64encode(raw)).rstrip(b'=')
    parsed=source_parser.parse(payload,{'base64-url':'base64','auto-base64':'auto'}.get(format,format))
    assert [n['type'] for n in parsed['nodes']]==['vmess','vless','trojan','ss','hysteria2','hysteria2']
    assert parsed['nodes'][-2]['obfs-password']==OBFS


@pytest.mark.parametrize('extra', [{},{'password':''},{'password':' '},{'udp':False},
    {'alpn':['h3','custom'],'up':'100 Mbps','down':200},
    {'ports':'443,5000-6000','hop-interval':30},{'ports':'443,5000-6000','hop-interval':'15-30'},
    {'sni':'tls.example','fingerprint':'AB:'*31+'AB','skip-cert-verify':True}])
def test_clash_explicit_allowlist_preserves(extra):
    node=parser.parse_hysteria2_link(HY2,'Tokyo');node.update(extra)
    result=source_parser.parse(yaml_bytes([node,dict(type='hysteria',name='Unknown'),dict(type='hy2',name='Alias-type')]),'clash')
    assert result['nodes'][0]==dict(node,name='🇯🇵 Tokyo')
    assert result['warnings']==['2 unsupported proxies skipped']


@pytest.mark.parametrize('extra', [
    {'port':True},{'port':443.0},{'port':'443'},{'port':0},{'port':65536},
    {'password':None},{'password':False},{'password':123},{'server':'bad host'},
    {'sni':''},{'sni':[]},{'udp':'true'},{'skip-cert-verify':1},
    {'obfs':False},{'obfs':'unknown'},{'obfs-password':''},{'obfs-password':123},
    {'fingerprint':False},{'fingerprint':'chrome'},{'alpn':[]},{'alpn':['']},{'alpn':[True]},
    {'up':'100\u00a0Mbps'},{'up':False},{'up':0},{'down':1.5},{'down':'junk'},{'up':-1},{'up':2**65},
    {'hop-interval':30},{'ports':443},{'ports':''},{'ports':'6000-5000'},
    {'ports':'443-444','hop-interval':True},{'ports':'443-444','hop-interval':1.5},
    {'ports':'443-444','hop-interval':'30-15'},{'ports':'443-444','hop-interval':'3'},
    {'realm-opts':{}},{'ech-opts':{}},{'obfs-min-packet-size':64},{'x-opaque':{}},
    {'bbr-profile':'conservative'},{'initial-stream-receive-window':1},
])
def test_clash_invalid_types_fixed_errors(extra):
    node=parser.parse_hysteria2_link(HY2,'Test');node.update(extra)
    with pytest.raises(SourceError) as error:source_parser.parse(yaml_bytes([node]),'clash')
    assert PASSWORD.strip() not in repr(error.value) and OBFS.strip() not in repr(error.value)
    assert yaml_utils.validate_new_nodes([node])


def test_clash_ports_only_engine_accepts_first_port_for_observations():
    node=dict(name='Test',type='hysteria2',server='example.com',ports='5000-5010,443')
    assert source_parser.parse(yaml_bytes([node]),'clash')['nodes'][0]['port']==5000
    with pytest.raises(SourceError):source_parser.parse(yaml_bytes([dict(node,port=0)]),'clash')


@pytest.mark.parametrize('payload',[
    b'proxies: [!!python/object/apply:os.system ["TEST_ONLY"]]',
    b'proxies: &a [{type: hysteria2, name: Test, server: example.com, port: 443, password: TEST_ONLY, alpn: *a}]',
    b'proxies: [{type: hysteria2, name: Test, server: example.com, port: 443, password: .nan}]',
    b'proxies: [{type: hysteria2, name: Test, server: example.com, port: 443, 1: bad}]',
    b'proxies: [{type: hysteria2, name: Test, server: example.com, port: 443, password: "\\uD800"}]',
])
def test_yaml_safe_import(payload):
    with pytest.raises(SourceError):source_parser.parse(payload,'clash')


def test_offline_no_network_process(monkeypatch):
    def forbidden(*a,**k):raise AssertionError('offline only')
    for owner,name in [(socket,'getaddrinfo'),(socket,'create_connection'),(subprocess,'run'),(subprocess,'Popen')]:monkeypatch.setattr(owner,name,forbidden)
    assert parser.parse_batch_nodes(HY2)['nodes']
    assert source_parser.parse(HY2.encode(),'auto')['nodes']
    assert source_parser.parse(yaml_bytes([parser.parse_hysteria2_link(HY2,'Test')]),'clash')['nodes']


@pytest.mark.parametrize('field,value',[('password','changed'),('server','other.example'),('port',444),
    ('sni','tls.example'),('obfs','gecko'),('obfs-password','changed'),('ports','443,444')])
def test_identity_rename_stable_connection_change_invalidates(field,value):
    node=parser.parse_hysteria2_link(HY2,'Test')
    assert fingerprint(node)==fingerprint(dict(node,name='Renamed'))
    assert fingerprint(node)!=fingerprint(dict(node,**{field:value}))


@pytest.mark.parametrize('name',[PASSWORD.strip(),OBFS.strip(),'hy2://SECRET@host','hysteria2://SECRET@host'])
def test_health_probe_private_config_and_notifications(tmp_path,name):
    from core import notification_events as events
    node=parser.parse_hysteria2_link(HY2,name)
    nodes=node_health.extract(yaml_bytes([node]),include_config=True)
    assert len(nodes)==1 and nodes[0]['protocol']=='hysteria2' and nodes[0]['name']=='Node 1'
    work=tmp_path/'probe';work.mkdir(mode=0o700)
    path=mihomo_probe.write_config(work,nodes,34567,'TEST_ONLY_controller')
    config=YAML(typ='safe').load(path.read_bytes())
    assert config['proxies']==[dict(node,name='probe-0001')]
    assert config['external-controller']=='127.0.0.1:34567' and config['log-level']=='silent'
    assert path.stat().st_mode & 0o777==0o600
    public=json.dumps(node_health.extract(yaml_bytes([node])),ensure_ascii=False)
    assert PASSWORD.strip() not in public and OBFS.strip() not in public and 'SECRET' not in public
    before={'nodes':{nodes[0]['fingerprint']:node_health.unknown()},'scheduler_failures':0}
    after=copy.deepcopy(before);after['nodes'][nodes[0]['fingerprint']]['status']='unhealthy'
    collected=[]
    with events.collect(collected):events.health('proxy_health',before,after,'Home',1800000000,'auto')
    assert len(collected)==1 and PASSWORD.strip() not in events.message(collected) and OBFS.strip() not in events.message(collected)


def test_all_four_prechange_goldens():
    golden=json.loads((Path(__file__).parent/'hysteria2fixtures/before.json').read_text())
    parsed=parser.parse_batch_nodes(golden['text'])
    assert parsed==golden['parsed']
    for mode,expected in golden['yaml'].items():
        data=yaml_utils.get_yaml_engine().load(SOURCE)
        assert yaml_utils.transform_yaml_config(data,parsed['nodes'],parsed['countries'],node_update_mode=mode)['success']
        out=io.StringIO();yaml_utils.get_yaml_engine().dump(data,out)
        assert out.getvalue().encode()==expected.encode()


def test_oversized_uri_and_lone_surrogates_are_fixed_errors():
    for uri in ['hy2://'+('a'*65537)+'@example.com','hy2://\ud800@example.com','hy2://pass@example.com#\ud800']:
        with pytest.raises(ValueError) as error:parser.parse_hysteria2_link(uri,'Test')
        assert str(error.value)==str(parser.Hysteria2ValidationError())


def test_import_depth_budget_and_numeric_warnings_are_private():
    import warnings
    node=parser.parse_hysteria2_link(HY2,'Test');nested='TEST_ONLY'
    for _ in range(34):nested=[nested]
    node['alpn']=nested
    with pytest.raises(SourceError):source_parser.parse(yaml_bytes([node]),'clash')
    with pytest.raises(SourceError):source_parser._plain(['TEST_ONLY']*100001)
    with pytest.raises(SourceError):source_parser.parse(b'x'*(source_parser.MAX_PAYLOAD+1),'raw')
    payload=b'%YAML 1.1\n---\nproxies: [{type: hysteria2, name: Test, server: example.com, port: 443, password: 1e9}]'
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter('always');filters=list(warnings.filters)
        with pytest.raises(SourceError):source_parser.parse(payload,'clash')
        assert not captured and warnings.filters==filters
