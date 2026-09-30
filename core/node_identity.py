"""Shared connection identity; byte-compatible with the original health hash."""
import hashlib
import json

from core import source_parser


def fingerprint(config):
    plain = source_parser._plain(config)
    encoded = json.dumps({k:v for k,v in plain.items() if k != 'name'},
                         sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()
