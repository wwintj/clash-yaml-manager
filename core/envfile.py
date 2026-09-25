"""Read systemd-style EnvironmentFile assignments without shell evaluation.

Preserve each original record verbatim when editing unrelated variables. Supports
quoted values, literal $/#/backticks, escaped characters and continued lines.
"""
import re

from core.state import StateError


class _Incomplete(Exception):
    pass


def _value(text):
    text = text.lstrip(' \t')
    if not text:
        return ''
    quote = text[0] if text[0] in ('"', "'") else None
    i, out = (1 if quote else 0), []
    while i < len(text):
        char = text[i]
        if quote and char == quote:
            if text[i + 1:].strip():
                raise StateError('环境文件的引号值格式无效。')
            return ''.join(out)
        if char == '\\' and quote != "'":
            if i + 1 == len(text):
                raise _Incomplete
            following = text[i + 1]
            if following == '\n':
                i += 2
                if i == len(text):
                    raise _Incomplete
                continue
            if quote == '"' and following not in ('"', '\\', '$', '`'):
                out.append('\\')
            out.append(following)
            i += 2
            continue
        if not quote and char in '\r\n':
            return ''.join(out).rstrip(' \t')
        out.append(char)
        i += 1
    if quote:
        raise _Incomplete
    return ''.join(out).rstrip(' \t')


def records(text):
    lines = iter(text.splitlines(keepends=True))
    for line in lines:
        match = re.match(r'^[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]*=', line)
        if not match:
            yield None, None, line
            continue
        raw, value_text = line, line[match.end():]
        while True:
            try:
                value = _value(value_text)
                break
            except _Incomplete:
                following = next(lines, None)
                if following is None:
                    raise StateError('环境文件含未结束的引号或续行。') from None
                raw += following
                value_text += following
        yield match.group(1), value, raw


def values(text):
    return {key: value for key, value, _ in records(text) if key is not None}
