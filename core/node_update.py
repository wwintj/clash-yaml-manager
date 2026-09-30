"""Explicit Generate-only node update option; no persistence or I/O."""

MESSAGE = 'Node Update Mode is invalid. Choose Replace or Merge.'


class ModeError(ValueError):
    """Fixed safe message; rejected values are never echoed."""


def normalize(value='replace'):
    if not isinstance(value, str) or value not in ('replace', 'merge'):
        raise ModeError(MESSAGE)
    return value


def parse_form(form):
    if hasattr(form, 'getlist') and 'node_update_mode' in form and len(form.getlist('node_update_mode')) != 1:
        raise ModeError(MESSAGE)
    return normalize(form.get('node_update_mode', 'replace'))
