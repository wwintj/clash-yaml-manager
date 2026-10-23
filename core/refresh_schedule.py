"""Validated UTC scheduling and bounded, credential-free refresh history."""
import math

from core.source_errors import SourceError, valid_code

INTERVALS = (900, 1800, 3600, 10800, 21600, 43200, 86400)
OPTIONS = ((None, '關閉'), (900, '每 15 分鐘'), (1800, '每 30 分鐘'),
           (3600, '每 1 小時'), (10800, '每 3 小時'), (21600, '每 6 小時'),
           (43200, '每 12 小時'), (86400, '每 24 小時'))
BACKOFF = (300, 900, 1800, 3600, 7200, 21600)
HISTORY_LIMIT = 20
FIELDS = ('refresh_interval_seconds', 'next_refresh_at', 'consecutive_failures',
          'last_trigger', 'refresh_history')
MAX_EPOCH = 253402300799


def defaults():
    return dict(refresh_interval_seconds=None, next_refresh_at=None,
                consecutive_failures=0, last_trigger=None, refresh_history=[])


def timestamp(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= MAX_EPOCH


def interval(value):
    return value is None or type(value) is int and value in INTERVALS


def valid(source):
    try:
        if not interval(source['refresh_interval_seconds']):
            return False
        next_at = source['next_refresh_at']
        if next_at is not None and not timestamp(next_at):
            return False
        if source['refresh_interval_seconds'] is None and next_at is not None:
            return False
        count = source['consecutive_failures']
        if type(count) is not int or not 0 <= count <= 1_000_000_000:
            return False
        if source['last_trigger'] not in (None, 'save', 'manual', 'auto'):
            return False
        history = source['refresh_history']
        if not isinstance(history, list) or len(history) > HISTORY_LIMIT:
            return False
        for item in history:
            if not isinstance(item, dict) or set(item) != {'at', 'trigger', 'result', 'node_count', 'error'}:
                return False
            if not timestamp(item['at']) or item['trigger'] not in ('save', 'manual', 'auto'):
                return False
            if item['result'] not in ('success', 'cached', 'error', 'conflict'):
                return False
            if type(item['node_count']) is not int or item['node_count'] < 0:
                return False
            if item['error'] is not None and not valid_code(item['error']):
                return False
        return True
    except (KeyError, TypeError):
        return False


def configure(source, requested):
    value = requested.get('refresh_interval_seconds', source.get('refresh_interval_seconds'))
    if not interval(value):
        raise SourceError('config')
    source['refresh_interval_seconds'] = value
    if value is None:
        source.update(next_refresh_at=None, consecutive_failures=0)


def record(source, trigger, result, at, error=None):
    if (not timestamp(at) or trigger not in ('save', 'manual', 'auto')
            or result not in ('success', 'cached', 'error', 'conflict')
            or error is not None and not valid_code(error)):
        raise SourceError('config')
    source['last_trigger'] = trigger
    source['last_attempt_at'] = at
    configured = source['refresh_interval_seconds']
    if result == 'success':
        source.update(last_success_at=at, last_error=None, using_cache=False, consecutive_failures=0)
        delay = configured
    else:
        count = min(source['consecutive_failures'] + 1, 1_000_000_000) if configured is not None else 0
        source.update(last_error=error, consecutive_failures=count)
        delay = BACKOFF[min(max(count, 1), len(BACKOFF)) - 1] if configured is not None else None
    source['next_refresh_at'] = min(at + delay, MAX_EPOCH) if delay is not None else None
    source['refresh_history'] = (source['refresh_history'] + [dict(
        at=at, trigger=trigger, result=result, node_count=source['node_count'], error=error)])[-HISTORY_LIMIT:]


def due(entry, source, now):
    return (entry['status'] == 'active' and source['type'] == 'remote_url' and source['enabled']
            and source['refresh_interval_seconds'] is not None
            and (source['next_refresh_at'] is None or source['next_refresh_at'] <= now))
