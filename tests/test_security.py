import base64
import json
import multiprocessing
from pathlib import Path

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

from core import state
from core.migrate import migrate_auth
from core.security import AuthStore, PASSWORD_METHOD
from core.state import StateError


@pytest.fixture(scope='module')
def password_hash():
    return generate_password_hash('legacy 密码 $!#', method=PASSWORD_METHOD)


def test_hash_verification_and_private_state(tmp_path):
    store = AuthStore(tmp_path / 'state')
    value = store.initialize({'APP_PASSWORD': 'new 密码'})
    assert value['password_hash'].startswith(PASSWORD_METHOD + '$')
    assert store.authenticate('new 密码') and not store.authenticate('wrong')
    assert 'new 密码' not in store.path.read_text()
    assert store.directory.stat().st_mode & 0o777 == 0o700
    assert store.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('kind', ['APP_PASSWORD', 'APP_PASSWORD_B64', 'APP_PASSWORD_HASH'])
def test_legacy_migration_preserves_unrelated_bytes(tmp_path, password_hash, kind):
    password = 'legacy 密码 $!#'
    value = {'APP_PASSWORD': "'" + password + "'", 'APP_PASSWORD_B64': base64.b64encode(password.encode()).decode(),
             'APP_PASSWORD_HASH': password_hash}[kind]
    unrelated = b'# keep comment\r\nSECRET_KEY=unchanged$!\r\nCUSTOM="literal $() `cmd` \\ path"\r\n'
    path = tmp_path / '.env'
    path.write_bytes(unrelated + f'{kind}={value}\n'.encode())
    migrated = migrate_auth(path, tmp_path / 'state')
    assert check_password_hash(migrated['password_hash'], password)
    assert path.read_bytes() == unrelated
    assert path.stat().st_mode & 0o777 == 0o600
    assert migrate_auth(path, tmp_path / 'state') == migrated


def test_credential_priority_and_existing_state_wins(tmp_path, password_hash):
    store = AuthStore(tmp_path / 'state')
    value = store.initialize({'APP_PASSWORD_HASH': password_hash, 'APP_PASSWORD_B64': 'bad!', 'APP_PASSWORD': 'wrong'})
    assert store.authenticate('legacy 密码 $!#')
    assert store.initialize({'APP_PASSWORD_HASH': 'invalid'}) == value


def test_b64_priority(tmp_path):
    store = AuthStore(tmp_path)
    store.initialize({'APP_PASSWORD_B64': 'cmlnaHQ=', 'APP_PASSWORD': 'wrong'})
    assert store.authenticate('right') and not store.authenticate('wrong')


@pytest.mark.parametrize('credentials', [{}, {'APP_PASSWORD_HASH': 'bad', 'APP_PASSWORD': 'fallback'},
                                        {'APP_PASSWORD_B64': '!bad!', 'APP_PASSWORD': 'fallback'}])
def test_invalid_legacy_never_downgrades(tmp_path, credentials):
    with pytest.raises(StateError):
        AuthStore(tmp_path).initialize(credentials)
    assert not (tmp_path / 'auth.json').exists()


def test_two_stores_password_change_and_version(tmp_path):
    a, b = AuthStore(tmp_path), AuthStore(tmp_path)
    initial = a.initialize({'APP_PASSWORD': 'old'})
    assert b.authenticate('old')
    assert a.change_password('old', 'new', initial['auth_version'], initial['instance_id'])
    assert not b.authenticate('old')
    assert b.authenticate('new')['auth_version'] == initial['auth_version'] + 1
    assert not b.change_password('new', 'other', initial['auth_version'], initial['instance_id'])


@pytest.mark.parametrize('failure_target', ['auth.json', '.env'])
def test_migration_failure_preserves_legacy(tmp_path, monkeypatch, failure_target):
    path = tmp_path / '.env'
    original = b'# keep\nAPP_PASSWORD=old\nSECRET_KEY=unchanged\n'
    path.write_bytes(original)
    replace = state.os.replace
    def fail(source, target):
        if Path(target).name == failure_target:
            raise OSError('synthetic write failure')
        return replace(source, target)
    monkeypatch.setattr(state.os, 'replace', fail)
    with pytest.raises(OSError):
        migrate_auth(path, tmp_path / 'state')
    assert path.read_bytes() == original
    if failure_target == '.env':
        assert AuthStore(tmp_path / 'state').authenticate('old')
    else:
        assert not (tmp_path / 'state/auth.json').exists()
    monkeypatch.setattr(state.os, 'replace', replace)
    assert migrate_auth(path, tmp_path / 'state')
    assert b'APP_PASSWORD' not in path.read_bytes()


def test_failed_change_leaves_complete_previous_json(tmp_path, monkeypatch):
    store = AuthStore(tmp_path)
    before = store.initialize({'APP_PASSWORD': 'old'})
    original = store.path.read_bytes()
    def fail(*args):
        raise OSError('synthetic full disk')
    monkeypatch.setattr(state.os, 'replace', fail)
    with pytest.raises(OSError):
        store.change_password('old', 'new', before['auth_version'], before['instance_id'])
    assert store.path.read_bytes() == original
    assert not list(tmp_path.glob('.auth.json-*'))


def test_corrupt_auth_never_falls_back(tmp_path):
    (tmp_path / 'auth.json').write_text('{broken')
    with pytest.raises(StateError):
        AuthStore(tmp_path).initialize({'APP_PASSWORD': 'old'})


def _initialize_worker(directory, password_hash):
    AuthStore(directory).initialize({'APP_PASSWORD_HASH': password_hash})


def test_real_processes_initialization_is_atomic(tmp_path, password_hash):
    ctx = multiprocessing.get_context('spawn')
    processes = [ctx.Process(target=_initialize_worker, args=(str(tmp_path), password_hash)) for _ in range(3)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(15)
        assert process.exitcode == 0
    value = json.loads((tmp_path / 'auth.json').read_text())
    assert value['auth_version'] == 1 and value['password_hash'] == password_hash
