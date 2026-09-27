"""Stdlib bootstrap embedded into both curl|bash entrypoints. Stable by default; main requires explicit selection."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

if __name__ == '__main__' and __file__ != '<stdin>':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.install_info import read_install_info, write_install_info, make_install_info, display_build

REPOSITORY = 'wwintj/clash-yaml-manager'
INSTALL_DIR = Path('/opt/clash-yaml-manager')
SEMVER = r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'


class LifecycleError(RuntimeError):
    pass


def version_tuple(value):
    if not re.fullmatch(SEMVER, value):
        raise LifecycleError('Invalid stable version; expected X.Y.Z or vX.Y.Z.')
    return tuple(map(int, value.split('.')))


def tag_name(value):
    if not isinstance(value, str):
        raise LifecycleError('Invalid release tag type.')
    version = value[1:] if value.startswith('v') else value
    version_tuple(version)
    return 'v' + version


def download(url, destination):
    result = subprocess.run([
        'curl', '--fail', '--silent', '--show-error', '--location',
        '--proto', '=https', '--proto-redir', '=https', '--connect-timeout', '10',
        '--max-time', '120', '--output', str(destination), '--write-out', '%{http_code}', url,
    ], capture_output=True, text=True)
    if result.returncode:
        status = result.stdout.strip()
        reason = {'404': 'Release not found', '403': 'GitHub access denied or API rate limit',
                  '429': 'GitHub API rate limit'}.get(status, 'Network/TLS/timeout or download error')
        raise LifecycleError(f'{reason} (HTTP {status or "unknown"}). Stopped; no main fallback.')


def resolve_release(directory, requested=None, fetch=download):
    endpoint = 'latest' if requested is None else 'tags/' + tag_name(requested)
    response = directory / 'release.json'
    fetch(f'https://api.github.com/repos/{REPOSITORY}/releases/{endpoint}', response)
    try:
        release = json.loads(response.read_text(encoding='utf-8'))
        tag = release['tag_name']
        if release.get('draft') is not False or release.get('prerelease') is not False:
            raise ValueError
        if tag_name(tag) != tag or (requested and tag != tag_name(requested)):
            raise ValueError
    except (KeyError, TypeError, ValueError, OSError, LifecycleError):
        raise LifecycleError('Malformed or non-stable GitHub Release response. Stopped.') from None
    return tag


def extract_archive(archive, directory, tag=None):
    """Manually extract only regular files/dirs after validating the entire archive."""
    try:
        with tarfile.open(archive, 'r:gz') as source:
            members = source.getmembers()
            if not members or len(members) > 10000 or sum(m.size for m in members) > 200 * 1024 * 1024:
                raise ValueError
            roots, names = set(), set()
            for member in members:
                path = PurePosixPath(member.name)
                if (path.is_absolute() or '..' in path.parts or '\\' in member.name or not path.parts
                        or not (member.isdir() or member.isfile()) or str(path) in names):
                    raise ValueError
                roots.add(path.parts[0])
                names.add(str(path))
            if len(roots) != 1:
                raise ValueError
            for member in members:
                target = directory / member.name
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with source.extractfile(member) as incoming, target.open('xb') as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
                    target.chmod(0o700 if member.mode & 0o111 else 0o600)
        root = directory / roots.pop()
        required = ('VERSION', 'app.py', 'requirements.txt', 'install.sh', 'update.sh',
                    'uninstall.sh', 'scripts/deploy-common.sh', 'core/security.py', 'core/version.py')
        if not all((root / name).is_file() for name in required):
            raise ValueError
        base_version = (root / 'VERSION').read_text().rstrip('\n')
        version_tuple(base_version)
        if tag is not None and base_version != tag[1:]:
            raise ValueError
        for script in ('install.sh', 'update.sh', 'uninstall.sh', 'scripts/deploy-common.sh'):
            subprocess.run(['bash', '-n', str(root / script)], check=True, capture_output=True)
        return root
    except (tarfile.TarError, OSError, ValueError, LifecycleError, subprocess.CalledProcessError):
        raise LifecycleError('Invalid release archive or VERSION/tag mismatch; nothing installed.') from None


def execute_script(root, mode, metadata):
    env = dict(os.environ, CLASH_DEPLOY_METADATA=str(metadata))
    if mode == 'install':
        # curl|bash consumes stdin. Read port/password from the controlling TTY.
        try:
            terminal = open('/dev/tty', 'r')
        except OSError:
            raise LifecycleError('Installation needs a terminal for port and hidden password input.') from None
        with terminal:
            subprocess.run(['bash', 'install.sh'], cwd=root, stdin=terminal, check=True, env=env)
    else:
        subprocess.run(['bash', 'update.sh'], cwd=root, check=True, env=env)


def resolve_commit(directory, channel, tag=None, fetch=download):
    response = directory / 'commit.json'
    endpoint = 'git/ref/heads/main' if channel == 'main' else 'commits/' + tag
    fetch(f'https://api.github.com/repos/{REPOSITORY}/{endpoint}', response)
    try:
        value = json.loads(response.read_text(encoding='utf-8'))
        if channel == 'main':
            if value['ref'] != 'refs/heads/main' or value['object']['type'] != 'commit':
                raise ValueError
            commit = value['object']['sha']
        else:
            commit = value['sha']
        if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit):
            raise ValueError
    except (KeyError, TypeError, ValueError, OSError):
        raise LifecycleError('Malformed GitHub commit response. Stopped; no channel fallback.') from None
    return commit


def run_lifecycle(mode, args, install_dir=INSTALL_DIR, fetch=download, execute=execute_script):
    channel = getattr(args, 'channel', 'stable')
    if channel not in ('stable', 'main'):
        raise LifecycleError('Invalid channel; choose stable or main.')
    if channel == 'main' and args.version:
        raise LifecycleError('--version cannot be combined with --channel main')
    if not args.resolve_only and os.geteuid() != 0:
        raise LifecycleError('Please run with sudo/root.')
    if mode == 'update' and not args.resolve_only and not (install_dir / 'app.py').is_file():
        raise LifecycleError('Existing installation not found; use remote-install.sh.')
    print(f'Channel: {channel}', flush=True)
    if channel == 'main':
        print('Development channel selected. This build is not a Stable Release.', flush=True)
    with tempfile.TemporaryDirectory(prefix=f'clash-yaml-manager-{mode}-') as work:
        directory = Path(work)
        tag = resolve_release(directory, args.version, fetch) if channel == 'stable' else None
        commit = resolve_commit(directory, channel, fetch=fetch) if channel == 'main' else None
        if tag:
            print(f'Resolved stable: {tag}', flush=True)
        if commit:
            print(f'Resolved commit: {commit}', flush=True)
        if args.resolve_only:
            return tag or commit
        current, installed_info = None, None
        if mode == 'update':
            installed = install_dir / 'VERSION'
            if installed.exists():
                current = installed.read_text().rstrip('\n')
                version_tuple(current)
                try:
                    installed_info = read_install_info(install_dir, current)
                except ValueError as error:
                    raise LifecycleError(str(error)) from None
                installed_channel = installed_info['channel'] if installed_info else 'stable'
                print('Installed build: ' + display_build(current, installed_info), flush=True)
                if installed_channel != channel:
                    print(f'Switching channel: {installed_channel} → {channel}', flush=True)
                if channel == 'main':
                    print('Installed commit: ' + str(installed_info['commit'] if installed_info else 'unknown'), flush=True)
                    print('Remote main commit: ' + commit, flush=True)
                    if installed_channel == 'main' and installed_info['commit'] == commit:
                        print('Already up to date.', flush=True)
                        return commit
                else:
                    current_tuple, target_tuple = version_tuple(current), version_tuple(tag[1:])
                    if installed_channel in ('main', 'local') and target_tuple <= current_tuple and not args.allow_downgrade:
                        raise LifecycleError('A development build is currently installed. Latest Stable is based on an older '
                            'or equal release. Refusing automatic channel downgrade; use --channel stable --allow-downgrade.')
                    if installed_channel == 'stable' and current_tuple == target_tuple:
                        print('Already up to date.', flush=True)
                        return tag
                    if target_tuple < current_tuple and not args.allow_downgrade:
                        raise LifecycleError('Downgrade refused; use --allow-downgrade explicitly.')
            else:
                if (install_dir / 'INSTALLATION.json').exists():
                    raise LifecycleError('Installation metadata exists without VERSION; inspect deployment backup.')
                print('Installed version: legacy (no VERSION); preserving existing data during migration.', flush=True)
        if commit is None:
            commit = resolve_commit(directory, 'stable', tag, fetch)
            print(f'Resolved commit: {commit}', flush=True)
        archive = directory / 'source.tar.gz'
        # Both channels download immutable commits; stable commits come only from Releases.
        fetch(f'https://codeload.github.com/{REPOSITORY}/tar.gz/{commit}', archive)
        root = extract_archive(archive, directory / 'extracted', tag)
        base_version = (root / 'VERSION').read_text().rstrip('\n')
        print(f'Base version: {base_version}', flush=True)
        info = make_install_info(channel, base_version, commit, tag)
        # Keep deployment data outside the source archive and out of .env.
        write_install_info(directory, info)
        execute(root, mode, directory / 'INSTALLATION.json')
        if (install_dir / 'VERSION').read_text().rstrip('\n') != base_version:
            raise LifecycleError('Installed VERSION verification failed; inspect deployment backup.')
        # Old stable lifecycle scripts predate metadata hooks. Finalize those too.
        write_install_info(install_dir, info)
        if read_install_info(install_dir, base_version) != info:
            raise LifecycleError('Installed build metadata verification failed.')
        print('Installed build: ' + display_build(base_version, info), flush=True)
        print(f'{mode.capitalize()} complete: {tag or commit}', flush=True)
        return tag or commit


def main(argv=None):
    parser = argparse.ArgumentParser(description='Install/update Stable by default; explicitly select main for development testing.')
    parser.add_argument('mode', choices=('install', 'update'))
    parser.add_argument('--channel', choices=('stable', 'main'), default='stable')
    parser.add_argument('--version', help='Pin a published stable release, vX.Y.Z or X.Y.Z')
    parser.add_argument('--allow-downgrade', action='store_true')
    parser.add_argument('--resolve-only', action='store_true', help='Read-only stable tag lookup; no root needed')
    args = parser.parse_args(argv)
    if args.channel == 'main' and args.version:
        parser.error('--version cannot be combined with --channel main')
    if args.mode == 'install' and args.allow_downgrade:
        parser.error('--allow-downgrade applies only to update')
    try:
        run_lifecycle(args.mode, args)
    except (LifecycleError, ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
