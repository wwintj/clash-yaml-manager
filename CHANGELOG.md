# Changelog

## Unreleased

### Added

- 可配置有限 `SESSION_LIFETIME_DAYS`（預設 30、合法 1–3650 天），Cookie／簽章有效期一致、活動滑動續期，Runtime 顯示生效值；登出、密碼及 Secret Key 撤銷保持，瀏覽器可能縮短 Cookie 保存時間。
- Upload／Generated Output／Web Overlay Backup 各自支援 `timed`／`keep`，舊預設與 hours／days fallback 保留；`TEMP_LINK_LIFETIME_HOURS` 可獨立設定有限 `/t/` 授權，不改既有到期、撤銷、tombstone 或 Fixed lifecycle。
- Generate 草稿新增明確本機 `Keep draft until I clear it`，預設仍 30 天；Clear 不會被待執行 autosave 復活，僅保存 allowlist 欄位，明列節點 URL 的共享瀏覽器隱私與儲存失敗限制。
- 新增唯讀 Backup Audit、Manifest v1 Verifier、Offline Snapshot Writer、固定 allowlist 的 Collector 與私人 Trust Anchor Catalog；以有界 no-follow IO、來源 ownership／role、canonical digest、no-replace 發布及身份清理驗證明確離線範圍。`FULL_TREE` 僅表示輸入 representation，所有工具固定 `restore_proven=false`。

### Changed

- 已認證表單與 Parse／Diff AJAX 在明確操作前取得 same-origin、no-store fresh CSRF token；保留有限驗證與草稿，不背景 polling、重新認證或重送拒絕的 POST。
- Web timed cleanup 僅有界掃描固定目錄的安全普通 YAML，核對 no-follow／filesystem／inode／owner／hardlink；keep 不掃描，未知或不安全物件保留，不清理 state、Fixed cache 或 protected backups。

### Deployment

- 新版 direct／remote updater 共用 root 私人 Deployment Guard 與已驗證 FD，保護至 remote 最終 metadata；衝突返回 75，不可由普通環境字串跳過。歷史 updater、install/uninstall 與外部 writer 不自動受保護。
- 新增明確 opt-in verified Sidecar，**預設 OFF**；OPTIONAL／STRICT 需精確外部 writers quiet 聲明及真正 systemd/cgroup、ownership、來源與磁碟 gates。僅在 legacy state backup 後、auth migration 前串接 Collector → Writer → Verifier → Catalog；**Legacy Backup、venv 與人工 rollback 材料保留**。全域安全／未知 IO／ENOSPC 失敗阻擋；不確定發布保留，不自動 restore 或刪備份。僅合成驗收，production、完整 VPS consistency、Restore 尚未證明；歷史 macOS Verifier 拒絕碼差異仍為 `ROOT_CAUSE_UNKNOWN`。

### Fixed

- Sidecar 無效 mode、明確空字串／大小寫／空白變體或缺少精確 YES，在共同 guard 入場後、任何部署副作用前拒絕；Direct 與 remote no-op／歷史 child 同步檢查，保留原 75／78、channel／SHA／FD 與後段 quiet gate。
- `POST /process` 直接回傳 HTTP 400 驗證錯誤時，Generate YAML 導覽保持 `aria-current="page"`；其他導覽、驗證、redirect 與狀態碼不變。

## v1.7.0 - 2026-10-08

### Changed

- Simplify the login screen into a compact password-only sign-in experience with password-manager support, without changing authentication behavior or the authenticated interface.
- Simplify the authenticated application header by integrating the main navigation and removing static dashboard metadata, while preserving routes and account actions.
- Simplify authenticated success and error feedback by removing dashboard-style headings while preserving message semantics and accessibility.

## v1.6.0 - 2026-10-07

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
