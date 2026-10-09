"""Authenticated finite CSRF refresh with real Flask-WTF validation."""
import hashlib
from pathlib import Path

from itsdangerous import SignatureExpired, URLSafeTimedSerializer
import pytest

from conftest import LINK
from test_session_lifetime import clock

HEADERS = {'X-CSRF-Refresh':'1','Sec-Fetch-Site':'same-origin'}


def refresh(client, **kwargs):
    return client.get('/api/csrf-token',headers=HEADERS,**kwargs)


def test_refresh_requires_authentication_and_no_secret_response(web, client, logged_in):
    anonymous = web.app.test_client()
    rejected = refresh(anonymous)
    assert rejected.status_code == 401 and 'csrf_token' not in rejected.json
    response = refresh(logged_in)
    assert response.status_code == 200 and set(response.json) == {'csrf_token'}
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['Referrer-Policy'] == 'no-referrer'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'Cookie' in response.vary and 'Access-Control-Allow-Origin' not in response.headers
    for secret in ('test 密码',web.app.secret_key,logged_in.get_cookie('session').value):
        assert secret not in response.text
    assert 'csrf.js' not in anonymous.get('/').text
    for path in ('/','/settings','/fixed-subscriptions','/fixed-subscriptions/new'):
        assert 'csrf.js' in logged_in.get(path).text


@pytest.mark.parametrize('headers', [{}, {'X-CSRF-Refresh':'0'},
    dict(HEADERS,Origin='https://attacker.example'),dict(HEADERS,Origin='null'),
    dict(HEADERS,Origin='http://localhost:bad'),dict(HEADERS,Origin='http://localhost/path'),
    dict(HEADERS,Origin='http://user@localhost'),dict(HEADERS,Origin='http://[invalid'),
    dict(HEADERS,**{'Sec-Fetch-Site':'same-site'}),dict(HEADERS,**{'Sec-Fetch-Site':'cross-site'}),
    dict(HEADERS,**{'Sec-Fetch-Site':'none'})])
def test_refresh_rejects_non_same_origin_requests(logged_in, headers):
    response = logged_in.get('/api/csrf-token',headers=headers)
    assert response.status_code == 403 and 'csrf_token' not in response.json
    assert 'Access-Control-Allow-Origin' not in response.headers


def test_origin_contract_and_preflight_no_cors(logged_in):
    assert logged_in.get('/api/csrf-token',headers=dict(HEADERS,Origin='http://localhost')).status_code == 200
    # Older same-origin clients without Fetch Metadata still require the custom header.
    assert logged_in.get('/api/csrf-token',headers={'X-CSRF-Refresh':'1'}).status_code == 200
    response = logged_in.options('/api/csrf-token',headers={'Origin':'https://attacker.example',
        'Access-Control-Request-Headers':'X-CSRF-Refresh'})
    assert 'Access-Control-Allow-Origin' not in response.headers and 'csrf_token' not in response.text
    assert logged_in.head('/api/csrf-token',headers=HEADERS).status_code == 403
    # No exemption for a POST to the refresh URL itself.
    assert logged_in.post('/api/csrf-token').status_code == 405


def test_refresh_does_not_modify_business_state_or_run_cleanup(web, logged_in, monkeypatch):
    def forbidden(): pytest.fail('Token refresh must not trigger file cleanup')
    monkeypatch.setattr(web,'cleanup_old_files',forbidden)
    root = Path(web.DIR_STATE)
    before = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    assert refresh(logged_in).status_code == 200
    assert before == {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


def test_expired_token_replaced_without_rotating_nonce(web, clock, logged_in):
    current = clock
    first = refresh(logged_in).json['csrf_token']
    with logged_in.session_transaction() as session: raw = session['csrf_token']
    current[0] += 3601
    s = URLSafeTimedSerializer(web.app.secret_key,salt='wtf-csrf-token')
    with pytest.raises(SignatureExpired): s.loads(first,max_age=3600)
    second = refresh(logged_in).json['csrf_token']
    assert second != first and s.loads(second,max_age=3600) == raw
    with logged_in.session_transaction() as session: assert session['csrf_token'] == raw
    accepted = logged_in.post('/parse-nodes',data={'csrf_token':second,'batch_nodes':LINK})
    assert accepted.status_code == 200 and accepted.json['nodes']
    assert web.app.config['WTF_CSRF_TIME_LIMIT'] == 3600
    # An old submitted token remains rejected, rather than silently revalidated.
    rejected = logged_in.post('/parse-nodes',data={'csrf_token':first,'batch_nodes':LINK})
    assert rejected.status_code == 400 and rejected.json['code'] == 'csrf_failed'
    assert not list(Path(web.DIR_OUTPUTS).iterdir())


def test_multiple_open_forms_keep_same_nonce_and_validate(web, clock, logged_in):
    current = clock
    first = refresh(logged_in).json['csrf_token']
    current[0] += 1800
    second = refresh(logged_in).json['csrf_token']
    assert first != second
    for csrf in (first, second):
        assert logged_in.post('/parse-nodes',data={'csrf_token':csrf,'batch_nodes':LINK}).status_code == 200
    # Existing error handler rotates a nonce after rejection. Fresh fetch on each
    # tab's next explicit action lets it recover without replaying rejected bodies.
    assert logged_in.post('/parse-nodes',data={'csrf_token':'bad','batch_nodes':LINK}).status_code == 400
    third = refresh(logged_in).json['csrf_token']
    assert logged_in.post('/parse-nodes',data={'csrf_token':third,'batch_nodes':LINK}).status_code == 200


def test_refresh_cannot_resurrect_expired_session(web, logged_in, monkeypatch):
    from itsdangerous import TimestampSigner
    saved = logged_in.get_cookie('session').value
    s = web.app.session_interface.get_signing_serializer(web.app)
    _, issued = s.loads(saved,return_timestamp=True)
    monkeypatch.setattr(TimestampSigner,'get_timestamp',lambda self:int(issued.timestamp())+30*86400+1)
    response = refresh(logged_in)
    assert response.status_code == 401 and 'csrf_token' not in response.json
    with logged_in.session_transaction() as session: assert not session.get('logged_in')


def test_frontend_tokens_not_persisted_or_added_to_urls(web, logged_in):
    script = (Path(web.BASE_DIR)/'static/csrf.js').read_text()
    for forbidden in ('localStorage','sessionStorage','console.','setInterval','setTimeout','.submit()'):
        assert forbidden not in script
    assert "redirect: 'error'" in script and 'response.ok' in script
    assert '/api/csrf-token?' not in script
    token = refresh(logged_in).json['csrf_token']
    for directory in (web.DIR_LOGS,web.DIR_STATE):
        for path in Path(directory).rglob('*'):
            if path.is_file(): assert token.encode() not in path.read_bytes()


@pytest.mark.parametrize('value', ['PRIVATE_SESSION_VALUE','3650',0,-1,3651,True,None])
def test_runtime_does_not_project_raw_or_invalid_session_values(value):
    from core.settings_status import runtime
    result = runtime(port=8899,cookie_secure=False,trust_proxy=False,download_base='',download_scheme='',
        upload_retention=3600,output_retention=86400,cleanup_interval=3600,backup_retention=604800,
        session_lifetime_days=value)
    assert result['session_lifetime'] == 'Unavailable'
    assert 'PRIVATE_SESSION_VALUE' not in str(result)
