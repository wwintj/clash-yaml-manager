"""Short-lived, controller-only Mihomo checks of committed VMess/VLESS/Trojan proxies."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
from urllib.parse import quote, urlencode

from ruamel.yaml import YAML

from core.state import atomic_write

BATCH_SIZE = 64
WORKERS = 16
BATCH_SECONDS = 55
WHOLE_SECONDS = 235
STARTUP_SECONDS = 5
VALIDATION_SECONDS = 5
MAX_CONFIG_BYTES = 16 * 1024 * 1024
MAX_CONTROLLER_BODY = 64 * 1024


class ProbeEngineError(RuntimeError):
    """Never carry a node, target, process or controller error string."""


class BoundedOutput:
    """Drain Mihomo stdout/stderr privately; retain only a small bounded tail."""
    def __init__(self, pipe, limit=16 * 1024):
        self.buffer = bytearray()
        self.limit = limit
        def drain():
            try:
                while True:
                    chunk = os.read(pipe.fileno(), 4096)
                    if not chunk:
                        break
                    self.buffer[:] = (self.buffer + chunk)[-limit:]
            except OSError:
                pass
        self.thread = threading.Thread(target=drain, daemon=True)
        self.thread.start()

    def finish(self):
        self.thread.join(timeout=1)


def remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise ProbeEngineError('Proxy probe deadline exceeded.')
    return value


def stop_process(process):
    if process is None:
        return
    try:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
        else:
            process.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            raise ProbeEngineError('Proxy probe process cleanup failed.') from None


def environment(work):
    return {'PATH':'/usr/bin:/bin', 'HOME':str(work), 'TMPDIR':str(work), 'LANG':'C'}


def render_config(nodes, port, secret):
    proxies = []
    for index, node in enumerate(nodes, 1):
        config = dict(node['config'])
        config['name'] = f'probe-{index:04d}'
        proxies.append(config)
    value = {'log-level':'silent', 'allow-lan':False, 'geo-auto-update':False,
             'external-controller':f'127.0.0.1:{port}', 'secret':secret, 'proxies':proxies}
    stream = io.StringIO()
    YAML().dump(value, stream)
    payload = stream.getvalue().encode('utf-8')
    if len(payload) > MAX_CONFIG_BYTES:
        raise ProbeEngineError('Proxy probe configuration is too large.')
    return payload


def write_config(work, nodes, port, secret):
    path = work / 'config.yaml'
    atomic_write(path, render_config(nodes, port, secret))
    return path


def command(binary, work, config, test=False):
    args = [str(binary), '-d', str(work), '-f', str(config)]
    if test:
        args.append('-t')
    process = subprocess.Popen(args, cwd=work, env=environment(work), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True, close_fds=True)
    return process, BoundedOutput(process.stdout)


def validate(binary, work, nodes, port, secret, deadline):
    config = write_config(work, nodes, port, secret)
    process = output = None
    try:
        process, output = command(binary, work, config, test=True)
        try:
            code = process.wait(timeout=min(VALIDATION_SECONDS, remaining(deadline)))
        except subprocess.TimeoutExpired:
            raise ProbeEngineError('Proxy config validation timed out.') from None
        if code == 0:
            return True
        if code == 1:  # v1.19.31 returns 1 for Parse/config failure.
            return False
        raise ProbeEngineError('Proxy config validation failed.')
    finally:
        stop_process(process)
        if output:
            output.finish()


def isolate(binary, work, nodes, port, secret, deadline):
    """Bisect only definite config-validation failures, never process/system errors."""
    if validate(binary, work, nodes, port, secret, deadline):
        return nodes, []
    if len(nodes) == 1:
        return [], nodes
    middle = len(nodes) // 2
    left_ok, left_bad = isolate(binary, work, nodes[:middle], port, secret, deadline)
    right_ok, right_bad = isolate(binary, work, nodes[middle:], port, secret, deadline)
    return left_ok + right_ok, left_bad + right_bad


def random_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def controller(port, secret, path, timeout):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    try:
        connection.request('GET', path, headers={'Authorization':'Bearer ' + secret})
        response = connection.getresponse()
        body = response.read(MAX_CONTROLLER_BODY + 1)
        if len(body) > MAX_CONTROLLER_BODY:
            raise ProbeEngineError('Proxy controller response is invalid.')
        return response.status, json.loads(body)
    finally:
        connection.close()


def ready(process, port, secret, deadline):
    until = min(time.monotonic() + STARTUP_SECONDS, deadline)
    while time.monotonic() < until:
        if process.poll() is not None:
            return False
        try:
            status, data = controller(port, secret, '/version', min(.5, remaining(until)))
            if status == 200 and isinstance(data, dict) and data.get('version') == 'v1.19.31':
                return True
            return False
        except (OSError, ValueError, ProbeEngineError):
            time.sleep(.1)
    return False


def controller_alive(port, secret, deadline):
    try:
        status, data = controller(port, secret, '/version', min(1, remaining(deadline)))
        return status == 200 and isinstance(data, dict) and data.get('version') == 'v1.19.31'
    except (OSError, ValueError, ProbeEngineError):
        return False


def probe_one(port, secret, alias, settings, deadline):
    url = settings['url']
    query = urlencode({'url':url, 'timeout':settings['timeout_ms'],
                       'expected':settings['expected_status']})
    encoded = quote(alias, safe='')
    try:
        status, data = controller(port, secret, f'/proxies/{encoded}/delay?{query}',
                                  min(settings['timeout_ms'] / 1000 + 2, remaining(deadline)))
    except (OSError, ValueError):
        if not controller_alive(port, secret, deadline):
            raise ProbeEngineError('Proxy controller unavailable.') from None
        return dict(kind='failure', error='proxy_failed', latency_ms=None)
    if status in (503, 504):
        if not controller_alive(port, secret, deadline):
            raise ProbeEngineError('Proxy controller unavailable.')
        return dict(kind='failure', error='timeout' if status == 504 else 'proxy_failed', latency_ms=None)
    if status != 200 or not isinstance(data, dict) or type(data.get('delay')) is not int or not 0 < data['delay'] <= 65535:
        raise ProbeEngineError('Proxy controller response is invalid.')
    # v1.19.31 returns HTTP 200 + delay even when expected status mismatches.
    # Its URL-specific extra.alive flag is the actual expected-status verdict.
    try:
        detail_status, detail = controller(port, secret, f'/proxies/{encoded}', min(2, remaining(deadline)))
    except (OSError, ValueError):
        raise ProbeEngineError('Proxy controller unavailable.') from None
    if detail_status != 200 or not isinstance(detail, dict):
        raise ProbeEngineError('Proxy controller response is invalid.')
    extra = detail.get('extra')
    state = extra.get(url) if isinstance(extra, dict) else None
    if not isinstance(state, dict) or type(state.get('alive')) is not bool:
        raise ProbeEngineError('Proxy controller response is invalid.')
    if not state['alive']:
        return dict(kind='failure', error='probe_status_mismatch', latency_ms=None)
    return dict(kind='success', error=None, latency_ms=data['delay'])


def run_batch(binary, nodes, settings, state_dir, whole_deadline):
    work = Path(tempfile.mkdtemp(prefix='.proxy-probe-', dir=state_dir))
    work.chmod(0o700)
    process = output = None
    try:
        deadline = min(whole_deadline, time.monotonic() + BATCH_SECONDS)
        secret = secrets.token_urlsafe(32)  # 256 random bits per batch.
        port = random_port()
        valid, unsupported = isolate(binary, work, nodes, port, secret, deadline)
        results = {node['fingerprint']:dict(kind='unsupported',error='unsupported_config',latency_ms=None)
                   for node in unsupported}
        if not valid:
            return results
        for attempt in range(5):
            remaining(deadline)
            port = random_port()
            config = write_config(work, valid, port, secret)
            if not validate(binary, work, valid, port, secret, deadline):
                raise ProbeEngineError('Validated proxy config changed.')
            started_ready = False
            try:
                process, output = command(binary, work, config)
                started_ready = ready(process, port, secret, deadline)
            finally:
                if not started_ready:
                    stop_process(process)
                    if output: output.finish()
                    process = output = None
            if started_ready:
                break
            # A competing local bind can win the released random port; retry.
        else:
            raise ProbeEngineError('Proxy controller startup failed.')
        executor = ThreadPoolExecutor(max_workers=WORKERS)
        completed = False
        try:
            futures = [executor.submit(probe_one, port, secret, f'probe-{index:04d}', settings, deadline)
                       for index in range(1, len(valid) + 1)]
            for node, future in zip(valid, futures):
                results[node['fingerprint']] = future.result(timeout=remaining(deadline))
            completed = True
        finally:
            # A failed/deadline-exceeded batch must not wait for queued URL tests.
            # The controller is stopped in the outer finally; in-flight localhost
            # HTTP calls have their own bounded socket timeout.
            executor.shutdown(wait=completed, cancel_futures=not completed)
        remaining(deadline)
        if process.poll() is not None:
            raise ProbeEngineError('Proxy controller unavailable.')
        return results
    except (OSError, ValueError, subprocess.SubprocessError, TimeoutError) as error:
        raise ProbeEngineError('Proxy probe engine could not complete this check.') from None
    finally:
        try:
            stop_process(process)
        finally:
            try:
                if output: output.finish()
            finally:
                shutil.rmtree(work)


def run(binary, nodes, settings, state_dir):
    if len(nodes) > 256:
        raise ProbeEngineError('Too many proxy nodes.')
    deadline = time.monotonic() + WHOLE_SECONDS
    results = {}
    for offset in range(0, len(nodes), BATCH_SIZE):
        remaining(deadline)
        batch = nodes[offset:offset + BATCH_SIZE]
        results.update(run_batch(binary, batch, settings, state_dir, deadline))
    return results
