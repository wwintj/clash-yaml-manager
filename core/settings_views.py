"""Authenticated modular Settings: composition of existing authoritative stores."""
from datetime import datetime, timezone

from flask import Blueprint, redirect, render_template, request, session, url_for

from core.geoip_store import GeoIPError, MAX_DATABASE
from core.proxy_health import ProxyHealthError
from core.settings_status import engine_status, probe_fields


def blueprint(store, context, login_required, *, proxy_health, fixed, runtime_context):
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
                                           if database.get('uploaded_at') is not None else 'Never')
        except (ValueError, OSError, OverflowError, TypeError):
            database = dict(status='Unavailable / Invalid', uploaded_display='Never')
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
        return render_template('settings.html', **ctx, database=database,
            database_limit=MAX_DATABASE // (1024 * 1024), proxy_defaults=defaults,
            engine=engine, fixed_counts=counts, runtime=runtime)

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
            return page('Unable to save global proxy defaults. Use a public HTTPS target without credentials, query or fragment and valid status/timeout values. Previous defaults are unchanged.'), 400
        session['settings_notice'] = 'Global proxy defaults saved. Observations and schedules reset for subscriptions using global defaults when values change.'
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
            return page('Unable to upload GeoIP database. Choose a valid country-capable .mmdb within the size limit. Previous database is unchanged.'), 400
        session['settings_notice'] = 'GeoIP database uploaded. Existing Fixed YAML remains unchanged.'
        return redirect(url_for('settings.index', _anchor='geoip'), code=303)

    @views.route('/remove', methods=['POST'])
    @login_required
    def remove():
        try:
            store.remove()
            session['settings_notice'] = 'GeoIP database removed. Existing Fixed YAML remains unchanged.'
        except GeoIPError:
            session['settings_error'] = 'GeoIP database could not be removed. Check private state permissions.'
        return redirect(url_for('settings.index', _anchor='geoip'), code=303)

    return views
