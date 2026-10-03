"""Cross-version release gates using genuine stable code and temporary deployments."""
import base64
import json
import os
import stat
from pathlib import Path
import subprocess
import sys

import pytest

from conftest import ROOT
from test_deployment import deployment

STABLE = '6ff864df84be74755d907032bd9be0f2cd8821de'
PASSWORD = ' 密码 Ω surrounding spaces '


STABLE_STAT_FIELDS = ('st_mode', 'st_ino', 'st_dev', 'st_nlink', 'st_uid',
                      'st_gid', 'st_size', 'st_mtime_ns', 'st_ctime_ns')


def stable_lstat(path):
    """Preserve object identity/structure and link target, excluding access time."""
    metadata = path.lstat()
    target = os.readlink(path) if stat.S_ISLNK(metadata.st_mode) else None
    return tuple(getattr(metadata, field) for field in STABLE_STAT_FIELDS), target


def isolated(root, program, env):
    # -I excludes this checkout/PYTHONPATH. Add only the extracted installation;
    # core is a namespace package and must never fall through to current code.
    result = subprocess.run([sys.executable, '-I', '-c',
        'import sys; sys.path.insert(0, sys.argv[1]);\n' + program, str(root)],
        cwd=root, env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('stable_commit', [STABLE, 'f62bf50721e3ac00d5d2a2a9f784ede4b79b49cf'], ids=['v1.1.1','v1.2.1'])
@pytest.mark.parametrize('legacy_env', [False, True])
def test_genuine_stable_upgrade_preserves_auth_links_session_and_runtime(deployment, legacy_env, stable_commit):
    installed, source, service, events, env, run = deployment
    paths = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', stable_commit,
                                     'core', 'app.py', 'VERSION', 'templates', 'static'], cwd=ROOT, text=True).splitlines()
    for name in paths:
        path = installed / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(subprocess.check_output(['git', 'show', stable_commit + ':' + name], cwd=ROOT))
    # The source fixture normally uses a stub app. This gate loads the actual app
    # after running the real update script so session and public routes are checked.
    (source / 'app.py').write_bytes((ROOT / 'app.py').read_bytes())
    b64 = base64.b64encode(PASSWORD.encode()).decode()
    text = f'APP_PASSWORD_B64={b64}\nAPP_PORT=8899\nSECRET_KEY=synthetic-stable-signing-key\nOPERATOR_VALUE=" keep Ω "\nCOOKIE_SECURE=false\nTRUST_PROXY_HEADERS=false\n'
    (installed / '.env').write_text(text)
    runtime_env = dict(env, APP_PASSWORD_B64=b64, SECRET_KEY='synthetic-stable-signing-key',
                       COOKIE_SECURE='false', TRUST_PROXY_HEADERS='false', PYTHONDONTWRITEBYTECODE='1')
    fixture = installed.parent / 'stable-evidence.json'
    runtime_env['AUDIT_EVIDENCE'] = str(fixture)
    isolated(installed, '''
import json, os, re, time
from pathlib import Path
import core.security as security
assert Path(security.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
import app
from core.temporary_links import TemporaryLinks
from core.subscriptions import SubscriptionSigner
client=app.app.test_client()
page=client.get('/').get_data(as_text=True)
token=re.search(r'name="csrf_token"[^>]*value="([^"]+)"',page).group(1)
password=' 密码 Ω surrounding spaces '
assert client.post('/login',data={'csrf_token':token,'password':password}).status_code==302
assert client.get('/').status_code==200
filename='tim_20260930_1.yaml'
Path('outputs',filename).write_bytes(b'proxies: []\\nrules: [MATCH,DIRECT]\\n')
short_id,_=TemporaryLinks('state').create(filename,lifetime=86400*365,now=time.time())
signer=SubscriptionSigner(app.get_secret_key_bytes())
Path(os.environ['AUDIT_EVIDENCE']).write_text(json.dumps(dict(
    session=client.get_cookie('session').value, short_id=short_id,
    slug=signer.build_slug(filename), full=signer.full_token(filename), filename=filename,
    identity=app.auth_store.read())))
''', runtime_env)
    evidence = json.loads(fixture.read_text())
    auth_before = (installed / 'state/auth.json').read_bytes()
    temp_before = (installed / 'state/temporary_links.json').read_bytes()
    if legacy_env:
        (installed / 'state/auth.json').unlink()
    for path in installed.glob('logs/*'):
        path.write_bytes(b'synthetic stable log\n')
    preserved = {p.relative_to(installed):p.read_bytes() for name in ('uploads','outputs','backups','logs','defaults')
                 for p in (installed/name).rglob('*') if p.is_file()}
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert (installed / '.env').read_text() == text.replace(f'APP_PASSWORD_B64={b64}\n', '')
    assert (installed / 'state/temporary_links.json').read_bytes() == temp_before
    if not legacy_env:
        assert (installed / 'state/auth.json').read_bytes() == auth_before
    assert all((installed/path).read_bytes()==raw for path,raw in preserved.items())
    backup = next(installed.parent.glob('upgrade-backup-*'))
    assert (backup / '.env').read_text() == text
    assert (backup / 'state/temporary_links.json').read_bytes() == temp_before
    assert (backup / 'state/auth.json').exists() is (not legacy_env)
    runtime_env.pop('APP_PASSWORD_B64')
    runtime_env['AUDIT_LEGACY_ENV'] = str(int(legacy_env))
    isolated(installed, '''
import json, os
from pathlib import Path
import app
from core.notifications import Notifications
from core.node_health import NodeHealth
from core.proxy_health import ProxyHealth
from core import health_policy, geoip, policy_engine
old=json.loads(Path(os.environ['AUDIT_EVIDENCE']).read_text())
assert app.auth_store.authenticate(' 密码 Ω surrounding spaces ')
assert not app.auth_store.authenticate('密码 Ω surrounding spaces')
current=app.auth_store.read()
if os.environ['AUDIT_LEGACY_ENV']=='0':
    assert current==old['identity']
else:
    assert current['instance_id']!=old['identity']['instance_id']
client=app.app.test_client(); client.set_cookie('session',old['session'])
client.get('/')
with client.session_transaction() as session:
    assert bool(session.get('logged_in')) is (os.environ['AUDIT_LEGACY_ENV']=='0')
for url in ('/t/'+old['short_id'], '/s/'+old['slug'],
            '/download/'+old['filename']+'?token='+old['full'],
            '/sub/'+old['full'][:8]+'/'+old['filename']):
    assert client.get(url).status_code==200
assert app.fixed_subscriptions.list()==[]
assert NodeHealth(app.fixed_subscriptions).scheduled_entries()=={}
assert ProxyHealth(app.fixed_subscriptions).scheduled_entries()=={}
assert Notifications(app.DIR_STATE).status()['enabled'] is False
assert app.geoip_store.status()['status']=='Not installed'
assert geoip.defaults()=={'geoip':'off'} and health_policy.defaults()['mode']=='off'
assert set(p['type'] for p in policy_engine.defaults().values())=={'preserve'}
assert not Path('HTTPS_DEPLOYMENT.json').exists()
assert not Path('bin/mihomo').exists()
''', runtime_env)
    log = events.read_text()
    assert all(word not in log for word in ('certbot','nginx','telegram','auto_refresh --once','auto_health --once'))


@pytest.mark.parametrize('choice', ['retain', 'backup'])
def test_update_then_uninstall_preserves_all_feature_artifacts(deployment, choice):
    from core.security import AuthStore
    from core.fixed_subscriptions import FixedSubscriptions
    from core.notifications import Notifications
    from core.node_health import NodeHealth
    from core.proxy_health import ProxyHealth
    from core import generator
    from test_fixed_subscriptions import source as config, parsed
    from conftest import LINK
    installed, incoming, service, events, env, run = deployment
    state = installed/'state'
    AuthStore(state).initialize({'APP_PASSWORD':PASSWORD})
    fixed=FixedSubscriptions(state)
    value=dict(config(),yaml_source='custom')
    entry=fixed.save(None,'Audit','audit',value,parsed(value),None,
        b'proxies: []\nproxy-groups: []\nrules: [MATCH,DIRECT]\n',
        sources=[dict(type='uploaded',name='Archive',enabled=True,format='raw')],
        uploads={0:(LINK+'#Tokyo-upload').encode()})
    NodeHealth(fixed).settings(entry['id'],'manual')
    ProxyHealth(fixed).settings(entry['id'],'off',True)
    Notifications(state).save(False, {k:True for k in ('source_refresh','endpoint_health','proxy_health','scheduler')},
        token='123456789:'+'A'*35, chat='-123456789')
    (state/'geoip').mkdir(mode=0o700)
    (state/'geoip/active.mmdb').write_bytes(b'synthetic opaque operator dataset')
    (state/'settings.json').write_bytes(b'synthetic paired metadata preserved without reading')
    (installed/'bin').mkdir();(installed/'bin/mihomo').write_bytes(b'synthetic managed executable')
    (installed/'bin/mihomo.json').write_bytes(b'synthetic metadata')
    (installed/'HTTPS_DEPLOYMENT.json').write_bytes(b'synthetic unmanaged/corrupt metadata')
    # Uninstall must not infer ownership from this invalid marker.
    (incoming/'state').mkdir();(incoming/'state/notifications.json').write_bytes(b'wrong incoming credentials')
    (incoming/'bin').mkdir();(incoming/'bin/mihomo').write_bytes(b'wrong incoming binary')
    (incoming/'HTTPS_DEPLOYMENT.json').write_bytes(b'wrong incoming metadata')
    for path in state.rglob('*'):
        if path.is_file():path.chmod(0o600)
    before={p.relative_to(installed):p.read_bytes() for p in installed.rglob('*')
        if p.is_file() and (p.is_relative_to(state) or p.is_relative_to(installed/'bin')
                          or p.name=='HTTPS_DEPLOYMENT.json')}
    result=run(); assert result.returncode==0,result.stdout+result.stderr
    assert all((installed/p).read_bytes()==raw for p,raw in before.items())
    assert fixed.get(entry['id'])['token']==entry['token']
    upgrade=next(installed.parent.glob('upgrade-backup-*'))
    assert all((upgrade/p).read_bytes()==raw for p,raw in before.items() if str(p).startswith('state/'))
    # bin is retained in place, not duplicated in the upgrade or uninstall backup.
    assert not (upgrade/'bin').exists()
    result=run('uninstall.sh',input_text='n\n' if choice=='retain' else 'y\n\n')
    assert result.returncode==0,result.stdout+result.stderr
    retained=installed if choice=='retain' else next(installed.parent.glob('uninstall-backup-*'))
    checked=before if choice=='retain' else {p:v for p,v in before.items() if not str(p).startswith('bin/')}
    assert all((retained/p).read_bytes()==raw for p,raw in checked.items())
    assert all(p.stat().st_mode&0o777==0o600 for p in (retained/'state').rglob('*') if p.is_file())
    assert all(p.stat().st_mode&0o777==0o700 for p in (retained/'state').rglob('*') if p.is_dir())
    if choice=='backup':assert retained.stat().st_mode&0o777==0o700
    assert all(word not in events.read_text() for word in ('certbot','nginx','telegram'))


@pytest.mark.parametrize('kind', ['fifo', 'symlink', 'broken-link', 'directory'])
def test_unsafe_auth_object_aborts_update_before_service_or_data_changes(deployment, kind):
    installed, source, service, events, env, run = deployment
    state = installed/'state'; state.mkdir(mode=0o700)
    path = state/'auth.json'
    if kind=='fifo':os.mkfifo(path,0o600)
    elif kind=='directory':path.mkdir(mode=0o700)
    else:
        other=installed.parent/'outside-auth.json'
        if kind=='symlink':other.write_bytes(b'{"password_hash":"synthetic","auth_version":1}')
        path.symlink_to(other)
    before=(installed/'.env').read_bytes(),service.read_bytes(),stable_lstat(path)
    result=run()
    assert result.returncode!=0
    assert '升级预检失败' in result.stderr
    assert not events.exists()
    assert ((installed/'.env').read_bytes(),service.read_bytes(),stable_lstat(path))==before


def test_unsafe_object_snapshot_ignores_only_symlink_access_time(tmp_path, monkeypatch):
    """Model an atime-only observation without utime also changing ctime."""
    from types import SimpleNamespace
    path = tmp_path / 'broken-link'
    path.symlink_to('missing-auth.json')
    metadata = path.lstat()
    observed = {field: getattr(metadata, field) for field in
                (*STABLE_STAT_FIELDS, 'st_atime', 'st_atime_ns')}
    original_lstat = Path.lstat
    monkeypatch.setattr(Path, 'lstat', lambda item: SimpleNamespace(**observed)
                        if item == path else original_lstat(item))
    before = stable_lstat(path)
    observed['st_atime'] += 1
    observed['st_atime_ns'] += 1_000_000_000
    assert stable_lstat(path) == before
    # Every structural field remains protected, including nanosecond times.
    for field in STABLE_STAT_FIELDS:
        observed[field] += 1
        assert stable_lstat(path) != before, field
        observed[field] -= 1
    original_readlink = os.readlink
    monkeypatch.setattr(os, 'readlink', lambda item: 'different-auth.json'
                        if item == path else original_readlink(item))
    assert stable_lstat(path) != before


def test_complete_route_inventory_auth_and_csrf_boundaries(web, logged_in):
    from conftest import post
    expected = {
        'static', 'index', 'healthz', 'login', 'logout', 'change_password', 'parse_nodes', 'preview_yaml_diff',
        'process_config', 'temporary_subscribe', 'download_file', 'subscribe_file',
        'short_subscribe_file', 'delete_temp', 'fixed.index', 'fixed.create', 'fixed.edit',
        'fixed.health_action', 'fixed.proxy_defaults', 'fixed.proxy_action',
        'fixed.source_action', 'fixed.action', 'settings.index', 'settings.proxy_defaults',
        'settings.upload', 'settings.remove', 'settings.notification_save',
        'settings.notification_test', 'settings.notification_remove',
    }
    rules = list(web.app.url_map.iter_rules())
    assert {rule.endpoint for rule in rules} == expected
    anonymous = web.app.test_client()
    protected = {'change_password','parse_nodes','process_config','delete_temp','preview_yaml_diff'}
    for rule in rules:
        path = rule.rule.replace('<key>','a'*32).replace('<identifier>','b'*32)
        path = path.replace('<operation>','settings').replace('<action>','disable')
        management = rule.endpoint.startswith(('fixed.','settings.')) or rule.endpoint in protected
        if management:
            if 'GET' in rule.methods:
                response=anonymous.get(path)
                assert response.status_code==302 and response.headers['Location'].endswith('/')
            if 'POST' in rule.methods:
                response=post(anonymous,path,{})
                if rule.endpoint=='preview_yaml_diff':
                    assert response.status_code==401 and response.json['ok'] is False
                else:assert response.status_code==302 and response.headers['Location'].endswith('/')
        if 'POST' in rule.methods:
            response=logged_in.post(path,data={})
            assert response.status_code==(400 if rule.endpoint in ('parse_nodes','preview_yaml_diff') else 303)
            if 'GET' not in rule.methods:assert logged_in.get(path).status_code==405


from test_fixed_subscriptions import base, store, parsed
from test_external_sources import response
from test_geoip import readers, link
from test_geoip_lifecycle import fixed_geoip


@pytest.mark.parametrize('kind', ['preserve','select','url-test','fallback','load-balance'])
@pytest.mark.parametrize('health_enabled', [False, True])
@pytest.mark.parametrize('country_mode', ['off','literal-ip'])
@pytest.mark.parametrize('refresh', ['manual','auto'])
def test_source_policy_health_geoip_refresh_interaction_matrix(
        store, base, response, fixed_geoip, kind, health_enabled, country_mode, refresh):
    from types import SimpleNamespace
    from ruamel.yaml import YAML
    from core import auto_refresh, health_policy, policy_engine, yaml_utils
    from core.proxy_health import ProxyHealth
    from test_proxy_health import public_resolver
    from test_external_sources import remote, uploaded
    from test_policy_engine import config
    clock=lambda:1_800_000_000
    fields=dict(yaml_source='default', batch_nodes='\n'.join(
        name+'|'+link(host) for name,host in [('Opaque-A','8.8.8.8'),('Opaque-B','9.9.9.9')]),
        aux_nodes=[],node_overrides={},special_groups=[],policy_config=config(kind),
        health_policy=dict(mode='exclude-unhealthy' if health_enabled else 'off',
                           max_age_seconds=172800,min_candidates=2),country_detection={'geoip':country_mode})
    response['payload']=(link('1.1.1.1')+'#Opaque-remote').encode()
    entry=store.save(None,'Matrix','matrix',fields,parsed(fields),base,
        sources=[remote(refresh_interval_seconds=900),uploaded()],
        uploads={1:(link('208.67.222.222')+'#Opaque-upload').encode()},clock=clock)
    def run(binary,nodes,settings,directory):
        return {n['fingerprint']:dict(kind='failure' if n['config']['server']=='1.1.1.1' else 'success',
            latency_ms=None if n['config']['server']=='1.1.1.1' else 10,
            error='proxy_failed' if n['config']['server']=='1.1.1.1' else None) for n in nodes}
    proxy=ProxyHealth(store,engine=SimpleNamespace(binary=store.state/'unused',status=lambda:{'status':'COMPATIBLE'}),
        clock=clock,runner=run,resolver=public_resolver)
    proxy.settings(entry['id'],'manual',True)
    for _ in range(3):proxy.check(entry['id'])
    health_bytes=proxy.path.read_bytes();slug=store.slug(entry);base_bytes=base.read_bytes()
    response['payload']=(link('1.1.1.1')+'#Opaque-renamed').encode()
    if refresh=='auto':assert auto_refresh.run_once(store,base,clock=lambda:1_800_000_900)==0
    else:store.source_action(entry['id'],'refresh',base,entry['sources'][1]['id'],clock=lambda:1_800_000_900)
    current=store.get(entry['id']); data=YAML(typ='safe').load(store.snapshot(entry['id'])[1])
    assert store.slug(current)==slug and current['token']==entry['token']
    assert current['policy_config']==entry['policy_config'] and current['country_detection']==entry['country_detection']
    assert current['health_policy']==entry['health_policy'] and proxy.path.read_bytes()==health_bytes
    assert base.read_bytes()==base_bytes and store._content(current,'base.yaml')==base_bytes
    assert len(data['proxies'])==4 and yaml_utils.validate_proxy_references(data)==[]
    assert {n['server'] for n in data['proxies']}=={'8.8.8.8','9.9.9.9','1.1.1.1','208.67.222.222'}
    assert data['rules']==['MATCH,DIRECT']
    named=next(n['name'] for n in data['proxies'] if n['server']=='1.1.1.1')
    group=next(g for g in data['proxy-groups'] if g['name']==('🇸🇬 狮城节点' if country_mode=='literal-ip' else '🌐 其他节点'))
    assert (named not in group['proxies']) is (health_enabled and kind in policy_engine.AUTOMATIC)


@pytest.mark.parametrize('url', [
    '/t/synthetic-temporary', '/s/v2.synthetic-signed', '/s/legacy-synthetic',
    '/sub/synthetic-token/file.yaml', '/download/file.yaml?token=synthetic-token',
    '/%74/synthetic-temporary', '/%73ub/synthetic-token/file.yaml',
    '/download%2Ffile.yaml?token=synthetic-token',
    '/s/home-fs_synthetic-token', '/%73/home-fs_synthetic-token',
])
def test_all_bearer_request_logs_suppress_credentials_and_referer(url):
    import logging
    from core.fixed_subscriptions import FixedBearerFilter
    record=logging.LogRecord('gunicorn.access',logging.INFO,'',1,
        'GET %s HTTP/1.1 Referer=https://example.invalid/private?secret=synthetic-referer',
        (url,),None)
    assert FixedBearerFilter().filter(record)
    assert 'redacted' in record.getMessage()
    assert 'synthetic' not in record.getMessage() and 'example.invalid' not in record.getMessage()


def test_managed_nginx_never_inherits_request_access_logs():
    from core.https_manager import Paths, nginx_config
    for tls, blocks in [(False,1),(True,2)]:
        config=nginx_config(Paths(),'example.com',8899,tls=tls)
        assert config.count('access_log off;')==blocks
        for server in config.split('server {')[1:]:
            assert 'access_log off;' in server
        if tls:
            assert 'proxy_set_header X-Forwarded-For $remote_addr;' in config
            assert 'proxy_pass http://127.0.0.1:8899;' in config
