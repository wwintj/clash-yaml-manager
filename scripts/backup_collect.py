#!/usr/bin/env python3
"""Bounded offline allowlist collector; no runtime, updater, trust store or restore."""
import sys

if __name__ == '__main__':
    sys.dont_write_bytecode = True

import errno
import hashlib
import json
import os
import re
import secrets
import stat
import time

if __package__:
    from . import backup_create as writer, backup_verify as verifier, backup_manifest as protocol
    from .backup_audit import AuditFault, SafeParser, fingerprint, flags, io_fault, kind, root_directory
    from .backup_audit import parse_json, installation_valid, VERSION_RE
else:
    import backup_create as writer
    import backup_verify as verifier
    import backup_manifest as protocol
    from backup_audit import AuditFault, SafeParser, fingerprint, flags, io_fault, kind, root_directory
    from backup_audit import parse_json, installation_valid, VERSION_RE

PROFILE = 'updater-sidecar-v1'
SOURCE_CONTROL = 'COLLECTOR_SOURCE.json'
SCOPE_FILE = 'COLLECTION_SCOPE.json'
OWNERSHIP_FILE = 'SOURCE_OWNERSHIP.json'
MAX_ENTRIES = 512  # Includes inspected omission roots + generated controls + future manifest.
MAX_DEPTH = 8
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_SECONDS = 10
MAX_READ_BYTES = 256 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_CONTROL_BYTES = 16 * 1024
MAX_METADATA_BYTES = 256 * 1024
CHUNK_BYTES = verifier.CHUNK_BYTES
STATE_VERSIONS = {'auth.json': (1,), 'fixed_subscriptions.json': (1, 2, 3, 4, 5, 6),
                  'node_health.json': (1, 2), 'proxy_health.json': (1, 2),
                  'settings.json': (1,), 'notifications.json': (1,),
                  'temporary_links.json': (1,), 'login_attempts.json': (1,)}
LOCKS = {'auth.lock', 'fixed_subscriptions.lock', 'node_health.lock', 'proxy_health.lock',
         'proxy_probe.lock', 'geoip.lock', 'notifications.lock', 'temporary_links.lock',
         'login_attempts.lock', 'auto_refresh.lock', 'auto_health.lock'}
ROOT_OMISSIONS = {'venv': 'directory', 'uploads': 'directory', 'outputs': 'directory',
                  'backups': 'directory', 'logs': 'directory', 'bin': 'directory',
                  'core': 'directory', 'templates': 'directory', 'static': 'directory',
                  'scripts': 'directory', 'nginx': 'directory', 'certificates': 'directory',
                  'app.py': 'file', 'requirements.txt': 'file', 'install.sh': 'file',
                  'update.sh': 'file', 'uninstall.sh': 'file', 'remote-install.sh': 'file',
                  'remote-update.sh': 'file', 'httpsctl.sh': 'file', 'mihomoctl.sh': 'file',
                  'HTTPS_DEPLOYMENT.json': 'file', '.httpsctl.lock': 'file'}
REQUIRED = {(), (SOURCE_CONTROL,), ('.env',), ('VERSION',), ('defaults',),
            ('defaults', 'default.yaml'), ('state',), ('state', 'auth.json')}
OPTIONAL = {('INSTALLATION.json',), ('.service-account',), ('state', 'fixed_subscriptions'),
            ('state', 'geoip'), ('state', 'geoip', 'active.mmdb')} | {
                ('state', name) for name in STATE_VERSIONS if name != 'auth.json'}
ID = re.compile(r'[0-9a-f]{32}\Z')


def policy(path):
    """Fixed paths/grammar; reject unknown paths BEFORE traversal or payload open."""
    if not path:
        return 'directory', 'OPERATOR_ROOT', True
    if len(path) == 1:
        if path[0] in (SOURCE_CONTROL, '.env', 'VERSION', 'INSTALLATION.json', '.service-account'):
            return 'file', 'OPERATOR_CONFIGURATION', True
        if path[0] in ('defaults', 'state'):
            return 'directory', 'PERSISTENT_STATE' if path[0] == 'state' else 'OPERATOR_CONFIGURATION', True
        if path[0] in ROOT_OMISSIONS:
            return ROOT_OMISSIONS[path[0]], 'OUT_OF_SCOPE', False
    if path == ('defaults', 'default.yaml'):
        return 'file', 'OPERATOR_CONFIGURATION', True
    if len(path) == 2 and path[0] == 'state':
        if path[1] in STATE_VERSIONS:
            return 'file', 'PERSISTENT_STATE', True
        if path[1] in ('fixed_subscriptions', 'geoip'):
            return 'directory', 'PERSISTENT_STATE', True
        if path[1] in LOCKS:
            return 'file', 'LOCK_NOT_COLLECTED', False
        if re.fullmatch(r'\.(?:proxy-probe|fixed-candidate|geoip-upload)-[A-Za-z0-9_-]{1,64}', path[1]):
            return 'directory', 'EPHEMERAL_NOT_COLLECTED', False
        if any(re.fullmatch(r'\.' + re.escape(name) + r'-[A-Za-z0-9_-]{1,64}', path[1]) for name in STATE_VERSIONS):
            return 'file', 'EPHEMERAL_NOT_COLLECTED', False
    if path == ('state', 'geoip', 'active.mmdb'):
        return 'file', 'PERSISTENT_STATE', True
    if path[:2] == ('state', 'fixed_subscriptions'):
        tail = path[2:]
        if len(tail) in (1, 2) and all(ID.fullmatch(p) for p in tail):
            return 'directory', 'FIXED_REVISION', True
        if len(tail) == 3 and all(ID.fullmatch(p) for p in tail[:2]):
            if tail[2] in ('base.yaml', 'current.yaml'):
                return 'file', 'FIXED_REVISION', True
            if tail[2] == 'sources':
                return 'directory', 'FIXED_SOURCE_CACHE', True
        if len(tail) in (4, 5) and all(ID.fullmatch(p) for p in tail[:2]) and tail[2] == 'sources' and ID.fullmatch(tail[3]):
            if len(tail) == 4:
                return 'directory', 'FIXED_SOURCE_CACHE', True
            if tail[4] == 'payload.bin':
                return 'file', 'FIXED_SOURCE_CACHE', True
    raise AuditFault('UNEXPECTED_COMPONENT')


def canonical(value, limit):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                     separators=(',', ':')).encode('ascii')
    if len(raw) > limit:
        raise AuditFault('METADATA_SIZE_LIMIT')
    return raw


def empty_report():
    return dict(collection_status='FAILED', publication_status='NOT_PUBLISHED', profile=PROFILE,
                collected_representation_only=True, restore_proven=False, trust_anchor_verified=False,
                cleanup_status='NOT_NEEDED', residual_staging_name=None, retained_destination=False,
                counts=dict(files=0, directories=0, omitted_roots=0), validation_codes=[])


class Collector(writer.Writer):
    """Reuse unchanged Writer fd/inode ledger primitives, never weaken its gates."""
    def tick(self):
        if time.monotonic() - self.started > MAX_SECONDS:
            raise AuditFault('TIME_LIMIT')

    def charge_read(self, size):
        self.read_bytes = getattr(self, 'read_bytes', 0) + size
        if self.read_bytes > MAX_READ_BYTES:
            raise AuditFault('TOTAL_READ_LIMIT')

    def consume(self, root_fd, path, records, collect=False):
        self.charge_read(records[path].st_size)
        return super().consume(root_fd, path, records, collect)

    def bounded_bytes(self, root_fd, path, records, limit):
        info = records[path]
        if info.st_size > limit:
            raise AuditFault('CONTENT_SIZE_LIMIT')
        pieces, remaining = [], info.st_size
        with self.open_record(root_fd, path, records) as fd:
            while remaining:
                self.tick()
                piece = os.read(fd, min(CHUNK_BYTES, remaining))
                if not piece:
                    raise AuditFault('BACKUP_CHANGED')
                self.charge_read(len(piece))
                pieces.append(piece)
                remaining -= len(piece)
            if fingerprint(os.fstat(fd)) != fingerprint(info):
                raise AuditFault('BACKUP_CHANGED')
        self.tick()
        return b''.join(pieces)

    def trusted_control(self, source_fd):
        root = os.fstat(source_fd)
        if root.st_uid != os.geteuid() or root.st_gid != os.getegid() or stat.S_IMODE(root.st_mode) != 0o700:
            raise AuditFault('UNSAFE_SOURCE_ROOT')
        try:
            info = os.stat(SOURCE_CONTROL, dir_fd=source_fd, follow_symlinks=False)
        except FileNotFoundError:
            raise AuditFault('MISSING_REQUIRED_COMPONENT') from None
        if (kind(info) != 'file' or info.st_nlink != 1 or info.st_dev != root.st_dev
                or info.st_uid != os.geteuid() or info.st_gid != os.getegid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise AuditFault('UNTRUSTED_SOURCE_DECLARATION')
        value = parse_json(self.bounded_bytes(source_fd, (SOURCE_CONTROL,), {(SOURCE_CONTROL,): info}, MAX_CONTROL_BYTES))
        if (not isinstance(value, dict) or set(value) != {'schema_version', 'profile', 'offline', 'writers_quiet', 'service_account'}
                or type(value['schema_version']) is not int or value['schema_version'] != 1
                or value['profile'] != PROFILE or value['offline'] is not True or value['writers_quiet'] is not True):
            raise AuditFault('OFFLINE_QUIET_NOT_ATTESTED')
        service = value['service_account']
        if service is not None:
            if (not isinstance(service, dict) or set(service) != {'name', 'uid', 'gid'} or service['name'] != 'clashyaml'
                    or type(service['uid']) is not int or not 0 < service['uid'] < 2**32 - 1
                    or type(service['gid']) is not int or not 0 < service['gid'] < 2**32 - 1
                    or service['uid'] == os.geteuid()):
                raise AuditFault('INVALID_SERVICE_IDENTITY')
            if os.geteuid() != 0:
                raise AuditFault('MIXED_OWNER_REQUIRES_ROOT')
        return value

    def inventory(self, root_fd):
        self.declaration = self.trusted_control(root_fd)
        records = {(): os.fstat(root_fd)}
        seen = 1
        def walk(fd, prefix):
            nonlocal seen
            self.tick()
            names = []
            with os.scandir(fd) as scan:
                for entry in scan:
                    self.tick()
                    seen += 1
                    if seen + 3 > MAX_ENTRIES:
                        raise AuditFault('ENTRY_LIMIT')
                    names.append(entry.name)
            for name in sorted(names, key=os.fsencode):
                self.tick()
                path = prefix + (name,)
                if len(path) > MAX_DEPTH:
                    raise AuditFault('DEPTH_LIMIT')
                protocol.relative_path('/'.join(path))
                wanted, role, selected = policy(path)
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if kind(info) != wanted or wanted == 'file' and info.st_nlink != 1:
                    raise AuditFault('UNSAFE_OBJECT')
                if info.st_dev != records[()].st_dev:
                    raise AuditFault('FILESYSTEM_BOUNDARY')
                records[path] = info
                if role != 'OUT_OF_SCOPE':
                    pairs = {(os.geteuid(), os.getegid())}
                    service = self.declaration['service_account']
                    if path[0] == 'state' and service is not None:
                        pairs.add((service['uid'], service['gid']))
                    if (info.st_uid, info.st_gid) not in pairs:
                        raise AuditFault('UNSAFE_SOURCE_OWNERSHIP')
                    mode = stat.S_IMODE(info.st_mode)
                    private = path[0] == 'state' or path in ((SOURCE_CONTROL,), ('.env',), ('.service-account',))
                    if mode & 0o7000 or (private and mode != (0o700 if wanted == 'directory' else 0o600)) or (not private and mode & 0o022):
                        raise AuditFault('UNSAFE_SOURCE_PERMISSION')
                if selected and wanted == 'file' and info.st_size > MAX_FILE_BYTES:
                    raise AuditFault('FILE_BYTE_LIMIT')
                if selected and wanted == 'directory':
                    with self.open_record(root_fd, path, records) as child:
                        walk(child, path)
        walk(root_fd, ())
        if not REQUIRED <= set(records):
            raise AuditFault('MISSING_REQUIRED_COMPONENT')
        service = self.declaration['service_account']
        if service is not None:
            marker = ('.service-account',)
            if marker not in records:
                raise AuditFault('SERVICE_MARKER_REQUIRED')
            data = self.bounded_bytes(root_fd, marker, records, MAX_CONTROL_BYTES)
            if data != f"clashyaml:{service['uid']}:{service['gid']}\n".encode('ascii'):
                raise AuditFault('SERVICE_IDENTITY_MISMATCH')
        selected = {p: i for p, i in records.items() if policy(p)[2]}
        if sum(i.st_size for i in selected.values() if kind(i) == 'file') + protocol.MAX_MANIFEST_BYTES > MAX_TOTAL_BYTES:
            raise AuditFault('TOTAL_BYTE_LIMIT')
        version = self.bounded_bytes(root_fd, ('VERSION',), records, MAX_CONTROL_BYTES).decode('utf-8')
        if re.fullmatch(VERSION_RE + r'\n?', version) is None:
            raise AuditFault('INVALID_VERSION')
        if records[('.env',)].st_size == 0 or records[('defaults', 'default.yaml')].st_size == 0:
            raise AuditFault('EMPTY_REQUIRED_COMPONENT')
        for path in selected:
            if path == ('INSTALLATION.json',):
                data = parse_json(self.bounded_bytes(root_fd, path, records, MAX_JSON_BYTES))
                if not installation_valid(data, version.rstrip('\n')):
                    raise AuditFault('INVALID_INSTALLATION_METADATA')
            elif len(path) == 2 and path[0] == 'state' and path[1] in STATE_VERSIONS:
                data = parse_json(self.bounded_bytes(root_fd, path, records, MAX_JSON_BYTES))
                if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] not in STATE_VERSIONS[path[1]]:
                    raise AuditFault('UNSUPPORTED_STATE_ENVELOPE')
        return records, selected

    def make_stage(self, parent_fd):
        name = '.backup-collect-' + secrets.token_hex(16)
        self.stage_name = name  # Record a possible mkdir result even on interruption.
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            self.stage_name = None  # A collision never establishes ownership.
            raise AuditFault('STAGING_NAME_COLLISION') from None
        self.owned[()] = writer.identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False))
        self.stage_fd = os.open(name, flags(True), dir_fd=parent_fd)
        if writer.identity(os.fstat(self.stage_fd)) != self.owned[()]:
            raise AuditFault('STAGING_CHANGED')
        os.fchmod(self.stage_fd, 0o700)

    def check_source(self, fd, absolute, before):
        after, _ = self.inventory(fd)
        if {p: fingerprint(i) for p, i in after.items()} != {p: fingerprint(i) for p, i in before.items()}:
            raise AuditFault('BACKUP_CHANGED')
        with root_directory(absolute) as (current, _):
            if fingerprint(os.fstat(current)) != fingerprint(before[()]):
                raise AuditFault('BACKUP_CHANGED')
        self.tick()

    def metadata_files(self, records, selected):
        omitted = [{'path': '/'.join(p), 'reason': policy(p)[1], 'contents_inspected': False}
                   for p in sorted(records) if p and not policy(p)[2]]
        scope = dict(schema_version=1, profile=PROFILE, source_scope='ALLOWLIST_SUBSET',
                     writer_full_tree_means='COLLECTED_REPRESENTATION_ONLY', restore_proven=False,
                     atomic_source_snapshot=False, writers_quiet='OPERATOR_ATTESTED',
                     business_closure_verified=False, source_provenance_authenticated=False,
                     missing_optional=sorted('/'.join(p) for p in OPTIONAL - set(records)),
                     omitted_roots=omitted, out_of_scope=sorted(ROOT_OMISSIONS),
                     unsupported='UNKNOWN_PATH_OR_UNSUPPORTED_STATE_ENVELOPE',
                     external_scope_not_collected=['SYSTEM_DEPENDENCIES', 'EXTERNAL_CERTIFICATES', 'NGINX_CONFIGURATION'])
        ownership = dict(schema_version=1, profile=PROFILE, restore_mapping_applied=False,
                         collected_owner=dict(uid=os.geteuid(), gid=os.getegid()),
                         collected_modes=dict(directory='0700', file='0600'),
                         operator_declaration=self.declaration,
                         original_entries=[dict(path='/'.join(p) if p else '.', type=kind(i),
                             role=policy(p)[1], original=writer.metadata(i)) for p, i in sorted(selected.items())])
        return {SCOPE_FILE: canonical(scope, MAX_METADATA_BYTES), OWNERSHIP_FILE: canonical(ownership, MAX_METADATA_BYTES)}

    def snapshot(self, root_fd, exclusions):
        # Output inventory uses Collector's own bounds, including a future manifest.
        records = {(): os.fstat(root_fd)}
        seen = 1
        def walk(fd, prefix):
            nonlocal seen
            names = []
            with os.scandir(fd) as scan:
                for entry in scan:
                    self.tick()
                    seen += 1
                    if seen + 1 > MAX_ENTRIES:
                        raise AuditFault('ENTRY_LIMIT')
                    names.append(entry.name)
            for name in sorted(names, key=os.fsencode):
                self.tick()
                path = prefix + (name,)
                if len(path) > MAX_DEPTH:
                    raise AuditFault('DEPTH_LIMIT')
                protocol.relative_path('/'.join(path))
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if kind(info) == 'unsafe' or kind(info) == 'file' and info.st_nlink != 1:
                    raise AuditFault('UNSAFE_OBJECT')
                if info.st_dev != records[()].st_dev:
                    raise AuditFault('FILESYSTEM_BOUNDARY')
                records[path] = info
                if kind(info) == 'directory':
                    with self.open_record(root_fd, path, records) as child:
                        walk(child, path)
        walk(root_fd, ())
        return records

    def validate_output(self):
        records = self.snapshot(self.stage_fd, set())
        if set(records) != set(self.owned):
            raise AuditFault('STAGING_CHANGED')
        self.total_bytes = 0
        for path, info in records.items():
            self.tick()
            if (writer.identity(info) != self.owned[path] or info.st_uid != os.geteuid()
                    or info.st_gid != os.getegid() or stat.S_IMODE(info.st_mode) != (0o700 if kind(info) == 'directory' else 0o600)):
                raise AuditFault('STAGING_CHANGED')
            if kind(info) == 'file':
                if info.st_size > MAX_FILE_BYTES or info.st_size != self.digests[path][0]:
                    raise AuditFault('STORED_BYTES_MISMATCH')
                if (info.st_size, self.consume(self.stage_fd, path, records)) != self.digests[path]:
                    raise AuditFault('STORED_BYTES_MISMATCH')
        self.tick()

    def run_collection(self, source_fd, source_absolute, parent_fd, parent_absolute, name, report):
        self.check_parent(parent_fd, parent_absolute)
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise AuditFault('DESTINATION_EXISTS')
        publish = writer.publication_function()
        before, selected = self.inventory(source_fd)
        controls = self.metadata_files(before, selected)
        if sum(i.st_size for i in selected.values() if kind(i) == 'file') + sum(map(len, controls.values())) + protocol.MAX_MANIFEST_BYTES > MAX_TOTAL_BYTES:
            raise AuditFault('TOTAL_BYTE_LIMIT')
        self.charge_read(sum(i.st_size for i in selected.values() if kind(i) == 'file'))
        self.make_stage(parent_fd)
        self.copy(source_fd, selected)
        for name_control, data in controls.items():
            path = (name_control,)
            with self.new_file(path) as fd:
                self.write_all(fd, data)
                os.fsync(fd)
            self.digests[path] = (len(data), hashlib.sha256(data).hexdigest())
        self.check_source(source_fd, source_absolute, before)
        self.validate_output()
        self.sync_directories(parent_fd)
        self.check_parent(parent_fd, parent_absolute)
        self.check_stage(parent_fd, self.stage_name)
        self.check_source(source_fd, source_absolute, before)
        publish(parent_fd, self.stage_name, name)
        self.published = True
        report['publication_status'] = 'PUBLISHED'
        os.fsync(parent_fd)
        self.check_parent(parent_fd, parent_absolute)
        self.check_stage(parent_fd, name)
        self.validate_output()
        self.check_source(source_fd, source_absolute, before)
        report['counts'] = dict(files=len(self.digests), directories=len(self.owned) - len(self.digests),
                               omitted_roots=sum(not policy(p)[2] for p in before))
        report['collection_status'] = 'COLLECTED'


def finish_staging(collector, parent_fd, name, report, codes):
    if not collector.stage_name or report['collection_status'] == 'COLLECTED':
        return
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        collector.published = collector.published or writer.identity(info) == collector.owned.get(())
    except FileNotFoundError:
        pass
    except OSError:
        report['publication_status'] = 'UNCERTAIN'
    if collector.published or report['publication_status'] == 'UNCERTAIN':
        report['publication_status'] = 'PUBLISHED' if collector.published else 'UNCERTAIN'
        report['retained_destination'] = True
        report['cleanup_status'] = 'NOT_ATTEMPTED_PUBLISHED' if collector.published else 'NOT_ATTEMPTED_UNCERTAIN'
        if not collector.published:
            report['residual_staging_name'] = collector.stage_name
        codes.add('PUBLISHED_RESULT_NOT_CONFIRMED')
    else:
        try:
            collector.cleanup(parent_fd)
            report['cleanup_status'] = 'CLEANED'
        except (Exception, KeyboardInterrupt):
            report['cleanup_status'] = 'FAILED'
            report['residual_staging_name'] = collector.stage_name
            codes.add('CLEANUP_FAILED')


def collect(source, destination, profile):
    report, collector = empty_report(), Collector()
    codes = {'RESTORE_NOT_PROVEN', 'TRUST_ANCHOR_NOT_ESTABLISHED', 'COLLECTED_REPRESENTATION_ONLY'}
    try:
        if profile != PROFILE:
            raise AuditFault('INVALID_PROFILE')
        parent, name = writer.destination_parts(destination)
        with root_directory(source) as (fd, absolute), root_directory(parent) as (parent_fd, parent_absolute):
            if absolute == '/' or os.path.commonpath((absolute, parent_absolute)) == absolute:
                raise AuditFault('OVERLAPPING_PATHS')
            try:
                collector.run_collection(fd, absolute, parent_fd, parent_absolute, name, report)
            finally:
                finish_staging(collector, parent_fd, name, report, codes)
    except (AuditFault, protocol.ManifestError) as error:
        codes.add(error.code)
    except OSError as error:
        codes.add('DISK_FULL' if error.errno == errno.ENOSPC else io_fault(error).code)
    except KeyboardInterrupt:
        codes.add('COLLECTION_INTERRUPTED')
    except (ValueError, TypeError, UnicodeError, RecursionError, MemoryError):
        codes.add('INVALID_COMPONENT_CONTENT')
    except Exception:
        codes.add('COLLECTION_FAILED')
    finally:
        if collector.stage_fd is not None:
            try:
                os.close(collector.stage_fd)
            except OSError:
                codes.add('HANDLE_CLOSE_FAILED')
    if report['collection_status'] == 'COLLECTED' and 'HANDLE_CLOSE_FAILED' in codes:
        report['collection_status'] = 'FAILED'
        report['retained_destination'] = True
        report['cleanup_status'] = 'NOT_ATTEMPTED_PUBLISHED'
        codes.add('PUBLISHED_RESULT_NOT_CONFIRMED')
    report['validation_codes'] = sorted(codes)
    return report


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    parser = SafeParser(prog='backup_collect.py', description='Quiet offline allowlist collection; restore_proven=false.', allow_abbrev=False)
    parser.add_argument('--source', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--profile', required=True)
    try:
        args = parser.parse_args(arguments)
    except AuditFault:
        result = empty_report()
        result['validation_codes'] = ['INVALID_ARGUMENTS', 'RESTORE_NOT_PROVEN']
        print(json.dumps(result, sort_keys=True))
        return 64
    result = collect(args.source, args.destination, args.profile)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['collection_status'] == 'COLLECTED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
