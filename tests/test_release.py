from pathlib import Path
import subprocess

import pytest

from conftest import ROOT
from core.version import bump_version, normalize_tag, parse_version, read_version
from scripts import release as r
from scripts.build_bootstraps import render


@pytest.mark.parametrize('value', ['0.0.0', '1.2.3', '12.34.56'])
def test_version_parsing(value, tmp_path):
    (tmp_path / 'VERSION').write_text(value + '\n')
    assert read_version(tmp_path / 'VERSION') == value
    assert parse_version(value) == tuple(map(int, value.split('.')))
    assert normalize_tag(value) == normalize_tag('v' + value) == 'v' + value


@pytest.mark.parametrize('value', ['', 'v1.0.0', '01.2.3', '1.0', '1.0.0-beta', '1.0.0+meta',
                                  '1.0.0\n', '1.0.0 ', '１.0.0', '-1.0.0', '1.2.3.4'])
def test_invalid_semver(value):
    with pytest.raises(ValueError):
        parse_version(value)


@pytest.mark.parametrize('kind, expected', [('patch', '2.3.5'), ('minor', '2.4.0'), ('major', '3.0.0')])
def test_bump(kind, expected):
    assert bump_version('2.3.4', kind) == expected


def test_previous_stable_ignores_drafts_prereleases_and_nonsemver():
    entries = [dict(tag_name='v1.0.1'), dict(tag_name='v1.2.0'), dict(tag_name='v9.0.0', draft=True),
               dict(tag_name='v8.0.0', prerelease=True), dict(tag_name='nightly')]
    assert r.latest_stable(entries) == '1.2.0'
    assert r.latest_stable([]) is None


def test_readme_markers_only_and_email_exclusion():
    text = (ROOT / 'README.md').read_text()
    assert r.PRIVATE_EMAIL not in text
    updated = r.update_readme(text, '8.9.10')
    assert 'Latest Stable: [v8.9.10]' in updated
    assert text.split('<!-- RELEASE:START -->')[0] == updated.split('<!-- RELEASE:START -->')[0]
    assert text.split('<!-- UPDATE:END -->')[1] == updated.split('<!-- UPDATE:END -->')[1]
    with pytest.raises(r.ReleaseError):
        r.update_readme(text + r.PRIVATE_EMAIL, '8.9.10')
    with pytest.raises(r.ReleaseError):
        r.replace_marker(text, 'MISSING', '')
    with pytest.raises(r.ReleaseError):
        r.replace_marker(text + '<!-- RELEASE:START -->', 'RELEASE', '')


def test_changelog_promotion_and_exact_section():
    original = '# Changelog\n\n## Unreleased\n\n### Fixed\n- Correct actual behavior.\n\n## v1.0.0 - 2020-01-01\n\nOld.\n'
    updated = r.insert_changelog(original, '1.0.1', '2026-09-26')
    assert '## v1.0.1 - 2026-09-26' in updated
    assert r.extract_notes(updated, '1.0.1') == '### Fixed\n- Correct actual behavior.'
    assert updated.endswith('## v1.0.0 - 2020-01-01\n\nOld.\n')
    with pytest.raises(r.ReleaseError):
        r.insert_changelog(updated, '1.0.1')
    with pytest.raises(r.ReleaseError):
        r.insert_changelog(updated, '1.0.2')  # empty Unreleased cannot publish raw git log


@pytest.mark.parametrize('source', ['local', 'remote', 'release'])
def test_existing_release_rejected(source):
    with pytest.raises(r.ReleaseError):
        r.reject_existing_tag('v1.0.1', ['v1.0.1'] if source == 'local' else [],
                              ['refs/tags/v1.0.1'] if source == 'remote' else [],
                              [dict(tag_name='v1.0.1')] if source == 'release' else [])


@pytest.fixture
def clean_repository(tmp_path):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path, text=True).strip()
    git('init', '-b', 'main')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.invalid')
    git('remote', 'add', 'origin', 'https://github.com/wwintj/clash-yaml-manager.git')
    (tmp_path / 'VERSION').write_text('1.0.0\n')
    git('add', '.')
    git('commit', '-m', 'baseline')
    return tmp_path, git


def test_dirty_tree_and_non_main_rejected(clean_repository):
    root, git = clean_repository
    assert r.check_tree(root).endswith('.git')
    (root / 'uncommitted').touch()
    with pytest.raises(r.ReleaseError, match='clean'):
        r.check_tree(root)
    (root / 'uncommitted').unlink()
    git('checkout', '-b', 'feature')
    with pytest.raises(r.ReleaseError, match='main'):
        r.check_tree(root)


def test_dry_run_never_changes_files_refs_or_calls_publisher(clean_repository, monkeypatch):
    root, git = clean_repository
    files = {'VERSION': '1.0.1\n'}
    plan = dict(current='1.0.0', previous=None, version='1.0.1', tag='v1.0.1', origin='test',
                commits='baseline', changed='test', files=files, head=git('rev-parse', 'HEAD'))
    before = (root / 'VERSION').read_bytes(), git('show-ref'), git('status', '--porcelain')
    monkeypatch.setattr(r, 'validate', lambda _: None)
    monkeypatch.setattr(r, 'publish_tag', lambda *_: pytest.fail('dry run attempted publication'))
    r.execute_release(plan, dry_run=True, root=root)
    assert before == ((root / 'VERSION').read_bytes(), git('show-ref'), git('status', '--porcelain'))


def test_tag_must_equal_version(clean_repository):
    root, _ = clean_repository
    with pytest.raises(r.ReleaseError, match='VERSION'):
        r.publish_tag('v1.0.1', root)


def test_existing_release_only_verified_never_overwritten():
    item = dict(tag_name='v1.0.1', name='v1.0.1', draft=False, prerelease=False,
                body='Notes', html_url='https://example.invalid/release')
    assert r.verify_release(item, 'v1.0.1', 'Notes') == item['html_url']
    with pytest.raises(r.ReleaseError):
        r.verify_release(item, 'v1.0.1', 'Changed notes')


@pytest.mark.parametrize('mode', ['install', 'update'])
def test_bootstraps_match_reviewed_source(mode):
    assert (ROOT / f'remote-{mode}.sh').read_text() == render(mode)


def test_workflow_version_validation_and_token():
    from ruamel.yaml import YAML
    workflow = YAML(typ='safe').load((ROOT / '.github/workflows/release.yml').read_text())
    assert workflow['on']['push']['tags'] == ['v*']
    assert workflow['permissions'] == {'contents': 'write'}
    step = workflow['jobs']['release']['steps'][-1]
    assert '--publish-tag' in step['run'] and step['env']['GH_TOKEN'] == '${{ github.token }}'


def test_release_commit_tag_and_push_order(clean_repository, monkeypatch):
    root, git = clean_repository
    (root / 'CHANGELOG.md').write_text('# Changelog\n\n## Unreleased\n\n### Fixed\n- Verified fix.\n')
    (root / 'README.md').write_text(r.replace_marker((ROOT / 'README.md').read_text(), 'RELEASE', 'Pending'))
    git('add', '.')
    git('commit', '-m', 'reviewed changes')
    files = {'VERSION': '1.0.1\n', 'CHANGELOG.md': r.insert_changelog((root / 'CHANGELOG.md').read_text(), '1.0.1'),
             'README.md': r.update_readme((root / 'README.md').read_text(), '1.0.1')}
    plan = dict(current='1.0.0', previous=None, version='1.0.1', tag='v1.0.1', origin='test',
                commits='test', changed='test', files=files, head=git('rev-parse', 'HEAD'))
    original_run, events = r.run, []
    def run(args, root=root, capture=True):
        if args[:2] == ['git', 'ls-remote']:
            return git('rev-parse', 'HEAD') + '\trefs/heads/main' if args[-1] == 'refs/heads/main' else ''
        if args[:2] == ['git', 'push'] or args[0] == 'bash':
            events.append(args)
            return 'Resolved stable: v1.0.1' if args[0] == 'bash' else ''
        return original_run(args, root, capture)
    monkeypatch.setattr(r, 'run', run)
    monkeypatch.setattr(r, 'validate', lambda _: None)
    monkeypatch.setattr(r, 'releases', lambda: [])
    monkeypatch.setattr(r, 'publish_tag', lambda *_: events.append(['publish']) or 'test-url')
    monkeypatch.setattr(r, 'api', lambda *_: dict(tag_name='v1.0.1', name='v1.0.1', draft=False,
                         prerelease=False, body=r.extract_notes(files['CHANGELOG.md'], '1.0.1'), html_url='test-url'))
    r.execute_release(plan, root=root)
    assert events[:3] == [['git', 'push', 'origin', 'main'], ['git', 'push', 'origin', 'v1.0.1'], ['publish']]
    assert git('log', '-1', '--format=%s') == 'chore(release): v1.0.1'
    assert git('cat-file', '-t', 'v1.0.1') == 'tag'
    assert set(git('diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD').splitlines()) == set(files)
    assert git('status', '--porcelain') == ''


@pytest.mark.parametrize('remote_annotated', [True, False])
def test_actions_flattened_local_tag_checks_remote_annotation(clean_repository, monkeypatch, remote_annotated):
    root, git = clean_repository
    (root / 'README.md').write_text(r.update_readme((ROOT / 'README.md').read_text(), '1.0.0'))
    (root / 'CHANGELOG.md').write_text('# Changelog\n\n## v1.0.0 - 2026-09-26\n\n### Deployment\n- Verified.\n')
    git('add', '.')
    git('commit', '-m', 'release metadata')
    git('tag', '-a', 'v1.0.0', '-m', 'Release v1.0.0')
    tag_object, head = git('rev-parse', 'v1.0.0'), git('rev-parse', 'HEAD')
    # Reproduce checkout's local-only ref flattening in this temporary repository.
    git('update-ref', 'refs/tags/v1.0.0', head)
    original_run = r.run
    def run(args, root=root, capture=True):
        if args[:2] == ['git', 'ls-remote']:
            if remote_annotated:
                return f'{tag_object}\trefs/tags/v1.0.0\n{head}\trefs/tags/v1.0.0^{{}}'
            return f'{head}\trefs/tags/v1.0.0'
        return original_run(args, root, capture)
    monkeypatch.setattr(r, 'run', run)
    monkeypatch.setattr(r, 'releases', lambda: [dict(tag_name='v1.0.0', name='v1.0.0', draft=False,
                         prerelease=False, body='### Deployment\n- Verified.', html_url='verified-url')])
    if remote_annotated:
        assert r.publish_tag('v1.0.0', root) == 'verified-url'
    else:
        with pytest.raises(r.ReleaseError, match='annotated tag'):
            r.publish_tag('v1.0.0', root)
    assert git('cat-file', '-t', 'v1.0.0') == 'commit'  # no local ref rewrite


def test_release_validation_covers_all_deployment_entrypoints(monkeypatch):
    expected = ('install.sh', 'remote-install.sh', 'update.sh', 'remote-update.sh',
                'uninstall.sh', 'httpsctl.sh', 'mihomoctl.sh', 'scripts/deploy-common.sh')
    assert r.SHELL_SCRIPTS == expected
    calls = []
    monkeypatch.setattr(r, 'run', lambda args, *a, **kw: calls.append(args) or '')
    monkeypatch.setattr(r.shutil, 'which', lambda name: '/test/shellcheck' if name == 'shellcheck' else None)
    r.validate(ROOT)
    assert [call for call in calls if call[:2] == ['bash', '-n']] == [
        ['bash', '-n', script] for script in expected]
    assert ['shellcheck', *expected] in calls
    assert any(call[1:] == ['scripts/build_bootstraps.py', '--check'] for call in calls)
    assert any(call[1:] == ['-m', 'pip', 'check'] for call in calls)
    assert any(call[1:] == ['-m', 'pytest', '-q', '-p', 'no:cacheprovider'] for call in calls)
    assert calls[-1] == ['git', 'diff', '--check']


def test_validate_only_runs_full_validation_without_mutation(clean_repository, monkeypatch, capsys):
    root, git = clean_repository
    (root / 'README.md').write_bytes((ROOT / 'README.md').read_bytes())
    (root / 'CHANGELOG.md').write_text('# Changelog\n\n## Unreleased\n')
    (root / 'app.py').write_text('VALUE = 1\n')
    (root / 'defaults').mkdir()
    (root / 'defaults/default.yaml').write_bytes((ROOT / 'defaults/default.yaml').read_bytes())
    git('add', '.')
    git('commit', '-m', 'validation inputs; no proposed version or release notes')
    git('tag', '-a', 'v1.0.0', '-m', 'Existing stable')
    release = dict(tag_name='v1.0.0', body='Immutable existing release')
    def snapshot():
        return (git('rev-parse', 'HEAD'), git('show-ref'), git('status', '--porcelain'),
                {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*')
                 if path.is_file() and '.git' not in path.relative_to(root).parts}, dict(release))
    before = snapshot()
    def forbidden(*args, **kwargs):
        pytest.fail('validate-only attempted release planning or publication')
    for name in ('plan_release', 'execute_release', 'publish_tag', 'api', 'releases'):
        monkeypatch.setattr(r, name, forbidden)
    calls = []
    def validation_command(args, *a, **kw):
        assert (args[:2] == ['bash', '-n'] or args[0] == 'shellcheck'
                or args[1:] == ['scripts/build_bootstraps.py', '--check']
                or args[1:] == ['-m', 'pip', 'check']
                or args[1:] == ['-m', 'pytest', '-q', '-p', 'no:cacheprovider']
                or args == ['git', 'diff', '--check']), args
        calls.append(args)
        return ''
    monkeypatch.setattr(r, 'run', validation_command)
    monkeypatch.setattr(r.shutil, 'which', lambda name: '/test/shellcheck')
    validation = r.validate
    monkeypatch.setattr(r, 'validate', lambda: validation(root))
    r.main(['--validate-only'])
    assert snapshot() == before
    assert len([call for call in calls if call[:2] == ['bash', '-n']]) == 8
    assert ['shellcheck', *r.SHELL_SCRIPTS] in calls
    assert any(call[1:] == ['scripts/build_bootstraps.py', '--check'] for call in calls)
    assert any(call[1:] == ['-m', 'pip', 'check'] for call in calls)
    assert any(call[1:] == ['-m', 'pytest', '-q', '-p', 'no:cacheprovider'] for call in calls)
    assert calls[-1] == ['git', 'diff', '--check']
    assert 'Validation: PASS' in capsys.readouterr().out


def test_validate_only_returns_nonzero_when_validation_fails(monkeypatch, capsys):
    def fail():
        raise r.ReleaseError('Synthetic validation failure')
    monkeypatch.setattr(r, 'validate', fail)
    monkeypatch.setattr(r, 'plan_release', lambda *a: pytest.fail('planned a version'))
    with pytest.raises(SystemExit) as error:
        r.main(['--validate-only'])
    assert error.value.code == 1
    assert 'Synthetic validation failure' in capsys.readouterr().err


@pytest.mark.parametrize('arguments', [['patch'], ['--version', '1.9.0'],
                                     ['--dry-run'], ['--publish-tag', 'v1.0.0']])
def test_validate_only_rejects_all_publication_modes(arguments, monkeypatch):
    monkeypatch.setattr(r, 'validate', lambda: pytest.fail('ambiguous mode ran validation'))
    with pytest.raises(SystemExit) as error:
        r.main(['--validate-only', *arguments])
    assert error.value.code == 2


def test_release_candidate_workflow_is_manual_read_only_and_reuses_validation():
    from ruamel.yaml import YAML
    workflow = YAML(typ='safe').load((ROOT / '.github/workflows/release-candidate.yml').read_text())
    assert set(workflow['on']) == {'workflow_dispatch'}
    assert workflow['on']['workflow_dispatch']['inputs']['ref']['default'] == 'main'
    assert workflow['permissions'] == {'contents': 'read'}
    job = workflow['jobs']['validate']
    assert job['runs-on'] == 'ubuntu-latest'
    steps = job['steps']
    assert steps[0]['with'] == {'ref': "${{ inputs.ref || 'main' }}", 'fetch-depth': 0,
                                'persist-credentials': False}
    assert 'Validated commit SHA:' in steps[1]['run'] and 'git rev-parse HEAD' in steps[1]['run']
    assert 'shellcheck --version' in steps[1]['run']
    assert steps[2]['with']['python-version'] == '3.12'
    assert steps[3]['run'] == 'python -m pip install -r requirements-dev.txt'
    assert steps[4]['run'] == 'python scripts/release.py --validate-only'
    assert not any('GH_TOKEN' in step.get('env', {}) for step in steps)
