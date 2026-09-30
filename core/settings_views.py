"""Authenticated minimal System Settings; database data only, no bulk regeneration."""
from datetime import datetime, timezone

from flask import Blueprint, redirect, render_template, request, session, url_for

from core.geoip_store import GeoIPError, MAX_DATABASE


def blueprint(store, context, login_required):
    views = Blueprint('settings', __name__, url_prefix='/settings')

    @views.route('', methods=['GET'])
    @login_required
    def index():
        ctx = context()
        ctx['success_message'] = session.pop('settings_notice', '')
        error = session.pop('settings_error', '')
        if error: ctx['error_messages'].append(error)
        value = store.status()
        value['uploaded_display'] = (datetime.fromtimestamp(value['uploaded_at'], timezone.utc).isoformat(timespec='seconds')
                                     if value.get('uploaded_at') is not None else 'Never')
        return render_template('settings.html', **ctx, database=value, database_limit=MAX_DATABASE // (1024 * 1024))

    @views.route('/upload', methods=['POST'])
    @login_required
    def upload():
        file = request.files.get('geoip_file')
        try:
            if file is None:
                raise GeoIPError('Choose a compatible .mmdb file.')
            store.upload(file.filename, file.stream)
        except GeoIPError:
            ctx = context()
            ctx['error_messages'] = ['Unable to upload GeoIP database. Choose a valid country-capable .mmdb within the size limit. Previous database is unchanged.']
            value = store.status()
            value['uploaded_display'] = (datetime.fromtimestamp(value['uploaded_at'], timezone.utc).isoformat(timespec='seconds')
                                         if value.get('uploaded_at') is not None else 'Never')
            return render_template('settings.html', **ctx, database=value, database_limit=MAX_DATABASE // (1024 * 1024)), 400
        session['settings_notice'] = 'GeoIP database uploaded. Existing Fixed YAML remains unchanged.'
        return redirect(url_for('settings.index'), code=303)

    @views.route('/remove', methods=['POST'])
    @login_required
    def remove():
        try:
            store.remove()
            session['settings_notice'] = 'GeoIP database removed. Existing Fixed YAML remains unchanged.'
        except GeoIPError:
            session['settings_error'] = 'GeoIP database could not be removed. Check private state permissions.'
        return redirect(url_for('settings.index'), code=303)

    return views
