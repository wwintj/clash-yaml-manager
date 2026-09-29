# Changelog

## Unreleased

### Added
- Add opt-in Automatic Endpoint and Full Proxy Health checks with seven intervals, independent scheduling metadata and a bounded dedicated systemd health timer; retain manual checks in Automatic mode.
- Add optional, exactly pinned Mihomo v1.19.31 management for Linux amd64/arm64 and manual end-to-end HTTPS proxy checks of committed Fixed Subscription VMess/VLESS nodes, with global and per-subscription probe settings and independent Proxy/Endpoint observations.
- Add manual, Off-by-default TCP endpoint reachability checks for committed Fixed Subscription VMess/VLESS nodes, with connect latency and Unknown/Healthy/Suspect/Unhealthy observations in private auxiliary state.
- Schedule each remote Fixed Subscription source through a separate systemd timer with seven intervals, Off by default, fixed failure backoff and bounded refresh history; keep public URLs and last-good data available during provider failures.
- Merge ordered manual, remote URL and persistent uploaded sources in Fixed Subscriptions; import VMess/VLESS from Clash/Mihomo YAML, raw URI lists and Base64 lists with manual refresh, source controls and last-good cache status.
- Add authenticated Fixed Subscriptions management with persistent source configuration and custom base YAML, stable readable bearer URLs, edit, copy, disable/enable, confirmed link regeneration and deletion.
- Keep fixed output outside temporary retention, record node/group/rule counts and shared throttled last access, and preserve existing V2/legacy subscriptions and temporary links.

### Changed
- Read health schema v1 as v2 in memory without changing existing Off/Manual modes; separate scheduler backoff from node observations and preserve newer settings/results during busy or revision races.
- Select explicit pinned Mihomo amd64 v1/v2/v3 builds from the intersection of Linux-exposed CPU capabilities, with verified execution-only fallback and legacy generic v3 metadata recognition; preserve the arm64 asset and ordinary update behavior.
- Keep managed Mihomo binaries and metadata across ordinary project updates; leave proxy checks Off after upgrades and never alter Fixed YAML, URL, groups or policy based on health results.
- Keep unhealthy nodes in generated YAML and proxy groups; preserve health on name-only edits, reset identity when connection configuration changes, and discard probe results when the Fixed revision changes during a check.
- Normalize fixed registry v1/v2 to v3 in memory with existing schedules Off; persist on successful management or required scheduler mutations while preserving URLs, manual settings and complete revision files.
- Fetch and generate outside the registry lock, then reject stale commits after concurrent management changes; preserve prior configuration, caches and output on failed source updates.

### Security
- Verify pinned archive and executable hashes, architecture and exact version before installing a root-owned binary; run probes in private short-lived directories through a secret-protected localhost controller with bounded batches, concurrency and process cleanup.
- Restrict probe targets to public HTTPS with all locally resolved addresses safe, store only opaque health metadata and sanitized errors, and reject stale revisions or concurrent checks without penalizing nodes.
- Validate every resolved node address before pinned numeric TCP connection, block private/mixed DNS answers, bound probes to three seconds, sixteen concurrent workers and 256 nodes, and keep endpoints, credentials and fingerprints out of logs and health UI.
- Bound automatic work, use a nonblocking shared worker lock, reject stale candidates and keep refresh history/journal free of source credentials and raw exceptions.
- Validate each remote URL/DNS/redirect, pin connections to approved public IPs, verify HTTPS hostnames/system CAs, ignore proxy environment settings, and bound DNS/connect/read time and payload size; keep remote credentials out of errors and browser storage.
- Commit fixed configuration and generated YAML together through private candidate files and an atomic registry pointer under a shared file lock; preserve the previous subscription on failed saves.
- Use 128-bit random tokens, permanent token-hash tombstones, constant-time authorization, private state permissions, strict schema/path checks and fixed-URL access-log redaction.

### Deployment
- Manage separate health oneshot/timer units on install, update and uninstall, preserve health state, stop writers before backup, and recover the health unit pair and prior timer flags on setup failure.
- Install and enable refresh oneshot/timer units, back up all existing units on upgrade, stop refresh writers before state backup/code replacement, and remove units on uninstall while preserving retained state.

## v1.1.1 - 2026-09-28

### Deployment
- Make the 30-second deployment readiness timeout explicit so release validation passes across ShellCheck versions without changing runtime behavior.

## v1.1.0 - 2026-09-28

### Added
- Add explicit `--channel main` installation/update for test VPS deployments, pin downloads to resolved commit SHAs, and keep stable as the default without fallback.
- Record atomic installation metadata and show development build identity; compare main SHAs and protect returns to same/older Stable releases.
- Save browser-local generation drafts for 30 days, including auxiliary rows, policies, source choice and manual corrections; restore after refresh/login and provide confirmed Clear Draft.
- Parse mixed COUNTRY|NAME|URI, NAME|URI and URI input with editable preview and latest-input parsing on Generate.
- Share a complete 249-region ISO catalog across detection and searchable selectors; allow Unknown warnings in a dynamic other-nodes group.
- Issue 16-character random temporary links with atomic shared metadata, independent expiry and permanent ID tombstones.

### Changed
- Extend sessions to 30 days with sliding renewal while preserving CSRF and global password-change invalidation.
- Default uploads to one hour, outputs to 24 hours and cleanup to hourly; keep backups separate and legacy day-based settings compatible.
- Display generation expiry and responsive node previews while retaining legacy subscription routes.

### Fixed
- Keep Parse Preview columns stable with wrapped warnings, normal-height action buttons and desktop/tablet/mobile layouts.
- Prevent country-search and auxiliary-input Enter keys from implicitly generating YAML; only the identified Generate submitter may proceed.
- Recover rejected CSRF forms through a fresh GET and a one-time notice, preserving browser drafts and the finite token lifetime; return a recoverable JSON error for node parsing.
- Preserve input through failed submissions and require reselecting Custom YAML after refresh; never save uploaded file contents in drafts.
- Submit auxiliary nodes separately so repeated generation does not append duplicate rows to Batch Nodes.

### Deployment
- Disable Gunicorn's unused control socket for the nologin service account; require Gunicorn ≥25.1.0 and its Python ≥3.10 runtime.
- Share install/update readiness checks with a 30-second budget, one-second retry interval and public `/healthz`; require HTTP 200 and systemd active before reporting completion. On failure, return nonzero, show service diagnostics and retain upgrade backups with manual rollback guidance.

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
