# Fixed Subscriptions UX — Phase 1 acceptance

Date: 2026-10-05 (Asia/Shanghai).

This report covers v1.5.0 development Phase 1 on main. VERSION and README Latest
Stable remain 1.4.1 / v1.4.1. No tag, Release or production VPS update is included.

## Identity and scope

- START HEAD: `bd5cd86e81ca2e345d4f69027f460a9b48fcdd9f`.
- Start gate: fetched main, clean tree, HEAD = origin/main = actual remote main.
- END HEAD: the documentation commit containing this report; resolve with
  `git log -1 --format=%H -- docs/FIXED_SUBSCRIPTIONS_UX_REPORT.md`.
  The final task response records its complete SHA and remote equality; a
  committed report cannot embed its own commit hash.
- feat: improve fixed subscription management overview: `6562305d1a685073ec88a47e3290a202a3cb04d4`.
- test: cover fixed subscription search health summary and responsive ux: `0eea2cc2472be1d2d0784e5e1514825eaa74b423`.
- Documentation follows as the commit containing this report.
- Scope: list presentation and client-side controls; only new read-only summary
  methods in Node/Proxy Health. Existing Health methods and schemas, Fixed store,
  revisions, token/source/public-URL contracts, generator, policies,
  authentication, deployment and release lifecycle are unchanged.

## Validation results

| Check | Result |
| --- | --- |
| Baseline pytest | 2977 passed in 380.87s; 0 failed |
| Baseline browser suites | 17/17 PASS |
| New Health summary tests | 63 passed |
| New Fixed list integration tests | 34 passed in 6.47s |
| Final pytest | 3074 passed in 393.08s; 0 failed |
| Final browser suites | 18/18 PASS (baseline 17 + Fixed UX) |
| Python compileall / 3.10 AST | PASS; 107 Python files parsed with 3.10 grammar |
| Node syntax | PASS; 23 JavaScript/browser files |
| pip check | PASS |
| bash -n | PASS; all eight lifecycle/deployment shell files |
| ShellCheck | PASS; 0.11.0 |
| Bootstrap entrypoint synchronization | PASS |
| git diff --check | PASS |
| release.py --validate-only | PASS; 3074 passed in 386.61s; 10,410-rule round trip PASS |
| 10,410-rule round trip | PASS in baseline, final pytest and independent generation comparison |
| Independent production/view review | PASS; no blocker |

The validate-only command completed in 388.00s. SHA256 snapshots of all tracked
and non-ignored untracked files were identical before and after execution; HEAD
and all local tag references were also unchanged. Evidence: `validate-result.json`,
`validate-files-before.json`, `validate-files-after.json` and `validate-only.log`
in the external artifact directory.

## List interaction matrix

| Capability | Evidence / result |
| --- | --- |
| Search | PASS: name/prefix, whitespace trimming, mixed case, Unicode; token, full URL and node secret queries do not match |
| Status filter | PASS: All/Active/Disabled and combined search/status |
| Clear / result count | PASS: exact visible/total count, reset to default, distinct empty-registry and filtered-empty states |
| Sort | PASS: all six options check actual visible DOM order, numeric 10 vs 2, and ties in both directions |
| External source count | PASS: excludes Manual; configured disabled remote sources still count; no fetch |
| Endpoint summary | PASS: Off, Manual/Automatic, Healthy, Suspect, Unhealthy, Unknown, Unavailable |
| Proxy summary | PASS: Off, Healthy, Suspect, Unhealthy, Unsupported, Unknown, Unavailable; Unsupported is not Unhealthy |
| Copy URL | PASS: second-row URL, independent first-row feedback, actual clipboard, two-second reset, rejected Clipboard API selects the correct input and shows fallback |
| Existing actions | PASS: authenticated/CSRF-protected POST with 303; enable/disable, regenerated old URL 404, deleted URL 404; Edit and Create navigation |
| Confirmations | PASS: original Regenerate/Delete text; cancel preserves the public URL; confirmed actions covered by existing Fixed browser suite |
| No-JS list | PASS: every row visible, enhancement controls hidden, Create/Edit links, existing state/regenerate/delete forms usable |
| Accessibility | PASS: explicit labels, live count, Copy status, visible keyboard focus, Tab order, focus after Clear, status words alongside colors |
| Privacy | PASS: only five safe row data fields; no token/source/node URI index, private Health detail or browser-storage leakage |

The browser fixture deliberately includes tied keys. Registry JSON orders internal
IDs, so fixture creation order is not the server list order. Expected sort groups
are independent, while ties are checked against the original returned row order;
production `store.list()` is unchanged.

No-JS acceptance is the list's progressive-enhancement boundary. The existing
editor still depends on JavaScript to restore/serialize node/source values, and
native confirmations retain their existing JavaScript dependency. This phase
does not claim a new no-JS editor save/create capability.

## Read-only and revision safety

Repeated real `/fixed-subscriptions` GETs compare exact bytes, private modes,
mtime, registry schema, committed revision layout and source cache contents.

| Resource / operation | Result |
| --- | --- |
| fixed_subscriptions.json | UNCHANGED; absent file remains absent |
| node_health.json | UNCHANGED; absent file remains absent |
| proxy_health.json | UNCHANGED; absent file remains absent |
| Revisions / YAML / source cache | UNCHANGED |
| Network / DNS / source fetch | NONE |
| Probe / Mihomo / subprocess | NONE |
| describe / prune / commit / settings / scheduler | NONE |

Tests use fail-on-call guards and call counters so caught exceptions cannot hide
forbidden work. Existing coordination lock files are excluded from content-state
comparisons; empty summaries do not create Health locks. Each Health JSON is read
once per batch under the existing Fixed-to-Health lock order. The Fixed lock stays
held while the selected committed YAML is read and matched.

Current fingerprints retain matching observations; stale connection fingerprints
become Unknown. Changed/deleted list revisions are Unknown. Legacy state migrates
in memory only; orphan observations are not pruned. Auxiliary corrupt, unreadable,
symlink, unsafe-permission and busy-lock cases display Unavailable without
breaking the list. Authoritative Fixed corruption remains fail-closed.

## Responsive and visual acceptance

| Width | Document overflow | Result |
| --- | --- | --- |
| 1440 | 0px | PASS |
| 1280 | 0px | PASS |
| 1024 | 0px | PASS |
| 768 | 0px | PASS |
| 430 | 0px | PASS |
| 390 | 0px | PASS |
| 360 | 0px | PASS |

Desktop/tablet table scrolling is local; <=767px rows become cards. A 128-character
name, 64-character prefix and long bearer URL fit without document overflow.
Button text is centered, controls wrap and mobile utility/standard heights are
40/44px under shared tokens. Edit intentionally uses standard density; existing
UI suite expectations were updated only for that role distinction.

Screenshots at 1440 and 390 include `fixed-empty`, `fixed-populated`,
`fixed-filtered`, `fixed-filtered-empty` and `fixed-health-warning`, with full-page
and selected row views. Manual inspection checked spacing, alignment, status
hierarchy, long-name/prefix wrapping, URL containment, Health text and buttons.
Artifacts are stored outside the repository under
`fixed-ux-phase1-20261004T164306Z/final-fixed-ux/`; the existing 140-check all-page
UI matrix writes to `final-ui/` in the same artifact directory.

The 50-subscription scenario checks rendering, filtering and numeric sorting.
Client operations must finish within 500ms and make zero network requests.
Final all-suite run: render 44ms, filter 1.0ms, sort 0.9ms, zero requests.
These are local synthetic-fixture measurements, not a production benchmark.

## Generation and storage boundaries

An isolated copy of the START HEAD core/default files generated representative
VMess, VLESS, Trojan, Shadowsocks and Hysteria2 Fixed outputs using both Default
and Custom YAML. Current code generated the same ten outputs: **10/10 byte-identical**.
Default cases each retain 10,410 rules. Registry schema remains v6 and the
`base.yaml` / `current.yaml` revision layout is unchanged. Evidence:
`fixed-generation-comparison.json`, `generation-before/manifest.json` and
`generation-after/manifest.json` in the external artifact directory.

DEFAULT YAML SHA256:

```text
a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b
```

Full regression coverage retains bearer-log redaction, auth, CSRF, constant-time
token comparison, private permissions and symlink rejection. No state schema,
retired-token format, source cache or Health observation schema changed.

## Environment and remaining acceptance

Tests use isolated temporary app copies, command doubles, cached Bootstrap 5.3.3
and Playwright Chromium. They do not operate on the developer machine's real
`/opt`, systemd, system accounts or a production VPS.

Production Stable v1.4.1 with healthz OK is the user's reported deployment status.
REAL VPS FIXED UX: NOT RUN. Real Hysteria2 network-level acceptance remains NOT
RUN; this UX work and synthetic Health data do not change that conclusion.

VERSION: 1.4.1. LATEST STABLE: v1.4.1. TAG CREATED: NO. RELEASE CREATED: NO.

V1.5.0 PHASE 1 READINESS: READY. All local acceptance gates passed. The final task
response and external `final-state.json` record the subsequent main push, exact
END HEAD, clean working tree and equality with origin/main and actual remote main,
plus unchanged existing tags and GitHub Releases.
