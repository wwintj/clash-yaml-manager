"""Bounded direct TCP connection only: no application packets or proxy forwarding."""
import errno
import ipaddress
import math
import socket
import time

from core import source_fetch
from core.source_errors import SourceError

TIMEOUT = 3
ERRORS = ('dns_failed', 'blocked_address', 'timeout', 'connection_refused',
          'network_unreachable', 'connect_failed')


def probe(server, port, resolver=None, socket_factory=None, monotonic=None):
    resolver = resolver or source_fetch._resolve
    socket_factory = socket_factory or socket.socket
    monotonic = monotonic or time.monotonic
    sock = None
    try:
        if not isinstance(server, str) or not server or len(server) > 253 or type(port) is not int or not 1 <= port <= 65535:
            raise ValueError
        if '%' in server:
            raise SourceError('address')  # Scoped addresses are not portable numeric endpoints.
        try:
            ipaddress.ip_address(server)
        except ValueError:
            server = server.encode('idna').decode('ascii')
            if any(ord(c) <= 32 or ord(c) == 127 for c in server) or any(c in server for c in '%/@\\:[]'):
                raise SourceError('dns')
        deadline = monotonic() + TIMEOUT
        addresses = resolver(server, port, deadline)
        # The shared resolver rejects ANY unsafe answer. Also enforce numeric
        # sockaddrs at this boundary; no hostname reaches socket.connect.
        if not addresses:
            raise SourceError('dns')
        for family, _, address in addresses:
            source_fetch._public(address[0])
            if family not in (socket.AF_INET, socket.AF_INET6) or address[1] != port:
                raise SourceError('dns')
        family, protocol, address = addresses[0]
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise SourceError('timeout')
        sock = socket_factory(family, socket.SOCK_STREAM, protocol)
        sock.settimeout(min(TIMEOUT, remaining))
        started = monotonic()
        sock.connect(address)
        elapsed = max(0, (monotonic() - started) * 1000)
        if not math.isfinite(elapsed):
            raise ValueError
        return dict(latency_ms=elapsed, error=None)
    except SourceError as error:
        code = {'address':'blocked_address', 'dns':'dns_failed', 'timeout':'timeout'}.get(error.code, 'connect_failed')
    except socket.gaierror:
        code = 'dns_failed'
    except (TimeoutError, socket.timeout):
        code = 'timeout'
    except OSError as error:
        code = {errno.ECONNREFUSED:'connection_refused', errno.ENETUNREACH:'network_unreachable',
                errno.EHOSTUNREACH:'network_unreachable', errno.ETIMEDOUT:'timeout'}.get(error.errno, 'connect_failed')
    except (ValueError, TypeError, IndexError, UnicodeError):
        code = 'connect_failed'
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
    return dict(latency_ms=None, error=code)
