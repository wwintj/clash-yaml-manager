"""Locked private subscriptions; immutable candidate files + one atomic commit pointer.

The registry selects the current revision. Readers hold the same process-shared lock
until bytes have been read, so no response depends on a path after unlocking.
"""
import copy
from contextlib import contextmanager, nullcontext
import hashlib
import hmac
import logging
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import tempfile
import time
import uuid
from urllib.parse import unquote

from core import generator, fixed_sources, refresh_schedule, policy_engine, health_policy
from core.source_errors import SourceError
from core.state import StateError, atomic_write, file_lock, private_directory, read_json, write_json

ID = re.compile(r'[0-9a-f]{32}\Z')
TOKEN = re.compile(r'[A-Za-z0-9_-]{22}\Z')
PREFIX = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\Z')
SLUG = re.compile(r'([a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?)-fs_([A-Za-z0-9_-]{22})\Z')
STATE_ERROR = '固定订阅状态不可用，请检查 state/ 并从备份恢复。'


class FixedBearerFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        # Access loggers may retain percent-encoded route characters. Match the
        # decoded path, then suppress the whole request record rather than risk
        # retaining an encoded alias of the bearer in another request field.
        if re.search(r'/s/[^\s?"<>]*-fs_', unquote(message)):
            message = 'Fixed subscription request [fixed-redacted].'
        record.msg = message
        record.args = ()
        return True


class GenerationError(ValueError):
    """A fixed message; never expose source nodes or YAML parser exceptions."""


def normalize_prefix(value):
    value = re.sub(r'[^a-z0-9-]+', '-', value.lower())
    return re.sub('-+', '-', value).strip('-')[:64].rstrip('-') or 'subscription'


def token_hash(token):
    return hashlib.sha256(token.encode('ascii')).hexdigest()


def valid_source(source):
    try:
        return (source['yaml_source'] in ('default', 'custom')
                and isinstance(source['batch_nodes'], str)
                and isinstance(source['aux_nodes'], list)
                and all(isinstance(r, dict) and set(r) == {'country', 'name', 'link'}
                        and all(isinstance(v, str) for v in r.values()) for r in source['aux_nodes'])
                and isinstance(source['node_overrides'], dict)
                and all(isinstance(k, str) and isinstance(v, dict)
                        and all(f in ('name', 'country') and isinstance(s, str) for f, s in v.items())
                        for k, v in source['node_overrides'].items())
                and isinstance(source['special_groups'], list)
                and all(isinstance(g, str) for g in source['special_groups']))
    except (KeyError, TypeError):
        return False


class FixedSubscriptions:
    def __init__(self, state_directory):
        self.state = private_directory(state_directory)
        self.directory = private_directory(self.state / 'fixed_subscriptions')
        self.path = self.state / 'fixed_subscriptions.json'
        self.lock = self.state / 'fixed_subscriptions.lock'

    def _directories(self, *parts):
        for path in (self.state, self.directory):
            if path.is_symlink() or not path.is_dir() or path.stat().st_mode & 0o077:
                raise StateError(STATE_ERROR)
        path = self.directory
        for part in parts:
            if not ID.fullmatch(part):
                raise StateError(STATE_ERROR)
            path = path / part
            if path.is_symlink() or not path.is_dir() or path.stat().st_mode & 0o077:
                raise StateError(STATE_ERROR)
        return path

    @contextmanager
    def _locked(self):
        self._directories()  # Reject replaced directory symlinks before opening the lock.
        with file_lock(self.lock, strict=True):
            yield

    @staticmethod
    def _allocate(parent, reserved=()):
        for _ in range(128):
            path = parent / uuid.uuid4().hex
            if path.name in reserved:
                continue
            try:
                path.mkdir(mode=0o700)  # Never reuse an existing internal id or revision.
            except FileExistsError:
                continue
            fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(fd)  # Make the candidate's directory entry durable before commit.
            finally:
                os.close(fd)
            return path
        raise StateError(STATE_ERROR)

    def _read(self):
        self._directories()
        if self.path.exists() or self.path.is_symlink():
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise StateError(STATE_ERROR)
            data = read_json(self.path)
        else:
            data = {'version': 1, 'subscriptions': {}, 'retired_tokens': []}
        def require(condition):
            if not condition:
                raise ValueError
        try:
            require(type(data['version']) is int and data['version'] in (1, 2, 3, 4, 5))
            require(isinstance(data['subscriptions'], dict) and isinstance(data['retired_tokens'], list))
            require(all(isinstance(t, str) and re.fullmatch('[0-9a-f]{64}', t) for t in data['retired_tokens']))
            used = set(data['retired_tokens'])
            require(len(used) == len(data['retired_tokens']))
            for key, entry in data['subscriptions'].items():
                require(ID.fullmatch(key) and entry['id'] == key and ID.fullmatch(entry['revision']))
                require(isinstance(entry['name'], str) and 0 < len(entry['name'].strip()) <= 128)
                require(PREFIX.fullmatch(entry['prefix']) and TOKEN.fullmatch(entry['token']))
                require(entry['status'] in ('active', 'disabled') and valid_source(entry))
                if data['version'] == 1:
                    # Existing subscription UUID is already server-generated and stable.
                    entry['sources'] = [fixed_sources.manual(entry['id'], entry['node_count'])]
                require(fixed_sources.valid(entry['sources'], schedules=data['version'] >= 3))
                if data['version'] < 3:
                    for item in entry['sources']:
                        if item['type'] == 'remote_url':
                            item.update(refresh_schedule.defaults())
                if data['version'] < 4:
                    entry['policy_config'] = policy_engine.defaults()
                else:
                    entry['policy_config'] = policy_engine.normalize(entry['policy_config'])
                if data['version'] < 5:
                    entry['health_policy'] = health_policy.defaults()
                    entry['health_policy_audit'] = health_policy.audit_defaults()
                else:
                    entry['health_policy'] = health_policy.normalize(entry['health_policy'])
                    require(health_policy.valid_audit(entry['health_policy_audit']))
                digest = token_hash(entry['token'])
                require(digest not in used)
                used.add(digest)
                for field in ('created_at', 'updated_at', 'last_access_at'):
                    v = entry[field]
                    require((field == 'last_access_at' and v is None) or (
                        type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 253402300799))
                for field in ('node_count', 'group_count', 'rule_count'):
                    require(type(entry[field]) is int and entry[field] >= 0)
        except (KeyError, TypeError, ValueError):
            raise StateError(STATE_ERROR) from None
        return data

    def _commit(self, data, migrate=True):
        data = copy.deepcopy(data)
        if migrate:
            data['version'] = 5
        elif data['version'] == 1:
            for entry in data['subscriptions'].values():
                entry.pop('sources', None)
        elif data['version'] == 2:
            for entry in data['subscriptions'].values():
                for item in entry['sources']:
                    for field in refresh_schedule.FIELDS:
                        item.pop(field, None)
        if not migrate and data['version'] < 4:
            for entry in data['subscriptions'].values():
                entry.pop('policy_config', None)
        if not migrate and data['version'] < 5:
            for entry in data['subscriptions'].values():
                entry.pop('health_policy', None)
                entry.pop('health_policy_audit', None)
        # atomic_write may report a directory-fsync error after os.replace. Restore
        # the old registry in that case before exposing an unsuccessful mutation.
        previous = self.path.read_bytes() if self.path.exists() else None
        try:
            write_json(self.path, data)
        except OSError:
            if previous is not None:
                atomic_write(self.path, previous)
            elif self.path.exists():
                self.path.unlink()
            raise StateError(STATE_ERROR) from None

    def _new_token(self, data):
        used = set(data['retired_tokens']) | {token_hash(r['token']) for r in data['subscriptions'].values()}
        for _ in range(128):
            token = secrets.token_urlsafe(16)  # 128 random bits, exactly 22 URL-safe chars.
            if TOKEN.fullmatch(token) and token_hash(token) not in used:
                return token
        raise StateError(STATE_ERROR)

    @staticmethod
    def slug(entry):
        return entry['prefix'] + '-fs_' + entry['token']

    @staticmethod
    def _file(path):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                    raise StateError(STATE_ERROR)
                return stream.read()
        except OSError:
            raise StateError(STATE_ERROR) from None

    def _content(self, entry, filename):
        return self._file(self._directories(entry['id'], entry['revision']) / filename)

    def list(self):
        with self._locked():
            return copy.deepcopy(list(self._read()['subscriptions'].values()))

    def get(self, key):
        with self._locked():
            return copy.deepcopy(self._read()['subscriptions'].get(key))

    def _payload(self, entry, identifier):
        revision = self._directories(entry['id'], entry['revision'])
        for part in ('sources', identifier):
            revision = revision / part
            if revision.is_symlink() or not revision.is_dir() or revision.stat().st_mode & 0o077:
                raise StateError(STATE_ERROR)
        return self._file(revision / 'payload.bin')

    @staticmethod
    def _identity(entry):
        # Public access statistics may advance while fetching; management must not.
        return {k: v for k, v in entry.items() if k not in ('last_access_at', 'health_policy_audit')} if entry else None

    def save(self, key, name, prefix, source, parsed, default_path, custom=None,
             sources=None, uploads=None, refresh=None, expected=None, trigger='save', clock=None,
             _cached=False, _health=None):
        clock = clock or time.time
        source = copy.deepcopy(source)
        if not isinstance(source, dict):
            raise GenerationError('请检查订阅名称和配置。')
        source['policy_config'] = policy_engine.normalize(source.get('policy_config', policy_engine.defaults()))
        source['health_policy'] = health_policy.normalize(source.get('health_policy', health_policy.defaults()))
        if not isinstance(name, str) or not 0 < len(name.strip()) <= 128 or not valid_source(source):
            raise GenerationError('请检查订阅名称和配置。')
        if parsed['errors']:
            raise GenerationError('节点无效，请检查节点及手工修改。')
        # Snapshot every byte needed later before releasing the shared lock. Other
        # workers may delete/collect the selected revision during network work.
        with self._locked():
            data = self._read()
            old = copy.deepcopy(data['subscriptions'].get(key)) if key else None
            if key and old is None:
                if expected is not None:
                    raise SourceError('conflict')
                raise KeyError(key)
            if expected is not None and self._identity(old) != self._identity(expected):
                raise SourceError('conflict')
            old_content = self._content(old, 'current.yaml') if old else None
            if _cached:
                if not old: raise KeyError(key)
                base_snapshot = self._content(old, 'base.yaml')
            previous = old['sources'] if old else [fixed_sources.manual()]
            configured = copy.deepcopy(previous) if _cached else fixed_sources.configure(previous, sources)
            caches = {item['id']: self._payload(old, item['id']) for item in previous
                      if item['type'] != 'manual' and item['last_success_at'] is not None}
            if source['yaml_source'] == 'custom' and custom is None:
                if not old or old['yaml_source'] != 'custom':
                    raise GenerationError('请选择 Custom YAML。')
                custom = self._content(old, 'base.yaml')
        enabled = source['health_policy']['mode']=='exclude-unhealthy'
        health = _health if enabled else None
        if custom is not None and len(custom) > 50 * 1024 * 1024:
            raise GenerationError('上传文件过大，最大支持 50MB。')
        # Staging outside subscription homes prevents GC/delete from touching an
        # in-flight candidate. No durable pointer references this temporary tree.
        with tempfile.TemporaryDirectory(prefix='.fixed-candidate-', dir=self.state) as scratch:
            candidate = self._allocate(Path(scratch))
            revision = candidate.name
            if _cached:
                aggregate, payloads = fixed_sources.aggregate_cached(configured,caches,parsed)
            else:
                aggregate, payloads = fixed_sources.prepare(configured, previous, caches,
                                                            uploads or {}, parsed, refresh, trigger, clock)
            base_bytes = (base_snapshot if _cached else custom if source['yaml_source'] == 'custom'
                          else Path(default_path).read_bytes())
            # Capture after provider work. One observation/time snapshot for this generation.
            if enabled and _health is None: health = health_policy.snapshot(self,key)
            at = clock()
            audit = health_policy.audit_defaults()
            def transform(data):
                nonlocal audit
                audit = health_policy.apply(data,aggregate['nodes'],aggregate['countries'],
                    source['special_groups'],source['policy_config'],source['health_policy'],health,at)
            atomic_write(candidate / 'base.yaml', base_bytes)
            if payloads:
                source_root = private_directory(candidate / 'sources')
                for identifier, payload in payloads.items():
                    target = private_directory(source_root / identifier)
                    atomic_write(target / 'payload.bin', payload)
                fd = os.open(source_root, os.O_RDONLY)
                try:
                    os.fsync(fd)  # Persist the source-id directory entries too.
                finally:
                    os.close(fd)
            out = private_directory(Path(scratch) / 'output')
            backups = private_directory(Path(scratch) / 'backup')
            result = generator.generate(candidate / 'base.yaml', out, backups, aggregate, source['special_groups'], source['policy_config'], transform if enabled else None)
            if not result['success']:
                raise GenerationError('生成失败，请检查节点、YAML 结构及策略组引用。旧订阅保持不变。')
            content = Path(result['output_path']).read_bytes()
            atomic_write(candidate / 'current.yaml', content)
            audit = health_policy.finish(audit, content != old_content)
            with self._locked():
                data = self._read()
                current = data['subscriptions'].get(key) if key else None
                if self._identity(current) != self._identity(old):
                    raise SourceError('conflict')
                with health_policy.guard(self,key,health) if enabled and old else nullcontext():
                    if _cached and content == old_content:
                        current['health_policy_audit'] = audit
                        self._commit(data)
                        return copy.deepcopy(current)
                    home = self._directories(key) if old else self._allocate(self.directory, data['subscriptions'])
                    key = home.name
                    selected = home / revision
                    if selected.exists() or selected.is_symlink():
                        raise StateError(STATE_ERROR)  # Never replace an existing revision, even on a UUID collision.
                    try:
                        os.rename(candidate, selected)
                        fd = os.open(home, os.O_RDONLY)
                        try:
                            os.fsync(fd)
                        finally:
                            os.close(fd)
                        now = clock()
                        entry = dict(source, health_policy_audit=audit, sources=configured, id=key, name=name.strip(),
                                     prefix=normalize_prefix(prefix or name), revision=revision,
                                     token=old['token'] if old else self._new_token(data),
                                     status=old['status'] if old else 'active',
                                     created_at=old['created_at'] if old else now, updated_at=now,
                                     last_access_at=current['last_access_at'] if current else None,
                                     node_count=result['new_node_count'], group_count=result['group_count'],
                                     rule_count=result['rule_count'])
                        data['subscriptions'][key] = entry
                        self._commit(data)
                    except BaseException:
                        referenced = True
                        try:
                            referenced = self._read()['subscriptions'].get(key, {}).get('revision') == revision
                        except (StateError, OSError):
                            pass
                        if not referenced:
                            if selected.exists():
                                shutil.rmtree(selected)
                            if not old:
                                home.rmdir()
                        raise
                self._collect(home, revision)
                return copy.deepcopy(entry)

    def source_action(self, key, action, default_path, identifier=None, clock=None):
        entry = self.get(key)
        if not entry:
            raise KeyError(key)
        sources = copy.deepcopy(entry['sources'][1:])
        selected = next((s for s in sources if s['id'] == identifier), None)
        refresh = set()
        if action == 'refresh-all':
            refresh = {s['id'] for s in sources if s['type'] == 'remote_url' and s['enabled']}
        elif selected is None:
            raise KeyError(identifier)
        elif action == 'refresh' and selected['type'] == 'remote_url' and selected['enabled']:
            refresh = {identifier}
        elif action == 'delete':
            sources.remove(selected)
        elif action in ('enable', 'disable'):
            selected['enabled'] = action == 'enable'
            if selected['enabled'] and selected['type'] == 'remote_url':
                refresh = {identifier}
        else:
            raise SourceError('config')
        source = {k: entry[k] for k in ('yaml_source', 'batch_nodes', 'aux_nodes', 'node_overrides', 'special_groups', 'policy_config', 'health_policy')}
        parsed = generator.parse_form_nodes(dict(batch_nodes=entry['batch_nodes'],
            aux_nodes=json.dumps(entry['aux_nodes']), node_overrides=json.dumps(entry['node_overrides'])))
        return self.save(key, entry['name'], entry['prefix'], source, parsed, default_path,
                         sources=sources, refresh=refresh, expected=entry, trigger='manual', clock=clock)

    def refresh_sources(self, entry, identifiers, default_path, trigger='auto', clock=None):
        """Regenerate one subscription once for a selected set of due sources."""
        available = {s['id'] for s in entry['sources'] if s['type'] == 'remote_url' and s['enabled']}
        if not identifiers or not set(identifiers) <= available:
            raise StateError(STATE_ERROR)
        source = {k: entry[k] for k in ('yaml_source', 'batch_nodes', 'aux_nodes', 'node_overrides', 'special_groups', 'policy_config', 'health_policy')}
        parsed = generator.parse_form_nodes(dict(batch_nodes=entry['batch_nodes'],
            aux_nodes=json.dumps(entry['aux_nodes']), node_overrides=json.dumps(entry['node_overrides'])))
        return self.save(entry['id'], entry['name'], entry['prefix'], source, parsed, default_path,
                         sources=entry['sources'][1:], refresh=set(identifiers), expected=entry,
                         trigger=trigger, clock=clock)

    def reconcile_health_policy(self, key, *, clock=None, automatic=False):
        clock = clock or time.time
        expected, health = None, None
        try:
            expected = self.get(key)
            if (not expected or not health_policy.applicable(expected)
                    or automatic and expected['status']!='active'):
                return 'off'
            health = health_policy.snapshot(self,key)
            source = {k:expected[k] for k in ('yaml_source','batch_nodes','aux_nodes',
                'node_overrides','special_groups','policy_config','health_policy')}
            parsed = generator.parse_form_nodes(dict(batch_nodes=expected['batch_nodes'],
                aux_nodes=json.dumps(expected['aux_nodes']),node_overrides=json.dumps(expected['node_overrides'])))
            result = self.save(key,expected['name'],expected['prefix'],source,parsed,None,
                expected=expected,clock=clock,_cached=True,_health=health)
            audit = result['health_policy_audit']
            logging.getLogger(__name__).info(
                'Health policy subscription=%s result=%s filtered=%d excluded=%d fail_open=%d',
                key,audit['result'],audit['groups_filtered'],audit['candidates_excluded'],audit['groups_fail_open'])
            return audit['result']
        except SourceError as error:
            if error.code == 'conflict':
                logging.getLogger(__name__).info('Health policy subscription=%s result=conflict',key)
                return 'error'
        except Exception:
            pass
        # Successful observations are never rolled back. Error metadata only, while current.
        if expected is not None:
            try:
                with self._locked():
                    data=self._read(); current=data['subscriptions'].get(key)
                    if self._identity(current)==self._identity(expected):
                        with health_policy.guard(self,key,health) if health else nullcontext():
                            audit=health_policy.audit_defaults()
                            audit.update(last_reconciled_at=clock(),result='error')
                            current['health_policy_audit']=audit
                            self._commit(data)
            except Exception:
                pass
        logging.getLogger(__name__).warning('Health policy subscription=%s result=error; previous YAML retained.',key)
        return 'error'

    def record_refresh_error(self, snapshot, identifiers, code, clock=None):
        """A failed candidate may update retry metadata only while its snapshot is current.

        Never annotate a newer user revision with stale outcomes. Keep the selected
        payload/output/configuration unchanged when an auto transaction fails.
        """
        clock = clock or time.time
        with self._locked():
            data = self._read()
            entry = data['subscriptions'].get(snapshot['id'])
            if self._identity(entry) != self._identity(snapshot):
                return False
            for item in entry['sources']:
                if item['id'] in identifiers and item['type'] == 'remote_url':
                    item['using_cache'] = item['last_success_at'] is not None
                    refresh_schedule.record(item, 'auto', 'error', clock(), code)
            entry['updated_at'] = clock()
            self._commit(data)
            return True

    def _collect(self, home, keep=None):
        # No history feature. Unreferenced revisions from a crash are also removed
        # on the next successful management mutation, never by output retention.
        try:
            children = list(home.iterdir())
        except OSError:
            return
        for child in children:
            if ID.fullmatch(child.name) and child.name != keep:
                if child.is_symlink():
                    continue
                try:
                    shutil.rmtree(child)
                except OSError:
                    pass  # Committed data is safe; later mutation retries cleanup.

    def snapshot(self, key):
        """Snapshot only committed output for observational subsystems, without stats writes."""
        with self._locked():
            entry = self._read()['subscriptions'].get(key)
            if not entry:
                raise KeyError(key)
            return copy.deepcopy(entry), self._content(entry, 'current.yaml')

    @contextmanager
    def revision_guard(self, key, revision):
        """Keep the revision current during a short auxiliary-state commit. No network here."""
        with self._locked():
            entries = self._read()['subscriptions']
            if key not in entries or entries[key]['revision'] != revision:
                raise SourceError('conflict')
            yield set(entries)

    def action(self, key, action):
        with self._locked():
            data = self._read()
            entry = data['subscriptions'].get(key)
            if not entry:
                raise KeyError(key)
            self._directories(key)
            if action in ('regenerate', 'delete'):
                data['retired_tokens'].append(token_hash(entry['token']))
            if action == 'regenerate':
                entry['token'] = self._new_token(data)
            elif action in ('enable', 'disable'):
                entry['status'] = 'active' if action == 'enable' else 'disabled'
            elif action == 'delete':
                del data['subscriptions'][key]
            else:
                raise ValueError('Invalid action')
            entry['updated_at'] = time.time()
            self._commit(data)
            if action == 'delete':
                shutil.rmtree(self._directories(key))
            result = copy.deepcopy(entry)
        if action == 'delete':
            # Auxiliary cleanup must never roll back an authoritative deletion.
            try:
                from core.node_health import NodeHealth
                NodeHealth(self).remove(key)
            except Exception:
                pass
            try:
                from core.proxy_health import ProxyHealth
                ProxyHealth(self).remove(key)
            except Exception:
                pass
        return result

    def resolve(self, slug):
        match = SLUG.fullmatch(slug)
        if not match:
            return None
        prefix, token = match.groups()
        with self._locked():
            data = self._read()
            for entry in data['subscriptions'].values():
                authorized = hmac.compare_digest(token, entry['token'])
                if not authorized or entry['prefix'] != prefix or entry['status'] != 'active':
                    continue
                try:
                    content = self._content(entry, 'current.yaml')
                except StateError:
                    return None
                now = time.time()
                if entry['last_access_at'] is None or now - entry['last_access_at'] >= 60:
                    entry['last_access_at'] = now
                    try:
                        self._commit(data, migrate=False)
                    except (OSError, StateError):
                        # Access statistics must not make a previously published
                        # subscription unavailable on a full/read-only disk. Still
                        # fail closed if the registry itself cannot be validated.
                        self._read()
                return content
            return None
