"""Bounded DATA parsers for D2. No business stores, imports, migration or writes.

These checks exclude known incompatibilities; they do not implement a loader or
prove the application's complete state semantics.
"""
import hashlib
import math
import re
import struct

from scripts import recovery_manifest as schema

MAX_TEXT = 64 * 1024
MAX_ITEMS = 4096
ID = re.compile(r'[0-9a-f]{32}\Z')
HASH = re.compile(r'[0-9a-f]{64}\Z')
INTERVALS = (900, 1800, 3600, 10800, 21600, 43200, 86400)


def require(value, code='INVALID_SCHEMA'):
    schema.require(value, code)


def mapping(value):
    require(type(value) is dict and len(value) <= MAX_ITEMS)
    return value


def integer(value, minimum=0, maximum=2**63-1):
    require(type(value) is int and minimum <= value <= maximum)


def timestamp(value):
    # Unix seconds, including fractional clock values. Bound integers before
    # math.isfinite's implicit float conversion; never normalize invalid input.
    require(type(value) in (int, float) and 0 <= value <= 253402300799 and math.isfinite(value))


def identifier(value):
    require(type(value) is str and ID.fullmatch(value) is not None)


def text(raw):
    require(len(raw) <= MAX_TEXT, 'ANALYSIS_BYTE_LIMIT')
    try:
        value = raw.decode('utf-8')
    except UnicodeError:
        require(False, 'INVALID_TEXT')
    require('\0' not in value, 'INVALID_TEXT')
    return value


def venv_config(raw, runtime):
    result = {}
    allowed = {'home', 'version', 'executable', 'include-system-site-packages', 'command', 'prompt'}
    for line in text(raw).splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        require('=' in line, 'INVALID_VENV_CONFIG')
        key, value = (part.strip() for part in line.split('=', 1))
        require(key in allowed and key not in result and 0 < len(value) <= 4096, 'INVALID_VENV_CONFIG')
        result[key] = value
    require({'home', 'version', 'include-system-site-packages'} <= result.keys(), 'INVALID_VENV_CONFIG')
    for key in ('home', 'executable'):
        if key in result:
            value = result[key]
            require(value.startswith('/') and '\\' not in value and '//' not in value
                    and not any(p in ('.', '..') for p in value.split('/')), 'VENV_PREFIX_MISMATCH')
    require(result['home'] in ('/usr/bin', '/usr/local/bin'), 'VENV_PREFIX_MISMATCH')
    if 'executable' in result:
        require(re.fullmatch(re.escape(result['home']) + r'/python3(?:\.\d+)?', result['executable']),
                'VENV_PREFIX_MISMATCH')
    require(re.fullmatch(r'3\.[0-9]+(?:\.[0-9]+)?', result['version']), 'INVALID_VENV_CONFIG')
    require(result['version'].split('.')[:2] == runtime['python_version'].split('.')[:2],
            'PYTHON_VERSION_MISMATCH')
    require(result['include-system-site-packages'] in ('true', 'false'), 'INVALID_VENV_CONFIG')
    require(result['include-system-site-packages'] == 'false', 'SYSTEM_SITE_PACKAGES_UNSUPPORTED')
    return 'STATIC_CONFIG_CONSISTENT_NOT_RUNTIME_PROOF'


def wheel(raw):
    fields = {}
    for line in text(raw).splitlines():
        if not line:
            continue
        require(': ' in line, 'INVALID_WHEEL_METADATA')
        key, value = line.split(': ', 1)
        require(key in ('Wheel-Version', 'Generator', 'Root-Is-Purelib', 'Tag', 'Build'), 'INVALID_WHEEL_METADATA')
        require(key == 'Tag' or key not in fields, 'INVALID_WHEEL_METADATA')
        fields.setdefault(key, []).append(value)
        require(len(fields[key]) <= 64, 'ANALYSIS_ENTRY_LIMIT')
    require({'Wheel-Version', 'Root-Is-Purelib', 'Tag'} <= fields.keys(), 'INVALID_WHEEL_METADATA')
    require(fields['Wheel-Version'] == ['1.0'] and fields['Root-Is-Purelib'] in (['true'], ['false']),
            'UNSUPPORTED_WHEEL_METADATA')
    require(all(re.fullmatch(r'[A-Za-z0-9_.]+-[A-Za-z0-9_.]+-[A-Za-z0-9_.]+', tag)
                for tag in fields['Tag']), 'INVALID_WHEEL_METADATA')
    return fields['Tag']


def elf(raw, architecture):
    require(len(raw) >= 64 and raw[:4] == b'\x7fELF', 'INVALID_ELF_HEADER')
    require(raw[4] == 2 and raw[5] in (1, 2) and raw[6] == 1, 'UNSUPPORTED_ELF_FORMAT')
    order = '<' if raw[5] == 1 else '>'
    kind, machine, version = struct.unpack_from(order + 'HHI', raw, 16)
    size = struct.unpack_from(order + 'H', raw, 52)[0]
    require(kind in (2, 3) and version == 1 and size == 64, 'INVALID_ELF_HEADER')
    expected = {'x86_64': 62, 'amd64': 62, 'aarch64': 183, 'arm64': 183}.get(architecture)
    require(expected is not None, 'UNSUPPORTED_ELF_ARCHITECTURE')
    require(machine == expected, 'ELF_ARCHITECTURE_MISMATCH')
    return 'HEADER_MATCH_DYNAMIC_CLOSURE_UNKNOWN'


def startup_data(raw, suffix, prefix):
    value = text(raw)
    if suffix == '.pth':
        lines = [line for line in value.splitlines() if line and not line.startswith('#')]
        require(not any(line.startswith(('import ', 'import\t')) for line in lines), 'EXECUTABLE_PTH_UNSUPPORTED')
        for line in lines:
            require(not line.startswith('/') and '\\' not in line and '..' not in line.split('/'),
                    'PTH_PATH_UNSUPPORTED')
        return 'PATH_PTH_NOT_EXECUTED_UNRESOLVED'
    if value.startswith('#!'):
        head = value.splitlines()[0][2:]
        if 'python' in head:
            require(re.fullmatch(re.escape(prefix) + r'/venv/bin/python(?:3(?:\.\d+)?)?', head),
                    'VENV_PREFIX_MISMATCH')
    return 'SCRIPT_DATA_NOT_EXECUTED'


def load(raw, version):
    require(len(raw) <= 1024 * 1024, 'STATE_BYTE_LIMIT')
    value = mapping(schema.parse(raw, canonical_required=False))
    require(type(value.get('version')) is int and value['version'] == version, 'UNSUPPORTED_VERSION')
    return value


def auth(raw):
    value = load(raw, 1)
    integer(value.get('auth_version'), 1)
    identifier(value.get('instance_id'))
    require(type(value.get('password_hash')) is str and re.fullmatch(
        r'(?:pbkdf2:sha256:[1-9][0-9]*|scrypt:[1-9][0-9]*:[1-9][0-9]*:[1-9][0-9]*)\$[A-Za-z0-9]+\$[0-9a-f]+',
        value['password_hash']), 'INVALID_SCHEMA')
    return value


def schedules(value, health=False):
    interval = value.get('interval_seconds' if health else 'refresh_interval_seconds')
    next_at = value.get('next_check_at' if health else 'next_refresh_at')
    failures = value.get('scheduler_failures' if health else 'consecutive_failures')
    require(interval is None or type(interval) is int and interval in INTERVALS)
    if next_at is not None:
        timestamp(next_at)
    require(interval is not None or next_at is None)
    integer(failures, 0, 1_000_000_000)
    if health:
        require(value.get('mode') in ('off', 'manual', 'automatic'))
        require((value['mode'] == 'automatic') == (interval is not None))
        require(value['mode'] != 'automatic' or next_at is not None)
        require(value['mode'] == 'automatic' or failures == 0)
        integer(value.get('check_revision'))
        trigger, result = value.get('last_trigger'), value.get('last_job_result')
        require((trigger is None and result is None) or trigger in ('manual', 'auto')
                and result in ('success', 'error', 'engine_unavailable', 'limit', 'busy', 'conflict'))
    else:
        require(value.get('last_trigger') in (None, 'save', 'manual', 'auto'))
        history = value.get('refresh_history')
        require(type(history) is list and len(history) <= 20)
        for entry in history:
            mapping(entry); timestamp(entry.get('at'))
            require(entry.get('trigger') in ('save', 'manual', 'auto')
                    and entry.get('result') in ('success', 'cached', 'error', 'conflict'))
            integer(entry.get('node_count'))


def fixed(files):
    if 'state/fixed_subscriptions.json' not in files:
        return {}, set()
    data = load(files['state/fixed_subscriptions.json'], 6)
    entries = mapping(data.get('subscriptions'))
    retired = data.get('retired_tokens')
    require(type(retired) is list and len(retired) <= MAX_ITEMS)
    require(all(type(t) is str and HASH.fullmatch(t) for t in retired))
    require(len(set(retired)) == len(retired), 'REVOCATION_INCONSISTENT')
    reserved = set(retired)
    for key, entry in entries.items():
        identifier(key); mapping(entry); identifier(entry.get('revision'))
        require(entry.get('id') == key and entry.get('status') in ('active', 'disabled'))
        token = entry.get('token')
        require(type(token) is str and re.fullmatch(r'[A-Za-z0-9_-]{22}', token))
        digest = hashlib.sha256(token.encode('ascii')).hexdigest()
        require(digest not in reserved, 'REVOCATION_INCONSISTENT')
        reserved.add(digest)
        home = 'state/fixed_subscriptions/' + key + '/' + entry['revision']
        require(all(home + '/' + name in files for name in ('base.yaml', 'current.yaml')), 'MISSING_REFERENCE')
        sources = entry.get('sources')
        require(type(sources) is list and 0 < len(sources) <= 64)
        seen = set()
        for index, item in enumerate(sources):
            mapping(item); identifier(item.get('id'))
            require(item['id'] not in seen); seen.add(item['id'])
            require(item.get('type') in ('manual', 'uploaded', 'remote_url')
                    and type(item.get('enabled')) is bool)
            require((index == 0) == (item['type'] == 'manual') and (index != 0 or item['enabled']))
            if item['type'] != 'manual':
                require(home + '/sources/' + item['id'] + '/payload.bin' in files, 'MISSING_REFERENCE')
            if item['type'] == 'remote_url':
                schedules(item)
        # Opaque YAML/cache contents are never parsed as code or claimed semantically compatible.
    return entries, set(retired)


def links(files, resolve_outputs=True):
    if 'state/temporary_links.json' not in files:
        return {}
    values = mapping(load(files['state/temporary_links.json'], 1).get('links'))
    for key, entry in values.items():
        require(type(key) is str and re.fullmatch(r'[A-Za-z0-9_-]{16}', key))
        if entry is None:
            continue
        mapping(entry)
        name = entry.get('filename')
        require(type(name) is str and 0 < len(name) <= 255 and name.endswith('.yaml')
                and '/' not in name and '\\' not in name and '\0' not in name)
        timestamp(entry.get('created_at')); timestamp(entry.get('expires_at'))
        require(entry['expires_at'] > entry['created_at'])
        require(not resolve_outputs or 'outputs/' + name in files, 'MISSING_REFERENCE')
    return values


def state_checks(current, archived):
    now, before = auth(current['state/auth.json']), auth(archived['state/auth.json'])
    require(now['instance_id'] == before['instance_id'] and now['auth_version'] >= before['auth_version'],
            'REVOCATION_INCONSISTENT')
    require(now['auth_version'] != before['auth_version'] or now['password_hash'] == before['password_hash'],
            'REVOCATION_INCONSISTENT')
    entries, retired = fixed(current)
    old_entries, old_retired = fixed(archived)
    require(old_retired <= retired, 'REVOCATION_INCONSISTENT')
    active = {entry['token'] for entry in entries.values()}
    require(all(entry['token'] in active or hashlib.sha256(entry['token'].encode('ascii')).hexdigest()
                in retired for entry in old_entries.values()), 'REVOCATION_INCONSISTENT')
    # An immutable revision/cache path cannot represent different bytes in the same identity.
    for path in archived.keys() & current.keys():
        if path.startswith('state/fixed_subscriptions/'):
            require(archived[path] == current[path], 'DIGEST_MISMATCH')
    # Archived outputs are intentionally omitted. Their existence remains UNKNOWN.
    new_links, old_links = links(current), links(archived, resolve_outputs=False)
    require(all(key in new_links and new_links[key] is None for key, value in old_links.items() if value is None),
            'REVOCATION_INCONSISTENT')
    for name in ('node_health.json', 'proxy_health.json'):
        path = 'state/' + name
        if path not in current:
            continue
        state = load(current[path], 2)
        for key, entry in mapping(state.get('subscriptions')).items():
            identifier(key); require(key in entries, 'MISSING_REFERENCE'); mapping(entry); schedules(entry, health=True)
            nodes = mapping(entry.get('nodes'))
            require(len(nodes) <= 256)
            require(all(type(fp) is str and HASH.fullmatch(fp) for fp in nodes))
            # Fingerprint/YAML semantic reconciliation requires a trusted parser: UNKNOWN.
    if 'state/settings.json' in current:
        settings = load(current['state/settings.json'], 1)
        require(set(settings) == {'version', 'geoip'})
        meta = settings['geoip']; database = current.get('state/geoip/active.mmdb')
        if meta is None:
            require(database is None, 'MISSING_REFERENCE')
        else:
            mapping(meta); require(database is not None, 'MISSING_REFERENCE')
            require(set(meta) == {'database_type', 'size', 'sha256', 'uploaded_at'})
            require(type(meta['database_type']) is str and 0 < len(meta['database_type']) <= 128)
            timestamp(meta['uploaded_at'])
            integer(meta['size'], 1, 32 * 1024 * 1024)
            require(type(meta['sha256']) is str and HASH.fullmatch(meta['sha256']))
            require(len(database) == meta['size'] and hashlib.sha256(database).hexdigest() == meta['sha256'],
                    'DIGEST_MISMATCH')
    else:
        require('state/geoip/active.mmdb' not in current, 'MISSING_REFERENCE')
    if 'state/login_attempts.json' in current:
        for entry in mapping(load(current['state/login_attempts.json'], 1).get('ips')).values():
            mapping(entry); failures = entry.get('failures')
            require(type(failures) is list and len(failures) <= MAX_ITEMS)
            for at in failures:
                timestamp(at)
            timestamp(entry.get('blocked_until'))
    if 'state/notifications.json' in current:
        data = load(current['state/notifications.json'], 1)
        integer(data.get('revision'))
        provider = mapping(data.get('telegram'))
        require(type(provider.get('enabled')) is bool)
        require(not provider['enabled'] or type(provider.get('bot_token')) is str
                and type(provider.get('chat_id')) is str, 'MISSING_REFERENCE')
        require(set(mapping(data.get('events'))) == {'source_refresh', 'endpoint_health', 'proxy_health', 'scheduler'})
        require(all(type(v) is bool for v in data['events'].values()))
        delivery = mapping(data.get('delivery'))
        for key in ('last_attempt_at', 'last_success_at'):
            if delivery.get(key) is not None:
                timestamp(delivery[key])
    for path in current:
        if path.startswith('state/'):
            schema.role(path, 'file')
    return 'PARTIAL_DATA_CLOSURE_NOT_BUSINESS_COMPATIBILITY'
