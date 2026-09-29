"""Fixed-clock scheduling, real atomic revisions, and cross-process worker safety."""
import copy
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import patch

import pytest

from core import auto_refresh, fixed_subscriptions as fixed, refresh_schedule as schedule, source_fetch
from core.source_errors import SourceError
from core.state import StateError, write_json
from conftest import LINK, ROOT, post
from test_fixed_subscriptions import BASE, base, parsed, save, source, store
from test_external_sources import external_save, payload, remote, response, uploaded


@pytest.fixture
def clock():
    class Clock:
        now = 1_800_000_000
        def __call__(self): return self.now
    return Clock()


def scheduled(store, base, clock, **changes):
    return external_save(store, base, sources=[remote(refresh_interval_seconds=900, **changes)], clock=clock)


@pytest.mark.parametrize('interval', schedule.INTERVALS)
def test_each_interval_due_success_same_public_url(store, base, response, clock, interval):
    entry = external_save(store, base, sources=[remote(refresh_interval_seconds=interval)], clock=clock)
    item = entry['sources'][1]; slug = store.slug(entry)
    assert item['next_refresh_at'] == clock.now + interval and item['last_trigger'] == 'save'
    before = store.path.read_bytes(); response['calls'].clear()
    clock.now += interval - 1
    assert auto_refresh.run_once(store, base, clock) == 0
    assert response['calls'] == [] and store.path.read_bytes() == before
    clock.now += 1; response['payload'] = payload('London auto')
    assert auto_refresh.run_once(store, base, clock) == 0
    new = store.get(entry['id']); item = new['sources'][1]
    assert response['calls'] == [item['url']] and new['revision'] != entry['revision']
    assert store.slug(new) == slug and b'London auto' in store.resolve(slug)
    assert item['next_refresh_at'] == clock.now + interval
    assert item['last_attempt_at'] == item['last_success_at'] == clock.now
    assert item['last_error'] is None and not item['using_cache'] and item['consecutive_failures'] == 0
    assert item['refresh_history'][-1] == dict(at=clock.now, trigger='auto', result='success', node_count=1, error=None)


@pytest.mark.parametrize('skip', ['off', 'subscription', 'source', 'not-due', 'manual-uploaded'])
def test_scan_skips_without_network_or_registry_write(store, base, response, clock, skip):
    if skip == 'manual-uploaded':
        entry = external_save(store, base, sources=[uploaded()], uploads={0:payload('Berlin uploaded')}, clock=clock)
    elif skip == 'off': entry = external_save(store, base, sources=[remote()], clock=clock)
    else:
        entry = scheduled(store, base, clock)
        if skip == 'subscription': store.action(entry['id'], 'disable')
        if skip == 'source': store.source_action(entry['id'], 'disable', base, entry['sources'][1]['id'], clock=clock)
    if skip != 'not-due': clock.now += 100000
    before = store.path.read_bytes(); response['calls'].clear()
    assert auto_refresh.run_once(store, base, clock) == 0
    assert response['calls'] == [] and store.path.read_bytes() == before


def test_fixed_backoff_recovery_manual_reschedule_and_off(store, base, response, clock, caplog):
    caplog.set_level(logging.INFO)
    entry = external_save(store, base, sources=[remote(refresh_interval_seconds=86400)], clock=clock)
    slug = store.slug(entry); good = store.resolve(slug); old_payload = store._payload(entry, entry['sources'][1]['id'])
    response['error'] = 'http_500'
    for count, delay in enumerate((300, 900, 1800, 3600, 7200, 21600, 21600), 1):
        clock.now = store.get(entry['id'])['sources'][1]['next_refresh_at']
        assert auto_refresh.run_once(store, base, clock) == 0
        new = store.get(entry['id']); item = new['sources'][1]
        assert item['consecutive_failures'] == count and item['next_refresh_at'] == clock.now + delay
        assert item['using_cache'] and item['last_success_at'] == entry['sources'][1]['last_success_at']
        assert item['refresh_history'][-1]['result'] == 'cached'
        assert store.resolve(slug) == good and store._payload(new, item['id']) == old_payload
    response.pop('error'); response['payload'] = payload('London recovered')
    clock.now += 20  # Manual refresh works while backoff is still in the future.
    new = store.source_action(entry['id'], 'refresh', base, item['id'], clock=clock)
    item = new['sources'][1]
    assert not item['using_cache'] and item['consecutive_failures'] == 0
    assert item['next_refresh_at'] == clock.now + 86400 and item['last_trigger'] == 'manual'
    assert b'London recovered' in store.resolve(slug)
    clock.now = item['next_refresh_at']; auto_refresh.run_once(store, base, clock)
    new = store.get(entry['id']); requested = copy.deepcopy(new['sources'][1:])
    requested[0]['refresh_interval_seconds'] = 3600
    new = external_save(store, base, new, sources=requested, clock=clock)
    assert new['sources'][1]['next_refresh_at'] == clock.now + 3600
    history = new['sources'][1]['refresh_history']
    requested = copy.deepcopy(new['sources'][1:]); requested[0]['refresh_interval_seconds'] = None
    new = external_save(store, base, new, sources=requested, clock=clock)
    assert new['sources'][1]['next_refresh_at'] is None and new['sources'][1]['consecutive_failures'] == 0
    assert new['sources'][1]['refresh_history'][:-1] == history
    for secret in (entry['token'], entry['sources'][1]['url'], 'PRIVATE', LINK,
                   '11111111-1111-4111-8111-111111111111', 'vmess://', 'vless://'):
        assert secret not in caplog.text and secret not in json.dumps(new['sources'][1]['refresh_history'])


def test_auto_provider_recovery_restores_normal_interval(store, base, response, clock):
    entry = scheduled(store, base, clock); clock.now += 900
    response['payload'] = b'invalid PRIVATE response'
    auto_refresh.run_once(store, base, clock)
    failed = store.get(entry['id'])['sources'][1]
    assert failed['using_cache'] and failed['next_refresh_at'] == clock.now + 300
    response['payload'] = payload('Tokyo recovered'); clock.now += 300
    auto_refresh.run_once(store, base, clock)
    new = store.get(entry['id']); item = new['sources'][1]
    assert store.slug(new) == store.slug(entry) and b'Tokyo recovered' in store.resolve(store.slug(entry))
    assert item['consecutive_failures'] == 0 and item['next_refresh_at'] == clock.now + 900
    assert not item['using_cache'] and item['last_error'] is None


def test_history_is_bounded_and_displayed_five_records(store, base, response, clock):
    entry = scheduled(store, base, clock)
    for _ in range(24):
        clock.now += 900; auto_refresh.run_once(store, base, clock)
    history = store.get(entry['id'])['sources'][1]['refresh_history']
    assert len(history) == 20 and history[0]['at'] == 1_800_004_500
    assert all(set(r) == {'at', 'trigger', 'result', 'node_count', 'error'} for r in history)


@pytest.mark.parametrize('bad', [1, 0, -900, 3601, '3600', True, 900.0, {}, []])
def test_interval_rejects_arbitrary_or_wrong_type(store, base, response, bad):
    with pytest.raises(SourceError): external_save(store, base, sources=[remote(refresh_interval_seconds=bad)])
    assert store.list() == []


@pytest.mark.parametrize('version', [1, 2])
def test_old_schema_scan_and_public_stats_preserve_version_bytes_identity(store, base, response, clock, version):
    entry = (save(store, base) if version == 1 else external_save(store, base, sources=[remote()]))
    data = json.loads(store.path.read_bytes()); data['version'] = version
    if version == 1: data['subscriptions'][entry['id']].pop('sources')
    else:
        for item in data['subscriptions'][entry['id']]['sources']:
            for field in schedule.FIELDS: item.pop(field, None)
    write_json(store.path, data); before = store.path.read_bytes()
    output = store._content(entry, 'current.yaml'); response['calls'].clear()
    normalized = store.get(entry['id'])
    assert normalized['revision'] == entry['revision'] and store.slug(normalized) == store.slug(entry)
    if version == 2:
        assert normalized['sources'][1]['refresh_interval_seconds'] is None
        assert store._payload(normalized, normalized['sources'][1]['id']) == payload('Tokyo-remote')
    assert auto_refresh.run_once(store, base, clock) == 0
    assert store.path.read_bytes() == before and response['calls'] == []
    assert store.resolve(store.slug(entry)) == output
    disk = json.loads(store.path.read_bytes()); assert disk['version'] == version
    if version == 2: assert not set(schedule.FIELDS) & set(disk['subscriptions'][entry['id']]['sources'][1])
    store.action(entry['id'], 'disable')
    assert json.loads(store.path.read_bytes())['version'] == 3
    new = store.get(entry['id']); assert new['revision'] == entry['revision'] and new['token'] == entry['token']


@pytest.mark.parametrize('field,value', [('refresh_interval_seconds', 301), ('next_refresh_at', -1),
    ('next_refresh_at', float('nan')), ('consecutive_failures', True), ('consecutive_failures', -1),
    ('last_trigger', 'PRIVATE'), ('refresh_history', [{'at':0,'trigger':'auto','result':'success','node_count':1,'error':'PRIVATE'}]),
    ('refresh_history', [dict(at=0,trigger='auto',result='success',node_count=1,error=None)] * 21)])
def test_corrupt_v3_fails_closed_without_reset(store, base, response, clock, field, value):
    entry = scheduled(store, base, clock); data = json.loads(store.path.read_bytes())
    data['subscriptions'][entry['id']]['sources'][1][field] = value
    write_json(store.path, data); before = store.path.read_bytes()
    with pytest.raises(StateError): auto_refresh.run_once(store, base, clock)
    assert store.path.read_bytes() == before


def test_group_fetches_only_due_once_and_preserves_other_sources(store, base, clock, monkeypatch):
    calls = []
    def fetch(url): calls.append(url); return payload('Tokyo ' + url.rsplit('/',1)[-1])
    monkeypatch.setattr(source_fetch, 'fetch', fetch)
    entry = external_save(store, base, sources=[remote('A',url='https://source.example/a',refresh_interval_seconds=900),
        remote('B',url='https://source.example/b',refresh_interval_seconds=900),
        remote('C',url='https://source.example/c',refresh_interval_seconds=3600), uploaded()],
        uploads={3:payload('Berlin upload')}, clock=clock)
    old_c = copy.deepcopy(entry['sources'][3]); calls.clear(); clock.now += 900
    original = fixed.generator.generate
    with patch.object(fixed.generator, 'generate', wraps=original) as generate:
        auto_refresh.run_once(store, base, clock)
    assert generate.call_count == 1 and calls == ['https://source.example/a', 'https://source.example/b']
    new = store.get(entry['id']); assert new['sources'][3] == old_c
    assert new['sources'][0]['node_count'] == 1 and new['sources'][4]['node_count'] == 1
    assert b'Berlin upload' in store.resolve(store.slug(entry))


def work_entry(key, count, at):
    return dict(id=str(key), status='active', sources=[dict(id=f'{key}-{i}',type='remote_url', enabled=True,
        refresh_interval_seconds=900,next_refresh_at=at) for i in range(count)])


@pytest.mark.parametrize('counts,expected', [([10,10,12,1], [0,1,2]), ([20,20,1],[0]),
    ([33,1],[0]), ([1,33],[0]), ([32,1],[0]), ([1,1,1],[0,1,2])])
def test_work_limit_oldest_first_unsplit_groups(counts, expected):
    entries = [work_entry(i, count, i) for i, count in enumerate(counts)]
    selected = auto_refresh.select_work(list(reversed(entries)), 100)
    assert [int(e['id']) for e, _ in selected] == expected
    assert all(len(ids) == counts[int(e['id'])] for e, ids in selected)


def test_oversized_subscription_refreshes_all_63_together(store, base, clock, monkeypatch):
    calls = []
    def fetch(url): calls.append(url); return payload('Tokyo ' + url.rsplit('/',1)[-1])
    monkeypatch.setattr(source_fetch, 'fetch', fetch)
    sources = [remote(str(i),url=f'https://source.example/{i}',refresh_interval_seconds=900) for i in range(63)]
    entry = external_save(store, base, sources=sources, clock=clock); calls.clear(); clock.now += 900
    auto_refresh.run_once(store, base, clock)
    assert len(calls) == 63 and store.get(entry['id'])['node_count'] == 64


def test_real_scan_leaves_over_budget_source_metadata_and_revision_untouched(store, base, response, clock):
    entries = []
    for _ in range(33):
        entries.append(scheduled(store, base, clock)); clock.now += 1
    response['calls'].clear(); clock.now += 900
    expected = copy.deepcopy(entries[-1])
    assert auto_refresh.run_once(store, base, clock) == 0
    assert len(response['calls']) == 32 and store.get(expected['id']) == expected
    response['calls'].clear()
    assert auto_refresh.run_once(store, base, clock) == 0
    assert len(response['calls']) == 1 and store.get(expected['id'])['revision'] != expected['revision']


def test_no_cache_failure_keeps_output_and_isolates_other_subscriptions(store, base, response, clock):
    entries = [scheduled(store, base, clock) for _ in range(3)]
    first = entries[0]; data = json.loads(store.path.read_bytes())
    data['subscriptions'][first['id']]['sources'][1].update(last_success_at=None,next_refresh_at=clock.now)
    write_json(store.path, data); old = store._content(first, 'current.yaml')
    for entry in entries[1:]:
        data['subscriptions'][entry['id']]['sources'][1]['next_refresh_at'] = clock.now + 1
    write_json(store.path, data); clock.now += 1
    calls = []
    def fetch(url):
        calls.append(url)
        if len(calls) == 1: raise SourceError('connection')
        return payload('London good')
    with patch.object(source_fetch, 'fetch', fetch): assert auto_refresh.run_once(store, base, clock) == 0
    assert len(calls) == 3 and store._content(store.get(first['id']), 'current.yaml') == old
    item = store.get(first['id'])['sources'][1]
    assert item['consecutive_failures'] == 1 and item['refresh_history'][-1]['result'] == 'error'
    assert item['next_refresh_at'] == clock.now + 300
    for entry in entries[1:]: assert b'London good' in store.resolve(store.slug(entry))


@pytest.mark.parametrize('mutation', ['read','edit','disable','regenerate','delete','source-disable'])
def test_auto_fetch_outside_lock_discards_stale_candidate(store, base, response, clock, monkeypatch, mutation, caplog):
    caplog.set_level(logging.INFO)
    entry = scheduled(store, base, clock); slug = store.slug(entry); old = store.resolve(slug)
    clock.now += 900; started = threading.Event(); resume = threading.Event(); outcomes = []
    def fetch(url): started.set(); assert resume.wait(5); return payload('Tokyo stale')
    monkeypatch.setattr(source_fetch, 'fetch', fetch)
    def run():
        try: outcomes.append(auto_refresh.run_once(store, base, clock))
        except BaseException as error: outcomes.append(error)
    worker = threading.Thread(target=run); worker.start(); assert started.wait(3)
    completed = threading.Event(); errors = []
    def request():
        try:
            assert store.resolve(slug) == old
            if mutation == 'edit':
                config = source('Concurrent edit')
                store.save(entry['id'], entry['name'], entry['prefix'], config, parsed(config), base,
                           sources=entry['sources'][1:], refresh=set(), clock=clock)
            elif mutation == 'source-disable':
                store.source_action(entry['id'], 'disable', base, entry['sources'][1]['id'], clock=clock)
            elif mutation != 'read': store.action(entry['id'], mutation)
        except BaseException as error: errors.append(error)
        finally: completed.set()
    other = threading.Thread(target=request); other.start()
    try: assert completed.wait(2), 'registry held during network'
    finally: resume.set(); worker.join(5); other.join(5)
    assert outcomes == [0] and not errors and not list(store.state.glob('.fixed-candidate-*'))
    if mutation == 'read': assert b'Tokyo stale' in store.resolve(slug)
    else:
        assert 'result=conflict' in caplog.text
        if mutation == 'edit': assert b'Concurrent edit' in store.resolve(slug) and b'Tokyo stale' not in store.resolve(slug)
        elif mutation == 'source-disable': assert b'Tokyo stale' not in store.resolve(slug)
        else: assert store.resolve(slug) is None


@pytest.mark.parametrize('mode', ['before', 'after'])
def test_auto_atomic_commit_failure_preserves_revision_and_cache(store, base, response, clock, monkeypatch, mode):
    entry = scheduled(store, base, clock); clock.now += 900
    before = store.path.read_bytes(); original = fixed.write_json
    def fail(path, value):
        if mode == 'after': original(path, value)
        raise OSError('PRIVATE disk secret')
    with monkeypatch.context() as injection:
        injection.setattr(fixed, 'write_json', fail)
        with pytest.raises(StateError): auto_refresh.run_once(store, base, clock)
    assert store.path.read_bytes() == before and b'Tokyo-remote' in store.resolve(store.slug(entry))
    assert not list(store.state.glob('.fixed-candidate-*'))


def test_generation_failure_records_safe_backoff_without_new_revision(store, base, response, clock, monkeypatch):
    entry = scheduled(store, base, clock); clock.now += 900
    monkeypatch.setattr(fixed.generator, 'generate', lambda *a:dict(success=False))
    assert auto_refresh.run_once(store, base, clock) == 0
    new = store.get(entry['id']); item = new['sources'][1]
    assert new['revision'] == entry['revision'] and item['last_error'] == 'generation'
    assert item['refresh_history'][-1]['result'] == 'error' and item['next_refresh_at'] == clock.now + 300


def test_disabled_subscription_and_source_reenable_scheduling(store, base, response, clock):
    entry = scheduled(store, base, clock); identifier = entry['sources'][1]['id']
    store.action(entry['id'], 'disable'); clock.now += 901
    auto_refresh.run_once(store, base, clock); assert len(response['calls']) == 1
    store.action(entry['id'], 'enable'); auto_refresh.run_once(store, base, clock)
    assert len(response['calls']) == 2
    disabled = store.source_action(entry['id'], 'disable', base, identifier, clock=clock)
    before = disabled['sources'][1]['next_refresh_at']; clock.now += 1000
    auto_refresh.run_once(store, base, clock); assert len(response['calls']) == 2
    new = store.source_action(entry['id'], 'enable', base, identifier, clock=clock)
    assert len(response['calls']) == 3 and new['sources'][1]['next_refresh_at'] == clock.now + 900 > before


def test_clock_backwards_is_safe_and_no_work(store, base, response, clock):
    scheduled(store, base, clock); clock.now -= 300
    auto_refresh.run_once(store, base, clock); assert len(response['calls']) == 1


@pytest.mark.parametrize('bad', ['registry', 'schema', 'state-mode', 'directory-mode', 'auto-lock-mode',
    'registry-lock-mode', 'auto-lock-symlink', 'auto-lock-fifo', 'directory-symlink'])
def test_cli_critical_state_returns_nonzero_sanitized(store, base, response, clock, bad, caplog, tmp_path):
    scheduled(store, base, clock)
    if bad == 'registry': store.path.write_text('PRIVATE invalid json')
    if bad == 'schema': write_json(store.path, dict(version=99, PRIVATE='https://secret/?token=PRIVATE'))
    if bad == 'state-mode': store.state.chmod(0o755)
    if bad == 'directory-mode': store.directory.chmod(0o755)
    if bad.endswith('lock-mode'):
        path = store.state / ('auto_refresh.lock' if bad == 'auto-lock-mode' else 'fixed_subscriptions.lock')
        path.touch(); path.chmod(0o644)
    if bad == 'auto-lock-symlink': (store.state/'auto_refresh.lock').symlink_to(base)
    if bad == 'auto-lock-fifo': os.mkfifo(store.state/'auto_refresh.lock', 0o600)
    if bad == 'directory-symlink':
        store.directory.rename(tmp_path/'old'); store.directory.symlink_to(tmp_path/'old')
    before = store.path.read_bytes()
    assert auto_refresh.main(['--once','--state-dir',str(store.state),'--default-yaml',str(base)]) == 1
    assert store.path.read_bytes() == before and 'PRIVATE' not in caplog.text and 'Traceback' not in caplog.text
    assert 'critical state error' in caplog.text


def test_cli_empty_scan_independent_of_flask(tmp_path):
    state = tmp_path/'state'
    command = [sys.executable, '-c', 'import sys; from core.auto_refresh import main; '
               'result=main(sys.argv[1:]); assert "app" not in sys.modules and "flask" not in sys.modules; '
               'raise SystemExit(result)', '--once', '--state-dir', str(state)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert not (state/'fixed_subscriptions.json').exists()


def test_two_cli_processes_singleton_only_one_fetch(store, base, response, clock, tmp_path):
    entry = scheduled(store, base, clock)
    data = json.loads(store.path.read_bytes()); data['subscriptions'][entry['id']]['sources'][1]['next_refresh_at'] = 0
    write_json(store.path, data)
    marker, release = tmp_path/'started', tmp_path/'release'
    script = '''import pathlib, sys, time, runpy
from core import source_fetch
marker, release = map(pathlib.Path, sys.argv[1:3])
def fetch(url):
    with marker.open('a') as out: out.write('fetch\\n')
    deadline = time.monotonic()+8
    while not release.exists():
        if time.monotonic() > deadline: raise RuntimeError('test timeout')
        time.sleep(.01)
    return %r
source_fetch.fetch=fetch
sys.argv=['core.auto_refresh','--once','--state-dir',sys.argv[3],'--default-yaml',sys.argv[4]]
runpy.run_module('core.auto_refresh',run_name='__main__')
''' % payload('Tokyo process')
    command = [sys.executable, '-c', script, str(marker), str(release), str(store.state), str(base)]
    first = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic()+5
        while not marker.exists() and time.monotonic()<deadline: time.sleep(.01)
        assert marker.exists()
        second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=3)
        assert second.returncode == 0 and 'already running' in second.stderr
        assert marker.read_text() == 'fetch\n'
    finally:
        release.touch(); stdout, stderr = first.communicate(timeout=10)
    assert first.returncode == 0, stdout+stderr
    assert b'Tokyo process' in store.resolve(store.slug(entry))


def test_web_schedule_history_and_auto_failure_public_200(web, logged_in, response, clock):
    config = dict(name='Auto',yaml_source='custom',yaml_file=(io.BytesIO(BASE),'base.yaml'),batch_nodes='',
                  sources=json.dumps([remote(refresh_interval_seconds=3600), uploaded()]),
                  source_file_1=(io.BytesIO(payload('Berlin uploaded')),'office.yaml'))
    assert post(logged_in, '/fixed-subscriptions/new', config).status_code == 303
    store = web.fixed_subscriptions; entry = store.list()[0]; slug = store.slug(entry)
    public = '/s/'+slug; assert web.app.test_client().get(public).status_code == 200
    for _ in range(7): store.source_action(entry['id'],'refresh',web.DEFAULT_YAML_PATH,entry['sources'][1]['id'],clock=clock)
    page = logged_in.get(f'/fixed-subscriptions/{entry["id"]}/edit')
    assert page.data.split(b'<template')[0].count(b'class="source-refresh-interval ') == 1
    assert page.data.count(b'\xc2\xb7 MANUAL \xc2\xb7 SUCCESS') == 5
    assert b'Next Refresh:' in page.data and b'Consecutive Failures: 0' in page.data
    clock.now += 3600; response['error'] = 'http_500'
    assert auto_refresh.run_once(store, web.DEFAULT_YAML_PATH, clock) == 0
    assert web.app.test_client().get(public).status_code == 200
    assert web.app.test_client().get('/healthz').status_code == 200
    page = logged_in.get(f'/fixed-subscriptions/{entry["id"]}/edit')
    assert b'Cached' in page.data and b'AUTO' in page.data and b'Consecutive Failures: 1' in page.data
