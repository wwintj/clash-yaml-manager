from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from core import yaml_utils as y
from conftest import ROOT


def process(tmp_path, node, source, **kwargs):
    path = tmp_path / 'input.yaml'
    path.write_text(source, encoding='utf-8')
    return y.process_yaml_config(str(path), str(tmp_path / 'outputs'), str(tmp_path / 'backups'),
                                 [node], [{'node_name': node['name'], 'group': '🇺🇸 美国节点'}], **kwargs)


def test_replace_preserves_configuration(tmp_path, node):
    source = '''# original header
dns: {enable: true, nameserver: ["1.1.1.1"]} # dns comment
hosts: {"example.com": "192.0.2.1"}
tun: {enable: false}
sniffer: {enable: false}
profile: {store-selected: true}
experimental: {custom: 'quoted'}
geodata-mode: true
x-user: {anything: 'kept'}
proxy-providers: {provider: {type: file, path: './provider.yaml'}}
rule-providers: {ruleset: {type: file, behavior: domain, path: './rules.yaml'}}
proxies: [{name: old, type: vmess, server: old.example, port: 443, uuid: old}]
proxy-groups:
  - name: custom
    type: select
    proxies: [old, DIRECT, REJECT]
  - name: provider-group
    type: select
    use: [provider]
rules:
  - 'RULE-SET,ruleset,custom'
  - 'MATCH,DIRECT'
'''
    result = process(tmp_path, node, source, special_groups=['special', 'special'])
    assert result['success'], result['errors']
    output = y.load_yaml(result['output_path'])
    original = y.load_yaml(str(tmp_path / 'input.yaml'))
    for key in original:
        if key not in ('proxies', 'proxy-groups'):
            assert output[key] == original[key]
    assert output['proxies'] == [node]
    groups = {g['name']: g for g in output['proxy-groups']}
    assert groups['custom']['proxies'] == ['DIRECT', 'REJECT']
    assert groups['special']['proxies'] == [node['name']]
    assert groups['🇺🇸 美国节点']['proxies'] == [node['name']]
    assert groups['provider-group']['use'] == ['provider']
    assert len(groups) == len(output['proxy-groups'])
    text = Path(result['output_path']).read_text()
    for fragment in ('# original header', '# dns comment', '"1.1.1.1"', "'quoted'"):
        assert fragment in text
    assert Path(result['backup_path']).read_bytes() == (tmp_path / 'input.yaml').read_bytes()
    for filename in ('backup_path', 'output_path'):
        assert Path(result[filename]).stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('kind', ['select', 'url-test', 'fallback', 'load-balance'])
def test_empty_group_filled_preserving_settings(tmp_path, node, kind):
    result = process(tmp_path, node, f'''proxy-groups:
  - name: special
    type: {kind}
    proxies: []
    url: https://example.com/check
    interval: 123
    tolerance: 50
    lazy: false
    filter: abc
''', special_groups=['special'])
    assert result['success'], result['errors']
    group = y.load_yaml(result['output_path'])['proxy-groups'][0]
    assert group['type'] == kind and group['interval'] == 123
    assert group['url'] == 'https://example.com/check' and group['tolerance'] == 50
    assert group['lazy'] is False and group['filter'] == 'abc'
    assert group['proxies'] == [node['name']]


def test_invalid_proxy_reference(tmp_path, node):
    result = process(tmp_path, node, 'proxy-groups: [{name: bad, type: select, proxies: [missing]}]')
    assert not result['success'] and result['errors']
    assert not list((tmp_path / 'outputs').glob('*.yaml'))


def test_real_default_full_roundtrip(tmp_path, node):
    source = ROOT / 'defaults/default.yaml'
    before = source.read_bytes()
    result = y.process_yaml_config(str(source), str(tmp_path / 'outputs'), str(tmp_path / 'backups'),
                                   [node], [{'node_name': node['name'], 'group': '🇺🇸 美国节点'}])
    assert result['success'], result['errors']
    original, output = y.load_yaml(str(source)), y.load_yaml(result['output_path'])
    assert len(original['rules']) > 10000
    for key in original:
        if key not in ('proxies', 'proxy-groups'):
            assert output[key] == original[key]
    assert not y.validate_proxy_references(output)
    assert source.read_bytes() == before


@pytest.mark.p0
@pytest.mark.parametrize('source', ['[]', 'proxies: invalid', 'proxy-groups: invalid',
                                  'proxy-groups: [invalid]', 'proxy-groups: [{name: g, proxies: invalid}]'])
def test_malformed_structure_not_silently_discarded(tmp_path, node, source):
    result = process(tmp_path, node, source)
    assert not result['success'] and result['errors']


@pytest.mark.p0
@pytest.mark.parametrize('source', ['password: [private-password-value\n',
                                  'password: private-password-value: invalid\n',
                                  'password: private-password-value\npassword: duplicate\n'])
def test_yaml_exception_has_no_source_secrets(tmp_path, node, source):
    result = process(tmp_path, node, source)
    assert not result['success']
    assert 'private-password-value' not in str(result['errors'])


@pytest.mark.p0
def test_duplicate_groups_cannot_discard_settings(tmp_path, node):
    result = process(tmp_path, node, '''proxy-groups:
  - {name: duplicate, type: select, proxies: [DIRECT]}
  - {name: duplicate, type: fallback, proxies: [REJECT], interval: 300}
''')
    assert not result['success'] and result['errors']


@pytest.mark.p0
def test_rules_targeting_removed_node_block_output(tmp_path, node):
    result = process(tmp_path, node, '''proxies: [{name: old}]
rules: ['DOMAIN,example.com,old', 'MATCH,DIRECT']
''')
    assert not result['success'] and result['errors']


@pytest.mark.p0
def test_match_flag_correction(tmp_path, node):
    result = process(tmp_path, node, '''proxy-groups: [{name: '🇨🇳 台湾节点', type: select, proxies: [DIRECT]}]
rules: ['MATCH,🇨🇳 台湾节点']
''')
    assert result['success'], result['errors']
    assert y.load_yaml(result['output_path'])['rules'] == ['MATCH,🇹🇼 台湾节点']


@pytest.mark.p0
def test_concurrent_output_cannot_overwrite(tmp_path, monkeypatch):
    # Force both writers to select the same initial filename.
    original = y.generate_output_filename
    barrier = Barrier(2)
    calls = []
    def race(directory):
        name = original(directory)
        calls.append(name)
        if len(calls) <= 2:
            barrier.wait(timeout=10)
            return 'tim_20260925_1_AAAAAAAAAAAAAAAAAAAAAA.yaml'
        return name
    monkeypatch.setattr(y, 'generate_output_filename', race)
    sources = []
    for i in range(2):
        path = tmp_path / f'input{i}.yaml'
        path.write_text(f'x-owner: {i}\n')
        sources.append(str(path))
    def run(source):
        return y.process_yaml_config(source, str(tmp_path / 'outputs'), str(tmp_path / 'backups'),
                                     [dict(name='test', type='vless', server='example.com', port=443, uuid='id')], [])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, sources))
    assert all(r['success'] for r in results), results
    assert len({r['output_path'] for r in results}) == 2
    assert {y.load_yaml(r['output_path'])['x-owner'] for r in results} == {0, 1}


@pytest.mark.parametrize('kind', ['select', 'url-test', 'fallback', 'load-balance'])
def test_empty_group_after_old_node_cleanup(tmp_path, node, kind):
    result = process(tmp_path, node, f'''proxies: [{{name: old}}]
proxy-groups: [{{name: empty, type: {kind}, proxies: [old]}}]
''')
    assert result['success'], result['errors']
    group = y.load_yaml(result['output_path'])['proxy-groups'][0]
    assert group['type'] == kind
    assert group['proxies'] == (['🚀 手动切换'] if kind == 'select' else [node['name']])


@pytest.mark.parametrize('flag', ['include-all', 'include-all-proxies', 'include-all-providers'])
def test_dynamic_provider_groups_not_filled(tmp_path, node, flag):
    result = process(tmp_path, node, f'''proxy-providers: {{remote: {{type: file, path: ./provider.yaml}}}}
proxy-groups: [{{name: dynamic, type: select, {flag}: true, filter: HK}}]
''')
    assert result['success'], result['errors']
    group = y.load_yaml(result['output_path'])['proxy-groups'][0]
    assert group[flag] is True and group['filter'] == 'HK' and not group['proxies']


@pytest.mark.parametrize('field,value', [('name', []), ('server', {}), ('port', True), ('uuid', ''), ('type', None)])
def test_invalid_new_nodes_rejected_without_writes(tmp_path, node, field, value):
    node[field] = value
    result = process(tmp_path, node, '{}')
    assert not result['success'] and result['errors']
    assert not (tmp_path / 'outputs').exists()
    assert not (tmp_path / 'backups').exists()


def test_failed_serialization_never_publishes_partial_yaml(tmp_path, monkeypatch):
    class BrokenEngine:
        def dump(self, data, target):
            target.write('secret partial content')
            raise OSError('private-password-value')
    monkeypatch.setattr(y, 'get_yaml_engine', BrokenEngine)
    output = tmp_path / 'existing.yaml'
    output.write_text('original')
    with pytest.raises(OSError):
        y.save_yaml({}, str(output))
    assert output.read_text() == 'original'
    with pytest.raises(OSError):
        y.save_new_output({}, str(tmp_path))
    assert list(tmp_path.iterdir()) == [output]


def test_retained_group_comments_and_quotes(tmp_path, node):
    result = process(tmp_path, node, '''proxies: [{name: old}]
proxy-groups:
  # custom group comment
  - name: 'custom'
    type: select
    proxies:
      - old
      - "DIRECT" # keep item comment
''')
    assert result['success'], result['errors']
    text = Path(result['output_path']).read_text()
    assert '# custom group comment' in text
    assert '"DIRECT" # keep item comment' in text


def test_backup_age_starts_when_created(tmp_path):
    import os
    import time
    source = tmp_path / 'old-default.yaml'
    source.write_text('{}')
    os.utime(source, (time.time() - 30 * 86400,) * 2)
    path = y.backup_yaml(str(source), str(tmp_path / 'backups'))
    assert time.time() - Path(path).stat().st_mtime < 5
