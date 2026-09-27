from pathlib import Path
import shutil
import subprocess
import pytest
from conftest import post
from conftest import ROOT
from html.parser import HTMLParser


def test_draft_storage():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is needed for the browser storage unit test')
    subprocess.run([node, str(Path(__file__).with_suffix('.js'))], check=True)


def test_expired_csrf_keeps_draft_client_hook(web, logged_in):
    response = logged_in.post('/process', data={'csrf_token': 'expired'}, follow_redirects=True)
    assert response.history[0].status_code == 303 and response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'draft.js' in html and 'draft-status' in html
    with logged_in.session_transaction() as session:
        session.clear()
    response = logged_in.post('/process', data={'csrf_token': 'expired'}, follow_redirects=True)
    assert response.status_code == 200 and 'draft.js' in response.get_data(as_text=True)
    response = post(logged_in, '/login', {'password': 'test 密码'}, follow_redirects=True)
    assert 'draft-status' in response.get_data(as_text=True)
    assert web.app.config['SESSION_REFRESH_EACH_REQUEST'] is True


def test_missing_custom_file_is_not_silently_defaulted(logged_in):
    response = post(logged_in, '/process', {'yaml_source': 'custom', 'batch_nodes':'invalid'}, follow_redirects=True)
    assert 'Custom YAML needs to be selected again.' in response.get_data(as_text=True)


def test_only_generate_is_a_process_submitter(logged_in):
    class Buttons(HTMLParser):
        def __init__(self):
            super().__init__()
            self.form = None
            self.buttons = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'form':
                self.form = attrs.get('id') or attrs.get('action')
            if tag == 'button':
                self.buttons.append((attrs.get('form', self.form), attrs))

        def handle_endtag(self, tag):
            if tag == 'form':
                self.form = None

    parser = Buttons()
    parser.feed(logged_in.get('/').get_data(as_text=True))
    process = [attrs for form, attrs in parser.buttons if form == 'process-form']
    submitters = [attrs for attrs in process if attrs.get('type', 'submit') == 'submit']
    assert len(submitters) == 1 and submitters[0]['id'] == 'generate-yaml'
    assert submitters[0]['name'] == 'action' and submitters[0]['value'] == 'generate'
    for _, attrs in parser.buttons:
        if attrs.get('id') in ('parse-nodes', 'add-node-row') or any(
            name in attrs.get('class', '') for name in ('remove-node-row', 'clear-draft')
        ):
            assert attrs['type'] == 'button'
    assert "action.type = 'button'" in (ROOT / 'static/nodes.js').read_text()


def test_sliding_session_and_30_day_inactivity(web, logged_in, monkeypatch):
    import time
    now = time.time()
    monkeypatch.setattr(time, 'time', lambda: now + 29 * 86400)
    response = logged_in.get('/')
    assert 'Set-Cookie' in response.headers
    assert 'process-form' in response.get_data(as_text=True)
    # The refreshed cookie remains valid 29 days later (58 since original login).
    monkeypatch.setattr(time, 'time', lambda: now + 58 * 86400)
    assert 'process-form' in logged_in.get('/').get_data(as_text=True)
    monkeypatch.setattr(time, 'time', lambda: now + 89 * 86400)
    assert 'id="password"' in logged_in.get('/').get_data(as_text=True)
