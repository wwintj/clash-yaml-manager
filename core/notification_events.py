"""Safe, transient events collected only by automatic scanner invocations."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import re
import unicodedata

CATEGORIES = ('source_refresh', 'endpoint_health', 'proxy_health', 'scheduler')
RESULTS = ('success', 'error', 'engine_unavailable', 'limit', 'busy', 'conflict')
MAX_MESSAGE = 3500
_collector = ContextVar('notification_events', default=None)


def safe_label(value):
    text = ''.join(' ' if unicodedata.category(c).startswith('C') else c for c in str(value))
    # A subscription label is arbitrary input. Remove obvious network addresses,
    # URIs and opaque credentials before it crosses the notification boundary.
    for pattern in (r'\b[a-zA-Z][a-zA-Z0-9+.-]*://\S+',
                    r'\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b',
                    r'-?fs_[A-Za-z0-9_-]+', r'\b\d+:[A-Za-z0-9_-]+',
                    r'\b[A-Za-z0-9_-]{20,}\b',
                    r'\b(?:[A-Za-z0-9-]+\.)+[A-Za-z0-9-]+\b',
                    r'\b[0-9a-fA-F]*:[0-9a-fA-F:]+\b', r'\b-?\d{5,}\b'):
        text = re.sub(pattern, '[redacted]', text)
    return ' '.join(text.split())[:96] or 'Subscription'


@dataclass(frozen=True)
class Event:
    kind: str
    transition: str
    label: str
    count: int
    total: int
    result: str
    at: float


@contextmanager
def collect(events):
    token = _collector.set(events)
    try:
        yield
    finally:
        _collector.reset(token)


def boundary(kind, before, after, total, label, at, result='success'):
    events = _collector.get()
    if events is None:
        return
    # Collection is auxiliary even after an authoritative commit succeeded.
    try:
        if kind not in CATEGORIES or result not in RESULTS:
            return
        transition = 'incident' if before == 0 and after > 0 else 'recovery' if before > 0 and after == 0 else None
        if transition:
            events.append(Event(kind, transition, safe_label(label), int(after), int(total), result, float(at)))
    except Exception:
        pass


def source_count(entry):
    if not entry:
        return 0, 0
    remote = [s for s in entry['sources'] if s['enabled'] and s['type'] == 'remote_url']
    return sum(s['consecutive_failures'] > 0 for s in remote), len(remote)


def source(before, after, at):
    if _collector.get() is None:
        return
    try:
        source_changed(source_count(before)[0], after, at)
    except Exception:
        pass


def source_changed(before_count, after, at):
    if _collector.get() is None:
        return
    try:
        count, total = source_count(after)
        boundary('source_refresh', before_count, count, total, after['name'], at,
                 'error' if count else 'success')
    except Exception:
        pass


def health(kind, before, after, label, at, trigger):
    if trigger != 'auto' or _collector.get() is None:
        return
    try:
        old = sum(r['status'] == 'unhealthy' for r in before['nodes'].values())
        new = sum(r['status'] == 'unhealthy' for r in after['nodes'].values())
        boundary(kind, old, new, len(after['nodes']), label, at)
        scheduler(before['scheduler_failures'], after['scheduler_failures'], label, at, 'success', kind)
    except Exception:
        pass


def scheduler(before, after, label, at, result, kind):
    prefix = 'Endpoint Health' if kind == 'endpoint_health' else 'Full Proxy Health'
    boundary('scheduler', before, after, after, prefix + ' / ' + safe_label(label), at, result)


def utc(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat(timespec='seconds')


def message(events):
    lines = ['Clash YAML Manager automatic notifications.']
    names = dict(source_refresh='Source Refresh', endpoint_health='Endpoint Health',
                 proxy_health='Full Proxy Health', scheduler='Scheduler')
    for index, event in enumerate(events):
        detail = ('Remote source refresh degraded; last-good cache may be in use.'
                  if event.kind == 'source_refresh' and event.transition == 'incident' else '')
        block = (f'{names[event.kind]} {event.transition}. Subscription: {safe_label(event.label)}. '
                 f'Count: {event.count} / {event.total}. Result: {event.result}. UTC: {utc(event.at)}. {detail}').strip()
        # Reserve room for the aggregate remainder notice, never split the batch.
        if len('\n'.join(lines)) + len(block) + 1 > MAX_MESSAGE - 80:
            lines.append(f'{len(events) - index} additional events omitted.')
            break
        lines.append(block)
    return '\n'.join(lines)
