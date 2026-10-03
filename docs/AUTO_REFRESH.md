# Fixed Subscriptions — Automatic Refresh

Automatic Refresh is included in Stable v1.3.2. Its Hysteria2 inputs are main-only,
frozen for the v1.4.0 candidate; see [Hysteria2 Final Audit](HYSTERIA2_FINAL_AUDIT_REPORT.md).
The [v1.2 Final Audit](FINAL_AUDIT_REPORT.md) preserves historical acceptance.

Use explicit `--channel main` to test the unreleased Hysteria2 inputs. This source worker does not perform health or policy probing; independent
opt-in health scheduling and policy generation are documented separately.

## Management

Each Remote URL source has an Auto Refresh selector: **Off** (default), 15 minutes,
30 minutes, 1 hour, 3 hours, 6 hours, 12 hours or 24 hours. Manual and Uploaded
sources have no automatic refresh. Save fetches enabled remote sources using the
existing validation/cache rules. A successful fetch and parse starts the selected
interval from the actual success time. Save interval changes before using Refresh,
whose actions always operate on saved settings.

Last Attempt, Last Success, Next Refresh and Consecutive Failures appear below the
remote source. Times are UTC; Next Refresh is `—` when Off. Recent Refreshes is
collapsed initially, shows the newest five records, and stores at most twenty.
Triggers are SAVE, MANUAL and AUTO; results are SUCCESS, CACHED, ERROR or CONFLICT.
Only allowlisted error codes are stored and mapped to safe UI messages.

Turning Off clears the next time and failure count, retaining history and payload.
Changing an enabled source's interval and successfully saving resets its next time.
Disabled subscriptions skip all automatic work and retain their schedule; enabling
an overdue subscription makes it eligible on the next scan. Disabled sources retain
their interval and cache, contribute no nodes and make no network requests. Enabling
a source attempts a refresh and computes the next time from that outcome.

Manual Refresh / Refresh All always work, including before the scheduled time.
Success resets the failure count and starts a fresh normal interval. A failure with
usable last-good data keeps the Fixed URL working, records CACHED, and retries after:

| Consecutive failure | Retry delay |
| --- | --- |
| 1 | 5 minutes |
| 2 | 15 minutes |
| 3 | 30 minutes |
| 4 | 1 hour |
| 5 | 2 hours |
| 6 and later | 6 hours |

Any later fetch + parse success resets this backoff. HTTP 200 with invalid content
uses the same failure rules. Auto Refresh never changes the prefix, bearer token or
Fixed URL. Regenerate Link remains the explicit token-changing operation.

## Worker and systemd

The web process has no refresh thread, scheduler hook or background job dependency.
The timer runs `venv/bin/python -m core.auto_refresh --once` from the installation
directory. It never imports the Flask application. A nonblocking private
`state/auto_refresh.lock` uses the shared `core.state.file_lock` primitive; duplicate
workers immediately exit 0 with `Auto refresh already running.`

Canonical deployment helpers write `clash-yaml-manager-refresh.service` and
`clash-yaml-manager-refresh.timer`. The service is Type=oneshot, runs as
clashyaml:clashyaml, loads `.env` through systemd, and uses UMask=0077,
NoNewPrivileges=true and PrivateTmp=true. TimeoutStartSec is **20min** to cover the
existing maximum of 63 external sources in one unsplit group, each with a 15-second
fetch budget, plus parsing and generation. The timer uses OnBootSec=2min,
OnUnitActiveSec=5min, AccuracySec=30s, RandomizedDelaySec=30s and Persistent=true.
This is a monotonic timer: Persistent does not replay missed five-minute ticks.
After boot, the worker scans overdue epoch timestamps normally. Actual timing may
be a few minutes after the stored due time; long runs finish before another instance
can run. Success schedules from completion time, avoiding catch-up loops.

A scan processes oldest due work first, normally at most 32 remote sources. Sources
within a subscription are never split: all due sources share one candidate and one
generation/commit; other remote caches, Manual and Uploaded sources are preserved.
A subscription with over 32 due sources may run alone, up to the existing 63-source
limit. Groups that do not fit are left completely untouched for a later scan.

Provider failure and usable cache are ordinary outcomes (exit 0), as is an empty
scan. A failed candidate without usable cache leaves the selected YAML/revision
intact and, when the snapshot is still current, records ERROR with retry metadata.
Aggregation/generation errors also preserve the complete old revision and record
safe failure metadata. One subscription's failure does not block other selected
subscriptions. Corrupt registry/schema, unsafe state/lock permissions, disk errors
or unexpected internal errors stop the run with nonzero status and a generic
critical message. No exception text or traceback is written to the journal.

## Atomicity, concurrency and security

The existing revision transaction snapshots metadata and all required private
files under the registry lock, releases it before network/parse/generate, then
checks the full optimistic identity before committing an atomic registry pointer.
Several due sources are aggregated once. Public requests only read the selected
YAML and never fetch; access-statistics writes are excluded from conflict identity.

An edit, disable, source mutation, Regenerate Link or Delete while a refresh is in
flight invalidates its candidate. The stale candidate is discarded and logged as
CONFLICT. Its history is **not appended to newer state**, because even a history
write would overwrite a user mutation's metadata. The schema accepts a conflict
record for future use, while current conflict outcomes live only in sanitized logs.
Failed disk commits retain the prior pointer/cache/output using the existing
rollback path. Runtime directories/files are 0700/0600; lock symlinks, nonregular
files and unsafe permissions fail closed.

Fetch retains the External Sources SSRF, DNS/IP pinning, redirect, HTTPS CA, direct
connection, bounded time/body and supported-protocol parser protections. Main's
Hysteria2 input subset is documented in [Hysteria2 Protocol](HYSTERIA2_PROTOCOL.md)
and is not included in Stable v1.3.2. No proxy
environment, cookies, authorization or Referer is forwarded. History contains only
`at`, `trigger`, `result`, `node_count` and an allowlisted `error` code. Worker logs
contain counts, internal subscription IDs and results; no source URLs, query tokens,
node URIs, credential UUIDs, response bodies or Fixed bearer tokens are included.

## Registry v6 migration

Versions 1, 2 and 3 normalize in memory with Preserve / Preserve policy defaults (see [POLICY_ENGINE.md](POLICY_ENGINE.md)). Existing v1 manual sources remain intact; v2
remote sources receive Off, null next time, zero failures, null trigger and empty
history. Reading, upgrading or scanning an all-Off registry makes no network
request and performs no migration write. Public access-statistics writes preserve
the original disk schema. A successful management mutation or required scheduler
mutation writes v6 atomically, including Health-aware and GeoIP defaults from
[Fixed Subscriptions](FIXED_SUBSCRIPTIONS.md). Existing v3 refresh schedules remain unchanged. Migration preserves token/prefix/URL, source IDs,
revision and exact YAML/payload bytes. Corruption is never repaired by resetting
the registry. Scheduled fields use UTC epoch seconds and an injected core clock;
clock rollback safely postpones future work.

## Deployment and operations

The source scheduler writes its service/timer pair beside the app unit (the health
scheduler has its own additional pair). Install reloads systemd, enables the web service, enables
and starts the timer, restarts the web service and checks web readiness. Update
backs up deployment files and all existing units, then stops the timer and oneshot
before stopping web, backing up state, migrating credentials or copying code. A
stop failure aborts the update. State, caches, schedules and history are preserved.
Uninstall stops/disables the timer, stops the oneshot, then handles web and removes
all three units; choosing to keep the installation keeps state. Runtime backups
include the complete private state required to restore fixed subscriptions.

Test VPS update (development only):

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh \
  | sudo bash -s -- --channel main
systemctl status clash-yaml-manager --no-pager -l
systemctl status clash-yaml-manager-refresh.timer --no-pager -l
systemctl list-timers clash-yaml-manager-refresh.timer
journalctl -u clash-yaml-manager-refresh.service -n 50 --no-pager
curl -i http://127.0.0.1:8899/healthz
```

Expected: web active (running), timer loaded/enabled/active (waiting), `/healthz`
HTTP 200 and web build `v1.3.2-dev+<resolved-main-sha>` / DEV before v1.4.0 publication. `/healthz` represents
web readiness only; it does not depend on provider availability or timer state.
For a manual worker run use `sudo systemctl start clash-yaml-manager-refresh.service`.
To pause automatic refresh globally use `sudo systemctl stop clash-yaml-manager-refresh.timer`;
also stop the oneshot before taking a consistent backup or replacing state/code.

For rollback, stop timer, oneshot and web first; restore backup deployment files,
venv, `.env`, defaults and matching units. Remove newly added refresh units if the
backup predates this feature. v4 state is not readable by old v1/v2/v3 code: returning
to that code requires restoring its matching private state backup, which also
restores authentication/subscriptions to that backup time. Check password versions,
tokens and revisions together before restarting. Never expose backup credentials.
Reload systemd and start the units that belong to the restored deployment.

Tests use temporary installations and command doubles. Real Ubuntu timer execution
and this new main SHA on an operator's VPS require the above deployment; local
fixture/static unit checks do not claim a real VPS result.
The user-attested deployment of `b68a84b` and timer activation are recorded
separately in [Hysteria2 Final Audit](HYSTERIA2_FINAL_AUDIT_REPORT.md); they do not
establish a real Hysteria2 provider refresh or proxy forwarding.
