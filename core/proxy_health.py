"""Auxiliary full-proxy observations; never changes a Fixed revision."""
import copy
import ipaddress
import json
import logging
import math
from pathlib import Path
import socket
import time
from urllib.parse import urlsplit

from core import health_schedule, mihomo_probe, node_health, source_fetch
from core.mihomo_manager import ManagedMihomo
from core.refresh_schedule import timestamp
from core.source_errors import SourceError
from core.state import LockBusyError, StateError, atomic_write, file_lock, read_private_bytes, write_json

LOGGER = logging.getLogger(__name__)
DEFAULT_PROBE = dict(url='https://www.gstatic.com/generate_204',expected_status=204,timeout_ms=8000)
ERRORS = ('timeout','proxy_connect_failed','probe_status_mismatch','proxy_failed','unsupported_config')
MESSAGES = {
    'unavailable':'Proxy health state unavailable.',
    'save':'Proxy health results could not be saved.',
    'mode':'Enable Manual or Automatic full proxy validation before checking.',
    'not_due':'Automatic proxy check is not due or the subscription is paused.',
    'settings':'Select valid proxy probe settings.',
    'target':'Probe target must be a public HTTPS URL without credentials, query or fragment.',
    'limit':'Full proxy validation supports up to 256 nodes per run.',
    'busy':'A proxy validation is already running. Please try again later.',
    'engine':'Proxy probe engine could not complete this check.',
    'compatible':'A compatible managed Mihomo v1.19.31 is required.',
    'conflict':'Subscription changed while checking. Please retry.',
    'health_conflict':'Proxy health settings or results changed while checking. Please retry.',
}


class ProxyHealthError(RuntimeError):
    def __init__(self, code):
        self.code = code if code in MESSAGES else 'unavailable'
        super().__init__(MESSAGES[self.code])


class UnavailableEngine:
    def __init__(self, root):
        self.binary = Path(root) / 'bin/mihomo'

    def status(self):
        return dict(status='BROKEN',required='v1.19.31',installed=None,architecture='unknown')


def parse_target(url):
    try:
        if not isinstance(url, str) or not url or len(url) > 2048 or any(ord(c) <= 32 or ord(c) == 127 for c in url):
            raise ValueError
        parts = urlsplit(url)
        if (parts.scheme != 'https' or not parts.hostname or parts.username is not None
                or parts.password is not None or '?' in url or '#' in url or '\\' in url
                or '%' in parts.netloc):
            raise ValueError
        host = parts.hostname.encode('idna').decode('ascii')
        if len(host) > 253 or host == 'localhost' or host.endswith('.localhost'):
            raise ValueError
        port = parts.port if parts.port is not None else 443
        if not 1 <= port <= 65535:
            raise ValueError
        if parts.path and not parts.path.startswith('/') or any(ord(c) > 127 for c in parts.path):
            raise ValueError
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            if any(c in host for c in '/:@[]'):
                raise ValueError
        else:
            source_fetch._public(str(ip))
        return host, port
    except (ValueError, UnicodeError, SourceError):
        raise ProxyHealthError('target') from None


def valid_settings(settings):
    if not isinstance(settings, dict) or set(settings) != {'url','expected_status','timeout_ms'}:
        return False
    if (type(settings['expected_status']) is not int or not 100 <= settings['expected_status'] <= 599
            or type(settings['timeout_ms']) is not int or not 3000 <= settings['timeout_ms'] <= 15000):
        return False
    try:
        parse_target(settings['url'])
        return True
    except ProxyHealthError:
        return False


def validate_target(settings, resolver=None):
    if not valid_settings(settings):
        raise ProxyHealthError('target')
    host, port = parse_target(settings['url'])
    try:
        addresses = (resolver or source_fetch._resolve)(host, port, time.monotonic() + 3)
        if not addresses:
            raise ValueError
        for family, _, address in addresses:
            if family not in (socket.AF_INET, socket.AF_INET6) or address[1] != port:
                raise ValueError
            source_fetch._public(address[0])
    except (SourceError, OSError, ValueError):
        raise ProxyHealthError('target') from None
    return settings


def unknown():
    return dict(status='unknown',consecutive_failures=0,latency_ms=None,
                last_checked_at=None,last_success_at=None,error=None)


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
        return count == 0 and success == checked and type(latency) in (int,float) and math.isfinite(latency) and latency >= 0 and error is None
    if status == 'unsupported':
        return latency is None and error == 'unsupported_config'
    return (status == ('suspect' if count in (1,2) else 'unhealthy') and count > 0
            and latency is None and error in ERRORS and error != 'unsupported_config')


def empty_entry():
    return dict(mode='off',use_global=True,override=None,last_check_at=None,nodes={},**health_schedule.defaults())


def valid_state(data):
    try:
        if (not isinstance(data, dict) or set(data) != {'version','global','subscriptions'}
                or type(data['version']) is not int or data['version'] not in (1,2) or not valid_settings(data['global'])
                or not isinstance(data['subscriptions'], dict)):
            return False
        for key, entry in data['subscriptions'].items():
            fields = set(empty_entry()) if data['version'] == 2 else {'mode','use_global','override','last_check_at','nodes'}
            if not isinstance(key,str) or not node_health.ID.fullmatch(key) or not isinstance(entry,dict) or set(entry) != fields:
                return False
            if (type(entry['use_global']) is not bool
                    or data['version'] == 1 and entry['mode'] not in ('off','manual')
                    or data['version'] == 2 and not health_schedule.valid(entry)):
                return False
            if entry['use_global'] and entry['override'] is not None or not entry['use_global'] and not valid_settings(entry['override']):
                return False
            if entry['last_check_at'] is not None and not timestamp(entry['last_check_at']):
                return False
            if not isinstance(entry['nodes'],dict) or len(entry['nodes']) > 256:
                return False
            if any(not isinstance(fp,str) or not node_health.FINGERPRINT.fullmatch(fp) or not valid_record(record)
                   for fp,record in entry['nodes'].items()):
                return False
        return True
    except (TypeError, ValueError, KeyError):
        return False


class ProxyHealth(health_schedule.ScheduledHealth):
    def __init__(self, fixed, *, engine=None, runner=None, clock=None, resolver=None):
        self.fixed = fixed
        self.state = Path(fixed.state)
        self.path = self.state / 'proxy_health.json'
        self.lock = self.state / 'proxy_health.lock'
        self.job_lock = self.state / 'proxy_probe.lock'
        if engine is not None:
            self.engine = engine
        else:
            try:
                self.engine = ManagedMihomo(root=self.state.parent)
            except (OSError, ValueError, TypeError, RuntimeError):
                self.engine = UnavailableEngine(self.state.parent)
        self.runner = runner or (lambda *args: mihomo_probe.run(*args))
        self.clock = clock or time.time
        self.resolver = resolver

    def _locked(self, path, blocking=True):
        if self.state.is_symlink() or not self.state.is_dir() or self.state.stat().st_mode & 0o077:
            raise ProxyHealthError('unavailable')
        return file_lock(path, blocking=blocking, strict=True)

    def _read(self):
        try:
            raw = read_private_bytes(self.path, 128 * 1024 * 1024) if self.path.exists() or self.path.is_symlink() else None
            def unique(pairs):
                result = {}
                for key,value in pairs:
                    if key in result: raise ValueError
                    result[key] = value
                return result
            def reject_constant(_):
                raise ValueError
            data = (json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)
                    if raw is not None else {'version':2,'global':copy.deepcopy(DEFAULT_PROBE),'subscriptions':{}})
            if not valid_state(data):
                raise ValueError
            return health_schedule.migrate(data), raw
        except (OSError, StateError, ValueError, TypeError):
            raise ProxyHealthError('unavailable') from None

    def _commit(self, data, previous):
        if not valid_state(data):
            raise ProxyHealthError('unavailable')
        try:
            write_json(self.path, data)
        except (OSError, StateError):
            try:
                if previous is not None:
                    atomic_write(self.path, previous)
                elif self.path.exists() and not self.path.is_symlink():
                    self.path.unlink()
            except (OSError, StateError):
                pass
            raise ProxyHealthError('save') from None

    def _schedule_locked(self):
        return self._locked(self.lock)

    @staticmethod
    def _prune(data, ids):
        stale = set(data['subscriptions']) - ids
        for key in stale:
            del data['subscriptions'][key]
        return bool(stale)

    def describe(self, key):
        snapshot, payload = self.fixed.snapshot(key)
        nodes = node_health.extract(payload)
        try:
            with self.fixed.revision_guard(key, snapshot['revision']) as ids:
                with self._locked(self.lock):
                    data, previous = self._read()
                    if self._prune(data, ids): self._commit(data, previous)
                    entry = copy.deepcopy(data['subscriptions'].get(key, empty_entry()))
                    global_settings = copy.deepcopy(data['global'])
        except (OSError, StateError):
            raise ProxyHealthError('unavailable') from None
        except SourceError:
            raise ProxyHealthError('conflict') from None
        counts = dict(healthy=0,suspect=0,unhealthy=0,unknown=0,unsupported=0)
        rows = []
        for index,node in enumerate(nodes):
            record = entry['nodes'].get(node['fingerprint'], unknown())
            counts[record['status']] += 1
            name = 'Node ' + str(index+1) if snapshot['token'] in node['name'] else node['name']
            rows.append(dict(name=name,protocol=node['protocol'],fingerprint=node['fingerprint'],**record))
        return dict(mode=entry['mode'],use_global=entry['use_global'],override=entry['override'],
                    global_settings=global_settings,effective=global_settings if entry['use_global'] else entry['override'],
                    last_check_at=entry['last_check_at'],total=len(nodes),rows=rows,counts=counts,
                    revision=snapshot['revision'],**health_schedule.details(entry))

    def set_global(self, settings):
        validated = validate_target(settings, self.resolver)
        try:
            with self._locked(self.lock):
                data, previous = self._read()
                if data['global'] != validated:
                    for entry in data['subscriptions'].values():
                        if entry['use_global']:
                            entry['nodes'] = {}
                            entry['last_check_at'] = None
                            health_schedule.configure(entry,entry['mode'],entry['interval_seconds'],self.clock(),reset=True)
                data['global'] = copy.deepcopy(validated)
                self._commit(data, previous)
        except (OSError, StateError):
            raise ProxyHealthError('unavailable') from None

    def settings(self, key, mode, use_global, override=None, interval_seconds=None):
        try:
            health_schedule.configure(empty_entry(),mode,interval_seconds,self.clock())
        except ValueError:
            raise ProxyHealthError('settings') from None
        if type(use_global) is not bool:
            raise ProxyHealthError('settings')
        if use_global:
            override = None
        else:
            override = validate_target(override, self.resolver)
        snapshot, _ = self.fixed.snapshot(key)
        try:
            with self.fixed.revision_guard(key, snapshot['revision']) as ids:
                with self._locked(self.lock):
                    data, previous = self._read()
                    self._prune(data, ids)
                    entry = data['subscriptions'].setdefault(key, empty_entry())
                    previous_probe = data['global'] if entry['use_global'] else entry['override']
                    current_probe = data['global'] if use_global else override
                    if previous_probe != current_probe:
                        entry['nodes'] = {}
                        entry['last_check_at'] = None
                    health_schedule.configure(entry,mode,interval_seconds,self.clock(),reset=previous_probe != current_probe)
                    entry.update(use_global=use_global,override=copy.deepcopy(override))
                    self._commit(data, previous)
        except (OSError, StateError):
            raise ProxyHealthError('unavailable') from None
        except SourceError:
            raise ProxyHealthError('conflict') from None

    def check(self, key, trigger='manual'):
        expected_entry, expected_global, started = None, None, False
        try:
            if trigger != 'auto':
                snapshot, payload = self.fixed.snapshot(key)
            with self._locked(self.lock):
                data, _ = self._read()
                expected_entry = copy.deepcopy(data['subscriptions'].get(key,empty_entry()))
                expected_global = copy.deepcopy(data['global'])
            if not health_schedule.allowed(expected_entry,trigger,self.clock()):
                raise ProxyHealthError('not_due' if trigger == 'auto' else 'mode')
            if trigger == 'auto':
                started = True
                snapshot, payload = self.fixed.snapshot(key)
                if snapshot['status'] != 'active':
                    raise ProxyHealthError('not_due')
            started = True
            try:
                return self._check(key,snapshot,payload,expected_entry,expected_global,trigger)
            except KeyError:
                raise ProxyHealthError('engine') from None
        except LockBusyError:
            failure = ProxyHealthError('busy')
        except (OSError, StateError):
            failure = ProxyHealthError('unavailable')
        except SourceError as error:
            failure = ProxyHealthError('conflict' if error.code == 'conflict' else 'unavailable')
        except KeyError:
            raise
        except ProxyHealthError as error:
            failure = error
        except Exception:
            failure = ProxyHealthError('engine')
        if trigger == 'auto' and started:
            self._record_failed_job(key,expected_entry,health_schedule.failure_result(failure.code),expected_global)
        raise failure from None

    def _check(self, key, snapshot, payload, expected_entry, expected_global, trigger):
        nodes = node_health.extract(payload, include_config=True)
        if len(nodes) > 256:
            raise ProxyHealthError('limit')
        targets = list({node['fingerprint']:node for node in nodes}.values())
        effective = expected_global if expected_entry['use_global'] else expected_entry['override']
        with self._locked(self.job_lock, blocking=False):
            if self.engine.status()['status'] != 'COMPATIBLE':
                raise ProxyHealthError('compatible')
            validate_target(effective, self.resolver)
            LOGGER.info('Proxy probe started subscription=%s nodes=%d', key, len(targets))
            results = self.runner(self.engine.binary, targets, effective, self.state)
            if set(results) != {node['fingerprint'] for node in targets}:
                raise ProxyHealthError('engine')
            at = self.clock()
            records = {}
            for node in targets:
                fp = node['fingerprint']
                result = results[fp]
                if not isinstance(result, dict) or result.get('kind') not in ('success','failure','unsupported'):
                    raise ProxyHealthError('engine')
                record = copy.deepcopy(expected_entry['nodes'].get(fp, unknown()))
                record['last_checked_at'] = at
                if result['kind'] == 'success':
                    record.update(status='healthy',consecutive_failures=0,latency_ms=result.get('latency_ms'),
                                  last_success_at=at,error=None)
                elif result['kind'] == 'unsupported':
                    record.update(status='unsupported',latency_ms=None,error='unsupported_config')
                else:
                    code = result.get('error')
                    if code not in ERRORS or code == 'unsupported_config':
                        raise ProxyHealthError('engine')
                    count = min(record['consecutive_failures']+1, 1_000_000_000)
                    record.update(status='suspect' if count < 3 else 'unhealthy',consecutive_failures=count,
                                  latency_ms=None,error=code)
                if not valid_record(record):
                    raise ProxyHealthError('engine')
                records[fp] = record
            with self.fixed.revision_guard(key, snapshot['revision']) as ids:
                if trigger == 'auto' and self.fixed._read()['subscriptions'][key]['status'] != 'active':
                    raise ProxyHealthError('conflict')
                with self._locked(self.lock):
                    data, previous = self._read()
                    if (not health_schedule.same_check_state(data['subscriptions'].get(key,empty_entry()),expected_entry)
                            or data['global'] != expected_global):
                        raise ProxyHealthError('health_conflict')
                    self._prune(data, ids)
                    completed = copy.deepcopy(expected_entry)
                    completed.update(last_check_at=at,nodes=records)
                    health_schedule.record(completed,trigger,'success',at)
                    data['subscriptions'][key] = completed
                    self._commit(data, previous)
            counts = {status:sum(record['status']==status for record in records.values())
                      for status in ('healthy','suspect','unhealthy','unsupported')}
            LOGGER.info('Proxy probe completed subscription=%s nodes=%d healthy=%d suspect=%d unhealthy=%d unsupported=%d',
                        key,len(targets),counts['healthy'],counts['suspect'],counts['unhealthy'],counts['unsupported'])
            return counts

    def remove(self, key):
        try:
            with self.fixed._locked():
                if key in self.fixed._read()['subscriptions']:
                    return
                with self._locked(self.lock, blocking=False):
                    data, previous = self._read()
                    if key in data['subscriptions']:
                        del data['subscriptions'][key]
                        self._commit(data, previous)
        except Exception:
            pass
