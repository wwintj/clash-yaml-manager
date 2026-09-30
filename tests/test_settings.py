"""Settings reads/composition and equivalent global mutations, using private tmp state."""
import copy
import io
import json
import re
import socket
import subprocess
from pathlib import Path

import pytest

from core import geoip_store, mihomo_probe, node_probe, source_fetch, settings_status
from core.mihomo_manager import ManagedMihomo
from core.proxy_health import DEFAULT_PROBE, ProxyHealth, ProxyHealthError
from core.state import file_lock, write_json
from conftest import post
from test_fixed_views import create
from test_geoip import readers
from test_mihomo_manager import managed
from test_proxy_health import public_resolver
from test_external_sources import response


ROUTE = '/settings/health/proxy-defaults'
NEW = dict(url='https://probe.example/new', expected_status=205, timeout_ms=5000)


def fields(value=NEW):
    return {'global_'+key: str(item) for key, item in value.items()}


def fixed_bytes(web):
    root = web.fixed_subscriptions.state
    paths = [web.fixed_subscriptions.path, root/'node_health.json', web.geoip_store.settings, web.geoip_store.path,
             Path(web.BASE_DIR)/'.env', Path(web.BASE_DIR)/'INSTALLATION.json']
    paths += list(web.fixed_subscriptions.directory.rglob('*'))
    return {str(path.relative_to(root.parent)): path.read_bytes() if path.exists() else None
            for path in paths if not path.is_dir() and path.suffix != '.lock'}


def seed_proxy(web, logged_in, monkeypatch):
    monkeypatch.setattr(source_fetch, '_resolve', public_resolver)
    monkeypatch.setattr(ManagedMihomo, 'status', lambda self, **kw: dict(status='COMPATIBLE',
        required='v1.19.31', installed='v1.19.31', architecture='amd64', cpu_level='v2',build='amd64-v2',preferred_build='amd64-v2'))
    monkeypatch.setattr(mihomo_probe, 'run', lambda binary,nodes,settings,state: {
        node['fingerprint']: dict(kind='success',error=None,latency_ms=31) for node in nodes})
    worker = web.proxy_health
    worker.clock = lambda: 1_800_000_000
    global_entry = create(web, logged_in)
    create(web, logged_in)
    custom_entry = next(entry for entry in web.fixed_subscriptions.list() if entry['id'] != global_entry['id'])
    worker.settings(global_entry['id'], 'automatic', True, interval_seconds=900)
    worker.settings(custom_entry['id'], 'automatic', False,
        dict(DEFAULT_PROBE, url='https://probe.example/custom'), interval_seconds=3600)
    worker.check(global_entry['id']); worker.check(custom_entry['id'])
    return global_entry, custom_entry


def test_workspace_sections_counts_no_read_time_writes(web, logged_in):
    first = create(web, logged_in); second = create(web, logged_in)
    web.fixed_subscriptions.action(second['id'], 'disable')
    before = fixed_bytes(web)
    response = logged_in.get('/settings')
    assert response.status_code == 200
    for section in ('overview', 'geoip', 'health', 'runtime'):
        assert f'id="{section}"'.encode() in response.data and f'href="#{section}"'.encode() in response.data
    assert b'data-fixed-count>2<' in response.data
    assert web.fixed_subscriptions.counts() == dict(total=2,active=1,disabled=1)
    assert fixed_bytes(web) == before and not web.proxy_health.path.exists()
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['Referrer-Policy'] == 'no-referrer'


@pytest.mark.parametrize('path', ['/settings/upload','/settings/remove',ROUTE])
def test_settings_auth_post_csrf_and_fresh_retry(web, logged_in, path):
    before = fixed_bytes(web)
    anonymous = web.app.test_client()
    assert anonymous.get('/settings').status_code == 302
    assert b'Runtime / Deployment' not in anonymous.get('/settings').data
    assert anonymous.post(path).status_code in (302,303)
    assert logged_in.get(path).status_code == 405
    rejected = logged_in.post(path, data=fields())
    assert rejected.status_code == 303 and rejected.location.endswith('/settings')
    assert fixed_bytes(web) == before and not web.proxy_health.path.exists()
    assert b'name="csrf_token"' in logged_in.get('/settings').data
    assert post(logged_in, ROUTE, fields(dict(NEW,url='https://8.8.8.8/new'))).status_code == 303


def test_routes_same_underlying_state_and_established_reset_semantics(web, logged_in, monkeypatch):
    global_entry, custom_entry = seed_proxy(web, logged_in, monkeypatch)
    worker = web.proxy_health; old = worker.path.read_bytes(); before = fixed_bytes(web)
    initial = json.loads(old); custom = copy.deepcopy(initial['subscriptions'][custom_entry['id']])
    response = post(logged_in, ROUTE, fields())
    assert response.status_code == 303 and response.location.endswith('/settings#health')
    settings_result = worker.path.read_bytes(); data = json.loads(settings_result)
    assert data['global'] == NEW
    reset = data['subscriptions'][global_entry['id']]
    assert reset['nodes'] == {} and reset['last_check_at'] is None
    assert reset['mode'] == 'automatic' and reset['interval_seconds'] == 900
    assert data['subscriptions'][custom_entry['id']] == custom
    assert fixed_bytes(web) == before
    worker.path.write_bytes(old)
    old_route = post(logged_in, '/fixed-subscriptions/proxy-health/defaults',
                     dict(fields(),subscription_id=global_entry['id']))
    assert old_route.status_code == 303 and old_route.location.endswith('/'+global_entry['id']+'/edit')
    assert worker.path.read_bytes() == settings_result and fixed_bytes(web) == before
    with logged_in.session_transaction() as session:
        assert NEW['url'] not in repr(dict(session))
    unchanged = worker.path.read_bytes()
    assert post(logged_in, ROUTE, fields()).status_code == 303
    assert worker.path.read_bytes() == unchanged  # Same values preserve observations/schedules.


@pytest.mark.parametrize('target', [
    'http://8.8.8.8/', 'https://127.0.0.1/', 'https://10.0.0.1/', 'https://[::1]/',
    'https://user:REJECTED_CREDENTIAL@8.8.8.8/', 'https://8.8.8.8/?REJECTED_QUERY',
    'https://8.8.8.8/#REJECTED_FRAGMENT', 'https://mixed.example/', 'file:///REJECTED_PATH',
])
def test_invalid_target_atomic_no_echo_log_or_other_mutation(web, logged_in, monkeypatch, target, caplog):
    seed_proxy(web, logged_in, monkeypatch)
    before = fixed_bytes(web); proxy = web.proxy_health.path.read_bytes()
    response = post(logged_in, ROUTE, fields(dict(NEW,url=target)))
    assert response.status_code == 400 and b'Previous defaults are unchanged' in response.data
    assert web.proxy_health.path.read_bytes() == proxy and fixed_bytes(web) == before
    assert target not in response.get_data(as_text=True) and target not in caplog.text
    assert 'REJECTED_' not in response.get_data(as_text=True) and 'REJECTED_' not in caplog.text
    assert post(logged_in, ROUTE, fields()).status_code == 303


@pytest.mark.parametrize('change', [dict(global_expected_status='bad'),dict(global_expected_status='99'),
    dict(global_expected_status='600'),dict(global_timeout_ms='2999'),dict(global_timeout_ms='15001'),dict(global_timeout_ms='NaN')])
def test_numeric_validation_owned_by_proxy_health(web, logged_in, monkeypatch, change):
    monkeypatch.setattr(source_fetch,'_resolve',public_resolver)
    before = fixed_bytes(web)
    response = post(logged_in, ROUTE, dict(fields(),**change))
    assert response.status_code == 400 and not web.proxy_health.path.exists() and fixed_bytes(web) == before


def test_fixed_canonical_form_cleanup_custom_controls_and_link(web, logged_in):
    entry = create(web, logged_in)
    response = logged_in.get('/fixed-subscriptions/'+entry['id']+'/edit')
    html = response.get_data(as_text=True)
    assert 'id="proxy-defaults"' not in html and 'name="global_url"' not in html
    assert 'id="global-proxy-summary"' in html and 'href="/settings#health"' in html
    for field in ('mode','scope','custom_url','custom_expected_status','custom_timeout_ms','interval_seconds'):
        assert 'name="'+field+'"' in html
    assert logged_in.get('/settings').data.count(b'id="proxy-defaults"') == 1


def test_get_forbids_network_subprocess_yaml_parsing_and_regeneration(web, logged_in, monkeypatch):
    create(web, logged_in); before = fixed_bytes(web); attempted = []
    def forbidden(*args, **kwargs):
        attempted.append(True)
        raise AssertionError('forbidden Settings side effect')
    for module, name in ((source_fetch,'fetch'),(source_fetch,'_resolve'),(socket,'getaddrinfo'),
        (socket,'gethostbyname'),(socket.socket,'connect'),(subprocess,'run'),(subprocess,'Popen'),
        (mihomo_probe,'run'),(node_probe,'probe')):
        monkeypatch.setattr(module,name,forbidden)
    for name in ('snapshot','_content','save','refresh_sources','reconcile_health_policy'):
        monkeypatch.setattr(web.fixed_subscriptions,name,forbidden)
    response = logged_in.get('/settings')
    assert response.status_code == 200 and attempted == [] and fixed_bytes(web) == before


@pytest.mark.parametrize('section', ['geoip','proxy','engine','fixed','runtime','install'])
def test_auxiliary_failures_are_isolated_and_secret_errors_hidden(web, logged_in, monkeypatch, section):
    def broken(*args,**kwargs): raise OSError('PRIVATE_EXCEPTION_PATH_PASSWORD')
    if section == 'geoip': monkeypatch.setattr(web.geoip_store,'status',broken)
    if section == 'proxy': monkeypatch.setattr(web.proxy_health,'global_settings',broken)
    if section == 'engine': monkeypatch.setattr(web.proxy_health.engine,'status',broken)
    if section == 'fixed': monkeypatch.setattr(web.fixed_subscriptions,'counts',broken)
    if section == 'runtime': monkeypatch.setattr(web.settings_status,'runtime',broken)
    if section == 'install': monkeypatch.setattr(web,'read_install_info',broken)
    response = logged_in.get('/settings')
    assert response.status_code == 200 and b'PRIVATE_EXCEPTION' not in response.data
    assert (b'Unavailable' in response.data or b'unavailable' in response.data or b'unknown' in response.data)
    assert b'id="geoip-file"' in response.data
    assert b'id="runtime"' in response.data and b'id="health"' in response.data


def test_busy_reads_do_not_block_other_sections(web, logged_in):
    for lock in (web.proxy_health.lock, web.fixed_subscriptions.lock):
        with file_lock(lock, strict=True):
            response = logged_in.get('/settings')
        assert response.status_code == 200 and b'id="geoip-file"' in response.data
        assert b'navailable' in response.data


def test_runtime_values_build_identity_and_secret_absence(web, logged_in, monkeypatch):
    entry = create(web, logged_in)
    root = Path(web.BASE_DIR)
    env_sentinel = 'ENV_CONTENT_SECRET_SENTINEL'
    (root/'.env').write_text('SECRET_KEY='+env_sentinel)
    auth_hash = json.loads((root/'state/auth.json').read_bytes())['password_hash']
    (root/'INSTALLATION.json').write_text(json.dumps(dict(channel='main',base_version='1.1.1',
        commit='a'*40,tag=None,installed_at='2026-09-30T00:00:00+00:00',source='github-main')))
    values = dict(APP_PORT=9012,COOKIE_SECURE=True,TRUST_PROXY_HEADERS=True,
        DOWNLOAD_BASE_URL='https://DOWNLOAD_CREDENTIAL_SENTINEL:password@private.example/PRIVATE_BASE_PATH',
        DOWNLOAD_URL_SCHEME='https',UPLOAD_RETENTION_SECONDS=7200,OUTPUT_RETENTION_SECONDS=10800,
        CLEANUP_INTERVAL_SECONDS=3600,BACKUP_RETENTION_SECONDS=604800)
    for name,value in values.items():monkeypatch.setattr(web,name,value)
    before = fixed_bytes(web); response = logged_in.get('/settings'); html = response.get_data(as_text=True)
    for value in ('9012','Enabled','Explicit base URL','Configured','7200 seconds','10800 seconds',
                  '3600 seconds','604800 seconds','30 days','1.1.1-dev+aaaaaaa','main'):
        assert value in html
    for value in (env_sentinel,auth_hash,entry['token'],web.SECRET_KEY,web.auth_store.path.read_text(),
                  'DOWNLOAD_CREDENTIAL_SENTINEL','private.example','PRIVATE_BASE_PATH'):
        assert value not in html
    assert fixed_bytes(web) == before


@pytest.mark.parametrize('base,scheme,mode,https', [
    ('','','Automatic','Not configured'),('','https','Explicit scheme','Configured'),
    ('','http','Explicit scheme','Not configured'),('https://example.com/path','','Explicit base URL','Configured'),
    ('http://example.com','','Explicit base URL','Not configured'),
    ('https://user:SECRET@example.com','','Explicit base URL','Not configured'),
    ('https://example.com/?SECRET','','Explicit base URL','Not configured'),
    ('https://example.com:bad','','Explicit base URL','Not configured'),
    ('https://example.com\\SECRET','','Explicit base URL','Not configured'),
])
def test_runtime_download_presentation_never_returns_raw_values(base,scheme,mode,https):
    value = settings_status.runtime(port=8899,cookie_secure=False,trust_proxy=False,
        download_base=base,download_scheme=scheme,upload_retention=3600,output_retention=86400,
        cleanup_interval=3600,backup_retention=604800)
    assert value['download_mode'] == mode and value['https_download'] == https
    assert 'SECRET' not in repr(value) and 'example.com' not in repr(value)


@pytest.mark.parametrize('arch', ['amd64','arm64'])
def test_installed_engine_local_status_never_executes_and_full_status_still_does(managed,arch):
    _, _, _, make = managed; manager = make(arch); manager.install(); calls = []
    def unavailable(path):
        calls.append(path)
        raise OSError('PRIVATE execution unavailable')
    manager.version_runner = unavailable
    assert manager.status(verify_execution=False)['status'] == 'COMPATIBLE' and calls == []
    assert manager.status()['status'] == 'BROKEN' and len(calls) == 1
    manager.binary.write_bytes(b'corrupt')
    assert manager.status(verify_execution=False)['status'] == 'BROKEN' and len(calls) == 1


def test_geoip_transaction_schema_unchanged_and_health_uses_own_store(web, logged_in, readers, monkeypatch):
    assert post(logged_in,'/settings/upload',{'geoip_file':(io.BytesIO(b'SYNTHETIC:SG'),'country.mmdb')}).status_code == 303
    original = web.geoip_store.settings.read_bytes(); database = web.geoip_store.path.read_bytes()
    assert set(json.loads(original)) == {'version','geoip'} and json.loads(original)['version'] == 1
    monkeypatch.setattr(source_fetch,'_resolve',public_resolver)
    assert post(logged_in, ROUTE, fields()).status_code == 303
    assert web.geoip_store.settings.read_bytes() == original and web.geoip_store.path.read_bytes() == database
    assert web.proxy_health.global_settings() == NEW
    assert b'GeoIP Database' in logged_in.get('/settings').data
    assert not (Path(web.DIR_STATE)/'app_settings.json').exists()
    assert not (Path(web.DIR_STATE)/'system_settings.json').exists()


def test_all_settings_actions_preserve_sources_policies_country_and_yaml(web, logged_in, readers, response, monkeypatch):
    from test_external_sources import external_save, remote, uploaded, payload
    from test_fixed_subscriptions import source
    from test_policy_engine import config as policies
    from core import health_policy
    post(logged_in,'/settings/upload',{'geoip_file':(io.BytesIO(b'SYNTHETIC:SG'),'country.mmdb')})
    config = dict(source(),country_detection={'geoip':'literal-ip'},policy_config=policies('url-test'),
                  health_policy=dict(health_policy.defaults(),mode='exclude-unhealthy'))
    entry = external_save(web.fixed_subscriptions,Path(web.DEFAULT_YAML_PATH),config=config,
        sources=[remote(url='https://source.example/sub?token=PROVIDER_CREDENTIAL_SENTINEL',refresh_interval_seconds=900),uploaded()],
        uploads={1:payload('London-upload')})
    before = fixed_bytes(web); fixed_only = {key:value for key,value in before.items() if '/geoip/' not in key and not key.endswith('/settings.json')}
    fetched = list(response['calls']); slug = web.fixed_subscriptions.slug(entry)
    html = logged_in.get('/settings').get_data(as_text=True)
    for value in ('PROVIDER_CREDENTIAL_SENTINEL',entry['token'],'vless://','11111111-1111-4111-8111-111111111111'):
        assert value not in html
    monkeypatch.setattr(source_fetch,'_resolve',public_resolver)
    assert post(logged_in,ROUTE,fields()).status_code == 303
    for operation in ('replace','remove'):
        result = (post(logged_in,'/settings/upload',{'geoip_file':(io.BytesIO(b'SYNTHETIC:TW'),'new.mmdb')})
                  if operation == 'replace' else post(logged_in,'/settings/remove'))
        assert result.status_code == 303
        after = fixed_bytes(web)
        assert {key:value for key,value in after.items() if key in fixed_only} == fixed_only
        current = web.fixed_subscriptions.get(entry['id'])
        assert current == entry and web.fixed_subscriptions.slug(current) == slug
        assert response['calls'] == fetched


def test_settings_engine_status_rejects_oversized_file_before_hashing(managed, monkeypatch):
    from core import mihomo_manager
    _, _, _, make = managed; manager = make(); manager.install()
    with manager.binary.open('r+b') as stream:
        stream.truncate(mihomo_manager.MAX_BINARY_BYTES + 1)
    attempted = []
    def forbidden(path):
        attempted.append(path)
        raise AssertionError('oversized file must not be scanned')
    monkeypatch.setattr(mihomo_manager,'sha256_file',forbidden)
    assert settings_status.engine_status(manager)['status'] == 'BROKEN' and attempted == []
