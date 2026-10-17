"""SYNTHETIC ONLY: no production caller, key store, capture authority or CLI.

HMAC authentication is real; source-event authority is an independent in-memory
test ledger. Neither that ledger nor software keys prove an uncloned host.
"""
import copy
import hashlib
import hmac
import json
import os
import secrets
import stat

PROTOCOL = 'cym-external-attestation-synthetic-v1'
DOMAIN = 'CYM/D3-P1/SYNTHETIC/CAPTURE/v1'
MAX_BYTES = 16384
MAX_EPOCH = 253402300799
STAGES = ('CAPTURE_STARTED', 'QUIET_ATTESTED', 'PACKAGE_DURABLE',
          'RECORD_DURABLE', 'ATTESTATION_ISSUED', 'CAPTURE_EVIDENCE_COMPLETE')
PAYLOAD = {'schema_version', 'protocol', 'algorithm', 'domain', 'scope', 'binding',
           'installation', 'event', 'controller', 'key_id', 'issued_at', 'expires_at'}


class Refusal(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise Refusal(code)


def exact(value, fields):
    require(type(value) is dict and set(value) == set(fields), 'INVALID_SCHEMA')


def hex_id(value, length=32):
    require(type(value) is str and len(value) == length
            and all(c in '0123456789abcdef' for c in value), 'INVALID_SCHEMA')


def number(value, maximum=MAX_EPOCH):
    require(type(value) is int and 0 <= value <= maximum, 'INVALID_SCHEMA')


def canonical(value):
    # Bound the object before encoding, including test-side re-signing inputs.
    stack, count = [(value, 0)], 0
    while stack:
        item, depth = stack.pop(); count += 1
        require(depth <= 6 and count <= 128, 'RESOURCE_LIMIT')
        if type(item) is dict:
            require(len(item) <= 32 and all(type(k) is str and len(k) <= 64 for k in item), 'RESOURCE_LIMIT')
            stack.extend((v, depth + 1) for v in item.values())
        elif type(item) is str:
            require(len(item) <= 256, 'RESOURCE_LIMIT')
        elif type(item) is int:
            number(item, 2**64 - 1)
        else:
            require(False, 'INVALID_SCHEMA')
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True,
                     separators=(',', ':'), allow_nan=False).encode('ascii')
    require(len(raw) <= MAX_BYTES, 'RESOURCE_LIMIT')
    return raw


def parse(raw):
    require(type(raw) is bytes and len(raw) <= MAX_BYTES, 'RESOURCE_LIMIT')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'DUPLICATE_KEY')
            result[key] = value
        return result
    def integer(text):
        require(len(text) <= 20, 'RESOURCE_LIMIT')
        return int(text)
    def invalid(_):
        raise Refusal('INVALID_JSON')
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_int=integer,
                           parse_float=invalid, parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, Refusal):
            raise
        raise Refusal('INVALID_JSON') from None
    require(canonical(value) == raw, 'NON_CANONICAL')
    return value


def identity(value):
    exact(value, ('device', 'inode'))
    for field in value.values():
        number(field, 2**64 - 1)


def validate_binding(value):
    exact(value, ('operation_id', 'manifest_sha256', 'record_sha256', 'package', 'record'))
    hex_id(value['operation_id'])
    for key in ('manifest_sha256', 'record_sha256'):
        hex_id(value[key], 64)
    identity(value['package']); identity(value['record'])


def validate(payload):
    exact(payload, PAYLOAD)
    require(type(payload['schema_version']) is int and payload['schema_version'] == 1, 'UNSUPPORTED_VERSION')
    require(payload['algorithm'] == 'HMAC-SHA256', 'INVALID_ALGORITHM')
    require(payload['protocol'] == PROTOCOL and payload['domain'] == DOMAIN, 'WRONG_DOMAIN')
    require(payload['scope'] == 'SYNTHETIC_ONLY', 'INVALID_ORIGIN')
    validate_binding(payload['binding'])
    exact(payload['installation'], ('instance_id', 'epoch', 'declaration_sha256', 'origin'))
    hex_id(payload['installation']['instance_id']); hex_id(payload['installation']['epoch'])
    hex_id(payload['installation']['declaration_sha256'], 64)
    require(payload['installation']['origin'] == 'SYNTHETIC_CONTROLLED_FIXTURE', 'INVALID_ORIGIN')
    exact(payload['controller'], ('id', 'version', 'origin'))
    hex_id(payload['controller']['id'])
    require(type(payload['controller']['version']) is int and payload['controller']['version'] == 1, 'INVALID_SCHEMA')
    require(payload['controller']['origin'] == 'SYNTHETIC_TEST_CONTROLLER', 'INVALID_ORIGIN')
    exact(payload['event'], ('id', 'origin', 'phase', 'started_at', 'quiet_at',
                             'package_durable_at', 'record_durable_at'))
    hex_id(payload['event']['id'])
    require(payload['event']['origin'] == 'SYNTHETIC', 'INVALID_ORIGIN')
    require(payload['event']['phase'] == 'ATTESTATION_ISSUED', 'INCOMPLETE_EVENT')
    times = [payload['event'][k] for k in ('started_at', 'quiet_at', 'package_durable_at', 'record_durable_at')]
    for value in times + [payload['issued_at'], payload['expires_at']]:
        number(value)
    require(times == sorted(times) and times[-1] <= payload['issued_at'] < payload['expires_at'], 'INVALID_SEQUENCE')
    require(payload['expires_at'] - payload['issued_at'] <= 300, 'INVALID_SEQUENCE')
    hex_id(payload['key_id'])


def mac(secret, payload):
    require(type(secret) is bytes and len(secret) == 32, 'INVALID_SYNTHETIC_KEY')
    return hmac.new(secret, DOMAIN.encode('ascii') + b'\0' + canonical(payload), hashlib.sha256).hexdigest()


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class FixtureReader:
    """Held caller-owned fixture FD only; no machine-id, system paths or discovery."""
    def __init__(self, root_fd, existing_verifier):
        self.root = root_fd
        self.existing_verifier = existing_verifier

    def read(self, parts, directory=False):
        require(parts and all(type(p) is str and p not in ('', '.', '..')
                             and '/' not in p for p in parts), 'INVALID_PATH')
        fd = os.dup(self.root); held = []
        try:
            root_info = os.fstat(fd)
            require(stat.S_ISDIR(root_info.st_mode) and stat.S_IMODE(root_info.st_mode) == 0o700
                    and root_info.st_uid == os.geteuid() and root_info.st_gid == os.getegid(), 'UNSAFE_FIXTURE')
            device = root_info.st_dev
            for index, name in enumerate(parts):
                isdir = index < len(parts)-1 or directory
                before = os.stat(name, dir_fd=fd, follow_symlinks=False)
                require((stat.S_ISDIR(before.st_mode) if isdir else stat.S_ISREG(before.st_mode))
                        and before.st_uid == os.geteuid() and before.st_gid == os.getegid()
                        and stat.S_IMODE(before.st_mode) == (0o700 if isdir else 0o600)
                        and (isdir or before.st_nlink == 1) and before.st_dev == device, 'UNSAFE_FIXTURE')
                child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                                | (os.O_DIRECTORY if isdir else 0), dir_fd=fd)
                held.append((fd, name, child, fingerprint(before)))
                require(fingerprint(os.fstat(child)) == fingerprint(before), 'INPUT_CHANGED')
                fd = child
            raw = bytearray()
            if not directory:
                require(os.fstat(fd).st_size <= MAX_BYTES, 'RESOURCE_LIMIT')
                while True:
                    chunk = os.read(fd, min(4096, MAX_BYTES-len(raw)+1))
                    if not chunk:
                        break
                    raw.extend(chunk)
                    require(len(raw) <= MAX_BYTES, 'RESOURCE_LIMIT')
            for parent, name, child, before in reversed(held):
                require(fingerprint(os.fstat(child)) == before
                        == fingerprint(os.stat(name, dir_fd=parent, follow_symlinks=False)), 'INPUT_CHANGED')
            info = os.fstat(fd)
            return bytes(raw), dict(device=info.st_dev, inode=info.st_ino)
        finally:
            for _, _, child, _ in reversed(held):
                os.close(child)
            os.close(held[0][0] if held else fd)

    def binding(self, operation):
        hex_id(operation)
        # A test-owned adapter calls the unchanged real v1 verifier. A valid MAC
        # is not a replacement for blob/content/Record verification.
        verified = self.existing_verifier(operation)
        require(verified['code'] == 'VERIFIED' and verified['TRUST_ANCHOR_VERIFIED'], 'PACKAGE_NOT_VERIFIED')
        _, package = self.read(['packages', operation], directory=True)
        manifest, _ = self.read(['packages', operation, 'manifest.json'])
        record, record_id = self.read(['records', operation + '.json'])
        return dict(operation_id=operation, manifest_sha256=hashlib.sha256(manifest).hexdigest(),
                    record_sha256=hashlib.sha256(record).hexdigest(), package=package, record=record_id)


class Controller:
    """Synthetic capability/ledger; NOT a protected production capture service."""
    def __init__(self):
        self.secret = secrets.token_bytes(32)
        self.key_id = secrets.token_hex(16)
        self.installation = dict(instance_id=secrets.token_hex(16), epoch=secrets.token_hex(16),
                                 declaration_sha256=hashlib.sha256(b'SYNTHETIC_INSTALLATION').hexdigest(),
                                 origin='SYNTHETIC_CONTROLLED_FIXTURE')
        self.controller = dict(id=secrets.token_hex(16), version=1, origin='SYNTHETIC_TEST_CONTROLLER')
        self.events = {}

    def start(self, at, existing_operations):
        number(at)
        require(type(existing_operations) is list and len(existing_operations) <= 64, 'INVALID_SCHEMA')
        for operation in existing_operations:
            hex_id(operation)
        event = secrets.token_hex(16)
        self.events[event] = dict(phase=STAGES[0], started_at=at,
                                 preexisting_operations=existing_operations[:])
        return event

    def advance(self, event, phase, at, binding=None, *, durable=False):
        require(event in self.events, 'EVENT_MISSING')
        item = self.events[event]; number(at)
        require(item['phase'] in STAGES, 'INVALID_SEQUENCE')
        index = STAGES.index(item['phase'])
        require(index < 3 and phase == STAGES[index + 1], 'INVALID_SEQUENCE')
        require(at >= max(v for k, v in item.items() if k.endswith('_at')), 'INVALID_SEQUENCE')
        if phase in ('PACKAGE_DURABLE', 'RECORD_DURABLE'):
            # This is a SYNTHETIC acknowledgement supplied by the trusted test
            # workflow, not a real durability/quiet authority or production API.
            require(durable is True, 'DURABILITY_NOT_ATTESTED')
        if phase == 'PACKAGE_DURABLE':
            validate_binding(binding)
            require(binding['operation_id'] not in item['preexisting_operations'], 'POSTHOC_CAPTURE_REFUSED')
            item['binding'] = copy.deepcopy(binding)
        if phase == 'RECORD_DURABLE':
            require(item['binding'] == binding, 'BINDING_MISMATCH')
        item.update(phase=phase)
        item[{'QUIET_ATTESTED': 'quiet_at', 'PACKAGE_DURABLE': 'package_durable_at',
              'RECORD_DURABLE': 'record_durable_at'}[phase]] = at

    def issue(self, event, reader, at, expires):
        try:
            return self._issue(event, reader, at, expires)
        except OSError:
            raise Refusal('IO_FAILED') from None

    def _issue(self, event, reader, at, expires):
        require(event in self.events, 'EVENT_MISSING')
        item = self.events[event]
        require(item['phase'] == 'RECORD_DURABLE', 'INCOMPLETE_EVENT')
        require(reader.binding(item['binding']['operation_id']) == item['binding'], 'INPUT_CHANGED')
        payload = dict(schema_version=1, protocol=PROTOCOL, algorithm='HMAC-SHA256', domain=DOMAIN,
                       scope='SYNTHETIC_ONLY', binding=copy.deepcopy(item['binding']),
                       installation=copy.deepcopy(self.installation), controller=copy.deepcopy(self.controller),
                       event=dict(id=event, origin='SYNTHETIC', phase='ATTESTATION_ISSUED',
                                  **{k: v for k, v in item.items() if k.endswith('_at')}),
                       key_id=self.key_id, issued_at=at, expires_at=expires)
        validate(payload)
        raw = canonical(dict(payload=payload, mac=mac(self.secret, payload)))
        item.update(phase='ATTESTATION_ISSUED', payload=copy.deepcopy(payload))
        return raw

    def complete(self, event, raw, *, durable=False):
        require(event in self.events, 'EVENT_MISSING')
        item = self.events[event]
        require(item['phase'] == 'ATTESTATION_ISSUED', 'INVALID_SEQUENCE')
        require(durable is True, 'DURABILITY_NOT_ATTESTED')
        envelope = parse(raw); exact(envelope, ('payload', 'mac'))
        require(envelope['payload'] == item['payload'], 'EVENT_ORIGIN_MISMATCH')
        hex_id(envelope['mac'], 64)
        require(hmac.compare_digest(envelope['mac'], mac(self.secret, item['payload'])), 'MAC_INVALID')
        # Synthetic caller acknowledgement, NOT a production durability authority.
        item['phase'] = 'CAPTURE_EVIDENCE_COMPLETE'


def result():
    return dict(scope='SYNTHETIC_ONLY', code='NOT_EVALUATED', CRYPTOGRAPHIC_BINDING_VALID=False,
                CAPTURE_EVENT_ORIGIN_TRUSTED=False, INSTALLATION_CONTINUITY_VERIFIED=False,
                CAPTURE_INSTALLATION_CONTINUITY_VERIFIED=False,
                SYNTHETIC_CAPTURE_EVENT_ORIGIN_VALID=False, SYNTHETIC_INSTALLATION_CONTINUITY_VERIFIED=False,
                ASSESSMENT_SUPPORTED=False, RUNTIME_REQUIREMENTS_READY=False,
                RESTORE_PLAN_READY=False, RESTORE_PROVEN=False,
                RESTORE_APPLY_IMPLEMENTED=False, AUTO_PRUNE_IMPLEMENTED=False, stages=[])


def verify(raw, reader, operation, keys, events, controller, current, nonce, now, hook=None):
    answer = result()
    try:
        require(raw is not None, 'ATTESTATION_MISSING')
        envelope = parse(raw); exact(envelope, ('payload', 'mac'))
        payload = envelope['payload']; validate(payload); hex_id(envelope['mac'], 64)
        answer['stages'].append('SCHEMA_VALIDATED')
        require(payload['key_id'] in keys, 'UNKNOWN_KEY')
        key = keys[payload['key_id']]
        exact(key, ('active', 'secret'))
        require(key['active'] is True, 'KEY_REVOKED')
        require(hmac.compare_digest(mac(key['secret'], payload), envelope['mac']), 'MAC_INVALID')
        answer['CRYPTOGRAPHIC_BINDING_VALID'] = True; answer['stages'].append('MAC_VALIDATED')
        number(now)
        require(payload['issued_at'] <= now < payload['expires_at'], 'EVIDENCE_EXPIRED')
        require(payload['binding']['operation_id'] == operation, 'OPERATION_MISMATCH')
        answer['stages'].append('V1_VERIFICATION_STARTED')
        before = reader.binding(operation)
        require(before == payload['binding'], 'BINDING_MISMATCH')
        answer['stages'].append('FILES_BOUND')
        require(payload['event']['id'] in events, 'EVENT_MISSING')
        event = events[payload['event']['id']]
        require(type(event) is dict and event.get('phase') == 'CAPTURE_EVIDENCE_COMPLETE', 'INCOMPLETE_EVENT')
        require(event.get('payload') == payload and payload['controller'] == controller, 'EVENT_ORIGIN_MISMATCH')
        answer['SYNTHETIC_CAPTURE_EVENT_ORIGIN_VALID'] = True; answer['stages'].append('SYNTHETIC_EVENT_VALIDATED')
        exact(current, ('origin', 'installation', 'key_id', 'nonce', 'observed_at'))
        require(current['nonce'] == nonce, 'NONCE_MISMATCH')
        number(current['observed_at'])
        require(0 <= now-current['observed_at'] <= 30, 'STALE_OBSERVATION')
        require(current['origin'] == 'SYNTHETIC' and current['key_id'] == payload['key_id']
                and current['installation'] == payload['installation'], 'INSTALLATION_MISMATCH')
        if hook is not None:
            hook()  # Test-process barrier only; production never imports this module.
        answer['stages'].append('EXIT_REVALIDATION_REACHED')
        require(reader.binding(operation) == before, 'INPUT_CHANGED')
        answer.update(code='SYNTHETIC_CONTINUITY_VERIFIED', SYNTHETIC_INSTALLATION_CONTINUITY_VERIFIED=True)
        answer['stages'].append('EXIT_REVALIDATION_COMPLETED')
    except Refusal as error:
        answer['code'] = error.code
    except OSError:
        answer['code'] = 'IO_FAILED'
    return answer
