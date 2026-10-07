"""Corrupt local objects must fail closed without trapping a worker in open()."""
import json
import os
import subprocess
import sys

import pytest

from conftest import ROOT
from core.state import StateError, read_json


def unchanged_metadata(path):
    # Reads may update filesystem atime; that is not an application write.
    value = path.lstat()
    return tuple(getattr(value, field) for field in (
        'st_mode', 'st_ino', 'st_dev', 'st_nlink', 'st_uid', 'st_gid',
        'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_rdev'))


@pytest.mark.parametrize('kind', ['fifo', 'directory', 'symlink', 'broken-link', 'corrupt'])
def test_json_reader_rejects_unsafe_objects_without_mutating_them(tmp_path, kind):
    path = tmp_path / 'state.json'
    other = tmp_path / 'other.json'
    other.write_bytes(b'{"private":"synthetic sentinel"}')
    if kind == 'fifo':
        os.mkfifo(path, 0o600)
    elif kind == 'directory':
        path.mkdir(mode=0o700)
    elif kind in ('symlink', 'broken-link'):
        path.symlink_to(other if kind == 'symlink' else tmp_path / 'missing')
    else:
        path.write_bytes(b'private malformed json')
        # Force a stale access time so reads exercise the original flaky case.
        os.utime(path, ns=(1, path.stat().st_mtime_ns))
    before = unchanged_metadata(path), other.read_bytes()
    # A subprocess timeout safely detects a regression to blocking FIFO opens.
    result = subprocess.run([sys.executable, '-c', '''
from core.state import StateError, read_json
import sys
try:
    read_json(sys.argv[1])
except StateError as error:
    assert 'private' not in str(error)
else:
    raise AssertionError('Unsafe state accepted')
''', str(path)], cwd=ROOT, capture_output=True, timeout=3)
    assert result.returncode == 0, result.stderr.decode()
    assert (unchanged_metadata(path), other.read_bytes()) == before


@pytest.mark.parametrize('mode', [0o600, 0o644])
def test_regular_legacy_json_read_preserves_bytes_permissions_and_inode(tmp_path, mode):
    path = tmp_path / 'state.json'
    value = {'version': 1, 'value': ' 密码 spaces '}
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    path.chmod(mode)
    before = path.read_bytes(), unchanged_metadata(path)
    assert read_json(path) == value
    assert (path.read_bytes(), unchanged_metadata(path)) == before


@pytest.mark.parametrize('kind', ['fifo', 'broken-link'])
@pytest.mark.parametrize('module,owner,filename,operation', [
    ('security', 'AuthStore', 'auth.json', 'read()'),
    ('rate_limit', 'LoginLimiter', 'login_attempts.json', "retry_after('127.0.0.1')"),
    ('temporary_links', 'TemporaryLinks', 'temporary_links.json', "resolve('A' * 16)"),
])
def test_authoritative_consumers_reject_unsafe_object_and_leave_it_intact(tmp_path, module, owner, filename, operation, kind):
    tmp_path.chmod(0o700)
    path = tmp_path / filename
    if kind=='fifo':os.mkfifo(path, 0o600)
    else:path.symlink_to(tmp_path/'missing')
    before = unchanged_metadata(path)
    code = f'''
import sys
from core.{module} import {owner}
from core.state import StateError
try:
    {owner}(sys.argv[1]).{operation}
except StateError:
    pass
else:
    raise AssertionError('FIFO accepted')
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path)], cwd=ROOT,
                            capture_output=True, timeout=3)
    assert result.returncode == 0, result.stderr.decode()
    assert unchanged_metadata(path) == before
