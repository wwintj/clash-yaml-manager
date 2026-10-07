# v1.5.0 feature freeze and final audit

Date: 2026-10-07 (Asia/Shanghai).

The v1.5.0 scope is frozen to Fixed Subscriptions management UX. This is a
prepublication audit; VERSION and README Latest Stable remain 1.4.1 / v1.4.1.
No v1.5.0 tag or GitHub Release is created by this task.

## Identity and evidence

- Stable baseline: `bd5cd86e81ca2e345d4f69027f460a9b48fcdd9f`.
- Freeze start / real-VPS tested runtime: `62b277702166a6a9e5fa94f8f05d0462675e7f91`.
- Start gate: clean main; HEAD = origin/main = actual remote main at the expected SHA.
- Phase 1 commits: `6562305d1a685073ec88a47e3290a202a3cb04d4`,
  `0eea2cc2472be1d2d0784e5e1514825eaa74b423`,
  `62b277702166a6a9e5fa94f8f05d0462675e7f91`.
- Final candidate: the documentation commit containing this report, resolvable
  with `git log -1 --format=%H -- docs/V1_5_FINAL_AUDIT_REPORT.md`.
  A committed report cannot contain its own SHA or a subsequent workflow outcome.
  The completion report records the exact candidate, both audit commits, final
  dry-run and Ubuntu RC run ID, validated SHA, Python version and pytest count.
- External controlled evidence: `v1.5-final-audit-20261007/` in the task artifact
  directory. Real acceptance evidence: `real-fixed-ux-20261007T032909Z/`.
  These private artifacts remain outside Git; this summary contains no credentials,
  host secrets, production source/node details or bearer URLs.

## Frozen scope

Included: name/prefix search, All/Active/Disabled filter, six sort modes, visible
result count, configured external-source count excluding Manual, compact Endpoint
and Proxy summaries, Copy URL feedback/fallback, responsive list actions,
accessibility and observational batch summary APIs.

Excluded: pagination, bulk actions, duplicate, revision history, rollback UI,
Check Now or source refresh on the list, TUIC, new protocols, a new dashboard and
new storage schemas. No feature, UI redesign or runtime behavior change was added
in this audit. The only regression addition covers existing concurrency contracts.

## Complete changed-file review

All 18 changed files from Stable to the tested runtime were reviewed.

| File | Review result |
| --- | --- |
| `CHANGELOG.md` | Unreleased Changed note accurately describes the user-facing Fixed UX; retained unchanged |
| `README.md` | Stable markers remain v1.4.1; development UX description is accurate; retained unchanged |
| `core/fixed_views.py` | Only list projection changed; existing route actions, authorization and bearer display boundary preserved |
| `core/node_health.py` | Observational summary additions; existing execution methods unchanged |
| `core/proxy_health.py` | Observational summary additions; existing execution methods unchanged |
| `docs/FIXED_SUBSCRIPTIONS.md` | Storage/action contracts accurate; freeze wording and final-audit link updated |
| `docs/FIXED_SUBSCRIPTIONS_UX.md` | List-only enhancement/no-JS boundary accurate; historical and final evidence distinguished |
| `docs/FIXED_SUBSCRIPTIONS_UX_REPORT.md` | Historical controlled Phase 1 evidence preserved, including its then-NOT-RUN real acceptance |
| `docs/UI_CONSISTENCY.md` | Existing density, layout, focus and action-role contracts satisfied |
| `static/fixed.css` | Scoped responsive list/toolbar/actions; shared density tokens preserved |
| `static/fixed.js` | Local safe-field search/filter/sort and bounded copy feedback; no new network/storage/logging |
| `templates/fixed_list.html` | Safe projection, labels/live regions and existing authenticated URL input/actions |
| `tests/browser_fixed_ux_fixture.py` | Isolated synthetic tied/long/private fixtures; no production data |
| `tests/run_preview_browser.py` | Adds isolated Fixed UX suite to the complete runner |
| `tests/test_fixed_ux_browser.cjs` | Real DOM/clipboard/actions, responsive, no-JS, privacy and sorting checks |
| `tests/test_fixed_ux_views.py` | Authenticated list integration, failures, no mutation and privacy coverage |
| `tests/test_health_summaries.py` | Current/stale/revision/missing/corrupt/busy/privacy and forbidden-operation checks |
| `tests/test_ui_consistency_browser.cjs` | Edit's standard action role and existing all-page layout checks |

The final audit adds `tests/test_fixed_ux_concurrency.py` and this report, and
corrects the two current contract documents above. No historical acceptance
report was rewritten. No accidental unrelated change was found.

## Business, locking and security boundaries

Fixed registry schema v6, revision semantics and base/current YAML layout, source
cache semantics, token format/retirement, public subscription URL, refresh,
generator, Policy, Health execution/scheduling, auth/CSRF, deployment and release
automation are unchanged. The corresponding runtime modules are byte-identical
to Stable. Existing methods in the three changed Python modules have identical
ASTs after removing the reviewed summary additions and list projection.

Both `summary_many` methods read one auxiliary Health snapshot and the selected
committed YAML under the existing Fixed → Health order. They do not commit,
prune, probe, resolve DNS, access the network, start Mihomo/subprocesses, schedule
work or refresh sources. Existing exclusive coordination locks are reused;
there is no new write-lock escalation or lock inversion. Health acquisition is
nonblocking, so a busy auxiliary writer yields Unavailable and releases Fixed.
Coordination lock files are distinguished from persistent business-state writes.

| State | Result |
| --- | --- |
| Missing Health state | Off; absence preserved |
| Corrupt, unsafe-permission, symlink, unreadable or busy auxiliary state | Unavailable; list remains usable without writes |
| Current fingerprints | Matching observations retained |
| Stale fingerprints, deleted subscription or changed revision | Unknown; no stale observation reused |
| Legacy state / orphan observations | In-memory interpretation only; no migration or pruning write |
| Corrupt authoritative Fixed registry / committed content | Existing fail-closed behavior retained |

Four added regression cases exercise real filesystem locks and actual list GETs
for Endpoint and Proxy: (1) a list holding its selected Fixed revision serializes
subscription and Health settings writers; (2) a held auxiliary Health writer
cannot block list completion or a subsequent Fixed mutation. Event-controlled
interleavings verify actual completion and state; there are no sleeps, retries,
skips or xfails. This raises pytest from 3074 to 3078; no tests were deleted.

Privacy: the JS index contains only five safe row fields. It adds no token,
bearer-URL index, source URL, node URI/server/port/fingerprint/UUID/password,
Hysteria2 auth/obfs-password or probe target. Existing authenticated URL inputs
remain the required bearer display boundary. Browser console/storage, data
attributes, errors and logs introduce no private index or secret leakage.

Security regressions pass for auth-required access, CSRF, POST-only mutations,
constant-time token comparisons, regeneration/retired-token tombstones, bearer
log redaction, symlink rejection and private state permissions.

No-JS claims remain limited to list rendering, Create/Edit navigation and
available server forms. The existing Fixed editor requires JavaScript to restore
and serialize inputs; this audit does not claim full no-JS create/save. Existing
native confirmations also retain their JavaScript dependency.

## Controlled validation

| Check | Result |
| --- | --- |
| Full pytest run 1 | 3078 passed in 417.80s (0:06:57); 0 failed |
| Full pytest run 2 | 3078 passed in 413.81s (0:06:53); 0 failed |
| Full browser runner | 18/18 PASS; suite count unchanged |
| Backend consecutive repeats | 50/50 PASS; 101 tests each, no retry |
| Critical Fixed UX browser repeats | 3/3 PASS after the full-suite run, no retry |
| All-page UI matrix | 140 checks PASS; 1440/1280/1024/768/430/390/360px |
| Fixed UX responsive matrix | All seven widths: 0 document horizontal overflow |
| Generation comparison to Stable | VMess/VLESS/Trojan/Shadowsocks/Hysteria2 × Default/Custom: 10/10 byte-identical |
| Default rule round trip | 10,410 rules PASS |
| compileall / Python 3.10 AST | PASS; 108 Python files compatible with 3.10 grammar |
| Node syntax | PASS; 23 JavaScript/browser files |
| pip check | PASS |
| bash -n | PASS; all eight lifecycle/deployment shell files |
| ShellCheck | PASS; pinned 0.11.0 |
| Bootstrap synchronization | PASS |
| git diff --check | PASS |
| release.py --validate-only | PASS; 3078 passed in 397.58s (0:06:37); 10,410-rule round trip; no mutation |

The browser run covers the toolbar, filtered empty state, Health warnings, long
name/prefix/URL, action wrapping/density, labels, live regions and visible keyboard
focus. Search, combined filters, all six sorting modes and ties, counts, source
count, summary states, copy success/reset/rejection fallback, security/privacy,
no-JS list and the 50-row local performance scenario pass. Local fixture timings
are not a production benchmark. Desktop and mobile filtered-empty screenshots
were visually inspected in addition to the measured layout suite.

Default YAML SHA256 remains:

```text
a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b
```

Validate-only compared SHA256 for every tracked and non-ignored untracked file
before/after; content, working-tree status, HEAD and tag refs were unchanged.
The two final full runs and validation include all four new concurrency cases.
The earlier 3074-test baseline is additional evidence, not counted as a final run.

## Real VPS Fixed UX acceptance

The full real acceptance report was read and its final evidence reconciled.
The tested runtime was exactly `62b277702166a6a9e5fa94f8f05d0462675e7f91`.
Deployment/healthz, search/filter/six sorts/counts, external source count,
Endpoint/Proxy summaries, copy/manual fallback, Edit, enable/disable,
regeneration/deletion, 390px long-content layout, YAML/10,410 rules and log
privacy all passed. Destructive actions were confined to four synthetic
subscriptions; all were deleted and all current synthetic URLs returned 404.
Regeneration separately proved old URL 404 and replacement URL 200 before deletion.
Normal retired-token tombstones remain part of the existing storage contract;
there is no active synthetic subscription or Health entry left.

Five repeated list reloads preserved exact content, mtime and size of Fixed,
Endpoint and Proxy JSON. No network/probe activity was observed in logs, state or
process inspection; **no packet capture, DNS trace or syscall trace was performed**.
This supports NONE OBSERVED, not a forensic claim that every packet was excluded.

Final target VPS state: VERSION 1.4.1, channel stable, tag v1.4.1, commit
`bd5cd86e81ca2e345d4f69027f460a9b48fcdd9f`, service active, healthz OK.
The original logged-in Chrome verified the restored Stable page. SSH tunnel and
control master were closed. Default YAML, .env, systemd and Nginx hashes were
unchanged. Existing runtime data was preserved; the application log only appended
two normal startup lines. Acceptance and automatic backups were retained.

This audit changes docs/tests only. Final runtime bytes match the tested SHA;
under the agreed policy no new VPS deployment or acceptance run is required.

### Temporary IAB cleanup timeout

**NON-BLOCKING ACCEPTANCE LIMITATION — RECORDED.** IAB stopped responding around
a confirmation; querying the dialog returned undefined, and closing/resetting
its viewport timed out. Successful tool-side temporary-window cleanup cannot be
claimed. Subsequent operations completed through the original logged-in Chrome;
independent server JSON and HTTP evidence verify sample cleanup, and the exact
Stable restore plus native Chrome final-page evidence verify the final service.

There is no observed impact on final business state, no active synthetic test
state left, no effect on Stable restoration and no unresolved Fixed UX failure.
The uncertainty is retained specifically for temporary IAB UI cleanup, not hidden
or converted into a cleanup PASS.

## Historical limits and severity

Historical Phase 1 and Hysteria2 acceptance records remain unchanged. Real
Hysteria2 QUIC, AUTH, FORWARDING, PORT HOPPING and LIVE LATENCY remain **NOT RUN**.
Other historical deferred items retain their recorded status. YAML/browser
regressions do not constitute real protocol forwarding acceptance.

| Severity | Count | Disposition |
| --- | --- | --- |
| BLOCKER | 0 | No blocker found |
| HIGH | 0 | No high issue found |
| MEDIUM | 0 | None found |
| LOW | 0 | None found |
| INFO | 3 | IAB cleanup uncertainty; observational network evidence boundary; historical real Hysteria2 NOT RUN |

## Final candidate gates and publication boundary

Local audited content is ready for the final candidate gates. Minor is the
appropriate future bump because the frozen change adds user-facing management UX.
The planned target is 1.5.0 / v1.5.0; Unreleased keeps its existing reviewed Changed
note. A release metadata commit must contain only VERSION, README.md and
CHANGELOG.md, promoting the note and previewing Latest Stable v1.5.0.

After the small test/doc commits are pushed, the task must run
`python3 scripts/release.py minor --dry-run` on clean final main and dispatch
[Ubuntu Release candidate validation](https://github.com/wwintj/clash-yaml-manager/actions/workflows/release-candidate.yml)
with the exact final candidate SHA. READY requires completed/success RC whose
logged checkout SHA matches that candidate, plus a passing dry-run with no file,
HEAD, tag or remote-object mutation. These subsequent outcomes and exact run
identity are recorded in the task completion report, rather than predeclared here.

The task stops before publication even when those gates pass. VERSION remains
1.4.1, Latest Stable remains v1.4.1, and no v1.5.0 tag/Release may be created
without the user's subsequent explicit release instruction.
