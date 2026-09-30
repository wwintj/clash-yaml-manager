"""Private MMDB transactions, with one verified memory reader per operation."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import time

from core import geoip
from core.refresh_schedule import timestamp
from core.state import StateError, atomic_write, file_lock, private_directory, read_private_bytes, write_json

MAX_DATABASE = 32 * 1024 * 1024  # Fits the existing 50 MiB multipart request limit.
ERROR = 'GeoIP database unavailable or invalid. Previous database is unchanged.'


class GeoIPError(ValueError):
    pass


class GeoIPStore:
    def __init__(self, state, *, reader_factory=None, clock=None):
        self.state = Path(state)
        self.directory = self.state / 'geoip'
        self.path = self.directory / 'active.mmdb'
        self.settings = self.state / 'settings.json'
        self.lock = self.state / 'geoip.lock'
        self.reader_factory = reader_factory
        self.clock = clock or time.time

    def _directories(self, create=False):
        for path in (self.state, self.directory):
            if path.is_symlink() or path.exists() and (not path.is_dir() or path.stat().st_mode & 0o077):
                raise StateError(ERROR)
            if not path.exists():
                if not create:
                    return False
                private_directory(path)
        return True

    @staticmethod
    def _optional(path, limit):
        return read_private_bytes(path, limit) if path.exists() or path.is_symlink() else None

    @staticmethod
    def _metadata(raw):
        def unique(pairs):
            data = {}
            for key, value in pairs:
                if key in data:
                    raise ValueError
                data[key] = value
            return data
        value = json.loads(raw, object_pairs_hook=unique) if raw is not None else {'version': 1, 'geoip': None}
        if not isinstance(value, dict) or set(value) != {'version', 'geoip'} or type(value['version']) is not int or value['version'] != 1:
            raise ValueError
        meta = value['geoip']
        if meta is not None and (not isinstance(meta, dict) or set(meta) != {'database_type', 'size', 'sha256', 'uploaded_at'}
                or not isinstance(meta['database_type'], str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}', meta['database_type'])
                or type(meta['size']) is not int or not 0 < meta['size'] <= MAX_DATABASE
                or not isinstance(meta['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', meta['sha256'])
                or not timestamp(meta['uploaded_at'])):
            raise ValueError
        return meta

    def _snapshot(self):
        if not self._directories():
            # No read-time directory/database creation; orphan metadata is invalid.
            if self.settings.exists() or self.settings.is_symlink():
                if self._metadata(read_private_bytes(self.settings, 65536)) is not None:
                    raise ValueError
            return None, None
        with file_lock(self.lock, blocking=False, strict=True):
            raw = self._optional(self.path, MAX_DATABASE)
            meta = self._metadata(self._optional(self.settings, 65536))
            if (raw is None) != (meta is None):
                raise ValueError
            if raw is not None and (len(raw) != meta['size'] or hashlib.sha256(raw).hexdigest() != meta['sha256']):
                raise ValueError
            return raw, meta

    @contextmanager
    def lookup(self, mode):
        geoip.normalize({'geoip': mode})
        if mode == 'off':
            yield None
            return
        reader = None
        try:
            raw, meta = self._snapshot()
            if raw is not None:
                reader = (self.reader_factory or geoip.open_reader)(raw)
                if geoip.database_type(reader) != meta['database_type']:
                    raise ValueError
        except Exception:
            if reader is not None:
                try: reader.close()
                except Exception: pass
            reader = None
        try:
            yield geoip.Lookup(reader)
        finally:
            if reader is not None:
                try: reader.close()
                except Exception: pass

    def status(self):
        reader = None
        try:
            raw, meta = self._snapshot()
            if raw is None:
                return {'status': 'Not installed'}
            reader = (self.reader_factory or geoip.open_reader)(raw)
            if geoip.database_type(reader) != meta['database_type']:
                raise ValueError
            return dict(meta, status='Ready', checksum_prefix=meta['sha256'][:12])
        except Exception:
            return {'status': 'Unavailable / Invalid'}
        finally:
            if reader is not None:
                try: reader.close()
                except Exception: pass

    @staticmethod
    def _restore(path, previous):
        if previous is None:
            if path.exists():
                path.unlink()
                fd = os.open(path.parent, os.O_RDONLY)
                try: os.fsync(fd)
                finally: os.close(fd)
        else:
            atomic_write(path, previous)

    def _transaction(self, payload, meta):
        self._directories(create=True)
        with file_lock(self.lock, strict=True):
            before = (self._optional(self.path, MAX_DATABASE), self._optional(self.settings, 65536))
            try:
                if payload is None:
                    if self.path.exists(): self.path.unlink()
                    fd = os.open(self.directory, os.O_RDONLY)
                    try: os.fsync(fd)
                    finally: os.close(fd)
                else:
                    atomic_write(self.path, payload)
                write_json(self.settings, {'version': 1, 'geoip': meta})
            except Exception:
                # Readers share the lock, so cannot observe the intermediate pair.
                for path, raw in zip((self.path, self.settings), before):
                    try: self._restore(path, raw)
                    except Exception: pass
                raise

    def upload(self, filename, stream):
        reader = None
        try:
            if not isinstance(filename, str) or not filename.lower().endswith('.mmdb'):
                raise ValueError
            payload = stream.read(MAX_DATABASE + 1)
            if not payload or len(payload) > MAX_DATABASE:
                raise ValueError
            # Private temporary data; never execute it or use the submitted path.
            self._directories(create=True)
            import tempfile
            with tempfile.TemporaryDirectory(prefix='.geoip-upload-', dir=self.state) as temporary:
                staged = Path(temporary) / 'candidate.mmdb'
                atomic_write(staged, payload)
                reader = (self.reader_factory or geoip.open_reader)(read_private_bytes(staged, MAX_DATABASE))
                kind = geoip.database_type(reader)
                reader.close(); reader = None
                meta = dict(database_type=kind, size=len(payload), sha256=hashlib.sha256(payload).hexdigest(), uploaded_at=self.clock())
                if not timestamp(meta['uploaded_at']): raise ValueError
                self._transaction(payload, meta)
        except Exception:
            raise GeoIPError(ERROR) from None
        finally:
            if reader is not None:
                try: reader.close()
                except Exception: pass

    def remove(self):
        try:
            self._transaction(None, None)
        except Exception:
            raise GeoIPError(ERROR) from None
