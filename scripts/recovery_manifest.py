"""managed-upgrade-v1: independent, bounded offline representation protocol.

No Manifest v1 changes, execution, restore, deployment or retention actions.
"""
from datetime import datetime
import json
import re

from scripts.backup_audit import AuditFault
from scripts.backup_collect import policy as sidecar_path_policy

PROFILE = 'managed-upgrade-v1'
MAX_ENTRIES = 4096
MAX_DEPTH = 16
MAX_PATH_BYTES = 1024
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_SECONDS = 60
ROOTS = {name: name.upper() for name in ('application', 'venv', 'configuration', 'default', 'units', 'state')}
REQUIRED = {'application/app.py', 'application/VERSION', 'application/INSTALLATION.json',
            'application/requirements.txt', 'application/core', 'application/scripts',
            'application/templates', 'application/static', 'venv/bin', 'venv/bin/python',
            'venv/bin/python3', 'venv/pyvenv.cfg', 'configuration/.env',
            'configuration/.service-account', 'default/default.yaml',
            'units/clash-yaml-manager.service', 'state/auth.json'} | set(ROOTS)
UNITS = {'clash-yaml-manager.service', 'clash-yaml-manager-refresh.service',
         'clash-yaml-manager-refresh.timer', 'clash-yaml-manager-health.service',
         'clash-yaml-manager-health.timer'}
SCRIPTS = {'install.sh', 'update.sh', 'remote-install.sh', 'remote-update.sh',
           'uninstall.sh', 'httpsctl.sh', 'mihomoctl.sh'}
OMISSIONS = ['NGINX', 'TLS', 'UFW', 'OS_PACKAGES', 'EXTERNAL_ACCOUNTS', 'MIHOMO',
             'UPLOADS_OUTPUTS', 'WEB_BACKUPS_LOGS', 'OFF_HOST_BACKUPS',
             'VOLATILE_LOCKS', 'ACL_XATTR_CAPABILITIES_RESTORE_UNSUPPORTED']
RETENTION = dict(policy='strict', keep_count=1, hours=72,
                 count_rotation_after='WHOLE_UPGRADE_SUCCEEDED',
                 age_expiry_after='WHOLE_UPGRADE_SUCCEEDED', completed_at=None,
                 failed_uncertain_busy='PROTECTED')
TOP = {'format_version', 'profile', 'operation_id', 'source_identity', 'target_identity',
       'installation_binding', 'capture_interval', 'capture_evidence', 'account_roles',
       'runtime_requirements', 'roots', 'entries', 'omissions', 'retention', 'restore_proven'}


def require(condition, code='INVALID_SCHEMA'):
    if not condition:
        raise AuditFault(code)


def keys(value, names):
    require(type(value) is dict and set(value) == set(names))


def text(value, size=256):
    require(type(value) is str)
    try:
        length = len(value.encode('utf-8'))
    except UnicodeError:
        raise AuditFault('INVALID_SCHEMA') from None
    require(0 < length <= size and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def integer(value, maximum=2**63 - 1):
    require(type(value) is int and 0 <= value <= maximum)


def digest(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None)


def operation(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{32}', value) is not None)


def timestamp(value):
    text(value, 64)
    try:
        parsed = datetime.fromisoformat(value)
        require(parsed.tzinfo is not None)
        return parsed
    except ValueError:
        raise AuditFault('INVALID_SCHEMA') from None


def path(value):
    text(value, MAX_PATH_BYTES)
    parts = value.split('/')
    require(not value.startswith('/') and '\\' not in value
            and all(p not in ('', '.', '..') for p in parts), 'INVALID_PATH')
    require(len(parts) <= MAX_DEPTH, 'DEPTH_LIMIT')
    return parts


def identity(value):
    keys(value, ('version', 'channel', 'commit', 'tag'))
    require(type(value['version']) is str and re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value['version']))
    require(value['channel'] in ('stable', 'main'))
    require(type(value['commit']) is str and re.fullmatch('[0-9a-f]{40}', value['commit']))
    require(value['tag'] == ('v' + value['version'] if value['channel'] == 'stable' else None))


def declaration(value):
    keys(value, ('source_identity', 'target_identity', 'installation_binding',
                 'account_roles', 'runtime_requirements', 'offline_quiet'))
    require(value['offline_quiet'] is True, 'OFFLINE_QUIET_REQUIRED')
    identity(value['source_identity'])
    identity(value['target_identity'])
    b = value['installation_binding']
    keys(b, ('origin', 'install_path', 'system_id'))
    require(b['origin'] == 'ROOT_OPERATOR_DECLARATION')
    text(b['install_path'], 1024)
    require(b['install_path'].startswith('/') and '..' not in b['install_path'].split('/'))
    text(b['system_id'])
    accounts = value['account_roles']
    keys(accounts, ('root', 'service'))
    for account in accounts.values():
        keys(account, ('name', 'uid', 'gid', 'origin'))
        text(account['name'], 64)
        integer(account['uid'], 2**32-1)
        integer(account['gid'], 2**32-1)
        require(account['origin'] == 'ROOT_OPERATOR_DECLARATION')
    require(accounts['root']['name'] == 'root')
    require(accounts['service']['name'] == 'clashyaml')
    runtime = value['runtime_requirements']
    keys(runtime, ('os', 'architecture', 'python_version', 'python_abi', 'system_libraries', 'origin'))
    for name in ('os', 'architecture', 'python_version', 'python_abi'):
        text(runtime[name], 128)
    require(runtime['origin'] == 'ROOT_OPERATOR_DECLARATION')
    require(type(runtime['system_libraries']) is list and len(runtime['system_libraries']) <= 64)
    for item in runtime['system_libraries']:
        text(item, 128)


def role(value, kind):
    parts = path(value)
    root = parts[0]
    require(root in ROOTS, 'OUT_OF_SCOPE')
    if len(parts) == 1:
        require(kind == 'directory', 'INVALID_KIND')
    elif root == 'application':
        allowed = {'app.py', 'VERSION', 'INSTALLATION.json', 'requirements.txt'} | SCRIPTS
        require((len(parts) == 2 and parts[1] in allowed and kind == 'file')
                or (parts[1] in ('core', 'scripts', 'templates', 'static')
                    and (kind == 'directory' or (len(parts) > 2 and kind == 'file'))), 'OUT_OF_SCOPE')
    elif root == 'venv':
        require(kind in ('file', 'directory', 'symlink'), 'INVALID_KIND')
    elif root == 'configuration':
        require(len(parts) == 2 and parts[1] in ('.env', '.service-account') and kind == 'file', 'OUT_OF_SCOPE')
    elif root == 'default':
        require(len(parts) == 2 and parts[1] == 'default.yaml' and kind == 'file', 'OUT_OF_SCOPE')
    elif root == 'units':
        require(len(parts) == 2 and parts[1] in UNITS and kind == 'file', 'OUT_OF_SCOPE')
    else:
        if value == 'state/.last_cleanup':
            require(kind == 'file', 'INVALID_KIND')
        else:
            wanted, _, selected = sidecar_path_policy(tuple(parts))
            require(selected and kind == wanted, 'OUT_OF_SCOPE')
    return ROOTS[root]


def link_target(value):
    text(value, MAX_PATH_BYTES)
    require('\\' not in value and not value.endswith('/') and '//' not in value, 'INVALID_LINK')
    return 'absolute' if value.startswith('/') else 'relative'


def resolve_links(entries):
    nodes = {e['path']: e for e in entries}
    external = []

    def resolve(parts, seen):
        current = []
        for offset, part in enumerate(parts):
            if part == '.':
                continue
            if part == '..':
                require(len(current) > 1, 'LINK_ESCAPE')
                current.pop()
                continue
            current.append(part)
            name = '/'.join(current)
            require(name in nodes and current[0] == 'venv', 'INVALID_LINK_TARGET')
            node = nodes[name]
            if node['kind'] == 'symlink':
                require(name not in seen and len(seen) < MAX_DEPTH, 'LINK_CYCLE')
                target = node['link_target']
                if target.startswith('/'):
                    require(offset == len(parts)-1 and re.fullmatch(r'venv/bin/python(?:3(?:\.\d+)?)?', name)
                            and re.fullmatch(r'/usr/(?:local/)?bin/python3(?:\.\d+)?', target), 'EXTERNAL_LINK_REFUSED')
                    return target
                return resolve(current[:-1] + target.split('/') + parts[offset+1:], seen | {name})
            if offset < len(parts)-1:
                require(node['kind'] == 'directory', 'INVALID_LINK_TARGET')
        return '/'.join(current)

    for node in entries:
        if node['kind'] == 'symlink':
            target = resolve(node['path'].split('/'), set())
            if target.startswith('/'):
                external.append(dict(path=node['path'], target=target))
    return external


def validate(value):
    keys(value, TOP)
    require(value['format_version'] == 1 and type(value['format_version']) is int)
    require(value['profile'] == PROFILE and value['restore_proven'] is False)
    operation(value['operation_id'])
    declaration({k: value[k] for k in ('source_identity', 'target_identity', 'installation_binding',
                                      'account_roles', 'runtime_requirements')} | {'offline_quiet': True})
    keys(value['capture_interval'], ('started_at', 'ended_at'))
    require(timestamp(value['capture_interval']['started_at']) <= timestamp(value['capture_interval']['ended_at']))
    evidence = value['capture_evidence']
    keys(evidence, ('offline_quiet', 'consistency', 'source_device', 'source_inode',
                    'source_reinventoried', 'external_python_links', 'extended_metadata'))
    require(evidence['offline_quiet'] == 'OPERATOR_DECLARED' and evidence['consistency'] == 'NOT_ATOMIC_SNAPSHOT')
    require(evidence['source_reinventoried'] is True)
    require(evidence['extended_metadata'] == 'NOT_CAPTURED_RESTORE_UNSUPPORTED')
    integer(evidence['source_device']); integer(evidence['source_inode'])
    require(value['roots'] == ROOTS and value['omissions'] == OMISSIONS and value['retention'] == RETENTION)
    entries = value['entries']
    require(type(entries) is list and 0 < len(entries) <= MAX_ENTRIES, 'ENTRY_LIMIT')
    initial_paths = []
    for entry in entries:
        keys(entry, ('path', 'role', 'kind', 'original', 'blob', 'size', 'sha256', 'link_target', 'link_type'))
        path(entry['path'])
        initial_paths.append(entry['path'])
    require(initial_paths == sorted(set(initial_paths), key=lambda p: p.encode('utf-8')), 'INVALID_ORDER')
    require(REQUIRED <= set(initial_paths), 'MISSING_REQUIRED')
    paths, blobs, total = [], set(), 0
    for index, entry in enumerate(entries):
        keys(entry, ('path', 'role', 'kind', 'original', 'blob', 'size', 'sha256', 'link_target', 'link_type'))
        parts = path(entry['path'])
        require(entry['role'] == role(entry['path'], entry['kind']))
        original = entry['original']
        keys(original, ('mode', 'uid', 'gid', 'mtime_ns', 'metadata_origin'))
        require(type(original['mode']) is str and re.fullmatch('[0-7]{4}', original['mode']))
        require(entry['kind'] == 'symlink' or not (int(original['mode'], 8) & 0o7022), 'UNSAFE_SOURCE_MODE')
        for key in ('uid', 'gid', 'mtime_ns'):
            integer(original[key])
        require(original['metadata_origin'] == 'OBSERVED_OFFLINE_FIXTURE')
        account = value['account_roles']['service' if parts[0] == 'state' else 'root']
        # State may also contain root-created metadata; arbitrary owners are refused.
        permitted = [account, value['account_roles']['root']]
        require(any(original['uid'] == a['uid'] and original['gid'] == a['gid'] for a in permitted), 'UNSAFE_OWNERSHIP')
        if entry['kind'] == 'file':
            require(entry['blob'] == f'{index:08d}', 'INVALID_BLOB')
            require(entry['blob'] not in blobs, 'INVALID_BLOB')
            blobs.add(entry['blob']); integer(entry['size'], MAX_FILE_BYTES); digest(entry['sha256'])
            total += entry['size']
            require(entry['link_target'] is None and entry['link_type'] is None)
        else:
            require(entry['blob'] is None and entry['sha256'] is None and entry['size'] == 0)
            if entry['kind'] == 'symlink':
                require(entry['link_type'] == link_target(entry['link_target']))
            else:
                require(entry['link_target'] is None and entry['link_type'] is None)
        paths.append(entry['path'])
    require(total <= MAX_TOTAL_BYTES, 'TOTAL_BYTE_LIMIT')
    require(paths == sorted(set(paths), key=lambda p: p.encode('utf-8')), 'INVALID_ORDER')
    by_path = {e['path']: e for e in entries}
    require(REQUIRED <= set(paths), 'MISSING_REQUIRED')
    require(by_path['venv/bin']['kind'] == 'directory'
            and by_path['venv/pyvenv.cfg']['kind'] == 'file'
            and all(by_path[p]['kind'] in ('file', 'symlink') for p in ('venv/bin/python', 'venv/bin/python3')), 'INVALID_KIND')
    for name in paths:
        parts = name.split('/')
        for depth in range(1, len(parts)):
            require('/'.join(parts[:depth]) in by_path and by_path['/'.join(parts[:depth])]['kind'] == 'directory', 'ROOT_CLOSURE')
    require(evidence['external_python_links'] == resolve_links(entries), 'INVALID_LINK_DEPENDENCIES')
    return value


def canonical(value):
    try:
        data = json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('ascii')
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise AuditFault('INVALID_JSON') from None
    require(len(data) <= MAX_JSON_BYTES, 'JSON_BYTE_LIMIT')
    return data


def parse(data, canonical_required=True):
    require(type(data) is bytes and len(data) <= MAX_JSON_BYTES, 'JSON_BYTE_LIMIT')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'DUPLICATE_KEY')
            result[key] = value
        return result
    try:
        value = json.loads(data, object_pairs_hook=pairs,
                           parse_constant=lambda _: require(False, 'INVALID_JSON'))
    except (ValueError, UnicodeError, RecursionError):
        raise AuditFault('INVALID_JSON') from None
    if canonical_required:
        require(canonical(value) == data, 'NON_CANONICAL_MANIFEST')
    return value
