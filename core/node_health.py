"""Private auxiliary reachability observations; Fixed output remains authoritative."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import math
from pathlib import Path
import re
import time

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from core import notification_events, health_schedule, node_probe, source_parser
from core.node_identity import fingerprint
from core.refresh_schedule import timestamp
from core.source_errors import SourceError
from core.state import StateError, atomic_write, file_lock, read_private_bytes, write_json

MAX_NODES = 256
MAX_WORKERS = 16
MAX_YAML_BYTES = 50 * 1024 * 1024
MAX_STATE_BYTES = 128 * 1024 * 1024
ID = re.compile(r'[0-9a-f]{32}\Z')
FINGERPRINT = re.compile(r'[0-9a-f]{64}\Z')
LOGGER = logging.getLogger(__name__)
MESSAGES = {
    'unavailable':'Health state unavailable.',
    'save':'Health results could not be saved.',
    'mode':'Enable Manual or Automatic health checks before checking.',
    'not_due':'Automatic endpoint check is not due or the subscription is paused.',
    'config':'Select Off, Manual or Automatic with a valid health interval.',
    'limit':'Health check currently supports up to 256 nodes per run.',
    'conflict':'Subscription changed while checking. Please retry.',
    'health_conflict':'Health settings or results changed while checking. Please retry.',
    'check':'Health check could not be completed.',
}
PROBE_MESSAGES = dict(dns_failed='DNS resolution failed',blocked_address='Address blocked',
    timeout='Connection timed out',connection_refused='Connection refused',
    network_unreachable='Network unreachable',connect_failed='Connection failed')


class HealthError(RuntimeError):
    def __init__(self, code):
        self.code = code if code in MESSAGES else 'unavailable'
        super().__init__(MESSAGES[self.code])


def extract(payload, include_config=False):
    """Read current proxies without fetching, aggregating, renaming or generating."""
    try:
        if not isinstance(payload, bytes) or len(payload) > MAX_YAML_BYTES:
            raise ValueError
        data = YAML(typ='safe').load(payload.decode('utf-8-sig'))
        if not isinstance(data, dict) or not isinstance(data.get('proxies'), list):
            raise ValueError
        proxies = source_parser._plain(data['proxies'])
        nodes = []
        for index, config in enumerate(proxies):
            if not isinstance(config, dict) or config.get('type') not in ('vmess', 'vless', 'trojan', 'ss'):
                continue
            server, port = config.get('server'), config.get('port')
            if not isinstance(server, str) or not server.strip() or type(port) is not int or not 1 <= port <= 65535:
                raise ValueError
            name = config.get('name', '')
            if not isinstance(name, str) or not name:
                name = 'Node ' + str(index + 1)
            # Names are display data, but must not smuggle endpoint/credentials
            # into the observational table. The original YAML is never modified.
            credential = config.get('password' if config['type'] in ('trojan', 'ss') else 'uuid')
            if (server in name or name.strip() == str(port)
                    or isinstance(credential, str) and credential and (credential in name or
                        config['type'] in ('trojan', 'ss') and credential.strip() and credential.strip() in name)
                    or re.search(r'(?i)(?:https?://|vmess://|vless://|trojan://|ss://|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})', name)):
                name = 'Node ' + str(index + 1)
            node = dict(fingerprint=fingerprint(config), name=name, protocol=config['type'], server=server, port=port)
            if include_config:
                node['config'] = config  # In-memory only; never persisted or rendered.
            nodes.append(node)
        return nodes
    except (ValueError, TypeError, UnicodeError, RecursionError, SourceError, YAMLError):
        raise HealthError('unavailable') from None


def unknown():
    return dict(status='unknown', consecutive_failures=0, latency_ms=None,
                last_checked_at=None, last_success_at=None, error=None)


def valid_record(record):
    if not isinstance(record, dict) or set(record) != set(unknown()):
        return False
    status, count = record['status'], record['consecutive_failures']
    latency, checked, success, error = (record[k] for k in ('latency_ms','last_checked_at','last_success_at','error'))
    if type(count) is not int or not 0 <= count <= 1_000_000_000:
        return False
    if checked is not None and not timestamp(checked) or success is not None and not timestamp(success):
        return False
    if status == 'unknown':
        return record == unknown()
    if not timestamp(checked):
        return False
    if status == 'healthy':
        return (count == 0 and success == checked and type(latency) in (int,float)
                and math.isfinite(latency) and latency >= 0 and error is None)
    return (status == ('suspect' if count in (1,2) else 'unhealthy') and count > 0
            and latency is None and isinstance(error, str) and error in node_probe.ERRORS)


def valid_state(data):
    try:
        if not isinstance(data, dict) or set(data) != {'version', 'subscriptions'} or type(data['version']) is not int or data['version'] not in (1,2):
            return False
        if not isinstance(data['subscriptions'], dict):
            return False
        for key, entry in data['subscriptions'].items():
            if not isinstance(key, str) or not ID.fullmatch(key) or not isinstance(entry, dict):
                return False
            fields = {'mode','last_check_at','nodes'}
            if data['version'] == 2:
                fields.update(health_schedule.FIELDS)
            if set(entry) != fields:
                return False
            if (data['version'] == 1 and entry['mode'] not in ('off','manual')
                    or data['version'] == 2 and not health_schedule.valid(entry)):
                return False
            if entry['last_check_at'] is not None and not timestamp(entry['last_check_at']):
                return False
            if not isinstance(entry['nodes'], dict) or len(entry['nodes']) > MAX_NODES:
                return False
            if any(not isinstance(fp,str) or not FINGERPRINT.fullmatch(fp) or not valid_record(r) for fp,r in entry['nodes'].items()):
                return False
        return True
    except (TypeError, KeyError, ValueError):
        return False


def empty_entry():
    return dict(mode='off',last_check_at=None,nodes={},**health_schedule.defaults())


class NodeHealth(health_schedule.ScheduledHealth):
    notification_kind = 'endpoint_health'
    def __init__(self, fixed, clock=None, probe=None):
        self.fixed = fixed
        self.state = Path(fixed.state)
        self.path, self.lock = self.state/'node_health.json', self.state/'node_health.lock'
        self.clock, self.probe = clock or time.time, probe

    def _read(self):
        try:
            raw = read_private_bytes(self.path, MAX_STATE_BYTES) if self.path.exists() or self.path.is_symlink() else None
            def unique(pairs):
                value = {}
                for key, item in pairs:
                    if key in value: raise ValueError
                    value[key] = item
                return value
            data = (json.loads(raw, object_pairs_hook=unique, parse_constant=lambda *_: (_ for _ in ()).throw(ValueError()))
                    if raw is not None else dict(version=2,subscriptions={}))
            if not valid_state(data):
                raise ValueError
            return health_schedule.migrate(data), raw
        except (OSError, StateError, ValueError, TypeError):
            raise HealthError('unavailable') from None

    def _commit(self, data, previous):
        if not valid_state(data):
            raise HealthError('unavailable')
        try:
            write_json(self.path, data)
        except (OSError, StateError):
            try:
                if previous is not None:
                    atomic_write(self.path, previous)
                elif self.path.exists() and not self.path.is_symlink():
                    self.path.unlink()
            except (OSError, StateError):
                pass  # Auxiliary data only; never touch the authoritative registry.
            raise HealthError('save') from None

    def _locked(self, blocking=True):
        if self.state.is_symlink() or not self.state.is_dir() or self.state.stat().st_mode & 0o077:
            raise HealthError('unavailable')
        return file_lock(self.lock, blocking=blocking, strict=True)

    def _schedule_locked(self):
        return self._locked()

    @staticmethod
    def _prune(data, ids):
        stale = set(data['subscriptions']) - ids
        for key in stale: del data['subscriptions'][key]
        return bool(stale)

    def describe(self, key):
        snapshot, payload = self.fixed.snapshot(key)
        nodes = extract(payload)
        try:
            with self.fixed.revision_guard(key, snapshot['revision']) as ids:
                with self._locked():
                    data, previous = self._read()
                    if self._prune(data, ids): self._commit(data, previous)
                    entry = copy.deepcopy(data['subscriptions'].get(key, empty_entry()))
        except (OSError, StateError):
            raise HealthError('unavailable') from None
        except SourceError:
            raise HealthError('conflict') from None
        rows, counts = [], dict(healthy=0,suspect=0,unhealthy=0,unknown=0)
        for index, node in enumerate(nodes):
            record = entry['nodes'].get(node['fingerprint'], unknown())
            counts[record['status']] += 1
            name = node['name']
            if snapshot['token'] in name:
                name = 'Node ' + str(index + 1)
            rows.append(dict(name=name,protocol=node['protocol'],fingerprint=node['fingerprint'],**record))
        return dict(mode=entry['mode'],rows=rows,counts=counts,total=len(nodes),
                    revision=snapshot['revision'],last_check_at=entry['last_check_at'],
                    **health_schedule.details(entry))

    def settings(self, key, mode, interval_seconds=None):
        try:
            health_schedule.configure(empty_entry(),mode,interval_seconds,self.clock())
        except ValueError:
            raise HealthError('config') from None
        snapshot, _ = self.fixed.snapshot(key)
        try:
            with self.fixed.revision_guard(key, snapshot['revision']) as ids:
                with self._locked():
                    data, previous = self._read(); self._prune(data, ids)
                    entry = data['subscriptions'].setdefault(key, empty_entry())
                    health_schedule.configure(entry,mode,interval_seconds,self.clock())
                    self._commit(data, previous)
        except (OSError, StateError):
            raise HealthError('unavailable') from None
        except SourceError:
            raise HealthError('conflict') from None

    def check(self, key, trigger='manual'):
        expected, started = None, False
        try:
            if trigger != 'auto':
                snapshot, payload = self.fixed.snapshot(key)
            with self._locked():
                data, _ = self._read()
                expected = copy.deepcopy(data['subscriptions'].get(key,empty_entry()))
            if not health_schedule.allowed(expected,trigger,self.clock()):
                raise HealthError('not_due' if trigger == 'auto' else 'mode')
            if trigger == 'auto':
                started = True
                snapshot, payload = self.fixed.snapshot(key)
                if snapshot['status'] != 'active':
                    raise HealthError('not_due')
            started = True
            try:
                return self._check(key,snapshot,payload,expected,trigger)
            except KeyError:
                raise HealthError('check') from None
        except (OSError, StateError):
            failure = HealthError('unavailable')
        except SourceError as error:
            failure = HealthError('conflict' if error.code == 'conflict' else 'unavailable')
        except KeyError:
            raise
        except HealthError as error:
            failure = error
        except Exception:
            failure = HealthError('check')
        if trigger == 'auto' and started:
            self._record_failed_job(key,expected,health_schedule.failure_result(failure.code))
        raise failure from None

    def _check(self, key, snapshot, payload, expected, trigger):
        nodes = extract(payload)
        if len(nodes) > MAX_NODES: raise HealthError('limit')
        targets = {n['fingerprint']:n for n in nodes}
        probe = self.probe or node_probe.probe
        def run(node): return probe(node['server'],node['port'])
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            outcomes = list(executor.map(run, targets.values()))
        at = self.clock()
        records = {}
        for fp, outcome in zip(targets, outcomes):
            record = copy.deepcopy(expected['nodes'].get(fp, unknown()))
            record['last_checked_at'] = at
            if outcome['error'] is None:
                record.update(status='healthy',consecutive_failures=0,latency_ms=outcome['latency_ms'],last_success_at=at,error=None)
            else:
                count = min(record['consecutive_failures'] + 1, 1_000_000_000)
                record.update(status='suspect' if count < 3 else 'unhealthy',consecutive_failures=count,
                              latency_ms=None,error=outcome['error'])
            if not valid_record(record): raise HealthError('check')
            records[fp] = record
        with self.fixed.revision_guard(key, snapshot['revision']) as ids:
            if trigger == 'auto' and self.fixed._read()['subscriptions'][key]['status'] != 'active':
                raise HealthError('conflict')
            with self._locked():
                data, previous = self._read()
                if not health_schedule.same_check_state(data['subscriptions'].get(key,empty_entry()),expected):
                    raise HealthError('health_conflict')
                before = data['subscriptions'].get(key,expected)
                self._prune(data, ids)
                completed = copy.deepcopy(expected)
                completed.update(last_check_at=at,nodes=records)
                health_schedule.record(completed,trigger,'success',at)
                data['subscriptions'][key] = completed
                self._commit(data, previous)
                notification_events.health(self.notification_kind, before, completed,
                    snapshot['name'], at, trigger)
        counts = {status:sum(r['status'] == status for r in records.values()) for status in ('healthy','suspect','unhealthy')}
        LOGGER.info('Node health check subscription=%s nodes=%d healthy=%d suspect=%d unhealthy=%d',
                    key,len(targets),counts['healthy'],counts['suspect'],counts['unhealthy'])
        return counts

    def remove(self, key):
        """Best-effort cleanup after deletion; corrupt auxiliary state stays untouched."""
        try:
            with self.fixed._locked():
                if key in self.fixed._read()['subscriptions']: return
                with self._locked(blocking=False):
                    data, previous = self._read()
                    if key in data['subscriptions']:
                        del data['subscriptions'][key]; self._commit(data, previous)
        except Exception:
            pass
