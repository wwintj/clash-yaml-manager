# Hysteria2 Protocol MVP Acceptance Report

Audit date: 2026-10-04. Development Phase 1 only, on main. No stable release,
version bump, tag, engine upgrade or real VPS update.

This report preserves the original Phase 1 results and its pending scope decision.
The subsequent Local 3-Commit Pre-Push Audit request authorizes retaining the
existing refresh/revision contract while auditing and, after all gates pass,
pushing main. That decision supersedes the pending decision below; it does not
change the historical results or claim that source refresh retains its revision.
Current pre-push results are recorded in [Pre-Push Audit](HYSTERIA2_PRE_PUSH_AUDIT.md).

## Starting and ending evidence

- START HEAD: `32a77e6777e1fb7706d9ab2afb45d3103363fe14`.
- Actual fetch completed before implementation. Branch main, clean tree,
  HEAD = origin/main = actual remote main; expected release commit verified.
- VERSION `1.3.2`; GitHub Latest Stable `v1.3.2`.
- Full baseline completed before edits: **2678 passed in 364.81s**, 0 failed.
- Implementation commit: `a2bbabebaa61af487b13830b824bbde2eeb3c07e`
  (`feat: add hysteria2 parsing and source import`).
- Tests commit: `c055e6508b9e2110ecefdd36a7ebe6c6bd7e3cd8`
  (`test: cover hysteria2 integration privacy and browser flows`).
- END HEAD and the final documentation commit are verified after committing this
  report, with their exact SHAs and remote comparison in the final task response
  and external `final-state.json`. A file cannot embed its own commit SHA.

## Implemented contract

Official Hysteria2 URI and current official Mihomo documentation were reviewed
before implementation. The actual compatibility boundary is pinned Mihomo
v1.19.31 official source plus the same version's verified binary; references
and the full allowlist are in [Hysteria2 Protocol](HYSTERIA2_PROTOCOL.md).

| Area | Contract / evidence | Result |
| --- | --- | --- |
| Schemes | `hysteria2://` / `hy2://`, canonical YAML `type: hysteria2` | PASS |
| URI positives | Hostname/IPv4/bracketed IPv6, default 443, valid explicit ports, fragment/manual/Unicode names, exact-once percent auth, literal plus, userpass, SNI, insecure 0/1, certificate pinning, Salamander/Gecko, hopping | PASS |
| URI negatives | Invalid scheme/authority/IPv6/port/encoding, zero/overflow, raw whitespace/control/backslash, multiple @, unknown/duplicate/blank query, invalid insecure/obfs/SNI, missing/orphan obfs password, arbitrary path, Realm/ECH/client extensions, oversized URI/query | PASS |
| Auth | Entire userinfo decoded once; no `unquote_plus`, trimming, splitting away username or complexity rules; absent/empty auth accepted by pinned engine | PASS |
| Hopping | Comma/range syntax; first concrete representative port; normalized decimal ports, input order; strict range/size/count bounds | SUPPORTED |
| Obfs | Salamander and Gecko require exact nonempty obfs password, including whitespace/Unicode; both pinned source and actual `-t` accept them | SUPPORTED |
| pinSHA256 | Maps to certificate SHA256 `fingerprint`; original case/colons retained | PASS |
| Clash | Explicit field allowlist and strict types; ALPN/up/down/ports/hop interval preserved; ports-only adds representative port; unknown types retain skip warning | PASS |
| Safe import | Existing size/depth/item/finite-number/Unicode/cycle/object-tag/key restrictions; numeric YAML warnings stay private | PASS |
| Batch / Auxiliary / Parse | Mixed five protocols and both aliases in order; editable Country/Name; Protocol shows Hysteria2; exact duplicate-name error | PASS |
| Fixed Manual | Save/edit, Manual refresh, regenerated link, stable URL during edits/refresh, unchanged schema v6 and Replace-only behavior | PASS |
| External formats | Uploaded Raw/Base64/Clash/Auto and Remote Raw/Base64/Clash, shared Batch parser, standard/URL-safe Base64 with missing padding | PASS |
| Automatic refresh | Success, changed mixed source, invalid replacement, last-good output/cache, recovery, fixed error/history redaction | PASS |
| Identical source refresh | YAML/cache bytes remain unchanged, but existing source refresh creates a new revision | REQUIREMENT CONFLICT; see below |
| Health-aware cached regeneration | Unchanged YAML keeps revision and URL; tested with healthy Hysteria2 observations | PASS |
| Generate Replace / Merge | All five protocols, exact node/group/country/special membership, old arbitrary proxy objects/anchors preserved in Merge, exact collision rejection | PASS |
| Exact Diff | 20 HTTP cases: Default/Custom × Replace/Merge × Preserve/Select/URL-Test/Fallback/Load-Balance, mixed Batch plus HY2 Auxiliary; patch reconstruction = Generate file = download bytes | PASS |
| Country | Manual > Name > enabled offline public literal GeoIP > Unknown; no DNS | PASS |
| Endpoint | Existing injected TCP observation, server/representative port, unchanged schema/thresholds/output; explicitly does not validate QUIC/Hysteria2 | PASS |
| Full Proxy | Existing runner/status flow, opaque names, loopback controller, 0600 config/0700 directory and silent logs; actual pinned `-t` below | PASS |
| Identity | Rename invariant; password/server/port/SNI/obfs/obfs-password/ports changes invalidate identity | PASS |
| Policy / Health-aware Policy | Select and automatic policies retain ordinary candidates; fresh confirmed unhealthy only, stale/suspect retention and minimum-candidate fail-open | PASS |
| Privacy | Both credentials redacted from ordinary Parse/Health names, errors, source history, logs and notification output; auth/CSRF rejection; authenticated private YAML/Diff retains needed credentials | PASS |

Realm schemes/options, ECH, custom URI bandwidth/ALPN/hop extensions, Gecko
packet-size tuning, arbitrary common and advanced QUIC options are explicitly
rejected and documented as deferred, rather than silently dropped.

## Controlled validation

- Final full pytest: **2975 passed in 377.01s**, 0 failed; baseline 2678,
  **+297 cases** (232 protocol + 65 integration). Existing cases retained;
  obsolete Hysteria2-unsupported fixtures now use still-unsupported types.
  No skipped/xfail cases or flaky-retry mechanism was introduced.
- Final protocol target: **100 consecutive PASS**, 232 cases each, 45.36s total.
- Privacy/import subset: **5 consecutive PASS**, 108 cases each.
- Browser: **17/17 suites PASS**. Existing Preview, Fixed, External, Endpoint,
  Proxy, Policy, Health-aware Policy, GeoIP, Settings, HTTPS, Notifications,
  YAML Diff, Merge, Trojan, Shadowsocks and UI Consistency remain, plus Hysteria2.
- New Hysteria2 browser: 1440px and 390px; mixed Batch/Aux, alias, redacted Parse,
  edits, Replace/Merge, exact Diff/download, literal script remark as text,
  invalid query, 6000-character auth, Fixed Manual/edit and uploaded external
  source, no document overflow or browser errors/dialogs.
- UI Consistency: original **140 live page/width checks PASS**. Its first launch
  lacked required cached Bootstrap JS; supplying the existing cache enabled the
  suite without changing any assertion. Other 16 suites passed in the full runner.
- Python compileall and Python 3.10 AST: 103 Python files PASS.
- Node syntax: 22 JS/CJS files PASS; pip check: no broken requirements.
- bash -n and ShellCheck 0.11.0: all 8 shell entrypoints PASS.
- Bootstrap synchronization and git diff --check: PASS.
- Actual `python3 scripts/release.py --validate-only`: **PASS**, including a separate full run of **2975 passed in 379.30s** and the 10,410-rule round trip. HEAD, VERSION, local tags, working-tree status and every tracked/untracked nonignored file hash matched its pre-command snapshot. Remote tags and all GitHub Release objects also matched the starting snapshot.

An earlier overlapping full run reported three integration fixture failures
(before their corrections) and a process-initialization failure. The individual
cause of the latter was not established; concurrent test/browser load was then
removed. Its redirect overlapped the following command, so the raw redirect is
retained separately, along with the complete final command output. The final
corrected-tree full run and the subsequent independent validation-only run each
passed all 2975 tests. No test assertion was weakened or retry mechanism added.

## Pinned Mihomo evidence and limits

An exact official Darwin arm64 v1.19.31 archive was used for local isolated
configuration validation. Project Linux installation manifest/version stayed
unchanged. This is not a managed engine install or VPS deployment.

- Archive: `mihomo-darwin-arm64-v1.19.31.gz` from the official v1.19.31 Release.
- GitHub asset digest matched downloaded SHA256:
  `d131f44b3deb2a8356f7ac75048ad67a10d53243323951c4f3cda7b672922963`.
- Extracted binary SHA256:
  `fae1f37e28ee53fcf5be7a8bb121099db1fe442e44205734ed49c62579364090`.
- Actual `-v`: Mihomo Meta v1.19.31 darwin arm64, go1.26.8, with_gvisor.
- Actual **14/14 `-t` PASS**: basic, absent auth, SNI, insecure, Salamander,
  Gecko, IPv6, hopping, certificate pin, numeric bandwidth/ALPN/UDP false,
  numeric hop interval, range hop interval, ports-only, explicit empty auth.
- Each command used a fresh temporary directory and private config with no live
  third-party node/controller delay request; temporary directories were removed.
- Full Proxy controller/status compatibility additionally uses the existing
  injected runner. Live Hysteria2 authentication, QUIC forwarding and delay
  measurements are **NOT RUN**, not implied by config parsing.

## Regression and immutable state

Before implementation, all four existing protocols were captured in
`tests/hysteria2fixtures/before.json`. Complete Batch data and Custom
Replace/Merge serialized YAML match exactly after implementation:

```text
Batch SHA256:   b2b6060713e020a7ea80636ad57824b75f9736229e792135c73deecc305556f2
Replace SHA256: 54601483c8b24524995c86d7f582f14641478980845c637e02b57e79d0651b1a
Merge SHA256:   76c7dda3a96fd26177b889a01d9795f2bc3703a97c473690f0eb94b8736257e4
```

Existing VMess/VLESS/Trojan/SS parser goldens remain unchanged. New default
integration cases and existing round-trip tests preserve all **10,410 rules**.
Default SHA256 remains:

```text
a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b
```

VERSION, README Latest Stable marker, stable tags/Releases, Mihomo manifest,
Fixed schema/auth/dependencies/runtime state and release-candidate workflow are
unchanged. Changelog adds only an Unreleased Added note. No publishing release command,
new tag, GitHub Release, RC dispatch or real VPS update is authorized/run.

## Scope conflict and readiness

The requested unchanged-refresh-revision check conflicts with the request to
retain existing Fixed/Automatic Refresh behavior. Existing `save()` creates a
new revision for ordinary source refresh even when YAML bytes are identical;
only cached Health-aware Policy reconciliation retains revision on equality.
Both behaviors were tested and retained. The user was asked to choose between
retaining this contract with a documented exception and expanding scope to
change automatic refresh transactions. That choice remains pending.

The implementation is reviewable in local commits. Main push is withheld until
this acceptance conflict is resolved; test success does not justify claiming
that the literal unchanged-source-revision requirement was met.

## Real-environment status

The user's new stable-baseline attestations are recorded as provided:
REAL VPS STABLE UPGRADE PASS; REAL VPS UI DENSITY PASS. Earlier deferred
Telegram/HTTPS/GeoIP/Policy/Health-aware Policy/Diff/Merge/Trojan/Shadowsocks real
checks remain NOT RUN; Automatic Health real-due Endpoint/Proxy remain PENDING.
They are not promoted by the controlled checks in this report.

```text
CONTROLLED MIHOMO CONFIG VALIDATION: PASS (14/14)
REAL VPS HYSTERIA2: NOT RUN
VERSION: 1.3.2
LATEST STABLE: v1.3.2
TAG CREATED: NO
RELEASE CREATED: NO
V1.4.0 PHASE 1 READINESS: NOT READY (refresh revision scope decision pending)
```
