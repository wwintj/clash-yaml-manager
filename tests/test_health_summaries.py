"""Local aggregate observations: no probes, read-time writes or stale identities."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from core import health_schedule, mihomo_probe, node_health, proxy_health, source_fetch
from core.state import LockBusyError, StateError, file_lock, write_json
from conftest import LINK
from test_fixed_subscriptions import base, save, source, store

NOW = 1_800_000_000


def forbidden(*args, **kwargs):
    pytest.fail('Summary attempted a probe, mutation or non-local operation')


@pytest.fixture(params=['endpoint', 'proxy'])
def worker(store, request):
    if request.param == 'endpoint':
        return node_health.NodeHealth(store, clock=forbidden, probe=forbidden)
    return proxy_health.ProxyHealth(store, clock=forbidden, runner=forbidden,
        resolver=forbidden, engine=SimpleNamespace(status=forbidden, binary=Path('/fixture/mihomo')))


def statuses(worker):
    values = ['healthy', 'suspect', 'unhealthy', 'unknown']
    return values + ['unsupported'] if isinstance(worker, proxy_health.ProxyHealth) else values


def observation(worker, status):
    record = node_health.unknown()
    if status != 'unknown':
        record['last_checked_at'] = NOW
    if status == 'healthy':
        record.update(status=status, latency_ms=12, last_success_at=NOW)
    elif status in ('suspect', 'unhealthy'):
        record.update(status=status, consecutive_failures=1 if status == 'suspect' else 3,
            error='proxy_failed' if isinstance(worker, proxy_health.ProxyHealth) else 'timeout')
    elif status == 'unsupported':
        record.update(status=status, error='unsupported_config')
    return record


def configured_entry(worker, node_states, mode='manual'):
    value = (proxy_health.empty_entry() if isinstance(worker, proxy_health.ProxyHealth)
             else node_health.empty_entry())
    value['mode'] = mode
    if mode == 'automatic':
        value.update(interval_seconds=900, next_check_at=NOW + 900)
    value['nodes'] = {fp: observation(worker, status) for fp, status in node_states.items()}
    return value


def seed(worker, entries, record_states=None, mode='manual', version=2, orphan=False):
    data = dict(version=version, subscriptions={})
    if isinstance(worker, proxy_health.ProxyHealth):
        data['global'] = dict(proxy_health.DEFAULT_PROBE, url='https://private-probe.example/check')
    for entry in entries:
        nodes = node_health.extract(worker.fixed._content(entry, 'current.yaml'))
        selected = record_states or ['healthy'] * len(nodes)
        value = configured_entry(worker, dict(zip([node['fingerprint'] for node in nodes], selected)), mode)
        if version == 1:
            for field in health_schedule.FIELDS:
                value.pop(field)
        data['subscriptions'][entry['id']] = value
    if orphan:
        data['subscriptions']['f' * 32] = configured_entry(worker, {})
    write_json(worker.path, data)
    return data


def files_before(store):
    files = {}
    for path in store.state.rglob('*'):
        if path.name.endswith('.lock') or path.is_dir() and not path.is_symlink():
            continue
        info = path.lstat()
        files[str(path.relative_to(store.state))] = (
            info.st_ino, info.st_mode, info.st_mtime_ns,
            os.readlink(path) if path.is_symlink() else path.read_bytes() if path.is_file() else None,
        )
    return files


def prohibit_effects(worker, monkeypatch):
    for name in ('describe', '_prune', '_commit', 'settings', 'check', '_check'):
        monkeypatch.setattr(worker, name, forbidden)
    for name in ('_commit', 'save', 'action', 'reconcile_health_policy'):
        monkeypatch.setattr(worker.fixed, name, forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(source_fetch, '_resolve', forbidden)
    monkeypatch.setattr(mihomo_probe, 'run', forbidden)


def test_empty_entries_do_not_open_locks_or_create_state(worker, monkeypatch):
    monkeypatch.setattr(worker.fixed, '_locked', forbidden)
    monkeypatch.setattr(worker, '_locked', forbidden)
    monkeypatch.setattr(worker, '_read', forbidden)
    assert worker.summary_many([]) == {}
    assert not worker.path.exists() and not worker.lock.exists()


def test_missing_state_off_and_no_new_json(worker, base, monkeypatch):
    entry = save(worker.fixed, base)
    before = files_before(worker.fixed)
    prohibit_effects(worker, monkeypatch)
    assert worker.summary_many([entry]) == {entry['id']: dict(
        mode='off', counts=dict.fromkeys(statuses(worker), 0), status='off')}
    assert not worker.path.exists() and files_before(worker.fixed) == before


@pytest.mark.parametrize('mode', ['off', 'manual', 'automatic'])
def test_mode_priority_and_orphan_observations_are_read_only(worker, base, monkeypatch, mode):
    config = source()
    selected = statuses(worker)
    config['batch_nodes'] = '\n'.join(
        f'US|Private Node {index}|{LINK.replace("example.com:443", f"private-{index}.example:{443 + index}")}'
        for index in range(len(selected)))
    entry = save(worker.fixed, base, config=config)
    seed(worker, [entry], selected, mode=mode, orphan=True)
    before = files_before(worker.fixed)
    prohibit_effects(worker, monkeypatch)
    summary = worker.summary_many([entry])[entry['id']]
    assert set(summary) == {'mode', 'counts', 'status'}
    assert summary['mode'] == mode
    assert summary['status'] == ('off' if mode == 'off' else 'unhealthy')
    assert summary['counts'] == dict.fromkeys(selected, 0 if mode == 'off' else 1)
    assert files_before(worker.fixed) == before
    public = json.dumps(summary)
    for private in ('Private Node', 'private-0.example', 'private-probe.example', LINK):
        assert private not in public


@pytest.mark.parametrize('selected, expected', [
    (['healthy', 'unknown'], 'healthy'), (['suspect', 'healthy'], 'suspect'),
    (['unhealthy', 'suspect'], 'unhealthy'), (['unknown', 'unknown'], 'unknown'),
])
def test_compact_priority_matches_current_fingerprints(worker, base, selected, expected):
    config = source()
    config['batch_nodes'] = 'US|First|' + LINK + '\nUS|Second|' + LINK.replace(':443', ':444')
    entry = save(worker.fixed, base, config=config)
    seed(worker, [entry], selected)
    summary = worker.summary_many([entry])[entry['id']]
    assert summary['status'] == expected
    assert sum(summary['counts'].values()) == 2


def test_proxy_unsupported_is_separate_from_unhealthy(store, base):
    worker = proxy_health.ProxyHealth(store, engine=SimpleNamespace(status=forbidden))
    config = source()
    config['batch_nodes'] = 'US|First|' + LINK + '\nUS|Second|' + LINK.replace(':443', ':444')
    entry = save(store, base, config=config)
    for states, expected in [(['unsupported', 'healthy'], 'unsupported'),
                             (['unsupported', 'suspect'], 'suspect')]:
        seed(worker, [entry], states)
        summary = worker.summary_many([entry])[entry['id']]
        assert summary['status'] == expected
        assert summary['counts']['unsupported'] == 1 and summary['counts']['unhealthy'] == 0


@pytest.mark.parametrize('version', [1, 2])
def test_legacy_state_and_hysteria2_credentials_stay_private_and_unmodified(worker, base, monkeypatch, version):
    password, obfs = 'TEST_ONLY_summary_auth_密', 'TEST_ONLY_summary_obfs_密'
    config = source()
    config['batch_nodes'] = ('US|TEST_ONLY_PRIVATE_NODE|hy2://' + quote(password, safe='') +
        '@private-hy2.example:443?obfs=gecko&obfs-password=' + quote(obfs, safe=''))
    entry = save(worker.fixed, base, config=config)
    seed(worker, [entry], version=version)
    before = files_before(worker.fixed)
    fingerprint = node_health.extract(worker.fixed._content(entry, 'current.yaml'))[0]['fingerprint']
    prohibit_effects(worker, monkeypatch)
    summary = worker.summary_many([entry])[entry['id']]
    assert summary['status'] == 'healthy' and summary['counts']['healthy'] == 1
    assert files_before(worker.fixed) == before
    public = json.dumps(summary)
    for private in (password, obfs, 'TEST_ONLY_PRIVATE_NODE', 'private-hy2.example',
                    'private-probe.example', fingerprint, entry['token']):
        assert private not in public


def test_one_health_read_and_fixed_before_health_lock_for_many_entries(worker, base, monkeypatch):
    entries = [save(worker.fixed, base, name='One'), save(worker.fixed, base, name='Two')]
    seed(worker, entries)
    active, events, reads = set(), [], dict(fixed=0, health=0, yaml=0)
    fixed_lock, health_lock = worker.fixed._locked, worker._locked
    fixed_read, health_read, content = worker.fixed._read, worker._read, worker.fixed._content

    @contextmanager
    def locked_fixed(*args, **kwargs):
        assert not active
        with fixed_lock(*args, **kwargs):
            active.add('fixed'); events.append('fixed')
            try:
                yield
            finally:
                active.remove('fixed')

    @contextmanager
    def locked_health(*args, **kwargs):
        assert active == {'fixed'} and kwargs['blocking'] is False
        with health_lock(*args, **kwargs):
            active.add('health'); events.append('health')
            try:
                yield
            finally:
                active.remove('health')

    def read_fixed():
        assert active == {'fixed'}
        reads['fixed'] += 1
        return fixed_read()

    def read_health():
        assert active == {'fixed', 'health'}
        reads['health'] += 1
        return health_read()

    def read_content(*args):
        assert 'fixed' in active
        with pytest.raises(LockBusyError):
            with fixed_lock(blocking=False):
                pytest.fail('Selected revision was not locked')
        reads['yaml'] += 1
        return content(*args)

    monkeypatch.setattr(worker.fixed, '_locked', locked_fixed)
    monkeypatch.setattr(worker, '_locked', locked_health)
    monkeypatch.setattr(worker.fixed, '_read', read_fixed)
    monkeypatch.setattr(worker, '_read', read_health)
    monkeypatch.setattr(worker.fixed, '_content', read_content)
    summaries = worker.summary_many(entries)
    assert all(summary['status'] == 'healthy' for summary in summaries.values())
    assert reads == dict(fixed=1, health=1, yaml=2) and events == ['fixed', 'health']


@pytest.mark.parametrize('mutation', ['rename', 'connection', 'delete'])
def test_stale_list_revision_unknown_without_reading_old_or_current_observations(worker, base, monkeypatch, mutation):
    entry = save(worker.fixed, base)
    seed(worker, [entry])
    if mutation == 'delete':
        worker.fixed.action(entry['id'], 'delete')
    else:
        config = source('Renamed')
        if mutation == 'connection':
            config['batch_nodes'] = config['batch_nodes'].replace(':443', ':444')
        save(worker.fixed, base, entry['id'], config=config)
    before = files_before(worker.fixed)
    monkeypatch.setattr(worker, '_read', forbidden)
    monkeypatch.setattr(worker.fixed, '_content', forbidden)
    summary = worker.summary_many([entry])[entry['id']]
    assert summary['status'] == 'unknown' and not any(summary['counts'].values())
    assert files_before(worker.fixed) == before


@pytest.mark.parametrize('rename', [False, True])
def test_current_connection_changes_unknown_but_rename_reuses_matching_records(worker, base, rename):
    entry = save(worker.fixed, base)
    seed(worker, [entry])
    config = source('Renamed')
    if not rename:
        config['batch_nodes'] = config['batch_nodes'].replace(':443', ':444')
    current = save(worker.fixed, base, entry['id'], config=config)
    before = files_before(worker.fixed)
    summary = worker.summary_many([current])[current['id']]
    assert summary['status'] == ('healthy' if rename else 'unknown')
    assert summary['counts']['healthy'] == int(rename)
    assert files_before(worker.fixed) == before


@pytest.mark.parametrize('bad', ['json', 'duplicate', 'permissions', 'symlink', 'fifo',
    'directory', 'read_error', 'lock_permissions', 'lock_symlink', 'lock_fifo'])
def test_auxiliary_unavailable_never_rewrites_or_exposes_private_errors(worker, base, monkeypatch, bad):
    entry = save(worker.fixed, base)
    seed(worker, [entry])
    target = worker.lock if bad.startswith('lock_') else worker.path
    if target.exists():
        target.unlink()
    if bad == 'json':
        target.write_bytes(b'{"PRIVATE_DETAIL')
    elif bad == 'duplicate':
        target.write_bytes(b'{"version":2,"version":2}')
    elif bad in ('permissions', 'lock_permissions'):
        target.write_bytes(b'PRIVATE_DETAIL'); target.chmod(0o644)
    elif bad in ('symlink', 'lock_symlink'):
        target.symlink_to(worker.state / 'PRIVATE_DETAIL_missing')
    elif bad in ('fifo', 'lock_fifo'):
        os.mkfifo(target, 0o600)
    elif bad == 'directory':
        target.mkdir(mode=0o700)
    elif bad == 'read_error':
        seed(worker, [entry])
        module = proxy_health if isinstance(worker, proxy_health.ProxyHealth) else node_health
        def fail(*args, **kwargs):
            raise StateError('PRIVATE_DETAIL')
        monkeypatch.setattr(module, 'read_private_bytes', fail)
    before = files_before(worker.fixed)
    prohibit_effects(worker, monkeypatch)
    summary = worker.summary_many([entry])[entry['id']]
    assert summary['status'] == 'unavailable' and not any(summary['counts'].values())
    assert 'PRIVATE_DETAIL' not in json.dumps(summary)
    assert files_before(worker.fixed) == before


def test_busy_auxiliary_lock_is_unavailable_without_wait_or_reset(worker, base):
    entry = save(worker.fixed, base)
    seed(worker, [entry])
    before = files_before(worker.fixed)
    with file_lock(worker.lock, strict=True):
        assert worker.summary_many([entry])[entry['id']]['status'] == 'unavailable'
    assert files_before(worker.fixed) == before


@pytest.mark.parametrize('broken', ['registry', 'selected_yaml'])
def test_authoritative_fixed_errors_still_fail_closed(worker, base, broken):
    entry = save(worker.fixed, base)
    seed(worker, [entry])
    if broken == 'registry':
        worker.fixed.path.write_bytes(b'PRIVATE_BAD_REGISTRY')
    else:
        (worker.fixed.directory / entry['id'] / entry['revision'] / 'current.yaml').unlink()
    before = files_before(worker.fixed)
    with pytest.raises(StateError):
        worker.summary_many([entry])
    assert files_before(worker.fixed) == before


def test_unmatchable_yaml_reports_unknown_without_private_detail(worker, base):
    entry = save(worker.fixed, base)
    seed(worker, [entry])
    path = worker.fixed.directory / entry['id'] / entry['revision'] / 'current.yaml'
    path.write_bytes(b'proxies: [PRIVATE_YAML_DETAIL')
    before = files_before(worker.fixed)
    summary = worker.summary_many([entry])[entry['id']]
    assert summary['status'] == 'unknown' and not any(summary['counts'].values())
    assert 'PRIVATE_YAML_DETAIL' not in json.dumps(summary)
    assert files_before(worker.fixed) == before
