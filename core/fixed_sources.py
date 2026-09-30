"""Source schema, ordered aggregation and last-good cache decisions."""
import copy
import math
import re
import time
import uuid

from core import source_fetch, source_parser, refresh_schedule
from core.source_errors import SourceError, valid_code

ID = re.compile(r'[0-9a-f]{32}\Z')


def manual(identifier=None, node_count=0):
    return dict(id=identifier or uuid.uuid4().hex, type='manual', name='Manual Nodes', enabled=True,
                format='auto', node_count=node_count, last_attempt_at=None, last_success_at=None,
                last_error=None, using_cache=False, warnings=[])


def valid(sources, schedules=True):
    if not isinstance(sources, list) or not sources or len(sources) > 64:
        return False
    ids, names = set(), set()
    try:
        for index, item in enumerate(sources):
            if not isinstance(item, dict) or not ID.fullmatch(item['id']) or item['id'] in ids:
                return False
            if not isinstance(item['name'], str) or not 0 < len(item['name'].strip()) <= 128 or item['name'] in names:
                return False
            ids.add(item['id']); names.add(item['name'])
            if item['type'] not in ('manual', 'remote_url', 'uploaded') or type(item['enabled']) is not bool:
                return False
            if (index == 0) != (item['type'] == 'manual') or index == 0 and not item['enabled']:
                return False
            if item['format'] not in source_parser.FORMATS or type(item['using_cache']) is not bool:
                return False
            if type(item['node_count']) is not int or item['node_count'] < 0:
                return False
            for field in ('last_attempt_at', 'last_success_at'):
                v = item[field]
                if v is not None and (type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 253402300799):
                    return False
            if item['last_error'] is not None and not valid_code(item['last_error']):
                return False
            if not isinstance(item['warnings'], list) or any(not isinstance(w, str) or not re.fullmatch(
                    r'[0-9]+ unsupported proxies skipped', w) for w in item['warnings']):
                return False
            if item['type'] == 'remote_url':
                source_fetch.validate_url(item['url'])
                if schedules and not refresh_schedule.valid(item):
                    return False
    except (KeyError, TypeError, ValueError):
        return False
    return True


def configure(existing, requested):
    """Only known ids may be supplied; all new ids are allocated on the server."""
    if requested is None:
        return copy.deepcopy(existing)
    if not isinstance(requested, list) or len(requested) > 63:
        raise SourceError('config')
    old = {item['id']: item for item in existing[1:]}
    result = [copy.deepcopy(existing[0])]
    for fields in requested:
        if not isinstance(fields, dict):
            raise SourceError('config')
        identifier = fields.get('id')
        previous = old.get(identifier) if isinstance(identifier, str) else None
        if identifier and previous is None:
            raise SourceError('config')
        item = copy.deepcopy(previous) if previous else manual()
        item.update({k: fields.get(k) for k in ('type', 'name', 'enabled', 'format')})
        if isinstance(item['name'], str):
            item['name'] = item['name'].strip()
        if item['type'] not in ('remote_url', 'uploaded') or previous and item['type'] != previous['type']:
            raise SourceError('config')
        if item['type'] == 'remote_url':
            item['url'] = fields.get('url')
            if not previous:
                item.update(refresh_schedule.defaults())
            refresh_schedule.configure(item, fields)
        result.append(item)
    if not valid(result):
        raise SourceError('config')
    return result


def prepare(sources, previous, caches, uploads, manual_result, refresh, trigger='save', clock=None):
    """Pure candidate metadata/payloads; no writes and no registry lock here.

    uploads is keyed by the submitted external row index (transport only, never
    a persistent id/path). refresh=None means Save: fetch every enabled remote.
    """
    old = {item['id']: item for item in previous}
    clock = clock or time.time
    payloads, results = {}, []
    for index, item in enumerate(sources):
        if item['type'] == 'manual':
            results.append(manual_result)
            item['node_count'] = len(manual_result['nodes'])
            continue
        cached = caches.get(item['id'])
        before = old.get(item['id'], {})
        changed = any(item.get(field) != before.get(field) for field in ('url', 'format'))
        replacement = uploads.get(index - 1)
        parsed = None
        if item['type'] == 'uploaded':
            payload = replacement if replacement is not None else cached
            if payload is None:
                raise SourceError('upload')
            # Replacements are validated even when disabled: never store invalid uploads.
            parsed = source_parser.parse(payload, item['format'])
            item.update(last_attempt_at=clock(), last_success_at=clock(), last_error=None,
                        using_cache=False, node_count=len(parsed['nodes']), warnings=parsed['warnings'])
        else:
            payload = cached
            if not item['enabled']:
                # Disabled URL/format changes cannot certify the old cache for a new config.
                if changed and before:
                    raise SourceError('config')
            elif refresh is None or item['id'] in refresh or changed:
                result, error_code = 'success', None
                try:
                    payload = source_fetch.fetch(item['url'])
                    parsed = source_parser.parse(payload, item['format'])
                except SourceError as error:
                    if cached is None or changed:
                        error.source_id = item['id']
                        raise
                    payload = cached
                    parsed = source_parser.parse(cached, item['format'])
                    item.update(last_error=error.code, using_cache=True)
                    result, error_code = 'cached', error.code
                else:
                    item.update(last_error=None, using_cache=False)
                item['node_count'] = len(parsed['nodes'])
                refresh_schedule.record(item, trigger, result, clock(), error_code)
            if item['enabled'] and parsed is None:
                if payload is None:
                    raise SourceError('empty')
                parsed = source_parser.parse(payload, item['format'])
            if parsed is not None:
                item.update(node_count=len(parsed['nodes']), warnings=parsed['warnings'])
        if payload is not None:
            payloads[item['id']] = payload
        if item['enabled']:
            results.append(parsed)
    return source_parser.combine(results), payloads


def aggregate_cached(sources, caches, manual_result):
    """Exact existing source aggregation, without fetch or source metadata changes."""
    results = [manual_result]
    for item in sources[1:]:
        if not item['enabled']: continue
        payload = caches.get(item['id'])
        if payload is None: raise SourceError('empty')
        results.append(source_parser.parse(payload,item['format']))
    return source_parser.combine(results), copy.deepcopy(caches)
