"""Hashed credentials shared by all workers. No runtime writes to .env."""
import base64
from datetime import datetime, timezone
import re
import secrets

from werkzeug.security import check_password_hash, generate_password_hash

from core.state import StateError, file_lock, private_directory, read_json, write_json

# Explicit Werkzeug-supported method, also available in macOS Python without scrypt.
PASSWORD_METHOD = 'pbkdf2:sha256:1000000'
CREDENTIAL_KEYS = ('APP_PASSWORD_HASH', 'APP_PASSWORD_B64', 'APP_PASSWORD')


def valid_hash(value):
    return isinstance(value, str) and bool(re.fullmatch(
        r'(?:pbkdf2:sha256:[1-9][0-9]*|scrypt:[1-9][0-9]*:[1-9][0-9]*:[1-9][0-9]*)\$[A-Za-z0-9]+\$[0-9a-f]+', value))


def legacy_hash(environ):
    """Migration priority is HASH > B64 > plaintext. Never downgrade on errors."""
    try:
        if environ.get('APP_PASSWORD_HASH'):
            value = environ['APP_PASSWORD_HASH']
            if not valid_hash(value):
                raise ValueError
            check_password_hash(value, 'migration-format-check')
            return value
        if environ.get('APP_PASSWORD_B64'):
            password = base64.b64decode(environ['APP_PASSWORD_B64'], validate=True).decode('utf-8')
        else:
            password = environ.get('APP_PASSWORD', '')
        if not password:
            raise ValueError
        return generate_password_hash(password, method=PASSWORD_METHOD)
    except (ValueError, TypeError, UnicodeError, AttributeError):
        raise StateError('缺少有效认证状态或兼容凭据，迁移未完成。') from None


class AuthStore:
    def __init__(self, directory):
        self.directory = private_directory(directory)
        self.path = self.directory / 'auth.json'
        self.lock_path = self.directory / 'auth.lock'

    def _read(self):
        value = read_json(self.path)
        if (not isinstance(value, dict) or value.get('version') != 1 or
                type(value.get('auth_version')) is not int or value['auth_version'] < 1 or
                not isinstance(value.get('instance_id'), str) or
                not re.fullmatch(r'[0-9a-f]{32}', value['instance_id']) or
                not valid_hash(value.get('password_hash'))):
            raise StateError('认证状态结构无效，请从备份恢复。')
        return value

    def initialize(self, environ):
        """First worker hashes legacy env once; subsequent workers read shared state."""
        with file_lock(self.lock_path):
            if self.path.exists() or self.path.is_symlink():
                return self._read()
            value = dict(version=1, auth_version=1, instance_id=secrets.token_hex(16),
                         password_hash=legacy_hash(environ), updated_at=self._timestamp())
            write_json(self.path, value)
            return value

    @staticmethod
    def _timestamp():
        return datetime.now(timezone.utc).isoformat()

    def read(self):
        # Atomic replace means readers see a complete previous or next snapshot.
        return self._read()

    def authenticate(self, password):
        with file_lock(self.lock_path):
            value = self._read()
            try:
                accepted = check_password_hash(value['password_hash'], password)
            except (ValueError, TypeError, AttributeError):
                raise StateError('认证状态无法校验，请检查运行环境。') from None
            return value if accepted else None

    def change_password(self, current, new, expected_version, expected_instance):
        if not isinstance(new, str) or not new:
            return False
        with file_lock(self.lock_path):
            value = self._read()
            if (value['auth_version'] != expected_version or value['instance_id'] != expected_instance or
                    not check_password_hash(value['password_hash'], current)):
                return False
            value['password_hash'] = generate_password_hash(new, method=PASSWORD_METHOD)
            value['auth_version'] += 1
            value['updated_at'] = self._timestamp()
            write_json(self.path, value)
            return True
