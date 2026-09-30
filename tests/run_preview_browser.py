"""Opt-in browser integration: isolated Flask copy, no real account/runtime writes.

Requires Node with Playwright/Chromium installed (NODE_PATH may supply the module).
BOOTSTRAP_CSS_PATH may point to a cached copy of the page's Bootstrap 5.3.3 CSS.
Run with the project's Python environment: python tests/run_preview_browser.py.
"""
import argparse
import importlib.util
import logging
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading

from browser_source_fixture import external_source_server

from werkzeug.serving import make_server


def main():
    arguments = argparse.ArgumentParser()
    arguments.add_argument('--suite', choices=('all', 'preview', 'fixed', 'external', 'health', 'proxy', 'policy', 'health_policy', 'geoip', 'settings', 'https', 'notifications'), default='all')
    suite = arguments.parse_args().suite
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='clash-preview-browser-') as temporary:
        work = Path(temporary)
        for name in ('app.py', 'VERSION', 'mihomo-manifest.json'):
            shutil.copy2(root / name, work / name)
        for name in ('core', 'templates', 'static', 'defaults'):
            shutil.copytree(root / name, work / name, ignore=shutil.ignore_patterns('__pycache__'))
        password = secrets.token_urlsafe(24)
        os.environ.update(APP_PASSWORD=password, SECRET_KEY=secrets.token_hex(32))
        for key in ('APP_PASSWORD_B64', 'APP_PASSWORD_HASH', 'DOWNLOAD_BASE_URL',
                    'TRUST_PROXY_HEADERS', 'COOKIE_SECURE'):
            os.environ.pop(key, None)
        sys.path.insert(0, str(work))
        spec = importlib.util.spec_from_file_location('preview_test_app', work / 'app.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        logging.getLogger().setLevel(logging.WARNING)
        server = make_server('127.0.0.1', 0, module.app, threaded=True)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with external_source_server(module) as fixture_env:
                for script in ('test_preview_layout.cjs', 'test_fixed_browser.cjs', 'test_external_browser.cjs', 'test_health_browser.cjs', 'test_proxy_browser.cjs', 'test_policy_browser.cjs', 'test_health_policy_browser.cjs', 'test_geoip_browser.cjs', 'test_settings_browser.cjs', 'test_https_browser.cjs', 'test_notifications_browser.cjs'):
                    if suite != 'all' and script != ('test_preview_layout.cjs' if suite=='preview' else f'test_{suite}_browser.cjs'):
                        continue
                    subprocess.run(['node', str(root / 'tests' / script)], check=True,
                                   env=dict(os.environ, **fixture_env,
                                            PREVIEW_TEST_URL=f'http://127.0.0.1:{server.server_port}',
                                            PREVIEW_TEST_PASSWORD=password), timeout=180)
        finally:
            server.shutdown()
            worker.join(timeout=5)
            server.server_close()


if __name__ == '__main__':
    main()
