# Changelog

## Unreleased

### Changed

- Simplify the built-in YAML template with dynamic country groups and place real nodes first in the Default primary selector, followed by only the country groups actually present.

### Fixed

- Update README and current Fixed Subscriptions documentation to reflect the v1.5.0 Stable management experience, and require README narrative review during feature completion and release audits.

## v1.5.0 - 2026-10-07

### Changed

- Improve Fixed Subscriptions management with search, status filtering, sorting, compact source/health summaries, and clearer responsive actions.

## v1.4.1 - 2026-10-04

### Fixed

- Correct post-v1.4.0 documentation that still described Hysteria2 as main-only or unreleased.

## v1.4.0 - 2026-10-04

### Added

- Add Hysteria2 / HY2 inputs to Generate, Fixed Subscriptions and External Raw/Base64/Clash sources, with strict pinned-Mihomo fields and credential-safe previews.

## v1.3.2 - 2026-10-04

### Fixed

- Prevent Linux access-time updates from falsely failing the unsafe-auth-object release audit; object identity, structure and symlink targets remain checked.

### Deployment

- Add manual Ubuntu release-candidate validation before stable publication, using the same full checks through a validation-only command.

## v1.3.1 - 2026-10-03

### Changed

- Unify Web UI labels, help and validation messages in English.
- Share typography, controls and responsive layouts across Login, Generate, Fixed Subscriptions and Settings.
- Make navigation, tabs, buttons and forms more compact, with clearer action hierarchy and less panel whitespace.

### Fixed

- Improve button text alignment, keyboard focus, form labels and table/code scrolling on narrow screens.
- Correct Endpoint automatic interval visibility and prevent action buttons from stretching.

## v1.3.0 - 2026-10-02

### Added
- Preview complete YAML changes before generating, using current inputs and the same output pipeline; private previews do not save files or subscription links.
- Add optional Generate Merge mode to preserve source nodes and append submitted nodes, with explicit name-conflict errors and saved draft mode; Replace remains the default and Fixed remains Replace only.
- Accept Trojan TCP/WebSocket and Shadowsocks inputs in Batch, Auxiliary, Parse, Fixed and External Raw/Base64/Clash sources, including automatic refresh. Preserve passwords; reject unsupported transports, plugins and URI options.

### Changed
- Align current feature manuals and README with the v1.3 release scope while retaining historical acceptance reports.

### Fixed
- Keep long generated filenames within the mobile layout without changing download behavior.
- Use a protocol-neutral message when an external import has no supported nodes.

### Security
- Hide Trojan/Shadowsocks credentials in ordinary previews and Health observations, and keep private YAML values out of parser warning output during Generate, Fixed imports, Diff and Health.

## v1.2.1 - 2026-10-01

### Fixed
- Make the Settings runtime build-identity regression derive its expected development label from the current VERSION, so release validation remains version-agnostic after a minor-version bump.

## v1.2.0 - 2026-09-30

### Added
- Add persistent Fixed Subscriptions with custom/default base YAML, stable bearer URLs, source editing and explicit enable, disable, regenerate and delete controls.
- Merge ordered Manual, Remote URL and Uploaded sources; import VMess/VLESS from Clash YAML, raw and Base64 lists with last-good cache and manual refresh.
- Add Off-by-default automatic source refresh with seven intervals, bounded history, failure backoff and an independent systemd worker.
- Add independent Off/Manual/Automatic Endpoint TCP and Full Proxy HTTPS observations, failure thresholds, per-subscription settings and a bounded health scheduler.
- Add optional SSH-managed Mihomo v1.19.31 for Linux amd64/arm64; select verified amd64 v1/v2/v3 artifacts from CPU capabilities with execution-only fallback.
- Add Country and selected Special group policies: Preserve (default), Select, URL-Test, Fallback and round-robin Load-Balance.
- Add Off-by-default Health-aware Policy for fresh confirmed Proxy Unhealthy candidates, with per-group minimums and fail-open behavior.
- Add Off-by-default offline GeoIP Country Assist with administrator-supplied MMDB, public literal IP lookup and Manual/Name priority.
- Add modular authenticated Settings for Overview, GeoIP, global Health defaults, read-only Runtime and Notifications.
- Add an optional SSH/root Nginx HTTPS assistant with Certbot Webroot, private transactions, ownership/drift checks, disable and rollback.
- Add Off-by-default Telegram alerts for automatic incident/recovery transitions, with masked private credentials and explicit test/removal actions.

### Changed
- Read supported Fixed v1–v5 as v6 defaults in memory and Health v1 as v2 without read-time schema promotion, URL rotation or automatic opt-in.
- Preserve Fixed policies, country mode, caches and top-level nodes across refresh and health reconciliation; keep name-independent health identities and discard stale results.
- Reconcile enabled policies after committed Proxy observations and bounded periodic scans; unchanged YAML does not create a revision.
- Centralize global Proxy defaults in Settings while retaining the Fixed compatibility route and per-subscription overrides.
- Align current manuals, backup/rollback guidance and release validation documentation with the integrated feature set; retain historical acceptance evidence.

### Fixed
- Reject FIFO, directory and symlink JSON state before reading so corrupt local objects cannot block authentication, temporary access or update preflight; fail closed on broken login-limiter state links without rewriting them.

### Security
- Commit Fixed revisions/cache/config through a private atomic registry pointer; use 128-bit bearers, permanent token-hash tombstones, constant-time authorization and Fixed access-log redaction.
- Validate source URLs, every DNS answer and redirect, pin numeric public addresses, verify TLS and bound time/body sizes without environment proxies; keep provider/node secrets out of operational errors and history.
- Keep network/probe work outside authoritative locks, reject optimistic conflicts and bound Endpoint/Proxy jobs with private temporary configs, secret-protected loopback controllers and process cleanup.
- Restrict managed automatic groups to their generated nodes; optional health filtering preserves top-level/manual nodes and fails open when observations or candidates are insufficient.
- Redact temporary, legacy and signed subscription request logs alongside Fixed bearers; disable inherited access logs in newly generated managed Nginx server blocks. Existing integrations retain their configuration until reviewed over SSH.
- Keep Settings GET local-only, GeoIP offline and notification state strictly private; sanitize alerts, bound direct verified Telegram delivery and isolate delivery failures/configuration races without a queue or retries.

### Deployment
- Preserve independent state, managed Mihomo artifacts, operator defaults and HTTPS configuration through ordinary updates; absent optional features remain Off, with no automatic Mihomo/GeoIP/Telegram/Certbot work.
- Manage separate source and health unit pairs, stop writers before state backup and recover previous health units/timer flags on setup failure.
- Validate public/loopback APP_BIND_HOST, retain direct HTTP defaults and detach only verified project Nginx integration on uninstall while preserving certificates and unrelated users/files.

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
