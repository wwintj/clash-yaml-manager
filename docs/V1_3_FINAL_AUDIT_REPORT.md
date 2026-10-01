# v1.3.0 Feature Freeze / Final Audit

Audit date: 2026-10-01. This is a controlled Release Candidate readiness audit,
not a release. VERSION and Latest Stable remain **1.2.1 / v1.2.1**.

## Identity and evidence

| Item | Actual evidence |
| --- | --- |
| START HEAD | `fdee4843511f656b14e032d5ac7e5bf72bc6656f` |
| Previous Stable v1.2.1 peeled commit | `f62bf50721e3ac00d5d2a2a9f784ede4b79b49cf` |
| Previous annotated tag object | `457787de1ee12d441605709bc59dc8d2e84737be` |
| END HEAD, audited source and tests | `a9e759fae75af40ac41ba3591236e9a337f5ada3` |
| END HEAD, report publication | The commit containing this file, resolved with `git log -1 --format=%H -- docs/V1_3_FINAL_AUDIT_REPORT.md`; its exact SHA is returned in the audit task's final response. A committed report cannot embed its own SHA. |
| Audit commit 1 | `16600ee239e7a29804f4c284dc8c7ddde8969579` — `fix: close private YAML warning leaks for v1.3 freeze` |
| Audit commit 2 | `fac416b286e384e0161b493c1d0e6c8089c6bba1` — `test: complete v1.3 mixed refresh transaction audit` |
| Audit commit 3 | `a9e759fae75af40ac41ba3591236e9a337f5ada3` — `test: ignore filesystem access time in read-only state checks` |
| Audit commit 4 | Report publication commit above — `docs: record v1.3 final audit and feature freeze` |
| Branch / remote | `main`; HEAD = origin/main = actual GitHub main before each dry-run |
| Repository | [wwintj/clash-yaml-manager](https://github.com/wwintj/clash-yaml-manager) |
| Stable Release | [v1.2.1](https://github.com/wwintj/clash-yaml-manager/releases/tag/v1.2.1) |

START checks included `git fetch origin`, branch, clean status, local HEAD,
origin/main, actual `git ls-remote`, tags and GitHub Releases. No baseline code
was edited until the complete baseline passed. The four historical scope reports
and `docs/FINAL_AUDIT_REPORT.md` retain their original facts. No default YAML,
runtime state, origin, history, stable tag or Release was changed.

## Gates and validation limits

| Gate | Result |
| --- | --- |
| BASELINE PYTEST, before edits | **2615 passed in 480.32s (8:00), 0 failed** |
| Focused privacy / genuine Stable upgrade regression | 11 passed, 582 deselected |
| New freeze-specific regression cases | 41 cases; together with source-parser cases: 81 passed |
| Combined Diff / lifecycle / audit regression | 299 passed in 220.45s, 0 failed |
| State-reader regression after atime fix | 13 passed; forced stale access time retains write/permission/inode checks |
| FINAL PYTEST, real main, full suite | **2658 passed in 356.94s (5:56), 0 failed** |
| TEMP V1.3.0 FULL PYTEST | **2658 passed in 355.58s (5:55), 0 failed** |
| Browser | **15 suites PASS**, all existing suites retained |
| Python compileall | PASS: app.py, core, scripts, tests |
| Python 3.10 syntax | PASS: 99 Python files parsed with AST feature_version=(3,10) |
| Node syntax | PASS: 19 JavaScript/CJS files |
| Dependencies | `pip check`: no broken requirements |
| Shell syntax / ShellCheck | All 8 files PASS: bash -n, ShellCheck 0.9.0 and 0.11.0 |
| Bootstrap synchronization | `scripts/build_bootstraps.py --check`: PASS |
| Diff whitespace | `git diff --check`: PASS |
| Default YAML | SHA256 unchanged; 10,410-rule round trip PASS |
| Controlled lifecycle | Fresh install / update / backup / both uninstall choices PASS; additional docs copy checks: 2 passed |
| Minor release preflight / dry-run | **PASS / PASS**, current 1.2.1, proposed 1.3.0, proposed tag v1.3.0 |
| Dry-run boundary | Tracked byte hashes, HEAD, local refs, remote tags and all Release publication metadata unchanged |
| Default remote install / update resolver | Both still resolve **v1.2.1**, exact Stable peeled commit above |

Full tests ran with Python 3.12.14; browser tooling used Node v24.18.0 and
Chromium/Playwright against a disposable local Flask application. The Python 3.10
check is syntax compatibility, not a claim of a full 3.10 runtime execution.
Controlled system commands, accounts and network responses use temporary paths
and doubles; the developer machine's /opt, systemd and real accounts were untouched.

Browser suites: Preview layout, Fixed, External, Endpoint Health, Proxy Health,
Policy, Health-aware Policy, GeoIP, Settings, HTTPS, Notifications, YAML Diff,
Merge, Trojan and Shadowsocks. All include desktop/mobile acceptance where
applicable; Diff/Merge/Trojan/SS explicitly passed at **1440 and 390**. Original
Preview breakpoints **1440, 1024, 390, 1200, 1199, 768, 767** remain covered.
Password redaction, latest input, exact download/diff, text XSS, draft behavior,
stale-response handling and no overflow passed.

## Actual v1.2.1 → main scope and SemVer

The actual Stable-to-START diff contains **43 files, 3974 insertions and 110
deletions**, across ten commits (Diff: 6ce1200 / 4e2d08a; Merge: dc2b0d1 /
8d5ba5f; Trojan: bb7bd17 / ed968cd / 76f4873; SS: 32c23ce / 71b990c / fdee484).
The audit adds only the privacy correction, neutral source-error text, documentation cleanup and regression
evidence. The final report is a documentation-only commit.

| Category | Reviewed changes |
| --- | --- |
| Added | Authenticated offline Full YAML Diff Preview; explicit Generate Merge; Trojan input/import; Shadowsocks input/import |
| Changed | Shared in-memory transform/serializer; explicit mode validation and draft mode; read-only GeoIP snapshots for Preview; parser/import/Health admission for the four input protocols |
| Fixed | Exact line endings and final-newline diff behavior; long filename mobile wrapping; byte/golden regressions and preserved deployment state |
| Security | Preview auth/CSRF/cache/referrer/XSS boundaries and resource limits; private source warnings; Trojan/SS credential redaction; strict URI/query/plugin rejection |
| Deployment | No deployment architecture or release workflow change; existing copying includes the two new Python modules and docs |

No Fixed Merge, new scheduler, settings/provider feature, extra protocol or
unrelated refactor was added. Fixed/auth/health schemas, timer/backoff contracts,
Stable install/update resolution and default YAML are unchanged. The new input
support is additive and Replace remains compatible by default. The supported
SemVer recommendation is therefore **v1.3.0 (minor)**; real VERSION is not bumped.

## Protocol capability matrix

`PASS` below means accepted and verified through controlled tests. It does not
mean a real external proxy handshake or real VPS acceptance. All columns describe
new input/import candidates, not arbitrary preserved source proxy types.

| Capability | VMess | VLESS | Trojan | Shadowsocks |
| --- | --- | --- | --- | --- |
| Generate Batch | PASS | PASS | PASS | PASS |
| Auxiliary input | PASS | PASS | PASS | PASS |
| Parse Preview / edits | PASS | PASS | PASS | PASS |
| Fixed Manual | PASS | PASS | PASS | PASS |
| External Raw | PASS | PASS | PASS | PASS |
| External Base64 | PASS | PASS | PASS | PASS |
| External Clash / Mihomo YAML | PASS | PASS | PASS | PASS |
| External Auto detection | PASS | PASS | PASS | PASS |
| Automatic refresh | PASS | PASS | PASS | PASS |
| Generate Replace | PASS | PASS | PASS | PASS |
| Generate Merge append | PASS | PASS | PASS | PASS |
| Exact YAML Diff | PASS | PASS | PASS | PASS |
| Policy candidates | PASS | PASS | PASS | PASS |
| Country / offline GeoIP | PASS | PASS | PASS | PASS |
| Endpoint Health admission | PASS (TCP endpoint only) | PASS (TCP endpoint only) | PASS (TCP endpoint only) | PASS (TCP endpoint only) |
| Full Proxy Health config / controlled observation | PASS | PASS | PASS | PASS |

Fixed remains **Replace only**. Merge preserves existing Trojan, SS, Hysteria2,
WireGuard and unknown proxy mappings. Preservation does not enable Hysteria2,
TUIC, WireGuard, SSR, SOCKS or HTTP URI/import input. Endpoint reachability is
not protocol validation. A Full Proxy config can preserve an SS cipher string;
that is not a claim that every cipher is usable by the managed engine.

## Protocol and dispatch review

**VMess / VLESS:** the AST of `parse_vmess_link` and `parse_vless_link` is identical
to the actual v1.2.1 tagged source, now enforced by regression tests. Existing
URI decoding, host/port/UUID, transports, TLS/Reality, WS, country/name,
public errors and the pre-Trojan/pre-SS mapping/preview/YAML byte goldens all
pass. Helpers extended for new protocols did not change those goldens.

**Trojan:** once-only percent decoding retains nonempty passwords, surrounding
spaces, Unicode and encoded delimiters. Bracketed IPv6, strict port/host,
TLS semantics, sni/peer agreement, TCP and WS are covered. Unsupported transport,
unknown/duplicate/conflicting query parameters and command/file/plugin fields
fail with fixed safe errors. The Mihomo Trojan adapter uses TLS intrinsically,
with SNI defaulting to the server; no fabricated `tls`/UUID field is required.
This was checked against the pinned [Mihomo adapter](https://raw.githubusercontent.com/MetaCubeX/mihomo/v1.19.31/adapter/outbound/trojan.go)
and [Trojan transport](https://raw.githubusercontent.com/MetaCubeX/mihomo/v1.19.31/transport/trojan/trojan.go).
Raw/Base64/Clash imports, controlled Health config and credential redaction pass.

**Shadowsocks:** legacy Base64 full authority, SIP002 Base64 userinfo and plain
userinfo are tested independently. Standard/URL-safe alphabets, percent-encoded
Base64, omitted padding, IPv4/domain/bracketed IPv6 and Unicode pass. Tests
preserve password `@`, `:`, `/`, spaces, tabs/newlines, Unicode and literal
percent sequences without delimiter corruption or double decoding. Cipher and
password are nonempty strings, preserved verbatim without a cipher whitelist
or password complexity rule. Plain Clash imports retain bounded unknown
non-plugin fields. This matches the representation reviewed in [SIP002](https://shadowsocks.org/doc/sip002.html)
and the pinned [Mihomo SS adapter](https://raw.githubusercontent.com/MetaCubeX/mihomo/v1.19.31/adapter/outbound/shadowsocks.go);
actual engine/cipher operation remains part of deferred real acceptance.

**Plugin boundary:** plugin, plugin options, obfs, simple-obfs, v2ray-plugin and
other SIP003-like options are explicitly unsupported, never silently ignored.
All SS URI queries are rejected, including empty queries and escaped/case
variants. Plugin mappings in Clash imports are rejected. No accepted parser
path invokes a plugin, command, binary or path.

**Dispatch:** the existing exact lowercase protocol dispatch now covers exactly
vmess/vless/trojan/ss. New audit tests reject uppercase, partial separator,
percent-encoded separator and nested HTTPS scheme confusion for all four.
No global parser state or shared credential buffer was introduced; no framework
refactor was performed.

Evidence: `test_parser.py`, `test_trojan_protocol.py`, `test_ss_protocol.py`,
`test_trojan_integration.py`, `test_ss_integration.py`, `test_v13_audit.py`.

## External Sources, refresh and Fixed state

Raw/Base64/Clash/Auto import continues to enforce **10 MiB**, strict UTF-8,
standard/URL-safe Base64 with controlled padding, safe YAML, depth **32**, item
budget **100,000**, cycles, non-string keys, object tags and nonfinite numbers.
Final-name collisions are rejected; unsupported proxy counts remain explicit.
Accepted new protocols do not relax those bounds. Parser work stays offline.

Four-protocol mixed refresh succeeds through the existing Fixed source pipeline.
New regression tests exercise unsupported protocol, invalid plugin, parse error
and network failure after a successful mixed refresh, retaining exact last-good
YAML/cache and stable URL with the original 300s initial backoff. Eight additional direct mixed-input transaction cases reuse the existing
commit-failure and concurrent-operation tests, including both sides of a failed
cache/registry publication and all six concurrent operations. Existing
transaction tests also cover no-cache
failure, generation failure, revision conflicts and stale candidates.

Failure status/history can legitimately commit a metadata revision while the
last-good content remains unchanged. The preservation requirement does not
mean suppressing failure metadata. No scheduler, interval, backoff, work budget,
worker singleton or registry-lock semantics changed.

Fixed registry remains **v6**. New explicit v1–v6 cases prove historical legal
registries can be read/resolved without byte rewrites, schema promotion or
token/URL/revision rotation. A legal mutation promotes to v6 and preserves
identity/content. Existing source ordering/cache, policy, health-policy and
country-detection migrations remain covered; Trojan/SS add no schema migration.

Evidence: `test_source_parser.py`, `test_external_sources.py`,
`test_auto_refresh.py`, `test_fixed_subscriptions.py`, `test_health_policy.py`,
`test_geoip_lifecycle.py`, mixed integration suites and `test_v13_audit.py`.

## Replace, Merge and exact Diff

**Replace** remains the default when mode is omitted. Historical byte goldens
cover old proxy removal, group cleanup, removed-rule target guard, counts,
backup, temporary link, download and redirect behavior. Explicit Replace and
implicit mode preserve the same contract. Invalid/duplicate mode is rejected.

**Merge** keeps existing proxy objects and order, comments, quotes, anchors,
unknown fields and arbitrary source types, then appends submitted nodes in
order. Node/group collisions and invalid references fail explicitly. It never
silently overwrites, renames or deduplicates equivalent connections. Source
rules retain valid old targets. Managed policy groups are rebuilt only under
the existing explicit automatic-policy contract; Preserve retains memberships.

**Diff** uses the same parser, `transform_yaml_config` and serializer as Generate;
no second protocol transform or Merge implementation exists. The generated side
of the unified diff is compared to actual downloaded Generate bytes for mixed
four-protocol input, Batch/Aux, default/custom source, Replace/Merge,
Policy/GeoIP and line-ending/final-newline cases.

Preview does not create output, backup, temporary link or mutate business,
Fixed, Health or notification state. Repeated read-only snapshots, network/DNS/
subprocess guards, busy/unsafe GeoIP locks and concurrency tests pass.
Preview requires login, **POST**, **CSRF**, **no-store**, **no-referrer**; browser
content uses textContent, with script/HTML payloads covered. It uses latest
inputs, does not persist diff content in browser drafts and rejects stale replies.

| Diff resource | Unchanged limit |
| --- | --- |
| Source / result | 2 MiB each |
| Source / result lines | 20,000 |
| Submitted nodes | 512 |
| Source groups | 256 |
| Complete diff | 512 KiB |
| JSON / form | 2 MiB |

Over-limit previews are explicitly refused while normal Generate remains
available. The audit did not raise any limit.

Evidence: `test_merge_mode.py`, `test_yaml_diff.py`, all protocol integration
suites and the corresponding four browser suites.

## Health, Policy and GeoIP

Endpoint Health admits the four protocols and uses only server/port for public
TCP endpoint probing. Full Proxy Health receives complete private Mihomo config
for the four protocols through the unchanged managed worker path. Public
observations/history retain only the existing schema; passwords, UUIDs and full
URIs are absent. New four-protocol extraction and warning-privacy assertions
pass; no protocol-specific status schema, probe algorithm or engine version
was added by this audit.

Preserve, Select, URL-Test, Fallback and Load-Balance treat all accepted protocols
as ordinary candidates, with no new `if protocol == ...` policy branch. Existing
health-aware filtering remains Fixed-specific; freshness, suspect handling,
manual/top-level preservation, exclusion, per-group fail-open and recovery pass.

Country precedence remains **Manual > Name > offline GeoIP > Unknown**. GeoIP
looks up literal public IPs only: no DNS, remote lookup or automatic download.
Preview's read-only snapshots do not create locks, chmod files or write state;
missing/busy/unsafe locks fail open consistently with the existing contract.

Evidence: `test_node_health.py`, `test_proxy_health.py`,
`test_auto_health.py`, `test_policy_engine.py`, `test_health_policy.py`,
`test_geoip.py`, `test_geoip_lifecycle.py` and `test_yaml_diff.py`.

## Auth and actual route inventory

The actual Flask application has **30 rules / 29 endpoints** (source_action has
two URL rules). GET includes Flask's implicit HEAD/OPTIONS where applicable;
those implicit methods do not bypass the route's authorization. The complete
inventory is checked by `test_complete_route_inventory_auth_and_csrf_boundaries`.

| Route | Methods | Boundary |
| --- | --- | --- |
| `/static/<path:filename>` | GET | Public GET |
| `/healthz` | GET | Public GET |
| `/` | GET | Public login page; authenticated view after login |
| `/login` | POST | Public POST + CSRF + rate limit |
| `/logout` | POST | Own session POST + CSRF |
| `/change-password` | POST | Authenticated; POST requires CSRF |
| `/parse-nodes` | POST | Authenticated; POST requires CSRF |
| `/api/preview-yaml-diff` | POST | Authenticated; POST requires CSRF |
| `/process` | POST | Authenticated; POST requires CSRF |
| `/t/<short_id>` | GET | Bearer GET |
| `/download/<path:filename>` | GET | Authenticated session or valid bearer GET |
| `/sub/<token>/<path:filename>` | GET | Authenticated session or valid bearer GET |
| `/s/<slug>` | GET | Bearer GET |
| `/delete-temp` | POST | Authenticated; POST requires CSRF |
| `/settings` | GET | Authenticated; POST requires CSRF |
| `/settings/health/proxy-defaults` | POST | Authenticated; POST requires CSRF |
| `/settings/upload` | POST | Authenticated; POST requires CSRF |
| `/settings/remove` | POST | Authenticated; POST requires CSRF |
| `/settings/notifications` | POST | Authenticated; POST requires CSRF |
| `/settings/notifications/test` | POST | Authenticated; POST requires CSRF |
| `/settings/notifications/remove` | POST | Authenticated; POST requires CSRF |
| `/fixed-subscriptions` | GET | Authenticated; POST requires CSRF |
| `/fixed-subscriptions/new` | GET, POST | Authenticated; POST requires CSRF |
| `/fixed-subscriptions/<key>/edit` | GET, POST | Authenticated; POST requires CSRF |
| `/fixed-subscriptions/<key>/health/<operation>` | POST | Authenticated; POST requires CSRF |
| `/fixed-subscriptions/proxy-health/defaults` | POST | Authenticated; POST requires CSRF |
| `/fixed-subscriptions/<key>/proxy-health/<operation>` | POST | Authenticated; POST requires CSRF |
| `/fixed-subscriptions/<key>/sources/<identifier>/<operation>` | POST | Authenticated; POST requires CSRF |
| `/fixed-subscriptions/<key>/sources/refresh-all` | POST | Authenticated; POST requires CSRF |
| `/fixed-subscriptions/<key>/<action>` | POST | Authenticated; POST requires CSRF |

`/api/preview-yaml-diff` is authenticated POST-only with CSRF, private JSON
errors, no-store/no-referrer; `/process` also requires authenticated POST and
CSRF. There is no newly public management endpoint. Login is rate-limited;
password policy is nonempty only, preserving all characters. Download paths,
bearer validation, session revocation and redacted request logging remain covered.

## Secrets, warnings, locks and concurrency

A metadata-only scan of tracked source/docs/fixtures found 117 node-URI syntax
matches, 51 UUID matches, 2 Telegram-token-shaped fixtures, 16 password literals,
5 signing-key patterns, 12 Basic-auth URL cases and 80 email-shaped strings.
Manual classification found examples, synthetic reserved domains/test-only
values, token-detection code and deliberate hostile fixtures, not operational
credentials or private provider URLs. Matches are candidate counts, not a claim
that every pattern is a secret. Real values were not printed. Removed contact
email display was not reintroduced.

Ordinary Parse and public logs/errors/Health/Notifications are separately tested
for Trojan/SS passwords, UUID and full URI redaction. Exact YAML Diff necessarily
contains private YAML and is deliberately restricted to authenticated,
non-cacheable, non-persisted display.

**HIGH H-01** was reproduced: ordinary committed YAML loading could emit a
ruamel duplicate-anchor warning containing a private anchor name, or a YAML 1.1
float warning containing a private scalar. Health's raw safe loader could also
emit the float warning. Diff already had instance-private suppression.
The fix shares that exact existing engine with Generate/Fixed loaders and uses
the existing private safe loader for Health. It does not change global warning
filters or ruamel's shared constructor registry. Concurrent regression tests
prove the unrelated raw engine still warns, application loaders stay private,
scalar meaning/serialized bytes agree and the original constructor stays intact.

Existing registry/state locks, worker singleton locks, fetch-outside-lock and
revision rechecks remain unchanged. Parallel previews (16 requests / 8 workers),
repeated snapshot checks and the new 16-load / 8-worker warning tests cover
cross-request isolation. Existing Generate/Fixed/refresh/Health concurrency and
atomic publication tests continue to pass; no credential buffer is shared.

## Network surface

| Component | Allowed surface / boundary |
| --- | --- |
| Protocol parsers, source decoding, Generate, Diff, Policy | Offline; tests reject DNS/connect/HTTP/subprocess use |
| GeoIP lookup | Offline literal-IP MMDB lookup; upload is an explicit authenticated operation |
| Remote source fetch | Explicit HTTP(S) source; public DNS answers only, per-hop numeric pinning, original TLS/SNI validation, no environment proxy, bounded redirects/body/time |
| Endpoint Health | Explicit existing worker; approved public numeric TCP server/port, bounded connection timeout |
| Full Proxy Health | Explicit existing managed Mihomo subprocess; private config/work directory, loopback controller and configured HTTPS probe targets |
| Mihomo lifecycle | Explicit CLI operation; HTTPS manifest/hash verification and CPU-aware pinned artifact choice |
| Telegram | Enabled event/test path only; direct verified HTTPS to api.telegram.org, bounded time/body; disabled by default |
| HTTPS assistant | Explicit operator CLI setup using nginx/certbot/package tools; no web command execution |
| Remote lifecycle | GitHub API/archive requests; default Stable exact tag commit, explicit main exact SHA only; no channel fallback on API/archive failure |
| Release audit | Read-only GitHub/git resolution and preflight; no publication call in dry-run |

No new parser network path was introduced by Trojan/SS. Existing Remote Source,
Telegram, endpoint/proxy Health and deployment network contracts are unchanged.

## Install, update, backup and uninstall

Controlled fresh install copies `yaml_diff.py` and `node_update.py` byte-for-byte,
uses Replace by default and exposes protocol parsing/Diff without additional
persistent feature state. Optional operational modes remain Off/unmanaged.
It does not automatically download Mihomo/GeoIP, contact Telegram or set up HTTPS.

Genuine v1.2.1 source is extracted by its actual peeled commit and upgraded using
the existing real update script in an isolated deployment, with normal and
legacy env variants. Password bytes, operator .env settings, session behavior,
legacy/public bearer links and uploads/outputs/backups/logs/default customization
are verified. Password env credentials are removed only by the existing auth
migration; the original .env is backed up, and initialized auth identity remains
unchanged. A deliberately missing auth registry uses the documented identity
migration/revocation behavior, not a new regression.

A new installed-v1.2.1 fixture preserves Fixed revision/token/public URL, external
source cache and schedules, automatic Endpoint/Proxy settings, notification
settings, GeoIP metadata/database, unmanaged HTTPS metadata and all runtime
files. Operator-owned opaque metadata is retained without inferring ownership.
New core modules are copied; INSTALLATION.json updates to the resolved incoming
main identity and the previous identity is backed up (preservation is provenance,
not keeping stale installation metadata active).

Two extra disposable lifecycle checks verify all four current feature manuals
copy during fresh install and update. The existing upgrade archive omits docs;
this does not omit executable core modules or runtime state and is recorded as
LOW L-01 rather than falsely claiming the docs were backed up.

Both uninstall retain/backup choices, service/timer stop ordering, private
permissions, invalid auth preflight, rollback and code/docs copying remain
covered. State/default customization and installation/HTTPS metadata are backed
up under the existing contract. Managed binary artifacts are retained in place
for keep-data uninstall; they are not duplicated into upgrade/uninstall archives,
as already documented and tested. No destructive schema migration is needed.

## Documentation, version simulation and release automation

README now consistently lists four main input protocols, Replace/Merge
behavior and representative `core/yaml_diff.py` / `core/node_update.py` modules.
Diff/Merge/Trojan/SS are explicitly development scope, absent from Stable
v1.2.1. The current audit link points here; the previous report remains linked
as historical evidence. Trojan's current manual no longer claims SS unsupported.
Unreleased notes were editorially condensed into Added/Fixed/Security, including
mobile filename behavior and this privacy correction, with no stale three-
protocol Merge claim, raw git log or premature v1.3.0 section.

Active source/scripts/templates/tests were searched for 1.2.1 and other Stable
version literals. Remaining numbers are immutable historical upgrade fixtures,
SemVer test fixtures, dependency versions or IP addresses such as 1.1.1.1.
Runtime/current-version expectations read VERSION; none require VERSION=1.2.1.

The disposable repository copied tracked source plus the new test, and retained
Git history for genuine historical upgrade tests. Only its VERSION=1.3.0,
README release markers=v1.3.0 and promoted CHANGELOG were changed, using the
actual release helpers. The **entire pytest suite** passed there. Real main's
VERSION, README Stable marker and Unreleased notes were unchanged by simulation;
no temp tag, push or Release was made.

`AGENTS.md`, `docs/RELEASE.md`, `docs/RELEASE_AUTOMATION.md`, release.py and
release.yml were reviewed together. VERSION is canonical; README markers and
reviewed CHANGELOG promotion agree. Preflight checks full pytest, Python,
dependencies, eight shell files, bootstrap sync, removed-email and default hash.
Annotated tags, immutable publication, exact Release-body verification,
publish-tag recovery, Latest verification and both Stable resolvers retain
existing behavior. Actions uses Python **3.12**, full Git history and v* tag
triggers. No tag workflow was triggered by this audit. The latest actual [v1.2.1 Actions run](https://github.com/wwintj/clash-yaml-manager/actions/runs/36747124043) is completed/success; the historical v1.2.0 failure is retained, not reclassified.

After committing and pushing audit repairs, the real minor dry-run passed on
`fac416b286e384e0161b493c1d0e6c8089c6bba1`; it proposed v1.3.0 without applying
metadata. Before/after snapshots verify tracked hashes, HEAD, local refs, remote
tags and every GitHub Release's publication identity/title/body/status/timestamps unchanged. Both read-only lifecycle
resolvers still select v1.2.1. Stable resolve-only confirms tag selection;
the remote annotated tag object and peeled SHA were verified independently.
No real Stable archive install/update was performed. The atime-only test repair and report publication commit get a final repeat
of this same dry-run and boundary check; its SHA and result are recorded in the
final task response rather than embedding a self-referential SHA in this file.

The first temp simulation passed 2649 tests. After adding the mixed transaction
cases, its next full run exposed a pre-existing atime-sensitive assertion in
`test_state.py`: **1 failed, 2657 passed**. This was a test brittleness finding,
not VERSION hard-coding or a state write. Reads may update filesystem access
time. The fix excludes atime while retaining mode, ownership, inode/device,
link count, size and nanosecond mtime/ctime checks; the corrupt-file fixture
forces a stale atime to make that case deterministic. Normal legacy JSON reads
also keep their byte checks. No state-reader implementation changed. The final
real-main and temp full results above are from the repaired test tree.

## Findings and dispositions

| ID | Severity | Finding / disposition | Status |
| --- | --- | --- | --- |
| B | BLOCKER | No blocker found in the controlled scope | 0 unresolved |
| H-01 | HIGH | Private YAML anchor/scalar warning disclosure in committed loading and Health; fixed with existing instance-private loaders and concurrency/output regression tests | RESOLVED |
| M | MEDIUM | No separate unresolved medium finding | 0 unresolved |
| L-01 | LOW | Existing upgrade archives do not snapshot installed docs. Retained for this freeze: runtime/code recovery is covered, current manuals are installed/updated, and versioned historical docs can be recovered from the recorded exact Git commit when provenance is available; operator-local docs are outside that archive scope. The current backup contract is retained; broader documentation archival can be considered separately. | DOCUMENTED / RETAINED LIMITATION |
| L-02 | LOW | The temp simulation reproduced an OS atime-dependent read-only assertion. Corrected the test to verify application mutations and forced stale atime for regression coverage; production state code unchanged | RESOLVED |
| D-01 | DOC | README omitted SS/current core modules and pointed at historical audit as current; corrected and explicit development/Stable boundary retained | RESOLVED |
| D-02 | DOC | Unreleased Merge repeated obsolete three-protocol scope; notes edited with actual user-visible changes | RESOLVED |
| D-03 | DOC | Current Trojan manual said SS input unsupported; corrected without changing historical reports | RESOLVED |
| D-04 | DOC | External empty-source message still named only VMess/VLESS; changed to protocol-neutral “No supported nodes” without changing its error code | RESOLVED |

**BLOCKER: 0. UNRESOLVED HIGH: 0.** No numerical security score is used.

## Deferred real acceptance

The user explicitly deferred these real-environment checks. Controlled evidence
above is not a substitute for them; they do not block the agreed controlled RC
verdict and must not be relabeled PASS.

| Real acceptance | Status |
| --- | --- |
| REAL TELEGRAM NOTIFICATION | NOT RUN |
| REAL HTTPS VPS | NOT RUN |
| REAL GEOIP VPS | NOT RUN |
| AUTOMATIC HEALTH REAL DUE ENDPOINT | PENDING |
| AUTOMATIC HEALTH REAL DUE PROXY | PENDING |
| REAL POLICY | NOT RUN |
| REAL HEALTH-AWARE POLICY | NOT RUN |
| REAL VPS YAML DIFF PREVIEW | NOT RUN |
| REAL VPS MERGE MODE | NOT RUN |
| REAL VPS TROJAN PROTOCOL | NOT RUN |
| REAL VPS SHADOWSOCKS | NOT RUN |

Default YAML SHA256:
`a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b`.

## Controlled verdict and release boundary

Baseline, full real-main and temp-version tests, all browser suites, static
checks, controlled lifecycle, default integrity and actual release preflight
passed. There are no unresolved BLOCKER/HIGH findings. The executable candidate
is frozen; this audit introduces no new product feature.

**FINAL READINESS: READY WITH DOCUMENTED DEFERRED REAL ACCEPTANCE**

```text
VERSION: 1.2.1
LATEST STABLE: v1.2.1
TAG CREATED: NO
RELEASE CREATED: NO
SEMVER RECOMMENDATION: v1.3.0
RELEASE DRY RUN: PASS
```

Only a later explicit stable release request authorizes publishing v1.3.0.
