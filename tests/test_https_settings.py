"""Safe metadata projection, runtime bind and unchanged URL identities."""
import json
import os
from pathlib import Path
import socket
import subprocess
import pytest
from core import https_metadata as metadata
from core.deployment_config import bind_host
from conftest import ROOT
from test_fixed_views import create


def safe_info():
    return dict(version=1,managed=True,domain='example.com',configured_at='2026-09-30T00:00:00+00:00',
                cert_mode='certbot-webroot',app_port=8899,nginx_config_sha256='a'*64,hook_sha256='b'*64,
                unit_sha256='c'*64,managed_settings=metadata.managed_settings('example.com'),
                previous_backup='/root/clash-yaml-manager-https-backup-20260930_000000.abcdef')


@pytest.fixture
def metadata_reader(monkeypatch):
    original=metadata.read
    monkeypatch.setattr(metadata,'read',lambda directory: original(directory,owner_uid=os.getuid(),group_gid=os.getgid()))


@pytest.mark.parametrize('mode',['absent','configured','invalid','manual'])
def test_settings_safe_metadata_runtime_no_execution(web,logged_in,monkeypatch,metadata_reader,mode):
    path=Path(web.BASE_DIR)/metadata.NAME
    sentinel=['PRIVATE_PASSWORD','CERT_PRIVATE_KEY','REGISTRATION_EMAIL@example.com','FIXED_BEARER','PROVIDER_CREDENTIAL','SECRET_KEY_VALUE']
    if mode=='configured':path.write_text(json.dumps(safe_info()));path.chmod(0o640)
    if mode=='invalid':path.write_text(json.dumps(dict(safe_info(),email=sentinel[2],secrets=sentinel)));path.chmod(0o640)
    if mode in ('configured','manual'):
        for name,value in dict(APP_BIND_HOST='127.0.0.1',COOKIE_SECURE=True,TRUST_PROXY_HEADERS=True,DOWNLOAD_URL_SCHEME='https',DOWNLOAD_BASE_URL='https://PRIVATE_PASSWORD:PROVIDER_CREDENTIAL@example.com/').items():
            monkeypatch.setattr(web,name,value)
    calls=[]
    def forbidden(*args,**kwargs):
        calls.append((args,kwargs))
        raise AssertionError('No Web process/network calls')
    for name in ('run','Popen','call','check_call','check_output'):monkeypatch.setattr(subprocess,name,forbidden)
    monkeypatch.setattr(socket,'getaddrinfo',forbidden)
    before=path.read_bytes() if path.exists() else None
    response=logged_in.get('/settings');assert response.status_code==200
    html=response.get_data(as_text=True)
    expected={'absent':'Not configured','configured':'Configured','invalid':'Metadata unavailable','manual':'Not configured'}[mode]
    assert f'data-runtime="managed_https">{expected}</dd>' in html
    assert ('data-runtime="managed_domain">example.com</dd>' in html)==(mode=='configured')
    if mode in ('configured','manual'):
        assert 'data-runtime="bind">Loopback only</dd>' in html
        assert 'data-runtime="cookie_secure">Enabled</dd>' in html
        assert 'data-runtime="trust_proxy">Enabled</dd>' in html
    for secret in sentinel+[web.SECRET_KEY if hasattr(web,'SECRET_KEY') else 'test-only-fixed-secret']:
        assert secret not in html
    assert 'sudo bash /opt/clash-yaml-manager/httpsctl.sh status' in html
    assert before==(path.read_bytes() if path.exists() else None)
    assert not calls
    assert logged_in.post('/settings/https/setup').status_code==404
    assert logged_in.post('/settings/https/disable').status_code==404
    anonymous=web.app.test_client().get('/settings')
    assert anonymous.status_code==302 and b'example.com' not in anonymous.data


@pytest.mark.parametrize('bad',['mode','symlink','unknown','oversized','duplicate','version','timestamp','backup'])
def test_metadata_rejects_unsafe_projection(web,logged_in,metadata_reader,bad):
    path=Path(web.BASE_DIR)/metadata.NAME;info=safe_info();path.write_text(json.dumps(info));path.chmod(0o640)
    if bad=='mode':path.chmod(0o644)
    if bad=='symlink':path.unlink();path.symlink_to(Path(web.BASE_DIR)/'VERSION')
    if bad=='unknown':path.write_text(json.dumps(dict(info,email='FORBIDDEN@example.com')))
    if bad=='oversized':path.write_text('FORBIDDEN'*2000)
    if bad=='duplicate':path.write_text(path.read_text().replace('"version": 1','"version": 1, "version": 1'))
    if bad=='version':path.write_text(json.dumps(dict(info,version=True)))
    if bad=='timestamp':path.write_text(json.dumps(dict(info,configured_at='2026-99-30T00:00:00+00:00')))
    if bad=='backup':path.write_text(json.dumps(dict(info,previous_backup='/tmp/arbitrary')))
    html=logged_in.get('/settings').get_data(as_text=True)
    assert 'data-runtime="managed_https">Metadata unavailable</dd>' in html
    assert 'FORBIDDEN' not in html and 'data-runtime="managed_domain"' not in html


def test_url_origin_switch_preserves_fixed_and_temp_identity(web,logged_in,monkeypatch):
    entry=create(web,logged_in);slug=web.fixed_subscriptions.slug(entry)
    state={p:p.read_bytes() for p in Path(web.DIR_STATE).rglob('*') if p.is_file()}
    filename='20260930_existing.yaml';token=web.generate_download_token(filename)
    with web.app.test_request_context('/'):
        old_fixed=web.fixed_public_url(slug);old_temp=web.build_download_url(filename);old_file=web.build_file_download_url(filename)
        monkeypatch.setattr(web,'DOWNLOAD_BASE_URL','https://example.com')
        monkeypatch.setattr(web,'DOWNLOAD_URL_SCHEME','https')
        assert web.fixed_public_url(slug)=='https://example.com'+old_fixed.removeprefix('http://localhost')
        assert web.build_download_url(filename)=='https://example.com'+old_temp.removeprefix('http://localhost')
        assert web.build_file_download_url(filename)=='https://example.com'+old_file.removeprefix('http://localhost')
        assert web.generate_download_token(filename)==token
        assert web.fixed_subscriptions.slug(entry)==slug
    assert state=={p:p.read_bytes() for p in state}


@pytest.mark.parametrize('host',['example.com','192.0.2.1',' 127.0.0.1','127.0.0.1\n'])
def test_startup_rejects_invalid_bind_without_runtime_writes(tmp_path,host):
    import shutil, sys
    shutil.copy2(ROOT/'app.py',tmp_path/'app.py')
    environment=dict(os.environ,APP_BIND_HOST=host,PYTHONPATH=str(ROOT))
    result=subprocess.run([sys.executable,str(tmp_path/'app.py')],env=environment,capture_output=True,text=True)
    assert result.returncode != 0 and 'APP_BIND_HOST 必须为' in result.stderr
    assert not (tmp_path/'state').exists() and not (tmp_path/'logs').exists()


def test_default_http_bind_runtime(web):
    assert web.APP_BIND_HOST == '0.0.0.0'
    assert web.settings_runtime()['bind'] == 'All interfaces'
