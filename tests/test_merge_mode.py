"""Generate-only Merge preserves source topology and the exact preview contract."""
import copy
import hashlib
import io
import re
from pathlib import Path

import pytest
from ruamel.yaml.comments import CommentedSeq
from werkzeug.datastructures import MultiDict

from conftest import LINK, ROOT, post
from core import generator, node_update, policy_engine, yaml_diff, yaml_utils as yaml
from test_yaml_diff import apply_diff, fields, body, APPROVED_HASHES, SOURCE, ROUTE, snapshot, token

BASE = (ROOT/'tests/fixtures/merge/base.yaml').read_text()


def parsed():
    return generator.parse_form_nodes({'batch_nodes':'US|new-c|'+LINK+'\nTW|new-d|'+LINK})


def transform(source=BASE, mode='merge', policy=None, special=('media',)):
    nodes=parsed()
    return yaml.transform_yaml_config(yaml.load_yaml_text(source),nodes['nodes'],nodes['countries'],
                                      list(special),policy,node_update_mode=mode)


@pytest.mark.parametrize('count',[0,1,3])
def test_merge_preserves_source_order_and_appends_submitted_order(count):
    data={'proxies':[{'name':f'old-{i}','type':'vendor-proxy','x-opaque':i} for i in range(count)]}
    existing=data['proxies'];old=copy.deepcopy(existing);nodes=parsed()
    result=yaml.transform_yaml_config(data,nodes['nodes'],nodes['countries'],node_update_mode='merge')
    assert result['success'],result['errors']
    assert data['proxies'] is existing and data['proxies']==old+nodes['nodes']
    assert result['old_node_count']==count and result['new_node_count']==2


@pytest.mark.parametrize('kind',policy_engine.TYPES)
def test_merge_policy_only_explicit_automatic_managed_candidates_rebuilt(kind):
    policy={scope:dict(type=kind,options={}) for scope in policy_engine.SCOPES}
    result=transform(policy=policy);assert result['success'],result['errors']
    data=result['data'];original=yaml.load_yaml_text(BASE)
    assert data['proxies'][:6]==original['proxies']
    names=[n['name'] for n in parsed()['nodes']]
    groups={g['name']:g for g in data['proxy-groups']}
    before={g['name']:g for g in original['proxy-groups']}
    # Existing topology is not repopulated from all available source nodes.
    for name in ['Manual','unselected','provider','🇯🇵 日本节点']:
        assert groups[name]==before[name]
    for name in yaml.GENERAL_GROUPS:
        assert groups[name]['proxies']==list(before[name]['proxies'])+names
        assert groups[name]['type']=='select'
    for name,submitted in [('media',names),('🇺🇸 美国节点',names[:1]),('🇹🇼 台湾节点',names[1:])]:
        group=groups[name];previous=before.get(name,{'type':'select','proxies':[]})
        if kind in policy_engine.AUTOMATIC:
            assert group['proxies']==submitted and group['type']==kind
        else:
            assert group['proxies']==list(previous['proxies'])+submitted
            assert group['type']==(previous['type'] if kind=='preserve' else 'select')
        if name=='media':assert group['icon']=='kept' and group['x-note']=='retained'
    assert groups['empty-select']['proxies']==['🚀 手动切换']
    assert groups['empty-auto']['proxies']==names # Not the six unrelated source nodes.


def test_ruamel_existing_objects_quotes_comments_anchors_and_unrelated_keys_preserved():
    data=yaml.load_yaml_text(BASE);original=yaml.load_yaml_text(BASE)
    sequence=data['proxies'];objects=list(sequence);nodes=parsed()
    result=yaml.transform_yaml_config(data,nodes['nodes'],nodes['countries'],['media'],node_update_mode='merge')
    assert result['success'],result['errors']
    assert isinstance(sequence,CommentedSeq) and data['proxies'] is sequence
    assert all(data['proxies'][i] is obj for i,obj in enumerate(objects))
    assert list(objects[0])==list(original['proxies'][0])
    assert data['x-node-copy'] is objects[0] and objects[0].anchor.value=='old_a'
    text=yaml.serialize_yaml(data)
    for fragment in ['# old node sequence comment','# old node name comment','# retained reference comment',
                     '# original manual topology','# group name comment','name: "old-a"',
                     "password: 'TEST_ONLY_NOT_A_CREDENTIAL'",'&old_a','*old_a','<<: *connection']:
        assert fragment in text
    for key in original:
        if key not in ('proxies','proxy-groups'):assert data[key]==original[key]
    restored=yaml.load_yaml_text(text)
    assert restored['proxies'][:6]==original['proxies']
    assert [p['type'] for p in restored['proxies'][:6]]==['trojan','ss','hysteria2','wireguard','vendor-proxy','vless']
    assert not yaml.validate_proxy_references(restored)


@pytest.mark.parametrize('rule',['MATCH,old-a','DOMAIN,example.com,old-a','IP-CIDR,192.0.2.0/24,old-a,no-resolve'])
def test_existing_rule_target_merge_valid_replace_guard_unchanged(rule):
    source='proxies: [{name: old-a, type: trojan}]\nrules: ["'+rule+'"]\n'
    merged=transform(source);assert merged['success'],merged['errors']
    assert merged['data']['rules']==[rule]
    replaced=transform(source,'replace')
    assert not replaced['success'] and '被替换的旧节点' in ' '.join(replaced['errors'])


def test_existing_proxy_named_like_flag_correction_keeps_refs_and_rules():
    source="proxies: [{name: '🇨🇳 台湾节点', type: ss}]\nproxy-groups: [{name: Manual, proxies: ['🇨🇳 台湾节点']}]\nrules: ['MATCH,🇨🇳 台湾节点']\n"
    result=transform(source);assert result['success'],result['errors']
    assert result['data']['proxy-groups'][0]['proxies']==['🇨🇳 台湾节点']
    assert result['data']['rules']==['MATCH,🇨🇳 台湾节点']


@pytest.mark.parametrize('name',['🇺🇸 美国节点','🚀 节点选择','media'])
def test_preserved_proxy_cannot_be_ambiguously_named_like_added_managed_group(name):
    source='proxies: [{name: "'+name+'", type: trojan}]\n'
    result=transform(source)
    assert not result['success'] and result['errors']==['Source node name conflicts with a proxy group.']


@pytest.mark.parametrize('kind',['existing','group','builtin','duplicate','new-country-group'])
def test_collision_rejected_without_output_and_preview_matches(web,logged_in,kind,caplog):
    values=fields();values['node_update_mode']='merge';source=SOURCE
    if kind=='existing':source=source.replace('name: old','name: 🇺🇸 Test')
    if kind=='group':source=source.replace('name: custom','name: 🇺🇸 Test')
    if kind=='duplicate':values['batch_nodes']+='\n'+values['batch_nodes']
    if kind in ('builtin','new-country-group'):
        # The parser adds flags; raw core inputs exercise exact reserved names.
        nodes=parsed();name='DIRECT' if kind=='builtin' else '🇺🇸 美国节点'
        nodes['nodes'][0]['name']=name;nodes['countries'][0]['node_name']=name
        result=yaml.transform_yaml_config(yaml.load_yaml_text(SOURCE),nodes['nodes'],nodes['countries'],node_update_mode='merge')
        assert not result['success'] and '策略组' in ' '.join(result['errors'])
        return
    preview=post(logged_in,ROUTE,body(values,source));assert preview.status_code==400
    actual=post(logged_in,'/process',body(values,source));assert actual.status_code==400
    from core.ui import display_message
    assert display_message(preview.json['error']) in actual.text
    if kind=='existing':assert preview.json['error']=='Node name already exists in source YAML.'
    assert not list(Path(web.DIR_OUTPUTS).iterdir()) and LINK not in caplog.text


@pytest.mark.parametrize('mode',['','MERGE',' merge','merge ','overwrite','PRIVATE<script>',None,True,{},[]])
def test_mode_strict_core_validation_without_backups(tmp_path,mode):
    with pytest.raises(node_update.ModeError,match='Node Update Mode is invalid'):
        node_update.normalize(mode)
    source=tmp_path/'source.yaml';source.write_text(BASE);nodes=parsed()
    result=generator.generate(source,tmp_path/'out',tmp_path/'backup',nodes,[],node_update_mode=mode)
    assert not result['success'] and result['errors']==[node_update.MESSAGE]
    assert not (tmp_path/'out').exists() and not (tmp_path/'backup').exists()


@pytest.mark.parametrize('mode',['','MERGE','overwrite','PRIVATE<script>'])
@pytest.mark.parametrize('route',[ROUTE,'/process'])
def test_invalid_mode_safe_400_before_source_or_output(web,logged_in,mode,route):
    values=fields();values['node_update_mode']=mode
    before=snapshot(web)
    response=post(logged_in,route,body(values))
    assert response.status_code==400 and node_update.MESSAGE in response.text
    assert 'PRIVATE<script>' not in response.text and snapshot(web)==before


def test_missing_mode_replace_and_duplicate_values_rejected():
    assert node_update.parse_form({})=='replace'
    assert node_update.parse_form({'node_update_mode':'merge'})=='merge'
    for values in [('replace','merge'),('merge','merge')]:
        with pytest.raises(node_update.ModeError):
            node_update.parse_form(MultiDict([('node_update_mode',v) for v in values]))


@pytest.mark.parametrize('route',[ROUTE,'/process'])
def test_http_duplicate_mode_rejected(web,logged_in,route):
    values=MultiDict(fields());values.add('node_update_mode','replace');values.add('node_update_mode','merge')
    values.add('csrf_token',token(logged_in));values.add('yaml_file',(io.BytesIO(SOURCE.encode()),'custom.yaml'))
    response=logged_in.post(route,data=values)
    assert response.status_code==400 and node_update.MESSAGE in response.text
    assert not list(Path(web.DIR_OUTPUTS).iterdir())


@pytest.mark.parametrize('route',[ROUTE,'/process'])
def test_invalid_mode_without_other_form_fields_is_400(logged_in,route):
    response=post(logged_in,route,{'node_update_mode':'INVALID'})
    assert response.status_code==400 and node_update.MESSAGE in response.text


@pytest.mark.parametrize('mode',[None,'replace'])
def test_replace_legacy_rejection_redirect_remains_compatible(logged_in,mode):
    values={'batch_nodes':'not a valid URI'}
    if mode:values['node_update_mode']=mode
    response=post(logged_in,'/process',values)
    assert response.status_code==302


@pytest.mark.parametrize('source',['custom','default'])
@pytest.mark.parametrize('mode',[None,'replace'])
def test_replace_approved_output_sha_and_cleanup_unchanged(web,logged_in,source,mode):
    values=fields(source)
    if mode is not None:values['node_update_mode']=mode
    response=post(logged_in,'/process',body(values));assert response.status_code==302
    with logged_in.session_transaction() as session:context=session['page_context']
    raw=Path(web.DIR_OUTPUTS,context['output_filename']).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==APPROVED_HASHES[source]
    data=yaml.load_yaml_text(raw.decode())
    assert [p['name'] for p in data['proxies']]==['🇺🇸 Test']
    assert all('old' not in g['proxies'] for g in data['proxy-groups'])


@pytest.mark.parametrize('source',['custom','default'])
def test_merge_rich_http_exact_backup_temp_url_private_output(web,logged_in,source):
    # The isolated default copy has nodes: the actual repository template stays intact.
    if source=='default':Path(web.DEFAULT_YAML_PATH).write_text(BASE)
    values=fields(source,batch='US|new-c|'+LINK+'\nTW|new-d|'+LINK)
    values.update(node_update_mode='merge',special_groups=['media'])
    preview=post(logged_in,ROUTE,body(values,BASE));assert preview.status_code==200
    assert not list(Path(web.DIR_OUTPUTS).iterdir()) and not list(Path(web.DIR_BACKUPS).iterdir())
    response=post(logged_in,'/process',body(values,BASE));assert response.status_code==302
    with logged_in.session_transaction() as session:context=session['page_context']
    output=Path(web.DIR_OUTPUTS,context['output_filename'])
    assert re.fullmatch(r'tim_\d{8}_\d+_[A-Za-z0-9_-]{22}\.yaml',output.name)
    assert output.stat().st_mode & 0o777==0o600
    assert output.read_bytes()==apply_diff(BASE,preview.json['diff']).encode()
    backup=list(Path(web.DIR_BACKUPS).glob('*.yaml'));assert len(backup)==1
    assert backup[0].read_bytes()==BASE.encode() and backup[0].stat().st_mode & 0o777==0o600
    assert '/t/' in context['download_url']
    assert logged_in.get(context['download_url']).data==output.read_bytes()
    assert logged_in.get(context['file_download_url']).headers['Content-Disposition'].startswith('attachment')
    assert context['result']['old_node_count']==6 and context['result']['new_node_count']==2


def test_fixed_ignores_generate_merge_option_and_still_replaces(web,logged_in):
    values=fields();values.update(name='Fixed stays Replace',prefix='',node_update_mode='merge')
    response=post(logged_in,'/fixed-subscriptions/new',body(values));assert response.status_code==303
    entry=web.fixed_subscriptions.list()[0]
    assert 'node_update_mode' not in entry
    data=yaml.load_yaml_text(logged_in.get('/s/'+web.fixed_subscriptions.slug(entry)).text)
    assert [p['name'] for p in data['proxies']]==['🇺🇸 Test']
    page=logged_in.get('/fixed-subscriptions/'+entry['id']+'/edit').text
    assert 'node-update-mode' not in page


def test_merge_preview_uses_latest_input_after_parse_and_same_name_is_not_deduped(web,logged_in):
    values=fields();post(logged_in,'/parse-nodes',values)
    values.update(batch_nodes='US|Latest|'+LINK,node_update_mode='merge')
    preview=post(logged_in,ROUTE,body(values));assert preview.status_code==200
    generated=apply_diff(SOURCE,preview.json['diff'])
    assert '🇺🇸 Latest' in generated and '🇺🇸 Test' not in generated
    assert [p['name'] for p in yaml.load_yaml_text(generated)['proxies']]==['old','🇺🇸 Latest']
    # Feeding a merged output back with the same name is an explicit error.
    response=post(logged_in,ROUTE,body(values,generated))
    assert response.status_code==400 and response.json['error']=='Node name already exists in source YAML.'


def test_merge_result_budget_unchanged_and_counts_only_submitted_nodes(web,logged_in,monkeypatch):
    values=fields();values['node_update_mode']='merge'
    # Source nodes are not reclassified as newly submitted/limited nodes.
    source='proxies:\n'+''.join(f'  - {{name: old-{i}, type: vendor-proxy}}\n' for i in range(513))
    preview=post(logged_in,ROUTE,body(values,source));assert preview.status_code==200
    assert preview.json['summary']['old_node_count']==513 and preview.json['summary']['new_node_count']==1
    monkeypatch.setattr(yaml_diff,'MAX_YAML_BYTES',len(source.encode())+1)
    response=post(logged_in,ROUTE,body(values,source))
    assert response.status_code==400 and response.json['error']==yaml_diff.TOO_LARGE and 'diff' not in response.json
    assert post(logged_in,'/process',body(values,source)).status_code==302


def test_merge_never_deduplicates_by_connection_or_protocol():
    nodes=parsed();existing=dict(nodes['nodes'][0],name='same-connection-different-name')
    result=yaml.transform_yaml_config({'proxies':[existing]},nodes['nodes'],nodes['countries'],node_update_mode='merge')
    assert result['success'] and len(result['data']['proxies'])==3


@pytest.mark.parametrize('protocol',['tuic','hysteria','wireguard'])
def test_merge_does_not_add_new_input_protocols(web,logged_in,protocol):
    values=fields(batch=f'US|Unsupported|{protocol}://TEST_ONLY@example.com')
    values['node_update_mode']='merge'
    response=post(logged_in,ROUTE,body(values,BASE))
    assert response.status_code==400 and not response.json['ok']
