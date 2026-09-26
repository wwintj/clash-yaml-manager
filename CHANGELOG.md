# Changelog

## Unreleased

## v1.0.2 - 2026-09-26

### Deployment
- Validate the authoritative remote annotated tag object when GitHub Actions checkout flattens its local tag reference to a commit; still reject genuinely lightweight remote tags.
- Preserve existing tags and Releases during verification, with regression coverage for the observed runner checkout behavior.

## v1.0.1 - 2026-09-26

### Added
- Establish a 178-test Phase 1/2 regression baseline and extend it with release, lifecycle and non-empty password coverage.
- Add a single VERSION source, a small Web version footer, and a release orchestrator that validates, updates metadata, creates annotated tags, pushes and verifies GitHub Releases.
- Add tag-triggered GitHub Actions release validation using the built-in GITHUB_TOKEN.

### Fixed
- Reject malformed YAML structures, duplicate groups and dangling rule targets; preserve surviving comments and singly encoded VLESS paths, validate ports and atomically publish concurrent YAML outputs.
- Keep administrator password input unchanged, including leading/trailing spaces; reject only truly empty new passwords and mismatched confirmation.
- Remove the public contact email from current documentation and prevent its return in README.

### Security
- Protect forms with CSRF, use POST-only logout, bound session lifetime, and make proxy-header trust opt-in.
- Replace reversible password storage with shared Werkzeug hashes, atomic credential migration, immediate multi-worker password consistency and global session invalidation after password changes.
- Add cross-worker IP login limits with HTTP 429, Retry-After, expiry and pruning.
- Run the service as a dedicated clashyaml account with root-owned read-only application code and private runtime directories.
- Use unique 128-bit output identities and V2 subscription HMACs; retain legacy-file links without allowing weak tokens to authorize new files.

### Deployment
- Preserve deployed configuration, default YAML and runtime/auth state during upgrades; add preflight, backups, health checks and rollback guidance.
- Install and update exact published stable tags through standalone remote entrypoints, with version pinning, no-op updates and explicit downgrade opt-in; never fall back to main.
- Validate downloaded archive paths and VERSION before running scripts; retain the installed version's one-command uninstaller and safe account/data handling.
- Automate bounded README metadata and dated CHANGELOG updates; keep stable releases immutable and verify publication after pushing.

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
