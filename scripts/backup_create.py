#!/usr/bin/env python3
"""Bounded offline snapshot creation. No runtime, deployment, restore or trust store."""
import sys

if __name__ == '__main__':
    sys.dont_write_bytecode = True

from contextlib import contextmanager
import ctypes
import errno
import hashlib
import json
import os
import secrets
import stat
import time

if __package__:
    from . import backup_manifest as protocol, backup_verify as verifier
    from .backup_audit import AuditFault, SafeParser, fingerprint, flags, io_fault, kind, root_directory
else:
    import backup_manifest as protocol
    import backup_verify as verifier
    from backup_audit import AuditFault, SafeParser, fingerprint, flags, io_fault, kind, root_directory


MAX_ENTRIES = verifier.MAX_ENTRIES
MAX_DEPTH = verifier.MAX_DEPTH
MAX_FILE_BYTES = verifier.MAX_FILE_BYTES
MAX_TOTAL_BYTES = verifier.MAX_TOTAL_BYTES
MAX_SECONDS = verifier.MAX_SECONDS
CHUNK_BYTES = verifier.CHUNK_BYTES


def identity(info):
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def metadata(info):
    return dict(mode=f'{stat.S_IMODE(info.st_mode):04o}', uid=info.st_uid, gid=info.st_gid)


def publication_function():
    """Never fall back to POSIX rename, which can overwrite an empty destination."""
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith('linux'):
        function = getattr(library, 'renameat2', None)
        option = 1  # RENAME_NOREPLACE
    elif sys.platform == 'darwin':
        function = getattr(library, 'renameatx_np', None)
        option = 4  # RENAME_EXCL
    else:
        function = None
    if function is None:
        raise AuditFault('NO_REPLACE_UNAVAILABLE')
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    def publish(parent_fd, staging_name, destination_name):
        if function(parent_fd, os.fsencode(staging_name), parent_fd, os.fsencode(destination_name), option):
            number = ctypes.get_errno()
            if number in (errno.EEXIST, errno.ENOTEMPTY):
                raise AuditFault('DESTINATION_EXISTS')
            if number in (errno.ENOSYS, errno.EINVAL, errno.ENOTSUP):
                raise AuditFault('NO_REPLACE_UNAVAILABLE')
            raise OSError(number, 'atomic publication failed')
    return publish


def destination_parts(path):
    raw = os.fspath(path)
    if not isinstance(raw, str) or not raw or '\x00' in raw or '..' in raw.split('/'):
        raise AuditFault('INVALID_PATH')
    absolute = os.path.abspath(raw)
    if absolute == '/opt/clash-yaml-manager' or absolute.startswith('/opt/clash-yaml-manager/'):
        raise AuditFault('LIVE_INSTALLATION_REFUSED')
    # A final slash / dot cannot silently turn an existing directory into a target.
    if raw.endswith('/') or raw.split('/')[-1] in ('', '.'):
        raise AuditFault('INVALID_PATH')
    parent, name = os.path.split(absolute)
    if len(protocol.relative_path(name)) != 1 or len(os.fsencode(absolute)) > 4096:
        raise AuditFault('INVALID_PATH')
    return parent, name


def empty_report():
    return dict(creation_status='FAILED', publication_status='NOT_PUBLISHED',
                MANIFEST_SHA256=None, trust_anchor_verified=False, restore_proven=False,
                cleanup_status='NOT_NEEDED', residual_staging_name=None,
                retained_destination=False, verification=None, validation_codes=[])


class Writer(verifier.Verifier):
    def __init__(self):
        super().__init__()
        self.owned = {}
        self.digests = {}
        self.stage_fd = None
        self.stage_name = None
        self.published = False
        self.verification = None

    def tick(self):
        if time.monotonic() - self.started > MAX_SECONDS:
            raise AuditFault('TIME_LIMIT')

    def source_snapshot(self, fd, exclusions):
        records = self.snapshot(fd, exclusions)
        if len(records) + 1 > MAX_ENTRIES:
            raise AuditFault('ENTRY_LIMIT')
        for path, info in records.items():
            if path:
                protocol.relative_path('/'.join(path))
                if len(path) > MAX_DEPTH:
                    raise AuditFault('DEPTH_LIMIT')
            if kind(info) == 'directory':
                if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
                    raise AuditFault('UNSAFE_SOURCE_DIRECTORY')
            elif info.st_size > MAX_FILE_BYTES:
                raise AuditFault('FILE_BYTE_LIMIT')
        if sum(info.st_size for info in records.values() if kind(info) == 'file') > MAX_TOTAL_BYTES:
            raise AuditFault('TOTAL_BYTE_LIMIT')
        if not exclusions <= set(records) or any(kind(records[p]) != 'directory' for p in exclusions):
            raise AuditFault('INVALID_EXCLUSION')
        return records

    @contextmanager
    def owned_directory(self, path=()):
        fd = os.dup(self.stage_fd)
        try:
            if identity(os.fstat(fd)) != self.owned[()]:
                raise AuditFault('STAGING_CHANGED')
            for n, name in enumerate(path):
                expected = self.owned[path[:n + 1]]
                before = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if kind(before) != 'directory' or identity(before) != expected:
                    raise AuditFault('STAGING_CHANGED')
                child = os.open(name, flags(True), dir_fd=fd)
                os.close(fd)
                fd = child
                if identity(os.fstat(fd)) != expected:
                    raise AuditFault('STAGING_CHANGED')
            yield fd
        finally:
            os.close(fd)

    def make_stage(self, parent_fd):
        name = '.backup-create-' + secrets.token_hex(16)
        os.mkdir(name, 0o700, dir_fd=parent_fd)  # EEXIST never owns / cleans the collision.
        self.stage_name = name
        self.owned[()] = identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False))
        self.stage_fd = os.open(name, flags(True), dir_fd=parent_fd)
        if identity(os.fstat(self.stage_fd)) != self.owned[()]:
            raise AuditFault('STAGING_CHANGED')
        os.fchmod(self.stage_fd, 0o700)

    def write_all(self, fd, data):
        view = memoryview(data)
        while view:
            self.tick()
            written = os.write(fd, view)
            if written <= 0:
                raise AuditFault('WRITE_FAILED')
            view = view[written:]

    @contextmanager
    def new_file(self, path):
        with self.owned_directory(path[:-1]) as folder:
            fd = os.open(path[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                         | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=folder)
            try:
                self.owned[path] = identity(os.fstat(fd))
                os.fchmod(fd, 0o600)
                yield fd
            finally:
                os.close(fd)

    def copy(self, source_fd, records):
        for path in sorted(set(records) - {()}, key=lambda p: '/'.join(p).encode('utf-8')):
            self.tick()
            info = records[path]
            if kind(info) == 'directory':
                with self.owned_directory(path[:-1]) as folder:
                    os.mkdir(path[-1], 0o700, dir_fd=folder)
                    self.owned[path] = identity(os.stat(path[-1], dir_fd=folder, follow_symlinks=False))
                with self.owned_directory(path) as fd:
                    os.fchmod(fd, 0o700)
                continue
            digest, remaining = hashlib.sha256(), info.st_size
            with self.open_record(source_fd, path, records) as source, self.new_file(path) as target:
                while remaining:
                    self.tick()
                    data = os.read(source, min(CHUNK_BYTES, remaining))
                    if not data:
                        raise AuditFault('BACKUP_CHANGED')
                    remaining -= len(data)
                    self.write_all(target, data)
                    digest.update(data)
                if fingerprint(os.fstat(source)) != fingerprint(info):
                    raise AuditFault('BACKUP_CHANGED')
                os.fsync(target)
                if os.fstat(target).st_size != info.st_size:
                    raise AuditFault('STORED_SIZE_MISMATCH')
            self.digests[path] = (info.st_size, digest.hexdigest())

    def manifest(self, snapshot_type, exclusions):
        entries = []
        records = self.snapshot(self.stage_fd, {protocol.relative_path(e['path']) for e in exclusions})
        if set(records) != set(self.owned):
            raise AuditFault('STAGING_CHANGED')
        for path in sorted(set(records) - {()}, key=lambda p: '/'.join(p).encode('utf-8')):
            self.tick()
            info = records[path]
            mode = 0o700 if kind(info) == 'directory' else 0o600
            if identity(info) != self.owned[path] or stat.S_IMODE(info.st_mode) != mode:
                raise AuditFault('STAGING_CHANGED')
            size, digest = None, None
            if kind(info) == 'file':
                size, digest = info.st_size, self.consume(self.stage_fd, path, records)
                if (size, digest) != self.digests[path]:
                    raise AuditFault('STORED_BYTES_MISMATCH')
            entries.append(dict(path='/'.join(path), type=kind(info), size=size,
                                sha256=digest, **metadata(info)))
        value = dict(schema_version=1, snapshot_type=snapshot_type,
                     snapshot_scope='DECLARED_EXCLUSIONS' if exclusions else 'FULL_TREE',
                     root_metadata=metadata(os.fstat(self.stage_fd)), entries=entries,
                     exclusions=exclusions)
        return protocol.canonical_bytes(value)

    def sync_directories(self, parent_fd):
        for path in sorted((p for p, ident in self.owned.items() if ident[2] == stat.S_IFDIR),
                           key=len, reverse=True):
            self.tick()
            with self.owned_directory(path) as fd:
                os.fsync(fd)
        os.fsync(parent_fd)

    def check_source(self, source_fd, absolute, before, exclusions):
        after = self.source_snapshot(source_fd, exclusions)
        if {p: fingerprint(i) for p, i in before.items()} != {p: fingerprint(i) for p, i in after.items()}:
            raise AuditFault('BACKUP_CHANGED')
        with root_directory(absolute) as (fd, _):
            if fingerprint(os.fstat(fd)) != fingerprint(before[()]):
                raise AuditFault('BACKUP_CHANGED')
        self.tick()

    def check_parent(self, parent_fd, absolute):
        info = os.fstat(parent_fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise AuditFault('UNSAFE_DESTINATION_PARENT')
        with root_directory(absolute) as (fd, _):
            if identity(os.fstat(fd)) != identity(info):
                raise AuditFault('DESTINATION_PARENT_CHANGED')

    def check_stage(self, parent_fd, name):
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if identity(info) != self.owned[()] or stat.S_IMODE(info.st_mode) != 0o700:
            raise AuditFault('STAGING_CHANGED')

    def verify_stage(self, path):
        self.tick()
        result = verifier.verify(path)
        self.verification = result
        self.tick()
        if (result['verification_status'] != 'INTERNALLY_CONSISTENT'
                or not result['file_hash_match'] or not result['declared_scope_verified']):
            raise AuditFault('VERIFICATION_FAILED')
        return result

    def cleanup(self, parent_fd):
        """Unlink only recorded inodes through owned directory fds. Never rmtree."""
        self.check_stage(parent_fd, self.stage_name)
        if self.stage_fd is None:
            self.stage_fd = os.open(self.stage_name, flags(True), dir_fd=parent_fd)
        for path in sorted(set(self.owned) - {()}, key=lambda p: (len(p), p), reverse=True):
            with self.owned_directory(path[:-1]) as folder:
                info = os.stat(path[-1], dir_fd=folder, follow_symlinks=False)
                if identity(info) != self.owned[path]:
                    raise AuditFault('CLEANUP_IDENTITY_MISMATCH')
                if kind(info) == 'directory':
                    os.rmdir(path[-1], dir_fd=folder)
                else:
                    os.unlink(path[-1], dir_fd=folder)
        self.check_stage(parent_fd, self.stage_name)
        os.rmdir(self.stage_name, dir_fd=parent_fd)

    def run(self, source_fd, source_absolute, parent_fd, parent_absolute, name, snapshot_type, exclusions, report):
        self.check_parent(parent_fd, parent_absolute)
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise AuditFault('DESTINATION_EXISTS')
        publish = publication_function()
        excluded_paths = {protocol.relative_path(item['path']) for item in exclusions}
        if len(excluded_paths) != len(exclusions):
            raise AuditFault('DUPLICATE_EXCLUSION')
        if any(parent in excluded_paths for p in excluded_paths for parent in (p[:n] for n in range(1, len(p)))):
            raise AuditFault('EXCLUSION_CONFLICT')
        before = self.source_snapshot(source_fd, excluded_paths)
        self.make_stage(parent_fd)
        self.copy(source_fd, before)
        self.check_source(source_fd, source_absolute, before, excluded_paths)
        raw = self.manifest(snapshot_type, exclusions)
        if sum(size for size, _ in self.digests.values()) + len(raw) > MAX_TOTAL_BYTES:
            raise AuditFault('TOTAL_BYTE_LIMIT')
        control = (protocol.MANIFEST_NAME,)
        with self.new_file(control) as fd:
            self.write_all(fd, raw)
            os.fsync(fd)
            control_before = fingerprint(os.fstat(fd))
        self.sync_directories(parent_fd)
        self.check_parent(parent_fd, parent_absolute)
        self.check_stage(parent_fd, self.stage_name)
        report['verification'] = self.verify_stage(os.path.join(parent_absolute, self.stage_name))
        self.check_source(source_fd, source_absolute, before, excluded_paths)
        self.check_parent(parent_fd, parent_absolute)
        self.check_stage(parent_fd, self.stage_name)
        publish(parent_fd, self.stage_name, name)
        self.published = True
        report['publication_status'] = 'PUBLISHED'
        os.fsync(parent_fd)
        self.check_parent(parent_fd, parent_absolute)
        self.check_stage(parent_fd, name)
        # Rebind the emitted digest to the unchanged control inode / bytes after publish.
        if fingerprint(os.stat(protocol.MANIFEST_NAME, dir_fd=self.stage_fd, follow_symlinks=False)) != control_before:
            raise AuditFault('STAGING_CHANGED')
        report['verification'] = self.verify_stage(os.path.join(parent_absolute, name))
        self.check_parent(parent_fd, parent_absolute)
        self.check_stage(parent_fd, name)
        if fingerprint(os.stat(protocol.MANIFEST_NAME, dir_fd=self.stage_fd, follow_symlinks=False)) != control_before:
            raise AuditFault('STAGING_CHANGED')
        report['MANIFEST_SHA256'] = hashlib.sha256(raw).hexdigest()
        report['creation_status'] = 'CREATED'


def create(source, destination, snapshot_type, exclusions=()):
    report, writer = empty_report(), Writer()
    codes = {'RESTORE_NOT_PROVEN', 'TRUST_ANCHOR_NOT_ESTABLISHED'}
    try:
        if snapshot_type not in protocol.SNAPSHOT_TYPES:
            raise AuditFault('INVALID_ARGUMENTS')
        if not isinstance(exclusions, (tuple, list)) or len(exclusions) > MAX_ENTRIES:
            raise AuditFault('INVALID_EXCLUSION')
        for item in exclusions:
            if (not isinstance(item, dict) or set(item) != {'path', 'reason'}
                    or item['reason'] not in protocol.EXCLUSION_REASONS):
                raise AuditFault('INVALID_EXCLUSION')
            protocol.relative_path(item['path'])
        exclusions = sorted(exclusions, key=lambda item: item['path'].encode('utf-8'))
        parent, name = destination_parts(destination)
        with root_directory(source) as (source_fd, source_absolute), root_directory(parent) as (parent_fd, parent_absolute):
            if source_absolute == '/' or os.path.commonpath((source_absolute, parent_absolute)) == source_absolute:
                raise AuditFault('OVERLAPPING_PATHS')
            try:
                writer.run(source_fd, source_absolute, parent_fd, parent_absolute, name, snapshot_type, exclusions, report)
            finally:
                if writer.stage_name and report['creation_status'] != 'CREATED':
                    # A syscall may have published before an interruption / reported error.
                    try:
                        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                        writer.published = writer.published or identity(info) == writer.owned.get(())
                    except FileNotFoundError:
                        pass
                    except OSError:
                        report['publication_status'] = 'UNCERTAIN'
                    if writer.published or report['publication_status'] == 'UNCERTAIN':
                        report['publication_status'] = 'PUBLISHED' if writer.published else 'UNCERTAIN'
                        report['retained_destination'] = True
                        report['cleanup_status'] = ('NOT_ATTEMPTED_PUBLISHED' if writer.published
                                                    else 'NOT_ATTEMPTED_UNCERTAIN')
                        if not writer.published:
                            report['residual_staging_name'] = writer.stage_name
                        codes.add('PUBLISHED_RESULT_NOT_CONFIRMED')
                    else:
                        try:
                            writer.cleanup(parent_fd)
                            report['cleanup_status'] = 'CLEANED'
                        except (Exception, KeyboardInterrupt):
                            report['cleanup_status'] = 'FAILED'
                            report['residual_staging_name'] = writer.stage_name
                            codes.add('CLEANUP_FAILED')
    except (AuditFault, protocol.ManifestError) as error:
        codes.add(error.code)
    except OSError as error:
        codes.add(io_fault(error).code)
    except KeyboardInterrupt:
        codes.add('CREATION_INTERRUPTED')
    except Exception:
        codes.add('CREATION_FAILED')
    finally:
        if writer.verification is not None:
            report['verification'] = writer.verification
        if writer.stage_fd is not None:
            try:
                os.close(writer.stage_fd)
            except OSError:
                codes.add('HANDLE_CLOSE_FAILED')
    if (report['creation_status'] == 'CREATED'
            and codes - {'RESTORE_NOT_PROVEN', 'TRUST_ANCHOR_NOT_ESTABLISHED'}):
        report['creation_status'] = 'FAILED'
        report['MANIFEST_SHA256'] = None
        report['retained_destination'] = True
        report['cleanup_status'] = 'NOT_ATTEMPTED_PUBLISHED'
        codes.add('PUBLISHED_RESULT_NOT_CONFIRMED')
    report['validation_codes'] = sorted(codes)
    return report


def render(report, as_json=False):
    if as_json:
        return json.dumps(report, sort_keys=True, ensure_ascii=True)
    return '\n'.join(f'{key}: {json.dumps(value, sort_keys=True, ensure_ascii=True)}' for key, value in report.items())


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    parser = SafeParser(prog='backup_create.py', description='Create a new offline snapshot; restore_proven=false.')
    parser.add_argument('--source', required=True, help='Explicit quiet offline source; never a live installation.')
    parser.add_argument('--destination', required=True, help='Nonexistent target in an owned physical 0700 parent.')
    parser.add_argument('--snapshot-type', required=True, choices=protocol.SNAPSHOT_TYPES)
    parser.add_argument('--exclude', nargs=2, action='append', metavar=('PATH', 'REASON'), default=[],
                        help='Explicit directory exclusion; payload is omitted, empty root retained.')
    parser.add_argument('--json', action='store_true')
    try:
        args = parser.parse_args(arguments)
    except AuditFault:
        report = empty_report()
        report['validation_codes'] = ['INVALID_ARGUMENTS', 'RESTORE_NOT_PROVEN']
        print(render(report, '--json' in arguments))
        return 64
    report = create(args.source, args.destination, args.snapshot_type,
                    [dict(path=path, reason=reason) for path, reason in args.exclude])
    print(render(report, args.json))
    return 0 if report['creation_status'] == 'CREATED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
