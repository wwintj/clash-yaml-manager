"""Public build identity, separate from credentials and the stable VERSION source.

This stdlib-only module is also embedded into the standalone remote bootstraps.
INSTALLATION.json is root-owned/readable by the service, outside private auth state.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile

INSTALL_INFO_FILE = 'INSTALLATION.json'
_VERSION_PATTERN = r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
_COMMIT_PATTERN = r'[0-9a-f]{40}'


def validate_install_info(info, base_version=None):
    try:
        expected = {'channel', 'base_version', 'commit', 'tag', 'installed_at', 'source'}
        if not isinstance(info, dict) or set(info) != expected:
            raise ValueError
        version, channel = info['base_version'], info['channel']
        if not isinstance(version, str) or not re.fullmatch(_VERSION_PATTERN, version):
            raise ValueError
        if base_version is not None and version != base_version:
            raise ValueError
        if channel not in ('stable', 'main', 'local'):
            raise ValueError
        if channel == 'local':
            if info['commit'] is not None or info['tag'] is not None or info['source'] != 'local-source':
                raise ValueError
        else:
            if not isinstance(info['commit'], str) or not re.fullmatch(_COMMIT_PATTERN, info['commit']):
                raise ValueError
            if info['tag'] != ('v' + version if channel == 'stable' else None):
                raise ValueError
            if info['source'] != ('github-release' if channel == 'stable' else 'github-main'):
                raise ValueError
        timestamp = datetime.fromisoformat(info['installed_at'])
        if timestamp.tzinfo is None:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError('Invalid installation metadata; inspect INSTALLATION.json before updating.') from None
    return info


def make_install_info(channel, base_version, commit=None, tag=None):
    return validate_install_info(dict(channel=channel, base_version=base_version, commit=commit,
        tag=tag, installed_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
        source={'stable':'github-release', 'main':'github-main', 'local':'local-source'}[channel]))


def read_install_info(directory, base_version=None):
    path = Path(directory) / INSTALL_INFO_FILE
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink():
        raise ValueError('Invalid installation metadata path.')
    try:
        return validate_install_info(json.loads(path.read_text(encoding='utf-8')), base_version)
    except (OSError, ValueError):
        raise ValueError('Invalid installation metadata; inspect INSTALLATION.json before updating.') from None


def write_install_info(directory, info):
    """Publish complete, credential-free metadata atomically before service startup."""
    validate_install_info(info)
    directory = Path(directory)
    path = directory / INSTALL_INFO_FILE
    if path.is_symlink():
        raise ValueError('Invalid installation metadata path.')
    fd, temporary = tempfile.mkstemp(prefix='.installation-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as target:
            json.dump(info, target, sort_keys=True)
            target.write('\n')
            target.flush()
            os.fchmod(target.fileno(), 0o644)  # Public build data; never auth material.
            os.fsync(target.fileno())
        os.replace(temporary, path)
        parent = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def display_build(base_version, info=None):
    if info is None:
        return base_version
    validate_install_info(info, base_version)
    if info['channel'] == 'main':
        return base_version + '-dev+' + info['commit'][:7]
    if info['channel'] == 'local':
        return base_version + '-local'
    return base_version


def finalize_install(directory):
    """Called by install/update before ownership repair and service restart.

    The remote bootstrap passes a private metadata path, never credentials. Direct
    local-source deployments get an honest local identity instead of retaining a
    stale main commit. Old stable scripts are supported by bootstrap finalization.
    """
    directory = Path(directory)
    version = (directory / 'VERSION').read_text().rstrip('\n')
    incoming = os.environ.get('CLASH_DEPLOY_METADATA')
    if incoming:
        path = Path(incoming)
        if path.is_symlink():
            raise ValueError('Invalid deployment metadata path.')
        info = validate_install_info(json.loads(path.read_text()), version)
    else:
        info = make_install_info('local', version)
    write_install_info(directory, info)
    print('Installed build: ' + display_build(version, info))
