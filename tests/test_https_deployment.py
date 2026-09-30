"""Controlled root deployment simulations. No real system/package/network calls."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import os
import signal
import stat
import subprocess
import pytest

from core import https_metadata as metadata
from core.deployment_config import bind_host, service_unit
from core.https_manager import Manager, Paths, Error, email, edit_env, nginx_config, renewal_hook, main
from core.envfile import values
from conftest import ROOT

SECRET = 'ENV_SECRET_DISTINCTIVE'
MAIL = 'ACCOUNT_EMAIL_DISTINCTIVE@example.com'
PRIVATE_KEY = b'CERT_PRIVATE_DISTINCTIVE'


class Commands:
    def __init__(self, paths):
        self.paths = paths
        self.calls = []
        self.active = {'clash-yaml-manager':True,'nginx':False}
        self.enabled = False
        self.failure = None
        self.ports = ''
        self.dump = '# configuration file /etc/nginx/sites-enabled/unrelated:\nserver { server_name unrelated.example; }\n'
        self.nginx_tests = 0
    def available(self, name):
        return True
    def run(self, args, *, timeout=60):
        self.calls.append(args)
        rc, output = 0, ''
        if args[0] == 'ss': output = self.ports
        if args[:2] == ['nginx','-T']:output = self.dump
        if args[:2] == ['nginx','-t']:
            self.nginx_tests += 1
            if self.failure in ('nginx-first','nginx-second') and self.nginx_tests == (1 if self.failure == 'nginx-first' else 2):rc = 1
        if args[0] == 'systemctl':
            action, name = args[1], args[-1]
            if action == 'is-active': rc = 0 if self.active.get(name) else 1
            if action == 'is-enabled': rc = 0 if self.enabled else 1
            if action in ('start','restart'):
                self.active[name] = True
                if name == 'clash-yaml-manager' and self.failure == 'restart':
                    self.failure = None; rc = 1
            if action == 'stop': self.active[name] = False
            if action in ('enable','disable'):self.enabled = action == 'enable'
        if args[0] == 'certbot':
            if self.failure == 'certbot': rc = 1
            else:
                host = args[args.index('--domain')+1]
                live = self.paths.certificates/'live'/host
                live.mkdir(parents=True)
                (live/'fullchain.pem').write_bytes(b'CERT_PUBLIC')
                (live/'privkey.pem').write_bytes(PRIVATE_KEY)
                (live/'privkey.pem').chmod(0o600)
        if args[0] == 'curl':
            output = '503' if self.failure == 'tls' and '--resolve' in args else '200'
            assert '--insecure' not in args and '-k' not in args
        return SimpleNamespace(returncode=rc,stdout=output,stderr='FORBIDDEN_RAW_DIAGNOSTIC')


@pytest.fixture
def managed(tmp_path):
    paths = Paths(install=tmp_path/'app',unit=tmp_path/'systemd/app.service',
                  nginx=tmp_path/'nginx/conf.d/clash.conf',hook=tmp_path/'certs/renewal-hooks/deploy/clash.sh',
                  acme=tmp_path/'webroot',certificates=tmp_path/'certs',backups=tmp_path/'backups')
    for folder in (paths.install,paths.unit.parent,paths.nginx.parent,paths.hook.parent,paths.backups):
        folder.mkdir(parents=True,exist_ok=True)
    text = ('# preserved header\nAPP_PORT=8899\nSECRET_KEY='+SECRET+'\n'
            'COOKIE_SECURE="false"\nDOWNLOAD_BASE_URL=\'http://old.example/private?credential=URL_SECRET\'\n'
            'UNRELATED="  literal $ ` # Unicode 密码  "\n')
    (paths.install/'.env').write_text(text);(paths.install/'.env').chmod(0o600)
    paths.unit.write_text(service_unit(paths.install,8899));paths.unit.chmod(0o644)
    (paths.nginx.parent/'other.conf').write_text('UNRELATED NGINX BYTES')
    state = paths.install/'state';state.mkdir(mode=0o700)
    for name in ('auth.json','node_health.json','proxy_health.json','fixed_subscriptions.json','settings.json','active.mmdb','temp.json','source-payload'):
        (state/name).write_bytes(b'IMMUTABLE_STATE_'+name.encode())
    commands = Commands(paths)
    manager = Manager(paths,commands,owner_uid=os.getuid(),root_gid=os.getgid(),service_gid=os.getgid(),require_account=False)
    return manager,commands,text


def files(manager):
    return {key:path.read_bytes() if path.exists() else None for key,path in manager.paths.files().items()}


@pytest.mark.parametrize('host',['0.0.0.0','127.0.0.1'])
def test_bind_host_and_unit(host):
    assert bind_host(host) == host
    unit = service_unit('/opt/clash-yaml-manager',8899,host)
    assert f'-b {host}:${{APP_PORT}}' in unit
    assert 'User=clashyaml' in unit and 'User=root' not in unit


@pytest.mark.parametrize('host',['example.com','192.0.2.1','::1',' 127.0.0.1','127.0.0.1\n','',None])
def test_bind_invalid(host):
    with pytest.raises(ValueError):bind_host(host)


def test_bind_missing():
    assert bind_host() == '0.0.0.0'


@pytest.mark.parametrize('host',['https://example.com','example.com/path','example.com?q=x','example.com#x','example.com:443','a@b.com','*.example.com','.example.com','example.com.','a..com','a'*64+'.com','a.'*126+'com','example.com\n',' example.com','1.2.3.4','localhost','example.local','foo.localhost','例子.com','-bad.com','bad-.com','a_b.com'])
def test_domain_rejection(host):
    with pytest.raises(ValueError):metadata.domain(host)


@pytest.mark.parametrize('host',['example.com','WWW.Example.COM','xn--fiqs8s.example','a-b.example','a'*63+'.example'])
def test_domain_acceptance(host):
    assert metadata.domain(host) == host.lower()


@pytest.mark.parametrize('address',['a@example.com','a+b@example.com',MAIL])
def test_email_acceptance(address):assert email(address) == address


@pytest.mark.parametrize('address',['a b@example.com','a@example.com\n','a@localhost','a@@example.com','.a@example.com','a..b@example.com','a.@example.com','a'*65+'@example.com','密码@example.com','a@https://example.com','@example.com','a@example.local'])
def test_email_rejection(address):
    with pytest.raises(Error):email(address)


def test_setup_disable_preserves_all_states(managed):
    manager,commands,text = managed
    state = {p:p.read_bytes() for p in (manager.paths.install/'state').iterdir()}
    old = files(manager)
    result = manager.setup('example.com',MAIL)
    assert 'configured for example.com' in result
    info = manager.managed()
    assert info['managed_settings'] == metadata.managed_settings('example.com')
    assert values((manager.paths.install/'.env').read_text())['SECRET_KEY'] == SECRET
    assert 'UNRELATED="  literal $ ` # Unicode 密码  "\n' in (manager.paths.install/'.env').read_text()
    assert '-b 127.0.0.1:${APP_PORT}' in manager.paths.unit.read_text()
    config = manager.paths.nginx.read_text()
    for header,value in [('Host','$host'),('X-Real-IP','$remote_addr'),('X-Forwarded-For','$remote_addr'),('X-Forwarded-Proto','https'),('X-Forwarded-Host','$host'),('X-Forwarded-Port','443')]:
        assert f'proxy_set_header {header} {value};' in config
    assert '$proxy_add_x_forwarded_for' not in config and '$http_x_forwarded' not in config
    assert '50m' in config and '300s' in config and 'TLSv1.2 TLSv1.3' in config
    assert 'Strict-Transport-Security' not in config
    assert 'if ($host != example.com)' in config
    assert 'return 301 https://example.com$request_uri;' in config
    assert 'location ^~ /.well-known/acme-challenge/' in config
    call = next(c for c in commands.calls if c[0] == 'certbot')
    assert call[:3] == ['certbot','certonly','--webroot'] and '--nginx' not in call
    assert call[call.index('--email')+1] == MAIL
    assert '--agree-tos' in call and '--non-interactive' in call
    assert any('--resolve' in c and 'example.com:443:127.0.0.1' in c for c in commands.calls)
    assert files(manager)['metadata'] and stat.S_IMODE((manager.paths.install/metadata.NAME).stat().st_mode) == 0o640
    backup = Path(info['previous_backup'])
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700
    for path in backup.iterdir():assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert (backup/'env').read_text() == text
    assert PRIVATE_KEY not in b''.join(p.read_bytes() for p in backup.iterdir())
    for forbidden in (SECRET,MAIL,'URL_SECRET','CERT_PRIVATE_DISTINCTIVE'):
        assert forbidden not in files(manager)['metadata'].decode()
    manager.disable()
    assert files(manager)['env'] == old['env']
    assert files(manager)['unit'] == old['unit']
    assert files(manager)['nginx'] is None and files(manager)['hook'] is None and files(manager)['metadata'] is None
    assert (manager.paths.certificates/'live/example.com/privkey.pem').read_bytes() == PRIVATE_KEY
    assert (manager.paths.nginx.parent/'other.conf').read_text() == 'UNRELATED NGINX BYTES'
    assert state == {p:p.read_bytes() for p in state}


@pytest.mark.parametrize('failure',['certbot','nginx-first','nginx-second','restart','tls'])
def test_setup_failure_restores_files_and_services(managed,failure):
    manager,commands,_ = managed
    before = files(manager);commands.failure = failure
    with pytest.raises(Error,match='state restored'):manager.setup('example.com',MAIL)
    assert files(manager) == before
    assert commands.active == {'clash-yaml-manager':True,'nginx':False}
    assert len(list(manager.paths.backups.iterdir())) == 1
    assert not list(manager.paths.install.glob('.httpsctl-*'))
    assert (manager.paths.nginx.parent/'other.conf').read_text() == 'UNRELATED NGINX BYTES'


def test_readonly_status_and_idempotence(managed):
    manager,commands,_ = managed
    assert 'Managed: NO' in manager.status()
    assert not list(manager.paths.backups.iterdir()) and not (manager.paths.install/'.httpsctl.lock').exists()
    manager.setup('example.com',MAIL)
    before = files(manager);backup_count = len(list(manager.paths.backups.iterdir()));calls = len(commands.calls)
    manager.setup('EXAMPLE.COM',MAIL)
    assert not any(c[0]=='certbot' for c in commands.calls[calls:])
    assert files(manager) == before
    assert len(list(manager.paths.backups.iterdir())) == backup_count
    assert 'Managed: YES' in manager.status()
    with pytest.raises(Error,match='Different managed domain'):manager.setup('other.example',MAIL)


@pytest.mark.parametrize('changed',['nginx','hook','unit','env','metadata'])
def test_drift_refuses_setup_and_disable(managed,changed):
    manager,commands,_ = managed;manager.setup('example.com',MAIL)
    path = manager.paths.files()[changed]
    if changed == 'env':path.write_text(path.read_text().replace('COOKIE_SECURE=true','COOKIE_SECURE=false'))
    else:path.write_bytes(path.read_bytes()+b'\nCHANGED')
    before = files(manager)
    assert 'Managed: DRIFT' in manager.status()
    for action in (lambda:manager.setup('example.com',MAIL),manager.disable):
        with pytest.raises((Error,ValueError)):action()
        assert files(manager) == before


@pytest.mark.parametrize('collision',['domain','port','unknown-port','owned-path','marked-orphan','hook-orphan'])
def test_collisions_preserve_everything(managed,collision):
    manager,commands,_ = managed
    if collision == 'domain':commands.dump='# configuration file /etc/nginx/sites-enabled/other:\nserver_name example.com other.example;\n'
    if collision == 'port':commands.ports='LISTEN 0 10 0.0.0.0:80 0.0.0.0:* users:(("apache2",pid=12,fd=1))'
    if collision == 'unknown-port':commands.ports='LISTEN 0 10 0.0.0.0:443 0.0.0.0:*'
    if collision in ('owned-path','marked-orphan'):manager.paths.nginx.write_text('ADMIN CONFIG' if collision=='owned-path' else '# Managed by clash-yaml-manager httpsctl.sh\n')
    if collision == 'hook-orphan':manager.paths.hook.write_text('ADMIN HOOK')
    before = files(manager)
    with pytest.raises(Error):manager.setup('example.com',MAIL)
    assert files(manager) == before and not list(manager.paths.backups.iterdir())


def test_nginx_port_ownership_acceptable(managed):
    manager,commands,_ = managed;commands.ports='LISTEN 0 10 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=12,fd=1))'
    manager.setup('example.com',MAIL)


@pytest.mark.parametrize('unsafe',['symlink','fifo','mode','duplicate','quotes'])
def test_unsafe_env_stops_before_mutation(managed,unsafe):
    manager,commands,text = managed;path = manager.paths.install/'.env'
    if unsafe == 'symlink':path.unlink();path.symlink_to(manager.paths.unit)
    if unsafe == 'fifo':path.unlink();os.mkfifo(path,0o600)
    if unsafe == 'mode':path.chmod(0o644)
    if unsafe == 'duplicate':path.write_text(text+'COOKIE_SECURE=true\n')
    if unsafe == 'quotes':path.write_text(text+'BROKEN="unfinished\n')
    with pytest.raises(Exception):manager.setup('example.com',MAIL)
    assert not any(c[0]=='certbot' for c in commands.calls)


def test_disable_preserves_new_unrelated_values(managed):
    manager,_,text = managed;manager.setup('example.com',MAIL)
    path = manager.paths.install/'.env'
    path.write_text(path.read_text().replace(SECRET,'NEW_SECRET')+'NEW_UNRELATED=value\n')
    manager.disable()
    assert path.read_text() == text.replace(SECRET,'NEW_SECRET')+'NEW_UNRELATED=value\n'


@pytest.mark.parametrize('key',['APP_BIND_HOST','TRUST_PROXY_HEADERS','DOWNLOAD_URL_SCHEME','DOWNLOAD_BASE_URL','COOKIE_SECURE'])
def test_previous_values_exactly_restored(managed,key):
    manager,_,text=managed;path=manager.paths.install/'.env'
    raw={k:r for k,_,r in __import__('core.envfile',fromlist=['records']).records(text) if k in metadata.KEYS}
    raw[key] = key+'="'+{'APP_BIND_HOST':'127.0.0.1','COOKIE_SECURE':'true','TRUST_PROXY_HEADERS':'true','DOWNLOAD_URL_SCHEME':'https','DOWNLOAD_BASE_URL':'https://prior.example'}[key]+'"\n'
    old=edit_env(text,raw);path.write_text(old)
    manager.setup('example.com',MAIL);manager.disable()
    assert path.read_text() == old


def test_disable_failure_restores_managed_state(managed):
    manager,commands,_=managed;manager.setup('example.com',MAIL);before=files(manager)
    commands.failure='restart'
    with pytest.raises(Error,match='state restored'):manager.disable()
    assert files(manager)==before and 'Managed: YES' in manager.status()


def test_atomic_post_replace_error_recovers(managed,monkeypatch):
    manager,_,_=managed;before=files(manager);original=manager.sync_dir;fired=False
    def fail_once(path):
        nonlocal fired
        if path == manager.paths.install and b'APP_BIND_HOST=127.0.0.1' in (path/'.env').read_bytes() and not fired:
            fired=True;raise OSError('INJECTED_FSYNC_FAILURE')
        original(path)
    monkeypatch.setattr(manager,'sync_dir',fail_once)
    with pytest.raises(Error,match='state restored'):manager.setup('example.com',MAIL)
    assert fired and files(manager)==before


def test_signal_exception_recovers(managed,monkeypatch):
    manager,_,_=managed;before=files(manager)
    monkeypatch.setattr(manager,'certificates_present',lambda host: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(Error,match='state restored'):manager.setup('example.com',MAIL)
    assert files(manager)==before


def test_explicit_rollback_validates_private_backup(managed):
    manager,_,_=managed;before=files(manager);manager.setup('example.com',MAIL)
    folder=Path(manager.managed()['previous_backup']);manager.rollback(folder)
    assert files(manager)==before
    with pytest.raises(Error):manager.rollback(folder/'../bad')
    (folder/'unexpected').write_text('bad')
    with pytest.raises(Error):manager.load_backup(folder)


@pytest.mark.parametrize('unsafe',['symlink','mode','checksum','manifest'])
def test_backup_tamper_stops_restore(managed,unsafe):
    manager,_,_=managed;manager.setup('example.com',MAIL);folder=Path(manager.managed()['previous_backup'])
    if unsafe=='symlink':(folder/'env').unlink();(folder/'env').symlink_to(manager.paths.unit)
    if unsafe=='mode':folder.chmod(0o755)
    if unsafe=='checksum':(folder/'env').write_text('tampered')
    if unsafe=='manifest':(folder/'manifest.json').write_text('{}')
    before=files(manager)
    with pytest.raises(Exception):manager.disable()
    assert files(manager)==before


def test_uninstall_detach_only_owned_files(managed):
    manager,_,_=managed;manager.setup('example.com',MAIL);before=files(manager)
    manager.detach()
    assert files(manager)['env']==before['env'] and files(manager)['unit']==before['unit'] and files(manager)['metadata']==before['metadata']
    assert not manager.paths.nginx.exists() and not manager.paths.hook.exists()
    assert (manager.paths.nginx.parent/'other.conf').read_text()=='UNRELATED NGINX BYTES'
    assert (manager.paths.certificates/'live/example.com/privkey.pem').read_bytes()==PRIVATE_KEY


def test_uninstall_drift_leaves_files(managed):
    manager,_,_=managed;manager.setup('example.com',MAIL);manager.paths.nginx.write_text('ADMIN EDIT')
    before=files(manager)
    with pytest.raises(Error):manager.detach()
    assert files(manager)==before


def test_root_only_safe_errors(monkeypatch,capsys):
    monkeypatch.setattr(os,'geteuid',lambda:501)
    assert main(['status'])==1
    monkeypatch.setattr(os,'geteuid',lambda:0)
    assert main(['setup','--email',MAIL,'--SECRET',SECRET])==1
    output=capsys.readouterr().out
    assert MAIL not in output and SECRET not in output


def test_hook_lineage_and_shell_syntax(managed):
    manager,_,_=managed;hook=renewal_hook(manager.paths,'example.com')
    assert 'RENEWED_LINEAGE' in hook and 'nginx -t\nsystemctl reload nginx' in hook
    assert '.env' not in hook and 'restart' not in hook
    path=manager.paths.hook;path.write_text(hook)
    assert subprocess.run(['bash','-n',str(path)]).returncode==0


def test_metadata_schema_rejects_secrets_and_duplicate_keys(managed):
    manager,_,_=managed;manager.setup('example.com',MAIL);info=manager.managed()
    with pytest.raises(ValueError):metadata.validate({**info,'email':MAIL},manager.paths.backups)
    path=manager.paths.install/metadata.NAME
    path.write_text(path.read_text().replace('"version": 1','"version": 1, "version": 1'))
    with pytest.raises(ValueError):manager.managed()


@pytest.mark.parametrize('fail',['none','apt','unsupported'])
def test_packages_only_in_explicit_setup_and_side_effect_rollback(managed,monkeypatch,fail):
    manager,commands,_=managed
    available=False
    monkeypatch.setattr(commands,'available',lambda name: available if name in ('nginx','certbot') else True)
    monkeypatch.setattr(commands,'distribution',lambda: 'unsupported' if fail=='unsupported' else 'debian',raising=False)
    original=commands.run
    def run(args,**kwargs):
        nonlocal available
        if args[:2]==['apt-get','install']:
            available=True;commands.active['nginx']=True;commands.enabled=True
            result=original(args,**kwargs)
            if fail=='apt':result.returncode=1
            return result
        return original(args,**kwargs)
    monkeypatch.setattr(commands,'run',run)
    before=files(manager)
    manager.status()
    assert not any(c[0]=='apt-get' for c in commands.calls)
    if fail=='none':
        manager.setup('example.com',MAIL)
        assert ['apt-get','update'] in commands.calls
        assert ['apt-get','install','-y','nginx','certbot'] in commands.calls
    else:
        with pytest.raises(Error):manager.setup('example.com',MAIL)
        assert files(manager)==before and not commands.active['nginx'] and not commands.enabled


def test_multiline_quoted_domain_collision(managed):
    manager,commands,_=managed
    commands.dump='# configuration file /etc/nginx/sites-enabled/other:\nserver_name\n "EXAMPLE.COM"\n other.example;\n'
    with pytest.raises(Error,match='Domain already claimed'):manager.setup('example.com',MAIL)


def test_certificate_symlink_must_be_certbot_archive(managed,monkeypatch):
    manager,commands,_=managed;before=files(manager)
    original=commands.run
    def run(args,**kwargs):
        result=original(args,**kwargs)
        if args[0]=='certbot':
            key=manager.paths.certificates/'live/example.com/privkey.pem';key.unlink();key.symlink_to(manager.paths.install/'.env')
        return result
    monkeypatch.setattr(commands,'run',run)
    with pytest.raises(Error,match='state restored'):manager.setup('example.com',MAIL)
    assert files(manager)==before


def test_no_root_application_service(managed):
    manager,commands,_=managed;manager.paths.unit.write_text('[Service]\nUser=root\nGroup=root\n')
    with pytest.raises(Error,match='non-root'):manager.setup('example.com',MAIL)
    assert not commands.calls


def test_lock_symlink_refused(managed):
    manager,commands,_=managed
    (manager.paths.install/'.httpsctl.lock').symlink_to(manager.paths.install/'.env')
    before=files(manager)
    with pytest.raises(Error):manager.disable()
    assert files(manager)==before and not commands.calls


@pytest.mark.parametrize('drift',['certificate','permissions'])
def test_same_domain_setup_checks_existing_integration(managed,drift):
    manager,commands,_=managed;manager.setup('example.com',MAIL)
    if drift=='certificate':(manager.paths.certificates/'live/example.com/fullchain.pem').unlink()
    else:manager.paths.hook.chmod(0o644)
    before=files(manager);count=len(commands.calls)
    with pytest.raises(Exception):manager.setup('example.com',MAIL)
    assert files(manager)==before and not any(c[0]=='certbot' for c in commands.calls[count:])


def test_wrapper_root_guard_without_host_commands():
    if os.geteuid()==0:pytest.skip('Non-root wrapper guard exercised on developer user')
    result=subprocess.run(['bash',str(ROOT/'httpsctl.sh'),'status'],capture_output=True,text=True)
    assert result.returncode==1 and 'requires root' in result.stderr



def test_concurrent_manual_env_edit_not_overwritten(managed,monkeypatch):
    manager,commands,_=managed
    original=commands.run
    path=manager.paths.install/'.env'
    def run(args,**kwargs):
        result=original(args,**kwargs)
        if args[0]=='certbot':path.write_text(path.read_text()+'ADMIN_CONCURRENT=value\n')
        return result
    monkeypatch.setattr(commands,'run',run)
    with pytest.raises(Error,match='state restored'):manager.setup('example.com',MAIL)
    assert 'ADMIN_CONCURRENT=value' in path.read_text()
    assert not manager.paths.nginx.exists() and not (manager.paths.install/metadata.NAME).exists()


def test_unowned_config_appearing_during_preflight_not_overwritten(managed,monkeypatch):
    manager,_,_=managed;original=manager.snapshot
    def snapshot():
        manager.paths.nginx.write_text('CONCURRENT_ADMIN_CONFIG')
        return original()
    monkeypatch.setattr(manager,'snapshot',snapshot)
    with pytest.raises(Error):manager.setup('example.com',MAIL)
    assert manager.paths.nginx.read_text()=='CONCURRENT_ADMIN_CONFIG'



def test_disable_previous_final_record_without_newline_and_new_setting(managed):
    manager,_,_=managed;path=manager.paths.install/'.env'
    path.write_text('APP_PORT=8899\nSECRET_KEY='+SECRET+'\nCOOKIE_SECURE="false"')
    manager.setup('example.com',MAIL)
    path.write_text(path.read_text()+'NEW_ADMIN_SETTING="  preserved  "\n')
    manager.disable()
    env=values(path.read_text())
    assert env['COOKIE_SECURE']=='false' and env['NEW_ADMIN_SETTING']=='  preserved  '
    assert 'COOKIE_SECURE="false"\nNEW_ADMIN_SETTING="  preserved  "\n' in path.read_text()



@pytest.mark.parametrize('setting',['APP_BIND_HOST=bad','DOWNLOAD_URL_SCHEME=bad','COOKIE_SECURE=false\nCOOKIE_SECURE=true'])
def test_invalid_managed_environment_status_is_safe_drift(managed,setting):
    manager,commands,_=managed;manager.setup('example.com',MAIL)
    path=manager.paths.install/'.env';path.write_text(path.read_text()+setting+'\n')
    before=files(manager);count=len(commands.calls)
    result=manager.status()
    assert 'Managed: DRIFT' in result and SECRET not in result and MAIL not in result
    assert files(manager)==before and not commands.calls[count:]



def test_uninstall_incomplete_rollback_retains_recovery_diagnostic(managed,monkeypatch):
    from core import https_manager
    manager,commands,_=managed;manager.setup('example.com',MAIL)
    commands.nginx_tests=0;commands.failure='nginx-first'
    monkeypatch.setattr(https_manager,'Manager',lambda paths:manager)
    monkeypatch.setattr(manager,'restore',lambda *args: (_ for _ in ()).throw(Error('INJECTED_RESTORE_FAILURE')))
    result=https_manager.cleanup_uninstall(manager.paths.install)
    assert 'Automatic rollback incomplete' in result and str(manager.backup) in result
    assert 'left untouched' not in result and SECRET not in result and MAIL not in result



@pytest.mark.parametrize('available',[True,False])
def test_disable_does_not_start_stopped_or_removed_nginx(managed,monkeypatch,available):
    manager,commands,_=managed;manager.setup('example.com',MAIL)
    commands.active['nginx']=False
    monkeypatch.setattr(commands,'available',lambda name: available if name=='nginx' else True)
    count=len(commands.calls);manager.disable()
    assert not commands.active['nginx']
    assert not any(c[:2]==['systemctl','start'] and c[-1]=='nginx' for c in commands.calls[count:])
    if not available:assert not any(c[0]=='nginx' for c in commands.calls[count:])
