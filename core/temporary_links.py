"""Private, atomic, process-shared temporary bearer links with permanent tombstones."""
import math
import re
import secrets
import time
from core.state import StateError, file_lock, private_directory, read_json, write_json
from core.subscriptions import safe_filename

ID_PATTERN = re.compile(r'[A-Za-z0-9_-]{16}\Z')


class TemporaryLinks:
    def __init__(self, directory):
        directory = private_directory(directory)
        self.path = directory / 'temporary_links.json'
        self.lock = directory / 'temporary_links.lock'

    def _read(self):
        data = read_json(self.path) if self.path.exists() or self.path.is_symlink() else {'version': 1, 'links': {}}
        try:
            if data['version'] != 1 or not isinstance(data['links'], dict):
                raise ValueError
            for key, value in data['links'].items():
                if not ID_PATTERN.fullmatch(key):
                    raise ValueError
                if value is not None and (not isinstance(value, dict) or not safe_filename(value['filename'])
                        or not isinstance(value['created_at'], (int, float))
                        or not isinstance(value['expires_at'], (int, float))
                        or not math.isfinite(value['created_at']) or not math.isfinite(value['expires_at'])
                        or value['expires_at'] <= value['created_at']):
                    raise ValueError
        except (KeyError, TypeError, ValueError):
            raise StateError('临时链接状态无效，请检查或恢复备份。') from None
        return data

    @staticmethod
    def _prune(data, now):
        for key, entry in data['links'].items():
            if entry is not None and entry['expires_at'] <= now:
                data['links'][key] = None  # Permanent reservation, never bind this ID again.

    def create(self, filename, lifetime=86400, now=None):
        if not safe_filename(filename) or lifetime <= 0:
            raise ValueError('Invalid temporary output.')
        now = time.time() if now is None else now
        with file_lock(self.lock):
            data = self._read()
            self._prune(data, now)
            for _ in range(128):
                key = secrets.token_urlsafe(12)  # 96 random bits -> exactly 16 URL-safe chars.
                if ID_PATTERN.fullmatch(key) and key not in data['links']:
                    entry = dict(filename=filename, created_at=now, expires_at=now + lifetime)
                    data['links'][key] = entry
                    write_json(self.path, data)
                    return key, entry
            raise StateError('无法分配临时链接，请重试。')

    def resolve(self, key, now=None):
        if not ID_PATTERN.fullmatch(key):
            return None
        now = time.time() if now is None else now
        with file_lock(self.lock):
            data = self._read()
            entry = data['links'].get(key)
            if entry is not None and entry['expires_at'] <= now:
                data['links'][key] = None
                write_json(self.path, data)
                return None
            return entry

    def revoke_file(self, filename):
        with file_lock(self.lock):
            data = self._read()
            changed = False
            for key, entry in data['links'].items():
                if entry is not None and entry['filename'] == filename:
                    data['links'][key] = None
                    changed = True
            if changed:
                write_json(self.path, data)

    def prune(self, now=None):
        with file_lock(self.lock):
            data = self._read()
            self._prune(data, time.time() if now is None else now)
            write_json(self.path, data)
