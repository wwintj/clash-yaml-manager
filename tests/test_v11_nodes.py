import json
from pathlib import Path
import pytest
from core.countries import COMMON, COUNTRIES, COUNTRY_MAPPING, detect_country
from core.parser import parse_batch_nodes
from core.yaml_utils import load_yaml, process_yaml_config
from conftest import LINK, post
from test_parser import vmess


@pytest.mark.parametrize('name,code', [('USA 01','US'),('United States','US'),('America','US'),('美国','US'),
 ('Los Angeles','US'),('LA','US'),('Tokyo-01','JP'),('JP01','JP'),('🇯🇵 node','JP'),('Japan','JP'),('东京','JP'),
 ('Taipei','TW'),('Taiwan','TW'),('台北','TW'),('Singapore','SG'),('狮城','SG'),('Korea','KR'),
 ('South Korea','KR'),('SouthKorea','KR'),('首尔','KR'),('Seoul','KR'),('Hong Kong','HK'),('UK','GB'),
 ('Frankfurt','DE'),('Paris','FR'),('Amsterdam','NL'),('in a tunnel','UNKNOWN'),('no limit','UNKNOWN'),
 ('at home','UNKNOWN'),('superfast','UNKNOWN'),('Japan US','UNKNOWN'),('🇺🇸🇯🇵 mixed','UNKNOWN')])
def test_country_detection(name, code):
    assert detect_country(name) == code


def test_complete_unified_country_data():
    assert len(COUNTRIES) == 249
    assert list(COUNTRIES)[:16] == COMMON
    for code, country in COUNTRIES.items():
        assert len(code) == 2 and code.isupper()
        assert all(country[k] for k in ('english','chinese','emoji','group'))
        assert country is COUNTRY_MAPPING[code]
        assert detect_country(country['english']) == code
        assert detect_country(country['chinese']) == code
        parsed = parse_batch_nodes(code + '|node|' + LINK)
        assert not parsed['errors'] and parsed['countries'][0]['code'] == code


def test_mixed_formats_remark_and_unknown():
    result = parse_batch_nodes('US|Tokyo|' + LINK + '\nTaipei|' + LINK + '\n' + LINK + '#Tokyo-01\n' + vmess(ps='Seoul') + '\n' + LINK)
    assert not result['errors']
    assert [c['code'] for c in result['countries']] == ['US','TW','JP','KR','UNKNOWN']
    assert result['preview'][-1]['name'] == 'Node-05'
    assert result['preview'][-1]['status'] == 'Warning'
    assert result['preview'][0]['source'] == 'Manual'
    assert '11111111-' not in json.dumps(result['preview'])
    assert 'vless://' not in json.dumps(result['preview'])
    assert 'example.com' not in json.dumps(result['preview'])


def test_overrides_survive_reorder_but_not_changed_uri():
    text = 'Tokyo|' + LINK
    initial = parse_batch_nodes(text)
    key = initial['preview'][0]['key']
    overrides = {key: {'country':'TW', 'name':'My manual node'}}
    changed = parse_batch_nodes('US|Other|' + LINK + '\n' + text, overrides)
    assert changed['preview'][1]['country'] == 'TW'
    assert changed['preview'][1]['source'] == 'Manual'
    assert changed['preview'][1]['name'] == 'My manual node'
    assert parse_batch_nodes(text.replace('example.com','other.example'), overrides)['preview'][0]['country'] == 'JP'


def test_duplicate_names_error_and_edit_repair():
    text = 'Tokyo|' + LINK + '\nTokyo|' + LINK
    initial = parse_batch_nodes(text)
    assert initial['preview'][-1]['status'] == 'Error'
    fixed = parse_batch_nodes(text, {initial['preview'][-1]['key']: {'name':'Tokyo two'}})
    assert not fixed['errors']


def test_only_present_countries_create_groups(tmp_path):
    source = tmp_path / 'source.yaml'; source.write_text('rules: [MATCH,DIRECT]\n')
    for name in ('outputs','backups'): (tmp_path/name).mkdir()
    parsed = parse_batch_nodes('TW|node|' + LINK + '\n' + LINK)
    result = process_yaml_config(str(source), str(tmp_path/'outputs'), str(tmp_path/'backups'), parsed['nodes'], parsed['countries'])
    assert result['success'], result['errors']
    groups = {g['name'] for g in load_yaml(result['output_path'])['proxy-groups']}
    assert '🇹🇼 台湾节点' in groups and '🌐 其他节点' in groups
    assert '🇯🇵 日本节点' not in groups and len(groups) < 10


def test_parse_api_and_latest_generate(web, logged_in):
    rows = json.dumps([{'country':'DE','name':'Aux','link':LINK}])
    response = post(logged_in, '/parse-nodes', {'batch_nodes':LINK, 'aux_nodes':rows})
    assert response.status_code == 200
    preview = response.json['nodes']
    assert [r['status'] for r in preview] == ['Warning','Ready']
    assert 'uuid' not in response.get_data(as_text=True)
    override = {preview[0]['key']:{'country':'TW', 'name':'Manual'}}
    # Generate sees the newly added JP line, not only the previous preview.
    post(logged_in, '/process', {'batch_nodes': LINK + '\nTokyo|' + LINK, 'aux_nodes':rows,
                                 'node_overrides':json.dumps(override)})
    with logged_in.session_transaction() as session: context = session['page_context']
    assert context['result']['new_node_count'] == 3
    data = load_yaml(str(Path(web.DIR_OUTPUTS)/context['output_filename']))
    assert [n['name'] for n in data['proxies']] == ['🇹🇼 Manual','🇯🇵 Tokyo','🇩🇪 Aux']


@pytest.mark.parametrize('data', [{'aux_nodes':'[1]'}, {'node_overrides':'{"bad":{"country":null}}'},
                                 {'batch_nodes':'US|bad|vless://private@host:99999'}])
def test_parse_errors_block_generate(web, logged_in, data):
    post(logged_in, '/process', data)
    assert not list(Path(web.DIR_OUTPUTS).iterdir())
    with logged_in.session_transaction() as session: assert session['page_context']['error_messages']


def test_preview_auth_and_csrf(client, logged_in):
    assert logged_in.post('/parse-nodes').status_code == 400
    post(logged_in, '/logout')
    assert post(client, '/parse-nodes', {'batch_nodes':LINK}).status_code == 302


def test_preview_hides_credentials_in_remark():
    secret = '11111111-1111-4111-8111-111111111111'
    parsed = parse_batch_nodes(vmess(ps='Tokyo ' + secret + ' vless://private@host:443'))
    preview = json.dumps(parsed['preview'])
    assert secret not in preview and 'private@host' not in preview
    assert parsed['nodes'][0]['name'].startswith('🇯🇵 Tokyo')
