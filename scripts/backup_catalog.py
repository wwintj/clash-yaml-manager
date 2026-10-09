#!/usr/bin/env python3
"""Independent bounded offline trust catalog. No runtime, network or restore."""
import sys

if __name__ == '__main__':
    sys.dont_write_bytecode = True

from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import fcntl
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
    from .backup_audit import parse_json, installation_valid
else:
    import backup_create as writer
    import backup_verify as verifier
    import backup_manifest as protocol
    from backup_audit import AuditFault, SafeParser, fingerprint, flags, io_fault, kind, root_directory
    from backup_audit import parse_json, installation_valid

MAX_RECORDS = 128
MAX_RECORD_BYTES = 16 * 1024
MAX_STAGING = 8
MAX_ENTRIES = MAX_RECORDS + MAX_STAGING
MAX_READ_BYTES = 16 * 1024 * 1024  # Catalog/metadata reads; Verifier keeps its own bounds.
MAX_SECONDS = 30  # Includes up to three unchanged full Verifier calls.
MAX_LOCATION_BYTES = 1024
MAX_LOCATION_PARTS = 32
PROFILES = ('manifest-v1-declared-scope', 'updater-sidecar-v1')
ID = re.compile(r'[0-9a-f]{32}\Z')
RECORD_NAME = re.compile(r'([0-9a-f]{32})\.json\Z')
STAGE_NAME = re.compile(r'\.catalog-stage-[0-9a-f]{32}\.tmp\Z')
STAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z')


def require(value, code):
    if not value:
        raise AuditFault(code)


def identifier(value):
    return isinstance(value, str) and ID.fullmatch(value) is not None


def safe_identity(value):
    if value is None:
        return True
    return (isinstance(value, dict) and installation_valid(value, None)
            and all(v is None or isinstance(v, str) and len(v) <= 128 for v in value.values()))


def binding(info, absolute):
    encoded = absolute.encode('utf-8')
    require(len(encoded) <= MAX_LOCATION_BYTES and len(absolute.split('/')) <= MAX_LOCATION_PARTS, 'LOCATION_LIMIT')
    # Private record never stores an arbitrary path, filename, URL or source bytes.
    for part in absolute.split('/'):
        if part:
            protocol.relative_path(part)
    return dict(path_sha256=hashlib.sha256(encoded).hexdigest(), device=info.st_dev,
                inode=info.st_ino, **writer.metadata(info))


def valid_binding(value):
    if not isinstance(value, dict) or set(value) != {'path_sha256', 'device', 'inode', 'mode', 'uid', 'gid'}:
        return False
    return (protocol.valid_digest(value['path_sha256'])
            and all(protocol.uint(value[k], 2**64 - 1) for k in ('device', 'inode'))
            and value['mode'] == '0700'
            and all(protocol.uint(value[k], 2**32 - 2) for k in ('uid', 'gid')))


def validate_record(value):
    require(isinstance(value, dict) and set(value) == {'schema_version', 'snapshot_id', 'operation_id',
        'manifest_sha256', 'snapshot_binding', 'catalog_binding', 'representation_binding',
        'enrolled_at', 'snapshot_claims', 'operator_claims', 'verified_facts', 'restore_proven'}, 'INVALID_RECORD_SCHEMA')
    require(type(value['schema_version']) is int and value['schema_version'] == 1, 'UNSUPPORTED_RECORD_SCHEMA')
    require(identifier(value['snapshot_id']) and identifier(value['operation_id']), 'INVALID_RECORD_ID')
    require(protocol.valid_digest(value['manifest_sha256']), 'INVALID_RECORD_DIGEST')
    require(all(valid_binding(value[k]) for k in ('snapshot_binding', 'catalog_binding', 'representation_binding')), 'INVALID_RECORD_BINDING')
    bindings = [value[k] for k in ('snapshot_binding', 'catalog_binding', 'representation_binding')]
    require(len({b['path_sha256'] for b in bindings}) == 3
            and len({(b['device'], b['inode']) for b in bindings}) == 3, 'INVALID_RECORD_BINDING')
    stamp = value['enrolled_at']
    require(isinstance(stamp, str) and STAMP.fullmatch(stamp) is not None, 'INVALID_RECORD_TIMESTAMP')
    datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%S.%fZ')
    claims, operator, facts = value['snapshot_claims'], value['operator_claims'], value['verified_facts']
    require(isinstance(claims, dict) and set(claims) == {'snapshot_type', 'snapshot_scope', 'installed_identity'}, 'INVALID_RECORD_CLAIMS')
    require(claims['snapshot_type'] in protocol.SNAPSHOT_TYPES and claims['snapshot_scope'] in protocol.SCOPES
            and safe_identity(claims['installed_identity']), 'INVALID_RECORD_CLAIMS')
    require(isinstance(operator, dict) and set(operator) == {'completed_offline_snapshot', 'independent_digest_handoff', 'scope', 'original_identity', 'target_identity'}, 'INVALID_OPERATOR_CLAIMS')
    scope = operator['scope']
    require(operator['completed_offline_snapshot'] is True and operator['independent_digest_handoff'] is True and isinstance(scope, dict)
            and set(scope) == {'profile', 'version'} and scope['profile'] in PROFILES
            and type(scope['version']) is int and scope['version'] == 1
            and safe_identity(operator['original_identity']) and safe_identity(operator['target_identity']), 'INVALID_OPERATOR_CLAIMS')
    require(facts == dict(manifest_schema_version=1, expected_digest_origin='OPERATOR_ARGUMENT',
            manifest_digest_matched=True, declared_scope_verified=True, snapshot_provenance_authenticated=False)
            and type(facts.get('manifest_schema_version')) is int
            and facts.get('manifest_digest_matched') is True and facts.get('declared_scope_verified') is True
            and facts.get('snapshot_provenance_authenticated') is False, 'INVALID_VERIFIED_FACTS')
    require(value['restore_proven'] is False, 'INVALID_RESTORE_CLAIM')
    return value


def canonical_record(value):
    validate_record(value)
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('ascii')
    require(len(raw) <= MAX_RECORD_BYTES, 'RECORD_SIZE_LIMIT')
    return raw


def load_record(raw):
    require(len(raw) <= MAX_RECORD_BYTES, 'RECORD_SIZE_LIMIT')
    value = parse_json(raw)
    require(raw == canonical_record(value), 'NON_CANONICAL_RECORD')
    return value


def disjoint(left, right):
    require(os.path.commonpath((left, right)) not in (left, right), 'CATALOG_NOT_INDEPENDENT')


def private_root(info):
    require(kind(info) == 'directory' and info.st_uid == os.geteuid() and info.st_gid == os.getegid()
            and stat.S_IMODE(info.st_mode) == 0o700, 'UNSAFE_PRIVATE_ROOT')


def report_empty(action):
    public_action = action if action in ('register', 'verify', 'inspect') else 'INVALID_ACTION'
    return dict(action=public_action, registration_status='NOT_REGISTERED' if action == 'register' else 'NOT_RUN',
        inspection_status='NOT_INSPECTED' if action == 'inspect' else 'NOT_RUN',
        verification_status='NOT_VERIFIED' if action == 'verify' else 'NOT_RUN', record_found=False, catalog_record_valid=False,
        snapshot_identity_match=False, manifest_digest_match=False, declared_scope_verified=False,
        trusted_scope_verified=False, restore_proven=False, snapshot_id=None,
        protection_model='ROOT_PRIVATE' if os.geteuid() == os.getegid() == 0 else 'LOCAL_UID_FIXTURE',
        publication_status='NOT_PUBLISHED', cleanup_status='NOT_NEEDED', retained_record=False,
        residual_staging_name=None, counts=dict(records=0, staging_residue=0), metadata=None, validation_codes=[])


class Catalog:
    def __init__(self):
        self.started = time.monotonic()
        self.read_bytes = 0
        self.stage_name = self.stage_identity = self.stage_fd = None
        self.published = False
        self.last_verification = None

    def tick(self):
        require(time.monotonic() - self.started <= MAX_SECONDS, 'TIME_LIMIT')

    def read(self, fd, name, limit):
        self.tick()
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        require(kind(info) == 'file' and info.st_nlink == 1, 'UNSAFE_FILE')
        require(info.st_dev == os.fstat(fd).st_dev, 'FILESYSTEM_BOUNDARY')
        require(info.st_size <= limit, 'RECORD_SIZE_LIMIT' if limit == MAX_RECORD_BYTES else 'METADATA_SIZE_LIMIT')
        require(self.read_bytes + info.st_size <= MAX_READ_BYTES, 'TOTAL_READ_LIMIT')
        parts, remaining = [], info.st_size
        child = os.open(name, flags(), dir_fd=fd)
        try:
            require(fingerprint(os.fstat(child)) == fingerprint(info), 'OBJECT_CHANGED')
            while remaining:
                self.tick()
                piece = os.read(child, min(65536, remaining))
                require(bool(piece), 'OBJECT_CHANGED')
                self.read_bytes += len(piece)
                parts.append(piece)
                remaining -= len(piece)
            require(fingerprint(os.fstat(child)) == fingerprint(info), 'OBJECT_CHANGED')
            require(fingerprint(os.stat(name, dir_fd=fd, follow_symlinks=False)) == fingerprint(info), 'OBJECT_CHANGED')
        finally:
            os.close(child)
        self.tick()
        return b''.join(parts), info

    def root_check(self, fd, absolute):
        private_root(os.fstat(fd))
        with root_directory(absolute) as (current, _):
            require(writer.identity(os.fstat(current)) == writer.identity(os.fstat(fd)), 'CATALOG_ROOT_CHANGED')

    def inventory(self, fd, absolute):
        self.root_check(fd, absolute)
        before = fingerprint(os.fstat(fd))
        names = []
        with os.scandir(fd) as scan:
            for entry in scan:
                self.tick()
                require(len(names) < MAX_ENTRIES, 'CATALOG_ENTRY_LIMIT')
                names.append(entry.name)
        records, residues, signatures = {}, [], {}
        for name in sorted(names, key=os.fsencode):
            self.tick()
            is_record, is_stage = RECORD_NAME.fullmatch(name), STAGE_NAME.fullmatch(name)
            require(is_record is not None or is_stage is not None, 'UNEXPECTED_CATALOG_OBJECT')
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            require(kind(info) == 'file' and info.st_nlink == 1, 'UNSAFE_CATALOG_OBJECT')
            require(info.st_dev == os.fstat(fd).st_dev, 'FILESYSTEM_BOUNDARY')
            require(info.st_uid == os.geteuid() and info.st_gid == os.getegid()
                    and stat.S_IMODE(info.st_mode) == 0o600, 'UNSAFE_CATALOG_OWNERSHIP_OR_PERMISSION')
            require(info.st_size <= MAX_RECORD_BYTES, 'RECORD_SIZE_LIMIT')
            signatures[name] = fingerprint(info)
            if is_stage:
                residues.append(name)
                require(len(residues) <= MAX_STAGING, 'STAGING_CAPACITY_LIMIT')
                continue  # Diagnose residue, never infer publication from its bytes.
            require(len(records) < MAX_RECORDS, 'CATALOG_CAPACITY_LIMIT')
            raw, read_info = self.read(fd, name, MAX_RECORD_BYTES)
            require(fingerprint(read_info) == fingerprint(info), 'CATALOG_CHANGED')
            value = load_record(raw)
            require(value['snapshot_id'] == is_record[1], 'RECORD_FILENAME_MISMATCH')
            require(value['catalog_binding'] == binding(os.fstat(fd), absolute), 'CATALOG_BINDING_MISMATCH')
            records[value['snapshot_id']] = value
        operations, locations, inodes = set(), set(), set()
        for value in records.values():
            op, snap = value['operation_id'], value['snapshot_binding']
            require(op not in operations, 'DUPLICATE_OPERATION_ID')
            require(snap['path_sha256'] not in locations and (snap['device'], snap['inode']) not in inodes, 'DUPLICATE_SNAPSHOT_ASSOCIATION')
            operations.add(op); locations.add(snap['path_sha256']); inodes.add((snap['device'], snap['inode']))
        require(fingerprint(os.fstat(fd)) == before, 'CATALOG_CHANGED')
        for name, signature in signatures.items():
            require(fingerprint(os.stat(name, dir_fd=fd, follow_symlinks=False)) == signature, 'CATALOG_CHANGED')
        self.root_check(fd, absolute)
        return records, residues, signatures

    @contextmanager
    def locked(self, path, write=False):
        with root_directory(path) as (fd, absolute):
            self.root_check(fd, absolute)
            try:
                fcntl.flock(fd, (fcntl.LOCK_EX if write else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            except BlockingIOError:
                raise AuditFault('CATALOG_BUSY') from None
            self.root_check(fd, absolute)
            yield fd, absolute
            # Closing this invocation's directory fd releases flock; no lock file.

    def snapshot(self, path, catalog_absolute):
        try:
            return self._snapshot(path, catalog_absolute)
        except FileNotFoundError:
            # Missing manifest is separately diagnosed inside _snapshot.
            raise AuditFault('MISSING_SNAPSHOT') from None

    def _snapshot(self, path, catalog_absolute):
        with root_directory(path) as (fd, absolute):
            require(not any(p.startswith(('.backup-create-', '.backup-collect-', '.catalog-stage-')) for p in absolute.split('/')), 'UNPUBLISHED_STAGING_REFUSED')
            disjoint(absolute, catalog_absolute)
            private_root(os.fstat(fd))
            try:
                raw, control = self.read(fd, protocol.MANIFEST_NAME, protocol.MAX_MANIFEST_BYTES)
            except FileNotFoundError:
                raise AuditFault('MANIFEST_MISSING') from None
            require(control.st_uid == os.geteuid() and control.st_gid == os.getegid()
                    and stat.S_IMODE(control.st_mode) == 0o600, 'UNSAFE_MANIFEST_PERMISSION')
            manifest = protocol.load_manifest(raw)
            return dict(absolute=absolute, root=fingerprint(os.fstat(fd)), control=fingerprint(control),
                        binding=binding(os.fstat(fd), absolute), manifest=manifest, raw=raw)

    def unchanged_snapshot(self, path, catalog_absolute, before):
        after = self.snapshot(path, catalog_absolute)
        require(after == before, 'SNAPSHOT_CHANGED')
        return after

    def verify_snapshot(self, path, digest, catalog_absolute, before):
        self.unchanged_snapshot(path, catalog_absolute, before)
        self.tick()
        result = verifier.verify(path, digest)  # Existing full implementation, never a substitute.
        self.last_verification = result
        self.tick()
        require(result['verification_status'] == 'TRUSTED_SCOPE_VERIFIED' and result['trust_anchor_verified'] is True
                and result['manifest_digest_match'] is True and result['declared_scope_verified'] is True
                and result['file_hash_match'] is True, 'SNAPSHOT_NOT_VERIFIED')
        self.unchanged_snapshot(path, catalog_absolute, before)
        return result

    def make_record(self, fd, absolute, snapshot, representation, snapshot_id, operation_id, profile, digest, original, target):
        installed = None
        with root_directory(snapshot['absolute']) as (snap_fd, _):
            names = {e['path']: e for e in snapshot['manifest']['entries']}
            def declared_bytes(name, limit):
                raw, info = self.read(snap_fd, name, limit)
                entry = names[name]
                require(entry['type'] == 'file' and len(raw) == entry['size']
                        and hashlib.sha256(raw).hexdigest() == entry['sha256'], 'METADATA_DIGEST_MISMATCH')
                verifier.check_metadata(info, entry)
                return raw
            if 'INSTALLATION.json' in names:
                raw = declared_bytes('INSTALLATION.json', MAX_RECORD_BYTES)
                installed = parse_json(raw)
                require(safe_identity(installed) and installed is not None, 'INVALID_INSTALLED_IDENTITY')
            if profile == 'updater-sidecar-v1':
                require('COLLECTION_SCOPE.json' in names, 'COLLECTOR_SCOPE_MISSING')
                raw = declared_bytes('COLLECTION_SCOPE.json', 256 * 1024)
                scope = parse_json(raw)
                require(isinstance(scope, dict) and type(scope.get('schema_version')) is int
                        and scope['schema_version'] == 1 and scope.get('profile') == profile
                        and scope.get('source_scope') == 'ALLOWLIST_SUBSET'
                        and scope.get('writer_full_tree_means') == 'COLLECTED_REPRESENTATION_ONLY', 'COLLECTOR_SCOPE_MISMATCH')
        return dict(schema_version=1, snapshot_id=snapshot_id, operation_id=operation_id,
            manifest_sha256=digest, snapshot_binding=snapshot['binding'], catalog_binding=binding(os.fstat(fd), absolute),
            representation_binding=representation, enrolled_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
            snapshot_claims=dict(snapshot_type=snapshot['manifest']['snapshot_type'], snapshot_scope=snapshot['manifest']['snapshot_scope'], installed_identity=installed),
            operator_claims=dict(completed_offline_snapshot=True, independent_digest_handoff=True, scope=dict(profile=profile, version=1), original_identity=original, target_identity=target),
            verified_facts=dict(manifest_schema_version=1, expected_digest_origin='OPERATOR_ARGUMENT', manifest_digest_matched=True,
                                declared_scope_verified=True, snapshot_provenance_authenticated=False), restore_proven=False)

    def write_stage(self, fd, raw):
        self.stage_name = '.catalog-stage-' + secrets.token_hex(16) + '.tmp'
        try:
            self.stage_fd = os.open(self.stage_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=fd)
        except FileExistsError:
            self.stage_name = None
            raise AuditFault('STAGING_COLLISION') from None
        self.stage_identity = writer.identity(os.fstat(self.stage_fd))
        os.fchmod(self.stage_fd, 0o600)
        view = memoryview(raw)
        while view:
            self.tick()
            count = os.write(self.stage_fd, view)
            require(count > 0, 'WRITE_FAILED')
            view = view[count:]
        os.fsync(self.stage_fd)

    def cleanup(self, fd, absolute, final_name, report, codes):
        if not self.stage_name or report['registration_status'] == 'REGISTERED':
            return
        try:
            found = os.stat(final_name, dir_fd=fd, follow_symlinks=False)
            self.published = self.published or writer.identity(found) == self.stage_identity
        except FileNotFoundError:
            pass
        except OSError:
            report['publication_status'] = 'UNCERTAIN'
        if self.published or report['publication_status'] == 'UNCERTAIN':
            report['publication_status'] = 'PUBLISHED' if self.published else 'UNCERTAIN'
            report['retained_record'] = True
            report['cleanup_status'] = 'NOT_ATTEMPTED_PUBLISHED' if self.published else 'NOT_ATTEMPTED_UNCERTAIN'
            if not self.published:
                report['residual_staging_name'] = self.stage_name
            codes.add('PUBLISHED_RESULT_NOT_CONFIRMED')
            return
        try:
            self.root_check(fd, absolute)
            info = os.stat(self.stage_name, dir_fd=fd, follow_symlinks=False)
            require(self.stage_identity is not None and writer.identity(info) == self.stage_identity, 'CLEANUP_IDENTITY_MISMATCH')
            os.unlink(self.stage_name, dir_fd=fd)
            os.fsync(fd)
            report['cleanup_status'] = 'CLEANED'
        except (Exception, KeyboardInterrupt):
            report['cleanup_status'] = 'FAILED'
            report['residual_staging_name'] = self.stage_name
            codes.add('CLEANUP_FAILED')


def metadata(value):
    return dict(snapshot_id=value['snapshot_id'], operation_id=value['operation_id'],
        snapshot_type=value['snapshot_claims']['snapshot_type'], snapshot_scope=value['snapshot_claims']['snapshot_scope'],
        scope=value['operator_claims']['scope'], enrolled_at=value['enrolled_at'], restore_proven=False)


def execute(action, catalog, snapshot=None, snapshot_id=None, operation_id=None, profile=None,
            expected_digest=None, representation=None, completed_offline=False, original_identity=None, target_identity=None):
    report, engine = report_empty(action), Catalog()
    codes = {'RESTORE_NOT_PROVEN'}
    catalog_opened = False
    failed = False
    try:
        require(action in ('register', 'verify', 'inspect'), 'INVALID_ACTION')
        if action == 'register':
            require(identifier(operation_id) and profile in PROFILES and completed_offline is True
                    and protocol.valid_digest(expected_digest) and safe_identity(original_identity) and safe_identity(target_identity), 'INVALID_ARGUMENTS')
            snapshot_id = secrets.token_hex(16)
            require(identifier(snapshot_id), 'INVALID_RECORD_ID')
        elif action == 'verify' or snapshot_id is not None:
            require(identifier(snapshot_id), 'INVALID_RECORD_ID')
        with engine.locked(catalog, action == 'register') as (fd, absolute):
            catalog_opened = True
            records, residues, signatures = engine.inventory(fd, absolute)
            report['counts'] = dict(records=len(records), staging_residue=len(residues))
            if residues:
                codes.add('STAGING_RESIDUE')
            if action == 'register':
                require(not residues, 'STAGING_RESIDUE')
                require(len(records) < MAX_RECORDS, 'CATALOG_FULL')
                require(snapshot_id not in records, 'DUPLICATE_SNAPSHOT_ID')
                require(all(r['operation_id'] != operation_id for r in records.values()), 'DUPLICATE_OPERATION_ID')
                before = engine.snapshot(snapshot, absolute)
                with root_directory(representation) as (rep_fd, rep_absolute):
                    private_root(os.fstat(rep_fd)); disjoint(absolute, rep_absolute); disjoint(before['absolute'], rep_absolute)
                    rep_binding = binding(os.fstat(rep_fd), rep_absolute)
                require(all(r['snapshot_binding']['path_sha256'] != before['binding']['path_sha256']
                            and (r['snapshot_binding']['device'], r['snapshot_binding']['inode']) != (before['binding']['device'], before['binding']['inode']) for r in records.values()), 'DUPLICATE_SNAPSHOT_ASSOCIATION')
                engine.verify_snapshot(snapshot, expected_digest, absolute, before)
                value = engine.make_record(fd, absolute, before, rep_binding, snapshot_id, operation_id, profile,
                                           expected_digest, original_identity, target_identity)
                raw = canonical_record(value)
                publish = writer.publication_function()
                final_name = snapshot_id + '.json'
                try:
                    engine.write_stage(fd, raw)
                    stored, _ = engine.read(fd, engine.stage_name, MAX_RECORD_BYTES)
                    require(stored == raw, 'STAGED_BYTES_MISMATCH')
                    engine.verify_snapshot(snapshot, expected_digest, absolute, before)
                    _, current_residues, current = engine.inventory(fd, absolute)
                    require(current_residues == [engine.stage_name] and {k:v for k,v in current.items() if k != engine.stage_name} == signatures, 'CATALOG_CHANGED')
                    require(writer.identity(os.stat(engine.stage_name, dir_fd=fd, follow_symlinks=False)) == engine.stage_identity, 'STAGING_CHANGED')
                    publish(fd, engine.stage_name, final_name)
                    engine.published = True; report['publication_status'] = 'PUBLISHED'
                    os.fsync(fd)
                    final_records, final_residues, final_signatures = engine.inventory(fd, absolute)
                    require(not final_residues and final_records.get(snapshot_id) == value
                            and writer.identity(os.stat(final_name, dir_fd=fd, follow_symlinks=False)) == engine.stage_identity
                            and {k:v for k,v in final_signatures.items() if k != final_name} == signatures, 'PUBLISHED_RECORD_CHANGED')
                    engine.verify_snapshot(snapshot, expected_digest, absolute, before)
                    again, _, after = engine.inventory(fd, absolute)
                    require(again == final_records and after == final_signatures, 'CATALOG_CHANGED')
                    report['registration_status'] = 'REGISTERED'
                    report['snapshot_id'] = snapshot_id
                    report['catalog_record_valid'] = report['record_found'] = True
                    report['snapshot_identity_match'] = True
                    report['manifest_digest_match'] = report['declared_scope_verified'] = True
                    report['counts']['records'] += 1
                    report['metadata'] = metadata(value)
                    codes.update(('REGISTERED', 'CATALOG_RECORD_VALID', 'MANIFEST_DIGEST_MATCH', 'DECLARED_SCOPE_VERIFIED'))
                finally:
                    engine.cleanup(fd, absolute, final_name, report, codes)
            elif action == 'inspect':
                if snapshot_id is not None:
                    require(snapshot_id in records, 'UNANCHORED')
                    report['record_found'] = report['catalog_record_valid'] = True
                    report['snapshot_id'] = snapshot_id
                    report['metadata'] = metadata(records[snapshot_id])
                    codes.update(('RECORD_FOUND', 'CATALOG_RECORD_VALID'))
                report['inspection_status'] = 'CATALOG_INSPECTED'
                codes.add('SNAPSHOT_EXISTENCE_NOT_CHECKED')
            else:
                require(snapshot_id in records, 'UNANCHORED')
                value = records[snapshot_id]
                report['record_found'] = report['catalog_record_valid'] = True
                codes.update(('RECORD_FOUND', 'CATALOG_RECORD_VALID'))
                before = engine.snapshot(snapshot, absolute)
                require(before['binding'] == value['snapshot_binding'], 'SNAPSHOT_IDENTITY_MISMATCH')
                report['snapshot_identity_match'] = True; codes.add('SNAPSHOT_IDENTITY_MATCH')
                result = engine.verify_snapshot(snapshot, value['manifest_sha256'], absolute, before)
                require(before['manifest']['snapshot_type'] == value['snapshot_claims']['snapshot_type']
                        and before['manifest']['snapshot_scope'] == value['snapshot_claims']['snapshot_scope'], 'SNAPSHOT_CLAIM_MISMATCH')
                _, _, after = engine.inventory(fd, absolute)
                require(after == signatures, 'CATALOG_CHANGED')
                report.update(verification_status='TRUSTED_SCOPE_VERIFIED', manifest_digest_match=result['manifest_digest_match'],
                    declared_scope_verified=result['declared_scope_verified'], trusted_scope_verified=True, snapshot_id=snapshot_id)
                codes.update(('MANIFEST_DIGEST_MATCH', 'DECLARED_SCOPE_VERIFIED', 'TRUSTED_SCOPE_VERIFIED'))
    except (AuditFault, protocol.ManifestError) as error:
        failed = True
        codes.add(error.code)
    except FileNotFoundError:
        failed = True
        codes.add('CATALOG_CHANGED' if catalog_opened else 'UNANCHORED' if action == 'verify' else 'CATALOG_MISSING')
    except OSError as error:
        failed = True
        codes.add('DISK_FULL' if error.errno == errno.ENOSPC else io_fault(error).code)
    except KeyboardInterrupt:
        failed = True
        codes.add('REGISTRATION_INTERRUPTED' if action == 'register' else 'INSPECTION_INTERRUPTED')
    except (ValueError, TypeError, UnicodeError, RecursionError, MemoryError):
        failed = True
        codes.add('INVALID_RECORD_CONTENT')
    except Exception:
        failed = True
        codes.add('CATALOG_OPERATION_FAILED')
    finally:
        if engine.stage_fd is not None:
            try:
                os.close(engine.stage_fd)
            except OSError:
                failed = True
                codes.add('HANDLE_CLOSE_FAILED')
    if failed and report['registration_status'] == 'REGISTERED':
        report['registration_status'] = 'NOT_REGISTERED'
        codes.discard('REGISTERED')
        report['retained_record'] = True
        report['cleanup_status'] = 'NOT_ATTEMPTED_PUBLISHED'
        codes.add('PUBLISHED_RESULT_NOT_CONFIRMED')
    if failed and action == 'verify':
        report['verification_status'] = 'NOT_VERIFIED'
        report['trusted_scope_verified'] = False
        codes.discard('TRUSTED_SCOPE_VERIFIED')
    if failed and action == 'inspect':
        report['inspection_status'] = 'NOT_INSPECTED'
    if action == 'verify' and report['verification_status'] != 'TRUSTED_SCOPE_VERIFIED':
        codes.add('NOT_VERIFIED')
        if engine.last_verification is not None:
            codes.update(engine.last_verification['validation_codes'])
            report['manifest_digest_match'] = engine.last_verification['manifest_digest_match'] is True
            report['declared_scope_verified'] = engine.last_verification['declared_scope_verified'] is True
    report['validation_codes'] = sorted(codes)
    return report


def identity_argument(raw):
    if raw is None:
        return None
    require(isinstance(raw, str) and len(raw.encode('utf-8')) <= MAX_RECORD_BYTES, 'INVALID_ARGUMENTS')
    value = parse_json(raw)
    require(value is not None and safe_identity(value), 'INVALID_ARGUMENTS')
    return value


def main(argv=None):
    parser = SafeParser(prog='backup_catalog.py', description='Protected offline catalog; restore_proven=false.', allow_abbrev=False)
    parser.add_argument('action', choices=('register', 'verify', 'inspect'))
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--snapshot')
    parser.add_argument('--snapshot-id')
    parser.add_argument('--operation-id')
    parser.add_argument('--scope-profile', choices=PROFILES)
    parser.add_argument('--expected-manifest-sha256')
    parser.add_argument('--representation')
    parser.add_argument('--completed-offline-snapshot', action='store_true')
    parser.add_argument('--original-identity')
    parser.add_argument('--target-identity')
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
        common = dict(action=args.action, catalog=args.catalog)
        if args.action == 'register':
            require(args.snapshot is not None and args.representation is not None and args.snapshot_id is None, 'INVALID_ARGUMENTS')
            common.update(snapshot=args.snapshot, representation=args.representation, operation_id=args.operation_id,
                profile=args.scope_profile, expected_digest=args.expected_manifest_sha256, completed_offline=args.completed_offline_snapshot,
                original_identity=identity_argument(args.original_identity), target_identity=identity_argument(args.target_identity))
        else:
            require(not any((args.operation_id, args.scope_profile, args.expected_manifest_sha256, args.representation,
                             args.completed_offline_snapshot, args.original_identity, args.target_identity)), 'INVALID_ARGUMENTS')
            require(args.action == 'inspect' and args.snapshot is None or args.action == 'verify' and args.snapshot is not None and args.snapshot_id is not None, 'INVALID_ARGUMENTS')
            common.update(snapshot=args.snapshot, snapshot_id=args.snapshot_id)
        result = execute(**common)
    except (AuditFault, ValueError, TypeError, RecursionError):
        result = report_empty('INVALID_ARGUMENTS'); result['validation_codes'] = ['INVALID_ARGUMENTS', 'RESTORE_NOT_PROVEN']
        print(json.dumps(result, sort_keys=True)); return 64
    print(json.dumps(result, sort_keys=True))
    return 0 if result['registration_status'] == 'REGISTERED' or result['inspection_status'] == 'CATALOG_INSPECTED' or result['verification_status'] == 'TRUSTED_SCOPE_VERIFIED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
