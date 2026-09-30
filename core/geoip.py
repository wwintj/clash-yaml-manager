"""Offline geographic ISO fallback. No DNS, network, global reader or health state."""
import io
import ipaddress
import re

from core.countries import COUNTRY_MAPPING

MODES = ('off', 'literal-ip')
MESSAGE = 'Country Detection settings are invalid.'


def defaults():
    return {'geoip': 'off'}


def normalize(value):
    if not isinstance(value, dict) or set(value) != {'geoip'} or value['geoip'] not in MODES:
        raise ValueError(MESSAGE)
    return dict(value)


def parse_form(form):
    key = 'country_geoip'
    if hasattr(form, 'getlist') and key in form and len(form.getlist(key)) != 1:
        raise ValueError(MESSAGE)
    if any(k.startswith('country_geoip') and k != key for k in form):
        raise ValueError(MESSAGE)
    return normalize({'geoip': form.get(key, 'off')})


def public_literal(value):
    if not isinstance(value, str) or '%' in value:
        return None
    try:
        address = ipaddress.ip_address(value)
        if (not address.is_global or address.is_multicast or address.is_reserved
                or address.is_unspecified or address.is_loopback or address.is_link_local
                or getattr(address, 'ipv4_mapped', None) is not None):
            return None
        return str(address)
    except ValueError:
        return None


def country_iso(record):
    if not isinstance(record, dict) or not isinstance(record.get('country'), dict):
        return None
    code = record['country'].get('iso_code')
    if not isinstance(code, str) or not re.fullmatch('[A-Za-z]{2}', code):
        return None
    code = code.upper()
    return code if code in COUNTRY_MAPPING and code != 'UNKNOWN' else None


def open_reader(payload):
    # MODE_FD consumes a verified bounded byte snapshot, not an untrusted path.
    import maxminddb
    with io.BytesIO(payload) as stream:
        return maxminddb.open_database(stream, maxminddb.MODE_FD)


def database_type(reader):
    meta = reader.metadata()
    value = meta.database_type
    if (not isinstance(value, str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}', value)
            or not any(kind in value.lower() for kind in ('country', 'city'))
            or type(meta.ip_version) is not int or meta.ip_version not in (4, 6)):
        raise ValueError('Invalid country-capable database.')
    return value


class Lookup:
    def __init__(self, reader=None):
        self.reader = reader
        self.classified = 0
        self.unavailable = reader is None

    def country(self, server):
        address = public_literal(server)
        if address is None or self.reader is None:
            return None
        try:
            code = country_iso(self.reader.get(address))
        except Exception:
            self.unavailable = True
            return None
        if code:
            self.classified += 1
        return code
