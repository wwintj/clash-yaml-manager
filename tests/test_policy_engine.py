"""Pinned schema and pure transformations; approved Custom and Default goldens."""
import hashlib
from pathlib import Path
import socket

import pytest
from werkzeug.datastructures import MultiDict

from core import policy_engine as policy, yaml_utils as yaml
from conftest import ROOT

FIXTURES = ROOT / 'tests/fixtures/policy'


def config(country='preserve', special='preserve', **options):
    value = policy.defaults()
    value['country_groups'] = dict(type=country, options=options)
    value['special_groups']['type'] = special
    return value


def nodes():
    return [dict(name=n, type='vless', server='example.com', port=443,
                 uuid='11111111-1111-4111-8111-111111111111')
            for n in ['TW-A', 'TW-B', 'US-with-TW-name', 'SG-A']]


def countries():
    return [dict(node_name=n['name'], group=g) for n, g in zip(nodes(),
            ['🇹🇼 台湾节点', '🇹🇼 台湾节点', '🇺🇸 美国节点', '🇸🇬 新加坡节点'])]


def generate(tmp_path, value=None, path=None, members=None, assignments=None, special=None):
    result = yaml.process_yaml_config(str(path or FIXTURES/'base.yaml'), str(tmp_path/'output'),
        str(tmp_path/'backup'), nodes() if members is None else members,
        countries() if assignments is None else assignments,
        ['media'] if special is None else special, value)
    return result


def groups(result):
    assert result['success'], result['errors']
    data = yaml.load_yaml(result['output_path'])
    return {g['name']: g for g in data['proxy-groups']}


@pytest.mark.parametrize('path', ['custom', 'default'])
@pytest.mark.parametrize('explicit', [False, True])
def test_preserve_custom_golden_and_current_default_10410_rules(tmp_path, path, explicit):
    original = FIXTURES/'base.yaml' if path == 'custom' else ROOT/'defaults/default.yaml'
    before = original.read_bytes()
    result = generate(tmp_path, policy.defaults() if explicit else None, original)
    assert result['success'], result['errors']
    output = Path(result['output_path']).read_bytes()
    if path == 'custom':
        assert output == (FIXTURES/'preserve.yaml').read_bytes()
    else:
        assert hashlib.sha256(output).hexdigest() == (FIXTURES/'preserve-default.sha256').read_text().strip()
        assert result['rule_count'] == 10410
        assert hashlib.sha256(before).hexdigest() == 'bc24dc51c528f7410c7e566f91c82883d2a2574ae3b359847e7ecfd854190576'
    assert original.read_bytes() == before


@pytest.mark.parametrize('kind', policy.TYPES)
def test_types_membership_custom_metadata_scope_and_unselected_groups(tmp_path, kind):
    result = generate(tmp_path, config(kind, kind))
    current = groups(result)
    original = groups(generate(tmp_path/'preserve', policy.defaults()))
    for name in ['unrelated', 'provider', '🇯🇵 日本节点', '🚀 手动切换', '🚀 节点选择', '🐟 漏网之鱼']:
        assert current[name] == original[name]
    targets = {'🇹🇼 台湾节点':['TW-A','TW-B'], '🇺🇸 美国节点':['US-with-TW-name'],
               '🇸🇬 新加坡节点':['SG-A'], 'media':[n['name'] for n in nodes()]}
    for name, refs in targets.items():
        group = current[name]
        if kind == 'preserve':
            assert group == original[name]
            continue
        assert group['type'] == kind
        assert group.get('icon') == original[name].get('icon')
        assert group.get('x-note') == original[name].get('x-note')
        if kind == 'select':
            assert group['proxies'] == original[name]['proxies']
            assert not set(policy.AUTO_FIELDS) & set(group)
        else:
            assert group['proxies'] == refs
            assert not set(policy.CANDIDATE_FIELDS) & set(group)
            assert {key:group[key] for key in policy.option_defaults(kind)} == policy.option_defaults(kind)
            assert ('tolerance' in group) == (kind == 'url-test')
            assert ('strategy' in group) == (kind == 'load-balance')
    assert yaml.load_yaml(result['output_path'])['rules'] == ['MATCH,media']


@pytest.mark.parametrize('kind', policy.AUTOMATIC)
def test_dynamic_membership_removed_but_unrelated_metadata_retained(tmp_path, kind):
    path = tmp_path/'custom.yaml'
    path.write_text('''proxy-groups:
- {name: media, type: url-test, proxies: [DIRECT], use: [p], include-all: true, include-all-proxies: true, include-all-providers: true, filter: JP, exclude-filter: US, exclude-type: vless, empty-fallback: DIRECT, timeout: 7, max-failed-times: 8, expected-status: '200', tolerance: 2, strategy: consistent-hashing, icon: kept, hidden: true, disable-udp: true, x-custom: retained}
proxy-providers: {p: {type: file, path: ./p.yaml}}
''')
    group = groups(generate(tmp_path, config('preserve', kind), path))['media']
    assert group['proxies'] == [n['name'] for n in nodes()]
    assert not set(policy.CANDIDATE_FIELDS) & set(group)
    assert not {'timeout','max-failed-times','expected-status'} & set(group)
    assert group['icon']=='kept' and group['hidden'] is True and group['disable-udp'] is True and group['x-custom']=='retained'


@pytest.mark.parametrize('kind', policy.AUTOMATIC)
def test_one_candidate_is_valid_and_zero_selected_special_fails(tmp_path, kind):
    group = groups(generate(tmp_path, config(kind, kind), members=nodes()[:1], assignments=countries()[:1]))['🇹🇼 台湾节点']
    assert group['proxies'] == ['TW-A']
    empty = generate(tmp_path/'empty', config(kind, kind), members=[], assignments=[])
    assert not empty['success'] and empty['output_path']==''
    assert not list((tmp_path/'empty'/'output').glob('*.yaml'))


def test_no_country_assignment_means_no_managed_country(tmp_path):
    result = generate(tmp_path, config('url-test'), assignments=[])
    group = groups(result)['🇹🇼 台湾节点']
    assert group['url']=='http://client.local/check' and group['interval']==123 and group['proxies']==['DIRECT']


@pytest.mark.parametrize('bad', [None, [], True, 'url-test', {}, {'country_groups':{}},
    dict(policy.defaults(), extra={}),
    dict(policy.defaults(), country_groups=dict(type='unknown', options={})),
    dict(policy.defaults(), country_groups=dict(type=3, options={})),
    dict(policy.defaults(), country_groups=dict(type='preserve', options={'url':'http://x'})),
    dict(policy.defaults(), country_groups=dict(type='select', options={'interval':300})),
    dict(policy.defaults(), country_groups=dict(type='url-test', options=[], extra=True)),
    dict(policy.defaults(), country_groups=dict(type='url-test', options={'weight':1})),
    dict(policy.defaults(), country_groups=dict(type='fallback', options={'tolerance':50})),
    dict(policy.defaults(), country_groups=dict(type='load-balance', options={'strategy':'consistent-hashing'})),
    dict(policy.defaults(), country_groups=dict(type='url-test', options={'strategy':'round-robin'}))])
def test_strict_schema(bad):
    with pytest.raises(policy.PolicyError): policy.normalize(bad)


@pytest.mark.parametrize('key,bad', [('interval',n) for n in [True,False,'300',300.0,0,-1,29,86401,10**30,float('nan'),float('inf'),None,{}]] +
    [('tolerance',n) for n in [True,False,'50',50.0,-1,10001,10**30,float('nan'),float('inf'),None,[]]] +
    [('lazy',n) for n in ['true',1,0,None,{},[]]])
def test_exact_scalar_types_and_bounds(key, bad):
    with pytest.raises(policy.PolicyError): policy.normalize(config('url-test', **{key:bad}))


@pytest.mark.parametrize('value', ['', None, 1, 'ftp://host/check', 'file:///x', 'javascript:alert(1)',
    'https://user:PRIVATE@host/x', 'https://user@host/x', 'https:///x', 'https://host:99999/x',
    'https://host:bad/x', 'https://[bad/x', 'https://host/\nx', 'https://host/\rx', 'https://host/\tx',
    ' https://host/x', 'https://host/white space', 'https://host/\x7fx', 'https://host/%0Dx',
    'https://host\\@other/x', 'http://'+'a'*2048])
def test_client_url_rejection_never_echoes_input(value):
    with pytest.raises(policy.PolicyError) as error: policy.normalize(config('url-test', url=value))
    assert str(error.value)==policy.MESSAGE


@pytest.mark.parametrize('value', ['http://localhost/check', 'http://127.0.0.1:80/check',
    'https://192.168.1.2/check', 'http://[::1]/check', 'https://client.local/generate_204',
    'https://example.com/check?q=hello%20world', 'HTTPS://example.com/check'])
def test_client_private_local_http_https_urls_without_dns(value, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('Policy must not use network')
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(socket, 'socket', forbidden)
    assert policy.normalize(config('url-test',url=value))['country_groups']['options']['url']==value


@pytest.mark.parametrize('interval,tolerance', [(30,0),(86400,10000)])
def test_boundary_values(interval,tolerance):
    value=policy.normalize(config('url-test', interval=interval,tolerance=tolerance,lazy=False))
    assert value['country_groups']['options']['interval']==interval
    assert value['country_groups']['options']['tolerance']==tolerance


@pytest.mark.parametrize('fields', [dict(policy_country_groups_type='unknown'),
    dict(policy_country_groups_type='fallback',policy_country_groups_tolerance='50'),
    dict(policy_country_groups_type='preserve',policy_country_groups_url='http://x'),
    dict(policy_country_groups_type='url-test',policy_country_groups_interval='300.0'),
    dict(policy_country_groups_type='url-test',policy_country_groups_interval='-1'),
    dict(policy_country_groups_type='url-test',policy_country_groups_lazy='1'),
    dict(policy_extra='PRIVATE'), dict(policy_country_groups_options='{}')])
def test_form_cannot_coerce_or_ignore_invalid_fields(fields):
    with pytest.raises(policy.PolicyError):policy.parse_form(fields)


def test_duplicate_form_values_rejected():
    with pytest.raises(policy.PolicyError):policy.parse_form(MultiDict([('policy_country_groups_type','select'),('policy_country_groups_type','fallback')]))


def test_generation_no_network_health_reads_or_probe(tmp_path, monkeypatch):
    from core import source_fetch, node_probe
    import urllib.request
    import subprocess
    def forbidden(*args, **kwargs):raise AssertionError('Policy must not probe or fetch')
    for module,key in [(socket,'getaddrinfo'),(socket,'socket'),(urllib.request,'urlopen'),
                       (source_fetch,'fetch'),(node_probe,'probe'),(subprocess,'Popen')]:
        monkeypatch.setattr(module,key,forbidden)
    # Deliberately unusable auxiliary health files; ordinary generation ignores them.
    (tmp_path/'node_health.json').write_text('{broken')
    (tmp_path/'proxy_health.json').write_text('{broken')
    result=generate(tmp_path,config('fallback','load-balance',url='http://127.0.0.1/check'))
    assert result['success'],result['errors']
    assert groups(result)['🇹🇼 台湾节点']['proxies']==['TW-A','TW-B']


def test_selected_general_groups_remain_manual_and_overlap_is_explicit_special(tmp_path):
    result=generate(tmp_path,config('url-test','fallback'),special=['🚀 手动切换','🇹🇼 台湾节点'])
    current=groups(result)
    assert current['🚀 手动切换']['type']=='select'
    assert current['🇹🇼 台湾节点']['type']=='fallback'
    assert current['🇹🇼 台湾节点']['proxies']==[node['name'] for node in nodes()]
