"""Conservative eligibility and brief auxiliary snapshots. Never fetch or probe."""
import copy
from contextlib import contextmanager, ExitStack

from core import policy_engine
from core.node_identity import fingerprint
from core.refresh_schedule import timestamp

AGES = (3600, 21600, 86400, 172800, 604800)
AGE_LABELS = ('1 hour', '6 hours', '24 hours', '48 hours', '7 days')
MESSAGE = 'Health-aware Policy settings are invalid.'
RESULTS = ('off', 'unchanged', 'updated', 'fail-open', 'unavailable', 'error')
COUNTS = ('groups_filtered', 'candidates_excluded', 'groups_fail_open')


def defaults():
    return dict(mode='off', max_age_seconds=172800, min_candidates=2)


def normalize(value):
    if (not isinstance(value, dict) or set(value) != set(defaults())
            or value['mode'] not in ('off', 'exclude-unhealthy')
            or type(value['max_age_seconds']) is not int or value['max_age_seconds'] not in AGES
            or type(value['min_candidates']) is not int or not 1 <= value['min_candidates'] <= 16):
        raise ValueError(MESSAGE)
    return {field:value[field] for field in defaults()}


def parse_form(form):
    fields = {'health_policy_mode', 'health_policy_max_age_seconds', 'health_policy_min_candidates'}
    if any(key.startswith('health_policy_') and key not in fields for key in form):
        raise ValueError(MESSAGE)
    if hasattr(form, 'getlist') and any(len(form.getlist(k)) != 1 for k in fields if k in form):
        raise ValueError(MESSAGE)
    value = defaults()
    for field in value:
        key = 'health_policy_' + field
        if key in form:
            raw = form.get(key)
            if field != 'mode':
                if not isinstance(raw,str) or not raw.isascii() or not raw.isdecimal() or len(raw) > 6:
                    raise ValueError(MESSAGE)
                raw = int(raw)
            value[field] = raw
    return normalize(value)


def form_values(config=None, form=None):
    result = {'health_policy_' + k:str(v) for k,v in normalize(config or defaults()).items()}
    if form is not None:
        for key in result:
            if key in form: result[key] = form.get(key)[:64]
    return result


def audit_defaults():
    return dict(last_reconciled_at=None, result='off', output_changed=False,
                groups_filtered=0, candidates_excluded=0, groups_fail_open=0)


def valid_audit(value):
    return (isinstance(value,dict) and set(value)==set(audit_defaults())
            and (value['last_reconciled_at'] is None or timestamp(value['last_reconciled_at']))
            and value['result'] in RESULTS and type(value['output_changed']) is bool
            and all(type(value[k]) is int and 0 <= value[k] <= 1_000_000_000 for k in COUNTS))


def applicable(entry):
    return (entry['health_policy']['mode']=='exclude-unhealthy'
            and any(scope['type'] in policy_engine.AUTOMATIC for scope in entry['policy_config'].values()))


@contextmanager
def locked_snapshot(fixed, key):
    """Only Proxy lock, nonblocking. Caller may hold Fixed for commit validation.

    No Fixed method is called here. This preserves Fixed → Proxy ordering; the
    generation-time caller releases Proxy before ever reacquiring Fixed.
    """
    from core.proxy_health import ProxyHealth
    observer = ProxyHealth(fixed, engine=object())  # No engine discovery/execution.
    with observer._locked(observer.lock, blocking=False):
        data, raw = observer._read()  # Existing strict private schema reader; no writes/pruning.
        entry = data['subscriptions'].get(key)
        available = raw is not None and entry is not None
        yield dict(available=available, records=copy.deepcopy(entry['nodes']) if entry else {},
                   identity=copy.deepcopy((entry, data['global'])))


def snapshot(fixed, key):
    try:
        with locked_snapshot(fixed,key) as value:
            return value
    except Exception:
        return dict(available=False, records={}, identity=None)


@contextmanager
def guard(fixed, key, expected):
    """Prevent a candidate based on superseded available observations committing."""
    if not expected['available']:
        # No exclusions were made. Corrupt/locked/missing auxiliary data fails open.
        yield
        return
    from core.source_errors import SourceError
    with ExitStack() as stack:
        try:
            current = stack.enter_context(locked_snapshot(fixed,key))
        except Exception:
            raise SourceError('conflict') from None
        if current['identity'] != expected['identity']:
            raise SourceError('conflict')
        yield


def fresh_unhealthy(record, now, age):
    if not isinstance(record,dict) or record.get('status')!='unhealthy':
        return False
    count, checked = record.get('consecutive_failures'), record.get('last_checked_at')
    return (type(count) is int and count>=3 and timestamp(checked) and timestamp(now)
            and 0 <= now-checked <= age)


def apply(data, nodes, countries, special_groups, policy, config, health, now):
    """Filter only managed automatic candidates, in their existing order."""
    config = normalize(config)
    summary = audit_defaults()
    if config['mode']=='off': return summary
    summary.update(last_reconciled_at=now, result='unchanged')
    if not health['available']:
        summary['result']='unavailable'
        return summary
    identities = {node['name']:fingerprint(node) for node in nodes}
    country, special = policy_engine.memberships(nodes,countries,special_groups)
    targets = {}
    for scope,members in (('country_groups',country),('special_groups',special)):
        if policy[scope]['type'] not in policy_engine.AUTOMATIC: continue
        for name in members:
            if scope=='country_groups' and name in special: continue
            targets[name] = True
    for group in data['proxy-groups']:
        if group['name'] not in targets: continue
        original = list(group['proxies'])
        if not original: continue  # Policy Engine itself already rejects explicit zero candidates.
        retained = [name for name in original if not fresh_unhealthy(
            health['records'].get(identities[name]), now, config['max_age_seconds'])]
        if len(retained)==len(original): continue
        required = min(config['min_candidates'],len(original))
        if len(retained)<required:
            summary['groups_fail_open']+=1
        else:
            group['proxies']=retained
            summary['groups_filtered']+=1
            summary['candidates_excluded']+=len(original)-len(retained)
    if summary['groups_fail_open']: summary['result']='fail-open'
    return summary


def finish(summary, changed):
    summary = copy.deepcopy(summary)
    summary['output_changed']=changed if summary['result']!='off' else False
    if summary['result']=='unchanged' and changed: summary['result']='updated'
    return summary
