"""One direct, verified Telegram HTTPS POST with a total five-second budget."""
import http.client
import json
import queue
import re
import socket
import ssl
import threading
import time

HOST = 'api.telegram.org'
TIMEOUT = 5.0
MAX_RESPONSE = 64 * 1024
ERRORS = ('timeout', 'network', 'tls', 'http', 'api', 'invalid_response', 'config')


def valid_token(value):
    return isinstance(value, str) and re.fullmatch(r'[1-9][0-9]{0,19}:[A-Za-z0-9_-]{20,180}', value) is not None


def valid_chat(value):
    return (isinstance(value, str) and re.fullmatch(r'-?[1-9][0-9]{0,18}', value) is not None
            and abs(int(value)) <= 2**63 - 1)


def remaining(deadline):
    timeout = deadline - time.monotonic()
    if timeout <= 0:
        raise TimeoutError
    return timeout


def response_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def invalid_constant(_value):
    raise ValueError


def resolve(deadline):
    # System getaddrinfo has no portable timeout. Only the fixed-host DNS lookup
    # may outlive the caller, in a daemon; it cannot later perform a POST.
    answer = queue.Queue(maxsize=1)
    def lookup():
        try:
            answer.put((True, socket.getaddrinfo(HOST, 443, type=socket.SOCK_STREAM)))
        except Exception:
            answer.put((False, None))
    threading.Thread(target=lookup, daemon=True).start()
    try:
        ok, addresses = answer.get(timeout=remaining(deadline))
    except queue.Empty:
        raise TimeoutError from None
    if not ok or not addresses:
        raise OSError
    return addresses


class DirectConnection(http.client.HTTPSConnection):
    def __init__(self, deadline):
        super().__init__(HOST, timeout=remaining(deadline), context=ssl.create_default_context())
        self.deadline = deadline

    def connect(self):
        last = None
        for family, kind, protocol, _, address in resolve(self.deadline):
            raw = socket.socket(family, kind, protocol)
            try:
                self.sock = raw
                raw.settimeout(remaining(self.deadline))
                raw.connect(address)
                raw.settimeout(remaining(self.deadline))
                self.sock = self._context.wrap_socket(raw, server_hostname=HOST)
                return
            except (TimeoutError, ssl.SSLError):
                raw.close()
                raise
            except OSError as error:
                raw.close()
                self.sock = None
                last = error
        raise OSError from last

    def send(self, data):
        if self.sock is None:
            self.connect()
        self.sock.settimeout(remaining(self.deadline))
        super().send(data)


class Telegram:
    def send(self, token, chat, text):
        if not valid_token(token) or not valid_chat(chat) or not isinstance(text, str) or not 0 < len(text) <= 3500:
            return 'config'
        connection = None
        watchdog = None
        try:
            deadline = time.monotonic() + TIMEOUT
            connection = DirectConnection(deadline)
            active_socket = []
            def expire():
                # Interrupt slow-drip HTTP headers as well as response bodies.
                # Socket timeouts alone bound each read, not the whole request.
                sock = active_socket[0] if active_socket else connection.sock
                if sock is not None:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
            watchdog = threading.Timer(remaining(deadline), expire)
            watchdog.daemon = True
            watchdog.start()
            body = json.dumps(dict(chat_id=chat, text=text, disable_web_page_preview=True)).encode()
            connection.request('POST', '/bot' + token + '/sendMessage', body=body,
                               headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
            connection.sock.settimeout(remaining(deadline))
            sock = connection.sock
            active_socket.append(sock)
            response = connection.getresponse()
            remaining(deadline)
            if response.status != 200:
                return 'http'  # No redirect following; never read/store error bodies.
            chunks, size = [], 0
            while True:
                sock.settimeout(remaining(deadline))
                chunk = response.read1(min(8192, MAX_RESPONSE + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_RESPONSE:
                    return 'invalid_response'
                if response.isclosed():
                    break
            remaining(deadline)
            if response.length not in (None, 0):
                return 'invalid_response'
            value = json.loads(b''.join(chunks), object_pairs_hook=response_object,
                               parse_constant=invalid_constant)
            if not isinstance(value, dict) or type(value.get('ok')) is not bool:
                return 'invalid_response'
            return 'success' if value['ok'] else 'api'
        except (TimeoutError, socket.timeout):
            return 'timeout'
        except ssl.SSLError:
            return 'tls'
        except (ValueError, UnicodeError, http.client.HTTPException):
            return 'timeout' if time.monotonic() >= deadline else 'invalid_response'
        except Exception:
            return 'timeout' if time.monotonic() >= deadline else 'network'
        finally:
            if watchdog is not None:
                watchdog.cancel()
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
