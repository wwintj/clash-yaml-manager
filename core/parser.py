import base64
import hashlib
import json
import re
import urllib.parse
from typing import Any, Dict, Tuple

# ==========================================
# 国家代码与策略组映射字典
# ==========================================
from core.countries import COUNTRY_MAPPING, detect_country


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
def parse_port(value: Any) -> int:
    """Do not coerce booleans/floats or echo untrusted port text."""
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
        raise ValueError("端口必须是 1–65535 的整数。")
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError("端口必须是 1–65535 的整数。")
    return port


def parse_vmess_link(link: str, display_name: str) -> Dict[str, Any]:
    """解析 vmess:// 分享链接，返回 Clash/Mihomo proxies 可用的 dict。"""
    content = link[8:]

    # 修复 Base64 padding，并兼容 URL-safe Base64。
    content = content.replace("-", "+").replace("_", "/")
    content += "=" * ((4 - len(content) % 4) % 4)

    try:
        decoded = base64.b64decode(content, validate=True).decode("utf-8")
        v_obj = json.loads(decoded)
    except Exception:
        raise ValueError("Base64 或 JSON 结构解析失败") from None

    if not isinstance(v_obj, dict):
        raise ValueError("VMess JSON 必须是对象。")

    server = v_obj.get("add", "")
    port_raw = v_obj.get("port")
    uuid_raw = v_obj.get("id", "")

    if not isinstance(server, str) or not server.strip() or not isinstance(uuid_raw, str) or not uuid_raw.strip():
        raise ValueError("节点解析失败，缺失必填字段 (add/server, port, 或 id)")
    server, uuid_raw = server.strip(), uuid_raw.strip()

    port = parse_port(port_raw)

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
    try:
        parsed = urllib.parse.urlparse(link)
        server = parsed.hostname
        port_raw = parsed.port
        uuid_raw = urllib.parse.unquote(parsed.username) if parsed.username else ""
    except ValueError:
        raise ValueError("VLESS 地址或端口格式无效。") from None

    if not server or not port_raw or not uuid_raw:
        raise ValueError("节点解析失败，缺失必填字段 (server, port, 或 uuid)")

    port = parse_port(port_raw)

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
            ws_opts["path"] = path

        host = get_qs("host", "")
        if host:
            ws_opts["headers"] = {"Host": host}

        if ws_opts:
            node["ws-opts"] = ws_opts

    return node


# ==========================================
# 批量处理层
# ==========================================
def node_key(line: str, occurrence: int = 0) -> str:
    # Key the complete input, not its line number: moving rows preserves overrides;
    # changing the URI invalidates them. Never return the URI itself to preview.
    return hashlib.sha256(line.strip().encode()).hexdigest() + ':' + str(occurrence)


def split_node_input(line: str, line_num: int):
    parts = [part.strip() for part in line.split('|', 2)]
    if len(parts) == 3:
        code, name, link = parts
        code = normalize_country_code(code)
        if code not in COUNTRY_MAPPING:
            raise ValueError('不支持的国家代码。请使用 ISO alpha-2 或 UNKNOWN。')
        if not name:
            raise ValueError('节点名称不能为空。')
        return code, name, link, 'Manual'
    if len(parts) == 2:
        name, link = parts
        if not name:
            raise ValueError('节点名称不能为空。')
    else:
        link = parts[0]
        name = ''
        try:
            if link.startswith('vless://'):
                name = urllib.parse.unquote(urllib.parse.urlsplit(link).fragment)
            elif link.startswith('vmess://'):
                payload, _, fragment = link[8:].partition('#')
                payload += '=' * ((4 - len(payload) % 4) % 4)
                obj = json.loads(base64.b64decode(payload, altchars=b'-_', validate=True).decode())
                name = urllib.parse.unquote(fragment) or obj.get('ps', '')
        except Exception:
            raise ValueError('节点解析失败，请检查链接格式、必填字段及端口范围。') from None
        if not isinstance(name, str):
            name = ''
        name = name.strip() or f'Node-{line_num:02d}'
    code = detect_country(name)
    return code, name, link, 'Unknown' if code == 'UNKNOWN' else 'Name Detection'


def parse_node_line(line: str, line_num: int = 1, override=None, country_lookup=None) -> Tuple[str, Dict[str, Any], Dict[str, str]]:
    code, raw_name, link, source = split_node_input(line, line_num)
    if override:
        if 'name' in override:
            raw_name = override['name'].strip()
            if not raw_name:
                raise ValueError('节点名称不能为空。')
            if source != 'Manual':
                code = detect_country(raw_name)
                source = 'Unknown' if code == 'UNKNOWN' else 'Name Detection'
        if 'country' in override:
            code = normalize_country_code(override['country'])
            if code not in COUNTRY_MAPPING:
                raise ValueError('不支持的国家代码。')
            source = 'Manual'
    if not (link.startswith('vmess://') or link.startswith('vless://')):
        raise ValueError('协议不支持，仅接受 vmess:// 或 vless://。')
    display_name = build_display_name(code, raw_name)
    try:
        node = (parse_vmess_link(link.split('#', 1)[0], display_name) if link.startswith('vmess://')
                else parse_vless_link(link, display_name))
    except Exception:
        raise ValueError('节点解析失败，请检查链接格式、必填字段及端口范围。') from None
    if code == 'UNKNOWN' and source != 'Manual' and country_lookup is not None:
        assisted = country_lookup.country(node['server'])
        if assisted:
            code, source = assisted, 'GeoIP'
            display_name = build_display_name(code, raw_name)
            node['name'] = display_name
    return display_name, node, dict(code=code, group=COUNTRY_MAPPING[code]['group'],
                                    source=source, raw_name=raw_name)


def preview_name(name: str) -> str:
    """Do not echo a credential even if it was embedded in a user-provided remark."""
    name = re.sub(r'(?i)(?:vmess|vless)://\S+', '[link hidden]', name)
    return re.sub(r'(?i)\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b', '[UUID hidden]', name)


def parse_batch_nodes(text: str, overrides=None, country_lookup=None) -> Dict[str, Any]:
    result = dict(nodes=[], node_names=[], countries=[], errors=[], preview=[])
    seen_names, occurrences = set(), {}
    overrides = overrides or {}
    for idx, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        occurrence = occurrences.get(line, 0)
        occurrences[line] = occurrence + 1
        key = node_key(line, occurrence)
        record = dict(key=key, line=idx, name='', country='UNKNOWN', protocol='—',
                      status='Error', source='Unknown', message='')
        try:
            display_name, node, info = parse_node_line(line, idx, overrides.get(key), country_lookup)
            record.update(name=preview_name(info['raw_name']), country=info['code'], protocol=node['type'].upper(), source=info['source'])
            if display_name in seen_names:
                raise ValueError('节点名称重复，请修改名称以防止冲突。')
            seen_names.add(display_name)
            result['nodes'].append(node)
            result['node_names'].append(display_name)
            result['countries'].append(dict(node_name=display_name, code=info['code'], group=info['group']))
            record['status'] = 'Warning' if info['code'] == 'UNKNOWN' else 'Ready'
            if record['status'] == 'Warning':
                record['message'] = 'Country Unknown — choose a country or generate as 其他节点.'
        except (ValueError, TypeError, AttributeError) as error:
            # Only fixed parser messages may be shown. Invalid override types are rejected.
            message = str(error) if isinstance(error, ValueError) else '手工修改格式无效。'
            record['message'] = message
            result['errors'].append(f'第 {idx} 行错误：{message}')
        result['preview'].append(record)
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
