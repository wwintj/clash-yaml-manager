"""Authenticated fixed-subscription management; public routing remains in app.py."""
from datetime import datetime, timezone
import json

from core import policy_engine, health_policy, geoip

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from core import generator, health_schedule, refresh_schedule
from core.fixed_subscriptions import GenerationError
from core.node_health import NodeHealth, HealthError, PROBE_MESSAGES
from core.proxy_health import ProxyHealth, ProxyHealthError, DEFAULT_PROBE
from core.source_errors import SourceError, message
from core.source_parser import MAX_PAYLOAD


def blueprint(store, base_context, login_required, default_yaml, special_groups, public_url):
    views = Blueprint('fixed', __name__, url_prefix='/fixed-subscriptions')
    health = NodeHealth(store)
    try:
        proxy_health = ProxyHealth(store)
    except Exception:
        # The managed engine/manifest is optional; Fixed management stays usable.
        proxy_health = None

    def context():
        value = base_context()
        value['success_message'] = session.pop('fixed_notice', '')
        value['csrf_notice'] = session.pop('csrf_notice', '')
        value['health_notice'] = session.pop('health_notice', '')
        value['proxy_notice'] = session.pop('proxy_notice', '')
        error = session.pop('fixed_error', '')
        if error:
            value['error_messages'] = [error]
        return value

    def display(entry):
        value = dict(entry, public_url=public_url(store.slug(entry)))
        for field in ('updated_at', 'last_access_at'):
            value[field + '_display'] = ('Never' if entry[field] is None else
                datetime.fromtimestamp(entry[field], timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))
        at = entry['health_policy_audit']['last_reconciled_at']
        value['health_policy_time_display'] = ('Never' if at is None else
            datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))
        return value

    def source_display(item):
        value = dict(item)
        value['status_display'] = ('Disabled' if not item['enabled'] else
            'Cached' if item['using_cache'] else 'Error' if item['last_error'] else
            'Ready' if item['last_success_at'] is not None else 'Never fetched')
        value['success_display'] = ('Never' if item['last_success_at'] is None else
            datetime.fromtimestamp(item['last_success_at'], timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))
        value['error_display'] = message(item['last_error']) if item['last_error'] else ''
        if item['type'] == 'remote_url':
            def utc(at, empty='Never'):
                return empty if at is None else datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
            value['attempt_display'] = utc(item['last_attempt_at'])
            value['next_display'] = utc(item['next_refresh_at'], '—')
            value['history_display'] = [dict(record, at_display=utc(record['at']),
                error_display=message(record['error']) if record['error'] else '')
                for record in reversed(item['refresh_history'][-5:])]
        return value

    def health_display(key):
        def utc(at):
            return '—' if at is None else datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        try:
            value = health.describe(key)
        except KeyError:
            return dict(unavailable='Health state unavailable.')
        except HealthError as error:
            return dict(unavailable=str(error))
        for row in value['rows']:
            row['latency_display'] = '—' if row['latency_ms'] is None else str(int(row['latency_ms'] + .5)) + ' ms'
            row['checked_display'] = utc(row['last_checked_at'])
            row['success_display'] = utc(row['last_success_at'])
            row['error_display'] = PROBE_MESSAGES.get(row['error'], '')
        value['check_display'] = utc(value['last_check_at'])
        value['next_display'] = utc(value['next_check_at'])
        value['trigger_display'] = value['last_trigger'] or '—'
        value['scheduler_display'] = value['last_job_result'] or '—'
        return value

    def proxy_display(key, endpoint):
        def utc(at):
            return '—' if at is None else datetime.fromtimestamp(at, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        engine = (proxy_health.engine.status() if proxy_health else
                  dict(status='BROKEN',required='v1.19.31',installed=None,architecture='unknown'))
        if proxy_health is None:
            return dict(engine=engine,unavailable='Proxy health state unavailable.',global_settings=DEFAULT_PROBE)
        try:
            value = proxy_health.describe(key)
        except (KeyError, ProxyHealthError, HealthError) as error:
            return dict(engine=engine,unavailable=(str(error) if isinstance(error, ProxyHealthError)
                else 'Proxy health state unavailable.'),global_settings=DEFAULT_PROBE)
        endpoint_rows = ({row['fingerprint']:row for row in endpoint['rows']}
                         if 'rows' in endpoint and endpoint.get('revision') == value['revision'] else {})
        for row in value['rows']:
            observed = endpoint_rows.get(row['fingerprint'], {})
            row['endpoint_status'] = observed.get('status','unknown')
            tcp = observed.get('latency_ms')
            row['tcp_latency_display'] = '—' if tcp is None else str(int(tcp + .5)) + ' ms'
            row['endpoint_failures'] = observed.get('consecutive_failures',0)
            row['proxy_latency_display'] = '—' if row['latency_ms'] is None else str(int(row['latency_ms'] + .5)) + ' ms'
            row['proxy_check_display'] = utc(row['last_checked_at'])
        value['engine'] = engine
        value['check_display'] = utc(value['last_check_at'])
        value['next_display'] = utc(value['next_check_at'])
        value['trigger_display'] = value['last_trigger'] or '—'
        value['scheduler_display'] = value['last_job_result'] or '—'
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
        external = entry['sources'][1:] if entry else []
        ctx = context()
        ctx['policy_fields'] = policy_engine.form_values(fields.get('policy_config', policy_engine.defaults()))
        ctx['health_policy_fields'] = health_policy.form_values(fields.get('health_policy'))
        ctx['country_geoip'] = fields.get('country_detection', geoip.defaults())['geoip']
        status = 200
        if request.method == 'POST':
            # No rejected body or uploaded file is stored in a cookie/browser draft.
            fields = dict(name=request.form.get('name', ''), prefix=request.form.get('prefix', ''),
                          yaml_source=request.form.get('yaml_source', 'default'),
                          batch_nodes=request.form.get('batch_nodes', ''), aux_nodes=[],
                          node_overrides={}, special_groups=[g for g in request.form.getlist('special_groups')
                                                           if g in special_groups])
            ctx['policy_fields'] = policy_engine.submitted_values(request.form)
            ctx['health_policy_fields'] = health_policy.form_values(form=request.form)
            ctx['country_geoip'] = request.form.get('country_geoip', 'off')[:64]
            try:
                external = json.loads(request.form.get('sources', json.dumps(external)))
                if not isinstance(external, list) or len(external) > 63 or any(not isinstance(s, dict) for s in external):
                    raise SourceError('config')
                fields['aux_nodes'] = json.loads(request.form.get('aux_nodes', '[]'))
                fields['node_overrides'] = json.loads(request.form.get('node_overrides', '{}'))
                fields['policy_config'] = policy_engine.parse_form(request.form)
                fields['health_policy'] = health_policy.parse_form(request.form)
                fields['country_detection'] = geoip.parse_form(request.form)
                parsed = generator.parse_form_nodes(request.form)
                upload = request.files.get('yaml_file')
                custom = None
                if fields['yaml_source'] == 'custom' and upload and upload.filename:
                    if '.' not in upload.filename or upload.filename.rsplit('.', 1)[1].lower() not in ('yaml', 'yml'):
                        raise GenerationError('仅支持 .yaml / .yml 文件。')
                    custom = upload.read(50 * 1024 * 1024 + 1)
                source = {k: fields[k] for k in ('yaml_source', 'batch_nodes', 'aux_nodes', 'node_overrides', 'special_groups', 'policy_config', 'health_policy', 'country_detection')}
                uploads = {}
                for index in range(len(external)):
                    upload = request.files.get('source_file_' + str(index))
                    if upload and upload.filename:
                        uploads[index] = upload.read(MAX_PAYLOAD + 1)
                saved = store.save(key, fields['name'], fields['prefix'], source, parsed, default_yaml, custom,
                                   sources=external, uploads=uploads, expected=entry)
                session['fixed_notice'] = 'Fixed subscription saved.' if key else 'Fixed subscription created.'
                return redirect(url_for('fixed.edit', key=saved['id']), code=303)
            except SourceError as error:
                ctx['error_messages'] = ['Unable to save. ' + message(error.code) + '. The previous subscription is unchanged.']
                status = 409 if error.code == 'conflict' else 400
            except (ValueError, TypeError):
                ctx['error_messages'] = ['Unable to save. Check the name, nodes, YAML and policy references. The previous subscription is unchanged.']
                status = 400
            except KeyError:
                abort(404)
        # Sanitize malformed structured input before rendering it into form controls.
        from core.fixed_subscriptions import valid_source
        if not valid_source(fields):
            fields = dict(fields, yaml_source='default', aux_nodes=[], node_overrides={}, special_groups=[])
        if not isinstance(external, list) or any(not isinstance(s, dict) for s in external):
            external = []
        # Failed POST values are editable, but status always comes from committed state.
        saved_sources = {s['id']: s for s in entry['sources'][1:]} if entry else {}
        cards = []
        for row in external[:63]:
            identifier = row.get('id', '')
            saved = saved_sources.get(identifier) if isinstance(identifier, str) else None
            cards.append(dict(fields={k: row.get(k, None if k == 'refresh_interval_seconds' else '') for k in
                                      ('id','type','name','url','format','enabled','refresh_interval_seconds')},
                              saved=source_display(saved) if saved else None))
        endpoint = health_display(key) if entry else None
        proxy = proxy_display(key, endpoint) if entry else None
        return render_template('fixed_form.html', **ctx, fields=fields,
                               entry=display(entry) if entry else None,
                               external_cards=cards,
                               refresh_options=refresh_schedule.OPTIONS, health_options=health_schedule.OPTIONS,
                               node_health=endpoint, proxy_health=proxy,
                               health_policy_ages=list(zip(health_policy.AGES,health_policy.AGE_LABELS)),
                               saved_custom=bool(entry and entry['yaml_source'] == 'custom')), status

    @views.route('/new', methods=['GET', 'POST'])
    @login_required
    def create():
        return form_page()

    @views.route('/<key>/edit', methods=['GET', 'POST'])
    @login_required
    def edit(key):
        return form_page(key)

    def health_interval():
        value = request.form.get('interval_seconds')
        if value in (None,''):
            return None
        try:
            return int(value)
        except (ValueError,TypeError):
            raise ValueError('Invalid health interval.') from None

    @views.route('/<key>/health/<operation>', methods=['POST'])
    @login_required
    def health_action(key, operation):
        if operation not in ('settings','check'): abort(404)
        try:
            if operation == 'settings':
                try:
                    seconds = health_interval()
                except ValueError:
                    raise HealthError('config') from None
                health.settings(key, request.form.get('mode'),seconds)
                session['health_notice'] = 'Health settings saved.'
            else:
                health.check(key)
                session['health_notice'] = 'Endpoint reachability check completed.'
        except KeyError:
            abort(404)
        except HealthError as error:
            session['health_notice'] = str(error)
        if store.get(key):
            return redirect(url_for('fixed.edit', key=key), code=303)
        if session.get('health_notice'):
            session['fixed_error'] = session.pop('health_notice')
        return redirect(url_for('fixed.index'), code=303)

    def probe_fields(prefix):
        try:
            return dict(url=request.form[prefix+'url'],
                        expected_status=int(request.form[prefix+'expected_status']),
                        timeout_ms=int(request.form[prefix+'timeout_ms']))
        except (ValueError, KeyError, TypeError):
            raise ProxyHealthError('settings') from None

    @views.route('/proxy-health/defaults', methods=['POST'])
    @login_required
    def proxy_defaults():
        key = request.form.get('subscription_id','')
        if not store.get(key):
            abort(404)
        try:
            if proxy_health is None:
                raise ProxyHealthError('compatible')
            proxy_health.set_global(probe_fields('global_'))
            session['proxy_notice'] = 'Proxy probe defaults saved.'
        except ProxyHealthError as error:
            session['proxy_notice'] = str(error)
        return redirect(url_for('fixed.edit', key=key), code=303)

    @views.route('/<key>/proxy-health/<operation>', methods=['POST'])
    @login_required
    def proxy_action(key, operation):
        if operation not in ('settings','check'):
            abort(404)
        try:
            if proxy_health is None:
                raise ProxyHealthError('compatible')
            if operation == 'settings':
                scope = request.form.get('scope')
                if scope not in ('global','custom'):
                    raise ProxyHealthError('settings')
                try:
                    seconds = health_interval()
                except ValueError:
                    raise ProxyHealthError('settings') from None
                proxy_health.settings(key, request.form.get('mode'), scope == 'global',
                                      probe_fields('custom_') if scope == 'custom' else None,seconds)
                session['proxy_notice'] = 'Full proxy validation settings saved.'
            else:
                proxy_health.check(key)
                session['proxy_notice'] = 'Full proxy validation completed.'
        except KeyError:
            abort(404)
        except ProxyHealthError as error:
            session['proxy_notice'] = str(error)
        if store.get(key):
            return redirect(url_for('fixed.edit', key=key), code=303)
        if session.get('proxy_notice'):
            session['fixed_error'] = session.pop('proxy_notice')
        return redirect(url_for('fixed.index'), code=303)

    @views.route('/<key>/sources/refresh-all', methods=['POST'])
    @views.route('/<key>/sources/<identifier>/<operation>', methods=['POST'])
    @login_required
    def source_action(key, identifier=None, operation='refresh-all'):
        if operation not in ('refresh-all', 'refresh', 'enable', 'disable', 'delete'):
            abort(404)
        try:
            store.source_action(key, operation, default_yaml, identifier)
        except KeyError:
            abort(404)
        except (SourceError, GenerationError) as error:
            # Only allowlisted source codes may be surfaced; never arbitrary exceptions.
            session['fixed_error'] = ('Unable to update. ' + message(error.code)
                if isinstance(error, SourceError) else 'Unable to generate. The previous subscription is unchanged.')
        else:
            session['fixed_notice'] = 'Sources updated. Cached sources use their last successful data.'
        return redirect(url_for('fixed.edit', key=key) if store.get(key) else url_for('fixed.index'), code=303)

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
