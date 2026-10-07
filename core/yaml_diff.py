"""Private, bounded text diff of the actual shared YAML transformation."""
import difflib
from core import yaml_utils
from ruamel.yaml.error import YAMLError

MAX_YAML_BYTES = 2 * 1024 * 1024
MAX_FORM_BYTES = 2 * 1024 * 1024
MAX_LINES = 20000
MAX_NODES = 512
MAX_SOURCE_GROUPS = 256
MAX_DIFF_BYTES = 512 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
TOO_LARGE = 'Diff is too large to display. Generate YAML is still available.'
PROCESSING_ERROR = 'YAML 处理失败，请检查配置结构、磁盘空间及目录权限。'


class PreviewValidationError(ValueError):
    """Only reviewed, safe validation messages cross the JSON boundary."""


class PreviewLimitError(PreviewValidationError):
    pass


def check_form_size(form):
    if sum(len(value.encode('utf-8')) for _, values in form.lists() for value in values) > MAX_FORM_BYTES:
        raise PreviewLimitError(TOO_LARGE)


def read_source(stream):
    raw = stream.read(MAX_YAML_BYTES + 1)
    if len(raw) > MAX_YAML_BYTES:
        raise PreviewLimitError(TOO_LARGE)
    try:
        return raw.decode('utf-8')
    except UnicodeError:
        raise PreviewValidationError(PROCESSING_ERROR) from None


def unified(source, generated):
    if source == generated:
        return ''
    if len(source.splitlines()) > MAX_LINES or len(generated.splitlines()) > MAX_LINES:
        raise PreviewLimitError(TOO_LARGE)
    chunks, size = [], 0
    for line in difflib.unified_diff(source.splitlines(keepends=True), generated.splitlines(keepends=True),
                                     fromfile='source.yaml', tofile='generated.yaml', n=3):
        # difflib leaves missing-newline lines unterminated; standard patch marker
        # keeps adjacent +/- lines distinct without pretending the newline exists.
        if not line.endswith('\n'):
            line += '\n\\ No newline at end of file\n'
        size += len(line.encode('utf-8'))
        if size > MAX_DIFF_BYTES:
            raise PreviewLimitError(TOO_LARGE)
        chunks.append(line)
    return ''.join(chunks)


def private_yaml_engine():
    """Use the same instance-private diagnostics as committed YAML loading."""
    return yaml_utils.private_yaml_engine()


def transform(source, parsed, special_groups, policy, *, node_update_mode='replace', template_profile='custom'):
    """Return the exact would-be bytes and existing counts, never publish them."""
    if len(source.encode('utf-8')) > MAX_YAML_BYTES or len(source.splitlines()) > MAX_LINES or len(parsed['nodes']) > MAX_NODES:
        raise PreviewLimitError(TOO_LARGE)
    try:
        data = yaml_utils.load_yaml_text(source, engine=private_yaml_engine())
        if isinstance(data, dict) and isinstance(data.get('proxy-groups'), list) and len(data['proxy-groups']) > MAX_SOURCE_GROUPS:
            raise PreviewLimitError(TOO_LARGE)
        result = yaml_utils.transform_yaml_config(data, parsed['nodes'], parsed['countries'], special_groups, policy, node_update_mode=node_update_mode, template_profile=template_profile)
        if not result['success']:
            raise PreviewValidationError(' '.join(result['errors']))
        generated = yaml_utils.serialize_yaml(result['data'], max_bytes=MAX_YAML_BYTES)
    except PreviewLimitError:
        raise
    except yaml_utils.YamlSizeError:
        raise PreviewLimitError(TOO_LARGE) from None
    except YAMLError:
        raise PreviewValidationError('YAML 格式错误，请检查缩进、引号和重复键。') from None
    summary = {key: result[key] for key in ('old_node_count', 'new_node_count', 'group_count', 'rule_count')}
    return generated, summary


def preview(source, parsed, special_groups, policy, *, node_update_mode='replace', template_profile='custom'):
    generated, summary = transform(source, parsed, special_groups, policy, node_update_mode=node_update_mode, template_profile=template_profile)
    diff = unified(source, generated)
    return dict(changed=source != generated, diff=diff, summary=summary)
