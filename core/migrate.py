"""Root-run credential migration, also independently testable without systemd."""
import argparse
from pathlib import Path
import sys

from core.envfile import records, values
from core.security import AuthStore, CREDENTIAL_KEYS
from core.state import StateError, atomic_write


def migrate_auth(env_path, state_dir):
    env_path = Path(env_path)
    original = env_path.read_bytes()
    text = original.decode('utf-8')
    parsed = list(records(text))
    store = AuthStore(state_dir)
    # First commit auth state durably. If either operation fails, never remove
    # legacy credentials before there is a valid replacement. Retry is idempotent.
    store.initialize(values(text))
    cleaned = ''.join(raw for key, _, raw in parsed if key not in CREDENTIAL_KEYS).encode('utf-8')
    if cleaned != original:
        atomic_write(env_path, cleaned)
    return store.read()


def main():
    arguments = argparse.ArgumentParser(description='Migrate credentials into private shared auth state.')
    arguments.add_argument('--env-file', required=True)
    arguments.add_argument('--state-dir', required=True)
    args = arguments.parse_args()
    try:
        migrate_auth(args.env_file, args.state_dir)
    except (StateError, OSError, ValueError):
        sys.exit('认证迁移失败：旧凭据未提前删除；请检查配置、磁盘空间及权限后重试。')
    print('认证迁移完成。')


if __name__ == '__main__':
    main()
