"""Safe Runtime projection and bounded status presentation via feature owners."""
import math
import re
from urllib.parse import urlsplit

from core.proxy_health import ProxyHealthError


def geoip_status(store):
    try:
        return store.status()
    except Exception:
        return {'status': 'Unavailable / Invalid'}


def engine_status(engine):
    try:
        value = engine.status(verify_execution=False)
        if value['status'] not in ('NOT INSTALLED', 'BROKEN', 'INCOMPATIBLE', 'COMPATIBLE'):
            raise ValueError
        result = {'status': value['status']}
        for field in ('required', 'installed', 'architecture', 'cpu_level', 'build', 'preferred_build'):
            item = value.get(field)
            result[field] = (item if isinstance(item, str) and re.fullmatch(r'[A-Za-z0-9._-]{1,64}', item) else '—')
        return result
    except Exception:
        return {'status': 'Unavailable'}


def probe_fields(form, prefix='global_'):
    """Transport coercion only. ProxyHealth.set_global owns validation/persistence."""
    try:
        return dict(url=form[prefix+'url'], expected_status=int(form[prefix+'expected_status']),
                    timeout_ms=int(form[prefix+'timeout_ms']))
    except (ValueError, KeyError, TypeError):
        raise ProxyHealthError('settings') from None


def runtime(*, port, cookie_secure, trust_proxy, download_base, download_scheme,
            upload_retention, output_retention, cleanup_interval, backup_retention, bind="0.0.0.0", managed_https=None,
            session_lifetime_days=30, retention_policies=('timed', 'timed', 'timed'),
            temporary_link_lifetime=None):
    # Never return arbitrary environment strings, even escaped URLs or origins.
    https = download_scheme == 'https' if not download_base else False
    if download_base:
        try:
            parts = urlsplit(download_base)
            https = (parts.scheme == 'https' and bool(parts.hostname) and parts.username is None
                     and parts.password is None and not parts.query and not parts.fragment
                     and not any(ord(c) <= 32 or ord(c) == 127 for c in download_base)
                     and '\\' not in download_base and (parts.port is None or 1 <= parts.port <= 65535))
        except ValueError:
            pass
    values = dict(port=port if type(port) is int and 1 <= port <= 65535 else '無法使用',
        cookie_secure='已啟用' if cookie_secure else '已停用',
        trust_proxy='已啟用' if trust_proxy else '已停用',
        download_mode='明確指定基礎 URL' if download_base else ('明確指定協定' if download_scheme else '自動'),
        download_base='已設定' if download_base else '未設定',
        download_scheme=download_scheme if download_scheme in ('http', 'https') else '自動',
        https_download='已設定' if https else '未設定',
        session_lifetime=(f'{session_lifetime_days} 天'
                          if type(session_lifetime_days) is int and 1 <= session_lifetime_days <= 3650 else '無法使用'),
        bind='僅限本機迴路' if bind == '127.0.0.1' else '所有網路介面',
        managed_https=(managed_https or {'status':'Not configured'}))
    for field, value in dict(upload_retention=upload_retention, output_retention=output_retention,
                            cleanup_interval=cleanup_interval, backup_retention=backup_retention).items():
        values[field] = format(value, 'g') + ' 秒' if type(value) in (int, float) and math.isfinite(value) and value >= 0 else '無法使用'
    if not isinstance(retention_policies, (tuple, list)) or len(retention_policies) != 3:
        retention_policies = (None, None, None)
    for field, policy in zip(('upload_retention', 'output_retention', 'backup_retention'), retention_policies):
        if policy == 'keep':
            values[field] = '永久保留：不依時間刪除，請自行管理磁碟空間。'
        elif policy != 'timed':
            values[field] = '無法使用'
    if retention_policies[1] == 'keep':
        link = (format(temporary_link_lifetime, 'g') + ' 秒'
                if type(temporary_link_lifetime) in (int, float) and math.isfinite(temporary_link_lifetime)
                and temporary_link_lifetime > 0 else '無法使用')
        values['output_retention'] += '臨時連結有效期：' + link + '。'
    return values
