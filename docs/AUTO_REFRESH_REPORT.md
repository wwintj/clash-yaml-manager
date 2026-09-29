# Automatic Refresh MVP acceptance — 2026-09-30

This stage develops `main` only. VERSION is **1.1.1**, Latest Stable remains
**v1.1.1**, and no tag or GitHub Release is created. Baseline main was
`dd9603698f7f1b0bb9969072b8226d1339020cd5`.

Baseline: **594 passed in 138.96s**. Final complete suite:
**667 passed in 150.89s, 0 failed**. The 67 automatic-refresh tests were also
re-run after the final allowlisted-error validation adjustment: **67 passed**.

| Acceptance gate | Result / evidence |
| --- | --- |
| Registry | v3; strict v1/v2 in-memory migration |
| v1 migration | PASS; manual configuration, token, revision and output preserved |
| v2 migration | PASS; source IDs/payloads/URL preserved, schedules Off; no scan migration write |
| Existing Fixed URL | PASS; auto success/failure/recovery retain prefix/token/URL |
| Auto Refresh Off default | PASS; no network or registry write during all-Off scan |
| 15m / 30m / 1h / 3h / 6h / 12h / 24h | PASS; fixed-clock due tests for all seven intervals |
| Next Refresh | PASS; actual success time + interval, UTC UI, Off displays `—` |
| Manual reschedule | PASS; manual refresh before due time resets schedule |
| Interval changes / Off | PASS; successful Save resets interval; Off clears next/failures and preserves history |
| Disabled subscription / source | PASS; no network; re-enable uses preserved schedule / refreshes source |
| Backoff | PASS; 5m / 15m / 30m / 1h / 2h / 6h / 6h |
| Success reset | PASS; failure count zero, last error cleared, configured interval restored |
| Last-good cache | PASS; HTTP and invalid-content failures keep last-good payload and YAML |
| Auto failure Fixed URL 200 | PASS; anonymous web route and healthz remain 200 |
| Auto recovery | PASS; same URL serves recovered nodes and Ready metadata |
| Refresh history | PASS; save/manual/auto outcomes, five newest UI records |
| History limit | PASS; twenty stored records, exact five-field shape |
| Secret redaction | PASS; logs/history exclude remote URL, query token, node URI, credential UUID and Fixed token |
| No network under lock | PASS; concurrent public read and management finish while fetch is paused |
| Optimistic concurrency | PASS; edit/disable/link regeneration/delete/source disable reject stale automatic candidate |
| Conflict history | Log-only; stale outcomes never annotate newer user state |
| Scheduler singleton | PASS; two actual CLI subprocesses, only one fetch, duplicate exits 0 |
| Maximum due work | PASS; 32 sources normally, deferred source entirely unchanged; unsplit 63-source exception |
| Failure isolation / no cache | PASS; old output retained and later subscriptions continue |
| Atomic rollback | PASS; injected errors before/after registry replacement retain selected cache/revision |
| Critical state | PASS; corrupt schema/JSON, unsafe permissions, lock symlink/FIFO fail closed with sanitized nonzero exit |
| Systemd service / timer | PASS; fixture/static validation of emitted units and all required settings |
| Install | PASS; units created, timer enabled/started before web readiness |
| Update | PASS; all existing units backed up, timer/oneshot stopped before state backup/code replacement |
| Uninstall | PASS; timer stopped/disabled, worker stopped, units removed, retained state preserved |
| Stop failure | PASS; failed timer/worker stop aborts before state backup/code deletion |
| Fixed /s / V2 /s / Legacy /s / Temporary /t | PASS; full route regression suite |
| Auth / CSRF / draft / Preview / Generate / Fixed CRUD / External Sources | PASS; full pytest and browser suites |
| Browser | PASS; seven Preview viewports, Fixed lifecycle, External schedules/cache/recovery/upload lifecycle at 1440/390 |
| Python syntax | PASS; 52 app/core/scripts/tests files |
| Node syntax / bash -n | PASS; six JS/CJS files / six shell files |
| pip check | PASS; no broken requirements, no new dependencies |
| ShellCheck 0.9.0 / 0.11.0 | PASS; all six shell files |
| Bootstrap synchronization | PASS; `build_bootstraps.py --check`; remote resolver entrypoints unchanged |
| Diff / removed README contact | PASS |
| Default YAML | Byte-for-byte unchanged; 10,410-rule round trip PASS |
| Default SHA256 | `a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b` |
| VERSION / Latest Stable | 1.1.1 / v1.1.1 unchanged |
| Tag / Release | NO new tag / NO new Release |
| Stable install/update resolution | PASS; both standalone `--resolve-only` commands resolve v1.1.1 |

Implementation is covered by `tests/test_auto_refresh.py`, updated deployment
fixtures and the extended `tests/test_external_browser.cjs`. Operator instructions,
architecture and rollback details are in [AUTO_REFRESH.md](AUTO_REFRESH.md).

Validation ran on macOS using an isolated Python 3.12 environment and temporary
application/deployment state. `systemd-analyze` is unavailable here, so systemd
acceptance is **fixture/static**, not a live Linux timer execution. No real `/opt`,
systemd unit registration or service account was changed. This stage does not
claim that the new main SHA has been deployed on a real VPS.

The oneshot uses a 20-minute timeout to accommodate a single unsplit 63-source
group. A monotonic timer does not replay missed ticks through Persistent; its boot
wakeup scans overdue UTC schedules. Worker conflicts are sanitized log outcomes
and never write history over newer user state.

After pushing, verify the exact final commit equals origin/main and the worktree is
clean; final commit identities are returned in the development handoff.

Test VPS:

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh \
  | sudo bash -s -- --channel main
systemctl status clash-yaml-manager --no-pager -l
systemctl status clash-yaml-manager-refresh.timer --no-pager -l
systemctl list-timers clash-yaml-manager-refresh.timer
journalctl -u clash-yaml-manager-refresh.service -n 50 --no-pager
curl -i http://127.0.0.1:8899/healthz
```

Expected web: `v1.1.1-dev+<new-sha>` / DEV, active (running). Expected timer:
loaded, enabled, active (waiting). Expected health: HTTP 200.
