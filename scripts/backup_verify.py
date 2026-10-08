#!/usr/bin/env python3
"""Offline Manifest v1 verifier. No writer, restore, network or runtime imports."""
import sys

if __name__ == '__main__':
    sys.dont_write_bytecode = True  # Local protocol imports must not create pycache.

from contextlib import contextmanager
import hashlib
import hmac
import json
import os
import stat
import time

if __package__:
    from . import backup_manifest as protocol
    from .backup_audit import AuditFault, SafeParser, fingerprint, flags, io_fault, kind, root_directory
else:
    import backup_manifest as protocol
    from backup_audit import AuditFault, SafeParser, fingerprint, flags, io_fault, kind, root_directory


MAX_ENTRIES = protocol.MAX_ENTRIES
MAX_DEPTH = protocol.MAX_DEPTH
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_SECONDS = 10
CHUNK_BYTES = 64 * 1024


class Verifier:
    def __init__(self):
        self.started = time.monotonic()
        self.total_bytes = 0

    def tick(self):
        if time.monotonic() - self.started > MAX_SECONDS:
            raise AuditFault('TIME_LIMIT')

    @contextmanager
    def open_record(self, root_fd, path, records):
        fd = os.dup(root_fd)
        try:
            for n, name in enumerate(path):
                self.tick()
                expected = records[path[:n + 1]]
                if fingerprint(os.stat(name, dir_fd=fd, follow_symlinks=False)) != fingerprint(expected):
                    raise AuditFault('BACKUP_CHANGED')
                child = os.open(name, flags(n < len(path) - 1), dir_fd=fd)
                os.close(fd)
                fd = child
                if fingerprint(os.fstat(fd)) != fingerprint(expected):
                    raise AuditFault('BACKUP_CHANGED')
            yield fd
        finally:
            os.close(fd)

    def consume(self, root_fd, path, records, collect=False):
        self.tick()
        info = records[path]
        if kind(info) != 'file' or info.st_nlink != 1:
            raise AuditFault('UNSAFE_FILE')
        maximum = protocol.MAX_MANIFEST_BYTES if collect else MAX_FILE_BYTES
        if info.st_size > maximum:
            raise AuditFault('MANIFEST_SIZE_LIMIT' if collect else 'FILE_BYTE_LIMIT')
        if self.total_bytes + info.st_size > MAX_TOTAL_BYTES:
            raise AuditFault('TOTAL_BYTE_LIMIT')
        digest, pieces, remaining = hashlib.sha256(), [], info.st_size
        with self.open_record(root_fd, path, records) as fd:
            while remaining:
                self.tick()
                piece = os.read(fd, min(CHUNK_BYTES, remaining))
                if not piece:
                    raise AuditFault('BACKUP_CHANGED')
                remaining -= len(piece)
                self.total_bytes += len(piece)
                digest.update(piece)
                if collect:
                    pieces.append(piece)
            self.tick()
            if fingerprint(os.fstat(fd)) != fingerprint(info):
                raise AuditFault('BACKUP_CHANGED')
        return b''.join(pieces) if collect else digest.hexdigest()

    def snapshot(self, root_fd, exclusions):
        records = {(): os.fstat(root_fd)}
        seen = 1
        def names(fd):
            nonlocal seen
            result = []
            with os.scandir(fd) as scan:
                for entry in scan:
                    self.tick()
                    seen += 1
                    if seen > MAX_ENTRIES:
                        raise AuditFault('ENTRY_LIMIT')
                    result.append(entry.name)
            return sorted(result, key=os.fsencode)
        def walk(fd, prefix):
            self.tick()
            for name in names(fd):
                self.tick()
                path = prefix + (name,)
                if len(path) > MAX_DEPTH:
                    raise AuditFault('DEPTH_LIMIT')
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                records[path] = info
                object_kind = kind(info)
                if object_kind == 'unsafe' or object_kind == 'file' and info.st_nlink != 1:
                    raise AuditFault('UNSAFE_OBJECT')
                if info.st_dev != records[()].st_dev:
                    raise AuditFault('FILESYSTEM_BOUNDARY')
                if object_kind == 'directory' and path not in exclusions:
                    child = os.open(name, flags(True), dir_fd=fd)
                    try:
                        if fingerprint(info) != fingerprint(os.fstat(child)):
                            raise AuditFault('BACKUP_CHANGED')
                        walk(child, path)
                    finally:
                        os.close(child)
        walk(root_fd, ())
        return records


def check_metadata(info, expected):
    if (stat.S_IMODE(info.st_mode) != int(expected['mode'], 8)
            or info.st_uid != expected['uid'] or info.st_gid != expected['gid']):
        raise AuditFault('PERMISSION_METADATA_MISMATCH')


def empty_report():
    return dict(verification_status='NOT_VERIFIED', file_hash_match=False,
                manifest_digest_match=None, trust_anchor_verified=False,
                declared_scope_verified=False, full_file_coverage=False,
                restore_proven=False, validation_codes=[])


def verify(path, trusted_manifest_sha256=None):
    report, verifier = empty_report(), Verifier()
    codes = set()
    try:
        if trusted_manifest_sha256 is not None:
            report['manifest_digest_match'] = False
            if not protocol.valid_digest(trusted_manifest_sha256):
                raise AuditFault('INVALID_TRUST_ANCHOR')
        with root_directory(path) as (root_fd, absolute):
            verifier.tick()
            root_before = os.fstat(root_fd)
            control_path = (protocol.MANIFEST_NAME,)
            try:
                control = os.stat(protocol.MANIFEST_NAME, dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                raise AuditFault('MANIFEST_MISSING') from None
            raw = verifier.consume(root_fd, control_path, {control_path: control}, collect=True)
            manifest = protocol.load_manifest(raw)
            verifier.tick()
            codes.update(('MANIFEST_V1_VALID', 'CANONICAL_SERIALIZATION_MATCH'))
            if trusted_manifest_sha256 is None:
                codes.add('TRUST_ANCHOR_NOT_PROVIDED')
            else:
                if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), trusted_manifest_sha256):
                    raise AuditFault('MANIFEST_DIGEST_MISMATCH')
                report['manifest_digest_match'] = report['trust_anchor_verified'] = True
                codes.update(('MANIFEST_DIGEST_MATCH', 'TRUST_ANCHOR_VERIFIED'))
            exclusions = {protocol.relative_path(item['path']) for item in manifest['exclusions']}
            before = verifier.snapshot(root_fd, exclusions)
            if fingerprint(before[control_path]) != fingerprint(control) or fingerprint(before[()]) != fingerprint(root_before):
                raise AuditFault('BACKUP_CHANGED')
            expected = {protocol.relative_path(item['path']): item for item in manifest['entries']}
            actual = set(before) - {(), control_path}
            if set(expected) - actual:
                raise AuditFault('LISTED_ENTRY_MISSING')
            if actual - set(expected):
                raise AuditFault('UNLISTED_ENTRY')
            check_metadata(before[()], manifest['root_metadata'])
            for item_path, entry in expected.items():
                verifier.tick()
                info = before[item_path]
                if kind(info) != entry['type']:
                    raise AuditFault('FILE_TYPE_MISMATCH')
                check_metadata(info, entry)
                if entry['type'] == 'file':
                    if info.st_size != entry['size']:
                        raise AuditFault('FILE_SIZE_MISMATCH')
                    digest = verifier.consume(root_fd, item_path, before)
                    if not hmac.compare_digest(digest, entry['sha256']):
                        raise AuditFault('FILE_DIGEST_MISMATCH')
            after = verifier.snapshot(root_fd, exclusions)
            if {p: fingerprint(info) for p, info in before.items()} != {p: fingerprint(info) for p, info in after.items()}:
                raise AuditFault('BACKUP_CHANGED')
            with root_directory(absolute) as (final_fd, _):
                if fingerprint(root_before) != fingerprint(os.fstat(final_fd)):
                    raise AuditFault('BACKUP_CHANGED')
            verifier.tick()
            report['file_hash_match'] = report['declared_scope_verified'] = True
            report['full_file_coverage'] = not exclusions
            codes.update(('FILE_HASH_MATCH', 'PERMISSION_METADATA_MATCH', 'DECLARED_SCOPE_VERIFIED'))
            codes.add('EXCLUDED_CONTENT_NOT_VERIFIED' if exclusions else 'FULL_FILE_COVERAGE')
            report['verification_status'] = ('TRUSTED_SCOPE_VERIFIED' if report['trust_anchor_verified'] else 'INTERNALLY_CONSISTENT')
    except protocol.ManifestError as error:
        codes.add(error.code)
    except AuditFault as error:
        codes.add(error.code)
    except OSError as error:
        codes.add(io_fault(error).code)
    except (ValueError, TypeError, RecursionError, MemoryError):
        codes.add('INSPECTION_FAILED')
    if report['verification_status'] == 'NOT_VERIFIED':
        codes.add('NOT_VERIFIED')
    codes.add('RESTORE_NOT_PROVEN')
    report['validation_codes'] = sorted(codes)
    return report


def render(report, as_json=False):
    if as_json:
        return json.dumps(report, sort_keys=True, ensure_ascii=True)
    return '\n'.join(f'{key}: ' + (', '.join(value) if isinstance(value, list) else json.dumps(value))
                     for key, value in report.items())


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    parser = SafeParser(prog='backup_verify.py', description='Offline declared-scope verification; restore_proven=false.')
    parser.add_argument('--path', required=True, help='Local Manifest v1 fixture directory; no symlink ancestors.')
    parser.add_argument('--trusted-manifest-sha256', help='Independently protected expected canonical manifest SHA-256.')
    parser.add_argument('--json', action='store_true')
    try:
        args = parser.parse_args(arguments)
    except AuditFault:
        report = empty_report()
        report['validation_codes'] = ['INVALID_ARGUMENTS', 'NOT_VERIFIED', 'RESTORE_NOT_PROVEN']
        print(render(report, '--json' in arguments))
        return 64
    report = verify(args.path, args.trusted_manifest_sha256)
    print(render(report, args.json))
    return 1 if report['verification_status'] == 'NOT_VERIFIED' else 0


if __name__ == '__main__':
    raise SystemExit(main())
