"""Freeze-specific privacy, migration and deployed-module regression gates."""
import ast
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import warnings

import pytest
from ruamel.yaml import YAML

from conftest import ROOT, LINK
from core import parser, yaml_utils, node_health
from core.state import write_json
from test_deployment import deployment
from test_fixed_subscriptions import base, store, save
from test_external_sources import external_save, remote, response
from test_auto_refresh import clock
from test_parser import vmess
from test_trojan_protocol import TROJAN, yaml_bytes
from test_ss_protocol import SS, PASSWORD


@pytest.mark.parametrize('function', ['parse_vmess_link', 'parse_vless_link'])
def test_legacy_parser_ast_identical_to_stable(function):
    old=subprocess.check_output(['git','show','v1.2.1:core/parser.py'],cwd=ROOT).decode()
    def definition(text):
        return ast.dump(next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name==function),include_attributes=False)
    assert definition(old)==definition((ROOT/'core/parser.py').read_text())


@pytest.mark.parametrize('uri', [vmess(),LINK,TROJAN,SS])
@pytest.mark.parametrize('mutation', [lambda x:x.upper(),lambda x:x.replace('://',':/'),
    lambda x:'https://example.invalid/'+x,lambda x:x.replace('://','%3A//')])
def test_dispatch_rejects_case_partial_and_confused_schemes(uri,mutation):
    result=parser.parse_batch_nodes(mutation(uri))
    assert not result['nodes'] and result['errors']
    public=json.dumps(result['preview'],ensure_ascii=False)
    assert PASSWORD.strip() not in public and 'TEST_ONLY_uuid' not in public


@pytest.mark.parametrize('version', [1,2,3,4,5,6])
def test_fixed_v1_v6_readonly_then_mutation_preserves_identity(store,base,version):
    entry=save(store,base);data=json.loads(store.path.read_bytes());row=data['subscriptions'][entry['id']]
    data['version']=version
    if version<6:row.pop('country_detection')
    if version<5:row.pop('health_policy');row.pop('health_policy_audit')
    if version<4:row.pop('policy_config')
    if version==1:row.pop('sources')
    write_json(store.path,data)
    before=store.path.read_bytes();slug=store.slug(entry)
    current=store.snapshot(entry['id'])
    assert store.path.read_bytes()==before
    loaded=store.get(entry['id'])
    assert loaded['token']==entry['token'] and loaded['revision']==entry['revision'] and store.slug(loaded)==slug
    assert loaded['country_detection']=={'geoip':'off'} and loaded['health_policy']['mode']=='off'
    assert store.resolve(slug)==current[1]
    assert json.loads(store.path.read_bytes())['version']==version
    store.action(entry['id'],'disable')
    assert json.loads(store.path.read_bytes())['version']==6
    loaded=store.get(entry['id'])
    assert loaded['token']==entry['token'] and loaded['revision']==entry['revision'] and store.slug(loaded)==slug
    assert store.snapshot(entry['id'])[1]==current[1]


@pytest.mark.parametrize('text', ['%YAML 1.1\n---\nx: 123456789e8\n',
    'a: &TEST_ONLY_PRIVATE_ANCHOR 1\nb: &TEST_ONLY_PRIVATE_ANCHOR 2\n'])
def test_committed_yaml_warning_isolation_concurrent_and_scalar_compatible(text):
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter('always');filters=list(warnings.filters)
        original=yaml_utils.get_yaml_engine().constructor.yaml_constructors['tag:yaml.org,2002:float']
        expected=yaml_utils.get_yaml_engine().load(text)
        assert records # Unrelated dependency/application raw engine still warns.
        records.clear()
        def load(_):return yaml_utils.serialize_yaml(yaml_utils.load_yaml_text(text))
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(load,range(16)))
        assert not records and warnings.filters==filters
        assert len(set(results))==1 and YAML(typ='safe').load(results[0])==expected
        assert yaml_utils.get_yaml_engine().constructor.yaml_constructors['tag:yaml.org,2002:float'] is original


def test_health_yaml_warning_private_and_four_protocol_probe_configs(tmp_path):
    nodes=parser.parse_batch_nodes('US|VM|'+vmess()+'\nJP|VL|'+LINK+'\nSG|TJ|'+TROJAN+'\nTW|SS|'+SS)['nodes']
    payload=yaml_bytes(nodes)
    extracted=node_health.extract(payload,include_config=True)
    assert [n['protocol'] for n in extracted]==['vmess','vless','trojan','ss']
    assert [n['config'] for n in extracted]==nodes
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter('always')
        node_health.extract(b'%YAML 1.1\n---\nproxies: [{type: ss, name: Test, server: example.com, port: 443, cipher: aes-256-gcm, password: 123456789e8}]')
        assert not records
    public=json.dumps(node_health.extract(payload),ensure_ascii=False)
    assert PASSWORD.strip() not in public and 'password' not in public and 'uuid' not in public


@pytest.mark.parametrize('bad', ['unsupported', 'plugin', 'parse', 'network'])
def test_mixed_refresh_failures_keep_last_good(store,base,response,clock,bad):
    mixed=(vmess(ps='US-VM')+'\n'+LINK+'#London-VL\n'+TROJAN+'#Tokyo-TJ\n'+SS+'#Singapore-SS').encode()
    response['payload']=mixed
    entry=external_save(store,base,sources=[remote(refresh_interval_seconds=900)],clock=clock)
    slug=store.slug(entry);good=store.snapshot(entry['id'])[1];item=entry['sources'][1]
    cache=store._payload(entry,item['id'])
    if bad=='network':response['error']='connection'
    else:response['payload']=mixed+b'\n'+{'unsupported':b'tuic://TEST_ONLY@example.com',
        'plugin':(SS+'?plugin=TEST_ONLY_exec').encode(),'parse':b'ss://invalid'}[bad]
    clock.now=item['next_refresh_at']
    from core import auto_refresh
    assert auto_refresh.run_once(store,base,clock)==0
    current=store.get(entry['id'])
    assert store.slug(current)==slug
    assert store.snapshot(entry['id'])[1]==good and store._payload(current,item['id'])==cache
    assert current['sources'][1]['using_cache'] and current['sources'][1]['consecutive_failures']==1
    assert current['sources'][1]['next_refresh_at']==clock.now+300


def test_v121_update_preserves_runtime_and_copies_new_core_modules(deployment,response):
    from core.security import AuthStore
    from core.fixed_subscriptions import FixedSubscriptions
    from core.node_health import NodeHealth
    from core.proxy_health import ProxyHealth
    from core.notifications import Notifications
    from core.temporary_links import TemporaryLinks
    from core.install_info import make_install_info
    from core.version import read_version
    installed,incoming,service,events,env,run=deployment
    state=installed/'state';AuthStore(state).initialize({'APP_PASSWORD':'TEST_ONLY_operator'})
    (installed/'VERSION').write_text('1.2.1\n') # Explicit historical source fixture, not current-version expectation.
    identity=make_install_info('stable','1.2.1','f62bf50721e3ac00d5d2a2a9f784ede4b79b49cf','v1.2.1')
    (installed/'INSTALLATION.json').write_text(json.dumps(identity))
    version=read_version(ROOT/'VERSION')
    metadata=incoming.parent/'incoming-main.json'
    metadata.write_text(json.dumps(make_install_info('main',version,'b'*40,None)))
    env['CLASH_DEPLOY_METADATA']=str(metadata)
    fixed=FixedSubscriptions(state)
    entry=external_save(fixed,incoming/'defaults/default.yaml',sources=[remote(refresh_interval_seconds=900)])
    NodeHealth(fixed).settings(entry['id'],'automatic',900)
    ProxyHealth(fixed).settings(entry['id'],'automatic',True,interval_seconds=900)
    Notifications(state).save(False,{k:True for k in ('source_refresh','endpoint_health','proxy_health','scheduler')},token='123456789:'+'A'*35,chat='-123456789')
    TemporaryLinks(state).create('TEST_ONLY.yaml',lifetime=86400)
    (state/'geoip').mkdir(mode=0o700);(state/'geoip/active.mmdb').write_bytes(b'TEST_ONLY_operator_mmdb')
    (state/'settings.json').write_bytes(b'TEST_ONLY_paired_metadata')
    (installed/'HTTPS_DEPLOYMENT.json').write_bytes(b'TEST_ONLY_unmanaged_metadata')
    for p in state.rglob('*'):
        if p.is_file():p.chmod(0o600)
    before={p.relative_to(installed):p.read_bytes() for folder in ['state','uploads','outputs','backups','logs','defaults'] for p in (installed/folder).rglob('*') if p.is_file()}
    auth=state/'auth.json';old_auth=auth.read_bytes();slug=fixed.slug(entry)
    env_before=(installed/'.env').read_bytes()
    result=run();assert result.returncode==0,result.stdout+result.stderr
    assert all((installed/p).read_bytes()==raw for p,raw in before.items())
    assert auth.read_bytes()==old_auth and fixed.slug(fixed.get(entry['id']))==slug
    assert (installed/'HTTPS_DEPLOYMENT.json').read_bytes()==b'TEST_ONLY_unmanaged_metadata'
    for name in ['yaml_diff.py','node_update.py']:assert (installed/'core'/name).read_bytes()==(incoming/'core'/name).read_bytes()
    assert json.loads((installed/'INSTALLATION.json').read_text())['base_version']==version
    backup=next(installed.parent.glob('upgrade-backup-*'))
    assert (backup/'.env').read_bytes()==env_before and json.loads((backup/'INSTALLATION.json').read_text())==identity
    assert all((backup/p).read_bytes()==raw for p,raw in before.items() if str(p).startswith(('state/','defaults/')))
    assert all(word not in events.read_text() for word in ('certbot','nginx','telegram','auto_refresh --once','auto_health --once'))


def mixed_payload(name):
    from urllib.parse import quote
    fragment=quote(name,safe='')
    return (vmess(ps=name+'-VM')+'\n'+LINK+'#'+fragment+'-VL\n'+TROJAN+'#'+fragment+'-TJ\n'+SS+'#'+fragment+'-SS').encode()


@pytest.mark.parametrize('mode', ['before', 'after'])
def test_mixed_refresh_atomic_commit_failure(store,base,response,clock,monkeypatch,mode):
    from test_auto_refresh import test_auto_atomic_commit_failure_preserves_revision_and_cache as check
    response['payload']=mixed_payload('Tokyo-remote')
    check(store,base,response,clock,monkeypatch,mode)
    entry=store.list()[0]
    assert store._payload(entry,entry['sources'][1]['id'])==response['payload']
    types={node['type'] for node in YAML(typ='safe').load(store.resolve(store.slug(entry)))['proxies']}
    assert types=={'vmess','vless','trojan','ss'}


@pytest.mark.parametrize('mutation', ['read','edit','disable','regenerate','delete','source-disable'])
def test_mixed_refresh_revision_recheck_outside_lock(store,base,response,clock,monkeypatch,mutation,caplog):
    import test_auto_refresh as audit
    response['payload']=mixed_payload('Tokyo-remote')
    monkeypatch.setattr(audit,'payload',mixed_payload)
    audit.test_auto_fetch_outside_lock_discards_stale_candidate(store,base,response,clock,monkeypatch,mutation,caplog)


def test_empty_source_error_uses_current_protocol_neutral_text():
    from core.source_errors import SourceError
    assert str(SourceError('empty'))=='No supported nodes'
