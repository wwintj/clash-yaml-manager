#!/usr/bin/env python3
"""Root updater hook: legacy offline subset integrity, never restore or deletion.

The shell calls this only after its original state backup has returned. No live
payload is collected. Service probes and filesystem headroom are global gates.
"""
import sys

if __name__ == '__main__':
    sys.dont_write_bytecode = True

from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
import re
import secrets
import selectors
import stat
import subprocess
import time

if __package__:
    from . import backup_collect as collector, backup_create as writer
    from . import backup_verify as verifier, backup_catalog as catalog
    from . import deployment_guard as guard
    from .backup_audit import AuditFault, SafeParser, fingerprint, flags, kind, parse_json
else:
    import backup_collect as collector
    import backup_create as writer
    import backup_verify as verifier
    import backup_catalog as catalog
    import deployment_guard as guard
    from backup_audit import AuditFault, SafeParser, fingerprint, flags, kind, parse_json

EXECUTOR_UID = 0
EXECUTOR_GID = 0
SIDECAR_ROOT = '/root/clash-yaml-manager-sidecars'
CGROUP_ROOT = '/sys/fs/cgroup'
SUPPORTED_QUIET_PLATFORM = sys.platform.startswith('linux')
DEPLOYMENT_RESERVE = 1024 * 1024 * 1024
UNITS = ('clash-yaml-manager.service', 'clash-yaml-manager-refresh.timer',
         'clash-yaml-manager-refresh.service', 'clash-yaml-manager-health.timer',
         'clash-yaml-manager-health.service')
PROPERTIES = ('LoadState', 'ActiveState', 'SubState', 'Job', 'MainPID', 'ControlPID',
              'ControlGroup', 'Slice', 'KillMode', 'Result')
GLOBAL_CODES = {'DISK_FULL', 'READ_FAILED', 'IO_FAILED', 'HEADROOM_INSUFFICIENT',
                'QUIET_GATE_REFUSED', 'CHECK_ERROR', 'MANUAL_WRITERS_NOT_ATTESTED',
                'KNOWN_BACKGROUND_WRITER', 'BACKUP_CHANGED', 'OBJECT_CHANGED',
                'UNSAFE_SOURCE_OWNERSHIP', 'UNSAFE_SOURCE_PERMISSION',
                'UNSAFE_SOURCE_ROOT', 'UNTRUSTED_SOURCE_DECLARATION',
                'SERVICE_IDENTITY_MISMATCH', 'INVALID_SERVICE_IDENTITY',
                'COLLECTION_INTERRUPTED', 'CREATION_INTERRUPTED', 'REGISTRATION_INTERRUPTED'}
CAPTURE_FILE = 'UPDATER_CAPTURE.json'


def require(condition, code):
    if not condition:
        raise AuditFault(code)


def protected_ancestor(info):
    require(kind(info) == 'directory' and info.st_uid in (0, EXECUTOR_UID)
            and (not info.st_mode & 0o022 or bool(info.st_mode & stat.S_ISVTX)), 'UNSAFE_ADAPTER_PATH')


@contextmanager
def physical_root(path, private=False):
    """Protected ancestors, descriptor-relative no-follow; no payload discovery."""
    raw = os.fspath(path)
    require(isinstance(raw, str) and raw.startswith('/') and '\x00' not in raw
            and len(os.fsencode(raw)) <= 1024 and len(raw.split('/')) <= 32
            and all(p not in ('', '.', '..') for p in raw.split('/')[1:]), 'UNSAFE_PATH')
    fd = os.open('/', flags(True))
    try:
        protected_ancestor(os.fstat(fd))
        for name in raw.split('/')[1:]:
            before = os.stat(name, dir_fd=fd, follow_symlinks=False)
            protected_ancestor(before)
            following = os.open(name, flags(True), dir_fd=fd)
            try:
                require(fingerprint(before) == fingerprint(os.fstat(following)), 'BACKUP_CHANGED')
            except BaseException:
                os.close(following)
                raise
            os.close(fd)
            fd = following
        if private:
            info = os.fstat(fd)
            require(info.st_uid == EXECUTOR_UID and info.st_gid == EXECUTOR_GID
                    and stat.S_IMODE(info.st_mode) == 0o700, 'UNSAFE_SOURCE_ROOT')
        yield fd
    finally:
        os.close(fd)


def private_child(parent, name):
    made = False
    try:
        os.mkdir(name, 0o700, dir_fd=parent)
        made = True
    except FileExistsError:
        pass
    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    require(kind(info) == 'directory' and info.st_uid == EXECUTOR_UID
            and info.st_gid == EXECUTOR_GID and stat.S_IMODE(info.st_mode) == 0o700
            and info.st_dev == os.fstat(parent).st_dev, 'UNSAFE_SOURCE_ROOT')
    if made:
        child = os.open(name, flags(True), dir_fd=parent)
        try:
            require(writer.identity(info) == writer.identity(os.fstat(child)), 'BACKUP_CHANGED')
            os.fsync(child)
            os.fsync(parent)
        finally:
            os.close(child)


def bounded_command(arguments, maximum=8192):
    """Do not retain unbounded systemctl/ps output or print arbitrary arguments."""
    with subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, close_fds=True) as child:
        result = bytearray()
        deadline = time.monotonic() + 5
        try:
            with selectors.DefaultSelector() as ready:
                ready.register(child.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    require(remaining > 0, 'CHECK_ERROR')
                    require(bool(ready.select(remaining)), 'CHECK_ERROR')
                    piece = os.read(child.stdout.fileno(), min(65536, maximum + 1 - len(result)))
                    if not piece:
                        break
                    result.extend(piece)
                    require(len(result) <= maximum, 'CHECK_ERROR')
            require(child.wait(timeout=max(0.01, deadline - time.monotonic())) == 0, 'CHECK_ERROR')
            return result.decode('utf-8', errors='strict')
        except BaseException:
            child.kill()  # Diagnostic child only, never a production writer.
            child.wait()
            raise


def read_small(fd, name, maximum):
    before = os.stat(name, dir_fd=fd, follow_symlinks=False)
    require(kind(before) == 'file' and before.st_nlink == 1 and before.st_size <= maximum
            and before.st_dev == os.fstat(fd).st_dev, 'UNSAFE_OBJECT')
    child = os.open(name, flags(), dir_fd=fd)
    try:
        require(fingerprint(before) == fingerprint(os.fstat(child)), 'BACKUP_CHANGED')
        result = bytearray()
        while True:
            data = os.read(child, min(65536, maximum + 1 - len(result)))
            if not data:
                break
            result.extend(data)
            require(len(result) <= maximum, 'CONTENT_SIZE_LIMIT')
        require(fingerprint(before) == fingerprint(os.fstat(child))
                == fingerprint(os.stat(name, dir_fd=fd, follow_symlinks=False)), 'BACKUP_CHANGED')
        return bytes(result)
    finally:
        os.close(child)


def quiet_evidence(held, external_quiet, evidence=None):
    held.validate()
    require(external_quiet == 'YES', 'MANUAL_WRITERS_NOT_ATTESTED')
    if evidence is None:
        evidence = {}
    evidence.update(external_manual_writers='OPERATOR_ATTESTED', guard='VALIDATED',
                    units={}, known_background_jobs='NOT_CHECKED')
    # Supported model: Linux cgroup v2, loaded units in system.slice. Missing
    # units/older lifecycles are refused, never inferred quiet from a stop result.
    with physical_root(CGROUP_ROOT) as cg:
        read_small(cg, 'cgroup.controllers', 4096)
        slice_fd = os.open('system.slice', flags(True), dir_fd=cg)
        try:
            for unit in UNITS:
                raw = bounded_command(['systemctl', 'show', unit, '--property=' + ','.join(PROPERTIES)])
                values = {}
                for line in raw.splitlines():
                    key, separator, value = line.partition('=')
                    require(separator and key in PROPERTIES and key not in values, 'CHECK_ERROR')
                    values[key] = value
                require(all(k in values for k in ('LoadState', 'ActiveState', 'SubState', 'Job')), 'CHECK_ERROR')
                load, active = values['LoadState'], values['ActiveState']
                classification = ('MISSING' if load == 'not-found' else 'UNKNOWN' if load != 'loaded'
                                  else active.upper() if active in ('failed', 'active', 'inactive') else 'UNKNOWN')
                evidence['units'][unit] = {'classification': classification}
                require(load == 'loaded' and active == 'inactive' and values['SubState'] == 'dead'
                        and values['Job'] in ('', '0'), 'QUIET_GATE_REFUSED')
                if unit.endswith('.service'):
                    require(values.get('MainPID') == values.get('ControlPID') == '0'
                            and values.get('ControlGroup') == '' and values.get('Slice') == 'system.slice'
                            and values.get('KillMode') == 'control-group'
                            and values.get('Result') == 'success', 'QUIET_GATE_REFUSED')
                    try:
                        directory = os.open(unit, flags(True), dir_fd=slice_fd)
                    except FileNotFoundError:
                        evidence['units'][unit]['cgroup'] = 'ABSENT'
                    else:
                        try:
                            events = read_small(directory, 'cgroup.events', 4096).decode('ascii')
                            require(re.search(r'^populated 0$', events, re.M) is not None
                                    and re.search(r'^populated 1$', events, re.M) is None, 'QUIET_GATE_REFUSED')
                            evidence['units'][unit]['cgroup'] = 'UNPOPULATED'
                        finally:
                            os.close(directory)
        finally:
            os.close(slice_fd)
    jobs = bounded_command(['systemctl', 'list-jobs', '--no-legend', '--no-pager'], 65536)
    for line in jobs.splitlines():
        if line.strip() == 'No jobs running.':
            continue
        fields = line.split()
        require(len(fields) == 4 and fields[0].isascii() and fields[0].isdigit()
                and fields[-1] in ('waiting', 'running'), 'CHECK_ERROR')
    require(not any(unit in line.split() for line in jobs.splitlines() for unit in UNITS), 'QUIET_GATE_REFUSED')
    processes = bounded_command(['ps', '-eo', 'pid=,ppid=,args='], 2 * 1024 * 1024)
    require(len(processes.splitlines()) <= 8192, 'CHECK_ERROR')
    inventory = {}
    for line in processes.splitlines():
        fields = line.strip().split(None, 2)
        require(len(fields) == 3 and all(f.isascii() and f.isdigit() for f in fields[:2]), 'CHECK_ERROR')
        pid, parent_pid = map(int, fields[:2])
        require(pid not in inventory, 'CHECK_ERROR')
        inventory[pid] = (parent_pid, fields[2].split())
    ancestors = {os.getpid()}
    cursor = os.getppid()
    for _ in range(32):
        if cursor == 0 or cursor in ancestors or cursor not in inventory:
            break
        ancestors.add(cursor)
        cursor = inventory[cursor][0]
    for pid, (_, arguments) in inventory.items():
        known = any(item in ('core.auto_refresh', 'core.auto_health', 'core.migrate') for item in arguments)
        known = known or bool(arguments and os.path.basename(arguments[0]) == 'mihomo')
        known = known or (pid not in ancestors and any(os.path.basename(item) in
                ('update.sh', 'remote-update.sh', 'install.sh', 'remote-install.sh', 'uninstall.sh',
                 'httpsctl.sh', 'mihomoctl.sh') for item in arguments))
        require(not known, 'KNOWN_BACKGROUND_WRITER')
    held.validate()
    evidence['known_background_jobs'] = 'NONE_OBSERVED'
    return evidence


def headroom(paths, sidecar_bytes=3 * collector.MAX_TOTAL_BYTES):
    """Conservative reserve, no unlimited-capacity or atomic reservation claim."""
    for path in paths:
        with physical_root(path) as fd:
            space = os.fstatvfs(fd)
            require(space.f_bavail * space.f_frsize >= DEPLOYMENT_RESERVE + sidecar_bytes
                    and (space.f_favail == 0 and space.f_files == 0 or space.f_favail >= 2048),
                    'HEADROOM_INSUFFICIENT')


class LegacySubset:
    """Bounded no-follow copy, preserving captured ownership only on NEW objects."""
    def __init__(self, service):
        self.service = service
        self.started = time.monotonic()
        self.read_bytes = 0

    def tick(self):
        require(time.monotonic() - self.started <= collector.MAX_SECONDS, 'TIME_LIMIT')

    def inventory(self, root):
        records, omitted = {(): os.fstat(root)}, []
        def walk(fd, prefix):
            self.tick()
            names = []
            with os.scandir(fd) as entries:
                for entry in entries:
                    self.tick()
                    require(len(records) + len(names) + 6 < collector.MAX_ENTRIES, 'ENTRY_LIMIT')
                    names.append(entry.name)
            for name in sorted(names):
                self.tick()
                path = prefix + (name,)
                require(len(path) <= collector.MAX_DEPTH, 'DEPTH_LIMIT')
                writer.protocol.relative_path('/'.join(path))
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                require(kind(info) != 'unsafe' and (kind(info) != 'file' or info.st_nlink == 1)
                        and info.st_dev == records[()].st_dev, 'UNSAFE_OBJECT')
                # Legacy units are reviewed recovery material, not Collector scope.
                if not prefix and name in UNITS:
                    require(kind(info) == 'file', 'UNSAFE_OBJECT')
                    omitted.append({'path': name, 'role': 'LEGACY_ONLY_UNIT', 'original': writer.metadata(info)})
                    records[path] = info
                    continue
                wanted, role, selected = collector.policy(path)
                require(path != (collector.SOURCE_CONTROL,), 'UNTRUSTED_SOURCE_DECLARATION')
                require(kind(info) == wanted, 'UNSAFE_OBJECT')
                records[path] = info
                if not selected:
                    omitted.append({'path': '/'.join(path), 'role': role, 'original': writer.metadata(info)})
                    continue
                pairs = {(EXECUTOR_UID, EXECUTOR_GID)}
                if path[0] == 'state' and self.service:
                    pairs.add((self.service['uid'], self.service['gid']))
                require((info.st_uid, info.st_gid) in pairs, 'UNSAFE_SOURCE_OWNERSHIP')
                mode = stat.S_IMODE(info.st_mode)
                private = path[0] == 'state' or path in (('.env',), ('.service-account',))
                require(not mode & 0o7000 and (mode == (0o700 if wanted == 'directory' else 0o600)
                        if private else not mode & 0o022), 'UNSAFE_SOURCE_PERMISSION')
                if wanted == 'file':
                    require(info.st_size <= collector.MAX_FILE_BYTES, 'FILE_BYTE_LIMIT')
                else:
                    child = os.open(name, flags(True), dir_fd=fd)
                    try:
                        require(fingerprint(info) == fingerprint(os.fstat(child)), 'BACKUP_CHANGED')
                        walk(child, path)
                    finally:
                        os.close(child)
        walk(root, ())
        selected = {p: i for p, i in records.items() if not p or '/'.join(p) not in {o['path'] for o in omitted}}
        require((collector.REQUIRED - {(collector.SOURCE_CONTROL,)}) <= set(selected), 'MISSING_REQUIRED_COMPONENT')
        require(sum(i.st_size for i in selected.values() if kind(i) == 'file')
                + writer.protocol.MAX_MANIFEST_BYTES + 3 * collector.MAX_METADATA_BYTES
                <= collector.MAX_TOTAL_BYTES, 'TOTAL_BYTE_LIMIT')
        return records, selected, omitted

    @contextmanager
    def record(self, root, path, records):
        fd = os.dup(root)
        try:
            for index, name in enumerate(path):
                self.tick()
                expected = records[path[:index + 1]]
                require(fingerprint(os.stat(name, dir_fd=fd, follow_symlinks=False)) == fingerprint(expected), 'BACKUP_CHANGED')
                following = os.open(name, flags(kind(expected) == 'directory'), dir_fd=fd)
                os.close(fd)
                fd = following
                require(fingerprint(os.fstat(fd)) == fingerprint(expected), 'BACKUP_CHANGED')
            yield fd
        finally:
            os.close(fd)

    def copy(self, root, destination, selected):
        for path, info in sorted(selected.items()):
            if not path:
                continue
            self.tick()
            with self.output_directory(destination, path[:-1]) as folder:
                if kind(info) == 'directory':
                    os.mkdir(path[-1], 0o700, dir_fd=folder)
                    target = os.open(path[-1], flags(True), dir_fd=folder)
                else:
                    target = os.open(path[-1], os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                                     | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=folder)
                try:
                    if kind(info) == 'file':
                        digest = hashlib.sha256()
                        with self.record(root, path, selected) as incoming:
                            remaining = info.st_size
                            while remaining:
                                self.tick()
                                piece = os.read(incoming, min(remaining, 65536))
                                require(bool(piece), 'BACKUP_CHANGED')
                                remaining -= len(piece)
                                digest.update(piece)
                                self.read_bytes += len(piece)
                                require(self.read_bytes <= collector.MAX_READ_BYTES, 'TOTAL_READ_LIMIT')
                                view = memoryview(piece)
                                while view:
                                    count = os.write(target, view)
                                    require(count > 0, 'IO_FAILED')
                                    view = view[count:]
                            require(fingerprint(os.fstat(incoming)) == fingerprint(info), 'BACKUP_CHANGED')
                        require(os.fstat(target).st_size == info.st_size, 'STORED_BYTES_MISMATCH')
                        os.lseek(target, 0, os.SEEK_SET)
                        stored = hashlib.sha256()
                        remaining = info.st_size
                        while remaining:
                            self.tick()
                            piece = os.read(target, min(remaining, 65536))
                            require(bool(piece), 'STORED_BYTES_MISMATCH')
                            remaining -= len(piece)
                            self.read_bytes += len(piece)
                            require(self.read_bytes <= collector.MAX_READ_BYTES, 'TOTAL_READ_LIMIT')
                            stored.update(piece)
                        require(stored.digest() == digest.digest(), 'STORED_BYTES_MISMATCH')
                    os.fchown(target, info.st_uid, info.st_gid)
                    os.fchmod(target, stat.S_IMODE(info.st_mode))
                    os.fsync(target)
                    self.output_records[path] = os.fstat(target)
                finally:
                    os.close(target)
            # Directory content writes change its fingerprint; refresh only NEW
            # owned output metadata, never the source inventory.
            with self.output_directory(destination, path[:-1]) as parent:
                self.output_records[path[:-1]] = os.fstat(parent)

    @contextmanager
    def output_directory(self, root, path):
        fd = os.dup(root)
        try:
            require(writer.identity(os.fstat(fd)) == writer.identity(self.output_records[()]), 'BACKUP_CHANGED')
            for index, name in enumerate(path):
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                require(writer.identity(info) == writer.identity(self.output_records[path[:index + 1]]), 'BACKUP_CHANGED')
                child = os.open(name, flags(True), dir_fd=fd)
                os.close(fd)
                fd = child
                require(writer.identity(os.fstat(fd)) == writer.identity(info), 'BACKUP_CHANGED')
            yield fd
        finally:
            os.close(fd)


def new_json(fd, name, value, maximum=collector.MAX_METADATA_BYTES):
    raw = collector.canonical(value, maximum)
    opened = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                     | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=fd)
    try:
        view = memoryview(raw)
        while view:
            count = os.write(opened, view)
            require(count > 0, 'IO_FAILED')
            view = view[count:]
        os.fsync(opened)
    finally:
        os.close(opened)
    os.fsync(fd)


def service_identity(legacy):
    try:
        info = os.stat('.service-account', dir_fd=legacy, follow_symlinks=False)
    except FileNotFoundError:
        return None
    require(info.st_uid == EXECUTOR_UID and info.st_gid == EXECUTOR_GID
            and stat.S_IMODE(info.st_mode) == 0o600, 'SERVICE_IDENTITY_MISMATCH')
    marker = read_small(legacy, '.service-account', collector.MAX_CONTROL_BYTES)
    match = re.fullmatch(rb'clashyaml:([0-9]{1,10}):([0-9]{1,10})\n', marker)
    require(match is not None, 'SERVICE_IDENTITY_MISMATCH')
    uid, gid = map(int, match.groups())
    require(0 < uid < 2**32 - 1 and 0 < gid < 2**32 - 1 and uid != EXECUTOR_UID, 'INVALID_SERVICE_IDENTITY')
    account = bounded_command(['getent', 'passwd', 'clashyaml']).strip().split(':')
    require(len(account) == 7 and account[0] == 'clashyaml' and account[2:4] == [str(uid), str(gid)]
            and account[4:] == ['Clash YAML Manager service', '/nonexistent', '/usr/sbin/nologin'], 'SERVICE_IDENTITY_MISMATCH')
    return {'name': 'clashyaml', 'uid': uid, 'gid': gid}


def deployment_identities(legacy, target_source):
    version = read_small(legacy, 'VERSION', collector.MAX_CONTROL_BYTES).decode('ascii').rstrip('\n')
    original = None
    try:
        original = parse_json(read_small(legacy, 'INSTALLATION.json', catalog.MAX_RECORD_BYTES))
    except FileNotFoundError:
        pass
    require(original is None or catalog.safe_identity(original) and original['base_version'] == version,
            'INVALID_DEPLOYMENT_IDENTITY')
    with physical_root(target_source) as fd:
        target_version = read_small(fd, 'VERSION', collector.MAX_CONTROL_BYTES).decode('ascii').rstrip('\n')
    metadata_path = os.environ.get('CLASH_DEPLOY_METADATA')
    if metadata_path:
        parent, name = os.path.split(metadata_path)
        with physical_root(parent, True) as fd:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            require(info.st_uid == EXECUTOR_UID and info.st_gid == EXECUTOR_GID
                    and not stat.S_IMODE(info.st_mode) & 0o022, 'INVALID_DEPLOYMENT_IDENTITY')
            target = parse_json(read_small(fd, name, catalog.MAX_RECORD_BYTES))
    else:
        target = dict(base_version=target_version, channel='local', commit=None, tag=None,
                      source='local-source', installed_at=datetime.now(timezone.utc).isoformat())
    require(catalog.safe_identity(target) and target is not None and target['base_version'] == target_version,
            'INVALID_DEPLOYMENT_IDENTITY')
    return original, target


def empty_report():
    return dict(LEGACY_BACKUP_STATUS='COMPLETE_BY_UPDATER_HANDOFF', SIDECAR_STATUS='NOT_RUN',
                CATALOG_STATUS='NOT_RUN', PUBLICATION_STATUS={}, CLEANUP_STATUS={},
                UPGRADE_STATUS='BLOCKED', operation_id=None, snapshot_id=None,
                manifest_sha256=None, quiet_evidence=None, validation_codes=[], restore_proven=False)


def run(legacy_backup, installed, mode, external_quiet, target_source):
    report = empty_report()
    held = None
    codes = set()
    paths = []
    operation = None
    before = None
    def probe_quiet():
        report['quiet_evidence'] = {}
        return quiet_evidence(held, external_quiet, report['quiet_evidence'])
    def confirm_legacy():
        if before is not None:
            with physical_root(legacy_backup, True) as fd:
                after, _, _ = engine.inventory(fd)
                require({p: fingerprint(i) for p, i in before.items()} ==
                        {p: fingerprint(i) for p, i in after.items()}, 'BACKUP_CHANGED')
    try:
        require(os.geteuid() == EXECUTOR_UID and os.getegid() == EXECUTOR_GID, 'ROOT_REQUIRED')
        require(mode in ('OPTIONAL', 'STRICT'), 'INVALID_MODE')
        require(SUPPORTED_QUIET_PLATFORM, 'UNSUPPORTED_QUIET_PLATFORM')
        held = guard.guard_inherited(os.environ)
        probe_quiet()
        parent, basename = os.path.split(SIDECAR_ROOT)
        paths = [parent, installed]
        headroom(paths)
        with physical_root(parent) as parent_fd:
            private_child(parent_fd, basename)
        with physical_root(SIDECAR_ROOT, True) as side:
            private_child(side, 'operations')
            private_child(side, 'catalog')
        operation_id = secrets.token_hex(16)
        report['operation_id'] = operation_id
        operations = SIDECAR_ROOT + '/operations'
        with physical_root(operations, True) as fd:
            os.mkdir(operation_id, 0o700, dir_fd=fd)  # Unique; never reuse residue.
            os.fsync(fd)
        operation = operations + '/' + operation_id
        paths += [SIDECAR_ROOT, operation]
        with physical_root(operation, True) as op, physical_root(legacy_backup, True) as legacy:
            original_identity, target_identity = deployment_identities(legacy, target_source)
            service = service_identity(legacy)
            engine = LegacySubset(service)
            before, selected, omissions = engine.inventory(legacy)
            os.mkdir('source', 0o700, dir_fd=op)
            with physical_root(operation + '/source', True) as source:
                engine.output_records = {(): os.fstat(source)}
                engine.copy(legacy, source, selected)
                after, _, _ = engine.inventory(legacy)
                require({p: fingerprint(i) for p, i in before.items()} ==
                        {p: fingerprint(i) for p, i in after.items()}, 'BACKUP_CHANGED')
                probe_quiet()
                new_json(source, collector.SOURCE_CONTROL, dict(schema_version=1, profile=collector.PROFILE,
                         offline=True, writers_quiet=True, service_account=service), collector.MAX_CONTROL_BYTES)
            capture = dict(schema_version=1, metadata_origin='LEGACY_BACKUP_NOT_LIVE_FILESYSTEM',
                           source_ownership_ledger_origin='ADAPTER_OFFLINE_SOURCE',
                           legacy_backup_capture='STAGED_CONFIG_THEN_QUIET_STATE',
                           legacy_state_copy='UPDATER_RETURNED_SUCCESS', quiet=report['quiet_evidence'],
                           operation_id=operation_id, restore_proven=False, atomic_snapshot=False,
                           original_identity=original_identity, target_identity=target_identity,
                           target_identity_is='PRE_MIGRATION_OPERATOR_CLAIM',
                           omitted=omissions, original_entries=[dict(path='/'.join(p) if p else '.',
                           role=collector.policy(p)[1], **writer.metadata(i)) for p, i in sorted(selected.items())])
        def stage(name, result, success):
            report['PUBLICATION_STATUS'][name] = result.get('publication_status', 'NOT_APPLICABLE')
            report['CLEANUP_STATUS'][name] = result.get('cleanup_status', 'NOT_APPLICABLE')
            codes.update(result.get('validation_codes', []))
            headroom(paths, 0)
            require(success, 'SIDECAR_STAGE_FAILED')
        report['SIDECAR_STATUS'] = 'FAILED'
        collected = operation + '/collected'
        result = collector.collect(operation + '/source', collected, collector.PROFILE)
        stage('collector', result, result['collection_status'] == 'COLLECTED')
        with physical_root(collected, True) as fd:
            new_json(fd, CAPTURE_FILE, capture)
        snapshot = operation + '/snapshot'
        result = writer.create(collected, snapshot, 'UPDATER_SNAPSHOT')
        stage('writer', result, result['creation_status'] == 'CREATED'
              and writer.protocol.valid_digest(result['MANIFEST_SHA256']))
        digest = result['MANIFEST_SHA256']  # Successful Writer result ONLY.
        report['manifest_sha256'] = digest
        result = verifier.verify(snapshot, digest)
        stage('verifier', result, result['verification_status'] == 'TRUSTED_SCOPE_VERIFIED'
              and result['full_file_coverage'] is True)
        report['CATALOG_STATUS'] = 'FAILED'
        result = catalog.execute('register', SIDECAR_ROOT + '/catalog', snapshot=snapshot,
                                 representation=collected, operation_id=operation_id,
                                 profile=collector.PROFILE, expected_digest=digest, completed_offline=True,
                                 original_identity=original_identity, target_identity=target_identity)
        stage('catalog_register', result, result['registration_status'] == 'REGISTERED'
              and result['metadata']['operation_id'] == operation_id)
        report['snapshot_id'] = result['snapshot_id']
        result = catalog.execute('verify', SIDECAR_ROOT + '/catalog', snapshot=snapshot,
                                 snapshot_id=report['snapshot_id'])
        stage('catalog_verify', result, result['verification_status'] == 'TRUSTED_SCOPE_VERIFIED'
              and result['snapshot_identity_match'] is True and result['manifest_digest_match'] is True)
        report['CATALOG_STATUS'] = report['SIDECAR_STATUS'] = 'TRUSTED_SCOPE_VERIFIED'
        confirm_legacy()
        probe_quiet()
        report['UPGRADE_STATUS'] = 'PERMITTED_NOT_COMPLETED'
    except guard.DeploymentGuardError as error:
        codes.add(error.code)
    except (AuditFault, writer.protocol.ManifestError) as error:
        codes.add(error.code)
    except OSError as error:
        codes.add('DISK_FULL' if error.errno == errno.ENOSPC else 'IO_FAILED')
    except KeyboardInterrupt:
        codes.add('INTEGRATION_INTERRUPTED')
    except Exception:
        codes.add('INTEGRATION_FAILED')
    finally:
        if operation:
            report['CLEANUP_STATUS']['adapter'] = 'RETAINED_PRIVATE_OPERATION_NO_AUTO_DELETE'
        if report['UPGRADE_STATUS'] == 'BLOCKED' and mode == 'OPTIONAL' and held is not None:
            # Only explicit known ordinary failures qualify; unknown errors and
            # source authenticity/quiet/IO failures never silently continue.
            ordinary = {'SIDECAR_STAGE_FAILED', 'UNSUPPORTED_STATE_ENVELOPE', 'UNEXPECTED_COMPONENT',
                        'MISSING_REQUIRED_COMPONENT', 'FILE_BYTE_LIMIT', 'TOTAL_BYTE_LIMIT', 'ENTRY_LIMIT',
                        'DEPTH_LIMIT', 'TIME_LIMIT', 'TOTAL_READ_LIMIT', 'METADATA_SIZE_LIMIT'}
            fatal = codes & GLOBAL_CODES or any(c.startswith('DEPLOYMENT_GUARD_') for c in codes)
            if not fatal and codes & ordinary:
                try:
                    headroom(paths, 0)
                    confirm_legacy()
                    probe_quiet()
                    report['UPGRADE_STATUS'] = 'PERMITTED_WITH_SIDECAR_FAILURE_NOT_COMPLETED'
                except (AuditFault, guard.DeploymentGuardError) as error:
                    codes.add(error.code)
                except Exception:
                    codes.add('GLOBAL_RECHECK_FAILED')
        if held is not None:
            try:
                held.validate()
                held.close()  # Duplicates only; never unlock parent references.
            except guard.DeploymentGuardError as error:
                codes.add(error.code)
                report['UPGRADE_STATUS'] = 'BLOCKED'
        if report['SIDECAR_STATUS'] == 'NOT_RUN' and operation:
            report['SIDECAR_STATUS'] = 'FAILED'
        report['validation_codes'] = sorted(codes | {'RESTORE_NOT_PROVEN', 'ALLOWLIST_SUBSET_ONLY'})
    return report


def main(argv=None):
    parser = SafeParser(prog='backup_sidecar_update.py', allow_abbrev=False)
    parser.add_argument('--legacy-backup', required=True)
    parser.add_argument('--installed', required=True)
    parser.add_argument('--target-source', required=True)
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
        result = run(args.legacy_backup, args.installed, os.environ.get('CLASH_BACKUP_SIDECAR_MODE', 'OFF'),
                     os.environ.get('CLASH_BACKUP_EXTERNAL_WRITERS_QUIET', ''), args.target_source)
    except AuditFault:
        result = empty_report()
        result['validation_codes'] = ['INVALID_ARGUMENTS']
    print(json.dumps(result, sort_keys=True, ensure_ascii=True))
    return 0 if result['UPGRADE_STATUS'].startswith('PERMITTED') else 1


if __name__ == '__main__':
    raise SystemExit(main())
