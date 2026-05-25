import base64
import json
import urllib.parse
from typing import Any, Dict, Tuple

# ==========================================
# 国家代码与策略组映射字典
# ==========================================
COUNTRY_MAPPING: Dict[str, Dict[str, str]] = {
    "US": {"emoji": "🇺🇸", "group": "🇺🇸 美国节点", "label": "美国"},
    "HK": {"emoji": "🇭🇰", "group": "🇭🇰 香港节点", "label": "香港"},
    "TW": {"emoji": "🇹🇼", "group": "🇹🇼 台湾节点", "label": "台湾"},
    "JP": {"emoji": "🇯🇵", "group": "🇯🇵 日本节点", "label": "日本"},
    "KR": {"emoji": "🇰🇷", "group": "🇰🇷 韩国节点", "label": "韩国"},
    "SG": {"emoji": "🇸🇬", "group": "🇸🇬 狮城节点", "label": "狮城"},
    "KP": {"emoji": "🇰🇵", "group": "🇰🇵 朝鲜节点", "label": "朝鲜"},
    "MY": {"emoji": "🇲🇾", "group": "🇲🇾 马来西亚节点", "label": "马来西亚"},
    "DE": {"emoji": "🇩🇪", "group": "🇩🇪 德国节点", "label": "德国"},
    "GB": {"emoji": "🇬🇧", "group": "🇬🇧 英国节点", "label": "英国"},
    "CA": {"emoji": "🇨🇦", "group": "🇨🇦 加拿大节点", "label": "加拿大"},
}


# ==========================================
# 辅助函数
# ==========================================
def mask_sensitive(value: str) -> str:
    """脱敏敏感信息，避免完整链接、UUID、password 出现在日志或前端错误里。"""
    if not value:
        return ""

    if value.startswith("vmess://") or value.startswith("vless://"):
        prefix = value[:8]
        content = value[8:]
        if len(content) > 16:
            return f"{prefix}{content[:6]}***{content[-6:]}"
        return f"{prefix}***"

    if "-" in value and len(value) == 36:
        return f"{value[:4]}***{value[-4:]}"

    if len(value) > 10:
        return f"{value[:4]}***{value[-4:]}"
    return "***"


def get_country_mapping() -> Dict[str, Dict[str, str]]:
    """获取支持的国家/地区映射。"""
    return COUNTRY_MAPPING


def normalize_country_code(country_code: str) -> str:
    """标准化国家/地区代码。"""
    return country_code.strip().upper()


def build_display_name(country_code: str, raw_name: str) -> str:
    """
    根据国家/地区代码自动给节点名添加国旗。
    如果 raw_name 已经包含对应国旗，则不重复添加。
    """
    code = normalize_country_code(country_code)
    raw_name = raw_name.strip()

    mapping = COUNTRY_MAPPING.get(code)
    if not mapping:
        return raw_name

    emoji = mapping["emoji"]
    if emoji in raw_name:
        return raw_name

    return f"{emoji} {raw_name}"


# ==========================================
# 协议解析核心
# ==========================================
def parse_vmess_link(link: str, display_name: str) -> Dict[str, Any]:
    """解析 vmess:// 分享链接，返回 Clash/Mihomo proxies 可用的 dict。"""
    content = link[8:]

    # 修复 Base64 padding，并兼容 URL-safe Base64。
    content = content.replace("-", "+").replace("_", "/")
    content += "=" * ((4 - len(content) % 4) % 4)

    try:
        decoded = base64.b64decode(content).decode("utf-8")
        v_obj = json.loads(decoded)
    except Exception:
        raise ValueError("Base64 或 JSON 结构解析失败")

    server = str(v_obj.get("add", "")).strip()
    port_raw = v_obj.get("port")
    uuid_raw = str(v_obj.get("id", "")).strip()

    if not server or not port_raw or not uuid_raw:
        raise ValueError("节点解析失败，缺失必填字段 (add/server, port, 或 id)")

    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        raise ValueError("端口号必须为有效数字")

    try:
        alter_id = int(v_obj.get("aid", 0))
    except (TypeError, ValueError):
        alter_id = 0

    cipher_raw = v_obj.get("scy", "auto")
    cipher = str(cipher_raw) if cipher_raw not in ["", None, "none"] else "auto"

    node: Dict[str, Any] = {
        "name": display_name,
        "type": "vmess",
        "server": server,
        "port": port,
        "uuid": uuid_raw,
        "alterId": alter_id,
        "cipher": cipher,
        "udp": True,
        "skip-cert-verify": False,
    }

    network = str(v_obj.get("net", "tcp")).strip() or "tcp"
    if network != "tcp":
        node["network"] = network

    if str(v_obj.get("tls", "")).lower() == "tls":
        node["tls"] = True

        sni = v_obj.get("sni")
        if sni:
            node["servername"] = str(sni)

        fp = v_obj.get("fp")
        if fp:
            node["client-fingerprint"] = str(fp)

        alpn = v_obj.get("alpn")
        if alpn:
            node["alpn"] = alpn.split(",") if isinstance(alpn, str) else alpn

    if network == "ws":
        ws_opts: Dict[str, Any] = {}

        path = v_obj.get("path")
        if path:
            ws_opts["path"] = str(path)

        # 优先使用分享链接里的 host；如果为空，则回退到 server。
        host_val = str(v_obj.get("host", "")).strip()
        ws_opts["headers"] = {"Host": host_val if host_val else server}

        node["ws-opts"] = ws_opts

    return node


def parse_vless_link(link: str, display_name: str) -> Dict[str, Any]:
    """解析 vless:// 分享链接，返回 Clash/Mihomo proxies 可用的 dict。"""
    parsed = urllib.parse.urlparse(link)

    server = parsed.hostname
    port_raw = parsed.port
    uuid_raw = urllib.parse.unquote(parsed.username) if parsed.username else ""

    if not server or not port_raw or not uuid_raw:
        raise ValueError("节点解析失败，缺失必填字段 (server, port, 或 uuid)")

    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        raise ValueError("端口号必须为有效数字")

    qs = urllib.parse.parse_qs(parsed.query)

    def get_qs(key: str, default: str = "") -> str:
        return qs.get(key, [default])[0]

    node: Dict[str, Any] = {
        "name": display_name,
        "type": "vless",
        "server": server,
        "port": port,
        "uuid": uuid_raw,
        "udp": True,
        "skip-cert-verify": False,
    }

    network = get_qs("type", "tcp") or "tcp"
    if network != "tcp":
        node["network"] = network

    security = get_qs("security", "")
    if security in ["tls", "reality"]:
        node["tls"] = True

        sni = get_qs("sni")
        if sni:
            node["servername"] = sni

        fp = get_qs("fp")
        if fp:
            node["client-fingerprint"] = fp

        alpn = get_qs("alpn")
        if alpn:
            node["alpn"] = alpn.split(",")

        if security == "reality":
            reality_opts: Dict[str, str] = {}

            pbk = get_qs("pbk")
            if pbk:
                reality_opts["public-key"] = pbk

            sid = get_qs("sid")
            if sid:
                reality_opts["short-id"] = sid

            if reality_opts:
                node["reality-opts"] = reality_opts

    if network == "ws":
        ws_opts: Dict[str, Any] = {}

        path = get_qs("path", "")
        if path:
            ws_opts["path"] = urllib.parse.unquote(path)

        host = get_qs("host", "")
        if host:
            ws_opts["headers"] = {"Host": host}

        if ws_opts:
            node["ws-opts"] = ws_opts

    return node


# ==========================================
# 批量处理层
# ==========================================
def parse_node_line(line: str, line_number: int) -> Tuple[str, Dict[str, Any], Dict[str, str]]:
    """解析单行批量数据，返回：最终节点名、节点 dict、国家策略信息。"""
    parts = line.split("|", 2)
    if len(parts) != 3:
        raise ValueError("缺少必填分隔符。需要 '国家代码|节点名称|节点链接'")

    raw_code, raw_name, link = [p.strip() for p in parts]
    code = normalize_country_code(raw_code)

    if code not in COUNTRY_MAPPING:
        supported = ", ".join(COUNTRY_MAPPING.keys())
        raise ValueError(f"不支持的国家代码 '{raw_code}'。支持列表: {supported}")

    if not (link.startswith("vmess://") or link.startswith("vless://")):
        raise ValueError("协议不支持，仅接受 vmess:// 或 vless://。")

    display_name = build_display_name(code, raw_name)

    try:
        if link.startswith("vmess://"):
            node = parse_vmess_link(link, display_name)
        else:
            node = parse_vless_link(link, display_name)
    except Exception as e:
        masked_link = mask_sensitive(link)
        raise ValueError(f"解析异常 ({masked_link}): {str(e)}")

    country_info = {
        "code": code,
        "group": COUNTRY_MAPPING[code]["group"],
    }

    return display_name, node, country_info


def parse_batch_nodes(text: str) -> Dict[str, Any]:
    """解析批量节点文本。"""
    result: Dict[str, Any] = {
        "nodes": [],
        "node_names": [],
        "countries": [],
        "errors": [],
    }

    seen_names = set()

    for idx, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue

        try:
            display_name, node, country_info = parse_node_line(line, idx)

            if display_name in seen_names:
                raise ValueError(f"节点名称 '{display_name}' 重复，请修改名称以防止冲突。")

            seen_names.add(display_name)

            result["nodes"].append(node)
            result["node_names"].append(display_name)
            result["countries"].append(
                {
                    "node_name": display_name,
                    "code": country_info["code"],
                    "group": country_info["group"],
                }
            )

        except ValueError as ve:
            result["errors"].append(f"第 {idx} 行错误：{str(ve)}")
        except Exception as e:
            result["errors"].append(f"第 {idx} 行发生系统异常: {str(e)}")

    return result


# ==========================================
# 独立测试模块
# ==========================================
if __name__ == "__main__":
    fake_vmess_no_host = (
        "eyJhZGQiOiIxLjEuMS4xIiwicG9ydCI6IjQ0MyIsImlkIjoiMDAwMC0wMDAwIiw"
        "iYWlkIjoiMCIsIm5ldCI6IndzIn0="
    )

    test_input = f"""
    US | Tim-GIA | vmess://{fake_vmess_no_host}
    HK | 🇭🇰 GIA | vless://1234-5678@2.2.2.2:443?type=ws&security=reality&sni=test.example&pbk=abcd&sid=1234&path=%2Fapi#ignored_name
    XX | ErrorCode | vmess://invalid
    TW | Tim-GIA | vmess://{fake_vmess_no_host}
    """

    parsed_result = parse_batch_nodes(test_input)
    print(json.dumps(parsed_result, indent=2, ensure_ascii=False))
