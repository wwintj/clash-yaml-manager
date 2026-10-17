#!/usr/bin/env python3
"""Stdlib-only, offline, read-only managed-upgrade-v1 inspection and planning.

Run from a trusted tool checkout: python3 -B -m scripts.recovery_inspect.
Never executes a package, probes a live host, installs tools, or applies a plan.
"""
import sys

if __name__ == '__main__':
    sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import os
import re
import stat

from scripts import recovery_io as io, recovery_manifest as schema, recovery_package as package
from scripts.backup_audit import AuditFault, fingerprint

MAX_RECORDS = 64
MAX_TARGET_ENTRIES = 512
MAX_TARGET_BYTES = 16 * 1024 * 1024
TARGET_ROOTS = {'environment.json', 'state', 'configuration', 'uploads', 'outputs', 'backups', 'logs', 'bin'}
STATE_VERSIONS = {'auth.json': (1,), 'fixed_subscriptions.json': (1, 2, 3, 4, 5, 6),
                  'node_health.json': (1, 2), 'proxy_health.json': (1, 2),
                  'settings.json': (1,), 'notifications.json': (1,),
                  'temporary_links.json': (1,), 'login_attempts.json': (1,)}
FLAGS = ('STRUCTURAL_VALID', 'CONTENT_INTEGRITY_VALID', 'MANAGEMENT_RECORD_MATCHED',
         'TRUST_ANCHOR_VERIFIED', 'RUNTIME_REQUIREMENTS_READY', 'RESTORE_PLAN_READY', 'RESTORE_PROVEN')


def report():
    return dict.fromkeys(FLAGS, False) | dict(code='NOT_EVALUATED', operation_id=None,
        trust_scope=package.TRUST_SCOPE, state_policy='PRESERVE_LIVE_STATE',
        state_compatibility='UNKNOWN', executable=False, apply_implemented=False)


def names(fd, maximum, budget):
    result = []
    with os.scandir(fd) as entries:
        for entry in entries:
            budget.tick()
            schema.require(len(result) < maximum, 'ENTRY_LIMIT')
            result.append(entry.name)
    return sorted(result)


def inventory(root, budget, target=False):
    """Lstat through held no-follow descriptors, bounded, same-device, private."""
    found = {'': fingerprint(os.fstat(root))}
    device = os.fstat(root).st_dev
    total = 0
    maximum = MAX_TARGET_ENTRIES if target else schema.MAX_ENTRIES + 3

    def walk(fd, prefix):
        nonlocal total
        before = os.fstat(fd)
        io.private(before, True)
        for name in names(fd, maximum, budget):
            value = '/'.join(prefix + [name])
            schema.path(value)
            schema.require(len(found) < maximum, 'ENTRY_LIMIT')
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            schema.require(info.st_dev == device, 'CROSS_FILESYSTEM')
            directory = stat.S_ISDIR(info.st_mode)
            io.private(info, directory)
            found[value] = fingerprint(info)
            if directory:
                with io.child_directory(fd, name, info, stored=True) as child:
                    walk(child, prefix + [name])
            else:
                total += info.st_size
                schema.require(total <= (MAX_TARGET_BYTES if target else schema.MAX_TOTAL_BYTES + schema.MAX_JSON_BYTES), 'TOTAL_BYTE_LIMIT')
        io.same(before, os.fstat(fd))
    walk(root, [])
    return found


def state_shape(data, name):
    """Minimum data-only shape check, NOT full business compatibility proof."""
    try:
        value = schema.parse(data, canonical_required=False)
        schema.require(type(value) is dict and type(value.get('version')) is int
                       and value['version'] in STATE_VERSIONS[name], 'INVALID_STATE_SCHEMA')
        if name == 'auth.json':
            schema.require(type(value.get('auth_version')) is int and value['auth_version'] > 0
                and type(value.get('instance_id')) is str and re.fullmatch('[0-9a-f]{32}', value['instance_id'])
                and type(value.get('password_hash')) is str
                and re.fullmatch(r'(?:pbkdf2:sha256:[1-9][0-9]*|scrypt:[1-9][0-9]*:[1-9][0-9]*:[1-9][0-9]*)\$[A-Za-z0-9]+\$[0-9a-f]+', value['password_hash']), 'INVALID_STATE_SCHEMA')
        fields = {'fixed_subscriptions.json': ('subscriptions', dict), 'temporary_links.json': ('links', dict),
                  'login_attempts.json': ('ips', dict)}
        if name in fields:
            field, kind = fields[name]
            schema.require(type(value.get(field)) is kind, 'INVALID_STATE_SCHEMA')
        return 'MINIMUM_SHAPE_VALID_COMPATIBILITY_UNKNOWN'
    except AuditFault:
        return 'INVALID_STATE_SCHEMA'


def package_state(fd, manifest, budget):
    states = []
    with io.child_directory(fd, 'blobs', stored=True) as blobs:
        for entry in manifest['entries']:
            if entry['path'].startswith('state/') and entry['kind'] == 'file':
                name = entry['path'].split('/')[-1]
                if name in STATE_VERSIONS and entry['path'] == 'state/' + name:
                    raw, _, _ = io.stream(blobs, entry['blob'], budget, stored=True, limit=MAX_TARGET_BYTES)
                    states.append(state_shape(raw, name))
                else:
                    states.append('BUSINESS_CLOSURE_NOT_EVALUATED')
    return 'INVALID_STATE_SCHEMA' if 'INVALID_STATE_SCHEMA' in states else 'UNKNOWN'


def inspect_fd(packages, records, operation, budget):
    schema.operation(operation)
    record_info = os.stat(operation + '.json', dir_fd=records, follow_symlinks=False)
    schema.require(record_info.st_dev == os.fstat(records).st_dev, 'CROSS_FILESYSTEM')
    raw, _, _ = io.stream(records, operation + '.json', budget, expected=record_info, stored=True, limit=32 * 1024)
    record = package.validate_record(schema.parse(raw))
    schema.require(record['operation_id'] == operation, 'RECORD_BINDING_MISMATCH')
    with io.child_directory(packages, operation, stored=True) as fd:
        before = inventory(fd, budget)
        manifest = package.verify_fd(fd, budget, record['manifest_sha256'])
        # Reuse the original canonical -> independent digest -> full content order.
        schema.require(manifest['operation_id'] == operation, 'RECORD_BINDING_MISMATCH')
        package.check_installation(fd, manifest, budget)
        package.bind(record, manifest, os.fstat(fd))
        archived_state = package_state(fd, manifest, budget)
        # Re-read all bytes after metadata/state reads to reject an in-flight change.
        schema.require(package.verify_fd(fd, budget, record['manifest_sha256']) == manifest, 'OBJECT_CHANGED')
        schema.require(before == inventory(fd, budget), 'OBJECT_CHANGED')
    again, _, _ = io.stream(records, operation + '.json', budget, expected=record_info, stored=True, limit=32 * 1024)
    schema.require(again == raw, 'OBJECT_CHANGED')
    return manifest, archived_state


def select(packages, records, selected, budget):
    if selected != 'latest':
        schema.operation(selected)
        return selected
    candidates = []
    before = os.fstat(records)
    record_names = names(records, MAX_RECORDS, budget)
    for name in record_names:
        schema.require(re.fullmatch(r'[0-9a-f]{32}\.json', name) is not None, 'UNEXPECTED_RECORD')
        manifest, _ = inspect_fd(packages, records, name[:-5], budget)
        candidates.append((schema.timestamp(manifest['capture_interval']['ended_at']), name[:-5]))
    io.same(before, os.fstat(records))
    schema.require(record_names == names(records, MAX_RECORDS, budget), 'OBJECT_CHANGED')
    schema.require(bool(candidates), 'NO_MANAGED_BACKUP')
    # Latest capture, not latest successful upgrade or expiry eligibility.
    return max(candidates)[1]


def verify(selected):
    result = report()
    try:
        budget = io.Budget()
        with package.managed() as (packages, records):
            operation = select(packages, records, selected, budget)
            manifest, archived_state = inspect_fd(packages, records, operation, budget)
        result.update({flag: True for flag in FLAGS[:4]})
        result.update(code='VERIFIED', operation_id=operation, archived_state=archived_state,
            source_version=manifest['source_identity']['version'], upgrade_target_version=manifest['target_identity']['version'],
            capture=dict(quiet='OPERATOR_DECLARED_NOT_SYSTEMD_PROVEN', atomic_snapshot=False,
                         started_at=schema.timestamp(manifest['capture_interval']['started_at']).isoformat(),
                         ended_at=schema.timestamp(manifest['capture_interval']['ended_at']).isoformat()),
            omissions=schema.OMISSIONS, runtime_requirements_origin='ROOT_OPERATOR_DECLARATION')
    except (AuditFault, OSError) as error:
        result['code'] = package.error_code(error)
    return result


def list_backups():
    result = report() | dict(backups=[], incomplete_count=0, orphan_count=0)
    try:
        budget = io.Budget()
        with package.managed() as (packages, records):
            before = (os.fstat(packages), os.fstat(records))
            rnames = names(records, MAX_RECORDS, budget)
            pnames = names(packages, MAX_RECORDS * 2, budget)
            for name in rnames:
                schema.require(re.fullmatch(r'[0-9a-f]{32}\.json', name) is not None, 'UNEXPECTED_RECORD')
                info = os.stat(name, dir_fd=records, follow_symlinks=False)
                schema.require(info.st_dev == os.fstat(records).st_dev, 'CROSS_FILESYSTEM')
                raw, _, _ = io.stream(records, name, budget, stored=True, limit=32 * 1024)
                record = package.validate_record(schema.parse(raw))
                schema.require(record['operation_id'] == name[:-5], 'RECORD_BINDING_MISMATCH')
                result['backups'].append(dict(operation_id=name[:-5], verification='NOT_EVALUATED'))
            for name in pnames:
                schema.require(re.fullmatch(r'(?:\.stage-)?[0-9a-f]{32}', name) is not None, 'UNEXPECTED_PACKAGE')
                with io.child_directory(packages, name, stored=True):
                    pass
                if name.startswith('.stage-'):
                    result['incomplete_count'] += 1
                elif name + '.json' not in rnames:
                    result['orphan_count'] += 1
            for old, fd in zip(before, (packages, records)):
                io.same(old, os.fstat(fd))
        result.update(code='LISTED', latest_basis='VERIFIED_CAPTURE_INTERVAL_ONLY_NOT_UPGRADE_SUCCESS')
    except (AuditFault, OSError) as error:
        result.update(code=package.error_code(error), backups=[])
    return result


def target_environment(value):
    schema.keys(value, ('schema_version', 'synthetic', 'runtime', 'accounts', 'install_path',
                       'current_identity', 'units', 'external_python', 'free_space_bytes', 'filesystem_metadata'))
    schema.require(type(value['schema_version']) is int and value['schema_version'] == 1
                   and value['synthetic'] is True, 'INVALID_TARGET_SCHEMA')
    runtime = value['runtime']
    schema.keys(runtime, ('os', 'architecture', 'python_version', 'python_abi', 'system_libraries'))
    for key in ('os', 'architecture', 'python_version', 'python_abi'):
        if runtime[key] is not None:
            schema.text(runtime[key], 128)
    schema.require(type(runtime['system_libraries']) is list and len(runtime['system_libraries']) <= 64)
    for library in runtime['system_libraries']:
        schema.text(library, 128)
    schema.identity(value['current_identity'])
    schema.text(value['install_path'], 1024)
    schema.keys(value['accounts'], ('root', 'service'))
    for role, account in value['accounts'].items():
        schema.keys(account, ('name', 'uid', 'gid'))
        schema.require(account['name'] == ('root' if role == 'root' else 'clashyaml'))
        schema.integer(account['uid'], 2**32-1); schema.integer(account['gid'], 2**32-1)
    schema.require(type(value['units']) is list and len(value['units']) <= len(schema.UNITS)
                   and all(type(unit) is str and unit in schema.UNITS for unit in value['units']))
    schema.require(len(value['units']) == len(set(value['units'])))
    schema.require(type(value['external_python']) is list and len(value['external_python']) <= 64)
    for path in value['external_python']:
        schema.require(type(path) is str and re.fullmatch(r'/usr/(?:local/)?bin/python3(?:\.\d+)?', path))
    schema.integer(value['free_space_bytes'])
    schema.require(value['filesystem_metadata'] in ('UNKNOWN', 'POSIX_ONLY', 'EXTENDED_PRESENT'))
    return value


def read_target(path, budget):
    # Offline fixtures only. Path binding in the descriptor is compared, never opened.
    schema.require(not any(path == p or path.startswith(p + '/') for p in ('/opt', '/root', '/var/lib')), 'LIVE_TARGET_REFUSED')
    with io.absolute_directory(path) as fd:
        io.private(os.fstat(fd), True)
        before = inventory(fd, budget, target=True)
        schema.require(set(names(fd, MAX_TARGET_ENTRIES, budget)) <= TARGET_ROOTS, 'UNEXPECTED_TARGET_OBJECT')
        raw, _, _ = io.stream(fd, 'environment.json', budget, stored=True, limit=32 * 1024)
        environment = target_environment(schema.parse(raw))
        states = []
        with io.child_directory(fd, 'state', stored=True) as state:
            for name in names(state, MAX_TARGET_ENTRIES, budget):
                if name in STATE_VERSIONS:
                    data, _, _ = io.stream(state, name, budget, stored=True, limit=MAX_TARGET_BYTES)
                    states.append(state_shape(data, name))
                else:
                    states.append('UNKNOWN')
            schema.require('auth.json' in names(state, MAX_TARGET_ENTRIES, budget), 'TARGET_STATE_MISSING')
        # Hash all fixture bytes for mutation detection; never print their contents.
        digests = {}
        for name in before:
            if name and stat.S_ISREG(before[name][2]):
                with io.at(fd, name.split('/')[:-1]) as parent:
                    _, _, digests[name] = io.stream(parent, name.split('/')[-1], budget, stored=True)
        schema.require(before == inventory(fd, budget, target=True), 'OBJECT_CHANGED')
        for name, digest in digests.items():
            with io.at(fd, name.split('/')[:-1]) as parent:
                _, _, again = io.stream(parent, name.split('/')[-1], budget, stored=True)
                schema.require(digest == again, 'OBJECT_CHANGED')
        schema.require(before == inventory(fd, budget, target=True), 'OBJECT_CHANGED')
        with io.absolute_directory(path) as rebound:
            io.same(os.fstat(fd), os.fstat(rebound))
        return environment, 'INVALID_STATE_SCHEMA' if 'INVALID_STATE_SCHEMA' in states else 'UNKNOWN'


def dry_run(selected, target):
    result = report()
    try:
        budget = io.Budget()
        with package.managed() as (packages, records):
            operation = select(packages, records, selected, budget)
            manifest, archived_state = inspect_fd(packages, records, operation, budget)
            environment, current_state = read_target(target, budget)
            # Verification and target assessment belong to one bounded observation.
            final, _ = inspect_fd(packages, records, operation, budget)
            schema.require(final == manifest, 'OBJECT_CHANGED')
        result.update({flag: True for flag in FLAGS[:4]})
        runtime = manifest['runtime_requirements']
        checks = {}
        for key in ('os', 'architecture', 'python_version', 'python_abi'):
            actual = environment['runtime'][key]
            checks[key] = 'UNKNOWN' if actual is None else 'MATCH' if runtime[key] == actual else 'MISMATCH'
        checks['system_libraries'] = 'MATCH' if set(runtime['system_libraries']) <= set(environment['runtime']['system_libraries']) else 'MISSING'
        checks['external_python'] = 'MATCH' if {e['target'] for e in manifest['capture_evidence']['external_python_links']} <= set(environment['external_python']) else 'MISSING'
        checks['installation_path'] = 'MATCH' if environment['install_path'] == manifest['installation_binding']['install_path'] else 'MISMATCH'
        checks['accounts'] = 'MATCH' if all(all(environment['accounts'][role][key] == account[key] for key in ('name', 'uid', 'gid')) for role, account in manifest['account_roles'].items()) else 'MISMATCH'
        units = sorted(e['path'].split('/')[1] for e in manifest['entries'] if e['role'] == 'UNITS' and e['kind'] == 'file')
        checks['units'] = 'MATCH' if set(units) <= set(environment['units']) else 'MISSING'
        payload = sum(e['size'] for e in manifest['entries'])
        # Lower bound: staging + preserved scene + manifest reserve; not a reservation.
        disk = 2 * payload + schema.MAX_JSON_BYTES
        checks['disk_space'] = 'MATCH' if environment['free_space_bytes'] >= disk else 'INSUFFICIENT'
        checks['target_permissions'] = 'PRIVATE_FIXTURE_VALIDATED'
        checks['filesystem_metadata'] = 'UNSUPPORTED' if environment['filesystem_metadata'] == 'EXTENDED_PRESENT' else 'UNKNOWN'
        checks['version'] = 'SAME_VERSION' if environment['current_identity'] == manifest['source_identity'] else 'CROSS_VERSION_REQUIRES_REVIEW'
        checks['state'] = 'INVALID_STATE_SCHEMA' if current_state == 'INVALID_STATE_SCHEMA' or archived_state == 'INVALID_STATE_SCHEMA' else 'UNKNOWN'
        blockers = [key.upper() + '_' + value for key, value in checks.items() if value not in ('MATCH', 'PRIVATE_FIXTURE_VALIDATED', 'SAME_VERSION')]
        blockers += ['ABI_AND_DEPENDENCIES_DECLARED_NOT_PROBED', 'BUSINESS_STATE_COMPATIBILITY_NOT_PROVEN',
                     'EXTENDED_METADATA_NOT_CAPTURED', 'CREDENTIAL_CONFIGURATION_REQUIRES_OPERATOR_DECISION',
                     'OMITTED_RUNTIME_COMPONENTS_NOT_VERIFIED', 'LINUX_NATIVE_NOT_VALIDATED', 'RESTORE_APPLY_NOT_IMPLEMENTED']
        result.update(code='PLAN_BLOCKED', operation_id=operation, prerequisites=checks, blockers=blockers,
            archived_state=archived_state, current_version=environment['current_identity']['version'],
            restore_version=manifest['source_identity']['version'], upgrade_target_version=manifest['target_identity']['version'],
            disk_required_lower_bound_bytes=disk, disk_reservation=False,
            services_requiring_later_stop=units, restore_material_classes=['APPLICATION', 'VENV', 'CONFIGURATION', 'DEFAULT', 'UNITS'],
            preserve_live_directories=['state', 'uploads', 'outputs', 'backups', 'logs', 'bin'],
            manual_decisions=['STATE_CODE_COMPATIBILITY', 'AUTH_ENV_REVOCATION_BOUNDARY', 'EXTERNAL_DEPENDENCY_EVIDENCE', 'CURRENT_SCENE_PRESERVATION'],
            evidence_scope='SYNTHETIC_OFFLINE_TARGET_DECLARATIONS_NOT_HOST_PROBES', omissions=schema.OMISSIONS)
    except (AuditFault, OSError) as error:
        result['code'] = package.error_code(error)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list'); commands.add_parser('status')
    for name in ('verify', 'restore'):
        command = commands.add_parser(name)
        choice = command.add_mutually_exclusive_group(required=True)
        choice.add_argument('selection', nargs='?', choices=('latest',))
        choice.add_argument('--id')
        if name == 'restore':
            command.add_argument('--dry-run', action='store_true', required=True)
            command.add_argument('--target-fixture', required=True)
    args = parser.parse_args(argv)
    if args.command in ('list', 'status'):
        result = list_backups()
    else:
        selected = args.id or args.selection
        result = verify(selected) if args.command == 'verify' else dry_run(selected, args.target_fixture)
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['code'] in ('VERIFIED', 'LISTED') else 1


if __name__ == '__main__':
    raise SystemExit(main())
