"""Independent evidence providers. Never consume a provider from CLI/env/data.

Local release provenance uses previously accepted, immutable release pins in
trusted tool code, not a digest supplied by the incoming Package. No networking.
Process observations describe THIS interpreter, not the synthetic target.
"""
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import sysconfig

from scripts import recovery_manifest as schema, recovery_io as io

ORIGINS = ('OBSERVED_TRUSTED_HOST_FACT', 'VERIFIED_PACKAGE_FACT',
           'VERIFIED_TRUSTED_RELEASE_FACT', 'STATIC_DERIVED_FACT', 'OPERATOR_DECLARED',
           'SYNTHETIC_DECLARED', 'UNKNOWN', 'UNSUPPORTED')
ROOT = Path(__file__).resolve().parents[1]
BASELINE = '0309006537fde20030777e5603f5e2f3332406a1'
# Accepted stable identities from independently read remote refs. Not incoming data.
RELEASE_PINS = {'v1.8.0': ('7657f2302545e74b1e9c1544e27ead9491e0d2a1',
                         '311f4fb65fd1fef08e39d3794562409fbfddc968'),
                'v1.8.1': ('7c9adfd6304d5a8b5bfaf6e5071c529a6e9c5546',
                         'fb95cd56e9d9e5b32832437eb1e67219c9d17279'),
                'v1.8.2': ('e48d0f9a1eb114693805010735c727ad2793d8c9',
                         '47d24d723b0c326fd05ac5ec77580e3961a89e23')}
MAX_GIT_BYTES = 8 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def digest(value):
    return hashlib.sha256(schema.canonical(value)).hexdigest()


class ProcessHostFactsProvider:
    """Trusted process observation; no target installation or backup execution."""
    def observe(self):
        return dict(origin='OBSERVED_TRUSTED_HOST_FACT', source='TRUSTED_ASSESSMENT_PROCESS',
                    acquired_at=now(), scope='PROCESS_RUNTIME_ONLY_NOT_TARGET_RUNTIME',
                    values=dict(os=platform.system(), architecture=platform.machine(),
                                python_version='.'.join(map(str, sys.version_info[:3])),
                                python_abi=sysconfig.get_config_var('SOABI')))


def git(arguments, maximum=MAX_GIT_BYTES):
    # Trusted system Git, immutable local objects. No hooks, helpers, fetch or shell.
    env = dict(PATH=os.defpath, LC_ALL='C', GIT_CONFIG_NOSYSTEM='1',
               GIT_CONFIG_GLOBAL=os.devnull, GIT_OPTIONAL_LOCKS='0',
               GIT_NO_REPLACE_OBJECTS='1', GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0')
    try:
        result = subprocess.run(['git', '--no-pager', '-c', 'core.fsmonitor=false', *arguments],
                                cwd=ROOT, env=env, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        schema.require(False, 'TRUSTED_RELEASE_SOURCE_UNAVAILABLE')
    schema.require(result.returncode == 0, 'TRUSTED_RELEASE_SOURCE_UNAVAILABLE')
    schema.require(len(result.stdout) <= maximum, 'TRUSTED_RELEASE_BYTE_LIMIT')
    return result.stdout


class PinnedLocalReleaseProvider:
    def observe(self, identity, budget):
        pin = RELEASE_PINS.get(identity['tag']) if identity['channel'] == 'stable' else None
        result = dict(origin='UNKNOWN', source='PINNED_LOCAL_RELEASE_OBJECTS', acquired_at=now(),
                      scope='APPLICATION_CODE_ONLY_NOT_INSTALLED_RUNTIME', identity=identity,
                      application={}, reason='INDEPENDENT_RELEASE_IDENTITY_UNAVAILABLE')
        if pin is None or pin[1] != identity['commit'] or identity['tag'] != 'v' + identity['version']:
            return result
        budget.tick()
        schema.require(git(['cat-file', '-t', pin[0]], 64).strip() == b'tag', 'RELEASE_PIN_MISMATCH')
        schema.require(git(['rev-parse', pin[0] + '^{}'], 64).decode().strip() == pin[1], 'RELEASE_PIN_MISMATCH')
        listing = git(['ls-tree', '-rz', '--full-tree', pin[1]], 512 * 1024)
        hashes = {}
        total = 0
        for item in listing.split(b'\0'):
            budget.tick()
            if not item:
                continue
            header, path_raw = item.split(b'\t', 1)
            path = path_raw.decode('utf-8')
            selected = (path in {'app.py', 'VERSION', 'requirements.txt'} | schema.SCRIPTS
                        or path.startswith(('core/', 'scripts/', 'templates/', 'static/')))
            if not selected:
                continue
            schema.path(path)
            mode, kind, object_id = header.split()
            schema.require(kind == b'blob' and mode in (b'100644', b'100755'), 'UNSUPPORTED_RELEASE_OBJECT')
            size = int(git(['cat-file', '-s', object_id.decode()], 64))
            total += size
            schema.require(size <= MAX_GIT_BYTES and total <= 64 * 1024 * 1024,
                           'TRUSTED_RELEASE_BYTE_LIMIT')
            schema.require(len(hashes) < schema.MAX_ENTRIES, 'TRUSTED_RELEASE_ENTRY_LIMIT')
            content = git(['cat-file', 'blob', object_id.decode()])
            schema.require(len(content) == size, 'TRUSTED_RELEASE_OBJECT_CHANGED')
            hashes['application/' + path] = hashlib.sha256(content).hexdigest()
        schema.require(bool(hashes), 'TRUSTED_RELEASE_SOURCE_UNAVAILABLE')
        result.update(origin='VERIFIED_TRUSTED_RELEASE_FACT', application=hashes, reason=None)
        return result


def tool_binding(budget=None):
    """Baseline plus actual working-source digest: never call an uncommitted SHA a commit."""
    hashes = {}
    budget = budget if budget is not None else io.Budget()
    total = 0
    for path in sorted((ROOT / 'scripts').glob('*.py')):
        budget.tick()
        schema.require(len(hashes) < 512, 'TOOL_ENTRY_LIMIT')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(fd)
            schema.require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                           and not stat.S_IMODE(before.st_mode) & 0o022, 'UNSAFE_TOOL_METADATA')
            total += before.st_size
            schema.require(before.st_size <= MAX_GIT_BYTES and total <= 64 * 1024 * 1024, 'TOOL_BYTE_LIMIT')
            raw = bytearray()
            while True:
                budget.tick()
                chunk = os.read(fd, min(64 * 1024, MAX_GIT_BYTES - len(raw) + 1))
                if not chunk:
                    break
                raw.extend(chunk)
                schema.require(len(raw) <= MAX_GIT_BYTES, 'TOOL_BYTE_LIMIT')
            from scripts.backup_audit import fingerprint
            schema.require(fingerprint(before) == fingerprint(os.fstat(fd))
                           == fingerprint(os.stat(path, follow_symlinks=False)), 'TOOL_CHANGED')
            hashes[path.name] = hashlib.sha256(raw).hexdigest()
        finally:
            os.close(fd)
    return dict(baseline_commit=BASELINE, commit_scope='ACCEPTED_BASELINE_NOT_UNCOMMITTED_CANDIDATE',
                source_sha256=digest(hashes))


def summarize(evidence):
    """Do not echo arbitrary provider values, paths, identifiers or exception text."""
    schema.require(type(evidence) is dict and evidence.get('origin') in ORIGINS, 'INVALID_EVIDENCE')
    schema.require(evidence.get('source') in ('TRUSTED_ASSESSMENT_PROCESS', 'PINNED_LOCAL_RELEASE_OBJECTS',
                                            'IN_PROCESS_SYNTHETIC_FIXTURE', 'OPERATOR_DECLARATION'),
                   'INVALID_EVIDENCE')
    allowed = {'TRUSTED_ASSESSMENT_PROCESS': {'OBSERVED_TRUSTED_HOST_FACT'},
               'PINNED_LOCAL_RELEASE_OBJECTS': {'VERIFIED_TRUSTED_RELEASE_FACT', 'UNKNOWN'},
               'IN_PROCESS_SYNTHETIC_FIXTURE': {'SYNTHETIC_DECLARED'},
               'OPERATOR_DECLARATION': {'OPERATOR_DECLARED'}}
    schema.require(evidence['origin'] in allowed[evidence['source']], 'INVALID_EVIDENCE')
    schema.timestamp(evidence['acquired_at'])
    age = (datetime.now(timezone.utc) - schema.timestamp(evidence['acquired_at'])).total_seconds()
    schema.require(0 <= age <= 60, 'STALE_EVIDENCE')
    return dict(origin=evidence['origin'], source=evidence['source'],
                acquired_at=evidence['acquired_at'], evidence_sha256=digest(evidence))
