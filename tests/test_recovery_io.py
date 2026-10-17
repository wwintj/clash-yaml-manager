"""Path-walk stability: unrelated ancestor churn versus real directory changes."""
import os

import pytest

from scripts import recovery_io as io
from scripts.backup_audit import AuditFault


@pytest.fixture
def tree(tmp_path, monkeypatch):
    monkeypatch.setattr(io, 'ROOT_UID', os.geteuid())
    monkeypatch.setattr(io, 'ROOT_GID', os.getegid())
    os.chmod(tmp_path, 0o700)
    (tmp_path / 'a').mkdir(mode=0o700)
    (tmp_path / 'a' / 'b').mkdir(mode=0o700)
    return tmp_path


def before_open(monkeypatch, name, action):
    """Run action once, after the walk has stat()ed name and before it opens it."""
    original, done = os.open, []

    def wrapped(path, *args, **kwargs):
        if path == name and kwargs.get('dir_fd') is not None and not done:
            done.append(True)
            action()
        return original(path, *args, **kwargs)
    monkeypatch.setattr(os, 'open', wrapped)
    return done


def test_unrelated_entry_in_ancestor_is_not_a_change(tree, monkeypatch):
    done = before_open(monkeypatch, 'a', lambda: (tree / 'a' / 'unrelated').mkdir())
    with io.absolute_directory(str(tree / 'a' / 'b')) as fd:
        assert os.fstat(fd).st_ino == (tree / 'a' / 'b').stat().st_ino
    assert done


def test_replaced_ancestor_is_still_rejected(tree, monkeypatch):
    def replace():
        os.rename(tree / 'a', tree / 'old')
        (tree / 'a').mkdir(mode=0o700)
        (tree / 'a' / 'b').mkdir(mode=0o700)
    done, entered = before_open(monkeypatch, 'a', replace), []
    with pytest.raises(AuditFault, match='OBJECT_CHANGED'):
        with io.absolute_directory(str(tree / 'a' / 'b')):
            entered.append(True)
    assert done and not entered


def test_reprotected_ancestor_is_still_rejected(tree, monkeypatch):
    done, entered = before_open(monkeypatch, 'a', lambda: os.chmod(tree / 'a', 0o750)), []
    with pytest.raises(AuditFault, match='OBJECT_CHANGED'):
        with io.absolute_directory(str(tree / 'a' / 'b')):
            entered.append(True)
    assert done and not entered


def test_change_inside_final_directory_is_still_rejected(tree, monkeypatch):
    done, entered = before_open(monkeypatch, 'b', lambda: (tree / 'a' / 'b' / 'new').mkdir()), []
    with pytest.raises(AuditFault, match='OBJECT_CHANGED'):
        with io.absolute_directory(str(tree / 'a' / 'b')):
            entered.append(True)
    assert done and not entered


def test_shared_child_directory_tolerates_new_entries(tree, monkeypatch):
    with io.absolute_directory(str(tree)) as root:
        done = before_open(monkeypatch, 'a', lambda: (tree / 'a' / 'other').mkdir())
        with io.child_directory(root, 'a') as fd:
            assert os.fstat(fd).st_ino == (tree / 'a').stat().st_ino
    assert done


def test_recorded_child_directory_keeps_full_fingerprint(tree, monkeypatch):
    with io.absolute_directory(str(tree)) as root:
        expected = os.stat('a', dir_fd=root, follow_symlinks=False)
        done, entered = before_open(monkeypatch, 'a', lambda: (tree / 'a' / 'other').mkdir()), []
        with pytest.raises(AuditFault, match='OBJECT_CHANGED'):
            with io.child_directory(root, 'a', expected):
                entered.append(True)
    assert done and not entered
