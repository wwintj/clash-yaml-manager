# Automatic Health Scheduler MVP (Unreleased / main)

VERSION stays **1.1.1**; Latest Stable stays **v1.1.1**. Automatic health is
opt-in and observational. Endpoint and Full Proxy results are separate; no job
changes committed `current.yaml`, nodes, groups, policies, Fixed tokens or URLs.
Health reads saved YAML only: it never fetches providers, refreshes sources,
aggregates subscriptions or reads browser drafts.

## Modes and configuration

Both cards support **Off**, **Manual** and **Automatic**. New subscriptions
start Off; existing Off/Manual settings retain their mode. Check Now remains
available in Manual and Automatic. Automatic Proxy checks require an already
COMPATIBLE managed Mihomo; Web never installs, updates or starts a permanent
engine daemon. Engine management remains the existing SSH/root helper workflow.

Automatic requires one of **15m, 30m, 1h, 3h, 6h, 12h or 24h**. Arbitrary cron
expressions are not accepted. Enabling Automatic, changing its interval or
changing its effective proxy target schedules the first run at **now + interval**.
Saving the same settings preserves the existing due time. Settings requests do
not run a health probe. Custom proxy target validation retains its existing DNS
safety check; it is not a probe. Off/Manual have null interval and next-check time.

The UI shows Last Check, Next Automatic Check, Last Trigger and Scheduler Result.
The next-check value is a due time, not a promise of exact execution: timer jitter,
older jobs, a running service, disabled subscriptions and the per-scan limits can
make a job run later. Times are displayed in UTC. The cards do not combine
Endpoint and Proxy into a score, rank nodes or select a best node.

## Independent state and migration

`state/node_health.json` and `state/proxy_health.json` remain separate; the Fixed
health scheduling does not require a registry schema change; Policy Engine separately adds Fixed v4 (see [POLICY_ENGINE.md](POLICY_ENGINE.md)). Both health files use schema **v2**, with per-entry
mode, `interval_seconds`, `next_check_at`, `scheduler_failures`, `last_trigger`,
`last_job_result`, `check_revision`, existing `last_check_at` and node observations.
Proxy also retains global/custom probe settings.

Validated v1 files migrate **in memory**: Off/Manual stay unchanged, interval and
next check are null, scheduler failures and internal check revision are zero,
and scheduler trigger/result are null. Node observations and proxy settings are
retained. Reading/startup does not rewrite the file or start network activity;
the next legitimate settings, result or cleanup write persists v2. Files and
locks remain private 0600 in the service user's 0700 state directory. Corrupt
auxiliary state is not reset or replaced with empty data.

The internal check revision advances on changed settings and completed checks,
including identical observations at the same clock value. It prevents stale
manual/automatic results from merging. A busy/retry bookkeeping update does not
invalidate the manual proxy job holding the global probe lock; its normal
completion can reset the schedule.

## Shared check path and scheduling outcomes

`NodeHealth.check(..., trigger='manual'|'auto')` and `ProxyHealth.check(...)`
share their existing fingerprinting, limits, probes, thresholds and optimistic
Fixed revision checks. Manual is allowed in Manual/Automatic; auto is allowed
only for a due Automatic entry on an active Fixed Subscription. No network or
Mihomo operation holds the Fixed registry lock. Results commit under short
Fixed → auxiliary locks after checking revision and configuration/result state.

A completed job can contain Healthy, Suspect, Unhealthy or Unsupported nodes.
It records `success`, clears scheduler failures and, in Automatic mode,
schedules **completion time + configured interval**. This includes a manual
Check Now in Automatic mode, preventing an immediate duplicate timer check.
An empty supported-node set also completes normally. The existing whole-job
limit is 256 supported nodes; excess nodes cause a job-level `limit` failure,
never a partial first-256 check.

Endpoint node failures still produce Suspect at failures 1/2, Unhealthy at 3+,
and Healthy/0 on recovery. Proxy uses the same thresholds; Unsupported does not
increase node failures. Engine/controller/internal job errors preserve all node
observations and their last-check timestamps; scheduler failures are separate.
Manual job failure retains the existing schedule and observations.

Automatic job-level errors use **5m → 15m → 30m → 1h → 2h → 6h**, capped at 6h.
The configured interval stays unchanged. Missing, incompatible or broken Mihomo
records `engine_unavailable` with this backoff; it does not affect Endpoint,
Fixed, Generate or healthz. Successful completion restores the normal interval.

A busy `state/proxy_probe.lock` or revision/state conflict records `busy` or
`conflict`, keeps node observations and scheduler failure count unchanged, and
retries after about 5 minutes. Retry bookkeeping is committed only if the entry
and relevant global settings still match the snapshot. Newer administrator
settings or a newer completed check win; they are never overwritten merely to
force a retry. Deletion does not recreate state. Disabling a Fixed Subscription
pauses selection without erasing configuration or observations; overdue work
can run after re-enabling. A disable during an automatic probe discards its result.

## Separate systemd worker and bounded work

`clash-yaml-manager-health.timer` invokes the oneshot
`clash-yaml-manager-health.service`, which runs:

```text
/opt/clash-yaml-manager/venv/bin/python -m core.auto_health --once
```

There is no Flask/Gunicorn scheduler, background application thread, APScheduler
or daemon loop. The worker runs as **clashyaml:clashyaml**, UMask 0077,
NoNewPrivileges and PrivateTmp, with a **15-minute** start limit, **10-second**
stop limit and `KillMode=control-group`. Gunicorn timeout is unchanged. SIGTERM
and SIGINT unwind the existing probe cleanup and release locks; systemd also
bounds the whole process group if graceful termination fails.

The timer uses OnBootSec=2min, OnUnitActiveSec=5min, AccuracySec=30s,
RandomizedDelaySec=30s and Persistent=true. Per the
[systemd timer definition](https://github.com/systemd/systemd/blob/v257/man/systemd.timer.xml),
Persistent only affects calendar timers; this monotonic timer's restart catch-up
comes from persisted due timestamps and its first scan after boot. Systemd does
not restart an already active oneshot on another timer tick.

A nonblocking `state/auto_health.lock` permits only one scan; a competing scan
logs a generic message and exits 0. Each scan selects oldest due time first,
then stable internal subscription ID, with at most **4 Endpoint subscriptions**
and **1 Proxy subscription**. It runs complete subscriptions, not node subsets.
Proxy shares the existing `state/proxy_probe.lock` with manual checks and uses
exactly the existing ephemeral Mihomo config/controller/process implementation.
Only a bounded set of jobs runs per invocation; the worker then exits.

The source refresh timer and `core.auto_refresh` remain independent. Source
refresh may change a Fixed revision during health work; the stale health result
is discarded and, if its auxiliary snapshot still matches, receives a safe retry.

## Deployment, recovery and privacy

Install/update enables and verifies the health timer separately from the source
refresh timer. Update backs up all five unit files, stops both timers/oneshots
before backing up state or replacing code, and preserves both health JSON files
and the optional managed `bin/` engine. Health unit files are staged privately on
the same filesystem before replacement. A write/replacement/activation/verification
failure restores the previous health pair and prior timer flags; update stops
with its existing deployment backup and manual code/venv rollback guidance.
If unit rollback itself fails, recovery files are retained and the script reports
the failure instead of claiming recovery. Full uninstall stops/disables/removes
both health units and preserves health JSON in the existing selected state backup.
Sensitive `.proxy-probe-*` scratch directories remain excluded from backups.

Logs contain only internal subscription ID, job type, node count and fixed result
codes. They exclude node names, endpoints/ports, UUIDs, URIs, provider URLs, Fixed
tokens, controller secrets, config contents and raw errors/tracebacks. Corrupt
Node Health state does not stop Proxy work; corrupt Proxy state does not stop
Endpoint work. If safe state cannot be read/written, it stays untouched and only
a generic scheduler error is logged; restore a consistent private backup or fix
permissions before relying on retry metadata.

## tim VPS acceptance: a real timer run is required

The preceding manual proxy/amd64-v2 acceptance is
**OPERATOR-ATTESTED REAL VPS ACCEPTANCE**, recorded in
[PROXY_HEALTH_REPORT.md](PROXY_HEALTH_REPORT.md). Automatic real health acceptance remains **PENDING / NOT FULLY CLOSED**.
The operator reports a real installed/enabled/active(waiting) health timer, one
actual auto_health timer trigger that exited 0 with **endpoint=0 proxy=0**, real
tim systemd-analyze verify PASS, managed engine COMPATIBLE and healthz 200.
Codex did not independently reproduce that run. Actual timer-triggered **due
Endpoint and due Proxy jobs** have not been supplied. Controlled tests and an
empty scan do not establish real scheduled VMess/VLESS checks.

Deploy explicit main and inspect the actual units:

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh \
  | sudo bash -s -- --channel main
sudo systemctl status clash-yaml-manager-health.timer --no-pager -l
sudo systemctl status clash-yaml-manager-health.service --no-pager -l
sudo systemctl is-enabled clash-yaml-manager-health.timer
sudo systemctl is-active clash-yaml-manager-health.timer
sudo systemctl list-timers --all --no-pager
sudo systemctl cat clash-yaml-manager-health.service clash-yaml-manager-health.timer
sudo systemd-analyze verify \
  /etc/systemd/system/clash-yaml-manager.service \
  /etc/systemd/system/clash-yaml-manager-refresh.service \
  /etc/systemd/system/clash-yaml-manager-refresh.timer \
  /etc/systemd/system/clash-yaml-manager-health.service \
  /etc/systemd/system/clash-yaml-manager-health.timer
sudo bash /opt/clash-yaml-manager/mihomoctl.sh status
curl -i http://127.0.0.1:8899/healthz
```

A oneshot that has finished normally may show inactive (dead); its exit/result
and the timer's active (waiting) state are what matter. On one dedicated active
Fixed Subscription with valid real VMess/VLESS nodes, set Endpoint and Proxy
**Automatic / Every 15 minutes**. Record its Fixed URL, privately record/hash
its current YAML, the Next Automatic Check times and the operator's start time.
Do not immediately click Check Now, which would postpone its schedule.

**Wait for the due time and a genuine timer invocation** (allow scan jitter and
older work), then inspect:

```bash
sudo journalctl -u clash-yaml-manager-health.service --since '25 minutes ago' --no-pager
sudo systemctl show clash-yaml-manager-health.service \
  -p Result -p ExecMainStatus -p ExecMainStartTimestamp -p ExecMainExitTimestamp
sudo systemctl show clash-yaml-manager-health.timer \
  -p ActiveState -p LastTriggerUSec -p NextElapseUSecMonotonic
ps -eo user,pid,args | awk '$1 == "clashyaml" && /[m]ihomo/ {print}'
sudo find /opt/clash-yaml-manager/state -maxdepth 1 -type d -name '.proxy-probe-*'
curl -i http://127.0.0.1:8899/healthz
```

Confirm journal evidence of both due jobs with safe internal IDs/results,
`last_trigger=auto`, advanced next-check times, healthy real nodes, unchanged
Fixed URL/YAML, working public `/s`, no leftover Mihomo process/config directory,
healthz 200 and no credentials in the journal. Check raw private health metadata
locally if needed; it should agree with the UI. Preserve the two timer units as
separate responsibilities. Merely `systemctl start ...health.service` does not
satisfy timer-triggered acceptance. Notifications, node exclusion, policy/group
rewriting, ranking, permanent engine and general Settings remain out of scope.
