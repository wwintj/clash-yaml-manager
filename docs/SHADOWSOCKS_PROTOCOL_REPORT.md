# Shadowsocks Protocol MVP Acceptance Report

Audit date: 2026-10-01. Development only; no release/version/tag operation.

## Starting evidence

- Branch `main`; clean working tree before implementation.
- START HEAD: `76f4873fcf5ff9256df5bb978809951032768478`.
- Actual fetch completed; HEAD, origin/main and actual remote main matched.
- VERSION `1.2.1`; actual GitHub Latest Stable title/tag `v1.2.1`.
- Full baseline completed before any edits: **2333 passed in 438.23s**.
- Stable annotated tag object `457787de1ee12d441605709bc59dc8d2e84737be`,
  peeled commit `f62bf50721e3ac00d5d2a2a9f784ede4b79b49cf`.
- Main-only publication. Final commit IDs, END HEAD, clean status and actual remote
  equality are verified after committing/pushing and recorded in the task response.

## Implementation evidence

| Area | Contract and verification |
| --- | --- |
| SS URI | Requested legacy whole-authority Base64 plus SIP002 encoded/plain userinfo; standard/URL-safe alphabets, missing padding, UTF-8 fragment names, hostname/IPv4/bracketed IPv6, port 1–65535. No simple credential delimiter splitting or decode fallback. Official sources linked in the manual. |
| Cipher/password | Nonempty strings only, no cipher whitelist; original values preserved, including Unicode/space-only values. Plain userinfo percent-decodes once; passwords inside Base64/YAML do not percent-decode. |
| Mapping | `type: ss`, name/server/port/cipher/password/UDP; URI UDP defaults true. No UUID/TLS/certificate fields invented. Pinned Mihomo source reviewed and private config compatibility tested. |
| Plugins/query | URI plugin/obfs families fail with an explicit fixed error, including the requested `/?plugin` variant; all other queries also fail. Clash plugin/obfs fields fail even when empty/null. No execution or new network/subprocess code. |
| Batch/Aux/Parse | Three existing input forms, four protocols mixed in order, manual overrides and duplicate name rejection. UI helpers list all four protocols with no selector. |
| Replace | Existing shared replacement/removal/reference contract, unchanged. |
| Merge | Existing source proxy objects/order, comments/quotes/anchors and arbitrary Trojan/Hysteria2/WireGuard/unknown mappings survive; SS appends normally. Same-name conflicts fail without overwrite, auto-rename or deduplication. |
| Exact Diff | 20 real HTTP cases across Default/Custom × Replace/Merge × Preserve/Select/URL-Test/Fallback/Load-Balance, mixed four-protocol Batch plus SS Aux. Public unified diff reconstruction equals Generate file and download bytes. Browser independently reconstructs both modes too. |
| Fixed | Manual Batch/Aux save/edit and name/country override; revision changes but token/URL stable; registry remains v6, Fixed remains Replace. |
| External | Raw/Auto, standard/URL-safe Base64 lists and nested SS encoding; Clash core fields plus unknown plain extra mappings/lists retained. Uploaded Raw/Base64/Clash/Auto; source order and cache payload preserved. |
| Auto Refresh | VMess/VLESS → mixed Trojan/SS updates revision/cache; invalid plugin payload keeps last-good YAML/cache/URL and existing 300s first backoff; recovery resets to existing 900s interval. Scheduler/lock/revision/cache implementation unchanged. |
| Policy | All five existing policies with country and selected Special group membership; SS is an ordinary candidate, no protocol branch. |
| GeoIP | Manual > Name > offline public literal IPv4/IPv6 > Unknown; hostname/private/documentation addresses do not trigger DNS. |
| Endpoint Health | Only shared protocol admission and password redaction; injected TCP probe receives existing server/port. No schema/algorithm/scheduler change. |
| Full Proxy Health | Existing injected runner and status thresholds; full SS mapping in opaque-name 0600 config, 0700 work directory, loopback controller, silent logs. No engine upgrade, real process or real proxy connection. |
| Security | Anonymous and CSRF rejection; fixed errors and private logs/warnings; Parse/observational names/state/notification events redact credentials. Browser renders `<script>alert(1)</script>` as data with no script/dialog. Authenticated administrator YAML/Diff and private input/cache retain credentials by design. |
| Import boundary | Existing 10 MiB limit, safe loader, depth 32, 100000-item budget, cycle/non-string-key/object-tag/finite-number/Unicode protections remain. Numeric password YAML warnings remain private to importer instance. |
| Regression | VMess/VLESS/Trojan parsing functions untouched; seven pre-change mappings, complete Batch result hash and mixed Replace/Merge byte goldens match. Previous Default/custom/policy goldens remain enforced. |

New tests: **242** offline cases in `tests/test_ss_protocol.py`, **40** integration
cases in `tests/test_ss_integration.py`: **282 added cases**. Existing obsolete
SS-unsupported fixtures now use Hysteria2/TUIC, keeping their case counts and
negative coverage. No existing test case was removed.

Before-change goldens, `tests/ssfixtures/before.json`:

```text
VMess/VLESS/Trojan Batch result: 7a647833798f17127a1264b4a845a0a11bd1b411b2db54901f5cd511f629250b
Mixed Custom Replace: 14591c352d947021a10654c156a2e32124868f69e53248d2ae5571856bae2465
Mixed Custom Merge:   4defcbd9d1dc2c7e6d45ac9f55bc00fc4eb8c72afa9c34eeaca488d9e324958e
```

The existing legacy unsupported-scheme diagnostic remains byte-compatible; UI and
current manuals advertise the expanded input protocol set. Historical acceptance
reports describe their original stage and are not rewritten as SS test evidence.

## Validation gates

- Existing focused regression: **431 passed in 18.11s**.
- SS focused validation: **282 passed in 15.90s**.
- Final full pytest: **2615 passed in 452.64s (7:32), 0 failed**; baseline 2333,
  net **+282**, with no removed cases.
- All **15 browser suites PASS**: Preview, Fixed, External, Endpoint Health,
  Full Proxy, Policy, Health-aware Policy, GeoIP, Settings, HTTPS, Notifications,
  YAML Diff, Merge, Trojan and Shadowsocks. Desktop/mobile cover 1440px and 390px;
  Preview additionally retains all seven existing breakpoint checks.
- SS browser verifies helpers, mixed protocols, Aux, password-safe Parse, name/
  country edits, XSS sentinel, exact Diff/Generate/download, Replace/Merge and
  no horizontal overflow at both widths.
- compileall and Python 3.10 syntax: **98 Python files PASS**.
- Node syntax: **20 JS/CJS files PASS**; pip check: no broken requirements.
- Bash syntax and ShellCheck **0.9.0 and 0.11.0**: all **8 shell files PASS**.
- Bootstrap synchronization and `git diff --check`: PASS.
- Secret-pattern review includes untracked additions and all four URI schemes;
  changed-file candidates are synthetic examples/fixtures, no operational secrets.

Direct SS/default round-trip and full existing regressions preserve all **10,410
rules** and unrelated source sections. Default SHA remains:

```text
a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b
```

No VERSION/Latest Stable/default YAML/Fixed schema/auth/dependency/runtime data,
Mihomo manifest or lifecycle source changes. Changelog only adds one Unreleased
Added entry. No release command ran; push targets main only with followTags disabled.

## Limits

Refresh/GeoIP/Health use controlled clocks, synthetic database and injected
fetch/resolver/probe/runner fixtures. Browser runs an isolated Flask copy with
loopback fixtures and cached Bootstrap CSS; other browser requests are blocked.
No live Shadowsocks server, real Mihomo process, VPS, developer /opt, systemd or
system account acceptance was run. Nonempty cipher/key admission is not proof of
runtime engine support. Only the existing tag-triggered release workflow exists;
a main push is not evidence of a GitHub Actions validation run.

VERSION: 1.2.1
LATEST STABLE: v1.2.1
TAG CREATED: NO
RELEASE CREATED: NO
REAL VPS SHADOWSOCKS: NOT RUN
