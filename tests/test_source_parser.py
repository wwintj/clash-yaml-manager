import base64
import json

import pytest

from core import source_parser as sources
from core.source_errors import SourceError
from conftest import LINK

VMESS = 'vmess://' + base64.b64encode(json.dumps(dict(add='192.0.2.1', port=443,
    id='test-credential', ps='Tokyo VMess', net='ws', path='/ws', tls='tls')).encode()).decode()
VLESS = LINK + '#Singapore%20VLESS'


@pytest.mark.parametrize('format', ['raw', 'auto'])
@pytest.mark.parametrize('text,types', [(VMESS, ['vmess']), (VLESS, ['vless']),
    ('# comment\n\n' + VMESS + '\n' + VLESS, ['vmess', 'vless'])])
def test_uri_formats(format, text, types):
    result = sources.parse(text.encode(), format)
    assert [n['type'] for n in result['nodes']] == types
    assert not result['errors']
    assert result['node_names'][-1].endswith('VMess' if types[-1] == 'vmess' else 'VLESS')


@pytest.mark.parametrize('encoder', [base64.b64encode, base64.urlsafe_b64encode])
@pytest.mark.parametrize('format', ['auto', 'base64'])
def test_base64(encoder, format):
    encoded = encoder((VMESS + '\n' + VLESS).encode()).rstrip(b'=')
    payload = b'\n '.join(encoded[i:i+19] for i in range(0, len(encoded), 19))
    assert len(sources.parse(payload, format)['nodes']) == 2


def clash(nodes):
    return json.dumps({'proxies': nodes}).encode()  # JSON is a YAML subset.


def node(**changes):
    return dict(dict(name='Tokyo', type='vless', server='203.0.113.1', port=443,
                     uuid='test-credential', tls=True, network='ws',
                     **{'ws-opts': {'path':'/ws', 'headers': {'Host':'node.example'}},
                        'reality-opts': {'public-key':'key'}, 'alpn':['h2'],
                        'client-fingerprint':'chrome', 'udp':True, 'skip-cert-verify':False}), **changes)


@pytest.mark.parametrize('format', ['auto', 'clash'])
def test_clash_options_and_skipped_protocols(format):
    result = sources.parse(clash([node(), node(type='vmess',name='Mystery'), node(type='ss')]), format)
    assert result['warnings'] == ['1 unsupported proxies skipped']
    assert [c['code'] for c in result['countries']] == ['JP', 'UNKNOWN']
    assert result['countries'][1]['group'] == '🌐 其他节点'
    assert result['nodes'][0]['ws-opts']['headers']['Host'] == 'node.example'
    assert result['nodes'][0]['reality-opts'] == {'public-key':'key'}


@pytest.mark.parametrize('change', [dict(port=True), dict(port=0), dict(port=65536), dict(port=1.2),
    dict(server=None), dict(server=''), dict(uuid=' '), dict(name=''), dict(type=None)])
def test_invalid_clash_node(change):
    with pytest.raises(SourceError): sources.parse(clash([node(**change)]), 'clash')


@pytest.mark.parametrize('payload,format', [(b'%%% PRIVATE', 'base64'), (b'proxies: [', 'clash'),
    (b'proxies: [{type: trojan}]', 'auto'), (b'proxies: []', 'clash'), (b'[]','clash'),
    (b'!!python/object/apply:os.system [echo secret]', 'clash'),
    (b'proxies: &a [*a]', 'clash'), (b'proxies: [{name: 2026-01-01, type: vless}]', 'clash'),
    (b'proxies: [{type: vless, port: .nan}]', 'clash'), (b'\xff', 'auto'),
    (b'hello', 'raw'), (b'   # comment\n', 'raw'), ('私人无效内容'.encode(), 'auto'),
    ('私人无效内容'.encode(), 'base64')])
def test_malformed_is_sanitized(payload, format):
    with pytest.raises(SourceError) as error: sources.parse(payload, format)
    assert 'PRIVATE' not in str(error.value) and 'secret' not in str(error.value)


@pytest.mark.parametrize('payload', [(VLESS+'\n'+VLESS).encode(), clash([node(),node()])])
def test_duplicate_names(payload):
    with pytest.raises(SourceError, match='Duplicate node name'): sources.parse(payload)


def test_unnamed_uris_get_ordered_names():
    assert sources.parse((LINK+'\n'+LINK).encode())['node_names'] == ['🌐 Node-01', '🌐 Node-02']


def test_size_and_structure_budgets(monkeypatch):
    monkeypatch.setattr(sources, 'MAX_PAYLOAD', 4)
    with pytest.raises(SourceError, match='too large'): sources.parse(b'12345')
    with pytest.raises(SourceError): sources._plain([[[1]]], budget=[2])
    cycle = []; cycle.append(cycle)
    with pytest.raises(SourceError): sources._plain(cycle)


def test_cross_source_duplicate_uses_final_display_name():
    first = sources.parse((LINK+'#Tokyo').encode())
    second = sources.parse(clash([node(name='🇯🇵 Tokyo')]))
    with pytest.raises(SourceError, match='Duplicate node name'): sources.combine([first,second])
