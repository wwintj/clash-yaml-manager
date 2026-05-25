import os
import shutil
import time
import uuid
from typing import Any, Dict, List, Optional

from ruamel.yaml import YAML

# ==========================================
# 常量配置
# ==========================================
BUILT_IN_POLICIES = {"DIRECT", "REJECT", "REJECT-DROP", "REJECT-TINYGIF", "PASS", "GLOBAL"}
GENERAL_GROUPS = ["🚀 节点选择", "🚀 手动切换", "🐟 漏网之鱼"]

FLAG_CORRECTIONS = {
    "🇨🇳 台湾节点": "🇹🇼 台湾节点",
    "🇺🇲 美国节点": "🇺🇸 美国节点",
}


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


# ==========================================
# 文件操作
# ==========================================
def generate_output_filename(original_filename: str) -> str:
    """生成带时间戳和短 UUID 的输出文件名，避免覆盖。"""
    base_name = os.path.basename(original_filename)
    name_part, ext_part = os.path.splitext(base_name)

    if not name_part:
        name_part = "config"
    if not ext_part:
        ext_part = ".yaml"

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:6]
    return f"{name_part}_{timestamp}_{short_uuid}{ext_part}"


def load_yaml(file_path: str) -> Dict[str, Any]:
    """读取 YAML 文件。"""
    yaml = get_yaml_engine()
    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.load(f)
    return data if data is not None else {}


def save_yaml(data: Dict[str, Any], output_path: str) -> None:
    """保存 YAML 文件，并设置权限为 600。"""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    yaml = get_yaml_engine()

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)

    os.chmod(output_path, 0o600)


def backup_yaml(input_path: str, backup_dir: str) -> str:
    """备份原始 YAML 文件，并设置权限为 600。"""
    os.makedirs(backup_dir, exist_ok=True)

    backup_filename = generate_output_filename(os.path.basename(input_path))
    backup_path = os.path.join(backup_dir, backup_filename)

    shutil.copy2(input_path, backup_path)
    os.chmod(backup_path, 0o600)

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
        if not name:
            errors.append(f"第 {i} 个节点缺失 name 字段或为空。")
        elif name in seen_names:
            errors.append(f"新节点中存在重复名称: '{name}'。")
        else:
            seen_names.add(name)

        if not node.get("type"):
            errors.append(f"节点 '{name or i}' 缺失 type 字段。")
        if not node.get("server"):
            errors.append(f"节点 '{name or i}' 缺失 server 字段。")

    return errors


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

    for group in data.get("proxy-groups", []):
        if not isinstance(group, dict):
            continue

        group_name = group.get("name", "UnknownGroup")

        has_proxies = "proxies" in group and isinstance(group["proxies"], list) and len(group["proxies"]) > 0
        has_use = "use" in group and bool(group["use"])
        has_include_all = group.get("include-all", False) is True

        if not has_proxies and not has_use and not has_include_all:
            errors.append(f"策略组 '{group_name}' 为空，且未引用 proxy-providers (use) 或 include-all。")
            continue

        for proxy_ref in group.get("proxies", []):
            if not proxy_ref:
                continue
            if proxy_ref not in valid_targets:
                errors.append(f"策略组 '{group_name}' 中存在无效的引用: '{proxy_ref}'。")

    return errors


# ==========================================
# 数据清洗与重组
# ==========================================
def normalize_group_names(data: Dict[str, Any]) -> None:
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
                    if proxy_name in FLAG_CORRECTIONS:
                        group["proxies"][i] = FLAG_CORRECTIONS[proxy_name]

    if "rules" in data and isinstance(data["rules"], list):
        for i, rule in enumerate(data["rules"]):
            if not isinstance(rule, str):
                continue

            parts = rule.split(",")
            if len(parts) < 3:
                continue

            target_idx = -2 if parts[-1].strip().lower() == "no-resolve" else -1
            target_value = parts[target_idx].strip()

            if target_value in FLAG_CORRECTIONS:
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
        has_include_all = group.get("include-all", False) is True

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
def process_yaml_config(
    input_path: str,
    output_dir: str,
    backup_dir: str,
    new_nodes: List[Dict[str, Any]],
    countries: List[Dict[str, str]],
    special_groups: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """无损处理 Clash/Mihomo YAML：删除旧节点，注入新节点，修复策略组引用。"""
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
        result["backup_path"] = backup_yaml(input_path, backup_dir)

        data = load_yaml(input_path)

        if "proxies" not in data or not isinstance(data["proxies"], list):
            data["proxies"] = []
        if "proxy-groups" not in data or not isinstance(data["proxy-groups"], list):
            data["proxy-groups"] = []

        normalize_group_names(data)
        merge_duplicate_groups(data)

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

        for group in data["proxy-groups"]:
            if not isinstance(group, dict):
                continue

            if "proxies" not in group or not isinstance(group["proxies"], list):
                group["proxies"] = []

            cleaned_proxies = []
            for ref in group["proxies"]:
                if ref in old_nodes_set and ref not in group_names and ref not in BUILT_IN_POLICIES:
                    continue
                cleaned_proxies.append(ref)

            group["proxies"] = cleaned_proxies

        data["proxies"] = new_nodes

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

        validation_errors = validate_proxy_references(data)
        if validation_errors:
            result["errors"].extend(validation_errors)
            result["success"] = False
            return result

        result["group_count"] = len(data.get("proxy-groups", []))
        result["rule_count"] = len(data.get("rules", []))

        output_filename = generate_output_filename(os.path.basename(input_path))
        output_path = os.path.join(output_dir, output_filename)

        save_yaml(data, output_path)

        result["output_path"] = output_path
        result["success"] = True

    except Exception as e:
        result["success"] = False
        result["errors"].append(f"YAML 核心处理崩溃: {str(e)}")

    return result


if __name__ == "__main__":
    print("yaml_utils.py loaded. Please call process_yaml_config() from app.py.")
