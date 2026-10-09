"""Finite login lifetime; never echo invalid private environment values."""
import re


def lifetime_days(value=None):
    if value is None:
        return 30
    # Bound before int conversion (including Python's large-integer limit).
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,4}', value):
        raise ValueError('SESSION_LIFETIME_DAYS must be an integer from 1 to 3650.')
    days = int(value)
    if not 1 <= days <= 3650:
        raise ValueError('SESSION_LIFETIME_DAYS must be an integer from 1 to 3650.')
    return days
