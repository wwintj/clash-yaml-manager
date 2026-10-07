"""Explicit source profiles, deterministic selectors and committed-revision flows."""
import copy
import hashlib
from pathlib import Path
import socket

import pytest

from conftest import LINK, post
from core import generator, health_policy, policy_engine, yaml_utils as yaml
from core.node_identity import fingerprint
from test_default_country_groups import DEFAULT, LINKS, SPECIAL, parsed, rows
from test_external_sources import external_save, payload, remote, response, uploaded
from test_fixed_subscriptions import store
from test_health_policy_lifecycle import scenario, check_three
from test_health_policy import settings, observation, NOW
from test_policy_engine import config as policies
from test_yaml_diff import apply_diff, body, fields

US = '🇺🇸 美国节点'
SG = '🇸🇬 狮城节点'
DE = '🇩🇪 德国节点'
FR = '🇫🇷 法国节点'
CA = '🇨🇦 加拿大节点'
AU = '🇦🇺 澳大利亚节点'
UNKNOWN = '🌐 其他节点'
PRIMARY = '🚀 节点选择'
MANUAL = '🚀 手动切换'
DIGEST = 'bc24dc51c528f7410c7e566f91c82883d2a2574ae3b359847e7ecfd854190576'


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Selector projection must not cause DNS or network work')
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


@pytest.fixture
def base(tmp_path):
    path = tmp_path / 'installed-default.yaml'
    path.write_bytes(DEFAULT.read_bytes())
    return path


def groups(data):
    return {group['name']: group for group in data['proxy-groups']}


def generate(tmp_path, nodes, *, profile='default', source=DEFAULT, mode='replace', special=(), policy=None, transform=None):
    kwargs = {} if profile is None else {'template_profile': profile}
    result = generator.generate(source, tmp_path / 'out', tmp_path / 'backup', nodes,
                                list(special), policy, transform, node_update_mode=mode, **kwargs)
    assert result['success'], result['errors']
    data = yaml.load_yaml(result['output_path'])
    assert not yaml.validate_proxy_references(data)
    return data, Path(result['output_path']).read_bytes()


def assert_primary(data, names, country_refs, profile='default'):
    expected = names + country_refs + [MANUAL, 'DIRECT'] if profile == 'default' else [MANUAL, 'DIRECT'] + names
    assert groups(data)[PRIMARY]['proxies'] == expected
    assert len(expected) == len(set(expected))
    assert groups(data)[MANUAL]['proxies'] == names


@pytest.mark.parametrize('codes,refs', [
    (('US', 'SG', 'DE'), [US, SG, DE]),
    (('US', 'US', 'SG', 'DE'), [US, SG, DE]),
    (('US', 'US', 'FR', 'US', 'CA'), [US, FR, CA]),
    (('AU', 'UNKNOWN', 'DE', 'FR', 'CA', 'SG', 'US'), [AU, UNKNOWN, DE, FR, CA, SG, US])])
@pytest.mark.parametrize('mode', ['replace', 'merge'])
@pytest.mark.parametrize('kind', policy_engine.TYPES)
def test_default_exact_four_layers_country_first_seen_policy_and_rules(tmp_path, codes, refs, mode, kind):
    nodes = parsed(rows(*codes))
    data, raw = generate(tmp_path, nodes, mode=mode, policy=policies(kind))
    assert_primary(data, nodes['node_names'], refs)
    assert [p['name'] for p in data['proxies']] == nodes['node_names']
    for name in refs:
        expected = [info['node_name'] for info in nodes['countries'] if info['group'] == name]
        assert groups(data)[name]['proxies'] == expected
        assert groups(data)[name]['type'] == ('select' if kind == 'preserve' else kind)
    # Projection changes only the primary selector after the existing engine.
    before = yaml.transform_yaml_config(yaml.load_yaml(str(DEFAULT)), nodes['nodes'], nodes['countries'],
                                       policy_config=policies(kind), node_update_mode=mode)
    assert before['success'], before['errors']
    for name, group in groups(before['data']).items():
        if name != PRIMARY:
            assert groups(data)[name] == group
    assert len(data['rules']) == 10410
    assert raw.split(b'rules:\n', 1)[1] == DEFAULT.read_bytes().split(b'rules:\n', 1)[1]
    assert hashlib.sha256(DEFAULT.read_bytes()).hexdigest() == DIGEST


@pytest.mark.parametrize('profile', [None, 'custom', 'default'])
@pytest.mark.parametrize('filename', ['default.yaml', 'opaque-upload.yaml'])
def test_profile_is_explicit_not_inferred_from_path_hash_or_identical_content(tmp_path, profile, filename):
    path = tmp_path / filename
    path.write_bytes(DEFAULT.read_bytes())
    nodes = parsed(rows('US', 'SG', 'DE'))
    data, _ = generate(tmp_path, nodes, profile=profile, source=path)
    assert_primary(data, nodes['node_names'], [US, SG, DE], profile or 'custom')


def test_country_assignment_metadata_order_does_not_override_real_node_order(tmp_path):
    nodes = parsed(rows('SG', 'US', 'SG', 'DE'))
    nodes['countries'].reverse()
    data, _ = generate(tmp_path, nodes)
    assert_primary(data, nodes['node_names'], [SG, US, DE])
    assert groups(data)[SG]['proxies'] == nodes['node_names'][2::-2]


def test_projection_deduplicates_preexisting_primary_refs():
    nodes = parsed(rows('US', 'US', 'SG'))
    data = yaml.load_yaml(str(DEFAULT))
    groups(data)[PRIMARY]['proxies'].extend([MANUAL, 'DIRECT', MANUAL])
    result = yaml.transform_yaml_config(data, nodes['nodes'], nodes['countries'], template_profile='default')
    assert result['success'], result['errors']
    assert_primary(result['data'], nodes['node_names'], [US, SG])


@pytest.mark.parametrize('profile', [None, '', 'DEFAULT', True, [], {}])
def test_invalid_explicit_profile_rejected_before_backup_or_output(tmp_path, profile):
    nodes = parsed(rows('US'))
    result = generator.generate(DEFAULT, tmp_path / 'out', tmp_path / 'backup', nodes, [], template_profile=profile)
    assert not result['success'] and result['errors'] == ['Template profile is invalid.']
    assert not (tmp_path / 'out').exists() and not (tmp_path / 'backup').exists()


@pytest.mark.parametrize('name', [MANUAL, PRIMARY, 'DIRECT', US])
def test_default_name_collision_still_rejected_without_published_output(tmp_path, name):
    nodes = parsed(rows('US'))
    nodes['nodes'][0]['name'] = name
    nodes['countries'][0]['node_name'] = name
    result = generator.generate(DEFAULT, tmp_path / 'out', tmp_path / 'backup', nodes, [], template_profile='default')
    assert not result['success'] and result['errors']
    assert not list((tmp_path / 'out').glob('*.yaml'))


@pytest.mark.parametrize('kind', policy_engine.TYPES)
def test_projection_runs_after_health_and_preserves_every_other_group(tmp_path, kind):
    nodes = parsed('\n'.join(
        f'{code}|Node-{i}|'+LINK.replace('example.com', f'node-{i}.example')
        for i, code in enumerate(('US', 'US', 'US', 'SG'))))
    policy = policies(kind, kind)
    health = dict(available=True, records={fingerprint(nodes['nodes'][1]): observation()})
    captured = {}
    def transform(data):
        assert groups(data)[PRIMARY]['proxies'][:2] == [MANUAL, 'DIRECT']
        captured['audit'] = health_policy.apply(data, nodes['nodes'], nodes['countries'], SPECIAL,
                                              policy, settings(), health, NOW)
        captured['groups'] = copy.deepcopy(groups(data))
    data, _ = generate(tmp_path, nodes, special=SPECIAL, policy=policy, transform=transform)
    assert_primary(data, nodes['node_names'], [US, SG])
    assert {k:v for k,v in groups(data).items() if k != PRIMARY} == {
        k:v for k,v in captured['groups'].items() if k != PRIMARY}
    if kind in policy_engine.AUTOMATIC:
        assert groups(data)[US]['proxies'] == [nodes['node_names'][0], nodes['node_names'][2]]
        assert captured['audit']['groups_filtered'] == 9
    else:
        assert groups(data)[US]['proxies'] == nodes['node_names'][:3]
    assert groups(data)['🐟 漏网之鱼']['proxies'] == ['🚀 节点选择', 'DIRECT', MANUAL] + nodes['node_names']


@pytest.mark.parametrize('protocol', list(LINKS))
@pytest.mark.parametrize('mode', ['replace', 'merge'])
def test_five_protocols_use_default_primary_projection(tmp_path, protocol, mode):
    nodes = parsed('US|Protocol|'+LINKS[protocol])
    data, _ = generate(tmp_path, nodes, mode=mode)
    assert data['proxies'][0]['type'] == protocol
    assert_primary(data, nodes['node_names'], [US])


@pytest.mark.parametrize('source', ['default', 'custom'])
@pytest.mark.parametrize('mode', ['replace', 'merge'])
def test_http_preview_generate_bytes_and_file_selection_overrides_spoofed_profile(web, logged_in, source, mode):
    values = fields(source, batch=rows('US', 'SG', 'DE'))
    values.update(node_update_mode=mode, template_profile='custom' if source == 'default' else 'default')
    stock = DEFAULT.read_text()
    response = post(logged_in, '/api/preview-yaml-diff', body(values, stock))
    assert response.status_code == 200, response.json
    expected = apply_diff(stock, response.json['diff']).encode()
    assert post(logged_in, '/process', body(values, stock)).status_code == 302
    with logged_in.session_transaction() as session:
        context = session['page_context']
    assert not context['error_messages']
    raw = Path(web.DIR_OUTPUTS, context['output_filename']).read_bytes()
    assert raw == expected and logged_in.get(context['download_url']).data == expected
    nodes = parsed(values['batch_nodes'])
    assert_primary(yaml.load_yaml_text(raw.decode()), nodes['node_names'], [US, SG, DE], source)


@pytest.mark.parametrize('profile', ['default', 'custom'])
def test_fixed_create_save_and_token_regenerate_preserve_source_contract(store, base, profile):
    config = dict(yaml_source=profile, batch_nodes=rows('US', 'SG', 'DE'), aux_nodes=[], node_overrides={}, special_groups=[])
    nodes = parsed(config['batch_nodes'])
    entry = store.save(None, 'Synthetic', 'synthetic', config, nodes, base,
                       base.read_bytes() if profile == 'custom' else None)
    slug = store.slug(entry)
    assert_primary(yaml.load_yaml_text(store._content(entry, 'current.yaml').decode()), nodes['node_names'], [US, SG, DE], profile)
    config['batch_nodes'] = rows('FR', 'US', 'FR', 'AU')
    nodes = parsed(config['batch_nodes'])
    saved = store.save(entry['id'], 'Synthetic', 'synthetic', config, nodes, base)
    assert store.slug(saved) == slug and saved['token'] == entry['token']
    assert_primary(yaml.load_yaml_text(store._content(saved, 'current.yaml').decode()), nodes['node_names'], [FR, US, AU], profile)
    previous = store._content(saved, 'current.yaml')
    rotated = store.action(entry['id'], 'regenerate')
    # Existing Regenerate is token rotation, not YAML regeneration.
    assert rotated['revision'] == saved['revision']
    assert store._content(rotated, 'current.yaml') == previous
    assert rotated['token'] != saved['token'] and store.resolve(slug) is None


def test_existing_committed_fixed_revision_is_not_rewritten_until_explicit_save(store, base, monkeypatch):
    config = dict(yaml_source='default', batch_nodes=rows('US', 'SG', 'DE'), aux_nodes=[], node_overrides={}, special_groups=[])
    nodes = parsed(config['batch_nodes'])
    original = generator.generate
    def legacy(*args, **kwargs):
        kwargs.pop('template_profile', None)
        return original(*args, **kwargs)
    with monkeypatch.context() as injection:
        injection.setattr(generator, 'generate', legacy)
        entry = store.save(None, 'Legacy synthetic', 'legacy-synthetic', config, nodes, base)
    before = store.path.read_bytes()
    old = store.snapshot(entry['id'])
    assert_primary(yaml.load_yaml_text(old[1].decode()), nodes['node_names'], [], 'custom')
    assert store.list()[0]['revision'] == entry['revision']
    assert store.get(entry['id']) == old[0] and store.snapshot(entry['id']) == old
    assert store.path.read_bytes() == before
    rotated = store.action(entry['id'], 'regenerate')
    assert rotated['revision'] == entry['revision'] and store._content(rotated, 'current.yaml') == old[1]
    saved = store.save(entry['id'], 'Legacy synthetic', 'legacy-synthetic', config, nodes, base)
    assert saved['token'] == rotated['token']
    assert_primary(yaml.load_yaml_text(store._content(saved, 'current.yaml').decode()), nodes['node_names'], [US, SG, DE])


@pytest.mark.parametrize('profile', ['default', 'custom'])
def test_fixed_external_aggregate_remote_refresh_and_cached_generation(store, base, response, profile):
    config = dict(yaml_source=profile, batch_nodes='US|Manual|'+LINK, aux_nodes=[], node_overrides={}, special_groups=[])
    response['payload'] = payload('Singapore-R1', 'US-R2')
    entry = external_save(store, base, config=config, custom=base.read_bytes() if profile == 'custom' else None,
                          sources=[remote(), uploaded()], uploads={1:payload('Germany-U1')})
    slug = store.slug(entry)
    def check(entry, names, refs):
        data = yaml.load_yaml_text(store._content(entry, 'current.yaml').decode())
        assert [node['name'] for node in data['proxies']] == names
        assert_primary(data, names, refs, profile)
        assert store.slug(entry) == slug
    check(entry, ['🇺🇸 Manual', '🇸🇬 Singapore-R1', '🇺🇸 US-R2', '🇩🇪 Germany-U1'], [US, SG, DE])
    response['payload'] = payload('France-R1', 'Australia-R2')
    entry = store.source_action(entry['id'], 'refresh', base, entry['sources'][1]['id'])
    names = ['🇺🇸 Manual', '🇫🇷 France-R1', '🇦🇺 Australia-R2', '🇩🇪 Germany-U1']
    check(entry, names, [US, FR, AU, DE])
    entry = store.refresh_sources(entry, {entry['sources'][1]['id']}, base)
    check(entry, names, [US, FR, AU, DE])
    calls = len(response['calls'])
    entry = store.save(entry['id'], entry['name'], entry['prefix'], config, parsed(config['batch_nodes']),
                       None, expected=entry, _cached=True)
    check(entry, names, [US, FR, AU, DE])
    assert len(response['calls']) == calls


@pytest.mark.parametrize('profile', ['default', 'custom'])
@pytest.mark.parametrize('kind', policy_engine.AUTOMATIC)
def test_fixed_health_reconciliation_preserves_primary_and_filtered_automatic_group(store, base, scenario, profile, kind):
    config = copy.deepcopy(scenario['fields'])
    config.update(yaml_source=profile, policy_config=policies(kind, 'select'))
    entry = store.save(scenario['entry']['id'], 'Health policy', 'health-policy', config,
                       parsed(config['batch_nodes']), base, base.read_bytes() if profile == 'custom' else None,
                       clock=lambda:scenario['now'])
    scenario['fields'] = config
    slug = store.slug(entry)
    check_three(scenario)
    entry = store.get(entry['id'])
    data = yaml.load_yaml_text(store._content(entry, 'current.yaml').decode())
    names = ['🇺🇸 A', '🇺🇸 B', '🇺🇸 C', '🇺🇸 D']
    assert_primary(data, names, [US], profile)
    assert groups(data)[US]['type'] == kind
    assert groups(data)[US]['proxies'] == ['🇺🇸 A', '🇺🇸 C', '🇺🇸 D']
    assert groups(data)['media']['proxies'] == names
    assert store.slug(entry) == slug and entry['health_policy_audit']['candidates_excluded'] == 1
    calls = len(scenario['calls'])
    health_bytes = scenario['worker'].path.read_bytes()
    scenario['now'] += 172801
    assert store.reconcile_health_policy(entry['id'], clock=lambda:scenario['now']) == 'updated'
    restored = store.get(entry['id'])
    data = yaml.load_yaml_text(store._content(restored, 'current.yaml').decode())
    assert_primary(data, names, [US], profile)
    assert groups(data)[US]['proxies'] == names and store.slug(restored) == slug
    assert len(scenario['calls']) == calls and scenario['worker'].path.read_bytes() == health_bytes


def test_custom_merge_keeps_authoritative_selector_refs_and_source_objects():
    source = """proxies:
  - {name: Existing-A, type: vendor-proxy, x-opaque: retained}
  - {name: Existing-B, type: vless, server: old.example, port: 443, uuid: TEST_ONLY}
proxy-groups:
  - {name: '🚀 节点选择', type: select, proxies: [Existing-A, DIRECT, Existing-B]}
  - {name: '🚀 手动切换', type: select, proxies: [Existing-B, Existing-A]}
  - {name: '🐟 漏网之鱼', type: select, proxies: [Existing-A]}
rules: ['MATCH,Existing-A']
"""
    data = yaml.load_yaml_text(source)
    objects = list(data['proxies'])
    before = copy.deepcopy(data)
    nodes = parsed('US|New-1|'+LINK+'\nDE|New-2|'+LINK)
    result = yaml.transform_yaml_config(data, nodes['nodes'], nodes['countries'],
                                       node_update_mode='merge', template_profile='custom')
    assert result['success'], result['errors']
    assert groups(data)[PRIMARY]['proxies'] == ['Existing-A', 'DIRECT', 'Existing-B'] + nodes['node_names']
    assert groups(data)[MANUAL]['proxies'] == ['Existing-B', 'Existing-A'] + nodes['node_names']
    assert data['proxies'] == before['proxies'] + nodes['nodes']
    assert all(data['proxies'][i] is node for i, node in enumerate(objects))
    assert [g['name'] for g in data['proxy-groups']][:3] == [PRIMARY, MANUAL, '🐟 漏网之鱼']
    assert data['rules'] == before['rules'] and not yaml.validate_proxy_references(data)
