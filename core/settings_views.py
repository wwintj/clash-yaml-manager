"""Authenticated modular Settings: composition of existing authoritative stores."""
from datetime import datetime, timezone

from flask import Blueprint, redirect, render_template, request, session, url_for

from core.notifications import NotificationError
from core.notification_events import CATEGORIES
from core.geoip_store import GeoIPError, MAX_DATABASE
from core.proxy_health import ProxyHealthError
from core.settings_status import engine_status, probe_fields


def blueprint(store, context, login_required, *, proxy_health, fixed, runtime_context, notifications):
    views = Blueprint('settings', __name__, url_prefix='/settings')

    def page(error=None):
        ctx = context()
        ctx['success_message'] = session.pop('settings_notice', '')
        ctx['csrf_notice'] = session.pop('csrf_notice', '')
        message = error or session.pop('settings_error', '')
        if message:
            ctx['error_messages'].append(message)
        database = dict(ctx['geoip_status'])
        try:
            database['uploaded_display'] = (datetime.fromtimestamp(database['uploaded_at'], timezone.utc).isoformat(timespec='seconds')
                                           if database.get('uploaded_at') is not None else '從未')
        except (ValueError, OSError, OverflowError, TypeError):
            database = dict(status='Unavailable / Invalid', uploaded_display='從未')
        try:
            defaults = proxy_health.global_settings()
        except Exception:
            defaults = None
        engine = engine_status(proxy_health.engine)
        try:
            counts = fixed.counts()
        except Exception:
            counts = None
        try:
            runtime = runtime_context()
        except Exception:
            runtime = None
        try:
            notification_status = notifications.status()
        except Exception:
            notification_status = None
        return render_template('settings.html', **ctx, database=database,
            database_limit=MAX_DATABASE // (1024 * 1024), proxy_defaults=defaults,
            engine=engine, fixed_counts=counts, runtime=runtime, notifications=notification_status)

    @views.route('', methods=['GET'])
    @login_required
    def index():
        return page()

    @views.route('/health/proxy-defaults', methods=['POST'])
    @login_required
    def proxy_defaults():
        try:
            proxy_health.set_global(probe_fields(request.form))
        except ProxyHealthError:
            # Rejected input never reaches HTML, session or operational logs.
            return page('無法儲存全域代理預設值。請使用不含憑證、查詢參數或片段的公開 HTTPS 目標，並填入有效的狀態碼與逾時值。原預設值保持不變。'), 400
        session['settings_notice'] = '全域代理預設值已儲存。數值有變更時，使用全域預設值的訂閱會重設觀測結果與排程。'
        return redirect(url_for('settings.index', _anchor='health'), code=303)

    @views.route('/upload', methods=['POST'])
    @login_required
    def upload():
        file = request.files.get('geoip_file')
        try:
            if file is None:
                raise GeoIPError('Choose a compatible .mmdb file.')
            store.upload(file.filename, file.stream)
        except GeoIPError:
            return page('無法上傳 GeoIP 資料庫。請選擇大小在上限內、含國家資料的有效 .mmdb 檔案。原資料庫保持不變。'), 400
        session['settings_notice'] = 'GeoIP 資料庫已上傳，既有固定訂閱的 YAML 保持不變。'
        return redirect(url_for('settings.index', _anchor='geoip'), code=303)

    @views.route('/remove', methods=['POST'])
    @login_required
    def remove():
        try:
            store.remove()
            session['settings_notice'] = 'GeoIP 資料庫已移除，既有固定訂閱的 YAML 保持不變。'
        except GeoIPError:
            session['settings_error'] = '無法移除 GeoIP 資料庫，請檢查私有狀態檔案權限。'
        return redirect(url_for('settings.index', _anchor='geoip'), code=303)

    @views.route('/notifications', methods=['POST'])
    @login_required
    def notification_save():
        try:
            # Duplicate/unknown fields cannot hide invalid input behind checkbox parsing.
            allowed = {'csrf_token', 'enabled', 'bot_token', 'chat_id', *CATEGORIES}
            if (set(request.form) - allowed or any(len(request.form.getlist(key)) != 1 for key in request.form)
                    or any(request.form.get(key) not in (None, 'on') for key in ('enabled', *CATEGORIES))):
                raise NotificationError
            notifications.save(request.form.get('enabled') == 'on',
                {key: request.form.get(key) == 'on' for key in CATEGORIES},
                request.form.get('bot_token', ''), request.form.get('chat_id', ''))
            session['settings_notice'] = '通知設定已儲存（儲存時不會連線 Telegram）。'
        except Exception:
            session['settings_error'] = '無法儲存通知設定，請檢查憑證與私有狀態檔案權限。原設定保持不變。'
        return redirect(url_for('settings.index', _anchor='notifications'), code=303)

    @views.route('/notifications/test', methods=['POST'])
    @login_required
    def notification_test():
        result = notifications.deliver(test=True)
        if result == 'success':
            session['settings_notice'] = 'Telegram 測試通知已傳送。'
        else:
            session['settings_error'] = 'Telegram 測試失敗，請檢查已儲存的憑證、私有狀態檔案權限與對外網路連線。'
        return redirect(url_for('settings.index', _anchor='notifications'), code=303)

    @views.route('/notifications/remove', methods=['POST'])
    @login_required
    def notification_remove():
        try:
            notifications.remove()
            session['settings_notice'] = 'Telegram 通知已停用，憑證已移除。'
        except Exception:
            session['settings_error'] = '無法移除通知憑證，請檢查私有狀態檔案權限。'
        return redirect(url_for('settings.index', _anchor='notifications'), code=303)

    return views
