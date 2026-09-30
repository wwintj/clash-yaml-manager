# Health-aware Policy Integration — controlled acceptance report

Date: 2026-09-30. Start gate: clean **main**, HEAD = origin/main =
`881a66186e85cb235245526d10aa4f3a26ee8ec9`; actual remote ref also verified.
VERSION **1.1.1**, Latest Stable **v1.1.1**. Baseline full pytest:
**1244 passed in 216.33s**, 0 failed, before implementation.
This is Unreleased main development, with no VERSION bump, tag or Release.

Final full pytest: **1379 passed in 211.31s**, **0 failed**. New eligibility and
lifecycle suites: **135 passed in 2.38s**. Tests use synthetic nodes, temporary
private state, DNS/probe/controller doubles and paused threads. Browser tests
use an isolated Flask copy and synthetic three-node probe outcomes. No real
provider credentials, developer /opt, system accounts or systemd were operated on.

## Evidence boundary

**REAL TIMER-TRIGGERED DUE ENDPOINT HEALTH: PENDING.**
**REAL TIMER-TRIGGERED DUE PROXY HEALTH: PENDING.**
**REAL VPS POLICY: NOT RUN. REAL VPS HEALTH-AWARE POLICY: NOT RUN.**

Prior operator-attested evidence remains limited to real timer installed/enabled/
active(waiting), one real invocation exiting 0 with endpoint=0/proxy=0, real tim
systemd-analyze verify PASS, Mihomo COMPATIBLE and healthz 200. Codex did not
independently reproduce it. Neither an empty scan nor a manually started service
closes real due-job acceptance. Historical reports retain their phase evidence.
The [VPS handoff](HEALTH_AWARE_POLICY.md#dedicated-vps-handoff) records the remaining
real three-node exclusion/recovery/fail-open and timer tests.

## Functional gates

| Gate | Result / controlled evidence |
| --- | --- |
| Fixed registry v5 | PASS; authoritative normalized health_policy and strictly validated safe audit commit with policy/source/YAML |
| v1–v4 migration | PASS; read-time Off/48h/2; registry/current YAML/revision/token/prefix/cache unchanged; public statistics retain legacy schema; legitimate mutation writes v5 |
| Off default | PASS; existing/new omitted config Off; no eligibility snapshot reads or reactive/periodic regeneration when Off; original Preserve goldens remain |
| Proxy Health only | PASS; only strict Proxy auxiliary records are read; existing schemas v1/v2 supported |
| Endpoint not used for exclusion | PASS; four Endpoint Unhealthy nodes cannot remove any automatic candidates |
| Fresh Unhealthy exclusion | PASS; only matching fingerprint, status unhealthy, failures ≥3 and fresh last_checked_at; all automatic policy types |
| Suspect retained | PASS; failures 1/2 remain; third result filters only after commit |
| Unknown retained | PASS; missing and changed-connection fingerprints remain; new source node D stays |
| Unsupported retained | PASS; unsupported is never an exclusion regardless of count |
| Stale retained | PASS; exact boundary fresh, age+1 stale; future/invalid timestamp fail-open; last_success does not control age |
| 48h default freshness | PASS; exact default 172800 seconds; five accepted windows, unsupported values rejected |
| Minimum candidates | PASS; exact integer 1–16/default2; bool/float rejected; effective minimum min(configured, original_count) |
| Per-group fail-open | PASS; 3→1/min2 restores all3; one unhealthy node remains; TW filters while US restores; zero-candidate Policy error unchanged |
| No ranking | PASS; original A/C/D order retained; no latency sort, scoring or weighting |
| Select unaffected | PASS; selected Special Select and manual/general paths unchanged; Preserve automatic base not targeted |
| Top-level proxies retained | PASS; all original definitions and source/manual input remain; later checks still probe excluded nodes |
| Policy core pure | PASS; core/policy_engine.py unchanged; eligibility is separate, after policy application and before final validation |
| Source refresh integration | PASS; Refresh, Refresh All, auto and last-good cache apply current observations, keep unknown D and exact policy/health settings, preserve URL |
| Manual Proxy reconcile | PASS; Suspect no churn, third failure exclusion, success restores candidates |
| Auto Proxy reconcile | PASS; due checks share same completion path; health job stays success, interval900/next time/zero scheduler failures retained |
| Stale-time reconcile | PASS; existing singleton selects max3 oldest then ID, seven entries eventually covered; no new probe needed; disabled skipped, re-enable restores |
| No-change no revision | PASS; identical YAML advances only safe audit; revision/updated_at stable |
| Changed output atomic revision | PASS; existing immutable files + atomic registry pointer; generation/metadata/post-replace failure injection retains selected bytes |
| Fixed URL stability | PASS; token/prefix/slug remain during exclusions/restoration; same public /s returns committed YAML |
| Corrupt health fail-open | PASS; missing, malformed, unsafe permissions, symlink, FIFO, busy and read failures preserve original candidates and do not repair state |
| No network in reconcile | PASS; DNS/socket/provider/TCP/Mihomo runner forbidden; committed default base reused even after template replaced with invalid bytes; source cache/status/schedule preserved |
| No network under Fixed lock | PASS; provider fetch, target resolution, probe runner and generation acquire both state locks nonblocking to prove they are free |
| Lock order | PASS; snapshot holds only Proxy; combined paths observed as Fixed→Proxy; no inverse acquisition |
| Concurrency | PASS; paused reconcile loses to policy edit, health setting edit, disable, delete, source refresh and newer committed observations; newer output/audit retained |
| Public /s responsiveness | PASS; while generation paused, anonymous /s serves complete old bytes and healthz returns200; both state locks free |
| Failure separation | PASS; failed engine/busy/failed health commit never call reconcile; failed reconcile retains successful observations and normal health schedule |
| Safe audit / logs | PASS; authenticated counts/result/time only; membership removal counts documented; endpoint/URI/UUID/bearer/provider secrets excluded |
| Fixed UI and errors | PASS; Off/48h/2, nonblocking Proxy Off/engine warnings, restored rejected values and auxiliary nodes; audit authenticated only |
| Temporary Generate | PASS; no health controls/reads/storage; existing /t semantics and draft boundaries retained |
| Browser | PASS; all original six suites plus Health-aware suite; seven Preview viewports; 1440/390 health controls/summary no horizontal overflow; section screenshots inspected |
| Default YAML | UNCHANGED; SHA256 a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b |
| 10,410 rule round trip | PASS; existing real-default round trip and pre-policy default goldens retained in full suite |

## Validation

| Check | Result |
| --- | --- |
| Full pytest | PASS; 1379 passed in 211.31s, 0 failed (baseline1244) |
| Playwright | PASS; original six + new Health-aware suite |
| Python syntax | PASS; app/core/scripts/tests |
| Node syntax | PASS; static JS, browser scripts and draft test |
| Node draft/Generate guards | PASS; existing storage/expiry/corruption/keyboard/submit tests |
| pip check | PASS; no broken requirements, no added dependency |
| bash -n | PASS; seven scripts |
| ShellCheck 0.9.0 / 0.11.0 | PASS; seven scripts checked together using the repository release-tool invocation |
| build_bootstraps.py --check | PASS; lifecycle source and standalone entrypoints unchanged |
| systemd-analyze verify | UNAVAILABLE on this macOS host; existing conditional temporary-unit validation retained; prior real tim operator PASS separately recorded |
| git diff --check | PASS |
| VERSION / Latest Stable | 1.1.1 / v1.1.1 |
| New tag / Release | NO / NO |
| Real due Health acceptance | PENDING for both Endpoint and Proxy |
| Real VPS Policy / Health-aware | NOT RUN / NOT RUN |

The generator's existing reference/structure checks remain. Generic Mihomo schema,
nested-group cycle validation, ranking and real client performance acceptance
are not added. Periodic scans bound attempts, not wall-clock expiry guarantees.
No scheduler/deployment unit or default stable resolution behavior changed.

Publication commit SHAs and clean HEAD = origin/main verification are reported in
the final delivery message after pushing the tested development commits.
