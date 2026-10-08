#!/usr/bin/env python3
"""Bounded, read-only structural inspection of local deployment backups.

No project/runtime imports, subprocesses, writes, manifest creation or restore.
All public output uses fixed categories/codes; inspected names and bytes stay private.
"""
import argparse
import ast
from contextlib import contextmanager
from datetime import datetime
import errno
import json
import os
import re
import stat
import time


MAX_ENTRIES = 4096
MAX_DEPTH = 12
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_SECONDS = 10
MAX_PATH_BYTES = 4096
MAX_PATH_PARTS = 64
VERSION_RE = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'
UNIT = 'clash-yaml-manager'
UPDATER = 'UPDATER_SNAPSHOT'
UNINSTALL = 'UNINSTALL_DATA_SNAPSHOT'
OVERLAY = 'UI_OVERLAY_BACKUP'

# A current structural readiness profile, not a claim about historical completeness.
# Each entry: public category, private paths, expected kind, applicable requirements.
SPECS = (
    ('VERSION', ('VERSION',), 'file', {UPDATER: 'REQUIRED', UNINSTALL: 'OPTIONAL', OVERLAY: 'REQUIRED'}),
    ('INSTALLATION_METADATA', ('INSTALLATION.json',), 'file', {UPDATER: 'OPTIONAL', UNINSTALL: 'OPTIONAL', OVERLAY: 'OPTIONAL'}),
    ('ENVIRONMENT', ('.env',), 'file', {UPDATER: 'REQUIRED', UNINSTALL: 'REQUIRED'}),
    ('DEFAULT_YAML', ('defaults/default.yaml',), 'file', {UPDATER: 'REQUIRED'}),
    ('APPLICATION', ('app.py', 'core'), 'mixed', {UPDATER: 'REQUIRED'}),
    ('TEMPLATES', ('templates', 'templates/index.html'), 'mixed', {UPDATER: 'REQUIRED', OVERLAY: 'REQUIRED'}),
    ('STATIC', ('static', 'static/ui.css'), 'mixed', {UPDATER: 'REQUIRED', OVERLAY: 'REQUIRED'}),
    ('STATE', ('state',), 'directory', {UPDATER: 'REQUIRED', UNINSTALL: 'REQUIRED'}),
    ('SERVICE_UNIT', (UNIT + '.service',), 'file', {UPDATER: 'REQUIRED'}),
    ('REFRESH_UNITS', (UNIT + '-refresh.service', UNIT + '-refresh.timer'), 'file', {UPDATER: 'OPTIONAL'}),
    ('HEALTH_UNITS', (UNIT + '-health.service', UNIT + '-health.timer'), 'file', {UPDATER: 'OPTIONAL'}),
    ('DEPENDENCY_SPEC', ('requirements.txt',), 'file', {UPDATER: 'REQUIRED'}),
    ('VENV', ('venv',), 'directory', {UPDATER: 'OPTIONAL'}),
    ('DEPLOYMENT_SCRIPTS', ('scripts',), 'directory', {UPDATER: 'OPTIONAL'}),
    ('HTTPS_METADATA', ('HTTPS_DEPLOYMENT.json',), 'file', {UPDATER: 'OPTIONAL', UNINSTALL: 'OPTIONAL'}),
    ('OUTPUTS', ('outputs',), 'directory', {UNINSTALL: 'OPTIONAL'}),
    ('PRIOR_BACKUPS', ('backups',), 'directory', {UNINSTALL: 'OPTIONAL'}),
)
FILE_PATHS = {tuple(p.split('/')) for _, paths, kind, _ in SPECS for p in paths
              if kind == 'file' or '/' in p or p == 'app.py'}


class AuditFault(Exception):
    def __init__(self, code, unsafe=False):
        super().__init__(code)
        self.code, self.unsafe = code, unsafe


def fingerprint(info):
    """Reading can update atime; identity/content/permission changes cannot pass."""
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def kind(info):
    if stat.S_ISDIR(info.st_mode):
        return 'directory'
    if stat.S_ISREG(info.st_mode):
        return 'file'
    return 'unsafe'


def io_fault(error):
    if error.errno in (errno.ELOOP, errno.ENOTDIR):
        return AuditFault('UNSAFE_PATH', True)
    if error.errno == errno.ENOENT:
        return AuditFault('PATH_MISSING_OR_CHANGED', True)
    return AuditFault('PERMISSION_DENIED' if error.errno in (errno.EACCES, errno.EPERM) else 'READ_FAILED')


def flags(directory=False):
    return (os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
            | (os.O_DIRECTORY if directory else 0))


@contextmanager
def root_directory(path):
    """Open every ancestor independently without resolving any symbolic link."""
    if not all(hasattr(os, name) for name in ('O_NOFOLLOW', 'O_NONBLOCK', 'O_DIRECTORY', 'O_CLOEXEC')):
        raise AuditFault('UNSUPPORTED_PLATFORM')
    raw = os.fspath(path)
    if not isinstance(raw, str) or '\x00' in raw or '..' in raw.split('/'):
        raise AuditFault('INVALID_PATH')
    absolute = os.path.abspath(raw)
    if len(os.fsencode(absolute)) > MAX_PATH_BYTES or len(absolute.split('/')) > MAX_PATH_PARTS:
        raise AuditFault('PATH_LIMIT')
    if absolute == '/opt/clash-yaml-manager' or absolute.startswith('/opt/clash-yaml-manager/'):
        raise AuditFault('LIVE_INSTALLATION_REFUSED', True)
    fd = os.open('/', flags(True))
    try:
        for part in absolute.split('/'):
            if not part:
                continue
            before = os.stat(part, dir_fd=fd, follow_symlinks=False)
            if kind(before) != 'directory':
                raise AuditFault('UNSAFE_ROOT_PATH', True)
            next_fd = os.open(part, flags(True), dir_fd=fd)
            try:
                if fingerprint(before) != fingerprint(os.fstat(next_fd)):
                    raise AuditFault('BACKUP_CHANGED', True)
            except BaseException:
                os.close(next_fd)
                raise
            os.close(fd)
            fd = next_fd
        yield fd, absolute
    finally:
        os.close(fd)


def classify(name, names):
    if re.fullmatch(r'clash-yaml-manager-update-backup-\d{8}_\d{6}\.[A-Za-z0-9]{6}', name):
        if names & {'VERSION', 'app.py', 'core', '.env', 'state'} and not names & {'outputs', 'backups'}:
            return UPDATER
    if re.fullmatch(r'clash-yaml-manager-backup-\d{8}_\d{6}', name):
        allowed = {'state', '.env', 'VERSION', 'INSTALLATION.json', 'HTTPS_DEPLOYMENT.json', 'outputs', 'backups'}
        if names <= allowed and names & {'state', '.env', 'outputs', 'backups'}:
            return UNINSTALL
    if re.fullmatch(r'clash-yaml-manager-v\d+\.\d+(?:\.\d+)?-ui-acceptance-\d{8}-\d{6}', name):
        if names <= {'VERSION', 'INSTALLATION.json', 'templates', 'static', 'baseline.json'} and names & {'templates', 'static'}:
            return OVERLAY
    return 'UNKNOWN'


class Inspector:
    def __init__(self):
        self.started = time.monotonic()
        self.read_bytes = 0

    def tick(self):
        if time.monotonic() - self.started > MAX_SECONDS:
            raise AuditFault('TIME_LIMIT')

    def entries(self, fd):
        names = []
        with os.scandir(fd) as scan:
            for entry in scan:
                self.tick()
                names.append(entry.name)
                if len(names) > MAX_ENTRIES:
                    raise AuditFault('ENTRY_LIMIT')
        return sorted(names)

    def snapshot(self, root_fd):
        records = {(): os.fstat(root_fd)}

        def walk(fd, prefix):
            self.tick()
            if len(prefix) > MAX_DEPTH:
                raise AuditFault('DEPTH_LIMIT')
            for name in self.entries(fd):
                self.tick()
                path = prefix + (name,)
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                records[path] = info
                if len(records) > MAX_ENTRIES:
                    raise AuditFault('ENTRY_LIMIT')
                # Never inspect venv contents (normal system-Python links are common).
                if kind(info) == 'directory' and path != ('venv',) and path not in FILE_PATHS:
                    if info.st_dev != records[()].st_dev:
                        raise AuditFault('FILESYSTEM_BOUNDARY', True)
                    child = os.open(name, flags(True), dir_fd=fd)
                    try:
                        if fingerprint(info) != fingerprint(os.fstat(child)):
                            raise AuditFault('BACKUP_CHANGED', True)
                        walk(child, path)
                    finally:
                        os.close(child)
        walk(root_fd, ())
        return records

    def read(self, root_fd, path, records):
        """Descriptor-relative bounded reads; no imports/evaluation of backup code."""
        self.tick()
        info = records[path]
        if kind(info) != 'file' or info.st_nlink != 1:
            raise AuditFault('UNSAFE_FILE', True)
        if info.st_size > MAX_FILE_BYTES:
            raise AuditFault('FILE_SIZE_LIMIT')
        fd = os.dup(root_fd)
        try:
            for index, part in enumerate(path):
                expected = records[path[:index + 1]]
                actual = os.stat(part, dir_fd=fd, follow_symlinks=False)
                if fingerprint(actual) != fingerprint(expected):
                    raise AuditFault('BACKUP_CHANGED', True)
                child = os.open(part, flags(index < len(path) - 1), dir_fd=fd)
                os.close(fd)
                fd = child
                if fingerprint(os.fstat(fd)) != fingerprint(expected):
                    raise AuditFault('BACKUP_CHANGED', True)
            pieces, size = [], 0
            while True:
                self.tick()
                piece = os.read(fd, min(65536, MAX_FILE_BYTES + 1 - size))
                if not piece:
                    break
                pieces.append(piece)
                size += len(piece)
                self.read_bytes += len(piece)
                if size > MAX_FILE_BYTES:
                    raise AuditFault('FILE_SIZE_LIMIT')
                if self.read_bytes > MAX_TOTAL_BYTES:
                    raise AuditFault('TOTAL_READ_LIMIT')
            if size != info.st_size or fingerprint(os.fstat(fd)) != fingerprint(info):
                raise AuditFault('BACKUP_CHANGED', True)
            return b''.join(pieces)
        finally:
            os.close(fd)


def parse_json(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result
    def reject_constant(value):
        raise ValueError
    return json.loads(text, object_pairs_hook=unique, parse_constant=reject_constant)


def installation_valid(value, version):
    if not isinstance(value, dict) or set(value) != {'channel', 'base_version', 'commit', 'tag', 'installed_at', 'source'}:
        return False
    base, channel = value['base_version'], value['channel']
    if not isinstance(base, str) or not re.fullmatch(VERSION_RE, base) or version is not None and base != version:
        return False
    if channel == 'local':
        valid = value['commit'] is None and value['tag'] is None and value['source'] == 'local-source'
    elif channel in ('stable', 'main'):
        valid = (isinstance(value['commit'], str) and bool(re.fullmatch(r'[0-9a-f]{40}', value['commit']))
                 and value['tag'] == ('v' + base if channel == 'stable' else None)
                 and value['source'] == ('github-release' if channel == 'stable' else 'github-main'))
    else:
        return False
    try:
        return valid and datetime.fromisoformat(value['installed_at']).tzinfo is not None
    except (ValueError, TypeError):
        return False


def validate_bytes(path, data, version):
    """Return fixed validation codes, never data or parser exception messages."""
    text = data.decode('utf-8')
    if not text.strip():
        raise AuditFault('EMPTY_CONTENT')
    if path == ('VERSION',):
        if not re.fullmatch(VERSION_RE + r'\n?', text):
            raise AuditFault('INVALID_VERSION')
        return ['VERSION_FORMAT_CHECKED']
    if path == ('INSTALLATION.json',):
        if not installation_valid(parse_json(text), version):
            raise AuditFault('INVALID_INSTALLATION_METADATA')
        return ['INSTALLATION_SCHEMA_CHECKED', 'IDENTITY_NOT_AUTHENTICATED']
    if path[-1].endswith('.json'):
        parse_json(text)
        return ['JSON_SYNTAX_CHECKED', 'BUSINESS_SCHEMA_NOT_CHECKED']
    if path[-1].endswith('.py'):
        ast.parse(data, filename='<backup-code>')
        return ['PYTHON_SYNTAX_CHECKED', 'CODE_NOT_EXECUTED']
    if path[-1].endswith(('.service', '.timer')):
        expected = '[Timer]' if path[-1].endswith('.timer') else '[Service]'
        sections = {line.strip() for line in text.splitlines() if line.strip().startswith('[')}
        if '[Unit]' not in sections or expected not in sections:
            raise AuditFault('INVALID_UNIT_SECTIONS')
        return ['UNIT_SECTIONS_CHECKED', 'UNIT_SEMANTICS_NOT_CHECKED']
    return ['NONEMPTY_UTF8_CHECKED', 'CONTENT_SEMANTICS_NOT_CHECKED']


def components(inspector, fd, records, backup_type):
    result, version = [], None
    for category, raw_paths, expected_kind, requirements in SPECS:
        requirement = requirements.get(backup_type, 'NOT_APPLICABLE')
        item = dict(component=category, requirement=requirement, status='NOT_APPLICABLE',
                    counts=dict(files=0, directories=0), validation_codes=[])
        result.append(item)
        if requirement == 'NOT_APPLICABLE':
            continue
        paths = [tuple(p.split('/')) for p in raw_paths]
        selected = {p: info for p, info in records.items() if any(p[:len(base)] == base for base in paths)}
        item['counts'] = {label: sum(kind(info) == kind_name for info in selected.values())
                          for label, kind_name in (('files', 'file'), ('directories', 'directory'))}
        missing = any(p not in records for p in paths)
        item['status'] = 'MISSING' if missing else 'PRESENT'
        codes = set()
        if missing:
            codes.add('MISSING_REQUIRED' if requirement == 'REQUIRED' else 'MISSING_OPTIONAL')
        try:
            for path in paths:
                if path not in records:
                    continue
                wanted = ('file' if path in FILE_PATHS else 'directory') if expected_kind == 'mixed' else expected_kind
                if kind(records[path]) != wanted:
                    raise AuditFault('WRONG_OBJECT_TYPE', True)
            if any(kind(info) == 'unsafe' or kind(info) == 'file' and info.st_nlink != 1 for info in selected.values()):
                raise AuditFault('UNSAFE_OBJECT', True)
            if category == 'VENV':
                if not missing:
                    codes.add('VENV_CONTENTS_NOT_INSPECTED')
            else:
                checked = 0
                for path, info in sorted(selected.items()):
                    if kind(info) != 'file':
                        continue
                    should_read = (path in FILE_PATHS or category == 'STATE' and path[-1].endswith('.json')
                                   or category == 'APPLICATION' and path[-1].endswith('.py'))
                    if not should_read:
                        codes.add('CONTENTS_NOT_INSPECTED')
                        continue
                    data = inspector.read(fd, path, records)
                    codes.update(validate_bytes(path, data, version))
                    checked += 1
                    if category == 'VERSION':
                        version = data.decode('utf-8').rstrip('\n')
                if not missing and category in ('STATE', 'APPLICATION') and checked < (1 if category == 'STATE' else 2):
                    raise AuditFault('REQUIRED_CONTENT_ABSENT')
        except AuditFault as fault:
            codes.add(fault.code)
            item['status'] = 'UNSAFE' if fault.unsafe else 'INVALID'
        except OSError as error:
            fault = io_fault(error)
            codes.add(fault.code)
            item['status'] = 'UNSAFE' if fault.unsafe else 'INVALID'
        except (ValueError, TypeError, SyntaxError, RecursionError, MemoryError):
            codes.add('INVALID_CONTENT')
            item['status'] = 'INVALID'
        item['validation_codes'] = sorted(codes)
    return result


def audit(path):
    report = dict(backup_type='UNKNOWN', structural_status='UNKNOWN', restore_proven=False,
                  counts=dict(files=0, directories=0), validation_codes=[], components=[])
    inspector = Inspector()
    try:
        with root_directory(path) as (fd, absolute):
            root_before = os.fstat(fd)
            names = inspector.entries(fd)
            report['backup_type'] = classify(os.path.basename(absolute), set(names))
            if report['backup_type'] == 'UNKNOWN':
                report['validation_codes'] = ['UNRECOGNIZED_LAYOUT', 'CONTENTS_NOT_INSPECTED']
                return report
            before = inspector.snapshot(fd)
            report['counts'] = {label: sum(kind(info) == kind_name for p, info in before.items() if p)
                                for label, kind_name in (('files', 'file'), ('directories', 'directory'))}
            report['components'] = components(inspector, fd, before, report['backup_type'])
            unsafe = any(kind(info) == 'unsafe' or kind(info) == 'file' and info.st_nlink != 1
                         for info in before.values())
            after = inspector.snapshot(fd)
            if {p: fingerprint(info) for p, info in before.items()} != {p: fingerprint(info) for p, info in after.items()}:
                raise AuditFault('BACKUP_CHANGED', True)
            with root_directory(absolute) as (final_fd, _):
                if fingerprint(root_before) != fingerprint(os.fstat(final_fd)):
                    raise AuditFault('BACKUP_CHANGED', True)
            if unsafe or any(c['status'] == 'UNSAFE' for c in report['components']):
                report['structural_status'] = 'UNSAFE'
                report['validation_codes'] = ['UNSAFE_OBJECT']
            elif any(c['status'] == 'INVALID' or c['requirement'] == 'REQUIRED' and c['status'] == 'MISSING'
                     for c in report['components']):
                report['structural_status'] = 'STRUCTURALLY_INCOMPLETE'
            else:
                report['structural_status'] = 'STRUCTURALLY_COMPLETE'
            report['validation_codes'].append('NO_TRUSTED_MANIFEST')
    except AuditFault as fault:
        report['structural_status'] = 'UNSAFE' if fault.unsafe else ('UNKNOWN' if report['backup_type'] == 'UNKNOWN' else 'STRUCTURALLY_INCOMPLETE')
        report['validation_codes'] = [fault.code]
    except OSError as error:
        fault = io_fault(error)
        report['structural_status'] = 'UNSAFE' if fault.unsafe else ('UNKNOWN' if report['backup_type'] == 'UNKNOWN' else 'STRUCTURALLY_INCOMPLETE')
        report['validation_codes'] = [fault.code]
    except (ValueError, TypeError, RecursionError, MemoryError):
        report['structural_status'] = 'STRUCTURALLY_INCOMPLETE'
        report['validation_codes'] = ['INSPECTION_FAILED']
    return report


def render(report, as_json=False):
    if as_json:
        return json.dumps(report, sort_keys=True, ensure_ascii=True)
    lines = [f"backup_type: {report['backup_type']}", f"structural_status: {report['structural_status']}",
             'restore_proven: false', f"counts: {json.dumps(report['counts'], sort_keys=True)}",
             'validation_codes: ' + ', '.join(report['validation_codes'])]
    for component in report['components']:
        lines.append(f"{component['component']}: {component['requirement']} / {component['status']} / "
                     f"{json.dumps(component['counts'], sort_keys=True)} / " + ', '.join(component['validation_codes']))
    return '\n'.join(lines)


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's normal diagnostics echo untrusted arguments (possibly credentials).
        raise AuditFault('INVALID_ARGUMENTS')


def main(argv=None):
    import sys
    args_list = sys.argv[1:] if argv is None else argv
    parser = SafeParser(prog='backup_audit.py', description='Read-only structural backup audit; restore_proven=false.')
    parser.add_argument('--path', required=True, help='Local backup directory (no symlink ancestors).')
    parser.add_argument('--json', action='store_true', help='Output fixed categories and codes as JSON.')
    try:
        args = parser.parse_args(args_list)
        report = audit(args.path)
    except AuditFault:
        report = dict(backup_type='UNKNOWN', structural_status='UNKNOWN', restore_proven=False,
                      counts=dict(files=0, directories=0), components=[], validation_codes=['INVALID_ARGUMENTS'])
        print(render(report, '--json' in args_list))
        return 64
    print(render(report, args.json))
    return {'STRUCTURALLY_COMPLETE': 0, 'STRUCTURALLY_INCOMPLETE': 1, 'UNSAFE': 2, 'UNKNOWN': 3}[report['structural_status']]


if __name__ == '__main__':
    raise SystemExit(main())
