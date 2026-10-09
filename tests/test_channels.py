import argparse
import json
import os
from pathlib import Path
import subprocess

import pytest
from core.install_info import (make_install_info, read_install_info, write_install_info,
                               display_build, finalize_install)
from scripts import remote_lifecycle as life
from conftest import ROOT
from test_remote_lifecycle import archive
from test_deployment import deployment

A, B, STABLE = 'a' * 40, 'b' * 40, 'c' * 40


@pytest.fixture
def channel_harness(tmp_path, monkeypatch, isolated_guard):
    monkeypatch.setattr(life.os, 'geteuid', lambda: 0)
    installed = tmp_path / 'installed'; installed.mkdir()
    (installed / 'VERSION').write_text('1.0.2\n')
    (installed / 'app.py').write_text('old')
    (installed / 'state').mkdir(); (installed / 'state/keep').write_text('untouched')
    remote = dict(main=A, base='1.0.2', stable='1.0.2')
    calls, executions = [], []
    def fetch(url, path):
        calls.append(url)
        if url.endswith('/git/ref/heads/main'):
            path.write_text(json.dumps({'ref':'refs/heads/main','object':{'type':'commit','sha':remote['main']}}))
        elif '/releases/' in url:
            tag = 'v' + remote['stable'] if url.endswith('/latest') else url.rsplit('/',1)[1]
            path.write_text(json.dumps(dict(tag_name=tag, draft=False, prerelease=False)))
        elif '/commits/' in url:
            path.write_text(json.dumps({'sha':STABLE}))
        elif '/tar.gz/' in url:
            commit = url.rsplit('/',1)[1]
            assert commit in (A, B, STABLE), 'Never download a moving branch'
            archive(path, remote['stable'] if commit == STABLE else remote['base'])
        else:
            pytest.fail('Unexpected endpoint: ' + url)
    def execute(root, mode, metadata):
        executions.append((mode, json.loads(metadata.read_text())))
        (installed / 'VERSION').write_bytes((root / 'VERSION').read_bytes())
        # Current scripts do this before restart; old stable scripts rely on bootstrap finalization.
        monkeypatch.setenv('CLASH_DEPLOY_METADATA', str(metadata))
        finalize_install(installed)
    args = argparse.Namespace(version=None, channel='main', allow_downgrade=False, resolve_only=False)
    return installed, remote, calls, executions, fetch, execute, args


@pytest.mark.parametrize('mode', ['install','update'])
def test_main_exact_commit_and_metadata(channel_harness, mode, capsys):
    installed, remote, calls, executions, fetch, execute, args = channel_harness
    assert life.run_lifecycle(mode, args, installed, fetch, execute) == A
    assert calls == [f'https://api.github.com/repos/{life.REPOSITORY}/git/ref/heads/main',
                     f'https://codeload.github.com/{life.REPOSITORY}/tar.gz/{A}']
    info = read_install_info(installed)
    assert info['channel'] == 'main' and info['base_version'] == '1.0.2' and info['commit'] == A
    assert info['tag'] is None and info['source'] == 'github-main'
    assert (installed / 'state/keep').read_text() == 'untouched'
    assert (installed / 'VERSION').read_text() == '1.0.2\n'
    output = capsys.readouterr().out
    assert 'Channel: main' in output and 'not a Stable Release' in output
    assert 'Base version: 1.0.2' in output and 'Installed build: 1.0.2-dev+aaaaaaa' in output
    if mode == 'update': assert 'stable → main' in output


def test_resolved_commit_survives_branch_movement(channel_harness):
    installed, remote, calls, _, fetch, execute, args = channel_harness
    def moving_fetch(url, path):
        fetch(url, path)
        if '/git/ref/heads/main' in url: remote['main'] = B
    life.run_lifecycle('update', args, installed, moving_fetch, execute)
    assert calls[-1].endswith('/' + A)
    assert read_install_info(installed)['commit'] == A


def test_main_new_sha_then_same_sha(channel_harness, capsys):
    installed, remote, calls, executions, fetch, execute, args = channel_harness
    life.run_lifecycle('update', args, installed, fetch, execute)
    remote['main'] = B
    life.run_lifecycle('update', args, installed, fetch, execute)
    assert read_install_info(installed)['commit'] == B and len(executions) == 2
    calls.clear()
    life.run_lifecycle('update', args, installed, fetch, execute)
    assert len(calls) == 1 and len(executions) == 2
    assert 'Already up to date.' in capsys.readouterr().out


@pytest.mark.parametrize('stable', ['1.0.1','1.0.2'])
def test_main_to_old_stable_protected_and_explicit_override(channel_harness, stable, capsys):
    installed, remote, calls, executions, fetch, execute, args = channel_harness
    life.run_lifecycle('update', args, installed, fetch, execute)
    old_info = (installed / 'INSTALLATION.json').read_bytes()
    remote['stable'], args.channel = stable, 'stable'
    with pytest.raises(life.LifecycleError, match='Refusing automatic channel downgrade'):
        life.run_lifecycle('update', args, installed, fetch, execute)
    assert len(executions) == 1 and (installed / 'INSTALLATION.json').read_bytes() == old_info
    args.allow_downgrade = True
    life.run_lifecycle('update', args, installed, fetch, execute)
    info = read_install_info(installed)
    assert info['channel'] == 'stable' and info['tag'] == 'v' + stable and info['commit'] == STABLE
    assert display_build(stable, info) == stable
    assert 'main → stable' in capsys.readouterr().out


def test_main_to_newer_stable(channel_harness):
    installed, remote, _, executions, fetch, execute, args = channel_harness
    life.run_lifecycle('update', args, installed, fetch, execute)
    remote['stable'], args.channel = '1.1.0', 'stable'
    life.run_lifecycle('update', args, installed, fetch, execute)
    assert len(executions) == 2 and read_install_info(installed)['tag'] == 'v1.1.0'
    assert (installed / 'VERSION').read_text() == '1.1.0\n'


@pytest.mark.parametrize('channel', [None, 'stable'])
@pytest.mark.parametrize('mode', ['install','update'])
def test_default_and_explicit_stable(channel_harness, channel, mode):
    installed, remote, calls, _, fetch, execute, args = channel_harness
    remote['stable'] = '1.1.0'
    if channel is None: del args.channel
    else: args.channel = channel
    life.run_lifecycle(mode, args, installed, fetch, execute)
    assert calls[0].endswith('/releases/latest') and all('/heads/main' not in url for url in calls)
    assert read_install_info(installed)['channel'] == 'stable'


@pytest.mark.parametrize('response', ['{}','[]','bad',
    json.dumps({'ref':'refs/heads/main','object':{'type':'tag','sha':A}}),
    json.dumps({'ref':'refs/heads/other','object':{'type':'commit','sha':A}}),
    json.dumps({'ref':'refs/heads/main','object':{'type':'commit','sha':'main'}})])
def test_invalid_main_resolution_stops(channel_harness, response):
    installed, _, calls, executions, _, execute, args = channel_harness
    def fetch(url,path): calls.append(url); path.write_text(response)
    with pytest.raises(life.LifecycleError, match='Malformed'):
        life.run_lifecycle('update', args, installed, fetch, execute)
    assert not executions and len(calls) == 1


@pytest.mark.parametrize('options', [['--channel','main','--version','v1.0.2'], ['--channel','invalid']])
def test_cli_invalid_options_before_network(options, monkeypatch):
    monkeypatch.setattr(life,'run_lifecycle',lambda *_: pytest.fail('Invalid arguments must not resolve anything'))
    with pytest.raises(SystemExit) as error: life.main(['update',*options])
    assert error.value.code == 2


def test_standalone_main_resolve_without_repository(tmp_path):
    commands=tmp_path/'bin'; commands.mkdir()
    curl=commands/'curl'
    curl.write_text('''#!/usr/bin/env python3
import sys,json
from pathlib import Path
assert sys.argv[-1].endswith('/git/ref/heads/main')
Path(sys.argv[sys.argv.index('--output')+1]).write_text(json.dumps({'ref':'refs/heads/main','object':{'type':'commit','sha':'a'*40}}))
print('200',end='')
''');curl.chmod(0o700)
    for mode in ('install','update'):
        result=subprocess.run(['bash',str(ROOT/f'remote-{mode}.sh'),'--channel','main','--resolve-only'],
            cwd=tmp_path,env=dict(os.environ,PATH=str(commands)+os.pathsep+os.environ['PATH']),capture_output=True,text=True)
        assert result.returncode==0, result.stderr
        assert 'Resolved commit: '+A in result.stdout


def test_metadata_atomic_permissions_and_failure(tmp_path, monkeypatch):
    info=make_install_info('main','1.0.2',A)
    write_install_info(tmp_path,info)
    target=tmp_path/'INSTALLATION.json'; original=target.read_bytes()
    assert target.stat().st_mode & 0o777 == 0o644
    assert not set(info) & {'password','password_hash','SECRET_KEY','token'}
    def failure(*_): raise OSError('disk error')
    with monkeypatch.context() as patch:
        patch.setattr('core.install_info.os.replace',failure)
        with pytest.raises(OSError): write_install_info(tmp_path,make_install_info('main','1.0.2',B))
    assert target.read_bytes()==original and not list(tmp_path.glob('.installation-*'))
    write_install_info(tmp_path,make_install_info('stable','1.1.0',STABLE,'v1.1.0'))
    assert read_install_info(tmp_path)['tag']=='v1.1.0'


def test_bad_metadata_cannot_bypass_downgrade(channel_harness):
    installed, _, _, executions, fetch, execute, args=channel_harness
    (installed/'INSTALLATION.json').write_text('{broken')
    args.channel='stable'
    with pytest.raises(life.LifecycleError,match='Invalid installation metadata'):
        life.run_lifecycle('update',args,installed,fetch,execute)
    assert not executions


@pytest.mark.parametrize('channel',['stable','main'])
def test_web_build_footer(web, client, channel):
    version=(Path(web.BASE_DIR)/'VERSION').read_text().strip()
    info=make_install_info(channel,version,A,'v'+version if channel=='stable' else None)
    write_install_info(web.BASE_DIR,info)
    html=client.get('/').get_data(as_text=True)
    if channel=='main':
        assert f'v{version}-dev+aaaaaaa' in html and 'DEV · Development Build' in html
    else:
        assert f'Clash YAML Manager v{version}' in html and 'DEV · Development Build' not in html


def test_web_build_footer_rejects_metadata_for_another_version(web, client):
    version=(Path(web.BASE_DIR)/'VERSION').read_text().strip()
    other='999.0.0' if version!='999.0.0' else '998.0.0'
    write_install_info(web.BASE_DIR,make_install_info('main',other,A))
    html=client.get('/').get_data(as_text=True)
    assert f'Clash YAML Manager v{version}' in html
    assert 'Build metadata unavailable' in html
    assert '-dev+aaaaaaa' not in html and 'DEV · Development Build' not in html


def test_real_update_hooks_preserve_state_across_main_updates(deployment):
    installed, source, _, events, env, run=deployment
    metadata=source.parent/'incoming.json'
    env['CLASH_DEPLOY_METADATA']=str(metadata)
    (installed/'state').mkdir()
    (installed/'state/temporary_links.json').write_text('{"version":1,"links":{}}')
    for commit in (A,B):
        info=make_install_info('main',(source/'VERSION').read_text().strip(),commit)
        metadata.write_text(json.dumps(info))
        result=run()
        assert result.returncode==0,result.stderr
        assert read_install_info(installed)==info
        assert (installed/'INSTALLATION.json').stat().st_mode & 0o777==0o644
        assert (installed/'state/temporary_links.json').read_text()=='{"version":1,"links":{}}'
        assert 'CLASH_DEPLOY_METADATA' not in (installed/'.env').read_text()
    assert 'chown -hR root:root '+str(installed/'INSTALLATION.json') in events.read_text()
    # Direct source updates must not retain an outdated main commit identity.
    env.pop('CLASH_DEPLOY_METADATA')
    assert run().returncode==0
    assert read_install_info(installed)['channel']=='local'
