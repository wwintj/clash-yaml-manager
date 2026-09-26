from concurrent.futures import ProcessPoolExecutor
import os
from pathlib import Path
import time
import pytest
from core.temporary_links import TemporaryLinks
from core.state import StateError, read_json
from core.retention import seconds_from_env
from conftest import LINK, post


def create_in_worker(directory, index):
    return TemporaryLinks(directory).create(f'worker{index}.yaml')[0]


def test_shared_process_atomicity_and_modes(tmp_path):
    with ProcessPoolExecutor(3) as pool:
        ids = list(pool.map(create_in_worker, [str(tmp_path)]*12, range(12)))
    assert len(set(ids)) == 12
    store = TemporaryLinks(tmp_path)
    assert all(store.resolve(key)['filename'].startswith('worker') for key in ids)
    assert store.path.stat().st_mode & 0o777 == 0o600
    assert tmp_path.stat().st_mode & 0o777 == 0o700


def test_expiry_revoke_and_forced_historical_collision(tmp_path, monkeypatch):
    store = TemporaryLinks(tmp_path)
    monkeypatch.setattr('core.temporary_links.secrets.token_urlsafe', lambda _: 'A'*16)
    a, _ = store.create('a.yaml', 10, now=100)
    assert store.resolve(a, now=109)['filename'] == 'a.yaml'
    assert store.resolve(a, now=110) is None
    assert read_json(store.path)['links'][a] is None
    values = iter(['A'*16, 'B'*16])
    monkeypatch.setattr('core.temporary_links.secrets.token_urlsafe', lambda _: next(values))
    b, _ = TemporaryLinks(tmp_path).create('b.yaml', now=111)
    store.revoke_file('b.yaml')
    values = iter(['A'*16, 'B'*16, 'C'*16])
    c, _ = store.create('c.yaml', now=112)
    assert store.resolve(a, now=113) is None and store.resolve(b, now=113) is None
    assert store.resolve(c, now=113)['filename'] == 'c.yaml'
    monkeypatch.setattr('core.temporary_links.secrets.token_urlsafe', lambda _: 'A'*16)
    with pytest.raises(StateError): store.create('d.yaml', now=114)


@pytest.mark.parametrize('key', ['', '../secret', '中文'*8, 'A'*15, 'A'*17])
def test_invalid_ids(tmp_path, key):
    assert TemporaryLinks(tmp_path).resolve(key) is None


def test_corruption_fails_closed(tmp_path):
    store = TemporaryLinks(tmp_path); store.path.write_text('{broken')
    with pytest.raises(StateError): store.create('test.yaml')


def test_retention_config():
    assert seconds_from_env({}, 'UPLOAD_RETENTION_HOURS', 1, 'FILE_RETENTION_DAYS') == 3600
    assert seconds_from_env({'FILE_RETENTION_DAYS':'7'}, 'OUTPUT_RETENTION_HOURS',24,'FILE_RETENTION_DAYS') == 604800
    assert seconds_from_env({'OUTPUT_RETENTION_HOURS':'24','FILE_RETENTION_DAYS':'7'},'OUTPUT_RETENTION_HOURS',24,'FILE_RETENTION_DAYS') == 86400
    for value in ('bad','0','-1','nan','inf'):
        assert seconds_from_env({'OUTPUT_RETENTION_HOURS':value}, 'OUTPUT_RETENTION_HOURS',24) == 86400


def test_cleanup_boundaries_and_scope(web, monkeypatch):
    now = time.time()
    paths = {}
    for directory, age, label in [(web.DIR_UPLOADS,3601,'expired-upload'),(web.DIR_UPLOADS,3590,'live-upload'),
        (web.DIR_OUTPUTS,86401,'expired-output'),(web.DIR_OUTPUTS,86390,'live-output'),
        (web.DIR_BACKUPS,86401,'safe-backup'),(web.DIR_BACKUPS,604801,'expired-backup'),
        (web.DIR_LOGS,999999,'log')]:
        path = Path(directory)/(label+'.yaml'); path.write_text('{}'); os.utime(path,(now-age,now-age)); paths[label]=path
    key, _ = web.temporary_links.create('expired-output.yaml', now=now-86401)
    auth = Path(web.DIR_STATE)/'auth.json'; original = auth.read_bytes()
    Path(web.CLEANUP_MARKER).unlink(); web.cleanup_old_files()
    for label, path in paths.items(): assert path.exists() == (not label.startswith('expired'))
    assert auth.read_bytes() == original
    assert web.temporary_links.resolve(key) is None
    monkeypatch.setattr(os, 'scandir', lambda *_: pytest.fail('Cleanup must be throttled'))
    web.cleanup_old_files()


def test_new_links_expire_before_cleanup_and_old_routes_work(web, logged_in, monkeypatch):
    post(logged_in, '/process', {'batch_nodes':LINK})
    with logged_in.session_transaction() as session: context = session['page_context']
    url = context['download_url']; short_id = url.rsplit('/',1)[1]
    assert len(short_id) == 16 and '/t/' in url
    assert 'expires_at' in context['result']
    anonymous = web.app.test_client()
    assert anonymous.get('/t/'+short_id).status_code == 200
    assert 'attachment' in anonymous.get('/t/'+short_id+'?download=1').headers['Content-Disposition']
    filename = context['output_filename']
    # Existing V2 remains usable while its file exists.
    assert anonymous.get('/s/'+web.build_short_subscription_slug(filename)).status_code == 200
    entry = web.temporary_links.resolve(short_id)
    monkeypatch.setattr(web, 'cleanup_old_files', lambda: None)
    monkeypatch.setattr('core.temporary_links.time.time', lambda: entry['expires_at'])
    assert anonymous.get('/t/'+short_id).status_code == 404
    assert (Path(web.DIR_OUTPUTS)/filename).exists()


def test_deleted_url_never_serves_new_generation(web, logged_in):
    post(logged_in,'/process',{'batch_nodes':LINK})
    with logged_in.session_transaction() as session: a=session['page_context'].copy()
    post(logged_in,'/delete-temp',{'output_filename':a['output_filename']})
    post(logged_in,'/process',{'batch_nodes':LINK})
    with logged_in.session_transaction() as session: b=session['page_context']
    assert a['download_url'] != b['download_url']
    assert web.app.test_client().get(a['download_url']).status_code == 404
    assert web.app.test_client().get(b['download_url']).status_code == 200
