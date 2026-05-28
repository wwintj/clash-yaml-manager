# Changelog

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

### Changed

- YAML upload is now optional; when omitted, the app uses `defaults/default.yaml`.
- README now puts one-command install, update, and uninstall first.
- Gunicorn systemd target fixed to `app:app`.

### Validation

- Python syntax check passed for `app.py`, `core/parser.py`, and `core/yaml_utils.py`.
- Default YAML was checked to ensure stale `redmi` / `vmess` references were removed.

### Contact

- wwintj@gmail.com
