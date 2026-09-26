import argparse
import io
import json
from pathlib import Path
import subprocess
import tarfile

import pytest

from scripts import remote_lifecycle as life


def archive(path, version='1.0.1', extra=None):
    entries = {'VERSION': version + '\n', 'app.py': '', 'requirements.txt': '',
               'install.sh': '#!/bin/bash\n', 'update.sh': '#!/bin/bash\n', 'uninstall.sh': '#!/bin/bash\n',
               'scripts/deploy-common.sh': '#!/bin/bash\n', 'core/security.py': '', 'core/version.py': ''}
    with tarfile.open(path, 'w:gz') as output:
        for name, data in entries.items():
            data = data.encode()
            member = tarfile.TarInfo('project/' + name)
            member.size = len(data)
            output.addfile(member, io.BytesIO(data))
        if extra:
            output.addfile(extra)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setattr(life.os, 'geteuid', lambda: 0)
    installed = tmp_path / 'installed'
    installed.mkdir()
    (installed / 'app.py').write_text('old')
    (installed / 'VERSION').write_text('1.0.0\n')
    (installed / 'state').mkdir()
    (installed / 'state/keep').write_text('keep')
    calls, executed, temporary = [], [], []
    def fetch(url, path):
        calls.append(url)
        temporary.append(path.parent)
        if url.endswith('/latest') or '/releases/tags/' in url:
            tag = url.rsplit('/', 1)[1]
            if tag == 'latest':
                tag = 'v1.0.1'
            path.write_text(json.dumps(dict(tag_name=tag, draft=False, prerelease=False)))
        else:
            archive(path, url.rsplit('/', 1)[1][1:])
    def execute(root, mode):
        executed.append((root, mode))
        (installed / 'VERSION').write_bytes((root / 'VERSION').read_bytes())
    args = argparse.Namespace(version=None, allow_downgrade=False, resolve_only=False)
    return installed, calls, executed, temporary, fetch, execute, args


@pytest.mark.parametrize('mode, pin', [('install', None), ('install', 'v1.2.0'), ('update', None), ('update', '1.2.0')])
def test_latest_and_pinned_exact_tag_download(harness, mode, pin):
    installed, calls, executed, temporary, fetch, execute, args = harness
    args.version = pin
    tag = life.run_lifecycle(mode, args, installed, fetch, execute)
    assert tag == ('v1.2.0' if pin else 'v1.0.1')
    assert calls[-1].endswith('/refs/tags/' + tag)
    assert all('/main' not in url for url in calls)
    assert executed[0][1] == mode
    assert (installed / 'VERSION').read_text() == tag[1:] + '\n'
    assert (installed / 'state/keep').read_text() == 'keep'
    assert all(not path.exists() for path in temporary)


def test_already_current_and_legacy_without_version(harness, capsys):
    installed, calls, executed, _, fetch, execute, args = harness
    (installed / 'VERSION').write_text('1.0.1\n')
    life.run_lifecycle('update', args, installed, fetch, execute)
    assert not executed and len(calls) == 1
    assert 'Already up to date.' in capsys.readouterr().out
    (installed / 'VERSION').unlink()
    life.run_lifecycle('update', args, installed, fetch, execute)
    assert executed and 'legacy' in capsys.readouterr().out


def test_downgrade_requires_explicit_option(harness):
    installed, calls, executed, _, fetch, execute, args = harness
    (installed / 'VERSION').write_text('2.0.0\n')
    with pytest.raises(life.LifecycleError, match='Downgrade'):
        life.run_lifecycle('update', args, installed, fetch, execute)
    assert not executed and len(calls) == 1
    args.allow_downgrade = True
    life.run_lifecycle('update', args, installed, fetch, execute)
    assert (installed / 'VERSION').read_text() == '1.0.1\n'


def test_resolve_only_needs_no_root_or_installation(harness, monkeypatch):
    installed, calls, executed, _, fetch, execute, args = harness
    monkeypatch.setattr(life.os, 'geteuid', lambda: 501)
    args.resolve_only = True
    assert life.run_lifecycle('install', args, installed, fetch, execute) == 'v1.0.1'
    assert not executed and len(calls) == 1


@pytest.mark.parametrize('response', ['not-json', '{}', '[]', '{"tag_name":1,"draft":false,"prerelease":false}',
                                    '{"tag_name":"main","draft":false,"prerelease":false}',
                                    '{"tag_name":"v1.0.1","draft":true,"prerelease":false}',
                                    '{"tag_name":"v1.0.1","draft":false,"prerelease":true}'])
def test_malformed_release_safe_no_fallback(harness, response):
    installed, calls, executed, temporary, _, execute, args = harness
    def fetch(url, path):
        calls.append(url)
        temporary.append(path.parent)
        path.write_text(response)
    with pytest.raises(life.LifecycleError):
        life.run_lifecycle('update', args, installed, fetch, execute)
    assert len(calls) == 1 and not executed
    assert all(not path.exists() for path in temporary)
    assert (installed / 'VERSION').read_text() == '1.0.0\n'


@pytest.mark.parametrize('status, code', [('404', 22), ('403', 22), ('429', 22), ('000', 28)])
def test_http_failures_and_timeout_are_explicit(tmp_path, monkeypatch, status, code):
    monkeypatch.setattr(life.subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(a, code, status, 'secret'))
    with pytest.raises(life.LifecycleError, match='no main fallback') as error:
        life.download('https://api.github.com/example', tmp_path / 'response')
    assert 'secret' not in str(error.value)


@pytest.mark.parametrize('failure', ['network', 'invalid', 'version', 'traversal', 'symlink'])
def test_archive_failure_never_executes_and_cleans_up(harness, failure):
    installed, calls, executed, temporary, original, execute, args = harness
    def fetch(url, path):
        if '/releases/' in url:
            return original(url, path)
        temporary.append(path.parent)
        if failure == 'network':
            raise life.LifecycleError('download failure')
        if failure == 'invalid':
            path.write_text('not an archive')
        elif failure == 'version':
            archive(path, '9.9.9')
        else:
            member = tarfile.TarInfo('project/../../outside' if failure == 'traversal' else 'project/link')
            if failure == 'symlink':
                member.type, member.linkname = tarfile.SYMTYPE, '/etc/passwd'
            archive(path, extra=member)
    with pytest.raises(life.LifecycleError):
        life.run_lifecycle('update', args, installed, fetch, execute)
    assert not executed
    assert (installed / 'VERSION').read_text() == '1.0.0\n'
    assert (installed / 'state/keep').read_text() == 'keep'
    assert all(not path.exists() for path in temporary)


def test_bootstrap_shell_executes_without_local_repository(tmp_path):
    """Run the actual standalone script with a fake curl, no network or /opt writes."""
    import os
    from conftest import ROOT
    commands = tmp_path / 'bin'
    commands.mkdir()
    curl = commands / 'curl'
    curl.write_text('''#!/usr/bin/env python3
import sys
from pathlib import Path
Path(sys.argv[sys.argv.index('--output') + 1]).write_text('{"tag_name":"v9.8.7","draft":false,"prerelease":false}')
print('200', end='')
''')
    curl.chmod(0o700)
    for mode in ('install', 'update'):
        result = subprocess.run(['bash', str(ROOT / f'remote-{mode}.sh'), '--resolve-only'], cwd=tmp_path,
                                env=dict(os.environ, PATH=str(commands) + os.pathsep + os.environ['PATH']),
                                text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert 'Resolved stable: v9.8.7' in result.stdout
