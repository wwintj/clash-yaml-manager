"""Descriptor-relative bounded IO for the separate offline package protocol."""
from contextlib import contextmanager
import hashlib
import os
import stat
import time

from scripts.backup_audit import AuditFault, fingerprint, flags
from scripts import recovery_manifest as schema

ROOT_UID = 0
ROOT_GID = 0
MANAGED_ROOT = '/var/lib/clash-yaml-manager-upgrade-backups'
CHUNK_BYTES = 64 * 1024
CONTROL = 'capture.json'


class Budget:
    def __init__(self):
        self.started = time.monotonic()
        self.read_bytes = 0

    def tick(self, count=0):
        self.read_bytes += count
        schema.require(time.monotonic() - self.started <= schema.MAX_SECONDS, 'TIME_LIMIT')
        schema.require(self.read_bytes <= 8 * schema.MAX_TOTAL_BYTES + 4 * schema.MAX_JSON_BYTES, 'READ_BYTE_LIMIT')


def same(a, b):
    schema.require(fingerprint(a) == fingerprint(b), 'OBJECT_CHANGED')


def private(info, directory=False):
    schema.require((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
                   and info.st_uid == ROOT_UID and info.st_gid == ROOT_GID
                   and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600)
                   and (directory or info.st_nlink == 1), 'UNSAFE_STORED_METADATA')


def directory_identity(info):
    # Directory entries may legitimately change while the Writer creates files.
    # Compare security metadata, not mutable size/nlink/mtime/ctime here.
    return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode),
            stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid)


def ancestor(info):
    schema.require(stat.S_ISDIR(info.st_mode), 'UNSAFE_PATH')
    schema.require(info.st_uid in (0, ROOT_UID), 'UNSAFE_ANCESTOR')
    writable = stat.S_IMODE(info.st_mode) & 0o022
    schema.require(not writable or (info.st_uid == 0 and info.st_mode & stat.S_ISVTX), 'UNSAFE_ANCESTOR')


def revalidate_directory(parent, name, fd, before, stored=False, ancestry=False):
    current = os.fstat(fd)
    if stored:
        private(current, True)
    if ancestry:
        ancestor(current)
    schema.require(directory_identity(current) == directory_identity(before), 'OBJECT_CHANGED')
    after = os.stat(name, dir_fd=parent, follow_symlinks=False)
    schema.require(directory_identity(after) == directory_identity(current), 'OBJECT_CHANGED')


@contextmanager
def absolute_directory(value):
    # No environment overrides, normalization, symlink traversal or writable ancestors.
    schema.text(value, 4096)
    schema.require(value.startswith('/') and value != '/' and not value.endswith('/'), 'INVALID_PATH')
    parts = value.split('/')[1:]
    schema.require(all(p not in ('', '.', '..') for p in parts) and len(parts) <= 64, 'INVALID_PATH')
    fd = os.open('/', flags(True))
    descriptors = [fd]
    bindings = []
    try:
        root_before = os.fstat(fd)
        ancestor(root_before)
        for part in parts:
            before = os.stat(part, dir_fd=fd, follow_symlinks=False)
            ancestor(before)
            child = os.open(part, flags(True), dir_fd=fd)
            descriptors.append(child)
            same(before, os.fstat(child))
            bindings.append((fd, part, child, before))
            fd = child
        yield fd
        for parent, name, child, before in reversed(bindings):
            revalidate_directory(parent, name, child, before, ancestry=True)
        ancestor(os.fstat(descriptors[0]))
        schema.require(directory_identity(root_before) == directory_identity(os.fstat(descriptors[0])), 'OBJECT_CHANGED')
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


@contextmanager
def child_directory(parent, name, expected=None, stored=False):
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if expected is not None:
        same(expected, before)
    fd = os.open(name, flags(True), dir_fd=parent)
    try:
        same(before, os.fstat(fd))
        if stored:
            private(os.fstat(fd), True)
        yield fd
        # Rebinding a pathname must not let an old, detached descriptor verify success.
        revalidate_directory(parent, name, fd, before, stored=stored)
    finally:
        os.close(fd)


@contextmanager
def at(root, parts, records=None):
    fd = os.dup(root)
    try:
        for offset, part in enumerate(parts):
            before = os.stat(part, dir_fd=fd, follow_symlinks=False)
            if records is not None:
                same(records['/'.join(parts[:offset+1])][0], before)
            child = os.open(part, flags(True), dir_fd=fd)
            same(before, os.fstat(child))
            os.close(fd); fd = child
        yield fd
    finally:
        os.close(fd)


def stream(parent, name, budget, expected=None, stored=False, target=None, limit=None):
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if expected is not None:
        same(expected, before)
    schema.require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, 'UNSAFE_FILE')
    if stored:
        private(before)
    cap = schema.MAX_FILE_BYTES if limit is None else limit
    schema.require(before.st_size <= cap, 'FILE_BYTE_LIMIT')
    fd = os.open(name, flags(), dir_fd=parent)
    count, digest, data = 0, hashlib.sha256(), bytearray()
    try:
        same(before, os.fstat(fd))
        while True:
            budget.tick()
            chunk = os.read(fd, min(CHUNK_BYTES, cap-count+1))
            if not chunk:
                break
            count += len(chunk); budget.tick(len(chunk))
            schema.require(count <= cap, 'FILE_BYTE_LIMIT')
            digest.update(chunk)
            if target is not None:
                write_all(target, chunk, budget)
            elif limit is not None:
                data.extend(chunk)
        schema.require(count == before.st_size, 'OBJECT_CHANGED')
        same(before, os.fstat(fd))
        same(before, os.stat(name, dir_fd=parent, follow_symlinks=False))
        return bytes(data), count, digest.hexdigest()
    finally:
        os.close(fd)


def write_all(fd, data, budget):
    view = memoryview(data)
    while view:
        budget.tick()
        written = os.write(fd, view)
        schema.require(written > 0, 'WRITE_FAILED')
        view = view[written:]


@contextmanager
def new_file(parent, name):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                 | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=parent)
    try:
        os.fchmod(fd, 0o600)
        private(os.fstat(fd))
        yield fd
    finally:
        os.close(fd)


def scan_source(root, control, budget):
    records = {}
    device = os.fstat(root).st_dev
    total = 0

    def walk(fd, prefix):
        nonlocal total
        before_dir = os.fstat(fd)
        names = os.listdir(fd)
        for name in names:
            schema.text(name, schema.MAX_PATH_BYTES)
        names.sort(key=lambda p: p.encode('utf-8'))
        for name in names:
            budget.tick()
            value = '/'.join(prefix + [name])
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            schema.require(info.st_dev == device, 'CROSS_FILESYSTEM')
            kind = ('directory' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode)
                    else 'symlink' if stat.S_ISLNK(info.st_mode) else 'special')
            schema.require(kind != 'special', 'SPECIAL_FILE_REFUSED')
            schema.require(kind == 'directory' or info.st_nlink == 1, 'HARDLINK_REFUSED')
            if value == CONTROL:
                private(info)
            else:
                schema.role(value, kind)
                accounts = control['account_roles']
                owners = [accounts['root']] + ([accounts['service']] if prefix and prefix[0] == 'state' or value == 'state' else [])
                schema.require(any(info.st_uid == a['uid'] and info.st_gid == a['gid'] for a in owners), 'UNSAFE_OWNERSHIP')
                schema.require(kind == 'symlink' or not stat.S_IMODE(info.st_mode) & 0o7022, 'UNSAFE_SOURCE_MODE')
            schema.require(len(records) < schema.MAX_ENTRIES+1, 'ENTRY_LIMIT')
            schema.path(value)
            target = None
            if kind == 'symlink':
                target = os.readlink(name, dir_fd=fd)
                schema.link_target(target)
                same(info, os.stat(name, dir_fd=fd, follow_symlinks=False))
            if kind == 'file':
                schema.require(info.st_size <= schema.MAX_FILE_BYTES, 'FILE_BYTE_LIMIT')
                total += info.st_size
                schema.require(total <= schema.MAX_TOTAL_BYTES, 'TOTAL_BYTE_LIMIT')
            records[value] = (info, kind, target)
            if kind == 'directory':
                with child_directory(fd, name, info) as child:
                    walk(child, prefix+[name])
        same(before_dir, os.fstat(fd))
    walk(root, [])
    schema.require(schema.REQUIRED <= set(records), 'MISSING_REQUIRED')
    return records


def compare_inventory(before, after):
    schema.require(set(before) == set(after), 'SOURCE_CHANGED')
    for name in before:
        same(before[name][0], after[name][0])
        schema.require(before[name][1:] == after[name][1:], 'SOURCE_CHANGED')
