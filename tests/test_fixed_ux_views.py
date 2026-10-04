"""Fixed list integration: aggregate privacy and observational GETs only."""
import copy
from html.parser import HTMLParser
import io
import json
import socket
import stat
import subprocess

import pytest

from core import (fixed_subscriptions, generator, health_schedule, mihomo_manager,
                  mihomo_probe, node_health, node_probe, proxy_health, source_fetch)
from core.node_identity import fingerprint
from core.state import write_json
from conftest import LINK
from test_external_sources import payload, remote, uploaded
from test_fixed_views import create as create_view
from test_hysteria2_protocol import HY2
from test_parser import vmess
from test_ss_protocol import SS
from test_trojan_protocol import TROJAN


def create(web, client, **fields):
    create_view(web, client, **fields)
    name = fields.get('name', 'My Home Proxy')
    return next(entry for entry in web.fixed_subscriptions.list() if entry['name'] == name)


class Element:
    def __init__(self, tag, attrs):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    @property
    def text(self):
        return ''.join(child.text if isinstance(child, Element) else child
                       for child in self.children)

    def contains_class(self, name):
        return name in self.attrs.get('class', '').split()


class ListHTML(HTMLParser):
    """Inspect actual rendered markup without adding a DOM dependency."""
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
            'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.nodes, self.stack = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        item = Element(tag, attrs)
        self.nodes.append(item)
        if self.stack:
            self.stack[-1].children.append(item)
        if tag not in self.VOID:
            self.stack.append(item)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.stack:
            self.stack[-1].children.append(data)

    def by_class(self, name):
        return [node for node in self.nodes if node.contains_class(name)]

    @property
    def rows(self):
        return [node for node in self.nodes if node.tag == 'tr' and
                'data-name' in node.attrs]


def snapshot(store):
    """Retain bytes, schema/layout, permissions and mtime; locks are coordination.

    Existing file_lock may create/chmod its separate lock inode. Such locks are
    excluded; auxiliary JSON, committed revisions and source cache are not.
    """
    result = {}
    for path in store.state.rglob('*'):
        if path.name.endswith('.lock'):
            continue
        info = path.lstat()
        relative = str(path.relative_to(store.state))
        if path.is_symlink():
            result[relative] = ('symlink', path.readlink(), info.st_mode)
        elif path.is_file():
            result[relative] = (path.read_bytes(), stat.S_IMODE(info.st_mode),
                                info.st_mtime_ns)
        elif path.is_dir():
            result[relative] = ('directory', stat.S_IMODE(info.st_mode))
    return result


def forbid_work(monkeypatch, web):
    """Fail loudly AND count calls, even if a caller catches the exception."""
    calls = []

    def forbid(label):
        def rejected(*args, **kwargs):
            calls.append(label)
            raise AssertionError('Fixed overview performed forbidden work: ' + label)
        return rejected

    for cls in (node_health.NodeHealth, proxy_health.ProxyHealth):
        for method in ('describe', '_prune', '_commit', 'settings', 'check',
                       'run_due'):
            if hasattr(cls, method):
                monkeypatch.setattr(cls, method, forbid(cls.__name__ + '.' + method))
    for method in ('save', '_commit', 'resolve', 'action', 'source_action',
                   'reconcile_health'):
        if hasattr(fixed_subscriptions.FixedSubscriptions, method):
            monkeypatch.setattr(fixed_subscriptions.FixedSubscriptions, method,
                                forbid('FixedSubscriptions.' + method))
    for target, names in (
        (generator, ('generate', 'parse_form_nodes')),
        (source_fetch, ('fetch', '_resolve')),
        (node_probe, ('probe',)),
        (mihomo_probe, ('run',)),
        (mihomo_manager, ('direct_download',)),
        (socket, ('socket', 'create_connection', 'getaddrinfo')),
        (subprocess, ('run', 'Popen')),
    ):
        for name in names:
            monkeypatch.setattr(target, name, forbid(target.__name__ + '.' + name))
    monkeypatch.setattr(mihomo_manager.ManagedMihomo, 'status',
                        forbid('ManagedMihomo.status'))
    monkeypatch.setattr(proxy_health.UnavailableEngine, 'status',
                        forbid('UnavailableEngine.status'))
    return calls


def observation(kind, family):
    values = dict(status=kind, consecutive_failures=0, latency_ms=None,
                  last_checked_at=1_800_000_000, last_success_at=None, error=None)
    if kind == 'healthy':
        values.update(latency_ms=12, last_success_at=values['last_checked_at'])
    elif kind in ('suspect', 'unhealthy'):
        values.update(consecutive_failures=1 if kind == 'suspect' else 3,
                      error='connection_refused' if family == 'endpoint' else 'proxy_failed')
    elif kind == 'unsupported':
        values['error'] = 'unsupported_config'
    elif kind == 'unknown':
        values['last_checked_at'] = None
    return values


def health_state(store, entry, family, *, kind='healthy', mode='manual', stale=False,
                 orphan=False):
    module = node_health if family == 'endpoint' else proxy_health
    value = module.empty_entry()
    health_schedule.configure(value, mode, 900 if mode == 'automatic' else None,
                              1_800_000_000)
    nodes = node_health.extract(store._content(entry, 'current.yaml'), include_config=True)
    fp = fingerprint(dict(nodes[0]['config'], server='old-secret.example')) if stale else nodes[0]['fingerprint']
    value.update(last_check_at=1_800_000_000,
                 nodes={fp: observation(kind, family)})
    data = dict(version=2, subscriptions={entry['id']: value})
    if orphan:
        data['subscriptions']['f' * 32] = copy.deepcopy(value)
    if family == 'proxy':
        data['global'] = dict(proxy_health.DEFAULT_PROBE,
                              url='https://private-probe.example/PRIVATE_PROBE_PATH')
    assert module.valid_state(data)
    path = store.state / ('node_health.json' if family == 'endpoint' else 'proxy_health.json')
    write_json(path, data)
    return path, fp


def overview(client):
    response = client.get('/fixed-subscriptions')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['Referrer-Policy'] == 'no-referrer'
    return response, ListHTML(response.get_data(as_text=True))


def test_empty_list_get_never_creates_registry_or_auxiliary_json(web, logged_in, monkeypatch):
    store = web.fixed_subscriptions
    paths = [store.path, store.state / 'node_health.json', store.state / 'proxy_health.json']
    assert all(not path.exists() for path in paths)
    before = snapshot(store)
    calls = forbid_work(monkeypatch, web)
    for _ in range(2):
        response, dom = overview(logged_in)
        assert b'No fixed subscriptions yet.' in response.data and not dom.rows
    assert snapshot(store) == before and calls == []
    assert all(not path.exists() for path in paths)
    assert not (store.state / 'node_health.lock').exists()
    assert not (store.state / 'proxy_health.lock').exists()


@pytest.mark.parametrize('mode', ['off', 'manual', 'automatic'])
def test_repeated_list_get_preserves_registry_auxiliary_bytes_revisions_and_cache(
        web, logged_in, monkeypatch, mode):
    entry = create(web, logged_in)
    store = web.fixed_subscriptions
    health_state(store, entry, 'endpoint', mode=mode, orphan=True)
    health_state(store, entry, 'proxy', mode=mode, orphan=True)
    before = snapshot(store)
    calls = forbid_work(monkeypatch, web)
    for _ in range(3):
        _, dom = overview(logged_in)
        assert len(dom.rows) == 1
        for selector in ('fixed-endpoint-summary', 'fixed-proxy-summary'):
            text = dom.by_class(selector)[0].text.lower()
            assert mode in text
            assert ('healthy' not in text) if mode == 'off' else ('healthy' in text)
    assert snapshot(store) == before and calls == []
    assert json.loads(store.path.read_bytes())['version'] == 6
    for family in ('node_health.json', 'proxy_health.json'):
        assert json.loads((store.state / family).read_bytes())['version'] == 2


@pytest.mark.parametrize('kind', ['healthy', 'suspect', 'unhealthy', 'unknown'])
def test_endpoint_list_summary_current_fingerprint_is_aggregate_only(
        web, logged_in, monkeypatch, kind):
    entry = create(web, logged_in)
    store = web.fixed_subscriptions
    health_state(store, entry, 'endpoint', kind=kind)
    before = snapshot(store)
    calls = forbid_work(monkeypatch, web)
    _, dom = overview(logged_in)
    shown = dom.by_class('fixed-endpoint-summary')[0].text.lower()
    assert 'endpoint' in shown and 'manual' in shown and kind in shown
    assert 'mystery' not in shown and 'example.com' not in shown
    assert snapshot(store) == before and calls == []


@pytest.mark.parametrize('kind', ['healthy', 'suspect', 'unhealthy', 'unsupported', 'unknown'])
def test_proxy_list_summary_does_not_conflate_unsupported_with_unhealthy(
        web, logged_in, monkeypatch, kind):
    entry = create(web, logged_in)
    store = web.fixed_subscriptions
    health_state(store, entry, 'proxy', kind=kind)
    before = snapshot(store)
    calls = forbid_work(monkeypatch, web)
    _, dom = overview(logged_in)
    shown = dom.by_class('fixed-proxy-summary')[0].text.lower()
    assert 'proxy' in shown and 'manual' in shown and kind in shown
    if kind == 'unsupported':
        assert 'unhealthy' not in shown
    assert snapshot(store) == before and calls == []


@pytest.mark.parametrize('family', ['endpoint', 'proxy'])
def test_stale_healthy_fingerprint_never_labels_current_nodes_healthy(
        web, logged_in, monkeypatch, family):
    entry = create(web, logged_in)
    store = web.fixed_subscriptions
    health_state(store, entry, family, kind='healthy', stale=True)
    before = snapshot(store)
    calls = forbid_work(monkeypatch, web)
    _, dom = overview(logged_in)
    shown = dom.by_class('fixed-' + family + '-summary')[0].text.lower()
    assert 'unknown' in shown and 'healthy' not in shown
    assert snapshot(store) == before and calls == []


@pytest.mark.parametrize('family', ['endpoint', 'proxy'])
@pytest.mark.parametrize('bad', ['corrupt', 'public_mode', 'symlink'])
def test_auxiliary_failures_leave_fixed_overview_available_without_repair(
        web, logged_in, monkeypatch, tmp_path, family, bad):
    entry = create(web, logged_in)
    store = web.fixed_subscriptions
    path, _ = health_state(store, entry, family)
    if bad == 'corrupt':
        path.write_bytes(b'{PRIVATE_AUXILIARY_SECRET')
    elif bad == 'public_mode':
        path.chmod(0o644)
    else:
        target = tmp_path / 'private-outside.json'
        target.write_bytes(path.read_bytes())
        target.chmod(0o600)
        path.unlink()
        path.symlink_to(target)
    before = snapshot(store)
    calls = forbid_work(monkeypatch, web)
    response, dom = overview(logged_in)
    shown = dom.by_class('fixed-' + family + '-summary')[0].text.lower()
    assert 'unavailable' in shown and len(dom.rows) == 1
    assert b'PRIVATE_AUXILIARY_SECRET' not in response.data
    assert snapshot(store) == before and calls == []


@pytest.mark.parametrize('family', ['endpoint', 'proxy'])
def test_unreadable_auxiliary_state_is_unavailable_without_breaking_list(
        web, logged_in, monkeypatch, family):
    entry = create(web, logged_in)
    store = web.fixed_subscriptions
    path, _ = health_state(store, entry, family)
    module = node_health if family == 'endpoint' else proxy_health
    read = module.read_private_bytes

    def unreadable(target, *args):
        if target == path:
            raise PermissionError('PRIVATE_IO_ERROR')
        return read(target, *args)

    monkeypatch.setattr(module, 'read_private_bytes', unreadable)
    before = snapshot(store)
    calls = forbid_work(monkeypatch, web)
    response, dom = overview(logged_in)
    assert 'unavailable' in dom.by_class('fixed-' + family + '-summary')[0].text.lower()
    assert b'PRIVATE_IO_ERROR' not in response.data and len(dom.rows) == 1
    assert snapshot(store) == before and calls == []


@pytest.mark.parametrize('bad', ['malformed', 'unknown_schema'])
def test_broken_authoritative_registry_still_fails_closed_with_broken_auxiliary(
        web, logged_in, monkeypatch, bad):
    create(web, logged_in)
    store = web.fixed_subscriptions
    if bad == 'malformed':
        store.path.write_bytes(b'{PRIVATE_REGISTRY_SECRET')
    else:
        data = json.loads(store.path.read_bytes())
        data['version'] = 99
        write_json(store.path, data)
    (store.state / 'node_health.json').write_bytes(b'{broken')
    (store.state / 'proxy_health.json').write_bytes(b'{broken')
    before = snapshot(store)
    calls = forbid_work(monkeypatch, web)
    response = logged_in.get('/fixed-subscriptions')
    assert response.status_code == 503 and b'PRIVATE_REGISTRY_SECRET' not in response.data
    assert snapshot(store) == before and calls == []


def test_external_source_count_excludes_manual_and_does_not_fetch_or_mutate(
        web, logged_in, monkeypatch):
    manual = create(web, logged_in, name='Manual only', prefix='manual-only')
    monkeypatch.setattr(source_fetch, 'fetch', lambda url: payload('Remote'))
    mixed = create(web, logged_in, name='Mixed sources', prefix='mixed-sources',
                   sources=json.dumps([remote(), uploaded()]),
                   source_file_1=(io.BytesIO(payload('Upload')), 'nodes.txt'))
    store = web.fixed_subscriptions
    assert len(manual['sources']) == 1 and len(mixed['sources']) == 3
    before = snapshot(store)
    calls = forbid_work(monkeypatch, web)
    response, dom = overview(logged_in)
    rows = {row.attrs['data-name']: row for row in dom.rows}
    assert 'External Sources: 0' in rows['Manual only'].text
    assert 'External Sources: 2' in rows['Mixed sources'].text
    assert b'source.example' not in response.data and b'token=PRIVATE' not in response.data
    assert LINK.encode() not in response.data
    assert snapshot(store) == before and calls == []


def test_legacy_registry_list_display_never_writes_a_schema_migration(web, logged_in, monkeypatch):
    entry = create(web, logged_in)
    store = web.fixed_subscriptions
    legacy = json.loads(store.path.read_bytes())
    legacy['version'] = 1
    legacy['subscriptions'][entry['id']].pop('sources')
    write_json(store.path, legacy)
    before = snapshot(store)
    calls = forbid_work(monkeypatch, web)
    _, dom = overview(logged_in)
    assert len(dom.rows) == 1 and 'External Sources: 0' in dom.rows[0].text
    assert snapshot(store) == before and calls == []
    assert json.loads(store.path.read_bytes())['version'] == 1


def test_list_search_metadata_and_health_markup_never_duplicate_secrets(
        web, logged_in, monkeypatch):
    secret_node = 'PRIVATE_NODE_NAME'
    private_link = HY2.replace('example.com', 'secret-endpoint.example')
    name = '<img src=x onerror=alert(1)> Ω Unicode'
    entry = create(web, logged_in, name=name, prefix='public-prefix',
                   batch_nodes='US|' + secret_node + '|' + private_link)
    store = web.fixed_subscriptions
    _, fp = health_state(store, entry, 'endpoint')
    health_state(store, entry, 'proxy')
    before = snapshot(store)
    calls = forbid_work(monkeypatch, web)
    response, dom = overview(logged_in)
    row = dom.rows[0]
    assert row.attrs['data-name'] == name and row.attrs['data-prefix'] == 'public-prefix'
    allowed = {'data-name', 'data-prefix', 'data-status', 'data-node-count', 'data-updated'}
    assert {key for key in row.attrs if key.startswith('data-')} == allowed
    assert row.attrs['data-status'] == 'active' and int(row.attrs['data-node-count']) == 1
    assert float(row.attrs['data-updated']) == entry['updated_at']
    forbidden = ('data-token', 'data-public-url', 'data-source-url', 'data-node-uri',
                 'data-health-node-name')
    assert all(not set(forbidden).intersection(node.attrs) for node in dom.nodes)
    html = response.get_data(as_text=True)
    from test_hysteria2_protocol import PASSWORD, OBFS
    for secret in (secret_node, 'secret-endpoint.example', PASSWORD, PASSWORD.strip(),
                   OBFS, OBFS.strip(), fp, private_link, 'PRIVATE_PROBE_PATH'):
        assert secret not in html
    assert not any(node.tag == 'img' and node.attrs.get('src') == 'x' for node in dom.nodes)
    url_inputs = dom.by_class('fixed-url')
    assert len(url_inputs) == 1 and 'readonly' in url_inputs[0].attrs
    assert url_inputs[0].attrs['value'].endswith('/s/' + store.slug(entry))
    assert html.count(entry['token']) == 1  # only the existing authenticated URL input
    for node in dom.nodes:
        if node is not url_inputs[0]:
            assert all(entry['token'] not in (value or '') for value in node.attrs.values())
    assert snapshot(store) == before and calls == []


@pytest.mark.parametrize('protocol,link', [
    ('vmess', vmess()), ('vless', LINK), ('trojan', TROJAN), ('ss', SS), ('hysteria2', HY2),
])
def test_each_fixed_protocol_yaml_and_public_url_survive_overview_get_exactly(
        web, logged_in, monkeypatch, protocol, link):
    entry = create(web, logged_in, name=protocol, prefix=protocol,
                   batch_nodes='US|Representative|' + link)
    store = web.fixed_subscriptions
    old_yaml = store._content(entry, 'current.yaml')
    old_slug = store.slug(entry)
    before = snapshot(store)
    calls = forbid_work(monkeypatch, web)
    response, dom = overview(logged_in)
    assert len(dom.rows) == 1 and old_slug.encode() in response.data
    assert store._content(entry, 'current.yaml') == old_yaml
    assert store.slug(store.get(entry['id'])) == old_slug
    assert snapshot(store) == before and calls == []


def test_without_javascript_all_subscriptions_and_authenticated_post_forms_render(web, logged_in):
    first = create(web, logged_in, name='Alpha Active', prefix='alpha')
    second = create(web, logged_in, name='Beta Disabled', prefix='beta')
    web.fixed_subscriptions.action(second['id'], 'disable')
    original_order = [entry['name'] for entry in web.fixed_subscriptions.list()]
    _, dom = overview(logged_in)  # Flask client executes no JavaScript.
    assert {row.attrs['data-name'] for row in dom.rows} == {'Alpha Active', 'Beta Disabled'}
    assert [row.attrs['data-name'] for row in dom.rows] == original_order
    assert all('hidden' not in row.attrs for row in dom.rows)
    for entry, toggle in ((first, 'disable'), (second, 'enable')):
        for action in (toggle, 'regenerate', 'delete'):
            target = '/fixed-subscriptions/' + entry['id'] + '/' + action
            form = next(node for node in dom.nodes if node.tag == 'form' and
                        node.attrs.get('action') == target)
            assert form.attrs['method'].lower() == 'post'
            assert any(isinstance(child, Element) and child.tag == 'input' and
                       child.attrs.get('name') == 'csrf_token' and child.attrs.get('value')
                       for child in form.children)
            if action == 'regenerate':
                assert form.attrs['data-confirm'] == 'This will invalidate the old subscription URL.'
            elif action == 'delete':
                assert form.attrs['data-confirm'] == 'Delete this fixed subscription? Its URL will stop working permanently.'
        edit = '/fixed-subscriptions/' + entry['id'] + '/edit'
        assert any(node.tag == 'a' and node.attrs.get('href') == edit for node in dom.nodes)
