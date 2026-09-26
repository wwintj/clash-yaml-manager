from pathlib import Path
import shutil
import subprocess
import pytest
from conftest import post


def test_draft_storage():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is needed for the browser storage unit test')
    subprocess.run([node, str(Path(__file__).with_suffix('.js'))], check=True)


def test_expired_csrf_keeps_draft_client_hook(web, logged_in):
    response = logged_in.post('/process', data={'csrf_token': 'expired'})
    assert response.status_code == 400
    html = response.get_data(as_text=True)
    assert 'draft.js' in html and 'draft-status' in html
    with logged_in.session_transaction() as session:
        session.clear()
    response = logged_in.post('/process', data={'csrf_token': 'expired'})
    assert response.status_code == 400 and 'draft.js' in response.get_data(as_text=True)
    response = post(logged_in, '/login', {'password': 'test 密码'}, follow_redirects=True)
    assert 'draft-status' in response.get_data(as_text=True)
    assert web.app.config['SESSION_REFRESH_EACH_REQUEST'] is True


def test_missing_custom_file_is_not_silently_defaulted(logged_in):
    response = post(logged_in, '/process', {'yaml_source': 'custom', 'batch_nodes':'invalid'}, follow_redirects=True)
    assert 'Custom YAML needs to be selected again.' in response.get_data(as_text=True)
