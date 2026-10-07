"""Built-in cleanup boundaries and shared generation contracts, with no network."""
import ast
import base64
import copy
import hashlib
import json
from pathlib import Path
import socket

import pytest

from conftest import LINK, ROOT
from core import countries, fixed_subscriptions as fixed, generator, parser, yaml_utils as yaml

DEFAULT = ROOT / 'defaults/default.yaml'
STATIC_CODES = ('HK', 'TW', 'SG', 'JP', 'US', 'KR')
COUNTRY_NAMES = {info['group'] for info in countries.COUNTRY_MAPPING.values()}
FUNCTIONAL = ['🚀 节点选择', '🚀 手动切换', '📲 电报消息', '💬 Ai平台', '📹 油管视频',
              '🎥 奈飞视频', '📺 巴哈姆特', '📺 哔哩哔哩', '🌍 国外媒体', '🌏 国内媒体',
              '📢 谷歌FCM', 'Ⓜ️ 微软Bing', 'Ⓜ️ 微软云盘', 'Ⓜ️ 微软服务', '🍎 苹果服务',
              '🎮 游戏平台', '🎶 网易音乐', '🎯 全球直连', '🛑 广告拦截', '🍃 应用净化',
              '🐟 漏网之鱼', '🎥 奈飞节点']
SPECIAL = ['🎥 奈飞节点', '📹 油管视频', '💬 Ai平台', '📲 电报消息',
           '🎵 TikTok', '🎬 HBO', '🏰 Disney+', '𝕏 X/Twitter']
UUID = '11111111-1111-4111-8111-111111111111'
VMESS = 'vmess://' + base64.b64encode(json.dumps(dict(add='example.com', port='443',
                       id=UUID, net='tcp')).encode()).decode()
LINKS = {'vmess': VMESS, 'vless': LINK, 'trojan': 'trojan://TEST_ONLY@example.com:443',
         'ss': 'ss://aes-256-gcm:TEST_ONLY@example.com:443',
         'hysteria2': 'hy2://TEST_ONLY@example.com:443'}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Default generation must not perform DNS or network work')
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


def parsed(text):
    result = generator.parse_form_nodes({'batch_nodes': text})
    assert not result['errors'], result['errors']
    return result


def rows(*codes):
    return '\n'.join(f'{code}|Node-{i}|{LINK}' for i, code in enumerate(codes))


def generate(tmp_path, nodes, special=(), source=DEFAULT, mode='replace'):
    result = generator.generate(source, tmp_path / 'outputs', tmp_path / 'backups',
                                nodes, list(special), node_update_mode=mode,
                                template_profile='default' if source == DEFAULT else 'custom')
    assert result['success'], result['errors']
    data = yaml.load_yaml(result['output_path'])
    assert not yaml.validate_proxy_references(data)
    return data


def groups(data):
    return {group['name']: group for group in data['proxy-groups']}


def assert_countries(data, nodes):
    expected = {}
    for info in nodes['countries']:
        expected.setdefault(info['group'], []).append(info['node_name'])
    actual = {name: group['proxies'] for name, group in groups(data).items() if name in COUNTRY_NAMES}
    assert actual == expected
    assert all('DIRECT' not in members for members in actual.values())


def test_template_preserves_rules_unrelated_settings_and_functional_groups():
    payload = DEFAULT.read_bytes()
    data = yaml.load_yaml(str(DEFAULT))
    assert data['proxies'] == []
    assert [group['name'] for group in data['proxy-groups']] == FUNCTIONAL
    assert not COUNTRY_NAMES.intersection(groups(data))
    assert all(not COUNTRY_NAMES.intersection(group.get('proxies', []))
               for group in data['proxy-groups'])
    assert groups(data)['🎥 奈飞节点']['proxies'] == ['DIRECT']
    # Approved pre-cleanup bytes/structure: catch unrelated routing or DNS edits.
    assert len(data['rules']) == 10410
    assert hashlib.sha256(payload.split(b'rules:\n', 1)[1]).hexdigest() == (
        'a1a15c778d9e212c8e9a23302e733ae0c3402c1e7cfdcf5f9ca297aef0cfe9d6')
    non_groups = {key: value for key, value in data.items() if key != 'proxy-groups'}
    assert hashlib.sha256(json.dumps(non_groups, ensure_ascii=False, sort_keys=True).encode()).hexdigest() == (
        '3a61251b692fe251f275bdf404ee9efc4dd8dca8e5ec3fd601474fa927e74e77')


@pytest.mark.parametrize('codes', [('US',), ('US', 'SG', 'DE'), ('US', 'US', 'SG', 'DE'),
                                  ('DE',), ('FR',), ('CA',), ('AU',), ('UNKNOWN',)])
@pytest.mark.parametrize('mode', ['replace', 'merge'])
def test_exact_dynamic_countries_membership_and_rule_roundtrip(tmp_path, codes, mode):
    nodes = parsed(rows(*codes))
    data = generate(tmp_path, nodes, mode=mode)
    assert_countries(data, nodes)
    assert [node['name'] for node in data['proxies']] == nodes['node_names']
    assert data['rules'] == yaml.load_yaml(str(DEFAULT))['rules']
    assert len(data['rules']) == 10410


@pytest.mark.parametrize('text,expected', [('Opaque|'+LINK, 'UNKNOWN'),
    ('Frankfurt-01|'+LINK, 'DE'), (LINK+'#Paris-01', 'FR'),
    ('DE|US Singapore|'+LINK+'#Tokyo', 'DE')])
def test_detection_and_manual_priority_generate_only_resolved_country(tmp_path, text, expected):
    nodes = parsed(text)
    assert nodes['countries'][0]['code'] == expected
    assert_countries(generate(tmp_path, nodes), nodes)


@pytest.mark.parametrize('text,lookup_calls,expected', [
    ('DE|Singapore|'+LINK, 0, 'DE'), ('Tokyo|'+LINK, 0, 'JP'),
    ('UNKNOWN|Opaque|'+LINK, 0, 'UNKNOWN'), ('Opaque|'+LINK, 1, 'SG')])
def test_optional_offline_lookup_keeps_priority(tmp_path, text, lookup_calls, expected):
    class Offline:
        calls = 0
        def country(self, server):
            self.calls += 1
            return 'SG'
    lookup = Offline()
    nodes = generator.parse_form_nodes({'batch_nodes': text}, lookup)
    assert not nodes['errors'] and lookup.calls == lookup_calls
    assert nodes['countries'][0]['code'] == expected
    assert_countries(generate(tmp_path, nodes), nodes)


@pytest.mark.parametrize('protocol', list(LINKS))
def test_five_protocols_default_country_and_references(tmp_path, protocol):
    nodes = parsed('US|Protocol|'+LINKS[protocol])
    assert nodes['nodes'][0]['type'] == protocol
    assert_countries(generate(tmp_path, nodes), nodes)


@pytest.mark.parametrize('selected', SPECIAL)
def test_selected_special_group_and_unselected_groups_keep_contract(tmp_path, selected):
    # Ensure this matrix follows the application's actual selector inventory.
    tree = ast.parse((ROOT / 'app.py').read_text())
    value = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'DEFAULT_SPECIAL_GROUPS'
                         for target in node.targets))
    assert value == SPECIAL
    nodes = parsed(rows('US', 'DE'))
    data = generate(tmp_path, nodes, [selected])
    before = groups(yaml.load_yaml(str(DEFAULT)))
    after = groups(data)
    assert after[selected]['proxies'] == list(before.get(selected, {}).get('proxies', [])) + nodes['node_names']
    for name in SPECIAL:
        if name == selected:
            continue
        if name in before:
            assert after[name] == before[name]
        else:
            assert name not in after
    assert_countries(data, nodes)


def test_three_node_default_selector_projects_nodes_then_countries(tmp_path):
    nodes = parsed(rows('US', 'SG', 'DE'))
    data = generate(tmp_path, nodes)
    assert groups(data)['🚀 节点选择']['proxies'] == nodes['node_names'] + [
        '🇺🇸 美国节点', '🇸🇬 狮城节点', '🇩🇪 德国节点', '🚀 手动切换', 'DIRECT']


def test_custom_replace_keeps_existing_country_groups_and_valid_refs(tmp_path):
    custom = tmp_path / 'custom.yaml'
    custom.write_text('''proxies: [{name: old, type: vendor-proxy}]
proxy-groups:
  - {name: '🇯🇵 日本节点', type: select, proxies: [DIRECT], icon: retained}
  - {name: '🇺🇸 美国节点', type: fallback, proxies: [old, DIRECT], url: 'https://example.com/check', interval: 111}
  - {name: custom, type: select, proxies: ['🇯🇵 日本节点', '🇺🇸 美国节点', DIRECT]}
rules: ['MATCH,custom']
''')
    before = yaml.load_yaml(str(custom))
    nodes = parsed(rows('US'))
    data = generate(tmp_path, nodes, source=custom)
    assert groups(data)['🇯🇵 日本节点'] == groups(before)['🇯🇵 日本节点']
    us = copy.deepcopy(groups(before)['🇺🇸 美国节点'])
    us['proxies'] = ['DIRECT'] + nodes['node_names']
    assert groups(data)['🇺🇸 美国节点'] == us
    assert groups(data)['custom'] == groups(before)['custom']
    assert data['rules'] == before['rules']


def test_custom_merge_retains_source_objects_group_order_refs_and_comments():
    source = (ROOT / 'tests/fixtures/merge/base.yaml').read_text()
    data = yaml.load_yaml_text(source)
    before = copy.deepcopy(data)
    objects = list(data['proxies'])
    names = [group['name'] for group in data['proxy-groups']]
    nodes = parsed(rows('US', 'DE'))
    result = yaml.transform_yaml_config(data, nodes['nodes'], nodes['countries'], node_update_mode='merge')
    assert result['success'], result['errors']
    assert all(data['proxies'][i] is obj for i, obj in enumerate(objects))
    assert data['proxies'] == before['proxies'] + nodes['nodes']
    assert [group['name'] for group in data['proxy-groups']][:len(names)] == names
    for name in names:
        expected = copy.deepcopy(groups(before)[name])
        if name in yaml.GENERAL_GROUPS or name == countries.COUNTRY_MAPPING['US']['group']:
            expected['proxies'].extend(nodes['node_names'] if name in yaml.GENERAL_GROUPS else nodes['node_names'][:1])
        elif not expected.get('proxies') and not expected.get('use'):
            expected['proxies'] = nodes['node_names'] if expected['type'] in ('url-test', 'fallback') else ['🚀 手动切换']
        assert groups(data)[name] == expected
    assert not yaml.validate_proxy_references(data)
    assert data['rules'] == before['rules']
    assert '# retained reference comment' in yaml.serialize_yaml(data)


def test_existing_fixed_revision_survives_builtin_change_until_explicit_resave(tmp_path):
    base = tmp_path / 'default.yaml'
    # A saved Default-source revision containing the former stock placeholders.
    old = dict(proxies=[], **{'proxy-groups': [dict(name=countries.COUNTRY_MAPPING[code]['group'],
               type='select', proxies=['DIRECT']) for code in STATIC_CODES]}, rules=['MATCH,DIRECT'])
    base.write_text(yaml.serialize_yaml(old))
    store = fixed.FixedSubscriptions(tmp_path / 'state')
    config = dict(yaml_source='default', batch_nodes=rows('US'), aux_nodes=[], node_overrides={}, special_groups=[])
    nodes = parsed(config['batch_nodes'])
    entry = store.save(None, 'Synthetic', 'synthetic', config, nodes, base)
    slug = store.slug(entry)
    original = {name: store._content(entry, name) for name in ('base.yaml', 'current.yaml')}
    revision = entry['revision']
    base.write_bytes(DEFAULT.read_bytes())
    assert store.get(entry['id'])['revision'] == revision
    assert {name: store._content(entry, name) for name in original} == original
    assert store.resolve(slug) == original['current.yaml']
    assert store.get(entry['id'])['revision'] == revision
    edited = store.save(entry['id'], 'Synthetic', 'synthetic', config, nodes, base)
    assert store.slug(edited) == slug
    assert store._content(edited, 'base.yaml') == DEFAULT.read_bytes()
    current = yaml.load_yaml_text(store._content(edited, 'current.yaml').decode())
    assert_countries(current, nodes)
    assert len(current['rules']) == 10410
    created = store.save(None, 'New Synthetic', 'new-synthetic', config, nodes, base)
    assert store._content(created, 'base.yaml') == DEFAULT.read_bytes()
    assert_countries(yaml.load_yaml_text(store._content(created, 'current.yaml').decode()), nodes)
