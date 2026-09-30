"""Root/SSH-only HTTPS orchestration. Web code must never import this module.

All selected paths are fixed in production. Paths/Runner injection is a Python
unit-test seam, never an environment variable or operator CLI option.
"""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pwd
import grp
import re
import shutil
import signal
import stat
import subprocess
import tempfile

from core import https_metadata as metadata
from core.deployment_config import bind_host, service_unit
from core.envfile import records, values
from core.state import file_lock

MARKER = '# Managed by clash-yaml-manager httpsctl.sh'
SERVICE = 'clash-yaml-manager'


class Error(Exception):
    """Messages are fixed, credential-free operator diagnostics."""


@dataclass(frozen=True)
class Paths:
    install: Path = Path('/opt/clash-yaml-manager')
    unit: Path = Path('/etc/systemd/system/clash-yaml-manager.service')
    nginx: Path = Path('/etc/nginx/conf.d/clash-yaml-manager.conf')
    hook: Path = Path('/etc/letsencrypt/renewal-hooks/deploy/clash-yaml-manager-nginx.sh')
    acme: Path = Path('/var/lib/clash-yaml-manager-acme')
    certificates: Path = Path('/etc/letsencrypt')
    backups: Path = Path('/root')

    def files(self):
        return dict(env=self.install/'.env', unit=self.unit, nginx=self.nginx,
                    hook=self.hook, metadata=self.install/metadata.NAME)


class Runner:
    def available(self, name):
        return shutil.which(name) is not None

    def distribution(self):
        try:
            return values(Path('/etc/os-release').read_text()).get('ID')
        except OSError:
            return None

    def run(self, args, *, timeout=60):
        try:
            return subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, timeout=timeout,
                                  check=False, env={**os.environ, 'LC_ALL': 'C'})
        except (OSError, subprocess.SubprocessError):
            raise Error('Deployment command unavailable or timed out.') from None


def digest(data):
    return hashlib.sha256(data).hexdigest()


def email(value):
    if (not isinstance(value, str) or not value.isascii() or len(value) > 254
            or value.count('@') != 1):
        raise Error('Invalid registration email syntax.')
    local, host = value.split('@')
    if (not 1 <= len(local) <= 64 or not re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+', local)
            or local.startswith('.') or local.endswith('.') or '..' in local):
        raise Error('Invalid registration email syntax.')
    try:
        metadata.domain(host)
    except ValueError:
        raise Error('Invalid registration email syntax.') from None
    return value


def edit_env(text, replacements):
    """Replace managed records, preserving all other bytes and original quoting."""
    result, seen = [], set()
    for key, _, raw in records(text):
        if key in metadata.KEYS:
            if key in seen:
                raise Error('Duplicate managed environment setting.')
            seen.add(key)
            if key in replacements:
                result.append(replacements[key])
        else:
            result.append(raw)
    for key in metadata.KEYS:
        if key not in seen and key in replacements:
            result.append(replacements[key])
    output = ''
    for raw in result:
        # A previously final record may now precede a later administrator record.
        # Keep its value/quoting while retaining an assignment separator.
        if output and not output.endswith('\n') and raw:
            output += '\n'
        output += raw
    return output


def nginx_config(paths, host, port, *, tls):
    host = metadata.domain(host)
    http = f'''{MARKER}
server {{
    listen 80;
    server_name {host};
    access_log off;
    if ($host != {host}) {{ return 404; }}
    client_max_body_size 50m;
    location ^~ /.well-known/acme-challenge/ {{
        root {paths.acme};
        try_files $uri =404;
    }}
    location / {{ {'return 301 https://'+host+'$request_uri;' if tls else 'return 503;'} }}
}}
'''
    if not tls:
        return http
    return http + f'''server {{
    listen 443 ssl;
    server_name {host};
    access_log off;
    if ($host != {host}) {{ return 404; }}
    ssl_certificate {paths.certificates}/live/{host}/fullchain.pem;
    ssl_certificate_key {paths.certificates}/live/{host}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 50m;
    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port 443;
        proxy_connect_timeout 10s;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }}
}}
'''


def renewal_hook(paths, host):
    host = metadata.domain(host)
    return f'''#!/usr/bin/env bash
{MARKER}
set -euo pipefail
[[ "${{EUID}}" -eq 0 ]] || exit 1
[[ "${{RENEWED_LINEAGE:-}}" == "{paths.certificates}/live/{host}" ]] || exit 0
nginx -t
systemctl reload nginx
'''


class Manager:
    def __init__(self, paths=None, runner=None, *, owner_uid=0, root_gid=0,
                 service_gid=None, require_account=True):
        self.paths = paths or Paths()
        self.runner = runner or Runner()
        self.uid, self.gid = owner_uid, root_gid
        self.service_gid = service_gid
        self.require_account = require_account
        self.backup = None

    def command(self, args, *, timeout=60, check=True):
        result = self.runner.run(args, timeout=timeout)
        if check and result.returncode:
            raise Error('Deployment command failed: '+args[0]+' '+args[1]+'.')
        return result

    def ancestors(self, path):
        for parent in [path.parent, *path.parent.parents]:
            try:
                info = parent.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(info.st_mode) or info.st_uid not in ((self.uid,) if self.require_account else (0, self.uid)) or info.st_mode & 0o022:
                # /tmp is allowed only in explicitly injected test layouts; never production.
                if self.require_account or parent != Path('/tmp') and parent != Path('/private/tmp'):
                    raise Error('Unsafe deployment parent directory.')

    def read_file(self, path, *, mode=None, gid=None, missing=False, maximum=1024*1024):
        self.ancestors(path)
        try:
            fd = os.open(path, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        except FileNotFoundError:
            if missing:
                return None
            raise Error('Required deployment file missing.') from None
        except OSError:
            raise Error('Unsafe deployment file.') from None
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.uid
                    or info.st_gid != (self.gid if gid is None else gid)
                    or (mode is not None and stat.S_IMODE(info.st_mode) != mode)
                    or info.st_mode & 0o022 or info.st_size > maximum):
                raise Error('Unsafe deployment file ownership, type, permissions or size.')
            return stream.read(maximum+1)

    def publish(self, path, data, mode, gid=None):
        self.ancestors(path)
        # Refuse a path changed into a link/device since preflight.
        self.read_file(path, gid=gid, missing=True)
        if data is None:
            path.unlink(missing_ok=True)
            self.sync_dir(path.parent)
            return
        fd, temporary = tempfile.mkstemp(prefix='.httpsctl-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                os.fchmod(stream.fileno(), mode)
                os.fchown(stream.fileno(), self.uid, self.gid if gid is None else gid)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            self.sync_dir(path.parent)
        finally:
            Path(temporary).unlink(missing_ok=True)

    @staticmethod
    def sync_dir(path):
        fd = os.open(path, os.O_RDONLY|os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def environment(self, raw=None):
        raw = self.read_file(self.paths.install/'.env', mode=0o600) if raw is None else raw
        text = raw.decode('utf-8')
        seen = set()
        for key, _, _ in records(text):
            if key in metadata.KEYS:
                if key in seen:
                    raise Error('Duplicate managed environment setting.')
                seen.add(key)
        value = values(text)
        bind_host(value.get('APP_BIND_HOST', '0.0.0.0'))
        try:
            port = int(value.get('APP_PORT', '8899'))
        except ValueError:
            raise Error('Invalid application port.') from None
        if not 1 <= port <= 65535 or not value.get('SECRET_KEY'):
            raise Error('Invalid application environment.')
        if value.get('DOWNLOAD_URL_SCHEME', '') not in ('', 'http', 'https'):
            raise Error('Invalid download scheme.')
        return text, value, port

    def preflight(self):
        self.environment()
        unit = self.read_file(self.paths.unit, mode=0o644).decode('utf-8')
        if (re.findall(r'^User=(.*)$', unit, re.M) != ['clashyaml']
                or re.findall(r'^Group=(.*)$', unit, re.M) != ['clashyaml']):
            raise Error('Application service must use the dedicated non-root clashyaml account.')
        if self.require_account:
            user = pwd.getpwnam('clashyaml')
            group = grp.getgrnam('clashyaml')
            marker = self.read_file(self.paths.install/'.service-account', mode=0o600).decode().strip()
            if (user.pw_uid == 0 or user.pw_gid != group.gr_gid
                    or user.pw_gecos != 'Clash YAML Manager service'
                    or user.pw_dir != '/nonexistent' or user.pw_shell != '/usr/sbin/nologin'
                    or marker != f'clashyaml:{user.pw_uid}:{user.pw_gid}'):
                raise Error('Dedicated service account ownership unavailable.')
            self.service_gid = group.gr_gid
        if self.service_gid is None:
            raise Error('Service group unavailable.')

    def managed(self):
        # Check the parent chain in addition to metadata's file/schema checks.
        self.ancestors(self.paths.install/metadata.NAME)
        return metadata.read(self.paths.install, owner_uid=self.uid, group_gid=self.service_gid,
                             backup_root=self.paths.backups)

    def consistent(self, info):
        _, env, port = self.environment()
        if port != info['app_port'] or any(env.get(k) != v for k, v in info['managed_settings'].items()):
            raise Error('DRIFT: managed environment changed; restore reviewed settings before retrying.')
        for key, hash_key in (('nginx','nginx_config_sha256'), ('hook','hook_sha256'), ('unit','unit_sha256')):
            data = self.read_file(self.paths.files()[key], mode={'nginx':0o644,'hook':0o755,'unit':0o644}[key])
            if digest(data) != info[hash_key] or key != 'unit' and not data.startswith(MARKER.encode()) and not data.startswith(('#!/usr/bin/env bash\n'+MARKER).encode()):
                raise Error('DRIFT: managed integration changed; manual recovery required.')
        self.load_backup(Path(info['previous_backup']))

    def service_state(self):
        return {key: self.command(['systemctl', action, '--quiet', name], check=False).returncode == 0
                for key, action, name in (('app_active','is-active',SERVICE), ('nginx_active','is-active','nginx'),
                                         ('nginx_enabled','is-enabled','nginx'))}

    def snapshot(self):
        self.ancestors(self.paths.backups/'placeholder')
        folder = Path(tempfile.mkdtemp(prefix='clash-yaml-manager-https-backup-'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.', dir=self.paths.backups))
        os.chmod(folder, 0o700)
        os.chown(folder,self.uid,self.gid)
        manifest = dict(version=1, installation=str(self.paths.install), services=self.service_state(), files={}, written={})
        for name, path in self.paths.files().items():
            gid = self.service_gid if name == 'metadata' else self.gid
            raw = self.read_file(path, gid=gid, missing=True)
            mode = stat.S_IMODE(path.stat().st_mode) if raw is not None else None
            manifest['files'][name] = dict(present=raw is not None, mode=mode, sha256=digest(raw) if raw is not None else None)
            if raw is not None:
                self.publish(folder/name, raw, 0o600)
        self.write_manifest(folder, manifest)
        self.backup = folder
        return folder, manifest

    def write_manifest(self, folder, value):
        self.publish(folder/'manifest.json', json.dumps(value, sort_keys=True, indent=2).encode()+b'\n', 0o600)

    def load_backup(self, folder):
        if (not folder.is_absolute() or folder.parent != self.paths.backups
                or not metadata.BACKUP_NAME.fullmatch(folder.name)):
            raise Error('Invalid HTTPS backup path.')
        self.ancestors(folder/'manifest.json')
        if stat.S_IMODE(folder.stat().st_mode) != 0o700:
            raise Error('Unsafe HTTPS backup directory.')
        def unique(pairs):
            result = {}
            for key,item in pairs:
                if key in result:
                    raise Error('Duplicate HTTPS backup manifest field.')
                result[key] = item
            return result
        value = json.loads(self.read_file(folder/'manifest.json', mode=0o600),object_pairs_hook=unique)
        if (not isinstance(value,dict) or set(value) != {'version','installation','services','files','written'}
                or type(value['version']) is not int or value['version'] != 1
                or value['installation'] != str(self.paths.install)
                or set(value['services']) != {'app_active','nginx_active','nginx_enabled'}
                or any(type(v) is not bool for v in value['services'].values())
                or set(value['files']) != set(self.paths.files()) or not isinstance(value['written'],dict)
                or not set(value['written']) <= set(self.paths.files())):
            raise Error('Invalid HTTPS backup manifest.')
        expected = {'manifest.json'}
        for name, item in value['files'].items():
            if not isinstance(item,dict) or set(item) != {'present','mode','sha256'} or type(item['present']) is not bool:
                raise Error('Invalid HTTPS backup manifest.')
            if item['present']:
                allowed = {'env':(0o600,), 'unit':(0o644,), 'nginx':(0o644,), 'hook':(0o755,), 'metadata':(0o640,)}
                if item['mode'] not in allowed[name] or not isinstance(item['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',item['sha256']):
                    raise Error('Invalid HTTPS backup manifest.')
                if digest(self.read_file(folder/name,mode=0o600)) != item['sha256']:
                    raise Error('HTTPS backup checksum mismatch.')
                expected.add(name)
            elif item['mode'] is not None or item['sha256'] is not None:
                raise Error('Invalid HTTPS backup manifest.')
        if set(p.name for p in folder.iterdir()) != expected:
            raise Error('Unexpected HTTPS backup files.')
        for items in value['written'].values():
            if not isinstance(items,list) or any(v is not None and (not isinstance(v,str) or not re.fullmatch('[a-f0-9]{64}',v)) for v in items):
                raise Error('Invalid HTTPS backup manifest.')
        return value

    def write(self, folder, journal, name, data, mode):
        current = self.read_file(self.paths.files()[name],gid=self.service_gid if name == 'metadata' else None,missing=True)
        current_hash = digest(current) if current is not None else None
        if current_hash not in [journal['files'][name]['sha256'], *journal['written'].get(name,[])]:
            raise Error('Selected file changed outside the transaction; no overwrite performed.')
        journal['written'].setdefault(name, []).append(digest(data) if data is not None else None)
        self.write_manifest(folder, journal)  # durable intent before replace, including post-replace failures
        self.publish(self.paths.files()[name], data, mode, self.service_gid if name == 'metadata' else None)

    def restore(self, folder, journal):
        # Refuse unexpected concurrent/manual changes before touching any selected file.
        selected = list(journal['written'])
        for name in selected:
            raw = self.read_file(self.paths.files()[name], gid=self.service_gid if name == 'metadata' else None, missing=True)
            current = digest(raw) if raw is not None else None
            if current not in [journal['files'][name]['sha256'], *journal['written'][name]]:
                raise Error('Recovery stopped: selected file changed outside the transaction.')
        errors = []
        for name in selected:
            try:
                item = journal['files'][name]
                raw = self.read_file(folder/name, mode=0o600) if item['present'] else None
                self.publish(self.paths.files()[name], raw, item['mode'] or 0o600,
                             self.service_gid if name == 'metadata' else None)
            except Exception:
                errors.append(name)
        # Attempt both service restorations even if one fails.
        prior = journal['services']
        try:
            if 'unit' in selected:
                self.command(['systemctl','daemon-reload'])
            if 'env' in selected or 'unit' in selected:
                self.command(['systemctl','restart' if prior['app_active'] else 'stop',SERVICE])
                if prior['app_active']:
                    self.verify_app(self.environment()[2])
        except Exception:
            errors.append('application service')
        try:
            if 'nginx' in selected and self.runner.available('nginx'):
                self.command(['nginx','-t'])
                self.command(['systemctl','reload' if prior['nginx_active'] else 'stop','nginx'])
            # apt may have enabled/started nginx; restore recorded state even on apt failure.
            if self.runner.available('nginx'):
                if not prior['nginx_active']:
                    self.command(['systemctl','stop','nginx'])
                enabled = self.command(['systemctl','is-enabled','--quiet','nginx'],check=False).returncode == 0
                if enabled != prior['nginx_enabled']:
                    self.command(['systemctl','enable' if prior['nginx_enabled'] else 'disable','nginx'])
        except Exception:
            errors.append('nginx service')
        if errors:
            raise Error('Automatic recovery incomplete; retained private backup requires review.')

    @contextmanager
    def transaction(self):
        folder, journal = self.snapshot()
        try:
            yield folder, journal
        except BaseException as original:
            try:
                self.restore(folder, journal)
            except BaseException:
                raise Error('Automatic rollback incomplete. Review private backup: '+str(folder)) from None
            reason = str(original) if isinstance(original, Error) else 'Operation failed.'
            raise Error(reason+' Project state restored. Private backup: '+str(folder)) from original

    @contextmanager
    def locked(self):
        path = self.paths.install/'.httpsctl.lock'
        self.read_file(path, mode=0o600, missing=True)
        with file_lock(path, strict=True):
            self.read_file(path,mode=0o600)
            yield

    def packages(self):
        if all(self.runner.available(name) for name in ('nginx','certbot')):
            return
        if self.runner.distribution() not in ('debian','ubuntu'):
            raise Error('Automatic package installation supports Debian/Ubuntu only.')
        self.command(['apt-get','update'],timeout=600)
        self.command(['apt-get','install','-y','nginx','certbot'],timeout=600)

    def collisions(self, host):
        result = self.command(['ss','-H','-ltnp','( sport = :80 or sport = :443 )'])
        for line in result.stdout.splitlines():
            names = re.findall(r'\("([^"\n]+)"',line)
            if not names or any(name != 'nginx' for name in names):
                raise Error('Port 80/443 ownership conflict; no service was stopped.')
        if self.runner.available('nginx'):
            result = self.command(['nginx','-T'])
            source, sections = None, {}
            for line in result.stdout.splitlines():
                match = re.match(r'# configuration file (.+):$',line)
                if match:
                    source = match.group(1)
                elif source != str(self.paths.nginx):
                    sections.setdefault(source, []).append(line.split('#',1)[0])
            for lines in sections.values():
                for match in re.finditer(r'\bserver_name\s+([^;]+);','\n'.join(lines)):
                    tokens = [token.strip('"\x27').lower() for token in match.group(1).split()]
                    if host in tokens:
                        raise Error('Domain already claimed by another enabled Nginx configuration.')

    def mkdir(self, path, mode=0o755):
        self.ancestors(path)
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != self.uid or info.st_mode & 0o022:
                raise Error('Unsafe deployment directory.')
        else:
            path.mkdir(mode=mode)
            os.chown(path,self.uid,self.gid)
            self.sync_dir(path.parent)

    def certificates_present(self, host):
        directory = self.paths.certificates/'live'/host
        for name in ('fullchain.pem','privkey.pem'):
            path = directory/name
            # Certbot standard symlinks are the only permitted cross-directory references.
            self.ancestors(path)
            target = path.resolve(strict=True)
            if target != path and target.parent != self.paths.certificates/'archive'/host:
                raise Error('Unexpected certificate link target.')
            self.ancestors(target)
            info = target.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != self.uid or info.st_mode & 0o022 or not info.st_size:
                raise Error('Unsafe or missing certificate file.')
        return True

    def health(self, port, host=None):
        args = ['curl','--noproxy','*','--silent','--show-error','--output','/dev/null',
                '--write-out','%{http_code}','--connect-timeout','3','--max-time','10',
                '--retry','2','--retry-delay','1','--retry-connrefused','--retry-max-time','15']
        if host:
            args += ['--resolve',host+':443:127.0.0.1','--proto','=https','https://'+host+'/healthz']
        else:
            args += ['http://127.0.0.1:'+str(port)+'/healthz']
        result = self.command(args,timeout=40,check=False)
        return result.stdout.strip() if result.returncode == 0 and re.fullmatch(r'\d{3}',result.stdout.strip()) else 'Unavailable'

    def verify_app(self, port):
        self.command(['systemctl','is-active','--quiet',SERVICE])
        # curl's bounded retry handles Gunicorn's short startup interval, without external DNS.
        for _ in range(3):
            if self.health(port) == '200':
                return
        raise Error('Application local health did not return HTTP 200.')

    def restart_app(self, port):
        self.command(['systemctl','daemon-reload'])
        self.command(['systemctl','restart',SERVICE])
        self.verify_app(port)

    def activate_nginx(self):
        active = self.command(['systemctl','is-active','--quiet','nginx'],check=False).returncode == 0
        self.command(['systemctl','reload' if active else 'start','nginx'])
        self.command(['systemctl','is-active','--quiet','nginx'])

    def reload_existing_nginx(self):
        if self.runner.available('nginx'):
            self.command(['nginx','-t'])
            active = self.command(['systemctl','is-active','--quiet','nginx'],check=False).returncode == 0
            if active:
                self.command(['systemctl','reload','nginx'])
                self.command(['systemctl','is-active','--quiet','nginx'])

    def setup(self, host, registration):
        host, registration = metadata.domain(host), email(registration)
        with self.locked():
            self.preflight()
            info = self.managed()
            if info:
                self.consistent(info)
                if info['domain'] != host:
                    raise Error('Different managed domain: disable the current integration first.')
                self.certificates_present(host)
                self.command(['nginx','-t'])
                self.verify_app(info['app_port'])
                if self.health(info['app_port'],host) != '200':
                    raise Error('Existing managed TLS check failed; review status and renewal before retrying.')
                return 'Managed HTTPS already configured; no certificate request made.'
            for key in ('nginx','hook'):
                if self.read_file(self.paths.files()[key],missing=True) is not None:
                    raise Error('Integration path already exists without verified managed ownership.')
            self.collisions(host)
            text, _, port = self.environment()
            with self.transaction() as (folder, journal):
                if any(journal['files'][key]['present'] for key in ('nginx','hook','metadata')):
                    raise Error('Integration appeared during preflight; ownership requires review.')
                self.packages()
                self.mkdir(self.paths.acme)
                # apt must not introduce an exact-domain collision either.
                self.collisions(host)
                self.write(folder,journal,'nginx',nginx_config(self.paths,host,port,tls=False).encode(),0o644)
                self.command(['nginx','-t'])
                self.activate_nginx()
                self.command(['certbot','certonly','--webroot','--webroot-path',str(self.paths.acme),
                              '--domain',host,'--cert-name',host,'--email',registration,'--agree-tos',
                              '--non-interactive','--keep-until-expiring','--preferred-challenges','http'],timeout=300)
                self.certificates_present(host)
                self.write(folder,journal,'nginx',nginx_config(self.paths,host,port,tls=True).encode(),0o644)
                self.command(['nginx','-t'])
                # Standard Certbot hook parents may not exist on an older installation.
                for path in (self.paths.certificates/'renewal-hooks',self.paths.hook.parent):
                    self.mkdir(path)
                hook = renewal_hook(self.paths,host).encode()
                self.write(folder,journal,'hook',hook,0o755)
                replacements = {key:key+'='+value+'\n' for key,value in metadata.managed_settings(host).items()}
                self.write(folder,journal,'env',edit_env(text,replacements).encode(),0o600)
                unit = service_unit(self.paths.install,port,'127.0.0.1').encode()
                self.write(folder,journal,'unit',unit,0o644)
                self.restart_app(port)
                self.activate_nginx()
                if self.health(port,host) != '200':
                    raise Error('Verified local TLS health did not return HTTP 200.')
                info = dict(version=1,managed=True,domain=host,cert_mode='certbot-webroot',app_port=port,
                            configured_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00'),
                            nginx_config_sha256=digest(self.read_file(self.paths.nginx)),hook_sha256=digest(hook),
                            unit_sha256=digest(unit),managed_settings=metadata.managed_settings(host),previous_backup=str(folder))
                metadata.validate(info,self.paths.backups)
                self.write(folder,journal,'metadata',json.dumps(info,sort_keys=True,indent=2).encode()+b'\n',0o640)
            return 'Managed HTTPS configured for '+host+'. Private backup: '+str(folder)

    def disable(self):
        with self.locked():
            self.preflight()
            info = self.managed()
            if not info:
                return 'Managed HTTPS: NO; manual integrations left untouched.'
            self.consistent(info)
            prior = Path(info['previous_backup'])
            original = self.read_file(prior/'env',mode=0o600).decode()
            text, _, port = self.environment()
            replacement = {key:raw for key,_,raw in records(original) if key in metadata.KEYS}
            restored = edit_env(text,replacement).encode()
            _, env, _ = self.environment(restored)
            with self.transaction() as (folder,journal):
                self.write(folder,journal,'nginx',None,0o644)
                self.write(folder,journal,'hook',None,0o755)
                self.write(folder,journal,'env',restored,0o600)
                self.write(folder,journal,'unit',service_unit(self.paths.install,port,env.get('APP_BIND_HOST','0.0.0.0')).encode(),0o644)
                self.restart_app(port)
                self.reload_existing_nginx()
                self.write(folder,journal,'metadata',None,0o640)
            return 'Managed HTTPS disabled; prior five settings restored. Certificate data retained. Private backup: '+str(folder)

    def rollback(self, folder):
        with self.locked():
            self.preflight()
            journal = self.load_backup(folder)
            self.restore(folder,journal)
            return 'Known project files restored from private backup; certificate data retained.'

    def detach(self):
        """Uninstall cleanup; no app/env writes, preserve metadata for retained backup."""
        with self.locked():
            self.preflight()
            info = self.managed()
            if not info:
                return 'No managed HTTPS ownership; external integrations left untouched.'
            self.consistent(info)
            with self.transaction() as (folder,journal):
                self.write(folder,journal,'nginx',None,0o644)
                self.write(folder,journal,'hook',None,0o755)
                self.reload_existing_nginx()
            return 'Owned HTTPS integration detached; certificates and deployment metadata retained.'

    def status(self):
        # No lock, backups, mkdir, certificate issuance, or file writes.
        try:
            self.preflight()
            _, env, port = self.environment()
        except Exception:
            return 'Managed: DRIFT\nRuntime configuration unavailable; review ownership, bind, port and environment.'
        result = {'Managed':'NO','Application bind':bind_host(env.get('APP_BIND_HOST','0.0.0.0')),
                  'Secure cookies':'Enabled' if env.get('COOKIE_SECURE','').lower() == 'true' else 'Disabled',
                  'Trusted proxy headers':'Enabled' if env.get('TRUST_PROXY_HEADERS','').lower() == 'true' else 'Disabled',
                  'Download URL mode':'Explicit base' if env.get('DOWNLOAD_BASE_URL') else 'Scheme/default',
                  'Manual HTTPS flags':'Present' if env.get('DOWNLOAD_URL_SCHEME') == 'https' or env.get('DOWNLOAD_BASE_URL','').startswith('https://') else 'Absent'}
        try:
            info = self.managed()
            if info:
                result.update(Managed='YES',Domain=info['domain'])
                self.consistent(info)
                try:
                    self.certificates_present(info['domain'])
                    result['Certificate files'] = 'Present (not a validity verdict)'
                except Exception:
                    result['Certificate files'] = 'Missing/unavailable'
                result['Local verified TLS health'] = self.health(port,info['domain'])
        except Exception:
            result['Managed'] = 'DRIFT'
        result['App local health'] = self.health(port)
        if self.runner.available('nginx'):
            result['Nginx config test'] = 'PASS' if self.command(['nginx','-t'],check=False).returncode == 0 else 'FAIL'
        return '\n'.join(key+': '+value for key,value in result.items())


def cleanup_uninstall(directory):
    try:
        return Manager(Paths(install=Path(directory))).detach()
    except Error as exc:
        return 'HTTPS cleanup did not complete. '+str(exc)+' Manual review required.'
    except Exception:
        return 'HTTPS cleanup unavailable; ownership/drift and any retained private backup require manual review.'


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise Error('Invalid command/options; use status, setup --domain DOMAIN --email EMAIL, disable, or rollback --backup PATH.')


def main(argv=None):
    if os.geteuid() != 0:
        print('HTTPS deployment requires root over SSH.')
        return 1
    parser = SafeParser(description='SSH-only managed HTTPS deployment; DNS and public TCP 80/443 are operator prerequisites.')
    subs = parser.add_subparsers(dest='operation',required=True,parser_class=SafeParser)
    subs.add_parser('status')
    setup = subs.add_parser('setup')
    setup.add_argument('--domain',required=True)
    setup.add_argument('--email',required=True)
    subs.add_parser('disable')
    rollback = subs.add_parser('rollback')
    rollback.add_argument('--backup',required=True)
    def interrupted(signum, frame):
        raise Error('Deployment interrupted.')
    signal.signal(signal.SIGTERM,interrupted)
    signal.signal(signal.SIGINT,interrupted)
    try:
        args = parser.parse_args(argv)
        manager = Manager()
        if args.operation == 'setup':
            print('Prerequisites: DNS points here; public TCP 80/443 reachable. Packages/certificates may remain after rollback.')
            result = manager.setup(args.domain,args.email)
        elif args.operation == 'rollback':
            result = manager.rollback(Path(args.backup))
        else:
            result = getattr(manager,args.operation)()
        print(result)
        return 0
    except Error as exc:
        print(str(exc))
    except Exception:
        print('Deployment state invalid or unavailable; no raw configuration/command output disclosed.')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
