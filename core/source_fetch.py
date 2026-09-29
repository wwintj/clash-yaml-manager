"""Direct HTTP with per-hop public IP pinning, verified TLS and a total deadline.

DNS runs in a synchronous, short-lived child so a stuck system resolver cannot
outlive the request budget. No background refresh worker or proxy library is used.
"""
import http.client
import io
import ipaddress
import json
import socket
import ssl
import subprocess
import sys
import time
from urllib.parse import urljoin, urlsplit

from core.source_errors import SourceError
from core.source_parser import MAX_PAYLOAD

CONNECT_TIMEOUT = 5
TOTAL_TIMEOUT = 15
MAX_REDIRECTS = 3
_DNS_SCRIPT = ('import json,socket,sys; h,p=json.load(sys.stdin); '
               'print(json.dumps(socket.getaddrinfo(h,p,type=socket.SOCK_STREAM)))')


def remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise SourceError('timeout')
    return value


def validate_url(url):
    try:
        if not isinstance(url, str) or not url or len(url) > 8192 or any(ord(c) <= 32 or ord(c) == 127 for c in url):
            raise ValueError
        parts = urlsplit(url)
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username is not None or parts.password is not None:
            raise ValueError
        host = parts.hostname.encode('idna').decode('ascii')
        if '%' in host or '\\' in host:
            raise ValueError
        port = parts.port if parts.port is not None else (443 if parts.scheme == 'https' else 80)
        if not 1 <= port <= 65535:
            raise ValueError
        target = (parts.path or '/') + ('?' + parts.query if parts.query else '')
        target.encode('ascii')  # URLs must percent-encode non-ASCII path/query characters.
        return parts.scheme, host, port, target
    except (ValueError, UnicodeError):
        raise SourceError('url') from None


def _public(address):
    try:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified or ip.is_loopback or ip.is_link_local:
            raise ValueError
        # Transition mechanisms can encapsulate a disallowed IPv4 destination.
        if isinstance(ip, ipaddress.IPv6Address) and (ip.ipv4_mapped or ip.sixtofour or ip.teredo):
            raise ValueError
    except ValueError:
        raise SourceError('address') from None


def _resolve(host, port, deadline):
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        try:
            child = subprocess.run([sys.executable, '-I', '-c', _DNS_SCRIPT],
                input=json.dumps([host, port]), text=True, capture_output=True, check=True,
                timeout=remaining(deadline))
            records = json.loads(child.stdout)
        except subprocess.TimeoutExpired:
            raise SourceError('timeout') from None
        except (OSError, subprocess.CalledProcessError, ValueError):
            raise SourceError('dns') from None
    else:
        records = [(socket.AF_INET6 if ip.version == 6 else socket.AF_INET,
                    socket.SOCK_STREAM, 0, '', (host, port))]
    approved = []
    for family, kind, protocol, _, address in records:
        if family not in (socket.AF_INET, socket.AF_INET6) or kind != socket.SOCK_STREAM:
            raise SourceError('dns')
        _public(address[0])  # Reject the entire answer if ANY address is unsafe.
        approved.append((family, protocol, tuple(address)))
    if not approved:
        raise SourceError('dns')
    remaining(deadline)
    return approved


class _Reader(io.RawIOBase):
    def __init__(self, owner):
        self.owner = owner
        self.owner.readers += 1

    def readable(self):
        return True

    def readinto(self, buffer):
        self.owner.sock.settimeout(remaining(self.owner.deadline))
        return self.owner.sock.recv_into(buffer)

    def close(self):
        if not self.closed:
            self.owner.readers -= 1
            if self.owner.released and not self.owner.readers:
                self.owner.sock.close()
        super().close()


class _DeadlineSocket:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline
        self.readers, self.released = 0, False

    def makefile(self, mode):
        return io.BufferedReader(_Reader(self))

    def sendall(self, data):
        self.sock.settimeout(remaining(self.deadline))
        self.sock.sendall(data)

    def close(self):
        self.released = True
        if not self.readers:
            self.sock.close()


class _PinnedConnection(http.client.HTTPConnection):
    def __init__(self, scheme, host, port, addresses, deadline):
        super().__init__(host, port, timeout=CONNECT_TIMEOUT)
        self.scheme, self.addresses, self.deadline = scheme, addresses, deadline

    def connect(self):
        # No create_connection(host): the only connect target is the approved numeric sockaddr.
        family, protocol, address = self.addresses[0]
        sock = socket.socket(family, socket.SOCK_STREAM, protocol)
        try:
            sock.settimeout(min(CONNECT_TIMEOUT, remaining(self.deadline)))
            sock.connect(address)
            if self.scheme == 'https':
                sock.settimeout(min(CONNECT_TIMEOUT, remaining(self.deadline)))
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
            self.sock = _DeadlineSocket(sock, self.deadline)
        except BaseException:
            sock.close()
            raise


def fetch(url):
    deadline = time.monotonic() + TOTAL_TIMEOUT
    try:
        for hop in range(MAX_REDIRECTS + 1):
            scheme, host, port, target = validate_url(url)
            addresses = _resolve(host, port, deadline)
            connection = _PinnedConnection(scheme, host, port, addresses, deadline)
            response = None
            try:
                connection.request('GET', target, headers={
                    'User-Agent': 'clash-yaml-manager', 'Accept': '*/*', 'Connection': 'close'})
                response = connection.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader('Location')
                    if hop == MAX_REDIRECTS or not location:
                        raise SourceError('redirect')
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    raise SourceError('http_' + str(response.status))
                if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                    raise SourceError('encoding')
                length = response.getheader('Content-Length')
                if length is not None:
                    if not length.isdigit():
                        raise SourceError('invalid')
                    if int(length) > MAX_PAYLOAD:
                        raise SourceError('size')
                payload = bytearray()
                while True:
                    remaining(deadline)
                    block = response.read1(min(65536, MAX_PAYLOAD + 1 - len(payload)))
                    if not block:
                        break
                    payload.extend(block)
                    if len(payload) > MAX_PAYLOAD:
                        raise SourceError('size')
                if length is not None and len(payload) != int(length):
                    raise SourceError('connection')
                return bytes(payload)
            finally:
                if response is not None:
                    response.close()
                connection.close()
    except SourceError:
        raise
    except ssl.SSLError:
        raise SourceError('tls') from None
    except (TimeoutError, socket.timeout):
        raise SourceError('timeout') from None
    except (OSError, ValueError, http.client.HTTPException):
        raise SourceError('connection') from None
