"""Real list GETs racing private state writers, with event-controlled interleavings."""
from contextlib import contextmanager
import json
import threading

import pytest

from core import health_schedule, node_health, proxy_health
from test_fixed_ux_views import create, health_state, ListHTML, snapshot


def observer(store, family):
    kind = node_health.NodeHealth if family == 'endpoint' else proxy_health.ProxyHealth
    return kind(store, clock=lambda: 1_800_000_000)


def start_thread(name, action, errors):
    def run():
        try:
            action()
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(name=name, target=run, daemon=True)
    thread.start()
    return thread


@pytest.mark.parametrize('family', ['endpoint', 'proxy'])
def test_list_snapshot_serializes_subscription_and_health_mutation(
        web, logged_in, monkeypatch, family):
    entry = create(web, logged_in)
    store = web.fixed_subscriptions
    health_state(store, entry, family)
    worker = observer(store, family)
    selected, resume = threading.Event(), threading.Event()
    attempting = {name: threading.Event() for name in ('mutation', 'health-update')}
    finished = {name: threading.Event() for name in attempting}
    errors, responses, threads = [], [], []
    original_lock, original_content = store._locked, store._content

    @contextmanager
    def tracked_lock(*args, **kwargs):
        name = threading.current_thread().name
        if name in attempting:
            attempting[name].set()
        with original_lock(*args, **kwargs):
            yield

    def held_content(*args):
        content = original_content(*args)
        if threading.current_thread().name == 'overview':
            selected.set()
            assert resume.wait(10), 'List snapshot was not released'
        return content

    def mutate():
        store.action(entry['id'], 'disable')
        finished['mutation'].set()

    def update():
        if family == 'proxy':
            worker.settings(entry['id'], 'off', True)
        else:
            worker.settings(entry['id'], 'off')
        finished['health-update'].set()

    monkeypatch.setattr(store, '_locked', tracked_lock)
    monkeypatch.setattr(store, '_content', held_content)
    threads.append(start_thread('overview', lambda: responses.append(
        logged_in.get('/fixed-subscriptions')), errors))
    try:
        assert selected.wait(10), 'List never selected its committed YAML'
        threads.append(start_thread('mutation', mutate, errors))
        threads.append(start_thread('health-update', update, errors))
        assert all(event.wait(10) for event in attempting.values())
        assert not any(event.is_set() for event in finished.values()), (
            'A writer crossed the Fixed lock while the list consumed its revision')
    finally:
        resume.set()
        for thread in threads:
            thread.join(10)
    assert not any(thread.is_alive() for thread in threads), 'List/writer deadlock'
    assert not errors
    assert all(event.is_set() for event in finished.values())
    assert len(responses) == 1 and responses[0].status_code == 200
    rows = ListHTML(responses[0].get_data(as_text=True))
    assert '1 healthy' in rows.by_class('fixed-' + family + '-summary')[0].text
    assert store.get(entry['id'])['status'] == 'disabled'
    assert json.loads(worker.path.read_bytes())['subscriptions'][entry['id']]['mode'] == 'off'
    refreshed = logged_in.get('/fixed-subscriptions')
    assert refreshed.status_code == 200
    dom = ListHTML(refreshed.get_data(as_text=True))
    assert dom.rows[0].attrs['data-status'] == 'disabled'
    assert dom.by_class('fixed-' + family + '-summary')[0].text.strip() == family.capitalize() + 'Off'


@pytest.mark.parametrize('family', ['endpoint', 'proxy'])
def test_busy_health_writer_does_not_hold_list_or_fixed_mutation(
        web, logged_in, family):
    entry = create(web, logged_in)
    store = web.fixed_subscriptions
    health_state(store, entry, family)
    worker = observer(store, family)
    held, release, completed = threading.Event(), threading.Event(), threading.Event()
    errors, responses, threads = [], [], []

    def update():
        lock = worker._locked(worker.lock) if family == 'proxy' else worker._locked()
        with lock:
            data, previous = worker._read()
            held.set()
            assert release.wait(10), 'Health writer was not released'
            health_schedule.configure(data['subscriptions'][entry['id']], 'off', None,
                                      1_800_000_000)
            worker._commit(data, previous)

    def overview():
        responses.append(logged_in.get('/fixed-subscriptions'))
        completed.set()

    threads.append(start_thread('health-writer', update, errors))
    try:
        assert held.wait(10)
        before = snapshot(store)
        threads.append(start_thread('overview', overview, errors))
        assert completed.wait(10), 'List waited on the busy Health lock'
        assert responses[0].status_code == 200
        dom = ListHTML(responses[0].get_data(as_text=True))
        assert 'Unavailable' in dom.by_class('fixed-' + family + '-summary')[0].text
        assert snapshot(store) == before, 'Busy list GET wrote business state'
        # The writer still owns Health; the completed list must have released Fixed.
        with store._locked(blocking=False):
            assert store._read()['subscriptions'][entry['id']]['status'] == 'active'
        store.action(entry['id'], 'disable')
        assert store.get(entry['id'])['status'] == 'disabled'
    finally:
        release.set()
        for thread in threads:
            thread.join(10)
    assert not any(thread.is_alive() for thread in threads), 'Busy list/writer deadlock'
    assert not errors
    assert json.loads(worker.path.read_bytes())['subscriptions'][entry['id']]['mode'] == 'off'
