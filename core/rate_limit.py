"""Bounded, flock-protected login attempts shared by Gunicorn workers."""
import ipaddress
import math
import time

from core.state import StateError, file_lock, private_directory, read_json, write_json


class LoginLimiter:
    def __init__(self, directory, max_failures=5, window=600, lockout=900,
                 max_entries=4096, clock=time.time):
        if any(type(value) is not int or value <= 0 for value in (max_failures, window, lockout, max_entries)):
            raise ValueError('登录限速配置必须是正整数。')
        directory = private_directory(directory)
        self.path, self.lock_path = directory / 'login_attempts.json', directory / 'login_attempts.lock'
        self.max_failures, self.window, self.lockout = max_failures, window, lockout
        self.max_entries, self.clock = max_entries, clock

    @staticmethod
    def _ip(ip):
        try:
            address = ipaddress.ip_address(ip)
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
            return str(address)
        except ValueError:
            # Do not let malformed proxy input create unlimited arbitrary keys.
            return 'unknown'

    def _load(self, now):
        if not self.path.exists():
            return {}
        state = read_json(self.path)
        if not isinstance(state, dict) or state.get('version') != 1 or not isinstance(state.get('ips'), dict):
            raise StateError('登录限速状态无效。')
        result = {}
        for ip, record in state['ips'].items():
            if (not isinstance(record, dict) or not isinstance(record.get('failures'), list) or
                    not isinstance(record.get('blocked_until'), (int, float)) or
                    any(not isinstance(t, (int, float)) or not math.isfinite(t) for t in record['failures']) or
                    not math.isfinite(record['blocked_until'])):
                raise StateError('登录限速状态无效。')
            blocked = record['blocked_until']
            if blocked and blocked <= now:
                continue  # Fixed lockout: blocked requests never extend it.
            failures = [t for t in record['failures'] if t > now - self.window]
            if blocked > now or failures:
                result[ip] = dict(failures=failures, blocked_until=blocked)
        return result

    def _save(self, ips):
        write_json(self.path, {'version': 1, 'ips': ips})

    def _retry(self, ips, ip, now):
        record = ips.get(ip)
        if record and record['blocked_until'] > now:
            return max(1, math.ceil(record['blocked_until'] - now))
        if not record and len(ips) >= self.max_entries:
            # Never evict active locks to make room: fail closed for new IPs.
            expiry = min(r['blocked_until'] or r['failures'][-1] + self.window for r in ips.values())
            return max(1, math.ceil(expiry - now))
        return 0

    def retry_after(self, ip):
        with file_lock(self.lock_path):
            now = self.clock()
            ips = self._load(now)
            self._save(ips)  # prune expired entries, including on blocked requests
            return self._retry(ips, self._ip(ip), now)

    def attempt(self, ip, authenticate):
        """Check + authenticate + record under one lock; no cross-worker race.

        The callback must return a truthy auth snapshot on success or None on
        failure. Passwords/hashes never enter the limiter's state or diagnostics.
        """
        with file_lock(self.lock_path):
            now, ip = self.clock(), self._ip(ip)
            ips = self._load(now)
            retry = self._retry(ips, ip, now)
            if retry:
                self._save(ips)
                return None, retry
            authenticated = authenticate()
            if authenticated:
                ips.pop(ip, None)
            else:
                record = ips.setdefault(ip, dict(failures=[], blocked_until=0))
                record['failures'].append(now)
                if len(record['failures']) >= self.max_failures:
                    record['blocked_until'] = now + self.lockout
                    retry = self.lockout
            self._save(ips)
            return authenticated, retry
