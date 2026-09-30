"""Shared opt-in scheduling rules for independent Endpoint and Proxy observations."""
import copy

from core import notification_events

from core.refresh_schedule import BACKOFF, INTERVALS, MAX_EPOCH, OPTIONS as REFRESH_OPTIONS, timestamp

OPTIONS = REFRESH_OPTIONS[1:]
FIELDS = ('interval_seconds','next_check_at','scheduler_failures','last_trigger','last_job_result','check_revision')
RESULTS = ('success','error','engine_unavailable','limit','busy','conflict')


def defaults():
    return dict(interval_seconds=None,next_check_at=None,scheduler_failures=0,
                last_trigger=None,last_job_result=None,check_revision=0)


def details(entry):
    return {field:entry[field] for field in FIELDS}


def valid(entry):
    try:
        if entry['mode'] not in ('off','manual','automatic'):
            return False
        seconds, next_at = entry['interval_seconds'], entry['next_check_at']
        if entry['mode'] == 'automatic':
            if type(seconds) is not int or seconds not in INTERVALS or not timestamp(next_at):
                return False
        elif seconds is not None or next_at is not None:
            return False
        if type(entry['check_revision']) is not int or not 0 <= entry['check_revision'] < 2**63:
            return False
        failures = entry['scheduler_failures']
        if type(failures) is not int or not 0 <= failures <= 1_000_000_000:
            return False
        if entry['mode'] != 'automatic' and failures != 0:
            return False
        trigger, result = entry['last_trigger'], entry['last_job_result']
        return ((trigger is None and result is None)
                or trigger in ('manual','auto') and result in RESULTS)
    except (KeyError, TypeError):
        return False


def migrate(data):
    """Validated v1 state becomes v2 in memory; callers retain original raw bytes."""
    if data['version'] == 1:
        for entry in data['subscriptions'].values():
            entry.update(defaults())
        data['version'] = 2
    return data


def later(at, seconds):
    if not timestamp(at):
        raise ValueError('Invalid health schedule time.')
    return min(at + seconds, MAX_EPOCH)


def configure(entry, mode, seconds, now, reset=False):
    if mode not in ('off','manual','automatic'):
        raise ValueError('Invalid health mode.')
    changed = reset or entry['mode'] != mode or entry['interval_seconds'] != seconds
    if mode == 'automatic':
        if type(seconds) is not int or seconds not in INTERVALS:
            raise ValueError('Invalid health interval.')
        if reset or entry['mode'] != mode or entry['interval_seconds'] != seconds:
            entry.update(next_check_at=later(now,seconds),scheduler_failures=0)
    else:
        if seconds is not None:
            raise ValueError('Health interval requires Automatic mode.')
        entry.update(next_check_at=None,scheduler_failures=0)
    if changed:
        advance(entry)
    entry.update(mode=mode,interval_seconds=seconds)


def due(entry, now):
    return entry['mode'] == 'automatic' and timestamp(now) and entry['next_check_at'] <= now


def allowed(entry, trigger, now):
    return (trigger == 'manual' and entry['mode'] in ('manual','automatic')
            or trigger == 'auto' and due(entry,now))


def record(entry, trigger, result, at):
    if trigger not in ('manual','auto') or result not in RESULTS:
        raise ValueError('Invalid health scheduler result.')
    entry.update(last_trigger=trigger,last_job_result=result)
    if result == 'success':
        advance(entry)
        entry['scheduler_failures'] = 0
        if entry['mode'] == 'automatic':
            entry['next_check_at'] = later(at,entry['interval_seconds'])
    elif trigger == 'auto':
        if result in ('busy','conflict'):
            seconds = 300
        else:
            count = min(entry['scheduler_failures'] + 1, 1_000_000_000)
            entry['scheduler_failures'] = count
            seconds = BACKOFF[min(count - 1,len(BACKOFF) - 1)]
        entry['next_check_at'] = later(at,seconds)


def advance(entry):
    if entry['check_revision'] >= 2**63 - 1:
        raise ValueError('Health check revision exhausted.')
    entry['check_revision'] += 1


def same_check_state(current, expected):
    # A busy/retry bookkeeping update must not invalidate the manual job holding
    # proxy_probe.lock. Settings and successful checks increment check_revision.
    bookkeeping = {'next_check_at','scheduler_failures','last_trigger','last_job_result'}
    return ({k:v for k,v in current.items() if k not in bookkeeping}
            == {k:v for k,v in expected.items() if k not in bookkeeping})


def failure_result(code):
    if code in ('conflict','health_conflict'):
        return 'conflict'
    return {'compatible':'engine_unavailable','busy':'busy','limit':'limit'}.get(code,'error')


class ScheduledHealth:
    """Short state-only scheduler operations; probe paths remain in their owners."""
    def scheduled_entries(self):
        with self._schedule_locked():
            return copy.deepcopy(self._read()[0]['subscriptions'])

    def _record_failed_job(self, key, expected, result, expected_global=None):
        try:
            # Same Fixed -> auxiliary lock order as successful commits. A changed
            # revision may receive a retry, but newer settings/results always win.
            with self.fixed._locked():
                entries = self.fixed._read()['subscriptions']
                if key not in entries or entries[key]['status'] != 'active':
                    return False
                with self._schedule_locked():
                    data, previous = self._read()
                    current = data['subscriptions'].get(key)
                    if (current != expected or current['mode'] != 'automatic'
                            or expected_global is not None and data['global'] != expected_global):
                        return False
                    before, at = current['scheduler_failures'], self.clock()
                    record(current,'auto',result,at)
                    self._commit(data,previous)
                    notification_events.scheduler(before, current['scheduler_failures'],
                        entries[key]['name'], at, result, self.notification_kind)
                    return True
        except Exception:
            # No exception text, traceback or sensitive state may reach the journal.
            return False
