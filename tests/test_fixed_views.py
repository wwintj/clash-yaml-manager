import io
import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from core.state import write_json
from conftest import LINK, post

BASE = b'proxies: []\nproxy-groups: []\nrules:\n  - MATCH,DIRECT\n'


def create(web, client, **extra):
    data = dict(name='My Home Proxy', prefix='', yaml_source='custom',
                batch_nodes='UNKNOWN|Mystery|' + LINK, yaml_file=(io.BytesIO(BASE), 'base.yaml'))
    data.update(extra)
    response = post(client, '/fixed-subscriptions/new', data)
    assert response.status_code == 303
    return web.fixed_subscriptions.list()[0]


def test_full_crud_and_server_restoration(web, logged_in):
    assert b'No fixed subscriptions yet.' in logged_in.get('/fixed-subscriptions').data
    entry = create(web, logged_in, aux_nodes=json.dumps([dict(country='JP', name='Tokyo', link=LINK)]),
                   special_groups=['🎥 奈飞节点'])
    store = web.fixed_subscriptions; url = '/s/' + store.slug(entry)
    anonymous = web.app.test_client()
    response = anonymous.get(url)
    assert response.status_code == 200 and '其他节点'.encode() in response.data
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['Referrer-Policy'] == 'no-referrer'
    assert response.headers['Content-Type'].startswith('application/x-yaml')
    assert 'attachment' in anonymous.get(url + '?download=1').headers['Content-Disposition']
    page = logged_in.get('/fixed-subscriptions/' + entry['id'] + '/edit')
    assert b'Current custom YAML: saved' in page.data and b'draft.js' not in page.data
    assert b'Tokyo' in page.data and b'Mystery' in page.data
    assert page.headers['Cache-Control'] == 'no-store'
    edit = dict(name='New Name', prefix=entry['prefix'], yaml_source='custom', batch_nodes='US|Changed|' + LINK)
    assert post(logged_in, '/fixed-subscriptions/' + entry['id'] + '/edit', edit).status_code == 303
    assert b'Changed' in anonymous.get(url).data
    assert store.get(entry['id'])['token'] == entry['token']
    for action, status in [('disable',404),('enable',200)]:
        assert post(logged_in, f'/fixed-subscriptions/{entry["id"]}/{action}').status_code == 303
        assert anonymous.get(url).status_code == status
    assert post(logged_in, f'/fixed-subscriptions/{entry["id"]}/regenerate').status_code == 303
    new_url = '/s/' + store.slug(store.get(entry['id']))
    assert anonymous.get(url).status_code == 404 and anonymous.get(new_url).status_code == 200
    assert post(logged_in, f'/fixed-subscriptions/{entry["id"]}/delete').status_code == 303
    assert anonymous.get(new_url).status_code == 404
    assert b'Fixed subscription deleted.' in logged_in.get('/fixed-subscriptions').data


def test_fixed_v2_legacy_and_temporary_coexist(web, logged_in):
    entry = create(web, logged_in)
    legacy = Path(web.DIR_OUTPUTS) / 'tim_20260928_1.yaml'; legacy.write_bytes(BASE)
    current = Path(web.yaml_utils.save_new_output({'proxies':[],'rules':[]}, web.DIR_OUTPUTS))
    short, _ = web.temporary_links.create(current.name)
    for path in ['/s/' + web.fixed_subscriptions.slug(entry), '/s/' + web.build_short_subscription_slug(current.name),
                 '/s/' + web.build_short_subscription_slug(legacy.name),
                 '/s/' + legacy.stem + '-' + web.generate_download_token(legacy.name)[:8], '/t/' + short]:
        assert web.app.test_client().get(path).status_code == 200
    # Current output deletion and retention cannot reach state-backed subscriptions.
    web.safe_delete_file(web.DIR_OUTPUTS, current.name)
    assert web.app.test_client().get('/s/' + web.fixed_subscriptions.slug(entry)).status_code == 200


def test_default_fixed_survives_output_retention_with_base_snapshot(web, logged_in):
    response = post(logged_in, '/fixed-subscriptions/new',
                    dict(name='Default source', prefix='default-source', yaml_source='default', batch_nodes='US|Default|' + LINK))
    assert response.status_code == 303
    entry = web.fixed_subscriptions.list()[0]
    assert entry['rule_count'] == 10410
    files = web.fixed_subscriptions.directory / entry['id'] / entry['revision']
    assert (files / 'base.yaml').read_bytes() == Path(web.DEFAULT_YAML_PATH).read_bytes()
    now = web.time.time()
    with patch.object(web.time, 'time', return_value=now + 3 * 86400):
        web.cleanup_old_files()
        response = web.app.test_client().get('/s/' + web.fixed_subscriptions.slug(entry))
        assert response.status_code == 200 and b'Default' in response.data


@pytest.mark.parametrize('slug', ['wrong-fs_' + 'A'*22, 'home-fs_' + 'B'*22, 'home-fs_short', 'UPPER-fs_' + 'A'*22])
def test_wrong_fixed_credentials_are_404(client, slug):
    assert client.get('/s/' + slug).status_code == 404


@pytest.mark.parametrize('suffix', ['', '/new', '/bad/edit'])
def test_management_requires_auth(client, suffix):
    assert client.get('/fixed-subscriptions' + suffix).status_code == 302


@pytest.mark.parametrize('action', ['disable','enable','regenerate','delete'])
def test_management_actions_post_csrf_only(web, logged_in, action):
    entry = create(web, logged_in); before = web.fixed_subscriptions.get(entry['id'])
    url = f'/fixed-subscriptions/{entry["id"]}/{action}'
    assert logged_in.get(url).status_code == 405
    assert logged_in.post(url, data={}).status_code == 303
    assert web.fixed_subscriptions.get(entry['id']) == before


@pytest.mark.parametrize('change', [dict(batch_nodes='INVALID PRIVATE NODE'), dict(name=''),
    dict(aux_nodes='bad json'), dict(node_overrides='[]'), dict(yaml_source='oops')])
def test_rejected_source_preserves_old_url(web, logged_in, change):
    entry = create(web, logged_in); url = '/s/' + web.fixed_subscriptions.slug(entry)
    old = logged_in.get(url).data
    data = dict(name='Updated', prefix=entry['prefix'], yaml_source='custom', batch_nodes='US|Updated|' + LINK)
    data.update(change)
    response = post(logged_in, f'/fixed-subscriptions/{entry["id"]}/edit', data)
    assert response.status_code == 400
    assert logged_in.get(url).data == old


def test_corruption_503_never_reset(web, logged_in):
    entry = create(web, logged_in); path = web.fixed_subscriptions.path
    path.write_text('{broken')
    assert logged_in.get('/fixed-subscriptions').status_code == 503
    assert logged_in.get('/s/' + web.fixed_subscriptions.slug(entry)).status_code == 503
    assert path.read_text() == '{broken'


def test_storage_failure_generic_response_preserves_old(web, logged_in, monkeypatch):
    from core import fixed_subscriptions as fixed
    entry = create(web, logged_in); url = '/s/' + web.fixed_subscriptions.slug(entry)
    old = logged_in.get(url).data
    with monkeypatch.context() as injection:
        def fail(*args): raise OSError('PRIVATE TOKEN SHOULD NEVER APPEAR')
        injection.setattr(fixed, 'write_json', fail)
        response = post(logged_in, f'/fixed-subscriptions/{entry["id"]}/edit',
                        dict(name='Updated',prefix=entry['prefix'],yaml_source='custom',batch_nodes='US|Next|' + LINK))
    assert response.status_code == 503 and b'PRIVATE TOKEN' not in response.data
    assert logged_in.get(url).data == old


def test_fixed_csrf_refresh_no_replay(web, logged_in):
    entry = create(web, logged_in)
    path = f'/fixed-subscriptions/{entry["id"]}/edit'
    before = web.fixed_subscriptions.get(entry['id'])
    response = logged_in.post(path, data={'csrf_token':'expired','name':'Rejected'}, follow_redirects=True)
    assert response.history[0].status_code == 303 and response.request.path == path
    assert b'Rejected' not in response.data and web.fixed_subscriptions.get(entry['id']) == before


@pytest.mark.parametrize('path', ['/s/home-fs_', '/%73/home-%66%73_'])
def test_no_bearer_in_access_logs(web, caplog, path):
    with caplog.at_level(logging.INFO, logger='werkzeug'):
        logging.getLogger('werkzeug').info('GET %s HTTP/1.1', path + 'A'*22)
    assert 'A'*22 not in caplog.text and '[fixed-redacted]' in caplog.text
