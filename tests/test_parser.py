import base64
import json

import pytest

from core.parser import parse_batch_nodes, parse_vless_link, parse_vless_node, parse_vmess_link, parse_vmess_node
from conftest import LINK


def vmess(**overrides):
    data = dict(add='example.com', port='443', id='test-uuid', net='tcp')
    data.update(overrides)
    return 'vmess://' + base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()


@pytest.mark.parametrize('urlsafe', [False, True])
def test_vmess_base64_and_tls_ws(urlsafe):
    link = vmess(net='ws', tls='tls', host='cdn.example.com', path='/ws',
                 sni='tls.example.com', fp='chrome', alpn='h2,http/1.1', ps='ÿÿÿ')
    if urlsafe:
        link = link.replace('+', '-').replace('/', '_').replace('vmess:__', 'vmess://').rstrip('=')
    node = parse_vmess_link(link, '测试')
    assert node['type'] == 'vmess' and node['port'] == 443
    assert node['tls'] and node['servername'] == 'tls.example.com'
    assert node['client-fingerprint'] == 'chrome'
    assert node['alpn'] == ['h2', 'http/1.1']
    assert node['ws-opts'] == {'path': '/ws', 'headers': {'Host': 'cdn.example.com'}}


def test_vmess_host_fallback():
    assert parse_vmess_link(vmess(net='ws'), 'test')['ws-opts']['headers']['Host'] == 'example.com'


@pytest.mark.parametrize('payload', ['!!!', base64.b64encode(b'{bad json').decode()])
def test_malformed_vmess(payload):
    assert parse_batch_nodes('US|test|vmess://' + payload)['errors']


@pytest.mark.parametrize('host', ['192.0.2.1', '[2001:db8::1]'])
@pytest.mark.parametrize('security', ['', 'tls', 'reality'])
@pytest.mark.parametrize('network', ['tcp', 'ws'])
def test_vless(host, security, network):
    node = parse_vless_link(f'vless://test-uuid@{host}:443?type={network}&security={security}'
                            '&sni=tls.example.com&fp=chrome&pbk=public&sid=1234&host=cdn.example.com&path=%2Fws', 'test')
    assert node['server'] == host.strip('[]') and node['port'] == 443
    assert node.get('network', 'tcp') == network
    if security:
        assert node['tls'] and node['servername'] == 'tls.example.com'
        assert node['client-fingerprint'] == 'chrome'
    if security == 'reality':
        assert node['reality-opts'] == {'public-key': 'public', 'short-id': '1234'}
    if network == 'ws':
        assert node['ws-opts'] == {'path': '/ws', 'headers': {'Host': 'cdn.example.com'}}


@pytest.mark.parametrize('text', ['XX|name|' + LINK, 'US|name', 'US|test|ss://unsupported',
                                 'US|name|' + LINK + '\nUS|name|' + LINK])
def test_batch_invalid(text):
    assert parse_batch_nodes(text)['errors']


def test_blank_unicode_flags():
    result = parse_batch_nodes('\n us |测试 🌟|' + LINK + '\n\nHK|🇭🇰 香港|' + LINK)
    assert result['errors'] == []
    assert result['node_names'] == ['🇺🇸 测试 🌟', '🇭🇰 香港']


@pytest.mark.p0
@pytest.mark.parametrize('port', [-1, 0, 65536, True, 1.5, 'secret-invalid-port'])
def test_vmess_rejects_invalid_port(port):
    assert parse_batch_nodes('US|test|' + vmess(port=port))['errors']


@pytest.mark.parametrize('port', ['0', '-1', '65536', 'bad'])
def test_vless_rejects_invalid_port(port):
    assert parse_batch_nodes('US|test|vless://id@example.com:' + port)['errors']


@pytest.mark.p0
def test_vless_error_never_echoes_invalid_port():
    result = parse_batch_nodes('US|test|vless://id@example.com:private-token-value')
    assert result['errors'] and 'private-token-value' not in str(result['errors'])


@pytest.mark.p0
def test_vless_path_decoded_once():
    assert parse_vless_link(LINK + '&type=ws', 'test')  # duplicate query remains compatible
    node = parse_vless_link(LINK.replace('type=tcp', 'type=ws&path=%2Fws%252Fencoded'), 'test')
    assert node['ws-opts']['path'] == '/ws%2Fencoded'


@pytest.mark.p0
def test_empty_node_name():
    assert parse_batch_nodes('US||' + LINK)['errors']


@pytest.mark.parametrize('payload', ['[]', 'null', '42'])
def test_vmess_json_must_be_object(payload):
    link = 'vmess://' + base64.b64encode(payload.encode()).decode()
    assert parse_batch_nodes('US|name|' + link)['errors']


@pytest.mark.parametrize('field', ['add', 'id'])
def test_vmess_null_required_fields(field):
    assert parse_batch_nodes('US|name|' + vmess(**{field: None}))['errors']


def test_vless_reality_vision_flow():
    node = parse_vless_node('vless://test-uuid@192.0.2.1:443?encryption=none&flow=xtls-rprx-vision'
                            '&security=reality&sni=www.example.com&fp=chrome&pbk=public&sid=12&type=tcp', 'test')
    assert node['flow'] == 'xtls-rprx-vision'
    assert 'flow' not in parse_vless_node(LINK, 'test')


@pytest.mark.parametrize('query, key, value', [
    ('type=grpc&serviceName=svc', 'grpc-opts', {'grpc-service-name': 'svc'}),
    ('type=h2&host=a.example.com,b.example.com&path=%2Fh2', 'h2-opts',
     {'host': ['a.example.com', 'b.example.com'], 'path': '/h2'}),
])
def test_vless_transport_options(query, key, value):
    node = parse_vless_node(f'vless://test-uuid@192.0.2.1:443?security=tls&{query}', 'test')
    assert node[key] == value


@pytest.mark.parametrize('net, key, value', [
    ('grpc', 'grpc-opts', {'grpc-service-name': 'svc'}),
    ('h2', 'h2-opts', {'host': ['cdn.example.com'], 'path': 'svc'}),
])
def test_vmess_transport_options(net, key, value):
    node = parse_vmess_node(vmess(net=net, tls='tls', path='svc', host='cdn.example.com'), 'test')
    assert node['network'] == net and node[key] == value


def test_vmess_grpc_without_service_name_has_no_empty_options():
    assert 'grpc-opts' not in parse_vmess_node(vmess(net='grpc'), 'test')


@pytest.mark.parametrize('line, name', [
    ('vless://test-uuid@192.0.2.1:443?type=tcp#HK%20|%2001', 'HK | 01'),
    ('vless://test-uuid@192.0.2.1:443?type=tcp#HK | 02', 'HK | 02'),
    ('自定义名称|vless://test-uuid@192.0.2.1:443?type=tcp#A|B', '自定义名称'),
    ('US|名称|vless://test-uuid@192.0.2.1:443?type=tcp#A | B', '名称'),
])
def test_pipe_inside_link_remark(line, name):
    result = parse_batch_nodes(line)
    assert not result['errors']
    assert result['nodes'][0]['name'].endswith(name)
    assert result['nodes'][0]['server'] == '192.0.2.1'
