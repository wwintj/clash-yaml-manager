"""Small, process-shared local state primitives (Linux/macOS, local filesystem)."""
import fcntl
import json
import os
from pathlib import Path
import tempfile
from contextlib import contextmanager


class StateError(RuntimeError):
    """Safe to display: never include file contents or underlying exceptions."""


def private_directory(directory):
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        raise StateError('状态目录无效。')
    directory.chmod(0o700)
    return directory


@contextmanager
def file_lock(path):
    """Lock a separate inode: replacing the data file must not replace its lock."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def atomic_write(path, content):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    atomic_write(path, (json.dumps(value, ensure_ascii=True, sort_keys=True) + '\n').encode())


def read_json(path):
    try:
        if Path(path).is_symlink():
            raise ValueError
        with open(path, encoding='utf-8') as source:
            return json.load(source)
    except (OSError, ValueError, TypeError):
        raise StateError('状态文件不可读取或已损坏，请检查权限并从备份恢复。') from None
