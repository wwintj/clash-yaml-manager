"""Allowlisted source failures: never retain transport/parser exception text."""
import re

MESSAGES = {
    'url': '遠端 URL 無效', 'address': '遠端位址不是公開位址',
    'dns': 'DNS 解析失敗', 'connection': '連線失敗',
    'timeout': '來源請求逾時', 'tls': 'TLS 驗證失敗',
    'redirect': '重新導向無效或次數過多', 'size': '回應內容過大',
    'encoding': '不支援的回應編碼', 'format': '不支援的來源格式',
    'invalid': '來源內容無效', 'empty': '沒有支援的節點',
    'duplicate': '節點名稱重複', 'config': '來源設定無效',
    'upload': '請選擇節點來源檔案',
    'conflict': '重新整理期間訂閱已變更，請重試',
    'generation': '來源彙整或 YAML 產生失敗',
}


def valid_code(code):
    return isinstance(code, str) and (code in MESSAGES or re.fullmatch(r'http_[1-5][0-9]{2}', code) is not None)


def message(code):
    if code in MESSAGES:
        return MESSAGES[code]
    return 'HTTP ' + code[5:] if valid_code(code) else '來源無法使用'


class SourceError(ValueError):
    def __init__(self, code):
        self.code = code if valid_code(code) else 'invalid'
        super().__init__(message(self.code))
