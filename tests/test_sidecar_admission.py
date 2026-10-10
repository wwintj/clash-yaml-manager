"""Pure early admission on isolated direct and generated remote shell paths."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from conftest import ROOT, local_guard_copy
from core.install_info import make_install_info, write_install_info
from core.version import normalize_tag, read_version
from test_backup_collect import frozen
from test_deployment import deployment


INVALID = [(m, 'YES', 'INVALID_MODE') for m in
           ('INVALID', 'off', 'optional', 'strict', '', ' ', ' OFF', 'OFF ', 'OFF\n', 'mode-secret-sentinel')]
INVALID += [(m, q, 'EXTERNAL_WRITERS_QUIET_REQUIRED') for m in ('OPTIONAL', 'STRICT')
            for q in (None, '', 'NO', 'yes', 'YES ', ' YES', 'YES\n', 'TRUE')]
VALID = [(None, None), ('OFF', None), ('OFF', 'NO'), ('OPTIONAL', 'YES'), ('STRICT', 'YES')]


@pytest.fixture
def admission(deployment, tmp_path, request):
    installed, source, service, events, env, execute = deployment
    for name in ('CLASH_BACKUP_SIDECAR_MODE', 'CLASH_BACKUP_EXTERNAL_WRITERS_QUIET', 'CLASH_DEPLOY_METADATA'):
        env.pop(name, None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    (installed / 'VERSION').write_text('1.0.0\n')
    write_install_info(installed, make_install_info('stable', '1.0.0', 'b'*40, 'v1.0.0'))
    prepared = execute(prepare_only=True)
    (source / 'update.sh').write_bytes(prepared.read_bytes())
    for name in ('install.sh', 'uninstall.sh'):
        (source / name).write_text('#!/bin/bash\n')
    if hasattr(request, 'param'):
        (source / 'VERSION').write_text(request.param + '\n')
    # Bind the mock release to the actual fixture archive, including after a
    # metadata-only release bump. Tests can deliberately override this tag.
    env['TEST_RELEASE_TAG'] = normalize_tag(read_version(source / 'VERSION'))
    archive = tmp_path / 'release.tar.gz'
    with tarfile.open(archive, 'w:gz') as output:
        output.add(source, arcname='project')
    # Real standalone bootstrap, only trusted test-copy root/path relocation.
    remote = tmp_path / 'remote-update.sh'
    text = local_guard_copy((ROOT / 'remote-update.sh').read_text(), tmp_path / 'deployment-guard')
    text = text.replace("INSTALL_DIR = Path('/opt/clash-yaml-manager')", f'INSTALL_DIR = Path({str(installed)!r})')
    text = text.replace('if not args.resolve_only and os.geteuid() != 0:', 'if False:')
    remote.write_text(text)
    curl = tmp_path / 'commands/curl'
    curl.write_text('#!' + sys.executable + '\n' + '''import json,os,shutil,sys
from pathlib import Path
args=sys.argv[1:];url=args[-1];target=Path(args[args.index('--output')+1])
with Path(os.environ['TEST_EVENTS']).open('a') as log:log.write('FETCH '+url+'\\n')
if '/releases/' in url:target.write_text(json.dumps(dict(tag_name=os.environ['TEST_RELEASE_TAG'],draft=False,prerelease=False)))
elif '/commits/' in url:target.write_text(json.dumps(dict(sha='a'*40)))
else:shutil.copyfile(os.environ['TEST_ARCHIVE'],target)
print('200',end='')
''')
    curl.chmod(0o700);env['TEST_ARCHIVE'] = str(archive)
    def settings(mode, quiet):
        for name, value in [('CLASH_BACKUP_SIDECAR_MODE', mode), ('CLASH_BACKUP_EXTERNAL_WRITERS_QUIET', quiet)]:
            if value is None: env.pop(name, None)
            else: env[name] = value
    def run(path):
        return subprocess.run(['bash', str(prepared if path == 'direct' else remote)], cwd=source,
                              env=env, capture_output=True, text=True, timeout=20)
    def unchanged(before):
        assert frozen(installed) == before
        assert not events.exists()
        assert not list(tmp_path.glob('upgrade-backup-*'))
        assert not list(tmp_path.glob('sidecars*'))
        assert not list(tmp_path.glob('clash-yaml-manager-update-*'))
    return installed, env, events, settings, run, unchanged


@pytest.mark.parametrize('path', ['direct', 'remote'])
@pytest.mark.parametrize('mode,quiet,code', INVALID)
def test_invalid_admission_has_no_deployment_effects(admission, path, mode, quiet, code):
    installed, env, events, settings, run, unchanged = admission
    settings(mode, quiet);before = frozen(installed)
    result = run(path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'Sidecar preflight refused: ' + code in result.stderr
    assert 'mode-secret-sentinel' not in result.stderr
    unchanged(before)  # Includes auth, metadata, venv, env and runtime bytes/modes.


@pytest.mark.parametrize('path', ['direct', 'remote'])
@pytest.mark.parametrize('mode,quiet', VALID)
@pytest.mark.parametrize('admission', ['1.7.0', '1.8.0'], indirect=True)
def test_valid_admission_enters_original_backup_and_pip(admission, path, mode, quiet):
    installed, env, events, settings, run, unchanged = admission
    settings(mode, quiet);env['TEST_PIP_FAIL'] = '1'
    identity = (installed / 'INSTALLATION.json').read_bytes()
    result = run(path)
    assert result.returncode == 1  # Deliberate dependency failure after admission.
    assert 'Sidecar preflight refused' not in result.stderr
    assert 'pip install' in events.read_text()
    assert not (installed / 'state/auth.json').exists()
    assert (installed / 'INSTALLATION.json').read_bytes() == identity
    assert len(list(installed.parent.glob('upgrade-backup-*'))) == 1
    assert not list(installed.parent.glob('sidecars*'))
    assert 'SIDECAR_STATUS=NOT_RUN' in result.stderr if mode in ('OPTIONAL', 'STRICT') else 'SIDECAR_STATUS' not in result.stderr


@pytest.mark.parametrize('admission', ['1.7.0', '1.8.0'], indirect=True)
@pytest.mark.parametrize('mode,quiet', [('OFF', None), ('OPTIONAL', 'YES'), ('STRICT', 'YES')])
def test_remote_rejects_release_archive_version_mismatch(admission, mode, quiet):
    installed, env, events, settings, run, unchanged = admission
    settings(mode, quiet)
    env['TEST_RELEASE_TAG'] = 'v1.8.0' if env['TEST_RELEASE_TAG'] == 'v1.7.0' else 'v1.7.0'
    before = frozen(installed)
    result = run('remote')
    assert result.returncode == 1
    assert 'Invalid release archive or VERSION/tag mismatch' in result.stderr
    assert 'Sidecar preflight refused' not in result.stderr
    assert frozen(installed) == before
    assert events.exists() and all(line.startswith('FETCH ') for line in events.read_text().splitlines())
    assert not list(installed.parent.glob('upgrade-backup-*'))
    assert not list(installed.parent.glob('sidecars*'))
    assert not list(installed.parent.glob('clash-yaml-manager-update-*'))


@pytest.mark.parametrize('path', ['direct', 'remote'])
@pytest.mark.parametrize('mode,quiet', [(None,None), ('OFF',None), ('INVALID','YES'), ('STRICT',None)])
def test_guard_conflict_precedes_admission_and_returns_75(admission, isolated_guard, path, mode, quiet):
    installed, env, events, settings, run, unchanged = admission
    settings(mode, quiet);before=frozen(installed)
    if path == 'remote':
        env['CLASH_DEPLOYMENT_GUARD_FDS'] = 'already-held'  # Cannot skip parent's real lock.
    with isolated_guard.held_deployment_guard():
        result=run(path)
    assert result.returncode == 75 and 'DEPLOYMENT_GUARD_CONFLICT' in result.stderr
    assert 'Sidecar preflight refused' not in result.stderr
    unchanged(before)


def test_remote_current_version_still_validates_before_resolution(admission):
    installed, env, events, settings, run, unchanged=admission
    (installed/'VERSION').write_text('1.7.0\n')
    write_install_info(installed,make_install_info('stable','1.7.0','b'*40,'v1.7.0'))
    settings('',None);before=frozen(installed)
    result=run('remote')
    assert result.returncode==1 and 'INVALID_MODE' in result.stderr
    unchanged(before)


def test_plain_environment_string_cannot_bypass_direct_guard(admission):
    installed, env, events, settings, run, unchanged=admission
    settings('INVALID','YES');env['CLASH_DEPLOYMENT_GUARD_FDS']='already-held'
    before=frozen(installed);result=run('direct')
    assert result.returncode==78 and 'DEPLOYMENT_GUARD' in result.stderr
    assert 'Sidecar preflight refused' not in result.stderr
    unchanged(before)
