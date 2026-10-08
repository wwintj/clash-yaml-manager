"""Manifest v1 protocol: pure validation/serialization, never filesystem writes.

Normative contract: docs/BACKUP_MANIFEST_V1.md. No runtime/store imports.
"""
import json
import re
import unicodedata


MANIFEST_NAME = 'BACKUP_MANIFEST.json'
SCHEMA_VERSION = 1
MAX_ENTRIES = 4096  # Includes root and the manifest control file.
MAX_DEPTH = 12
MAX_PATH_BYTES = 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
SNAPSHOT_TYPES = ('UPDATER_SNAPSHOT', 'UNINSTALL_DATA_SNAPSHOT', 'UI_OVERLAY_BACKUP')
SCOPES = ('FULL_TREE', 'DECLARED_EXCLUSIONS')
EXCLUSION_REASONS = ('VENV_NOT_VERIFIED', 'EPHEMERAL_RUNTIME', 'OUT_OF_SCOPE')
DIGEST_PATTERN = r'[0-9a-f]{64}'
MODE_PATTERN = r'0[0-7]{3}'
ENTRY_KEYS = {'path', 'type', 'size', 'sha256', 'mode', 'uid', 'gid'}


class ManifestError(ValueError):
    """Fixed code only; never retain or display names, bytes or parser errors."""
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def valid_digest(value):
    return isinstance(value, str) and re.fullmatch(DIGEST_PATTERN, value) is not None


def relative_path(value):
    if not isinstance(value, str) or not value or unicodedata.normalize('NFC', value) != value:
        raise ManifestError('NON_CANONICAL_PATH')
    if any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value) or '\\' in value or ':' in value:
        raise ManifestError('NON_CANONICAL_PATH')
    try:
        if len(value.encode('utf-8')) > MAX_PATH_BYTES:
            raise ManifestError('PATH_LIMIT')
    except UnicodeError:
        raise ManifestError('NON_CANONICAL_PATH') from None
    parts = value.split('/')
    if len(parts) > MAX_DEPTH:
        raise ManifestError('DEPTH_LIMIT')
    if any(p in ('', '.', '..') or p != p.strip(' ') or p.endswith('.') for p in parts):
        raise ManifestError('NON_CANONICAL_PATH')
    if value == MANIFEST_NAME:
        raise ManifestError('MANIFEST_SELF_REFERENCE')
    return tuple(parts)


def ancestors(path):
    parts = path.split('/')
    return ('/'.join(parts[:n]) for n in range(1, len(parts)))


def uint(value, maximum):
    return type(value) is int and 0 <= value <= maximum


def permission_metadata(value):
    if (not isinstance(value['mode'], str) or re.fullmatch(MODE_PATTERN, value['mode']) is None
            or not uint(value['uid'], 2**32 - 2) or not uint(value['gid'], 2**32 - 2)):
        raise ManifestError('INVALID_PERMISSION_METADATA')


def validate_manifest(value):
    if not isinstance(value, dict) or set(value) != {
        'schema_version', 'snapshot_type', 'snapshot_scope', 'root_metadata', 'entries', 'exclusions'
    }:
        raise ManifestError('INVALID_MANIFEST_SCHEMA')
    if type(value['schema_version']) is not int:
        raise ManifestError('INVALID_MANIFEST_SCHEMA')
    if value['schema_version'] != SCHEMA_VERSION:
        raise ManifestError('UNSUPPORTED_SCHEMA_VERSION')
    if value['snapshot_type'] not in SNAPSHOT_TYPES or value['snapshot_scope'] not in SCOPES:
        raise ManifestError('INVALID_MANIFEST_SCHEMA')
    root = value['root_metadata']
    if not isinstance(root, dict) or set(root) != {'mode', 'uid', 'gid'}:
        raise ManifestError('INVALID_PERMISSION_METADATA')
    permission_metadata(root)
    entries, exclusions = value['entries'], value['exclusions']
    if not isinstance(entries, list) or not isinstance(exclusions, list):
        raise ManifestError('INVALID_MANIFEST_SCHEMA')
    if len(entries) + 2 > MAX_ENTRIES or len(exclusions) > MAX_ENTRIES:
        raise ManifestError('ENTRY_LIMIT')
    by_path = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            raise ManifestError('INVALID_ENTRY_SCHEMA')
        path = entry['path']
        relative_path(path)
        if path in by_path:
            raise ManifestError('DUPLICATE_PATH')
        by_path[path] = entry
        permission_metadata(entry)
        if entry['type'] == 'file':
            if not uint(entry['size'], 2**63 - 1):
                raise ManifestError('INVALID_FILE_SIZE')
            if not valid_digest(entry['sha256']):
                raise ManifestError('MALFORMED_DIGEST')
        elif entry['type'] == 'directory':
            if entry['size'] is not None or entry['sha256'] is not None:
                raise ManifestError('INVALID_DIRECTORY_ENTRY')
        else:
            raise ManifestError('UNSAFE_MANIFEST_TYPE')
    if list(by_path) != sorted(by_path, key=lambda p: p.encode('utf-8')):
        raise ManifestError('NON_CANONICAL_ENTRY_ORDER')
    for path in by_path:
        if any(by_path.get(parent, {}).get('type') != 'directory' for parent in ancestors(path)):
            raise ManifestError('INVALID_ENTRY_HIERARCHY')
    excluded = []
    for exclusion in exclusions:
        if not isinstance(exclusion, dict) or set(exclusion) != {'path', 'reason'}:
            raise ManifestError('INVALID_EXCLUSION')
        path = exclusion['path']
        relative_path(path)
        if exclusion['reason'] not in EXCLUSION_REASONS or by_path.get(path, {}).get('type') != 'directory':
            raise ManifestError('INVALID_EXCLUSION')
        excluded.append(path)
    if len(set(excluded)) != len(excluded):
        raise ManifestError('DUPLICATE_EXCLUSION')
    if excluded != sorted(excluded, key=lambda p: p.encode('utf-8')):
        raise ManifestError('NON_CANONICAL_EXCLUSION_ORDER')
    excluded_set = set(excluded)
    if any(parent in excluded_set for path in by_path for parent in ancestors(path)):
        raise ManifestError('EXCLUSION_CONFLICT')
    if (value['snapshot_scope'] == 'FULL_TREE' and excluded
            or value['snapshot_scope'] == 'DECLARED_EXCLUSIONS' and not excluded):
        raise ManifestError('INVALID_SNAPSHOT_SCOPE')
    return value


def canonical_bytes(value):
    """Validated JSON: sorted object keys, ordered paths, ASCII escapes, no LF/BOM."""
    validate_manifest(value)
    data = json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(',', ':')).encode('ascii')
    if len(data) > MAX_MANIFEST_BYTES:
        raise ManifestError('MANIFEST_SIZE_LIMIT')
    return data


def load_manifest(data):
    if len(data) > MAX_MANIFEST_BYTES:
        raise ManifestError('MANIFEST_SIZE_LIMIT')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ManifestError('DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    def reject_constant(value):
        raise ManifestError('INVALID_MANIFEST_JSON')
    try:
        value = json.loads(data.decode('utf-8'), object_pairs_hook=unique, parse_constant=reject_constant)
    except ManifestError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise ManifestError('INVALID_MANIFEST_JSON') from None
    if data != canonical_bytes(value):
        raise ManifestError('NON_CANONICAL_MANIFEST')
    return value
