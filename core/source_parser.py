"""Offline, bounded imports of VMess/VLESS/Trojan nodes; never import base YAML settings."""
import base64
import binascii
import math
from types import FunctionType, SimpleNamespace

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from core import parser
from core.source_errors import SourceError

MAX_PAYLOAD = 10 * 1024 * 1024
FORMATS = ('auto', 'clash', 'raw', 'base64')


def _plain(value, depth=0, budget=None, ancestors=None):
    """Reject cycles, object tags, non-string mapping keys and alias expansion bombs."""
    budget = [100000] if budget is None else budget
    ancestors = set() if ancestors is None else ancestors
    budget[0] -= 1
    if budget[0] < 0 or depth > 32:
        raise SourceError('invalid')
    if type(value) in (dict, list):
        identity = id(value)
        if identity in ancestors:
            raise SourceError('invalid')
        ancestors.add(identity)
        try:
            if isinstance(value, dict):
                if any(type(key) is not str for key in value):
                    raise SourceError('invalid')
                return {key: _plain(item, depth + 1, budget, ancestors) for key, item in value.items()}
            return [_plain(item, depth + 1, budget, ancestors) for item in value]
        finally:
            ancestors.remove(identity)
    if type(value) not in (str, int, float, bool, type(None)) or (
            type(value) is float and not math.isfinite(value)):
        raise SourceError('invalid')
    if isinstance(value, str):
        # JSON-style YAML escapes can produce a UTF-16 surrogate pair. Normalize
        # it before country/name comparison; reject lone surrogates during decode.
        return value.encode('utf-16', 'surrogatepass').decode('utf-16')
    return value


def combine(results, require_nodes=True):
    result = dict(nodes=[], countries=[], node_names=[], warnings=[], errors=[])
    seen = set()
    for item in results:
        if item['errors']:
            raise SourceError('invalid')
        for node in item['nodes']:
            if node['name'] in seen:
                raise SourceError('duplicate')
            seen.add(node['name'])
        for field in ('nodes', 'countries', 'node_names', 'warnings'):
            result[field].extend(item.get(field, []))
    if require_nodes and not result['nodes']:
        raise SourceError('empty')
    return result


def _raw(text, country_lookup=None):
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    if not lines:
        raise SourceError('empty')
    if any(not line.startswith(parser.SUPPORTED_URI_SCHEMES) or '|' in line for line in lines):
        raise SourceError('invalid')
    # Parse individually so duplicate failures retain a fixed, specific error code.
    results = []
    for index, line in enumerate(lines, 1):
        try:
            name, node, info = parser.parse_node_line(line, index, country_lookup=country_lookup)
        except (ValueError, TypeError, AttributeError):
            raise SourceError('invalid') from None
        results.append(dict(nodes=[node], node_names=[name], errors=[], countries=[
            dict(node_name=name, code=info['code'], group=info['group'])]))
    return combine(results)


def _clash(data, country_lookup=None):
    data = _plain(data)
    if not isinstance(data, dict) or not isinstance(data.get('proxies'), list):
        raise SourceError('format')
    results, skipped = [], 0
    for node in data['proxies']:
        if not isinstance(node, dict) or not isinstance(node.get('type'), str):
            raise SourceError('invalid')
        if node['type'] not in ('vmess', 'vless', 'trojan'):
            skipped += 1
            continue
        if any(not isinstance(node.get(field), str) or not node[field].strip()
               for field in (('name', 'server') if node['type'] == 'trojan' else ('name', 'server', 'uuid'))):
            raise SourceError('invalid')
        try:
            node['port'] = parser.parse_port(node.get('port'))
            if node['type'] == 'trojan':
                parser.validate_trojan_options(node)
        except ValueError:
            raise SourceError('invalid') from None
        code = parser.detect_country(node['name'])
        if code == 'UNKNOWN' and country_lookup is not None:
            code = country_lookup.country(node['server']) or 'UNKNOWN'
        node['name'] = parser.build_display_name(code, node['name'])
        results.append(dict(nodes=[node], node_names=[node['name']], errors=[],
                            countries=[dict(node_name=node['name'], code=code,
                                            group=parser.COUNTRY_MAPPING[code]['group'])]))
    result = combine(results)
    if skipped:
        result['warnings'] = [f'{skipped} unsupported proxies skipped']
    return result


def _private_safe_yaml():
    """Same safe scalar semantics, without warnings that echo private values.

    As in Diff Preview, clone only the instance's float constructor; never modify
    global warning filters or the dependency's shared constructor registry.
    """
    engine = YAML(typ='safe')
    constructor = engine.constructor
    tag = 'tag:yaml.org,2002:float'
    original = constructor.yaml_constructors[tag]
    scope = dict(original.__globals__, warnings=SimpleNamespace(warn=lambda *args, **kwargs: None))
    quiet = FunctionType(original.__code__, scope, original.__name__, original.__defaults__, original.__closure__)
    quiet.__kwdefaults__ = original.__kwdefaults__
    constructor.yaml_constructors = dict(constructor.yaml_constructors)
    constructor.yaml_constructors[tag] = quiet
    return engine


def parse(payload, format='auto', country_lookup=None):
    if format not in FORMATS:
        raise SourceError('format')
    if not isinstance(payload, bytes) or len(payload) > MAX_PAYLOAD:
        raise SourceError('size')
    try:
        text = payload.decode('utf-8-sig')
        data = None
        if format in ('auto', 'clash'):
            try:
                data = _private_safe_yaml().load(text)
            except (YAMLError, RecursionError):
                if format == 'clash':
                    raise SourceError('invalid') from None
            if format == 'clash' or isinstance(data, dict) and isinstance(data.get('proxies'), list):
                return _clash(data, country_lookup)
        if format == 'raw' or format == 'auto' and any(
                line.lstrip().startswith(parser.SUPPORTED_URI_SCHEMES) for line in text.splitlines()):
            return _raw(text, country_lookup)
        compact = ''.join(text.split())
        decoded = base64.b64decode(compact + '=' * (-len(compact) % 4), altchars=b'-_', validate=True)
        if len(decoded) > MAX_PAYLOAD:
            raise SourceError('size')
        return _raw(decoded.decode('utf-8-sig'), country_lookup)
    except SourceError:
        raise
    except (ValueError, UnicodeError, binascii.Error, RecursionError, YAMLError):
        raise SourceError('invalid') from None
