"""The root VERSION file is the sole application version source."""
from pathlib import Path
import re


def parse_version(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value):
        raise ValueError('Expected stable MAJOR.MINOR.PATCH without a v prefix.')
    return tuple(int(part) for part in value.split('.'))


def read_version(path):
    value = Path(path).read_text(encoding='utf-8').rstrip('\n')
    parse_version(value)
    return value


def normalize_tag(value):
    version = value[1:] if value.startswith('v') else value
    parse_version(version)
    return 'v' + version


def bump_version(value, kind):
    major, minor, patch = parse_version(value)
    if kind == 'major':
        return f'{major + 1}.0.0'
    if kind == 'minor':
        return f'{major}.{minor + 1}.0'
    if kind == 'patch':
        return f'{major}.{minor}.{patch + 1}'
    raise ValueError('Expected patch, minor or major.')
