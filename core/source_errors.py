"""Allowlisted source failures: never retain transport/parser exception text."""
import re

MESSAGES = {
    'url': 'Invalid remote URL', 'address': 'Remote address is not public',
    'dns': 'DNS resolution failed', 'connection': 'Connection failed',
    'timeout': 'Source request timed out', 'tls': 'TLS verification failed',
    'redirect': 'Invalid or excessive redirects', 'size': 'Response too large',
    'encoding': 'Unsupported response encoding', 'format': 'Unsupported source format',
    'invalid': 'Invalid source payload', 'empty': 'No supported VMess/VLESS nodes',
    'duplicate': 'Duplicate node name', 'config': 'Invalid source configuration',
    'upload': 'Select a node source file',
    'conflict': 'Subscription changed while refreshing. Please retry.',
}


def valid_code(code):
    return isinstance(code, str) and (code in MESSAGES or re.fullmatch(r'http_[1-5][0-9]{2}', code) is not None)


def message(code):
    if code in MESSAGES:
        return MESSAGES[code]
    return 'HTTP ' + code[5:] if valid_code(code) else 'Source unavailable'


class SourceError(ValueError):
    def __init__(self, code):
        self.code = code if valid_code(code) else 'invalid'
        super().__init__(message(self.code))
