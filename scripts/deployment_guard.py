"""Root-only admission for participating updaters, including remote finalization.

This module is also embedded into the two standalone bootstraps. Never unlink
the persistent directory or lock file. Closing references releases flock; an
explicit LOCK_UN would incorrectly unlock a parent's inherited description.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import errno
import fcntl
import os
import stat
import subprocess
import sys

GUARD_ROOT = '/var/lib/clash-yaml-manager-deployment'
GUARD_NAME = 'update.lock'
GUARD_UID = 0
GUARD_GID = 0
GUARD_ENV = 'CLASH_DEPLOYMENT_GUARD_FDS'
GUARD_CONFLICT_EXIT = 75
GUARD_UNSAFE_EXIT = 78
GUARD_ACTIVE = ContextVar('deployment_guard', default=None)


class DeploymentGuardError(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code
        self.exit_code = GUARD_CONFLICT_EXIT if code == 'DEPLOYMENT_GUARD_CONFLICT' else GUARD_UNSAFE_EXIT


def guard_require(condition, code='DEPLOYMENT_GUARD_UNSAFE'):
    if not condition:
        raise DeploymentGuardError(code)


def guard_require_root():
    guard_require(os.geteuid() == 0, 'DEPLOYMENT_GUARD_ROOT_REQUIRED')


def guard_io(function):
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except OSError:
            raise DeploymentGuardError('DEPLOYMENT_GUARD_UNAVAILABLE') from None
    return checked


def guard_identity(info):
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def guard_ancestor(info):
    # Root-owned sticky ancestors also protect root-owned children (/tmp in
    # native isolated fixtures). The fixed production ancestors are /var/lib.
    guard_require(stat.S_ISDIR(info.st_mode) and info.st_uid in (0, GUARD_UID))
    guard_require(not info.st_mode & 0o022 or bool(info.st_mode & stat.S_ISVTX))


def guard_private(info, directory=False):
    guard_require((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
                  and info.st_uid == GUARD_UID and info.st_gid == GUARD_GID
                  and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600))
    if not directory:
        guard_require(info.st_nlink == 1 and info.st_size == 0)


def guard_flags(directory=False):
    names = ('O_NOFOLLOW', 'O_NONBLOCK', 'O_CLOEXEC', 'O_DIRECTORY')
    guard_require(all(hasattr(os, name) for name in names), 'DEPLOYMENT_GUARD_UNAVAILABLE')
    return (os.O_RDONLY if directory else os.O_RDWR) | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | (os.O_DIRECTORY if directory else 0)


@guard_io
def guard_open_root(create=False):
    guard_require(isinstance(GUARD_ROOT, str) and GUARD_ROOT.startswith('/')
                  and len(GUARD_ROOT.encode()) <= 1024 and len(GUARD_ROOT.split('/')) <= 32
                  and all(p not in ('.', '..', '') for p in GUARD_ROOT.split('/')[1:]))
    pieces = GUARD_ROOT.split('/')[1:]
    fd = os.open('/', guard_flags(True))
    try:
        guard_ancestor(os.fstat(fd))
        for piece in pieces[:-1]:
            before = os.stat(piece, dir_fd=fd, follow_symlinks=False)
            guard_ancestor(before)
            following = os.open(piece, guard_flags(True), dir_fd=fd)
            try:
                guard_require(guard_identity(before) == guard_identity(os.fstat(following)))
            except BaseException:
                os.close(following)
                raise
            os.close(fd)
            fd = following
        made = False
        if create:
            try:
                os.mkdir(pieces[-1], 0o700, dir_fd=fd)
                made = True
            except FileExistsError:
                pass
        before = os.stat(pieces[-1], dir_fd=fd, follow_symlinks=False)
        guard_require(stat.S_ISDIR(before.st_mode) and before.st_uid == GUARD_UID and before.st_gid == GUARD_GID)
        root = os.open(pieces[-1], guard_flags(True), dir_fd=fd)
        try:
            guard_require(guard_identity(before) == guard_identity(os.fstat(root)))
            if made:
                os.fchmod(root, 0o700)  # Only the directory this call exclusively created.
                os.fsync(root)
                os.fsync(fd)
            guard_private(os.fstat(root), True)
        except BaseException:
            os.close(root)
            raise
        return root
    finally:
        os.close(fd)


def guard_flock(fd):
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
            raise DeploymentGuardError('DEPLOYMENT_GUARD_CONFLICT') from None
        raise DeploymentGuardError('DEPLOYMENT_GUARD_UNAVAILABLE') from None


class DeploymentGuard:
    def __init__(self, directory, lock):
        self.directory, self.lock = directory, lock
        self.directory_identity = guard_identity(os.fstat(directory))
        self.lock_identity = guard_identity(os.fstat(lock))

    @guard_io
    def validate(self):
        guard_private(os.fstat(self.directory), True)
        guard_private(os.fstat(self.lock))
        guard_require(guard_identity(os.fstat(self.directory)) == self.directory_identity
                      and guard_identity(os.fstat(self.lock)) == self.lock_identity,
                      'DEPLOYMENT_GUARD_CHANGED')
        current = guard_open_root()
        try:
            guard_require(guard_identity(os.fstat(current)) == self.directory_identity,
                          'DEPLOYMENT_GUARD_CHANGED')
            info = os.stat(GUARD_NAME, dir_fd=current, follow_symlinks=False)
            guard_private(info)
            guard_require(guard_identity(info) == self.lock_identity
                          and info.st_dev == os.fstat(current).st_dev,
                          'DEPLOYMENT_GUARD_CHANGED')
        finally:
            os.close(current)
        # This succeeds for the same inherited open-file description, but
        # refuses a forged fresh descriptor while another holder owns the lock.
        guard_flock(self.directory)
        guard_flock(self.lock)

    def environment(self, environ):
        self.validate()
        result = dict(environ)
        result[GUARD_ENV] = f'{self.directory}:{self.lock}'
        return result

    def close(self):
        failure = None
        for fd in (self.lock, self.directory):
            try:
                os.close(fd)
            except OSError:
                failure = DeploymentGuardError('DEPLOYMENT_GUARD_UNAVAILABLE')
        if failure:
            raise failure


@guard_io
def guard_acquire():
    guard_require_root()
    directory, lock = guard_open_root(True), None
    try:
        # Directory locking also excludes a second participating updater if a
        # privileged external actor replaces the lock file during this lease.
        guard_flock(directory)
        made = False
        try:
            lock = os.open(GUARD_NAME, guard_flags() | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
            made = True
        except FileExistsError:
            before = os.stat(GUARD_NAME, dir_fd=directory, follow_symlinks=False)
            guard_private(before)
            lock = os.open(GUARD_NAME, guard_flags(), dir_fd=directory)
            guard_require(guard_identity(before) == guard_identity(os.fstat(lock)), 'DEPLOYMENT_GUARD_CHANGED')
        if made:
            os.fchmod(lock, 0o600)
            os.fsync(lock)
            os.fsync(directory)
        guard_private(os.fstat(lock))
        guard_flock(lock)
        result = DeploymentGuard(directory, lock)
        result.validate()
        return result
    except BaseException:
        if lock is not None:
            os.close(lock)
        os.close(directory)
        raise


@guard_io
def guard_inherited(environ):
    guard_require_root()
    value = environ.get(GUARD_ENV, '')
    guard_require(isinstance(value, str) and len(value) <= 23, 'DEPLOYMENT_GUARD_BAD_HANDOFF')
    fields = value.split(':')
    guard_require(len(fields) == 2 and all(p.isascii() and p.isdigit() and len(p) <= 10 for p in fields),
                  'DEPLOYMENT_GUARD_BAD_HANDOFF')
    directory, lock = map(int, fields)
    guard_require(3 <= directory <= 2**31 - 1 and 3 <= lock <= 2**31 - 1
                  and directory != lock, 'DEPLOYMENT_GUARD_BAD_HANDOFF')
    duplicate_directory = os.dup(directory)
    try:
        duplicate_lock = os.dup(lock)
        try:
            result = DeploymentGuard(duplicate_directory, duplicate_lock)
            result.validate()
            return result
        except BaseException:
            os.close(duplicate_lock)
            raise
    except BaseException:
        os.close(duplicate_directory)
        raise


@contextmanager
def held_deployment_guard():
    # Remote admission always acquires independently. Environment cannot supply
    # an unchecked "already locked" assertion to skip this acquisition.
    handle = guard_acquire()
    token = GUARD_ACTIVE.set(handle)
    try:
        yield handle
        handle.validate()
    finally:
        GUARD_ACTIVE.reset(token)
        handle.close()


def current_deployment_guard():
    handle = GUARD_ACTIVE.get()
    guard_require(handle is not None, 'DEPLOYMENT_GUARD_BAD_HANDOFF')
    handle.validate()
    return handle


def deployment_guard_main(argv=None):
    sys.dont_write_bytecode = True
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args == ['--check-inherited']:
            handle = guard_inherited(os.environ)
            handle.close()  # Close duplicates only; never LOCK_UN the parent.
            return 0
        guard_require(len(args) >= 2 and args[0] == '--run-update', 'DEPLOYMENT_GUARD_ARGUMENTS')
        with held_deployment_guard() as handle:
            result = subprocess.run(['bash', args[1], *args[2:]], env=handle.environment(os.environ),
                                    pass_fds=(handle.directory, handle.lock))
            return result.returncode if result.returncode >= 0 else 128 - result.returncode
    except DeploymentGuardError as error:
        print('Deployment guard refused: ' + error.code, file=sys.stderr)
        return error.exit_code
    except (OSError, ValueError, TypeError):
        print('Deployment guard refused: DEPLOYMENT_GUARD_UNAVAILABLE', file=sys.stderr)
        return GUARD_UNSAFE_EXIT


if __name__ == '__main__':
    raise SystemExit(deployment_guard_main())
