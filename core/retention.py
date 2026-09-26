"""Hour-based temporary retention, with explicit legacy configuration fallback."""
import math


def seconds_from_env(env, key, default_hours, legacy=None):
    value, multiplier = env.get(key), 3600
    if value is None and legacy and env.get(legacy) is not None:
        value, multiplier = env[legacy], 86400
    if value is None:
        return default_hours * 3600
    try:
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            raise ValueError
        return number * multiplier
    except (ValueError, TypeError):
        # Historical malformed values must not crash upgrades or trigger mass deletion.
        return default_hours * 3600
