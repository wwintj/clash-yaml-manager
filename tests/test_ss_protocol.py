"""Offline Shadowsocks contract, privacy boundaries and pre-change byte goldens."""
import base64
import hashlib
import io
import json
from pathlib import Path
import socket
import subprocess
from urllib.parse import quote
import warnings

import pytest
from ruamel.yaml import YAML

from core import parser, source_parser, yaml_utils, node_health, mihomo_probe
from core.source_errors import SourceError
from conftest import LINK
from test_parser import vmess
from test_trojan_protocol import TROJAN, yaml_bytes
from test_yaml_diff import SOURCE

PASSWORD = ' TEST_ONLY_SS_密:@/%40 + '


def ss_uri(password=PASSWORD, host='example.com', port=443, cipher='aes-256-gcm',
           form='legacy', urlsafe=True, padding=False):
    encode = base64.urlsafe_b64encode if urlsafe else base64.b64encode
    def encoded(value):
        result = encode(value.encode()).decode()
        return result if padding else result.rstrip('=')
    if form == 'plain':
        return 'ss://' + quote(cipher, safe='') + ':' + quote(password, safe='') + '@' + host + ':' + str(port)
    credentials = cipher + ':' + password
    if form == 'legacy':
        return 'ss://' + encoded(credentials + '@' + host + ':' + str(port))
    return 'ss://' + encoded(credentials) + '@' + host + ':' + str(port)


SS = ss_uri()


@pytest.mark.parametrize('form', ['legacy', 'userinfo', 'plain'])
@pytest.mark.parametrize('password', ['pass', 'p@ss', 'p:ss', 'p/ss', 'p%40ss', ' 密码 ', ' ', '\t\n', '+/#?'])
@pytest.mark.parametrize('host', ['example.com', '192.0.2.10', '[2001:db8::1]'])
def test_password_exact_once_hosts_and_yaml(form, password, host):
    uri = ss_uri(password, host, form=form)
    node = parser.parse_ss_link(uri, 'Test')
    assert node == dict(name='Test', type='ss', server=host.strip('[]'), port=443,
                        cipher='aes-256-gcm', password=password, udp=True)
    assert not yaml_utils.validate_new_nodes([node])
    assert YAML(typ='safe').load(yaml_bytes([node]))['proxies'][0] == node
    assert parser.parse_batch_nodes(uri)['nodes'][0]['password'] == password


@pytest.mark.parametrize('form', ['legacy', 'userinfo'])
@pytest.mark.parametrize('urlsafe', [False, True])
@pytest.mark.parametrize('padding', [False, True])
def test_base64_alphabets_and_padding(form, urlsafe, padding):
    # UTF-8 data deliberately produces both '/' and '+' in standard Base64.
    password = 'TEST_ONLY_???\uffff??'
    uri = ss_uri(password, form=form, urlsafe=urlsafe, padding=padding)
    assert parser.parse_ss_link(uri, 'Test')['password'] == password
    assert parser.parse_ss_link('ss://' + quote(uri[5:].partition('@')[0], safe='') + ('@'+uri.partition('@')[2] if '@' in uri else ''), 'Test')['password'] == password


@pytest.mark.parametrize('cipher', ['aes-256-gcm', 'chacha20-ietf-poly1305', '2022-blake3-aes-128-gcm', 'UnknownCipher', ' ', ' 密码 '])
@pytest.mark.parametrize('form', ['legacy', 'userinfo', 'plain'])
def test_nonempty_cipher_preserved_without_whitelist(cipher, form):
    node = parser.parse_ss_link(ss_uri(cipher=cipher, form=form), 'Test')
    assert node['cipher'] == cipher and node['password'] == PASSWORD
    assert source_parser.parse(yaml_bytes([node]), 'clash')['nodes'][0]['cipher'] == cipher


@pytest.mark.parametrize('port', [1, 443, 65535])
def test_valid_port(port):
    assert parser.parse_ss_link(ss_uri(port=port), 'Test')['port'] == port


@pytest.mark.parametrize('uri', [
    'ss://', 'ss://%%%', 'ss://a', 'ss://a===', 'ss://YWJj===', 'ss://YWJj=bad',
    'ss://!!!!@example.com:443', 'ss://YWJj@example.com:443',
    ss_uri(password=''), ss_uri(cipher=''), ss_uri(port=0), ss_uri(port=65536),
    ss_uri(port=-1), ss_uri(port='1.2'), ss_uri(port='bad'), ss_uri(port=''),
    ss_uri(host=''), ss_uri(host='bad host'), ss_uri(host='exa\nmple.com'),
    ss_uri(host='exam\\ple.com'), ss_uri(host='999.999.999.999'),
    ss_uri(host='[2001:db8::1]junk'), ss_uri(host='2001:db8::1'),
    ss_uri(host='[fe80::1%25eth0]'), ss_uri(host='[v1.example]'),
    'ss://aes:bad@password@example.com:443', 'ss://aes:bad/path@example.com:443',
    'ss://aes:bad%XX@example.com:443', 'ss://aes:bad%FF@example.com:443',
    ss_uri(form='userinfo')+'/path', ss_uri()+'#%ff',
    SS.replace('ss://', 'SS://'), 'ss://aes:bad@exam\nple.com:443',
])
def test_invalid_authority_encoding_safe_errors(uri):
    with pytest.raises(ValueError) as error:
        parser.parse_ss_link(uri, 'Test')
    assert str(error.value) == str(parser.SSValidationError())
    result = parser.parse_batch_nodes('Name|' + uri)
    assert result['errors']
    assert PASSWORD.strip() not in json.dumps(result['preview'], ensure_ascii=False)


@pytest.mark.parametrize('suffix', [
    '?plugin=exec', '/?plugin=exec', '?plugin=', '?plugin', '?%70lugin=TEST_ONLY',
    '?plugin=one&plugin=two', '?obfs=x', '?simple-obfs=x', '?v2ray-plugin=x',
    '?plugin_opts=x', '?sip003=x', '?PLUGIN=x',
])
@pytest.mark.parametrize('form', ['legacy', 'userinfo', 'plain'])
def test_plugin_explicit_error_never_ignored(suffix, form):
    parsed = parser.parse_batch_nodes('Name|' + ss_uri(form=form) + suffix)
    assert not parsed['nodes'] and '插件及混淆选项不受支持' in parsed['errors'][0]
    assert PASSWORD.strip() not in str(parsed['errors'])


@pytest.mark.parametrize('suffix', ['?', '?udp=true', '?tls=true', '?sni=host', '?unknown=x', '?command=sh'])
def test_no_query_passthrough(suffix):
    with pytest.raises(ValueError, match='query'):
        parser.parse_ss_link(SS + suffix, 'Test')


@pytest.mark.parametrize('fragment,name,code', [('', 'Node-01', 'UNKNOWN'), ('#', 'Node-01', 'UNKNOWN'),
    ('#Tokyo-01', 'Tokyo-01', 'JP'), ('#%E6%9D%B1%E4%BA%AC%20%E2%98%83', '東京 ☃', 'JP'),
    ('#%25literal', '%literal', 'UNKNOWN'), ('#'+quote('<script>alert(1)</script>'), '<script>alert(1)</script>', 'UNKNOWN')])
def test_fragment_names(fragment, name, code):
    parsed = parser.parse_batch_nodes(SS + fragment)
    assert not parsed['errors'] and parsed['preview'][0]['name'] == name
    assert parsed['preview'][0]['country'] == code


@pytest.mark.parametrize('text', [SS+'#'+quote(PASSWORD), PASSWORD.strip()+'|'+SS,
    'US|'+PASSWORD.strip()+'|'+SS, 'SS://TEST_ONLY_PRIVATE@host:443|'+SS])
def test_preview_redaction(text):
    parsed = parser.parse_batch_nodes(text)
    assert not parsed['errors']
    shown = json.dumps(parsed['preview'], ensure_ascii=False)
    assert PASSWORD.strip() not in shown and 'TEST_ONLY_PRIVATE' not in shown
    assert parser.mask_sensitive(SS) == 'ss://***'


def test_mixed_order_duplicates_manual_overrides():
    batch = 'US|VM|'+vmess()+'\nJP|TJ|'+TROJAN+'\nSG|VL|'+LINK+'\nOpaque|'+SS
    parsed = parser.parse_batch_nodes(batch)
    assert [n['type'] for n in parsed['nodes']] == ['vmess', 'trojan', 'vless', 'ss']
    key = parsed['preview'][-1]['key']
    edited = parser.parse_batch_nodes(batch, {key: dict(name='Edited', country='TW')})
    assert edited['preview'][-1]['source'] == 'Manual' and edited['preview'][-1]['country'] == 'TW'
    assert parser.parse_batch_nodes('US|Same|'+SS+'\nUS|Same|'+LINK)['errors']


@pytest.mark.parametrize('format', ['raw', 'auto', 'base64', 'base64-url', 'auto-base64'])
def test_external_nested_encoding_mixed_order(format):
    raw = ('# comment\n'+vmess(ps='US-VM')+'\n'+LINK+'#London-VL\n'+TROJAN+'#Tokyo-TJ\n'+SS+'#Singapore-SS').encode()
    payload = raw
    if format in ('base64', 'base64-url', 'auto-base64'):
        payload = (base64.urlsafe_b64encode(raw) if format == 'base64-url' else base64.b64encode(raw)).rstrip(b'=')
    result = source_parser.parse(payload, {'base64-url':'base64', 'auto-base64':'auto'}.get(format, format))
    assert [n['type'] for n in result['nodes']] == ['vmess', 'vless', 'trojan', 'ss']
    assert result['nodes'][-1]['password'] == PASSWORD


@pytest.mark.parametrize('format', ['auto', 'clash'])
def test_clash_plain_unknown_extras_retained(format):
    node = parser.parse_ss_link(SS, 'Tokyo')
    node.update(**{'x-opaque': {'a': [1, True, None, 'TEST_ONLY_extra']}, 'udp-over-tcp': True})
    result = source_parser.parse(yaml_bytes([node, dict(type='tuic', name='Skipped')]), format)
    assert result['nodes'][0] == dict(node, name='🇯🇵 Tokyo')
    assert result['warnings'] == ['1 unsupported proxies skipped']


@pytest.mark.parametrize('change', [{'password':''}, {'password':None}, {'password':1}, {'cipher':''},
    {'cipher':None}, {'cipher':False}, {'name':''}, {'server':''}, {'port':True}, {'port':0}, {'udp':'true'},
    {'plugin':'exec'}, {'plugin':None}, {'plugin-opts':{}}, {'PLUGIN':'exec'}, {'plugin_opts':{}},
    {'obfs':''}, {'obfs-opts':{}}, {'simple-obfs':''}, {'v2ray-plugin':'exec'}, {'sip003':{}}])
def test_clash_invalid_fields_and_plugin_rejected(change):
    node = parser.parse_ss_link(SS, 'Test'); node.update(change)
    with pytest.raises(SourceError) as error:
        source_parser.parse(yaml_bytes([node]), 'clash')
    assert PASSWORD.strip() not in str(error.value)


@pytest.mark.parametrize('field', ['cipher', 'password'])
@pytest.mark.parametrize('value', ['', None, False, 42])
def test_generator_required_fields_without_uuid(field, value):
    node = parser.parse_ss_link(SS, 'Test'); node[field] = value
    errors = yaml_utils.validate_new_nodes([node])
    assert errors and field in errors[0] and 'uuid' not in str(errors)


@pytest.mark.parametrize('payload', [
    b'proxies: [!!python/object/apply:os.system ["TEST_ONLY"]]',
    b'proxies: &a [{type: ss, name: Test, server: example.com, port: 443, cipher: aes-256-gcm, password: TEST_ONLY, x: *a}]',
    b'proxies: [{type: ss, name: Test, server: example.com, port: 443, cipher: aes-256-gcm, password: TEST_ONLY, 1: bad}]',
    b'proxies: [{type: ss, name: Test, server: example.com, port: 443, cipher: aes-256-gcm, password: TEST_ONLY, x: .inf}]',
])
def test_yaml_security_boundaries(payload):
    with pytest.raises(SourceError): source_parser.parse(payload, 'clash')


def test_plain_depth_budget_and_payload_limit():
    node = parser.parse_ss_link(SS, 'Test'); nested = 'TEST_ONLY'
    for _ in range(34): nested = [nested]
    node['x-extra'] = nested
    with pytest.raises(SourceError): source_parser.parse(yaml_bytes([node]), 'clash')
    with pytest.raises(SourceError): source_parser._plain(['TEST_ONLY'] * 100001)
    with pytest.raises(SourceError) as error: source_parser.parse(b'x' * (source_parser.MAX_PAYLOAD+1), 'raw')
    assert error.value.code == 'size'


@pytest.mark.parametrize('format', ['auto', 'clash'])
def test_yaml_warning_does_not_echo_invalid_numeric_password(format):
    payload = b'%YAML 1.1\n---\nproxies: [{type: ss, name: Test, server: example.com, port: 443, cipher: aes-256-gcm, password: 1e9}]'
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter('always'); filters = list(warnings.filters)
        with pytest.raises(SourceError): source_parser.parse(payload, format)
        assert not captured and warnings.filters == filters


def test_offline_no_dns_network_process(monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('offline contract')
    for owner, name in [(socket, 'getaddrinfo'), (socket, 'create_connection'), (subprocess, 'run'), (subprocess, 'Popen')]:
        monkeypatch.setattr(owner, name, forbidden)
    assert parser.parse_batch_nodes(SS)['nodes']
    assert source_parser.parse(SS.encode(), 'auto')['nodes']
    assert source_parser.parse(yaml_bytes([parser.parse_ss_link(SS, 'Test')]), 'clash')['nodes']


def test_private_probe_config_and_notification_counts(tmp_path):
    from core import notification_events as events
    node = parser.parse_ss_link(SS, 'Remark '+PASSWORD.strip())
    nodes = node_health.extract(yaml_bytes([node]), include_config=True)
    assert len(nodes) == 1 and nodes[0]['protocol'] == 'ss' and nodes[0]['name'] == 'Node 1'
    assert node_health.fingerprint(node) != node_health.fingerprint(dict(node, password=PASSWORD+'changed'))
    assert node_health.fingerprint(node) == node_health.fingerprint(dict(node, name='Other'))
    work = tmp_path/'probe'; work.mkdir(mode=0o700)
    path = mihomo_probe.write_config(work, nodes, 34567, 'TEST_ONLY_controller')
    config = YAML(typ='safe').load(path.read_bytes())
    assert path.stat().st_mode & 0o777 == 0o600 and work.stat().st_mode & 0o777 == 0o700
    assert config['proxies'] == [dict(node, name='probe-0001')]
    assert config['external-controller'] == '127.0.0.1:34567' and config['log-level'] == 'silent'
    public = node_health.extract(yaml_bytes([node]))
    assert PASSWORD.strip() not in json.dumps(public, ensure_ascii=False)
    before = {'nodes':{nodes[0]['fingerprint']:dict(node_health.unknown())}, 'scheduler_failures':0}
    after = {'nodes':{nodes[0]['fingerprint']:dict(node_health.unknown(), status='unhealthy')}, 'scheduler_failures':0}
    collected = []
    with events.collect(collected): events.health('proxy_health', before, after, 'Home', 1_800_000_000, 'auto')
    assert len(collected) == 1 and collected[0].count == 1
    assert PASSWORD.strip() not in events.message(collected) and 'ss://' not in events.message(collected)


def test_prechange_vm_vl_trojan_mappings_preview_and_yaml_bytes():
    golden = json.loads((Path(__file__).parent/'ssfixtures/before.json').read_text())
    for case in golden['mappings']:
        assert parser.parse_node_line('US|Golden|'+case['uri'])[1] == case['node']
    preview = json.dumps(parser.parse_batch_nodes(golden['preview_text']), sort_keys=True).encode()
    assert hashlib.sha256(preview).hexdigest() == golden['preview_sha256']
    parsed = parser.parse_batch_nodes('US|Test|'+LINK+'\nJP|TJ|'+TROJAN)
    for mode, expected in golden['yaml_sha256'].items():
        data = yaml_utils.get_yaml_engine().load(SOURCE)
        result = yaml_utils.transform_yaml_config(data, parsed['nodes'], parsed['countries'], node_update_mode=mode)
        assert result['success']
        out = io.StringIO(); yaml_utils.get_yaml_engine().dump(data, out)
        assert hashlib.sha256(out.getvalue().encode()).hexdigest() == expected
