"""Traditional Chinese display adapter for reviewed legacy UI messages, never user data.

Core parser, API and CLI contracts retain their original strings. The browser
uses the same fixed phrases as Jinja; no locale selection/catalog is introduced.
"""
import re

DISPLAY_PHRASES = {
    '登录失败，密码错误。': '登入失敗，密碼錯誤。',
    '两次输入的新密码不一致。': '兩次輸入的新密碼不一致。',
    '新密码不能为空。': '新密碼不能為空。',
    '当前密码不正确或登录状态已失效。': '目前密碼不正確，或登入狀態已失效。',
    '密码保存失败，请检查认证状态文件权限。': '密碼儲存失敗，請檢查認證狀態檔案權限。',
    '更新密码失败，请检查认证状态文件权限。': '密碼更新失敗，請檢查認證狀態檔案權限。',
    '管理密码已更新，请使用新密码重新登录。': '管理密碼已更新，請使用新密碼重新登入。',
    '不支持的文件格式，仅支持 .yaml 或 .yml 文件。': '不支援的檔案格式，請選擇 .yaml 或 .yml 檔案。',
    '仅支持 .yaml / .yml 文件。': '請選擇 .yaml 或 .yml 檔案。',
    '没有提供任何有效的新节点信息。': '沒有提供任何有效的新節點。',
    '未上传 YAML，且默认 YAML 模板不存在。请先放置 defaults/default.yaml。': '未上傳 YAML，且預設模板不存在。請還原 defaults/default.yaml。',
    '文件保存失败，请检查磁盘空间和目录权限。': '檔案儲存失敗，請檢查磁碟空間與目錄權限。',
    '配置已成功更新，您可以下载或清理临时文件。': 'YAML 已產生，可以下載或刪除暫存檔案。',
    '未找到可删除的文件或文件已被清理。': '找不到可刪除的檔案，可能已被清理。',
    '删除临时文件失败，请检查目录权限。': '刪除暫存檔案失敗，請檢查目錄權限。',
    '安全状态暂不可用，请联系管理员检查 state/。': '安全狀態暫時無法使用，請管理員檢查 state/。',
    '上传文件过大，最大支持 50MB。': '上傳檔案過大，上限為 50MB。',
    '安全令牌已刷新，请重试；如有草稿，将自动恢复。': '安全權杖已更新，請重試；已儲存的草稿會自動還原。',
    '请重新登录；如有草稿，将在登录后自动恢复。': '請重新登入；已儲存的草稿會在登入後自動還原。',
    '辅助节点或手工修改格式无效，请检查名称、国家及链接。': '輔助節點或手動修改格式無效，請檢查名稱、國家及連結。',
    '节点解析失败，请检查链接格式、必填字段及端口范围。': '無法解析節點，請檢查連結格式、必填欄位及連接埠範圍。',
    '节点名称不能为空。': '節點名稱不能為空。',
    '节点名称重复，请修改名称以防止冲突。': '節點名稱重複，請修改名稱以避免衝突。',
    '不支持的国家代码。请使用 ISO alpha-2 或 UNKNOWN。': '不支援的國家代碼，請使用 ISO alpha-2 或 UNKNOWN。',
    '不支持的国家代码。': '不支援的國家代碼。',
    '协议不支持，仅接受 vmess:// 或 vless://。': '不支援的協定，請使用 VMess、VLESS、Trojan、Shadowsocks 或 Hysteria2。',
    '手工修改格式无效。': '手動修改格式無效。',
    'Country Unknown — choose a country or generate as 其他节点.': '國家未知，請選擇國家，或歸入「其他節點」組產生。',
    'Trojan 配置无效或包含不支持的选项。': 'Trojan 設定無效或包含不支援的選項。',
    'Trojan 链接无效或包含不支持的参数。': 'Trojan 連結無效或包含不支援的參數。',
    'Shadowsocks 链接或配置无效，请检查编码、必填字段及端口。': 'Shadowsocks 連結或設定無效，請檢查編碼、必填欄位及連接埠。',
    'Shadowsocks 插件及混淆选项不受支持。': '不支援 Shadowsocks 外掛及混淆選項。',
    'Shadowsocks URI query 参数不受支持。': '不支援 Shadowsocks URI query 參數。',
    '端口必须是 1–65535 的整数。': '連接埠必須是 1–65535 的整數。',
    'Base64 或 JSON 结构解析失败': 'Base64 或 JSON 結構無效',
    'VMess JSON 必须是对象。': 'VMess JSON 必須是物件。',
    '节点解析失败，缺失必填字段 (add/server, port, 或 id)': '缺少節點必填欄位（add/server、port 或 id）',
    '节点解析失败，缺失必填字段 (server, port, 或 uuid)': '缺少節點必填欄位（server、port 或 uuid）',
    'VLESS 地址或端口格式无效。': 'VLESS 位址或連接埠無效。',
    'YAML 格式错误，请检查缩进、引号和重复键。': 'YAML 格式錯誤，請檢查縮排、引號與重複鍵。',
    'YAML 处理失败，请检查配置结构、磁盘空间及目录权限。': 'YAML 處理失敗，請檢查設定結構、磁碟空間及目錄權限。',
    'YAML 顶层必须是映射。': 'YAML 頂層必須是對應（mapping）。',
    '必须是列表。': '必須是清單。',
    '项的 ': '項的 ',
    '项必须有有效名称。': '項必須有有效名稱。',
    '项名称重复，请先处理冲突。': '項名稱重複，請先處理衝突。',
    '必须是字符串列表。': '必須是字串清單。',
    '条引用了被替换的旧节点，请先改为保留的策略组。': '條引用了被替換的舊節點，請先改用保留的策略組。',
    '新节点名称与策略组或内置策略冲突。': '新節點名稱與策略組或內建策略衝突。',
    '新节点名称与策略组冲突。': '新節點名稱與策略組衝突。',
    '新节点数据必须是列表格式。': '新節點必須是清單。',
    '个节点格式错误，必须是字典对象。': '個節點必須是對應（mapping）。',
    '个节点缺失 name 字段或为空。': '個節點缺少 name 欄位或為空。',
    '个节点名称重复。': '個節點名稱重複。',
    '个节点缺失 type 字段。': '個節點缺少 type 欄位。',
    '个节点缺失 server 字段。': '個節點缺少 server 欄位。',
    '个节点端口必须是 1–65535 的整数。': '個節點連接埠必須是 1–65535 的整數。',
    '个节点缺失 uuid 字段。': '個節點缺少 uuid 欄位。',
    '个节点缺失 password 字段。': '個節點缺少 password 欄位。',
    '个节点 Hysteria2 配置无效。': '個節點 Hysteria2 設定無效。',
    '个节点缺失 cipher 字段。': '個節點缺少 cipher 欄位。',
    '个策略组为空，且未引用 proxy-providers 或 include-all。': '個策略組為空，且未引用 proxy-providers 或 include-all。',
    '个策略组中存在无效的节点或策略组引用。': '個策略組含有無效的節點或策略組引用。',
    'Policy 配置无效，请检查类型、选项、URL 和数值范围。': '策略設定無效，請檢查類型、選項、URL 與數值範圍。',
    '自动策略组没有有效的新节点。旧订阅保持不变。': '自動策略組沒有有效的新節點，原訂閱保持不變。',
    '固定订阅状态不可用，请检查 state/ 并从备份恢复。': '固定訂閱狀態無法使用，請檢查 state/ 並從備份還原。',
    '请检查订阅名称和配置。': '請檢查訂閱名稱與設定。',
    '节点无效，请检查节点及手工修改。': '節點無效，請檢查節點及手動修改。',
    '请选择 Custom YAML。': '請選擇自訂 YAML 檔案。',
    '生成失败，请检查节点、YAML 结构及策略组引用。旧订阅保持不变。': '產生失敗，請檢查節點、YAML 結構及策略組引用，原訂閱保持不變。',
    'Custom YAML needs to be selected again.': '需要重新選擇自訂 YAML 檔案。',
    'Country Detection settings are invalid.': '國家偵測設定無效。',
    'Health-aware Policy settings are invalid.': '健康感知策略設定無效。',
    'Node Update Mode is invalid. Choose Replace or Merge.': '節點更新模式無效，請選擇「取代」或「合併」。',
    'Diff is too large to display. Generate YAML is still available.': 'YAML 差異過大無法顯示，仍可直接產生 YAML。',
    'Session or security token expired; refresh or log in again. Any saved draft will be restored.': '登入狀態或安全權杖已失效，請重新整理或重新登入；已儲存的草稿會自動還原。',
    'Session expired; refresh or log in again.': '登入已逾時，請重新整理或重新登入。',
    'Node name already exists in source YAML.': '節點名稱已存在於來源 YAML 中。',
    'Source node name conflicts with a proxy group.': '來源節點名稱與策略組衝突。',
    'Template profile is invalid.': '模板設定無效。',
}
# Only fixed safe message structure is rewritten, never node names or YAML/diff.
DISPLAY_PATTERNS = (
    (r'登录尝试过多，请在 (\d+) 秒后重试。', r'登入嘗試次數過多，請在 \1 秒後重試。'),
    (r'已成功删除 (\d+) 个服务器临时文件。', r'已刪除 \1 個伺服器暫存檔案。'),
    (r'第 (\d+) 行错误：', r'第 \1 行錯誤：'),
    (r'\A(\d+) unsupported proxies skipped\Z', r'已略過 \1 個不支援的代理節點'),
)

# Exact internal enum/status values shown in pages. Unknown values are shown as-is.
DISPLAY_LABELS = {
    'Not installed': '未安裝', 'Ready': '就緒', 'Unavailable / Invalid': '無法使用／無效',
    'Unavailable': '無法使用', 'Warning': '警告', 'Error': '錯誤',
    'Manual': '手動指定', 'Name Detection': '名稱偵測', 'GeoIP': 'GeoIP', 'Unknown': '未知',
    # Health statuses and modes.
    'healthy': '健康', 'suspect': '可疑', 'unhealthy': '不健康', 'unknown': '未知',
    'unsupported': '不支援', 'unavailable': '無法使用', 'off': '關閉', 'manual': '手動',
    'automatic': '自動', 'active': '啟用中', 'disabled': '已停用',
    # Triggers and job / refresh / reconciliation / delivery results.
    'auto': '自動', 'save': '儲存', 'success': '成功', 'cached': '使用快取', 'error': '錯誤',
    'conflict': '衝突', 'engine_unavailable': '引擎無法使用', 'limit': '超出上限', 'busy': '忙碌中',
    'unchanged': '未變更', 'updated': '已更新', 'fail-open': '保守保留（fail-open）', 'failure': '失敗',
    # Telegram delivery errors.
    'timeout': '逾時', 'network': '網路錯誤', 'tls': 'TLS 錯誤', 'http': 'HTTP 錯誤',
    'api': 'Telegram API 錯誤', 'invalid_response': '回應無效', 'config': '設定錯誤',
    'COMPATIBLE': '相容', 'INCOMPATIBLE': '不相容', 'BROKEN': '損壞', 'NOT INSTALLED': '未安裝',
    'Configured': '已設定', 'Not configured': '未設定', 'Metadata unavailable': '中繼資料無法使用',
}


def display_message(value):
    text = str(value)
    for original, translated in sorted(DISPLAY_PHRASES.items(), key=lambda pair: len(pair[0]), reverse=True):
        text = text.replace(original, translated)
    for pattern, replacement in DISPLAY_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text


def display_label(value):
    if value is None:
        return '—'
    return DISPLAY_LABELS.get(str(value), str(value))

# Only Parse/Diff phrases are needed in the browser. Authentication and notices
# are server-rendered, so do not duplicate their copy in every page's script data.
BROWSER_DISPLAY_PHRASES = {
    original: translated for original, translated in DISPLAY_PHRASES.items()
    if original not in (
        '登录失败，密码错误。', '两次输入的新密码不一致。', '新密码不能为空。',
        '当前密码不正确或登录状态已失效。', '密码保存失败，请检查认证状态文件权限。',
        '更新密码失败，请检查认证状态文件权限。',
        '管理密码已更新，请使用新密码重新登录。',
        '配置已成功更新，您可以下载或清理临时文件。',
        '未找到可删除的文件或文件已被清理。', '删除临时文件失败，请检查目录权限。',
        '安全令牌已刷新，请重试；如有草稿，将自动恢复。',
        '请重新登录；如有草稿，将在登录后自动恢复。',
    )
}
# Browser labels for parse records; the same table the server uses.
BROWSER_DISPLAY_LABELS = {key: DISPLAY_LABELS[key] for key in
                          ('Ready', 'Warning', 'Error', 'Manual', 'Name Detection', 'GeoIP', 'Unknown')}
