"""One bounded health scan outside Flask; source refresh is a separate service."""
import argparse
import logging
from pathlib import Path
import signal
import time

from core import health_schedule
from core.fixed_subscriptions import FixedSubscriptions
from core.node_health import HealthError, NodeHealth
from core.proxy_health import ProxyHealth, ProxyHealthError
from core.state import LockBusyError, StateError, file_lock

MAX_ENDPOINT_JOBS = 4
MAX_PROXY_JOBS = 1
LOGGER = logging.getLogger(__name__)


def select_work(entries, schedules, now, limit):
    active = {entry['id'] for entry in entries if entry['status'] == 'active'}
    return [key for _,key in sorted((entry['next_check_at'],key)
            for key,entry in schedules.items()
            if key in active and health_schedule.due(entry,now))[:limit]]


def run_once(store, *, endpoint=None, proxy=None, clock=None):
    clock = clock or time.time
    endpoint = endpoint or NodeHealth(store,clock=clock)
    proxy = proxy or ProxyHealth(store,clock=clock)
    try:
        with file_lock(store.state/'auto_health.lock',blocking=False,strict=True):
            entries, now = store.list(), clock()
            work = []
            for kind, observer, limit in (('endpoint',endpoint,MAX_ENDPOINT_JOBS),('proxy',proxy,MAX_PROXY_JOBS)):
                try:
                    keys = select_work(entries,observer.scheduled_entries(),now,limit)
                except Exception:
                    LOGGER.error('Automatic %s health state unavailable.',kind)
                    keys = []
                work.append((kind,observer,keys))
            LOGGER.info('Automatic health started endpoint=%d proxy=%d',len(work[0][2]),len(work[1][2]))
            for kind,observer,keys in work:
                for key in keys:
                    count = 0
                    try:
                        counts = observer.check(key,trigger='auto')
                        count = sum(counts.values())
                        result = 'success'
                    except (HealthError,ProxyHealthError) as error:
                        result = ('not_due' if error.code == 'not_due' else health_schedule.failure_result(error.code))
                    except KeyError:
                        result = 'conflict'  # Deleted after selection; no auxiliary entry recreated.
                    except Exception:
                        result = 'error'
                    LOGGER.info('Auto %s health subscription=%s nodes=%d result=%s',kind,key,count,result)
            return 0
    except LockBusyError:
        LOGGER.info('Automatic health already running.')
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Check due Fixed health jobs once, then exit.')
    parser.add_argument('--once',action='store_true',required=True)
    parser.add_argument('--state-dir',type=Path,default=Path('state'))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,format='%(message)s')
    def stop(_signal, _frame):
        LOGGER.info('Automatic health stopped.')
        raise SystemExit(0)  # Unwind existing probe cleanup and singleton contexts.
    previous = {signum:signal.signal(signum,stop) for signum in (signal.SIGTERM,signal.SIGINT)}
    try:
        for directory in (args.state_dir,args.state_dir/'fixed_subscriptions'):
            if directory.exists() or directory.is_symlink():
                if directory.is_symlink() or not directory.is_dir() or directory.stat().st_mode & 0o077:
                    raise StateError('Unsafe state directory.')
        return run_once(FixedSubscriptions(args.state_dir))
    except Exception:
        LOGGER.error('Automatic health critical state error. Inspect private state and restore a consistent backup.')
        return 1
    finally:
        for signum,handler in previous.items():
            signal.signal(signum,handler)


if __name__ == '__main__':
    raise SystemExit(main())
