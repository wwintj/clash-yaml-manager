#!/usr/bin/env python3
"""Independent offline package writer and read-only basic verifier.

CLI: python3 -m scripts.recovery_package create --source /private/offline-fixture
     python3 -m scripts.recovery_package verify --operation-id <32 hex>
Fixed root-only management policy. No updater, restore, prune or environment overrides.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
import secrets
import stat

from scripts.backup_audit import AuditFault, flags
from scripts.backup_create import publication_function
from scripts import recovery_manifest as schema, recovery_io as io

RECORD_KEYS = {'record_version', 'profile', 'operation_id', 'manifest_sha256',
               'package_device', 'package_inode', 'source_identity', 'target_identity',
               'installation_binding', 'trust_scope'}
TRUST_SCOPE = 'SAME_HOST_ROOT_PRIVATE_DIGEST_HANDOFF_NOT_SIGNED_NOT_OFF_HOST'


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def report():
    return dict(PACKAGE_CREATED=False, PACKAGE_VERIFIED=False, TRUST_ANCHOR_VERIFIED=False,
                STRUCTURAL_VALID=False, CONTENT_INTEGRITY_VALID=False,
                RECOVERY_REQUIREMENTS_NOT_EVALUATED=True, RESTORE_PROVEN=False,
                operation_id=None, manifest_sha256=None, publication='NOT_STARTED',
                cleanup='NOT_CREATED', code=None)


def error_code(error):
    if isinstance(error, AuditFault):
        return error.code
    return {errno.ENOSPC: 'DISK_FULL', errno.EIO: 'IO_FAILED', errno.EEXIST: 'DESTINATION_EXISTS',
            errno.EACCES: 'PERMISSION_DENIED', errno.EPERM: 'PERMISSION_DENIED',
            errno.ENOENT: 'PATH_MISSING', errno.ELOOP: 'UNSAFE_PATH', errno.ENOTDIR: 'UNSAFE_PATH'}.get(error.errno, 'IO_FAILED')


@contextmanager
def managed(create=False):
    schema.require(os.geteuid() == io.ROOT_UID and os.getegid() == io.ROOT_GID, 'ROOT_REQUIRED')
    parent, name = os.path.split(io.MANAGED_ROOT)
    with io.absolute_directory(parent) as parent_fd:
        if create:
            try:
                os.mkdir(name, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
        with io.child_directory(parent_fd, name, stored=True) as root:
            schema.require(set(os.listdir(root)) <= {'packages', 'records'}, 'UNEXPECTED_MANAGED_OBJECT')
            if create:
                for child in ('packages', 'records'):
                    try:
                        os.mkdir(child, 0o700, dir_fd=root)
                    except FileExistsError:
                        pass
                os.fsync(root); os.fsync(parent_fd)
            with io.child_directory(root, 'packages', stored=True) as packages:
                with io.child_directory(root, 'records', stored=True) as records:
                    schema.require(os.fstat(packages).st_dev == os.fstat(records).st_dev == os.fstat(root).st_dev, 'CROSS_FILESYSTEM')
                    yield packages, records


def verify_fd(package, budget, trusted_digest):
    """Digest is handed in independently; NEVER derive an anchor from this package."""
    io.private(os.fstat(package), True)
    directory_before = os.fstat(package)
    schema.require(set(os.listdir(package)) == {'manifest.json', 'blobs'}, 'PAYLOAD_CLOSURE')
    raw, _, digest = io.stream(package, 'manifest.json', budget, stored=True, limit=schema.MAX_JSON_BYTES)
    manifest = schema.validate(schema.parse(raw))
    schema.digest(trusted_digest)
    schema.require(digest == trusted_digest, 'MANIFEST_DIGEST_MISMATCH')
    with io.child_directory(package, 'blobs', stored=True) as blobs:
        before = os.fstat(blobs)
        expected = {e['blob'] for e in manifest['entries'] if e['kind'] == 'file'}
        schema.require(set(os.listdir(blobs)) == expected, 'PAYLOAD_CLOSURE')
        for entry in manifest['entries']:
            budget.tick()
            if entry['kind'] != 'file':
                continue
            _, size, actual = io.stream(blobs, entry['blob'], budget, stored=True)
            schema.require(size == entry['size'] and actual == entry['sha256'], 'CONTENT_DIGEST_MISMATCH')
        io.same(before, os.fstat(blobs))
    again, _, _ = io.stream(package, 'manifest.json', budget, stored=True, limit=schema.MAX_JSON_BYTES)
    schema.require(again == raw, 'OBJECT_CHANGED')
    io.same(directory_before, os.fstat(package))
    return manifest


def validate_record(record):
    schema.keys(record, RECORD_KEYS)
    schema.require(type(record['record_version']) is int and record['record_version'] == 1)
    schema.require(record['profile'] == schema.PROFILE and record['trust_scope'] == TRUST_SCOPE)
    schema.operation(record['operation_id']); schema.digest(record['manifest_sha256'])
    schema.integer(record['package_device']); schema.integer(record['package_inode'])
    schema.identity(record['source_identity']); schema.identity(record['target_identity'])
    schema.keys(record['installation_binding'], ('origin', 'install_path', 'system_id'))
    return record


def bind(record, manifest, info):
    for key in ('operation_id', 'source_identity', 'target_identity', 'installation_binding'):
        schema.require(record[key] == manifest[key], 'RECORD_BINDING_MISMATCH')
    schema.require((record['package_device'], record['package_inode']) == (info.st_dev, info.st_ino), 'RECORD_BINDING_MISMATCH')


def verify(operation_id, _budget=None):
    result = report()
    try:
        schema.operation(operation_id)
        result['operation_id'] = operation_id
        budget = _budget if _budget is not None else io.Budget()
        with managed() as (packages, records):
            raw, _, _ = io.stream(records, operation_id+'.json', budget, stored=True, limit=32*1024)
            record = validate_record(schema.parse(raw))
            schema.require(record['operation_id'] == operation_id, 'RECORD_BINDING_MISMATCH')
            with io.child_directory(packages, operation_id, stored=True) as package:
                manifest = verify_fd(package, budget, record['manifest_sha256'])
                check_installation(package, manifest, budget)
                bind(record, manifest, os.fstat(package))
            again, _, _ = io.stream(records, operation_id+'.json', budget, stored=True, limit=32*1024)
            schema.require(again == raw, 'OBJECT_CHANGED')
        result.update(STRUCTURAL_VALID=True, CONTENT_INTEGRITY_VALID=True,
                      PACKAGE_VERIFIED=True, TRUST_ANCHOR_VERIFIED=True,
                      manifest_sha256=record['manifest_sha256'], code='VERIFIED')
    except (AuditFault, OSError) as error:
        result['code'] = error_code(error)
    return result


def check_installation(package, manifest, budget):
    files = {e['path']: e for e in manifest['entries']}
    with io.child_directory(package, 'blobs', stored=True) as blobs:
        version_raw, _, _ = io.stream(blobs, files['application/VERSION']['blob'], budget, stored=True, limit=128)
        schema.require(version_raw.decode('ascii', errors='replace').strip() == manifest['source_identity']['version'], 'SOURCE_IDENTITY_MISMATCH')
        raw, _, _ = io.stream(blobs, files['application/INSTALLATION.json']['blob'], budget, stored=True, limit=16*1024)
        installation = schema.parse(raw, canonical_required=False)
        schema.keys(installation, ('channel', 'base_version', 'commit', 'tag', 'installed_at', 'source'))
        for field, key in (('version', 'base_version'), ('channel', 'channel'), ('commit', 'commit'), ('tag', 'tag')):
            schema.require(installation[key] == manifest['source_identity'][field], 'SOURCE_IDENTITY_MISMATCH')
        schema.timestamp(installation['installed_at'])
        schema.require(installation['source'] == ('github-release' if installation['channel'] == 'stable' else 'github-main'), 'SOURCE_IDENTITY_MISMATCH')
        marker, _, _ = io.stream(blobs, files['configuration/.service-account']['blob'], budget, stored=True, limit=128)
        schema.require(marker in (b'clashyaml', b'clashyaml\n'), 'ACCOUNT_ROLE_MISMATCH')


def create(source):
    result = report()
    try:
        schema.require(os.geteuid() == io.ROOT_UID and os.getegid() == io.ROOT_GID, 'ROOT_REQUIRED')
        schema.require(source != '/opt/clash-yaml-manager' and not source.startswith('/opt/clash-yaml-manager/'), 'LIVE_INSTALLATION_REFUSED')
        budget = io.Budget()
        publish = publication_function()  # Capability required before staging.
        with io.absolute_directory(source) as source_fd:
            io.private(os.fstat(source_fd), True)
            source_before = os.fstat(source_fd)
            raw_control, _, _ = io.stream(source_fd, io.CONTROL, budget, stored=True, limit=16*1024)
            control = schema.parse(raw_control)
            schema.declaration(control)
            schema.require(control['account_roles']['root']['uid'] == io.ROOT_UID
                           and control['account_roles']['root']['gid'] == io.ROOT_GID, 'UNSAFE_OWNERSHIP')
            schema.require(control['account_roles']['service']['uid'] != io.ROOT_UID
                           and control['account_roles']['service']['gid'] != io.ROOT_GID, 'UNSAFE_OWNERSHIP')
            before = io.scan_source(source_fd, control, budget)
            operation_id = secrets.token_hex(16)
            schema.operation(operation_id)
            result['operation_id'] = operation_id
            staging = '.stage-'+operation_id
            with managed(create=True) as (packages, records):
                os.mkdir(staging, 0o700, dir_fd=packages)
                result.update(cleanup='PRIVATE_STAGING_RETAINED_ON_FAILURE', publication='STAGING')
                with io.child_directory(packages, staging, stored=True) as stage:
                    os.mkdir('blobs', 0o700, dir_fd=stage)
                    entries = []
                    started_at = now()
                    with io.child_directory(stage, 'blobs', stored=True) as blobs:
                        for index, name in enumerate(sorted(set(before)-{io.CONTROL}, key=lambda p: p.encode('utf-8'))):
                            info, kind, target = before[name]
                            entry = dict(path=name, role=schema.role(name, kind), kind=kind,
                                         original=dict(mode=f'{stat.S_IMODE(info.st_mode):04o}', uid=info.st_uid,
                                                       gid=info.st_gid, mtime_ns=info.st_mtime_ns,
                                                       metadata_origin='OBSERVED_OFFLINE_FIXTURE'),
                                         blob=None, size=0, sha256=None, link_target=target,
                                         link_type=schema.link_target(target) if target is not None else None)
                            if kind == 'file':
                                entry['blob'] = f'{index:08d}'
                                with io.at(source_fd, name.split('/')[:-1], before) as parent:
                                    with io.new_file(blobs, entry['blob']) as output:
                                        _, entry['size'], entry['sha256'] = io.stream(parent, name.split('/')[-1], budget, expected=info, target=output)
                                        os.fsync(output)
                            entries.append(entry)
                        os.fsync(blobs)
                    io.compare_inventory(before, io.scan_source(source_fd, control, budget))
                    # Re-read all regular source bytes to reject changes during capture,
                    # including modifications after a file's first copy.
                    for entry in entries:
                        if entry['kind'] == 'file':
                            name = entry['path']
                            with io.at(source_fd, name.split('/')[:-1], before) as parent:
                                _, _, digest = io.stream(parent, name.split('/')[-1], budget, expected=before[name][0])
                                schema.require(digest == entry['sha256'], 'SOURCE_CHANGED')
                    io.compare_inventory(before, io.scan_source(source_fd, control, budget))
                    io.same(source_before, os.fstat(source_fd))
                    again, _, _ = io.stream(source_fd, io.CONTROL, budget, stored=True, limit=16*1024)
                    schema.require(again == raw_control, 'SOURCE_CHANGED')
                    with io.absolute_directory(source) as rebound:
                        io.same(source_before, os.fstat(rebound))
                    manifest = dict(format_version=1, profile=schema.PROFILE, operation_id=operation_id,
                                    **{k: control[k] for k in ('source_identity', 'target_identity', 'installation_binding', 'account_roles', 'runtime_requirements')},
                                    capture_interval=dict(started_at=started_at, ended_at=now()),
                                    capture_evidence=dict(offline_quiet='OPERATOR_DECLARED', consistency='NOT_ATOMIC_SNAPSHOT',
                                                         source_device=source_before.st_dev, source_inode=source_before.st_ino,
                                                         source_reinventoried=True, external_python_links=schema.resolve_links(entries),
                                                         extended_metadata='NOT_CAPTURED_RESTORE_UNSUPPORTED'),
                                    roots=schema.ROOTS, entries=entries, omissions=schema.OMISSIONS,
                                    retention=schema.RETENTION, restore_proven=False)
                    schema.validate(manifest)
                    data = schema.canonical(manifest)
                    digest = hashlib.sha256(data).hexdigest()
                    with io.new_file(stage, 'manifest.json') as output:
                        io.write_all(output, data, budget); os.fsync(output)
                    os.fsync(stage)
                    verify_fd(stage, budget, digest)
                    check_installation(stage, manifest, budget)
                    stage_identity = os.fstat(stage)
                result['publication'] = 'UNCERTAIN_UNTIL_DURABLE_IDENTITY_CHECK'
                publish(packages, staging, operation_id)
                os.fsync(packages)
                with io.child_directory(packages, operation_id, stored=True) as package:
                    info = os.fstat(package)
                    schema.require((info.st_dev, info.st_ino) == (stage_identity.st_dev, stage_identity.st_ino), 'PUBLICATION_IDENTITY_MISMATCH')
                    verified = verify_fd(package, budget, digest)
                    schema.require(verified == manifest, 'OBJECT_CHANGED')
                result.update(PACKAGE_CREATED=True, PACKAGE_VERIFIED=True, STRUCTURAL_VALID=True,
                              CONTENT_INTEGRITY_VALID=True, publication='PACKAGE_DURABLE', manifest_sha256=digest)
                record = dict(record_version=1, profile=schema.PROFILE, operation_id=operation_id,
                              manifest_sha256=digest, package_device=info.st_dev, package_inode=info.st_ino,
                              **{k: manifest[k] for k in ('source_identity', 'target_identity', 'installation_binding')},
                              trust_scope=TRUST_SCOPE)
                validate_record(record); bind(record, manifest, info)
                record_bytes = schema.canonical(record)
                with io.new_file(records, staging) as output:
                    io.write_all(output, record_bytes, budget); os.fsync(output)
                    record_identity = os.fstat(output)
                os.fsync(records)
                publish(records, staging, operation_id+'.json')
                os.fsync(records)
                actual, _, _ = io.stream(records, operation_id+'.json', budget, stored=True, limit=32*1024)
                schema.require(actual == record_bytes, 'OBJECT_CHANGED')
                final_record = os.stat(operation_id+'.json', dir_fd=records, follow_symlinks=False)
                schema.require((record_identity.st_dev, record_identity.st_ino) == (final_record.st_dev, final_record.st_ino), 'PUBLICATION_IDENTITY_MISMATCH')
            accepted = verify(operation_id, _budget=budget)
            schema.require(accepted['TRUST_ANCHOR_VERIFIED'], accepted['code'])
            result.update(TRUST_ANCHOR_VERIFIED=True, publication='PACKAGE_AND_RECORD_DURABLE', cleanup='NONE_NEEDED', code='CREATED')
    except (AuditFault, OSError) as error:
        result['code'] = error_code(error)
    except KeyboardInterrupt:
        result['code'] = 'INTERRUPTED_STAGING_OR_PUBLICATION_UNCERTAIN'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('create').add_argument('--source', required=True)
    commands.add_parser('verify').add_argument('--operation-id', required=True)
    args = parser.parse_args(argv)
    result = create(args.source) if args.command == 'create' else verify(args.operation_id)
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['TRUST_ANCHOR_VERIFIED'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
