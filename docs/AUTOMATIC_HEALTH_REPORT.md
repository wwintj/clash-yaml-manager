# Automatic Health Scheduler MVP — acceptance report

Date: 2026-09-30. Start gate: branch main, clean tree, HEAD and origin/main
`e2e430d7740b0dcf8d5f7453417c4b9a131dd19d`, VERSION **1.1.1**, Latest Stable
**v1.1.1**, baseline **984 passed in 165.21s**. This is Unreleased main work:
no VERSION bump, tag or GitHub Release.

## Evidence boundary

The prior manual proxy/CPU phase is closed by **OPERATOR-ATTESTED REAL VPS
ACCEPTANCE**, separately recorded in [PROXY_HEALTH_REPORT.md](PROXY_HEALTH_REPORT.md):
tim build `1.1.1-dev+e2e430d`, amd64-v2 engine COMPATIBLE, exact pinned executable
hash/version, healthz 200, real VMess/VLESS and bad UUID differentiation,
Suspect/Unhealthy/recovery, stable Fixed URL/YAML and continued application health.
Codex did not independently reproduce that VPS run. Reality, real arm64,
latencies, endpoints and node counts were not supplied or inferred.

All Automatic Health results here are **controlled automated tests** in private
temporary directories, with command, DNS, engine/process/controller doubles.
They do not touch the developer machine's real /opt, systemd or system accounts.
The browser fixtures do not run an application background scheduler.
**REAL TIMER-TRIGGERED VPS HEALTH: NOT RUN.** A manual oneshot start alone does
not close that acceptance; a due Endpoint and Proxy job must be observed after
an actual timer trigger. Exact commands and expected evidence are in
[AUTOMATIC_HEALTH.md](AUTOMATIC_HEALTH.md#tim-vps-acceptance-a-real-timer-run-is-required).

## Controlled functional gates

| Gate | Result | Evidence |
| --- | --- | --- |
| Real VPS proxy acceptance docs closeout | PASS, operator-attested | Only the explicit operator build/hash/version/healthz/checklist evidence is recorded; no independent-run, Reality or inferred measurements claim. |
| Node Health state migration | PASS | v1 Off/Manual → v2 same mode and observations in memory, null interval/next/scheduler metadata, no file rewrite/probe; legitimate change persists v2. |
| Proxy Health state migration | PASS | Same migration, retaining global/custom settings and observations; independent state file. |
| Off default / Manual / Automatic | PASS | New Off; Manual unscheduled; Automatic requires exact valid interval; invalid mode/trigger/interval cannot probe. |
| 15m–24h intervals | PASS | All seven choices; booleans, strings, floats, arbitrary and absent intervals refused at the state API; typed Web form conversion. |
| Manual check in Automatic / next reschedule | PASS | Manual remains available; normal completion records manual/success and schedules completion+interval; enabling/changing interval does not probe and same-save preserves due time. |
| Auto Endpoint | PASS | Existing saved-YAML extractor, fingerprints, bounded TCP probe and 1/2/3 failure threshold; recovery Healthy/0; auto metadata and normal next time. |
| Auto Proxy | PASS | Existing managed binary path and existing ephemeral config/controller/process code; controlled process stop/config cleanup and controller failure exercised. |
| Job/node failure separation | PASS | Bad-node jobs complete normally, Unsupported adds no node failure; internal/controller/engine errors preserve observations and observation timestamps. |
| Scheduler backoff | PASS | Independent 5m/15m/30m/1h/2h/6h capped sequence and success reset; interval unchanged; all unavailable engine statuses covered. |
| Busy retry / shared proxy lock | PASS | Existing proxy_probe.lock reused; busy preserves nodes/failure count, retries in 5m and does not invalidate the running manual job. |
| Conflict retry | PASS | Fixed save and real controlled Automatic Source Refresh revision changes discard old candidates and retry; newer mode/interval/global settings or completed checks always win. |
| Disabled subscription pause | PASS | Due selection excludes disabled entries without erasing state; overdue re-enable resumes; disable during a probe discards results. |
| Max 4 Endpoint / max 1 Proxy / fairness | PASS | Oldest due then stable ID; excess subscriptions remain due for subsequent scans; no first-256 partial probe on oversized subscription. |
| Scheduler singleton | PASS | Lock held and simultaneous-scan fixtures allow only one worker; other exits 0; auto_health.lock stays private. |
| No network under Fixed lock | PASS | Paused auto Endpoint/Proxy permits actual Flask public /s, management edit and healthz reads; concurrent mutation completes. |
| Optimistic Endpoint result comparison | PASS | Manual/auto same-clock race cannot merge stale identical results; internal check revision advances on completed checks/changed settings. |
| Systemd service | PASS in fixture | oneshot, project venv CLI, clashyaml User/Group, UMask 0077, NoNewPrivileges, PrivateTmp, 15m/10s bounds, control-group; CLI termination unwinds/restores handlers. |
| Systemd timer | PASS in fixture | boot 2m / scan 5m / accuracy+jitter 30s, enabled/active verification; no Flask/Gunicorn scheduler or timeout change. |
| Source refresh timer independent | PASS | Existing refresh unit/CLI unchanged; health does not call refresh_sources or fetch providers; separate timer lifecycle. |
| Deployment / recovery / uninstall | PASS in fixture | Both health JSON files preserved and backed up; five units backed up; stop-before-state/code ordering; stop failures abort early; write/replace/enable/active/enabled failures restore old pair or remove new pair; uninstall removes units and preserves selected state backup. |
| Fixed URL / YAML / no node exclusion | PASS | Fixed registry bytes, slug and saved YAML unchanged by health outcomes; no group/policy rewrite or node removal. Public reads retain their existing access-stat semantics. |
| Secret redaction / corrupt state isolation | PASS | IDs/counts/fixed results only; no UUID, endpoint, URI, provider URL, token, controller secret or raw traceback; corrupt Endpoint/Proxy state does not stop the other subsystem or public routes. |
| Browser | PASS | Off→Automatic/15m, next/trigger/result display, manual buttons in Automatic, unavailable-engine warning, 1440/390 widths, no overflow or secret storage; all prior suites retained. |
| Existing regressions | PASS | Generate, Fixed CRUD, Fixed/V2/Legacy /s, temporary /t, sources, refresh, manual Endpoint/Proxy, Mihomo CPU variants, auth/CSRF, deployment/release tooling and seven Preview viewports. |
| default.yaml / 10,410-rule round trip | PASS | Exact original byte SHA256 and existing real default generation round trip. |

## Final validation

| Gate | Result |
| --- | --- |
| Full pytest | PASS; 1101 passed in 206.24s, 0 failed; baseline 984 passed |
| Playwright | PASS; all five suites, including seven Preview viewports and Automatic controls at 1440/390 |
| Python / Node syntax | PASS |
| pip check | PASS |
| bash -n | PASS; seven shell scripts |
| ShellCheck 0.9.0 / 0.11.0 | PASS; seven shell scripts |
| systemd-analyze verify | UNAVAILABLE on macOS; conditional test verifies all five temp units when available; real VPS command supplied |
| build_bootstraps.py --check | PASS; lifecycle source/entrypoints unchanged |
| git diff --check | PASS |
| VERSION / Latest Stable | 1.1.1 / v1.1.1 |
| New tag / Release | NO / NO |

The unit tests validate structure and mocked deployment activation; they are
not a claim that a real systemd timer fired. Persisted due timestamps supply
restart catch-up; Persistent=true alone does not add catch-up to a monotonic timer.
Job limits, older work, jitter and long probes can delay actual execution.
If an auxiliary file cannot safely be read/written, it is left intact and its
retry metadata cannot be guaranteed until the operator repairs/restores it.
The next required operator evidence is the genuine timer-triggered VPS checklist
in [AUTOMATIC_HEALTH.md](AUTOMATIC_HEALTH.md), including journal auto jobs,
advanced due times, healthy real nodes, public URL/YAML stability, cleanup and
healthz 200 with no credentials in the journal.
