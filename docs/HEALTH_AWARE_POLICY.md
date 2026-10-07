# Health-aware Policy Integration MVP

Health-aware Policy 已隨 v1.2.0 提供；正式可用版本以
[README Latest Stable](../README.md) 為準。[Final Audit](FINAL_AUDIT_REPORT.md)
保留早期推出、migration 與 deferred 驗收的歷史記錄。只有明確授權的開發部署
使用 `--channel main`。

v1.6.0 的 [Default profile](DEFAULT_YAML_COUNTRY_GROUPS.md) 在 Health transform
之後投影主 selector 的引用，不重建已過濾的 country／special group 成員或改寫
Policy metadata。Custom 排序、Health 的 freshness／minimum／fail-open 契約不變。

## Settings and scope

Only authenticated Fixed create/edit has these optional settings:

```json
{"mode":"off","max_age_seconds":172800,"min_candidates":2}
```

Mode is `off` or `exclude-unhealthy`. Freshness is exactly 3600 / 21600 / 86400 /
172800 / 604800 seconds (1h / 6h / 24h / **48h default** / 7d). Minimum candidates
is an exact integer **1–16**, default **2**. Unknown keys/modes, bool-as-int,
floats and unsupported values are rejected. Failed POST values remain editable;
rejected settings are not stored in cookies, session storage or local drafts.
Temporary Generate has no controls or health-state reads.

Only actual generated node candidates in the existing managed Country and
explicitly selected Special scopes with policy type `url-test`, `fallback` or
`load-balance` can be excluded. Special scope retains its existing precedence
on overlaps. Preserve and Select are untouched, even when the preserved base
happens to use an automatic type. General/manual groups, unrelated custom or
provider groups, unselected Special groups and rule targets remain unchanged.

Top-level `proxies` and source/manual node definitions always remain. The
existing manual Select escape path still offers the excluded node. Proxy probes
read all top-level nodes, so an excluded candidate can later recover. There is
no ranking, score, latency sorting, weighting, best-node selection or protocol
conversion. Retained candidates keep their original generation order.

## Conservative eligibility and per-group fail-open

Only **Full Proxy Health** can exclude. Endpoint Health is never consulted.
A matching connection fingerprint must have status **UNHEALTHY**, at least
**three consecutive failures**, and a valid `last_checked_at` with
`0 <= now - last_checked_at <= max_age_seconds`. The exact boundary is fresh.
`last_success_at` does not determine freshness. Future timestamps fail open,
including clock rollback; invalid timestamps cannot exclude.

Healthy, Suspect (failures 1/2), Unknown, Unsupported, missing and stale records
remain. A name-only edit uses the same fingerprint; connection/credential changes
produce a new identity and cannot inherit exclusions. The shared identity module
preserves the pre-phase fingerprint serialization/hash algorithm byte-for-byte.

For each automatic group, calculate `required = min(min_candidates, original_count)`.
If exclusion leaves fewer than required, restore **all original candidates for
that group only**. Other groups may still filter safely. A single unhealthy node
therefore stays. An explicit zero-candidate policy remains the Policy Engine's
existing generation error, with no invalid revision committed.

Missing, corrupt, duplicate-key, unsafe-permission, symlink, FIFO, unreadable or
busy Proxy auxiliary state makes the entire generation retain original candidates.
It is not repaired/reset or replaced with an empty health file. Authoritative
Fixed v6 corruption remains fail-closed, preserving the existing state contract.
Proxy mode Off or an unavailable engine produces a nonblocking UI warning:
existing observations can still be fresh, but new observations will not arrive
and old ones eventually expire. Engine presence is not eligibility evidence.

## Registry and generation transaction

Fixed registry **v6** stores `health_policy` and a safe `health_policy_audit`.
Reading v1/v2/v3/v4 supplies **Off / 48h / 2** and empty audit in memory. It does
not rewrite files, generate output, rotate tokens or touch caches/schedules.
Existing v4 policy choices remain; earlier Preserve migration remains unchanged.
Public Last Access statistics preserve the legacy disk version. A legitimate
management/scheduler mutation writes v6. No existing subscription opts in.

`core/policy_engine.py` remains pure: no health imports, reads, files or probes.
`core/health_policy.py` applies eligibility after normal policy construction and
before the shared generator's final structure/reference checks. A generation
uses one deterministic observation/time snapshot, after provider work if any.
Manual and automatic source refresh preserve both settings and apply current
observations to newly parsed membership; new fingerprints remain Unknown.

Snapshot reads hold only the short nonblocking Proxy lock, released before
aggregation/generation. Commit verifies the unchanged Fixed management identity
and, when usable observations affected eligibility, unchanged Proxy entry/global
state under **Fixed → Proxy** locks. No reverse lock acquisition occurs. A stale
candidate loses to newer saves, source refresh, delete, disable or health checks.
Unavailable snapshots make no exclusions and may commit the safe original set.
No network, DNS or engine execution holds either state lock. Public `/s` and
`/healthz` stay responsive during generation and probes.

## Reactive and periodic reconciliation

A successful Manual or Automatic Proxy check first commits its observations and
scheduler result and releases locks. It then calls Fixed reconciliation when
filtering and an automatic policy scope are enabled. Engine failure, busy job,
revision conflict or failed health commit never launches reactive reconciliation.

Reconciliation snapshots the current Fixed config, **committed `base.yaml`**,
manual configuration and persisted payloads of all enabled external sources.
It reuses parsing, aggregation, policy generation and immutable candidate commits.
It never fetches a URL, refreshes source status, probes nodes, starts Mihomo or
reloads `defaults/default.yaml`. Disabled source caches are preserved as well.
Identical YAML only updates safe audit metadata: no new revision, no Updated
change. Changed output atomically selects one complete revision, retaining URL,
token, prefix, sources/caches, source schedules and both health schedules.

Reconciliation errors retain selected Fixed YAML and successful Proxy observations.
The successful health job stays success, with its normal interval and zero
scheduler failures. A separate safe error audit/warning is recorded when the
snapshot is still current. Conflicts do not overwrite newer audit or output.

The existing `auto_health` singleton periodically selects up to **three** active,
enabled entries by oldest reconciliation time then internal ID. It runs before
network checks; at most one due Proxy completion adds a fourth attempt per scan.
This permits stale results to be restored even without another successful probe.
Disabled subscriptions are skipped; re-enabled ones become eligible again.
No new timer, service, queue, daemon or loop is introduced. Fairness is bounded
by healthy state writes and successful scans, not a precise expiry-time guarantee.

## Audit and evidence boundary

Authenticated UI shows saved mode/freshness/minimum, last reconciliation UTC,
result `off` / `unchanged` / `updated` / `fail-open` / `unavailable` / `error`,
whether YAML changed, filtered-group count, excluded-candidate count and
fail-open-group count. Excluded count is **membership removals**, so one node
removed from two groups counts twice; groups restored by fail-open count zero
removals. `fail-open`/`unavailable` can coexist with changed YAML (restoration).
Logs contain only internal IDs, counts and allowlisted results; no node names,
endpoints, ports, UUIDs, URIs, provider credentials or subscription bearers.

Controlled tests use synthetic nodes and doubles, not real working proxies.
**REAL VPS HEALTH-AWARE POLICY: NOT RUN. REAL VPS POLICY: NOT RUN.**
Real timer-triggered due Endpoint and due Proxy Health remain **PENDING**.
Existing operator evidence is limited to timer installed/enabled/active, one real
trigger with endpoint=0/proxy=0, tim systemd-analyze verify PASS, engine COMPATIBLE
and healthz 200. This feature does not close those acceptances.

## Dedicated VPS handoff

Deploy only to the dedicated development VPS, retaining private backups:

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh \
  | sudo bash -s -- --channel main
sudo bash /opt/clash-yaml-manager/mihomoctl.sh status
sudo systemd-analyze verify /etc/systemd/system/clash-yaml-manager-health.service \
  /etc/systemd/system/clash-yaml-manager-health.timer
curl -i http://127.0.0.1:8899/healthz
```

Use at least three **real** nodes in one managed Country group: A valid, B with
an intentionally wrong UUID, C valid. Use private credentials only in the
subscription form, never public evidence. Enable Country Fallback or URL-Test,
Health-aware `exclude-unhealthy` / 48h / minimum 2, and Full Proxy Manual with
COMPATIBLE Mihomo. Save the fixed URL privately and perform three Proxy checks.

1. After failures 1/2, B is Suspect and remains an automatic candidate.
2. After failure 3, B is Unhealthy and excluded from the managed automatic group;
   A/C remain in order. Verify B still exists in top-level proxies and manual
   Select, fixed URL/token unchanged, audit shows one exclusion. Import with the
   pinned Linux Mihomo and a real client and verify the candidate behavior.
3. Restore B's real UUID, save, and successfully check proxies. Confirm B returns
   (the edited credential has a new fingerprint and remains eligible even before
   the success), with Healthy/zero failures and the same fixed URL.
4. In a separate controlled test subscription, A valid and B/C wrong UUIDs, use
   minimum 2. After three failures B/C, confirm the group retains all A/B/C and
   records per-group fail-open. Do not use a production subscription for this.
5. Verify freshness using 1h and an actual wait beyond the latest check timestamp;
   keep Proxy Manual so no fresh check renews it. A real timer scan must restore
   stale candidates without fetching sources or probing nodes. Disabled Fixed
   stays skipped; after re-enable the existing timer can reconcile it.
6. Separately enable Endpoint and Proxy Automatic 15m, wait for **real timer-fired
   due jobs**, and capture sanitized journal counts/results and advanced schedules.
   Empty scans or manual service invocations do not satisfy due-job acceptance.

Record deployment commit, settings, redacted before/after group memberships,
revision transitions, timer journal, engine/client validation and healthz. Keep
all three real acceptances open until their own evidence is supplied.

Current main also stores optional country detection in Fixed v6, with
v1–v5 GeoIP Off migration. Country assignment and health identity remain
independent; see [GEOIP.md](GEOIP.md).
