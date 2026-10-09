"""Independent retention policies and bounded, identity-checked age cleanup."""
import math
import os
import re
import stat
import time


POLICY_KEYS = ('UPLOAD_RETENTION_POLICY', 'OUTPUT_RETENTION_POLICY', 'BACKUP_RETENTION_POLICY')
MAX_SCAN_ENTRIES = 4096
SCAN_BUDGET_SECONDS = 2


def policies_from_env(env):
    """Validate all policies before any runtime directory initialization/cleanup."""
    values = tuple(env.get(key, 'timed') for key in POLICY_KEYS)
    if any(value not in ('timed', 'keep') for value in values):
        raise ValueError('Retention policies must be timed or keep.')
    return values


def link_seconds_from_env(env, output_seconds):
    """Missing option inherits the historical finite Output hours/days value."""
    value = env.get('TEMP_LINK_LIFETIME_HOURS')
    if value is None:
        return output_seconds
    if (not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,5}', value)
            or not 1 <= int(value) <= 87600):
        raise ValueError('TEMP_LINK_LIFETIME_HOURS must be an integer from 1 to 87600.')
    return int(value) * 3600


def seconds_from_env(env, key, default_hours, legacy=None):
    value, multiplier = env.get(key), 3600
    if value is None and legacy and env.get(legacy) is not None:
        value, multiplier = env[legacy], 86400
    if value is None:
        return default_hours * 3600
    try:
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            raise ValueError
        seconds = number * multiplier
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError
        return seconds
    except (ValueError, TypeError):
        # Historical malformed values must not crash upgrades or trigger mass deletion.
        return default_hours * 3600


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def cleanup_directory(directory, retention, policy, now, on_delete=None):
    """Flat YAML-only sweep; never open a kept directory or recurse into state.

    Cooperative entry/time budgets bound normal filesystem scanning. Shared lock
    is owned by the caller. Like ordinary unlink, final identity check/unlink is
    not atomic against a malicious writer with the same OS identity.
    """
    if policy not in ('timed', 'keep'):
        raise ValueError('Retention policies must be timed or keep.')
    if policy == 'keep':
        return 0
    deleted = 0
    start = time.monotonic()
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        root = os.fstat(fd)
        if root.st_uid != os.geteuid() or root.st_mode & 0o022:
            return 0
        with os.scandir(fd) as entries:
            for count, entry in enumerate(entries):
                if count >= MAX_SCAN_ENTRIES or time.monotonic() - start >= SCAN_BUDGET_SECONDS:
                    break
                name = entry.name
                if (len(name) > 255 or name.startswith('.') or '/' in name or '\\' in name
                        or not name.lower().endswith(('.yaml', '.yml'))):
                    continue
                try:
                    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                            or info.st_dev != root.st_dev or info.st_uid != os.geteuid()
                            or info.st_mode & 0o022 or now - info.st_mtime < retention):
                        continue
                    file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                    try:
                        if (_identity(info) != _identity(os.fstat(file_fd))
                                or _identity(info) != _identity(os.stat(name, dir_fd=fd, follow_symlinks=False))):
                            continue
                        current_root = os.stat(directory, follow_symlinks=False)
                        if ((current_root.st_dev, current_root.st_ino) != (root.st_dev, root.st_ino)
                                or current_root.st_uid != root.st_uid
                                or not stat.S_ISDIR(current_root.st_mode) or current_root.st_mode & 0o022):
                            continue
                        os.unlink(name, dir_fd=fd)
                        deleted += 1
                        if on_delete:
                            on_delete(name)
                    finally:
                        os.close(file_fd)
                except FileNotFoundError:
                    continue
    finally:
        os.close(fd)
    return deleted
