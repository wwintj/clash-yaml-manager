"""English display adapter for reviewed legacy UI messages, never user data.

Core parser, API and CLI contracts retain their original strings. The browser
uses the same fixed phrases as Jinja; no locale selection/catalog is introduced.
"""
import re

DISPLAY_PHRASES = {
    '登录失败，密码错误。': 'Login failed. Incorrect password.',
    '两次输入的新密码不一致。': 'The new passwords do not match.',
    '新密码不能为空。': 'The new password must not be empty.',
    '当前密码不正确或登录状态已失效。': 'Current password is incorrect or the session has expired.',
    '密码保存失败，请检查认证状态文件权限。': 'Unable to save the password. Check authentication state permissions.',
    '管理密码已更新，请使用新密码重新登录。': 'Password updated. Log in again with the new password.',
    '不支持的文件格式，仅支持 .yaml 或 .yml 文件。': 'Unsupported file format. Choose a .yaml or .yml file.',
    '仅支持 .yaml / .yml 文件。': 'Choose a .yaml or .yml file.',
    '没有提供任何有效的新节点信息。': 'No valid new nodes provided.',
    '未上传 YAML，且默认 YAML 模板不存在。请先放置 defaults/default.yaml。': 'No YAML uploaded and the default template is missing. Restore defaults/default.yaml.',
    '文件保存失败，请检查磁盘空间和目录权限。': 'Unable to save the file. Check disk space and directory permissions.',
    '配置已成功更新，您可以下载或清理临时文件。': 'YAML generated. Download it or remove the temporary files.',
    '未找到可删除的文件或文件已被清理。': 'No removable files found. They may have already been cleaned up.',
    '安全状态暂不可用，请联系管理员检查 state/。': 'Security state unavailable. Ask the administrator to check state/.',
    '上传文件过大，最大支持 50MB。': 'Upload too large. Maximum size is 50MB.',
    '安全令牌已刷新，请重试；如有草稿，将自动恢复。': 'Security token refreshed. Try again; any saved draft will be restored.',
    '请重新登录；如有草稿，将在登录后自动恢复。': 'Log in again; any saved draft will be restored after login.',
    '辅助节点或手工修改格式无效，请检查名称、国家及链接。': 'Invalid auxiliary nodes or edits. Check names, countries and links.',
    '节点解析失败，请检查链接格式、必填字段及端口范围。': 'Unable to parse the node. Check the URI, required fields and port range.',
    '节点名称不能为空。': 'Node name must not be empty.',
    '节点名称重复，请修改名称以防止冲突。': 'Duplicate node name. Rename it to avoid a conflict.',
    '不支持的国家代码。请使用 ISO alpha-2 或 UNKNOWN。': 'Unsupported country code. Use ISO alpha-2 or UNKNOWN.',
    '不支持的国家代码。': 'Unsupported country code.',
    '协议不支持，仅接受 vmess:// 或 vless://。': 'Unsupported protocol. Use VMess, VLESS, Trojan or Shadowsocks.',
    '手工修改格式无效。': 'Invalid node edits.',
    'Country Unknown — choose a country or generate as 其他节点.': 'Country unknown. Choose a country or generate in the Other Nodes group.',
    'Trojan 配置无效或包含不支持的选项。': 'Invalid Trojan configuration or unsupported options.',
    'Trojan 链接无效或包含不支持的参数。': 'Invalid Trojan URI or unsupported parameters.',
    'Shadowsocks 链接或配置无效，请检查编码、必填字段及端口。': 'Invalid Shadowsocks URI or configuration. Check encoding, required fields and port.',
    'Shadowsocks 插件及混淆选项不受支持。': 'Shadowsocks plugins and obfuscation options are unsupported.',
    'Shadowsocks URI query 参数不受支持。': 'Shadowsocks URI query parameters are unsupported.',
    '端口必须是 1–65535 的整数。': 'Port must be an integer from 1 to 65535.',
    'Base64 或 JSON 结构解析失败': 'Invalid Base64 or JSON structure',
    'VMess JSON 必须是对象。': 'VMess JSON must be an object.',
    '节点解析失败，缺失必填字段 (add/server, port, 或 id)': 'Missing required node fields (add/server, port or id)',
    '节点解析失败，缺失必填字段 (server, port, 或 uuid)': 'Missing required node fields (server, port or uuid)',
    'VLESS 地址或端口格式无效。': 'Invalid VLESS address or port.',
    'YAML 格式错误，请检查缩进、引号和重复键。': 'Invalid YAML. Check indentation, quotes and duplicate keys.',
    'YAML 处理失败，请检查配置结构、磁盘空间及目录权限。': 'Unable to process YAML. Check its structure, disk space and directory permissions.',
    'YAML 顶层必须是映射。': 'YAML root must be a mapping.',
    '必须是列表。': 'must be a list.',
    '项的 ': '',
    '项必须有有效名称。': 'must have a valid name.',
    '项名称重复，请先处理冲突。': 'has a duplicate name. Resolve the conflict first.',
    '必须是字符串列表。': 'must be a list of strings.',
    '条引用了被替换的旧节点，请先改为保留的策略组。': 'references a replaced node. Use a retained proxy group first.',
    '新节点名称与策略组或内置策略冲突。': 'New node name conflicts with a proxy group or built-in policy.',
    '新节点名称与策略组冲突。': 'New node name conflicts with a proxy group.',
    '新节点数据必须是列表格式。': 'New nodes must be a list.',
    '个节点格式错误，必须是字典对象。': 'must be a mapping.',
    '个节点缺失 name 字段或为空。': 'has a missing or empty name.',
    '个节点名称重复。': 'has a duplicate name.',
    '个节点缺失 type 字段。': 'is missing type.',
    '个节点缺失 server 字段。': 'is missing server.',
    '个节点端口必须是 1–65535 的整数。': 'port must be an integer from 1 to 65535.',
    '个节点缺失 uuid 字段。': 'is missing uuid.',
    '个节点缺失 password 字段。': 'is missing password.',
    '个节点缺失 cipher 字段。': 'is missing cipher.',
    '个策略组为空，且未引用 proxy-providers 或 include-all。': 'is empty without proxy-providers or include-all.',
    '个策略组中存在无效的节点或策略组引用。': 'contains an invalid node or proxy group reference.',
    'Policy 配置无效，请检查类型、选项、URL 和数值范围。': 'Invalid Policy settings. Check type, options, URL and numeric ranges.',
    '自动策略组没有有效的新节点。旧订阅保持不变。': 'Automatic policy group has no valid new nodes. Previous subscription is unchanged.',
    '固定订阅状态不可用，请检查 state/ 并从备份恢复。': 'Fixed subscription state unavailable. Check state/ and restore a backup.',
    '请检查订阅名称和配置。': 'Check the subscription name and configuration.',
    '节点无效，请检查节点及手工修改。': 'Invalid nodes. Check the nodes and edits.',
    '请选择 Custom YAML。': 'Choose a Custom YAML file.',
    '生成失败，请检查节点、YAML 结构及策略组引用。旧订阅保持不变。': 'Generation failed. Check nodes, YAML structure and group references. Previous subscription is unchanged.',
}
# Only fixed safe message structure is rewritten, never node names or YAML/diff.
DISPLAY_PATTERNS = (
    (r'登录尝试过多，请在 (\d+) 秒后重试。', r'Too many login attempts. Try again in \1 seconds.'),
    (r'已成功删除 (\d+) 个服务器临时文件。', r'Deleted \1 temporary server files.'),
    (r'第 (\d+) 行错误：', r'Line \1: '),
    (r'第 (\d+) ', r'Item \1 '),
)


def display_message(value):
    text = str(value)
    for original, english in sorted(DISPLAY_PHRASES.items(), key=lambda pair: len(pair[0]), reverse=True):
        text = text.replace(original, english)
    for pattern, replacement in DISPLAY_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text

# Only Parse/Diff phrases are needed in the browser. Authentication and notices
# are server-rendered, so do not duplicate their copy in every page's script data.
BROWSER_DISPLAY_PHRASES = {
    original: english for original, english in DISPLAY_PHRASES.items()
    if original not in (
        '登录失败，密码错误。', '两次输入的新密码不一致。', '新密码不能为空。',
        '当前密码不正确或登录状态已失效。', '密码保存失败，请检查认证状态文件权限。',
        '管理密码已更新，请使用新密码重新登录。',
        '配置已成功更新，您可以下载或清理临时文件。',
        '未找到可删除的文件或文件已被清理。',
        '安全令牌已刷新，请重试；如有草稿，将自动恢复。',
        '请重新登录；如有草稿，将在登录后自动恢复。',
    )
}
