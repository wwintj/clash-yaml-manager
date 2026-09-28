"""Authenticated fixed-subscription management; public routing remains in app.py."""
from datetime import datetime, timezone
import json

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from core import generator
from core.fixed_subscriptions import GenerationError


def blueprint(store, base_context, login_required, default_yaml, special_groups, public_url):
    views = Blueprint('fixed', __name__, url_prefix='/fixed-subscriptions')

    def context():
        value = base_context()
        value['success_message'] = session.pop('fixed_notice', '')
        value['csrf_notice'] = session.pop('csrf_notice', '')
        return value

    def display(entry):
        value = dict(entry, public_url=public_url(store.slug(entry)))
        for field in ('updated_at', 'last_access_at'):
            value[field + '_display'] = ('Never' if entry[field] is None else
                datetime.fromtimestamp(entry[field], timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))
        return value

    @views.route('')
    @login_required
    def index():
        return render_template('fixed_list.html', **context(), entries=[display(r) for r in store.list()])

    def form_page(key=None):
        entry = store.get(key) if key else None
        if key and not entry:
            abort(404)
        fields = entry or dict(name='', prefix='', yaml_source='default', batch_nodes='',
                               aux_nodes=[], node_overrides={}, special_groups=[])
        ctx = context()
        status = 200
        if request.method == 'POST':
            # No rejected body or uploaded file is stored in a cookie/browser draft.
            fields = dict(name=request.form.get('name', ''), prefix=request.form.get('prefix', ''),
                          yaml_source=request.form.get('yaml_source', 'default'),
                          batch_nodes=request.form.get('batch_nodes', ''), aux_nodes=[],
                          node_overrides={}, special_groups=[g for g in request.form.getlist('special_groups')
                                                           if g in special_groups])
            try:
                fields['aux_nodes'] = json.loads(request.form.get('aux_nodes', '[]'))
                fields['node_overrides'] = json.loads(request.form.get('node_overrides', '{}'))
                parsed = generator.parse_form_nodes(request.form)
                upload = request.files.get('yaml_file')
                custom = None
                if fields['yaml_source'] == 'custom' and upload and upload.filename:
                    if '.' not in upload.filename or upload.filename.rsplit('.', 1)[1].lower() not in ('yaml', 'yml'):
                        raise GenerationError('仅支持 .yaml / .yml 文件。')
                    custom = upload.read(50 * 1024 * 1024 + 1)
                source = {k: fields[k] for k in ('yaml_source', 'batch_nodes', 'aux_nodes', 'node_overrides', 'special_groups')}
                saved = store.save(key, fields['name'], fields['prefix'], source, parsed, default_yaml, custom)
                session['fixed_notice'] = 'Fixed subscription saved.' if key else 'Fixed subscription created.'
                return redirect(url_for('fixed.edit', key=saved['id']), code=303)
            except (ValueError, TypeError):
                ctx['error_messages'] = ['Unable to save. Check the name, nodes, YAML and policy references. The previous subscription is unchanged.']
                status = 400
            except KeyError:
                abort(404)
        # Sanitize malformed structured input before rendering it into form controls.
        from core.fixed_subscriptions import valid_source
        if not valid_source(fields):
            fields = dict(fields, yaml_source='default', aux_nodes=[], node_overrides={}, special_groups=[])
        return render_template('fixed_form.html', **ctx, fields=fields,
                               entry=display(entry) if entry else None,
                               saved_custom=bool(entry and entry['yaml_source'] == 'custom')), status

    @views.route('/new', methods=['GET', 'POST'])
    @login_required
    def create():
        return form_page()

    @views.route('/<key>/edit', methods=['GET', 'POST'])
    @login_required
    def edit(key):
        return form_page(key)

    @views.route('/<key>/<action>', methods=['POST'])
    @login_required
    def action(key, action):
        if action not in ('enable', 'disable', 'regenerate', 'delete'):
            abort(404)
        try:
            store.action(key, action)
        except KeyError:
            abort(404)
        session['fixed_notice'] = 'Fixed subscription deleted.' if action == 'delete' else 'Fixed subscription updated.'
        return redirect(url_for('fixed.index'), code=303)

    return views
