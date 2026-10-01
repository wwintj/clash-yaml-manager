import os
import io
import re
import secrets
import shutil
import tempfile
import time
import uuid
from typing import Any, Dict, List, Optional
from types import FunctionType, SimpleNamespace

from core import policy_engine, node_update

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

# ==========================================
# 常量配置
# ==========================================
BUILT_IN_POLICIES = {"DIRECT", "REJECT", "REJECT-DROP", "REJECT-TINYGIF", "PASS", "GLOBAL"}
GENERAL_GROUPS = ["🚀 节点选择", "🚀 手动切换", "🐟 漏网之鱼"]

FLAG_CORRECTIONS = {
    "🇨🇳 台湾节点": "🇹🇼 台湾节点",
    "🇺🇲 美国节点": "🇺🇸 美国节点",
}


class ConfigValidationError(ValueError):
    """Only fixed, non-sensitive validation messages may cross into the UI."""


# ==========================================
# YAML 引擎初始化
# ==========================================
def get_yaml_engine() -> YAML:
    """初始化 ruamel.yaml 实例，尽量保留 Clash/Mihomo YAML 原有结构。"""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    return yaml


def private_yaml_engine():
    """Keep private source values out of nonfatal diagnostics in every loader.

    ruamel can warn with private anchor names / YAML 1.1 scalar values. Its float
    handler has no warning switch: reuse the exact installed function code with
    an instance-private warnings facade. Parsing/serialization semantics and the
    dependency's global constructor registry remain unchanged.
    """
    engine = get_yaml_engine()
    engine.composer.warn_double_anchors = False
    constructor = engine.constructor
    tag = 'tag:yaml.org,2002:float'
    original = constructor.yaml_constructors[tag]
    scope = dict(original.__globals__, warnings=SimpleNamespace(warn=lambda *args, **kwargs: None))
    quiet = FunctionType(original.__code__, scope, original.__name__, original.__defaults__, original.__closure__)
    quiet.__kwdefaults__ = original.__kwdefaults__
    constructor.yaml_constructors = dict(constructor.yaml_constructors)
    constructor.yaml_constructors[tag] = quiet
    return engine


# ==========================================
# 文件操作
# ==========================================
def generate_backup_filename(original_filename: str) -> str:
    """生成带时间戳和短 UUID 的备份文件名，避免覆盖。"""
    base_name = os.path.basename(original_filename)
    name_part, ext_part = os.path.splitext(base_name)

    if not name_part:
        name_part = "config"
    if not ext_part:
        ext_part = ".yaml"

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:6]
    return f"{name_part}_{timestamp}_{short_uuid}{ext_part}"


def generate_output_filename(output_dir: str) -> str:
    """日期和序号便于识别；128 位随机标识避免删除后复用订阅地址。"""
    today = time.strftime("%Y%m%d")
    prefix = f"tim_{today}_"
    next_index = 1

    if os.path.isdir(output_dir):
        for filename in os.listdir(output_dir):
            if not filename.startswith(prefix) or not filename.endswith(".yaml"):
                continue

            match = re.fullmatch(r'([1-9][0-9]{0,15})(?:_[A-Za-z0-9_-]{22})?', filename[len(prefix):-5])
            if match:
                next_index = max(next_index, int(match.group(1)) + 1)

    return f"{prefix}{next_index}_{secrets.token_urlsafe(16)}.yaml"


def load_yaml(file_path: str) -> Dict[str, Any]:
    """读取 YAML 文件。"""
    with open(file_path, "r", encoding="utf-8") as source:
        return load_yaml_stream(source)


def load_yaml_text(text, *, engine=None):
    """Match file TextIO universal-newline loading, including comment tokens."""
    return load_yaml_stream(io.StringIO(text, newline=None), engine=engine)


def load_yaml_stream(stream, *, engine=None):
    data = (engine or private_yaml_engine()).load(stream)
    return data if data is not None else {}


class YamlSizeError(ValueError):
    """The caller's in-memory serialization budget was exhausted."""


def serialize_yaml(data, max_bytes=None, *, stream=None):
    """Same serialization for committed output and would-be preview bytes."""
    if stream is not None:
        get_yaml_engine().dump(data, stream)
        return None
    class Buffer(io.StringIO):
        size = 0
        def write(self, text):
            if max_bytes is not None:
                self.size += len(text.encode('utf-8'))
                if self.size > max_bytes:
                    raise YamlSizeError
            return super().write(text)
    stream = Buffer()
    get_yaml_engine().dump(data, stream)
    return stream.getvalue()


def save_yaml(data: Dict[str, Any], output_path: str) -> None:
    """Serialize privately, then atomically replace; never expose partial YAML."""
    directory = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.yaml-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            serialize_yaml(data, stream=f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, output_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_new_output(data: Dict[str, Any], output_dir: str) -> str:
    """Publish a complete 600 file without overwriting another worker's output."""
    os.makedirs(output_dir, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=output_dir)
    os.close(fd)
    try:
        save_yaml(data, temporary)
        while True:
            output_path = os.path.join(output_dir, generate_output_filename(output_dir))
            try:
                # Same filesystem: link is atomic and fails if the name exists.
                os.link(temporary, output_path)
                return output_path
            except FileExistsError:
                continue
    finally:
        os.unlink(temporary)


def backup_yaml(input_path: str, backup_dir: str) -> str:
    """备份原始 YAML 文件，并设置权限为 600。"""
    os.makedirs(backup_dir, exist_ok=True)

    backup_filename = generate_backup_filename(os.path.basename(input_path))
    backup_path = os.path.join(backup_dir, backup_filename)

    fd = os.open(backup_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as target, open(input_path, 'rb') as source:
        shutil.copyfileobj(source, target)

    return backup_path


# ==========================================
# 校验逻辑
# ==========================================
def validate_new_nodes(new_nodes: Any) -> List[str]:
    """校验 parser.py 传入的新节点列表。"""
    errors: List[str] = []

    if not isinstance(new_nodes, list):
        return ["新节点数据必须是列表格式。"]

    seen_names = set()

    for i, node in enumerate(new_nodes, 1):
        if not isinstance(node, dict):
            errors.append(f"第 {i} 个节点格式错误，必须是字典对象。")
            continue

        name = node.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"第 {i} 个节点缺失 name 字段或为空。")
        elif name in seen_names:
            errors.append(f"第 {i} 个节点名称重复。")
        else:
            seen_names.add(name)

        if not isinstance(node.get("type"), str) or not node["type"].strip():
            errors.append(f"第 {i} 个节点缺失 type 字段。")
        if not isinstance(node.get("server"), str) or not node["server"].strip():
            errors.append(f"第 {i} 个节点缺失 server 字段。")
        port = node.get('port')
        if type(port) is not int or not 1 <= port <= 65535:
            errors.append(f"第 {i} 个节点端口必须是 1–65535 的整数。")
        if node.get('type') in ('vmess', 'vless') and (not isinstance(node.get('uuid'), str) or not node['uuid'].strip()):
            errors.append(f"第 {i} 个节点缺失 uuid 字段。")
        if node.get('type') in ('trojan', 'ss') and (not isinstance(node.get('password'), str) or node['password'] == ''):
            errors.append(f"第 {i} 个节点缺失 password 字段。")
        if node.get('type') == 'ss' and (not isinstance(node.get('cipher'), str) or node['cipher'] == ''):
            errors.append(f"第 {i} 个节点缺失 cipher 字段。")

    return errors


def validate_input_structure(data: Any) -> None:
    """Reject destructive coercions before transforming, without echoing input."""
    if not isinstance(data, dict):
        raise ConfigValidationError('YAML 顶层必须是映射。')
    for key in ('proxies', 'proxy-groups'):
        if key not in data:
            continue
        if not isinstance(data[key], list):
            raise ConfigValidationError(f'{key} 必须是列表。')
        names = set()
        for i, item in enumerate(data[key], 1):
            if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not item['name'].strip():
                raise ConfigValidationError(f'{key} 第 {i} 项必须有有效名称。')
            if item['name'] in names:
                raise ConfigValidationError(f'{key} 第 {i} 项名称重复，请先处理冲突。')
            names.add(item['name'])
            if key == 'proxy-groups':
                for field in ('proxies', 'use'):
                    if field in item and (not isinstance(item[field], list) or
                                          any(not isinstance(ref, str) for ref in item[field])):
                        raise ConfigValidationError(f'proxy-groups 第 {i} 项的 {field} 必须是字符串列表。')
    if 'rules' in data and (not isinstance(data['rules'], list) or
                           any(not isinstance(rule, str) for rule in data['rules'])):
        raise ConfigValidationError('rules 必须是字符串列表。')


def validate_removed_rule_targets(data: Dict[str, Any], removed_names: set) -> None:
    """Targeted replacement guard; a full Mihomo rule validator is a later step."""
    remaining = {p['name'] for p in data['proxies']} | {g['name'] for g in data['proxy-groups']} | BUILT_IN_POLICIES
    removed_targets = removed_names - remaining
    for i, rule in enumerate(data.get('rules', []), 1):
        parts = rule.split(',')
        target = parts[-2] if len(parts) > 2 and parts[-1].strip().lower() == 'no-resolve' else parts[-1]
        if target.strip() in removed_targets:
            raise ConfigValidationError(f'rules 第 {i} 条引用了被替换的旧节点，请先改为保留的策略组。')


def validate_proxy_references(data: Dict[str, Any]) -> List[str]:
    """校验 proxy-groups 中的引用是否有效，并拦截非法空策略组。"""
    errors: List[str] = []

    valid_proxies = {
        p.get("name")
        for p in data.get("proxies", [])
        if isinstance(p, dict) and p.get("name")
    }
    valid_groups = {
        g.get("name")
        for g in data.get("proxy-groups", [])
        if isinstance(g, dict) and g.get("name")
    }
    valid_targets = valid_proxies | valid_groups | BUILT_IN_POLICIES

    for i, group in enumerate(data.get("proxy-groups", []), 1):
        if not isinstance(group, dict):
            continue

        has_proxies = "proxies" in group and isinstance(group["proxies"], list) and len(group["proxies"]) > 0
        has_use = "use" in group and bool(group["use"])
        has_include_all = any(group.get(key) is True for key in ('include-all', 'include-all-proxies', 'include-all-providers'))

        if not has_proxies and not has_use and not has_include_all:
            errors.append(f"第 {i} 个策略组为空，且未引用 proxy-providers 或 include-all。")
            continue

        for proxy_ref in group.get("proxies", []):
            if not proxy_ref:
                continue
            if proxy_ref not in valid_targets:
                errors.append(f"第 {i} 个策略组中存在无效的节点或策略组引用。")

    return errors


# ==========================================
# 数据清洗与重组
# ==========================================
def normalize_group_names(data: Dict[str, Any], preserved_node_names=()) -> None:
    """修正常见错误策略组名，并同步修正组内引用和 rules 中的策略名。"""
    if "proxy-groups" in data and isinstance(data["proxy-groups"], list):
        for group in data["proxy-groups"]:
            if not isinstance(group, dict):
                continue

            old_name = group.get("name", "")
            if old_name in FLAG_CORRECTIONS:
                group["name"] = FLAG_CORRECTIONS[old_name]

            if "proxies" in group and isinstance(group["proxies"], list):
                for i, proxy_name in enumerate(group["proxies"]):
                    if proxy_name in FLAG_CORRECTIONS and proxy_name not in preserved_node_names:
                        group["proxies"][i] = FLAG_CORRECTIONS[proxy_name]

    if "rules" in data and isinstance(data["rules"], list):
        for i, rule in enumerate(data["rules"]):
            if not isinstance(rule, str):
                continue

            parts = rule.split(",")
            if len(parts) < 2:
                continue

            target_idx = -2 if parts[-1].strip().lower() == "no-resolve" else -1
            target_value = parts[target_idx].strip()

            if target_value in FLAG_CORRECTIONS and target_value not in preserved_node_names:
                parts[target_idx] = parts[target_idx].replace(target_value, FLAG_CORRECTIONS[target_value])
                data["rules"][i] = ",".join(parts)


def merge_duplicate_groups(data: Dict[str, Any]) -> None:
    """按 name 合并重复 proxy-groups，并去重 proxies 引用。"""
    if "proxy-groups" not in data or not isinstance(data["proxy-groups"], list):
        return

    seen_groups: Dict[str, Dict[str, Any]] = {}
    merged_list: List[Any] = []

    for group in data["proxy-groups"]:
        if not isinstance(group, dict):
            merged_list.append(group)
            continue

        name = group.get("name")
        if not name:
            merged_list.append(group)
            continue

        if name in seen_groups:
            existing_group = seen_groups[name]

            if "proxies" in group and isinstance(group["proxies"], list):
                if "proxies" not in existing_group or not isinstance(existing_group["proxies"], list):
                    existing_group["proxies"] = []

                for proxy_name in group["proxies"]:
                    if proxy_name not in existing_group["proxies"]:
                        existing_group["proxies"].append(proxy_name)
        else:
            seen_groups[name] = group
            merged_list.append(group)

    data["proxy-groups"] = merged_list


def ensure_group_exists(data: Dict[str, Any], group_name: str, group_type: str = "select") -> None:
    """确保策略组存在，不存在则创建。"""
    if "proxy-groups" not in data or not isinstance(data["proxy-groups"], list):
        data["proxy-groups"] = []

    for group in data["proxy-groups"]:
        if isinstance(group, dict) and group.get("name") == group_name:
            if "proxies" not in group or not isinstance(group["proxies"], list):
                group["proxies"] = []
            return

    data["proxy-groups"].append(
        {
            "name": group_name,
            "type": group_type,
            "proxies": [],
        }
    )


def add_node_to_group(data: Dict[str, Any], group_name: str, node_name: str) -> None:
    """将节点加入指定策略组，自动去重。"""
    for group in data.get("proxy-groups", []):
        if isinstance(group, dict) and group.get("name") == group_name:
            if "proxies" not in group or not isinstance(group["proxies"], list):
                group["proxies"] = []

            if node_name not in group["proxies"]:
                group["proxies"].append(node_name)
            return


def fill_empty_proxy_groups(data: Dict[str, Any], new_node_names: List[str]) -> None:
    """填充清理旧节点后变为空的策略组，避免 Clash/Mihomo 导入异常。"""
    if "proxy-groups" not in data or not isinstance(data["proxy-groups"], list):
        return

    for group in data["proxy-groups"]:
        if not isinstance(group, dict):
            continue

        if "proxies" not in group or not isinstance(group["proxies"], list):
            group["proxies"] = []

        has_proxies = len(group["proxies"]) > 0
        has_use = "use" in group and bool(group["use"])
        has_include_all = any(group.get(key) is True for key in ('include-all', 'include-all-proxies', 'include-all-providers'))

        if has_proxies or has_use or has_include_all:
            continue

        group_type = group.get("type", "select")
        group_name = group.get("name", "")

        if group_type in ["url-test", "fallback", "load-balance"]:
            group["proxies"].extend(new_node_names)
        else:
            if group_name == "🚀 手动切换":
                group["proxies"].extend(new_node_names)
            else:
                group["proxies"].append("🚀 手动切换")


# ==========================================
# 主入口
# ==========================================
def transform_yaml_config(data, new_nodes, countries, special_groups=None, policy_config=None, group_transform=None, *, node_update_mode='replace'):
    """Shared in-memory update/validation; no files, state or network work."""
    result: Dict[str, Any] = {
        "success": False,
        "output_path": "",
        "backup_path": "",
        "old_node_count": 0,
        "new_node_count": 0,
        "group_count": 0,
        "rule_count": 0,
        "errors": [],
    }

    node_errors = validate_new_nodes(new_nodes)
    if node_errors:
        result["errors"].extend(node_errors)
        return result

    result["new_node_count"] = len(new_nodes)

    try:
        mode = node_update.normalize(node_update_mode)
        policy = policy_engine.normalize(policy_config if policy_config is not None else policy_engine.defaults())
        validate_input_structure(data)

        if "proxies" not in data or not isinstance(data["proxies"], list):
            data["proxies"] = []
        if "proxy-groups" not in data or not isinstance(data["proxy-groups"], list):
            data["proxy-groups"] = []

        # In Merge a proxy can legitimately have a legacy flag-looking name.
        # Its references/rule targets must not be mistaken for corrected groups.
        preserved = {p['name'] for p in data['proxies']} if mode == 'merge' else set()
        normalize_group_names(data, preserved)
        # Normalization can itself introduce a duplicate name.
        validate_input_structure(data)

        old_node_names = [
            p["name"]
            for p in data["proxies"]
            if isinstance(p, dict) and "name" in p
        ]
        old_nodes_set = set(old_node_names)
        result["old_node_count"] = len(old_node_names)

        group_names = {
            g["name"]
            for g in data["proxy-groups"]
            if isinstance(g, dict) and "name" in g
        }

        if mode == 'replace':
            for group in data["proxy-groups"]:
                if not isinstance(group, dict):
                    continue

                if "proxies" not in group or not isinstance(group["proxies"], list):
                    group["proxies"] = []

                # Remove in-place so retained ruamel sequence comments survive.
                for index in range(len(group['proxies']) - 1, -1, -1):
                    ref = group['proxies'][index]
                    if ref in old_nodes_set and ref not in group_names and ref not in BUILT_IN_POLICIES:
                        del group['proxies'][index]

            data["proxies"] = new_nodes
        else:
            if any(node['name'] in old_nodes_set for node in new_nodes):
                raise ConfigValidationError('Node name already exists in source YAML.')
            # Extend the original ruamel sequence: keep every old node object,
            # its unknown protocol/fields, comments, quotes, aliases and order.
            data['proxies'].extend(new_nodes)
        if any(node['name'] in group_names | BUILT_IN_POLICIES for node in new_nodes):
            raise ConfigValidationError('新节点名称与策略组或内置策略冲突。')

        special_groups = special_groups or []

        for group_name in GENERAL_GROUPS + special_groups:
            ensure_group_exists(data, group_name)

        for country_info in countries:
            group_name = country_info.get("group")
            if group_name:
                ensure_group_exists(data, group_name)

        for node in new_nodes:
            node_name = node["name"]

            for group_name in GENERAL_GROUPS:
                add_node_to_group(data, group_name, node_name)

            for group_name in special_groups:
                add_node_to_group(data, group_name, node_name)

        for country_info in countries:
            node_name = country_info.get("node_name")
            group_name = country_info.get("group")

            if node_name and group_name:
                add_node_to_group(data, group_name, node_name)

        new_node_names = [node["name"] for node in new_nodes]
        fill_empty_proxy_groups(data, new_node_names)
        policy_engine.apply(data, new_nodes, countries, special_groups, policy)
        if group_transform is not None:
            group_transform(data)
        validate_input_structure(data)
        if {node['name'] for node in new_nodes} & {g['name'] for g in data['proxy-groups']}:
            raise ConfigValidationError('新节点名称与策略组冲突。')
        if mode == 'merge' and old_nodes_set & {g['name'] for g in data['proxy-groups']}:
            raise ConfigValidationError('Source node name conflicts with a proxy group.')
        validate_removed_rule_targets(data, old_nodes_set)

        validation_errors = validate_proxy_references(data)
        if validation_errors:
            result["errors"].extend(validation_errors)
            result["success"] = False
            return result

        result["group_count"] = len(data.get("proxy-groups", []))
        result["rule_count"] = len(data.get("rules", []))

        result["data"] = data
        result["success"] = True

    except (ConfigValidationError, policy_engine.PolicyError, node_update.ModeError) as e:
        result['errors'].append(str(e))
    except YAMLError:
        result['errors'].append('YAML 格式错误，请检查缩进、引号和重复键。')
    except Exception:
        result["success"] = False
        result["errors"].append('YAML 处理失败，请检查配置结构、磁盘空间及目录权限。')

    return result


def process_yaml_config(
    input_path: str,
    output_dir: str,
    backup_dir: str,
    new_nodes: List[Dict[str, Any]],
    countries: List[Dict[str, str]],
    special_groups: Optional[List[str]] = None,
    policy_config: Optional[Dict[str, Any]] = None,
    group_transform=None,
    *, node_update_mode='replace',
) -> Dict[str, Any]:
    """替换节点及修复组引用，尽可能保留其余 YAML 内容。"""
    result = dict(success=False, output_path="", backup_path="", old_node_count=0,
                  new_node_count=0, group_count=0, rule_count=0, errors=[])
    errors = validate_new_nodes(new_nodes)
    if errors:
        result['errors'].extend(errors)
        return result
    result['new_node_count'] = len(new_nodes)
    try:
        mode = node_update.normalize(node_update_mode)
        policy = policy_engine.normalize(policy_config if policy_config is not None else policy_engine.defaults())
        result['backup_path'] = backup_yaml(input_path, backup_dir)
        transformed = transform_yaml_config(load_yaml(input_path), new_nodes, countries,
                                            special_groups, policy, group_transform, node_update_mode=mode)
        data = transformed.pop('data', None)
        transformed.pop('output_path')
        transformed.pop('backup_path')
        result.update(transformed)
        if result['success']:
            result['success'] = False
            result['output_path'] = save_new_output(data, output_dir)
            result['success'] = True
    except (ConfigValidationError, policy_engine.PolicyError, node_update.ModeError) as error:
        result['errors'].append(str(error))
    except YAMLError:
        result['errors'].append('YAML 格式错误，请检查缩进、引号和重复键。')
    except Exception:
        result['success'] = False
        result['errors'].append('YAML 处理失败，请检查配置结构、磁盘空间及目录权限。')
    return result


if __name__ == "__main__":
    print("yaml_utils.py loaded. Please call process_yaml_config() from app.py.")
