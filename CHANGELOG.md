# Changelog

## Unreleased - Regression baseline and scoped P0 fixes

- Added isolated pytest coverage for parsers, YAML round trips, Flask flows, signed/short downloads, concurrent output and deployment script failure paths.
- Reject invalid ports, empty node names, malformed YAML structures and duplicate policy groups instead of silently discarding configuration. Preserve singly encoded VLESS WS paths and repair MATCH flag references.
- Block replacement when rules still target a removed node. Keep surviving group-list comments; publish complete private output files atomically without overwriting concurrent results.
- Remove raw parser/YAML exception content and user-supplied filenames from diagnostics. Create uploads/backups/outputs with private permissions from the start.
- Add Flask-WTF CSRF protection, POST-only logout, session reset on login/logout/password change and a 12-hour login session lifetime.
- Make ProxyFix opt-in with `TRUST_PROXY_HEADERS`; default new download URLs to the request scheme, preserving `DOWNLOAD_BASE_URL` and explicit scheme overrides. Reject malformed download tokens without a server error.
- Refuse destructive reinstall/in-place update, exclude `.env` and local environments from code copying, use unique remote staging directories, extend upgrade preflight/backups and report health-check failures with rollback guidance.
- Keep the default YAML and historical templates unchanged. Password hashes, multi-worker credential consistency, login rate limits and dedicated system user migration remain next-stage work; this release is not a complete security migration.

## v1.0.0 - Default YAML and Update Flow

Initial public release focused on one-command VPS deployment and Clash/Mihomo YAML node replacement.

### Added

- Web panel for uploading an existing Clash/Mihomo YAML and generating a cleaned replacement.
- Default YAML fallback at `defaults/default.yaml`, so a config can be generated without uploading a YAML file.
- Cleaned built-in default YAML with the expired `vmess` node removed.
- Batch node input using `国家代码|节点名称|节点链接`.
- `vmess://` and `vless://` parsing.
- Automatic country flag prefixing and country/region proxy group insertion.
- Optional special proxy groups for Netflix, YouTube, AI platforms, and Telegram.
- Change-password flow in the Web panel.
- Password storage via `APP_PASSWORD_B64`, allowing spaces, symbols, and non-ASCII characters.
- `install.sh` for one-command install.
- `update.sh` for upgrading code while preserving deployed configuration and runtime data.
- `uninstall.sh` for service cleanup and optional data backup.
- Compact `/s/...` YAML subscription links for Clash/Mihomo clients, while keeping older signed links compatible.
- Progress feedback when deleting temporary upload and output files.
- Built-in SVG favicon for the browser tab.

### Changed

- YAML upload is now optional; when omitted, the app uses `defaults/default.yaml`.
- README now puts one-command install, update, and uninstall first.
- Gunicorn systemd target fixed to `app:app`.

### Validation

- Python syntax check passed for `app.py`, `core/parser.py`, and `core/yaml_utils.py`.
- Default YAML was checked to ensure stale `redmi` / `vmess` references were removed.

### Contact

- wwintj@gmail.com
