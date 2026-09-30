"""Private notification authority; delivery is auxiliary and never holds locks."""
from contextlib import contextmanager
import copy
import fcntl
import json
import math
import os
from pathlib import Path
import stat
import time

from core import notification_events as events
from core.state import atomic_write, write_json
from core.telegram import Telegram, ERRORS, valid_token, valid_chat

MAX_STATE = 64 * 1024


class NotificationError(RuntimeError):
    def __init__(self):
        super().__init__('Notification configuration unavailable.')


def defaults():
    return dict(version=1, revision=0,
        telegram=dict(enabled=False, bot_token=None, chat_id=None),
        events={key: True for key in events.CATEGORIES},
        delivery=dict(last_attempt_at=None, last_success_at=None, last_result=None, last_error=None))


def keys(value, expected):
    return type(value) is dict and set(value) == set(expected)


def timestamp(value):
    return value is None or type(value) in (float, int) and math.isfinite(value) and 0 <= value <= 253402300799


def validate(data):
    try:
        if (not keys(data, defaults()) or type(data['version']) is not int or data['version'] != 1
                or type(data['revision']) is not int or not 0 <= data['revision'] < 2**63):
            raise ValueError
        provider, delivery = data['telegram'], data['delivery']
        if (not keys(provider, defaults()['telegram']) or type(provider['enabled']) is not bool
                or provider['bot_token'] is not None and not valid_token(provider['bot_token'])
                or provider['chat_id'] is not None and not valid_chat(provider['chat_id'])
                or provider['enabled'] and not (provider['bot_token'] and provider['chat_id'])
                or not keys(data['events'], events.CATEGORIES)
                or any(type(value) is not bool for value in data['events'].values())
                or not keys(delivery, defaults()['delivery'])
                or not timestamp(delivery['last_attempt_at']) or not timestamp(delivery['last_success_at'])
                or delivery['last_result'] not in (None, 'success', 'failure')
                or delivery['last_error'] not in (None,) + ERRORS):
            raise ValueError
        if (delivery['last_result'] is None and any(value is not None for value in delivery.values())
                or delivery['last_result'] == 'success' and (delivery['last_error'] is not None or delivery['last_success_at'] != delivery['last_attempt_at'])
                or delivery['last_result'] == 'failure' and delivery['last_error'] is None
                or delivery['last_result'] is not None and delivery['last_attempt_at'] is None
                or delivery['last_success_at'] is not None and delivery['last_success_at'] > delivery['last_attempt_at']):
            raise ValueError
        return data
    except Exception:
        raise NotificationError from None


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def private(info, mode, directory=False):
    return ((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            and stat.S_IMODE(info.st_mode) == mode
            and info.st_uid == os.geteuid() and info.st_gid == os.getegid())


class Notifications:
    def __init__(self, state, *, clock=None, transport=None):
        self.state = Path(state)
        self.path = self.state / 'notifications.json'
        self.lock = self.state / 'notifications.lock'
        self.clock = clock or time.time
        self.transport = transport  # Test doubles only; no configurable endpoint.

    def _directory(self):
        try:
            if not private(self.state.lstat(), 0o700, True):
                raise ValueError
        except Exception:
            raise NotificationError from None

    def _read(self):
        self._directory()
        try:
            info = self.lock.lstat()
        except FileNotFoundError:
            pass
        else:
            if not private(info, 0o600):
                raise NotificationError
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            if self.path.is_symlink():
                raise NotificationError from None
            return defaults(), None
        except OSError:
            raise NotificationError from None
        try:
            with os.fdopen(fd, 'rb') as source:
                info = os.fstat(source.fileno())
                if not private(info, 0o600) or info.st_size > MAX_STATE:
                    raise ValueError
                raw = source.read(MAX_STATE + 1)
            if len(raw) > MAX_STATE:
                raise ValueError
            return validate(json.loads(raw, object_pairs_hook=unique)), raw
        except Exception:
            raise NotificationError from None

    @contextmanager
    def _locked(self):
        self._directory()
        try:
            fd = os.open(self.lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        except OSError:
            raise NotificationError from None
        try:
            if not private(os.fstat(fd), 0o600):
                raise NotificationError
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _commit(self, data, previous):
        validate(data)
        try:
            write_json(self.path, data)
        except Exception:
            # An error may occur after replace (e.g. directory fsync). Restore
            # committed bytes, rather than letting a failed Save retain new secrets.
            try:
                if previous is None:
                    self.path.unlink(missing_ok=True)
                else:
                    atomic_write(self.path, previous)
            except Exception:
                pass
            raise NotificationError from None

    def status(self):
        data, _ = self._read()  # Atomic local read: GET creates neither file nor lock.
        provider = data['telegram']
        chat = provider['chat_id']
        delivery = copy.deepcopy(data['delivery'])
        for key in ('last_attempt_at', 'last_success_at'):
            delivery[key] = events.utc(delivery[key]) if delivery[key] is not None else 'Never'
        return dict(enabled=provider['enabled'], configured=bool(provider['bot_token'] and chat),
            token_configured=bool(provider['bot_token']),
            chat_masked=('••••' + chat[-4:] if chat and len(chat.lstrip('-')) > 4 else '••••' if chat else 'Not configured'),
            events=copy.deepcopy(data['events']), delivery=delivery)

    def save(self, enabled, preferences, token='', chat=''):
        if (type(enabled) is not bool or not keys(preferences, events.CATEGORIES)
                or any(type(value) is not bool for value in preferences.values())
                or type(token) is not str or type(chat) is not str
                or token != '' and not valid_token(token) or chat != '' and not valid_chat(chat)):
            raise NotificationError
        with self._locked():
            data, raw = self._read()
            old = copy.deepcopy(data)
            provider = data['telegram']
            provider.update(enabled=enabled, bot_token=token or provider['bot_token'], chat_id=chat or provider['chat_id'])
            data['events'] = copy.deepcopy(preferences)
            validate(data)
            if data != old:
                data['revision'] += 1
                self._commit(data, raw)

    def remove(self):
        with self._locked():
            data, raw = self._read()
            data['telegram'] = defaults()['telegram']
            data['revision'] += 1
            self._commit(data, raw)

    def enabled(self):
        try:
            data, _ = self._read()
            return data['telegram']['enabled'] and any(data['events'].values())
        except Exception:
            return False

    def deliver(self, batch=None, *, test=False):
        try:
            # The no-op path never initializes transport or creates a lock file.
            initial, _ = self._read()
            if not test and (not initial['telegram']['enabled'] or not batch):
                return None
            with self._locked():
                data, _ = self._read()
                provider = data['telegram']
                if not provider['bot_token'] or not provider['chat_id']:
                    return 'config'
                if test:
                    text = 'Clash YAML Manager test notification. Telegram delivery is working. UTC: ' + events.utc(self.clock())
                else:
                    eligible = [event for event in batch if data['events'][event.kind]]
                    if not provider['enabled'] or not eligible:
                        return None
                    text = events.message(eligible)
                revision = data['revision']
                token, chat = provider['bot_token'], provider['chat_id']
                at = self.clock()
            # All configuration and feature locks are released before any DNS/TLS.
            try:
                result = (self.transport or Telegram()).send(token, chat, text)
                if result not in ('success',) + ERRORS:
                    result = 'network'
            except Exception:
                result = 'network'
            try:
                with self._locked():
                    current, raw = self._read()
                    last = current['delivery']['last_attempt_at']
                    if current['revision'] == revision and (last is None or last <= at):
                        delivery = current['delivery']
                        delivery.update(last_attempt_at=at, last_result='success' if result == 'success' else 'failure',
                                        last_error=None if result == 'success' else result)
                        if result == 'success':
                            delivery['last_success_at'] = at
                        self._commit(current, raw)
            except Exception:
                pass  # No resend loop or propagation into authoritative work.
            return result
        except Exception:
            return 'config' if test else None
