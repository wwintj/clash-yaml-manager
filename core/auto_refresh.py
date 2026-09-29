"""One bounded scheduler run, independent of Flask/Gunicorn lifecycle."""
import argparse
import logging
from pathlib import Path
import time

from core.fixed_subscriptions import FixedSubscriptions, GenerationError
from core import refresh_schedule
from core.source_errors import SourceError
from core.state import LockBusyError, StateError, file_lock

MAX_DUE_SOURCES = 32
LOGGER = logging.getLogger(__name__)


def select_work(entries, now):
    groups = []
    for entry in entries:
        sources = [s for s in entry['sources'] if refresh_schedule.due(entry, s, now)]
        if sources:
            oldest = min(s['next_refresh_at'] if s['next_refresh_at'] is not None else 0 for s in sources)
            groups.append((oldest, entry['id'], entry, sources))
    work, count = [], 0
    for _, _, entry, sources in sorted(groups):
        if count and count + len(sources) > MAX_DUE_SOURCES:
            break  # Do not split a subscription or jump ahead of older work.
        work.append((entry, [s['id'] for s in sources]))
        count += len(sources)
        if count >= MAX_DUE_SOURCES:
            break  # One oversized subscription may run alone.
    return work


def run_once(store, default_path, clock=None):
    clock = clock or time.time
    try:
        with file_lock(store.state / 'auto_refresh.lock', blocking=False, strict=True):
            work = select_work(store.list(), clock())
            LOGGER.info('Auto refresh started. subscriptions=%d sources=%d',
                        len(work), sum(len(ids) for _, ids in work))
            for entry, identifiers in work:
                try:
                    refreshed = store.refresh_sources(entry, identifiers, default_path, clock=clock)
                except SourceError as error:
                    if error.code == 'conflict':
                        result = 'conflict'
                    else:
                        failed = [error.source_id] if getattr(error, 'source_id', None) else identifiers
                        result = 'error' if store.record_refresh_error(entry, failed, error.code, clock) else 'conflict'
                except GenerationError:
                    result = 'error' if store.record_refresh_error(entry, identifiers, 'generation', clock) else 'conflict'
                else:
                    result = 'cached' if any(s['using_cache'] for s in refreshed['sources'] if s['id'] in identifiers) else 'success'
                LOGGER.info('Auto refresh subscription=%s sources=%d result=%s', entry['id'], len(identifiers), result)
            return 0
    except LockBusyError:
        LOGGER.info('Auto refresh already running.')
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Refresh due fixed sources once, then exit.')
    parser.add_argument('--once', action='store_true', required=True)
    parser.add_argument('--state-dir', type=Path, default=Path('state'))
    parser.add_argument('--default-yaml', type=Path, default=Path('defaults/default.yaml'))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    try:
        # Do not repair an unsafe existing state directory during a scheduler scan.
        for directory in (args.state_dir, args.state_dir / 'fixed_subscriptions'):
            if directory.exists() or directory.is_symlink():
                if directory.is_symlink() or not directory.is_dir() or directory.stat().st_mode & 0o077:
                    raise StateError('Unsafe state directory.')
        store = FixedSubscriptions(args.state_dir)
        return run_once(store, args.default_yaml)
    except Exception:
        # Journal must never contain traceback/exception text with URLs or credentials.
        LOGGER.error('Auto refresh critical state error. Inspect private state and restore a consistent backup.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
