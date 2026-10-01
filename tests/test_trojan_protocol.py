"""Offline Trojan URI/import contract and pre-change VMess/VLESS byte goldens."""
import base64
import hashlib
import io
import json
from pathlib import Path
import socket
import subprocess
from urllib.parse import quote

import pytest
from ruamel.yaml import YAML

from core import parser, source_parser, yaml_utils, node_health, mihomo_probe
from core.source_errors import SourceError
from conftest import LINK
from test_parser import vmess
from test_yaml_diff import SOURCE

PASSWORD = ' TEST_ONLY_密:@% + '
TROJAN = 'trojan://' + quote(PASSWORD, safe='') + '@example.com:443'


def yaml_bytes(nodes):
    out = io.StringIO(); YAML().dump(dict(proxies=nodes), out)
    return out.getvalue().encode()


@pytest.mark.parametrize('password', ['pass', 'p@ss', 'p:ss', 'p%40ss', ' 密码 ', ' ', '\t\n', '+/#?'])
@pytest.mark.parametrize('host', ['example.com', '192.0.2.10', '[2001:db8::1]'])
def test_password_once_and_ipv6(password, host):
    node = parser.parse_trojan_link('trojan://' + quote(password, safe='') + '@' + host + ':443#Tokyo', 'Test')
    assert node == dict(name='Test', type='trojan', server=host.strip('[]'), port=443,
                        password=password, udp=True, **{'skip-cert-verify': False})
    assert not yaml_utils.validate_new_nodes([node])
    assert YAML(typ='safe').load(yaml_bytes([node]))['proxies'][0] == node


@pytest.mark.parametrize('port', [1, 443, 65535])
def test_valid_ports(port):
    assert parser.parse_trojan_link(TROJAN.replace(':443', ':' + str(port)), 'Test')['port'] == port


@pytest.mark.parametrize('query,extra', [
    ('', {}), ('?type=tcp&security=tls', {}), ('?sni=tls.example', {'sni': 'tls.example'}),
    ('?peer=tls.example', {'sni': 'tls.example'}),
    ('?sni=tls.example&peer=tls.example', {'sni': 'tls.example'}),
    ('?type=ws', {'network': 'ws', 'ws-opts': {'path': '/'}}),
    ('?type=ws&path=%2Fws%252Fencoded&host=cdn.example&sni=tls.example',
     {'network': 'ws', 'sni': 'tls.example', 'ws-opts': {'path': '/ws%2Fencoded', 'headers': {'Host': 'cdn.example'}}}),
])
def test_tls_sni_and_ws_contract(query, extra):
    node = parser.parse_trojan_link(TROJAN + query, 'Test')
    assert all(node[k] == v for k,v in extra.items())
    assert 'tls' not in node and 'servername' not in node and 'uuid' not in node


@pytest.mark.parametrize('uri', [
    'trojan://pass@example.com:443', 'trojan://p%40ss@example.com:443',
    'trojan://p%3Ass@example.com:443', 'trojan://pass@[2001:db8::1]:443',
])
def test_requested_authority_examples(uri):
    assert parser.parse_batch_nodes(uri + '#Tokyo-01')['preview'][0]['country'] == 'JP'


@pytest.mark.parametrize('suffix', [
    '?type=grpc', '?type=http', '?type=h2', '?type=xhttp', '?type=reality', '?type=',
    '?security=none', '?security=reality', '?security=', '?type=TCP',
    '?type=tcp&type=tcp', '?type=tcp&type=ws', '?sni=a.example&sni=a.example',
    '?sni=a.example&peer=b.example', '?sni=', '?peer=', '?host=cdn.example', '?path=%2Fws',
    '?type=ws&path=relative', '?type=ws&path=%2F%0d%0a', '?type=ws&host=evil%0d%0aHost',
    '?type=ws&host=', '?sni=bad%20host', '?plugin=exec', '?command=sh', '?file=%2Fetc%2Fpasswd',
    '?config=x', '?proxy=env', '?unknown=value', '?alpn=h2', '?fp=chrome',
    '?type', '?type=ws&', '?type=ws&path=%GG', '?sni=%ff',
])
def test_rejected_queries_fixed_secret_free(suffix):
    result = parser.parse_batch_nodes('Name|' + TROJAN + suffix)
    assert result['errors']
    assert PASSWORD not in json.dumps(result['preview'], ensure_ascii=False)
    with pytest.raises(ValueError) as error:
        parser.parse_trojan_link(TROJAN + suffix, 'Test')
    assert str(error.value) == 'Trojan 链接无效或包含不支持的参数。'


@pytest.mark.parametrize('uri', [
    'trojan://@example.com:443', 'trojan://pass@:443', 'trojan://pass@example.com',
    'trojan://pass@example.com:0', 'trojan://pass@example.com:65536', 'trojan://pass@example.com:bad',
    'trojan://pass@example.com:-1', 'trojan://pass@example.com:1.5', 'trojan://pass@example.com:',
    'trojan://pass@2001:db8::1:443', 'trojan://pass@[2001:db8::1:443',
    'trojan://pass@[2001:db8::1]junk:443', 'trojan://pass@[fe80::1%25eth0]:443',
    'trojan://p@ss@example.com:443', 'trojan://p:ss@example.com:443',
    'trojan://pass@example.com:443/ignored', 'trojan://pass@bad host:443',
    'trojan://pass@exa\nmple.com:443', 'trojan://pass@exam\\ple.com:443',
    'trojan://p%xx@example.com:443', 'trojan://p%ff@example.com:443',
    'trojan://pass@999.999.999.999:443', 'trojan://pass@[v1.example]:443',
    'trojan://pass@example.com..:443', 'pass@example.com:443',
    'Trojan://pass@example.com:443', 'TROJAN://pass@example.com:443',
])
def test_rejected_authority_and_case(uri):
    assert parser.parse_batch_nodes(uri)['errors']
    with pytest.raises(ValueError): parser.parse_trojan_link(uri, 'Test')


@pytest.mark.parametrize('fragment,name,code', [('', 'Node-01', 'UNKNOWN'),
    ('#', 'Node-01', 'UNKNOWN'), ('#Tokyo-01', 'Tokyo-01', 'JP'),
    ('#%E6%9D%B1%E4%BA%AC%20%E2%98%83', '東京 ☃', 'JP'), ('#%25literal', '%literal', 'UNKNOWN')])
def test_fragment_and_unknown(fragment, name, code):
    parsed = parser.parse_batch_nodes(TROJAN + fragment)
    assert not parsed['errors']
    assert parsed['preview'][0]['name'] == name and parsed['preview'][0]['country'] == code


@pytest.mark.parametrize('input', [TROJAN+'#'+quote(PASSWORD), PASSWORD.strip()+'|'+TROJAN,
    'US|'+PASSWORD.strip()+'|'+TROJAN, 'TROJAN://PRIVATE@example.com:443|'+TROJAN])
def test_preview_remark_redacts_credentials(input):
    result = parser.parse_batch_nodes(input)
    assert not result['errors']
    shown = json.dumps(result['preview'], ensure_ascii=False)
    assert PASSWORD not in shown and PASSWORD.strip() not in shown
    assert 'PRIVATE' not in shown
    assert parser.mask_sensitive(TROJAN) == 'trojan://***'


def test_mixed_order_duplicate_and_manual_override():
    batch = 'US|VM|'+vmess()+'\nJP|TJ|'+TROJAN+'\nSG|VL|'+LINK+'\nMystery|'+TROJAN
    result=parser.parse_batch_nodes(batch)
    assert [n['type'] for n in result['nodes']] == ['vmess','trojan','vless','trojan']
    key=result['preview'][-1]['key']
    edited=parser.parse_batch_nodes(batch, {key:{'name':'Edited', 'country':'TW'}})
    assert edited['preview'][-1]['source']=='Manual' and edited['preview'][-1]['country']=='TW'
    assert parser.parse_batch_nodes('US|Same|'+TROJAN+'\nUS|Same|'+LINK)['errors']


@pytest.mark.parametrize('format', ['raw','auto','base64','base64-url','auto-base64'])
def test_external_uri_lists_order_and_comments(format):
    raw=('# comment\n\n'+vmess(ps='US VM')+'\n'+TROJAN+'#Tokyo\n'+LINK+'#Singapore\n').encode()
    payload=raw
    if format in ('base64','base64-url','auto-base64'):
        payload=(base64.urlsafe_b64encode(raw) if format=='base64-url' else base64.b64encode(raw)).rstrip(b'=')
    result=source_parser.parse(payload, {'base64-url':'base64','auto-base64':'auto'}.get(format,format))
    assert [n['type'] for n in result['nodes']] == ['vmess','trojan','vless']
    assert result['nodes'][1]['password']==PASSWORD


@pytest.mark.parametrize('format', ['raw','auto','base64'])
@pytest.mark.parametrize('text', ['US|Name|'+TROJAN,TROJAN+'#Same\n'+TROJAN+'#Same',TROJAN+'?type=grpc'])
def test_external_fixed_errors(format,text):
    payload=text.encode()
    if format=='base64':payload=base64.b64encode(payload)
    with pytest.raises(SourceError) as error:source_parser.parse(payload,format)
    assert PASSWORD not in str(error.value) and 'Traceback' not in str(error.value)


@pytest.mark.parametrize('format',['auto','clash'])
def test_clash_allowed_mapping_and_skip(format):
    node=parser.parse_trojan_link(TROJAN+'?type=ws&sni=tls.example&host=cdn.example&path=%2Fws','Tokyo')
    node.update(alpn=['http/1.1'], **{'client-fingerprint':'chrome'})
    result=source_parser.parse(yaml_bytes([node,{'type':'hysteria2','name':'Unsupported'}]),format)
    assert result['warnings']==['1 unsupported proxies skipped']
    assert result['nodes'][0]==dict(node,name='🇯🇵 Tokyo')


@pytest.mark.parametrize('change',[{'password':''},{'password':None},{'password':123},{'password':False},
    {'name':''},{'server':''},{'port':True},{'port':0},{'network':'grpc'},{'tls':False},
    {'ws-opts':{'path':'/ignored'}},{'plugin':'exec'},{'certificate':'/file'},
    {'udp':'true'},{'skip-cert-verify':1},{'sni':123},{'sni':'bad host'},
    {'alpn':'h2'},{'alpn':[None]},{'client-fingerprint':False},
    {'network':'ws','ws-opts':{'path':'bad'}},
    {'network':'ws','ws-opts':{'headers':{'Host':'bad\r\nhost'}}},
    {'network':'ws','ws-opts':{'early-data-header-name':'x'}},
    {'network':'ws','ws-opts':{'headers':{'Host':'cdn.example','Other':'x'}}},
])
def test_clash_trojan_validation_remains_bounded(change):
    node=parser.parse_trojan_link(TROJAN,'Test');node.update(change)
    with pytest.raises(SourceError):source_parser.parse(yaml_bytes([node]),'clash')


@pytest.mark.parametrize('password',[' ',PASSWORD])
def test_clash_password_no_strip_and_uuid_not_required(password):
    node=parser.parse_trojan_link(TROJAN,'Test');node['password']=password
    assert source_parser.parse(yaml_bytes([node]),'clash')['nodes'][0]['password']==password
    assert not yaml_utils.validate_new_nodes([node])


@pytest.mark.parametrize('password',['',None,False,42])
def test_generator_password_validation(password):
    node=parser.parse_trojan_link(TROJAN,'Test');node['password']=password
    errors=yaml_utils.validate_new_nodes([node])
    assert errors and 'password' in errors[0] and 'uuid' not in str(errors)


def test_parser_no_network_dns_process(monkeypatch):
    def forbidden(*a,**k):raise AssertionError('offline contract')
    for owner,name in [(socket,'getaddrinfo'),(socket,'create_connection'),(subprocess,'run')]:
        monkeypatch.setattr(owner,name,forbidden)
    assert parser.parse_batch_nodes(TROJAN+'#Tokyo')['nodes']
    assert source_parser.parse(TROJAN.encode(),'auto')['nodes']


def test_health_private_probe_config_and_fingerprint(tmp_path):
    node=parser.parse_trojan_link(TROJAN+'?type=ws&sni=tls.example&path=%2Fws','Remark '+PASSWORD.strip())
    nodes=node_health.extract(yaml_bytes([node]),include_config=True)
    assert len(nodes)==1 and nodes[0]['protocol']=='trojan' and nodes[0]['name']=='Node 1'
    changed=dict(node,password=PASSWORD+'different')
    assert node_health.fingerprint(node)!=node_health.fingerprint(changed)
    assert node_health.fingerprint(node)==node_health.fingerprint(dict(node,name='Other'))
    work=tmp_path/'probe';work.mkdir(mode=0o700)
    path=mihomo_probe.write_config(work,nodes,34567,'TEST_ONLY_controller')
    config=YAML(typ='safe').load(path.read_bytes())
    assert path.stat().st_mode & 0o777==0o600
    assert config['proxies']==[dict(node,name='probe-0001')]
    assert config['external-controller']=='127.0.0.1:34567' and config['log-level']=='silent'
    assert PASSWORD not in json.dumps(node_health.extract(yaml_bytes([node])),ensure_ascii=False)


def test_prechange_mapping_and_replace_merge_byte_goldens():
    golden=json.loads((Path(__file__).parent/'trojanfixtures/before.json').read_text())
    for case in golden['mappings']:
        assert parser.parse_node_line('US|Golden|'+case['uri'])[1]==case['node']
    parsed=parser.parse_batch_nodes('US|Test|'+LINK)
    for mode,expected in golden['yaml_sha256'].items():
        data=yaml_utils.get_yaml_engine().load(SOURCE)
        result=yaml_utils.transform_yaml_config(data,parsed['nodes'],parsed['countries'],node_update_mode=mode)
        assert result['success']
        out=io.StringIO();yaml_utils.get_yaml_engine().dump(data,out)
        assert hashlib.sha256(out.getvalue().encode()).hexdigest()==expected


@pytest.mark.parametrize('payload', [
    b'proxies: [!!python/object/apply:os.system ["TEST_ONLY"]]',
    b'proxies: &a [{type: trojan, name: Test, server: example.com, port: 443, password: TEST_ONLY, ws-opts: *a}]',
    b'proxies: [{type: trojan, name: Test, server: example.com, port: 443, password: TEST_ONLY, 1: bad}]',
])
def test_trojan_yaml_tags_cycles_nonstring_keys_rejected(payload):
    with pytest.raises(SourceError):source_parser.parse(payload,'clash')


def test_trojan_notification_boundary_contains_counts_not_configs():
    from core import notification_events as events
    config=parser.parse_trojan_link(TROJAN,'Remark '+PASSWORD)
    node=node_health.extract(yaml_bytes([config]))[0]
    before={'nodes':{node['fingerprint']:dict(node_health.unknown())},'scheduler_failures':0}
    after={'nodes':{node['fingerprint']:dict(node_health.unknown(),status='unhealthy')},'scheduler_failures':0}
    collected=[]
    with events.collect(collected):events.health('proxy_health',before,after,'Home',1_800_000_000,'auto')
    assert len(collected)==1 and collected[0].count==1
    assert PASSWORD.strip() not in events.message(collected) and 'trojan://' not in events.message(collected)


@pytest.mark.parametrize('format',['auto','clash'])
def test_malformed_clash_password_warning_is_private_instance_only(format):
    import warnings
    from ruamel.yaml.error import MantissaNoDotYAML1_1Warning
    payload=b'%YAML 1.1\n---\nproxies: [{type: trojan, name: Test, server: example.com, port: 443, password: 1e9}]'
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter('always')
        filters=list(warnings.filters)
        with pytest.raises(SourceError):source_parser.parse(payload,format)
        assert not captured and warnings.filters==filters
        # The unrelated dependency instance still warns; no global suppression.
        assert YAML(typ='safe').load('%YAML 1.1\n---\nvalue: 1e9')['value']==1e9
        assert any(item.category is MantissaNoDotYAML1_1Warning for item in captured)
