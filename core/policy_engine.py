"""Pure, pinned-Mihomo group policies. No I/O or health observations belong here."""
import re
from urllib.parse import urlsplit

SCOPES = ('country_groups', 'special_groups')
TYPES = ('preserve', 'select', 'url-test', 'fallback', 'load-balance')
AUTOMATIC = TYPES[2:]
DEFAULT_URL = 'https://www.gstatic.com/generate_204'
# These bounds are product limits, narrower than Mihomo's integer storage.
MIN_INTERVAL, MAX_INTERVAL, MAX_TOLERANCE = 30, 86400, 10000
AUTO_FIELDS = ('url', 'interval', 'lazy', 'tolerance', 'strategy', 'timeout',
               'max-failed-times', 'expected-status')
# v1.19.31 parser.go/GroupBase can expand or filter the explicit candidate list.
CANDIDATE_FIELDS = ('use', 'include-all', 'include-all-proxies', 'include-all-providers',
                    'filter', 'exclude-filter', 'exclude-type', 'empty-fallback')
GENERAL_GROUPS = {'🚀 节点选择', '🚀 手动切换', '🐟 漏网之鱼'}
MESSAGE = 'Policy 配置无效，请检查类型、选项、URL 和数值范围。'


class PolicyError(ValueError):
    """Fixed non-sensitive message, never echo rejected values."""


def defaults():
    return {scope: {'type': 'preserve', 'options': {}} for scope in SCOPES}


def option_defaults(kind):
    if kind not in AUTOMATIC:
        return {}
    options = dict(url=DEFAULT_URL, interval=300, lazy=True)
    if kind == 'url-test':
        options['tolerance'] = 50
    if kind == 'load-balance':
        options['strategy'] = 'round-robin'
    return options


def valid_url(value):
    """Client test URL only: local/private HTTP(S) allowed, never resolve/fetch."""
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        return False
    if any(c.isspace() or ord(c) < 32 or 127 <= ord(c) <= 159 for c in value) or '\\' in value:
        return False
    # Also refuse percent-encoded control characters.
    if re.search(r'%(?:0[0-9a-f]|1[0-9a-f]|7f)', value, re.I):
        return False
    try:
        parts = urlsplit(value)
        return (parts.scheme in ('http', 'https') and bool(parts.hostname)
                and parts.username is None and parts.password is None
                and (parts.port is None or 1 <= parts.port <= 65535))
    except ValueError:
        return False


def normalize(config):
    """Validate exact schema and return an independent, deterministic full config."""
    if not isinstance(config, dict) or set(config) != set(SCOPES):
        raise PolicyError(MESSAGE)
    result = {}
    for scope in SCOPES:
        value = config[scope]
        if not isinstance(value, dict) or set(value) != {'type', 'options'}:
            raise PolicyError(MESSAGE)
        kind, options = value['type'], value['options']
        if not isinstance(kind, str) or kind not in TYPES or not isinstance(options, dict):
            raise PolicyError(MESSAGE)
        full = option_defaults(kind)
        if set(options) - set(full):
            raise PolicyError(MESSAGE)
        full.update(options)
        if kind in AUTOMATIC:
            if (not valid_url(full['url']) or type(full['interval']) is not int
                    or not MIN_INTERVAL <= full['interval'] <= MAX_INTERVAL
                    or type(full['lazy']) is not bool):
                raise PolicyError(MESSAGE)
        if kind == 'url-test' and (type(full['tolerance']) is not int or
                                   not 0 <= full['tolerance'] <= MAX_TOLERANCE):
            raise PolicyError(MESSAGE)
        if kind == 'load-balance' and full['strategy'] != 'round-robin':
            raise PolicyError(MESSAGE)
        result[scope] = dict(type=kind, options=full)
    return result


def form_values(config):
    result = {}
    for scope, value in normalize(config).items():
        result['policy_' + scope + '_type'] = value['type']
        # Keep useful defaults available when an operator first switches type.
        options = dict(option_defaults('url-test'), strategy='round-robin')
        options.update(value['options'])
        for key, item in options.items():
            result['policy_' + scope + '_' + key] = str(item).lower() if type(item) is bool else str(item)
    return result


def submitted_values(form):
    """Ephemeral redisplay only. Do not save these raw values in session/draft."""
    result = form_values(defaults())
    for key in result:
        if key in form:
            result[key] = form.get(key)[:2049]
    return result


def parse_form(form):
    allowed = set(form_values(defaults()))
    if any(key.startswith('policy_') and key not in allowed for key in form):
        raise PolicyError(MESSAGE)
    if hasattr(form, 'getlist') and any(len(form.getlist(key)) != 1 for key in allowed if key in form):
        raise PolicyError(MESSAGE)
    config = {}
    for scope in SCOPES:
        prefix = 'policy_' + scope + '_'
        kind = form.get(prefix + 'type', 'preserve')
        options = {}
        for key in ('url', 'interval', 'lazy', 'tolerance', 'strategy'):
            if prefix + key not in form:
                continue
            value = form.get(prefix + key)
            if key in ('interval', 'tolerance'):
                if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,5}', value):
                    raise PolicyError(MESSAGE)
                value = int(value)
            elif key == 'lazy':
                if value not in ('true', 'false'):
                    raise PolicyError(MESSAGE)
                value = value == 'true'
            options[key] = value
        config[scope] = dict(type=kind, options=options)
    return normalize(config)


def memberships(new_nodes, countries, special_groups):
    """Use structured assignments, ordered by the actual generated proxy list."""
    names = [node['name'] for node in new_nodes]
    actual = set(names)
    assigned = {}
    for item in countries:
        group, node = item.get('group'), item.get('node_name')
        if group and group not in GENERAL_GROUPS and node in actual:
            assigned.setdefault(group, set()).add(node)
    country = {group: [name for name in names if name in members] for group, members in assigned.items()}
    special = {group: list(names) for group in special_groups if group not in GENERAL_GROUPS}
    return country, special


def apply(data, new_nodes, countries, special_groups, config):
    policy = normalize(config)
    country, special = memberships(new_nodes, countries, special_groups)
    groups = {group['name']: group for group in data['proxy-groups']}
    # An explicitly selected special group takes precedence if scopes overlap.
    for scope, targets in (('country_groups', country), ('special_groups', special)):
        value = policy[scope]
        kind = value['type']
        if kind == 'preserve':
            continue
        for name, candidates in targets.items():
            if scope == 'country_groups' and name in special:
                continue
            if kind in AUTOMATIC and not candidates:
                raise PolicyError('自动策略组没有有效的新节点。旧订阅保持不变。')
            group = groups[name]
            for field in AUTO_FIELDS:
                group.pop(field, None)
            group['type'] = kind
            if kind in AUTOMATIC:
                for field in CANDIDATE_FIELDS:
                    group.pop(field, None)
                group['proxies'] = list(candidates)
                group.update(value['options'])
