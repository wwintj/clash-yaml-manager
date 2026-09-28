"""Locked private subscriptions; immutable candidate files + one atomic commit pointer.

The registry selects the current revision. Readers hold the same process-shared lock
until bytes have been read, so no response depends on a path after unlocking.
"""
import copy
from contextlib import contextmanager
import hashlib
import hmac
import logging
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

from core import generator
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
        with file_lock(self.lock):
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
            require(type(data['version']) is int and data['version'] == 1)
            require(isinstance(data['subscriptions'], dict) and isinstance(data['retired_tokens'], list))
            require(all(isinstance(t, str) and re.fullmatch('[0-9a-f]{64}', t) for t in data['retired_tokens']))
            used = set(data['retired_tokens'])
            require(len(used) == len(data['retired_tokens']))
            for key, entry in data['subscriptions'].items():
                require(ID.fullmatch(key) and entry['id'] == key and ID.fullmatch(entry['revision']))
                require(isinstance(entry['name'], str) and 0 < len(entry['name'].strip()) <= 128)
                require(PREFIX.fullmatch(entry['prefix']) and TOKEN.fullmatch(entry['token']))
                require(entry['status'] in ('active', 'disabled') and valid_source(entry))
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

    def _commit(self, data):
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

    def save(self, key, name, prefix, source, parsed, default_path, custom=None):
        if not isinstance(name, str) or not 0 < len(name.strip()) <= 128 or not valid_source(source):
            raise GenerationError('请检查订阅名称和配置。')
        if parsed['errors'] or not parsed['nodes']:
            raise GenerationError('节点无效或为空，请检查节点及手工修改。')
        with self._locked():
            data = self._read()
            old = data['subscriptions'].get(key) if key else None
            if key and old is None:
                raise KeyError(key)
            if old:
                self._content(old, 'current.yaml')
                home = self._directories(key)
            else:
                home = self._allocate(self.directory, data['subscriptions'])
                key = home.name
            candidate = self._allocate(home)
            revision = candidate.name
            try:
                if source['yaml_source'] == 'custom':
                    if custom is None:
                        if not old or old['yaml_source'] != 'custom':
                            raise GenerationError('请选择 Custom YAML。')
                        custom = self._content(old, 'base.yaml')
                    if len(custom) > 50 * 1024 * 1024:
                        raise GenerationError('上传文件过大，最大支持 50MB。')
                    atomic_write(candidate / 'base.yaml', custom)
                    base = candidate / 'base.yaml'
                else:
                    base = default_path
                with tempfile.TemporaryDirectory(prefix='.generate-', dir=home) as scratch:
                    out = private_directory(Path(scratch) / 'output')
                    backups = private_directory(Path(scratch) / 'backup')
                    result = generator.generate(base, out, backups, parsed, source['special_groups'])
                    if not result['success']:
                        raise GenerationError('生成失败，请检查节点、YAML 结构及策略组引用。旧订阅保持不变。')
                    atomic_write(candidate / 'current.yaml', Path(result['output_path']).read_bytes())
                now = time.time()
                entry = dict(source, id=key, name=name.strip(), prefix=normalize_prefix(prefix or name),
                             revision=revision, token=old['token'] if old else self._new_token(data),
                             status=old['status'] if old else 'active',
                             created_at=old['created_at'] if old else now, updated_at=now,
                             last_access_at=old['last_access_at'] if old else None,
                             node_count=result['new_node_count'], group_count=result['group_count'],
                             rule_count=result['rule_count'])
                data['subscriptions'][key] = entry
                self._commit(data)  # The only visible commit point: config and bytes agree.
            except BaseException:
                # If even rollback I/O fails, preserve complete candidate bytes;
                # never delete files the registry might still reference.
                referenced = True
                try:
                    referenced = self._read()['subscriptions'].get(key, {}).get('revision') == revision
                except (StateError, OSError):
                    pass
                if not referenced:
                    shutil.rmtree(candidate)
                    if not old:
                        home.rmdir()
                raise
            self._collect(home, revision)
            return copy.deepcopy(entry)

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
            return copy.deepcopy(entry)

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
                        self._commit(data)
                    except (OSError, StateError):
                        # Access statistics must not make a previously published
                        # subscription unavailable on a full/read-only disk. Still
                        # fail closed if the registry itself cannot be validated.
                        self._read()
                return content
            return None
