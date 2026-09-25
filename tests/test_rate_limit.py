import json
import multiprocessing

import pytest

from core.rate_limit import LoginLimiter
from core.state import StateError


def test_two_limiters_share_threshold_expiry_and_prune(tmp_path):
    now = [1000.0]
    a, b = [LoginLimiter(tmp_path, clock=lambda: now[0]) for _ in range(2)]
    for _ in range(3):
        assert a.attempt('192.0.2.1', lambda: None) == (None, 0)
    assert b.attempt('192.0.2.1', lambda: None) == (None, 0)
    assert b.attempt('192.0.2.1', lambda: None) == (None, 900)
    assert a.retry_after('192.0.2.1') == 900
    now[0] += 899
    assert b.attempt('192.0.2.1', lambda: pytest.fail('locked login must not verify password')) == (None, 1)
    now[0] += 1
    assert a.retry_after('192.0.2.1') == 0
    assert json.loads(a.path.read_text())['ips'] == {}


def test_window_and_success_reset(tmp_path):
    now = [1000.0]
    limiter = LoginLimiter(tmp_path, max_failures=2, window=10, clock=lambda: now[0])
    limiter.attempt('192.0.2.1', lambda: None)
    now[0] += 11
    assert limiter.attempt('192.0.2.1', lambda: None) == (None, 0)
    assert limiter.attempt('192.0.2.1', lambda: {'authenticated': True}) == ({'authenticated': True}, 0)
    assert json.loads(limiter.path.read_text())['ips'] == {}


def test_only_ips_and_times_persisted(tmp_path):
    limiter = LoginLimiter(tmp_path)
    secret = 'never-persist-this-password-or-hash'
    limiter.attempt('192.0.2.1', lambda: secret if False else None)
    record = json.loads(limiter.path.read_text())['ips']['192.0.2.1']
    assert set(record) == {'failures', 'blocked_until'}
    assert secret not in limiter.path.read_text()
    assert limiter.path.stat().st_mode & 0o777 == 0o600


def test_bounded_state_does_not_evict_locked_ip(tmp_path):
    now = [1000.0]
    limiter = LoginLimiter(tmp_path, max_failures=1, max_entries=1, clock=lambda: now[0])
    limiter.attempt('192.0.2.1', lambda: None)
    assert limiter.attempt('192.0.2.2', lambda: pytest.fail('capacity is full')) == (None, 900)
    assert list(json.loads(limiter.path.read_text())['ips']) == ['192.0.2.1']
    now[0] += 901
    assert limiter.attempt('192.0.2.2', lambda: True) == (True, 0)


def test_corrupt_limiter_fails_closed(tmp_path):
    limiter = LoginLimiter(tmp_path)
    limiter.path.write_text('{invalid')
    with pytest.raises(StateError):
        limiter.attempt('192.0.2.1', lambda: True)


def _failed_attempts(directory, number):
    limiter = LoginLimiter(directory)
    for _ in range(number):
        limiter.attempt('192.0.2.1', lambda: None)


def test_process_shared_failures(tmp_path):
    ctx = multiprocessing.get_context('spawn')
    processes = [ctx.Process(target=_failed_attempts, args=(str(tmp_path), count)) for count in (3, 2)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0
    assert LoginLimiter(tmp_path).retry_after('192.0.2.1') > 0
