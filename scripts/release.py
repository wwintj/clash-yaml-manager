#!/usr/bin/env python3
"""Validate, prepare and publish an immutable stable release. Never force-push."""
import argparse
from datetime import date
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.version import bump_version, normalize_tag, parse_version, read_version

REPO = 'wwintj/clash-yaml-manager'
DEFAULT_SHA256 = 'a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b'
PRIVATE_EMAIL = 'wwintj' + '@gmail.com'
RAW = f'https://raw.githubusercontent.com/{REPO}/main'
SHELL_SCRIPTS = ('install.sh', 'remote-install.sh', 'update.sh', 'remote-update.sh',
                 'uninstall.sh', 'httpsctl.sh', 'mihomoctl.sh', 'scripts/deploy-common.sh')


class ReleaseError(RuntimeError):
    pass


def run(arguments, root=ROOT, capture=True):
    result = subprocess.run(arguments, cwd=root, text=True, capture_output=capture,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    if result.returncode:
        # Do not echo credential-bearing environments or raw API errors.
        raise ReleaseError(f'Command failed: {arguments[0]} {arguments[1]} (exit {result.returncode})')
    return result.stdout.strip() if capture else ''


def api(endpoint):
    try:
        return json.loads(run(['gh', 'api', endpoint]))
    except json.JSONDecodeError:
        raise ReleaseError('Malformed GitHub API response.') from None


def releases():
    try:
        pages = json.loads(run(['gh', 'api', '--paginate', '--slurp', f'repos/{REPO}/releases?per_page=100']))
        if (not isinstance(pages, list) or any(not isinstance(page, list) for page in pages)
                or any(not isinstance(item, dict) for page in pages for item in page)):
            raise TypeError
        return [release for page in pages for release in page]
    except (TypeError, json.JSONDecodeError):
        raise ReleaseError('Malformed GitHub releases list.') from None


def latest_stable(items):
    versions = []
    for item in items:
        if item.get('draft') or item.get('prerelease'):
            continue
        tag = item.get('tag_name', '')
        if not isinstance(tag, str):
            continue
        try:
            if normalize_tag(tag) == tag:
                versions.append(tag[1:])
        except ValueError:
            continue
    return max(versions, key=parse_version) if versions else None


def replace_marker(text, name, content):
    start, end = f'<!-- {name}:START -->', f'<!-- {name}:END -->'
    if text.count(start) != 1 or text.count(end) != 1 or text.index(start) > text.index(end):
        raise ReleaseError(f'README needs exactly one ordered {name} marker pair.')
    before, rest = text.split(start)
    _, after = rest.split(end)
    return before + start + '\n' + content.rstrip() + '\n' + end + after


def update_readme(text, version):
    parse_version(version)
    if PRIVATE_EMAIL in text:
        raise ReleaseError('README contains the removed contact address.')
    text = replace_marker(text, 'RELEASE',
        f'**Latest Stable: [v{version}](https://github.com/{REPO}/releases/tag/v{version})**')
    for mode, marker in [('install', 'INSTALL'), ('update', 'UPDATE')]:
        text = replace_marker(text, marker,
            f'```bash\ncurl -fsSL {RAW}/remote-{mode}.sh | sudo bash\n```')
    return text


def insert_changelog(text, version, today=None):
    """Promote reviewed, diff-based Unreleased prose; never paste a commit log."""
    parse_version(version)
    if re.search(r'^## v' + re.escape(version) + r'(?:\s|$)', text, re.M):
        raise ReleaseError('CHANGELOG already contains this version.')
    match = re.search(r'^## Unreleased\s*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    if not match:
        raise ReleaseError('Missing Unreleased notes; summarize the actual diff first.')
    body = match.group(1).strip()
    if not body or not re.search(r'^- \S', body, re.M):
        raise ReleaseError('Unreleased notes are empty; prepare diff-based release notes first.')
    for title in re.findall(r'^### (.+)$', body, re.M):
        if title not in ('Added', 'Changed', 'Fixed', 'Security', 'Deployment'):
            raise ReleaseError('Unsupported CHANGELOG category.')
    block = f'## Unreleased\n\n## v{version} - {today or date.today().isoformat()}\n\n{body}\n\n'
    return (text[:match.start()] + block + text[match.end():]).rstrip() + '\n'


def extract_notes(text, version):
    match = re.search(r'^## v' + re.escape(version) + r' - \d{4}-\d{2}-\d{2}\n(.*?)(?=^## |\Z)',
                      text, re.M | re.S)
    if not match or not match.group(1).strip():
        raise ReleaseError('Current release section is missing or empty.')
    return match.group(1).strip()


def check_tree(root=ROOT):
    if run(['git', 'branch', '--show-current'], root) != 'main':
        raise ReleaseError('Release requires branch main.')
    if run(['git', 'status', '--porcelain'], root):
        raise ReleaseError('Release requires a clean working tree; commit feature work first.')
    origin = run(['git', 'remote', 'get-url', 'origin'], root)
    if origin not in (f'https://github.com/{REPO}.git', f'https://github.com/{REPO}',
                      f'git@github.com:{REPO}.git'):
        raise ReleaseError('Unexpected origin; remote will not be changed.')
    push_origin = run(['git', 'remote', 'get-url', '--push', 'origin'], root)
    if push_origin != origin:
        raise ReleaseError('Fetch and push origin differ.')
    return origin


def reject_existing_tag(tag, local_tags, remote_refs, items):
    if tag in local_tags or f'refs/tags/{tag}' in remote_refs or any(r.get('tag_name') == tag for r in items):
        raise ReleaseError('Tag or GitHub Release already exists; never replace stable releases.')


def validate(root=ROOT):
    read_version(root / 'VERSION')
    if PRIVATE_EMAIL in (root / 'README.md').read_text():
        raise ReleaseError('README email check failed.')
    if hashlib.sha256((root / 'defaults/default.yaml').read_bytes()).hexdigest() != DEFAULT_SHA256:
        raise ReleaseError('Default YAML changed; explicit review required.')
    for path in [root / 'app.py', *root.glob('core/*.py'), *root.glob('scripts/*.py'), *root.glob('tests/*.py')]:
        compile(path.read_bytes(), str(path), 'exec')
    print('Python syntax / README email / default YAML byte check: PASS', flush=True)
    for script in SHELL_SCRIPTS:
        run(['bash', '-n', script], root)
    run([sys.executable, 'scripts/build_bootstraps.py', '--check'], root)
    print('bash -n / bootstrap synchronization: PASS', flush=True)
    if shutil.which('shellcheck'):
        run(['shellcheck', *SHELL_SCRIPTS], root, capture=False)
    else:
        print('ShellCheck: unavailable', flush=True)
    python = str(root / '.venv/bin/python') if (root / '.venv/bin/python').exists() else sys.executable
    run([python, '-m', 'pip', 'check'], root, capture=False)
    run([python, '-m', 'pytest', '-q', '-p', 'no:cacheprovider'], root, capture=False)
    run(['git', 'diff', '--check'], root)
    print('Validation: PASS (includes 10,410-rule round trip)', flush=True)


def plan_release(kind=None, version=None, root=ROOT):
    origin = check_tree(root)
    current = read_version(root / 'VERSION')
    items = releases()
    previous = latest_stable(items)
    proposed = version or bump_version(current, kind or 'patch')
    if parse_version(proposed) <= parse_version(current):
        raise ReleaseError('Requested version must exceed current VERSION.')
    if previous and parse_version(proposed) <= parse_version(previous):
        raise ReleaseError('Requested version must exceed previous stable.')
    tag = normalize_tag(proposed)
    refs = dict(line.split()[::-1] for line in run(['git', 'ls-remote', 'origin'], root).splitlines())
    reject_existing_tag(tag, run(['git', 'tag'], root).splitlines(), refs, items)
    remote_head = refs.get('refs/heads/main')
    if not remote_head:
        raise ReleaseError('origin/main not found.')
    run(['git', 'merge-base', '--is-ancestor', remote_head, 'HEAD'], root)
    info = api(f'repos/{REPO}')
    if info.get('default_branch') != 'main' or not info.get('permissions', {}).get('push'):
        raise ReleaseError('GitHub write permission or default branch check failed.')
    base = refs.get(f'refs/tags/v{previous}^{{}}') or refs.get(f'refs/tags/v{previous}') if previous else None
    if previous and not base:
        raise ReleaseError('Previous stable tag is missing on origin.')
    history = f'{base}..HEAD' if base else 'HEAD'
    files = {
        'VERSION': proposed + '\n',
        'CHANGELOG.md': insert_changelog((root / 'CHANGELOG.md').read_text(), proposed),
        'README.md': update_readme((root / 'README.md').read_text(), proposed),
    }
    return dict(current=current, previous=previous, version=proposed, tag=tag, origin=origin,
                head=run(['git', 'rev-parse', 'HEAD'], root), files=files,
                commits=run(['git', 'log', '--format=%h %s', history], root),
                changed=run(['git', 'diff', '--stat', base, 'HEAD'], root) if base else 'First formal release: complete repository history')


def show_plan(plan, root=ROOT):
    for label, value in [('Current stable version', plan['previous'] or 'none (no published stable)'),
                         ('Current VERSION', plan['current']), ('Proposed version', plan['version']),
                         ('Tag', plan['tag']), ('Remote', plan['origin']),
                         ('Commits included', plan['commits']), ('Diff scope', plan['changed'])]:
        print(f'{label}: {value}', flush=True)
    print('Files that would change: VERSION, CHANGELOG.md, README.md', flush=True)
    for name, content in plan['files'].items():
        print(''.join(difflib.unified_diff((root / name).read_text().splitlines(True), content.splitlines(True),
                                        fromfile=name, tofile=name)), flush=True)
    print('Tests: full pytest, syntax, dependencies, shell, default YAML, README, git diff', flush=True)


def verify_release(item, tag, notes):
    if (item.get('tag_name') != tag or item.get('name') != tag or item.get('draft') is not False
            or item.get('prerelease') is not False or (item.get('body') or '').strip() != notes.strip()):
        raise ReleaseError('Existing Release metadata differs; it will not be overwritten.')
    return item['html_url']


def publish_tag(tag, root=ROOT):
    if normalize_tag(tag) != tag or read_version(root / 'VERSION') != tag[1:]:
        raise ReleaseError('VERSION must exactly match the release tag.')
    commit = run(['git', 'rev-parse', tag + '^{}'], root)
    if commit != run(['git', 'rev-parse', 'HEAD'], root):
        raise ReleaseError('HEAD must equal the release tag commit.')
    notes = extract_notes((root / 'CHANGELOG.md').read_text(), tag[1:])
    if (root / 'README.md').read_text() != update_readme((root / 'README.md').read_text(), tag[1:]):
        raise ReleaseError('README metadata does not match VERSION/tag.')
    refs = dict(line.split()[::-1] for line in run(['git', 'ls-remote', 'origin', 'refs/tags/' + tag + '*'], root).splitlines())
    if refs.get(f'refs/tags/{tag}^{{}}') != commit:
        raise ReleaseError('Remote annotated tag does not match this commit.')
    # actions/checkout can flatten the runner's local tag ref to the event SHA.
    # Validate the authoritative remote tag object, without replacing any refs.
    tag_object = refs[f'refs/tags/{tag}']
    try:
        object_type = run(['git', 'cat-file', '-t', tag_object], root)
    except ReleaseError:
        run(['git', 'fetch', '--no-tags', 'origin', tag_object], root)
        object_type = run(['git', 'cat-file', '-t', tag_object], root)
    if object_type != 'tag' or run(['git', 'rev-parse', tag_object + '^{}'], root) != commit:
        raise ReleaseError('Remote release tag must be an annotated object pointing to HEAD.')
    existing = next((r for r in releases() if r.get('tag_name') == tag), None)
    if existing:
        # Tag workflow may race the local publisher. Verify only; never edit.
        return verify_release(existing, tag, notes)
    with tempfile.TemporaryDirectory(prefix='clash-release-notes-') as work:
        path = Path(work) / 'notes.md'
        path.write_text(notes + '\n')
        try:
            run(['gh', 'release', 'create', tag, '--repo', REPO, '--verify-tag', '--title', tag,
                 '--notes-file', str(path), '--latest'], root)
        except ReleaseError:
            # If another publisher won the race, only identical metadata is accepted.
            existing = next((r for r in releases() if r.get('tag_name') == tag), None)
            if existing is None:
                raise
            return verify_release(existing, tag, notes)
    return verify_release(api(f'repos/{REPO}/releases/tags/{tag}'), tag, notes)


def execute_release(plan, dry_run=False, root=ROOT):
    show_plan(plan, root)
    validate(root)
    check_tree(root)
    if run(['git', 'rev-parse', 'HEAD'], root) != plan['head']:
        raise ReleaseError('HEAD changed during validation.')
    print('Release preflight: PASS', flush=True)
    if dry_run:
        print('Release dry run: PASS; no project files, refs or remote objects changed.', flush=True)
        return
    # Recheck remote state after tests, before creating metadata and refs.
    refs = [line.split()[1] for line in run(['git', 'ls-remote', '--tags', 'origin'], root).splitlines()]
    reject_existing_tag(plan['tag'], run(['git', 'tag'], root).splitlines(), refs, releases())
    for name, content in plan['files'].items():
        (root / name).write_text(content)
    run(['git', 'diff', '--check'], root)
    run(['git', 'add', '--', *plan['files']], root)
    run(['git', 'commit', '-m', f'chore(release): {plan["tag"]}'], root, capture=False)
    run(['git', 'tag', '-a', plan['tag'], '-m', f'Release {plan["tag"]}'], root)
    run(['git', 'push', 'origin', 'main'], root, capture=False)
    run(['git', 'push', 'origin', plan['tag']], root, capture=False)
    url = publish_tag(plan['tag'], root)
    remote = run(['git', 'ls-remote', 'origin', 'refs/heads/main'], root).split()[0]
    if remote != run(['git', 'rev-parse', 'HEAD'], root):
        raise ReleaseError('origin/main moved; inspect remote before claiming success.')
    latest = api(f'repos/{REPO}/releases/latest')
    verify_release(latest, plan['tag'], extract_notes(plan['files']['CHANGELOG.md'], plan['version']))
    print('GitHub Release: ' + url, flush=True)
    for mode in ('install', 'update'):
        resolved = run(['bash', f'remote-{mode}.sh', '--resolve-only'], root)
        if f'Resolved stable: {plan["tag"]}' not in resolved.splitlines():
            raise ReleaseError(f'remote-{mode} did not resolve the published stable tag.')
        print(f'remote-{mode}: {resolved}', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bump', nargs='?', choices=('patch', 'minor', 'major'))
    parser.add_argument('--version')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--publish-tag', help='Verify an existing annotated tag and publish; used by Actions/recovery')
    args = parser.parse_args(argv)
    if args.bump and args.version or args.publish_tag and (args.bump or args.version or args.dry_run):
        parser.error('Choose one version mode.')
    try:
        if args.publish_tag:
            validate()
            print('GitHub Release: ' + publish_tag(args.publish_tag), flush=True)
        else:
            execute_release(plan_release(args.bump, args.version), args.dry_run)
    except (ReleaseError, ValueError, OSError) as error:
        parser.exit(1, f'Release stopped: {error}\nNo force push, tag deletion or Release overwrite was attempted.\n')


if __name__ == '__main__':
    main()
