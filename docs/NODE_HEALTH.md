# Node Health: Endpoint Reachability (main development)

**This is endpoint reachability, not end-to-end proxy validation.** The result
answers only whether this VPS can open a TCP connection to the saved node's
`server:port`. It does not authenticate VMess/VLESS, negotiate TLS/WebSocket/Reality,
forward traffic, measure throughput or prove that an internet destination works.
VERSION and Latest Stable remain **1.1.1 / v1.1.1**; this feature is on explicit
`--channel main` only.

## Use and meaning

On a Fixed Subscription Edit page, Health Checks starts **Off** for new subscriptions; upgrades preserve existing
Off/Manual modes. Set it to **Manual** or **Automatic**, save the setting, then choose **Check
Now**. The check reads the current committed `current.yaml` and reports Total,
Healthy, Suspect, Unhealthy, Unknown and Last Check. Each supported row shows Node,
Protocol, Status, Connect Latency, Consecutive Failures, Last Checked and Last
Success (UTC). Names that would expose a server address, credential UUID,
Fixed bearer token or URI
are replaced with a generic node label in the health table. The original YAML is
unchanged.

Unknown means no observation for the current connection identity. The latest TCP
success sets Healthy, clears failures, stores the elapsed connect time and records
Last Checked/Last Success. A failure records an allowlisted code, clears latency,
preserves Last Success, and increments failures. Failures 1–2 are Suspect; failure
3 and later is Unhealthy. A later success immediately resets failures to zero.
The latency is monotonic TCP connect time, rounded to an integer millisecond in UI.
An Unhealthy node remains in the generated YAML and all proxy groups. Health never
selects a fastest node, removes an endpoint or changes policy/rules. Check Now is
available manually, with opt-in Automatic mode documented in
[AUTOMATIC_HEALTH.md](AUTOMATIC_HEALTH.md). The separate health timer runs
scheduled checks; the Automatic Refresh timer does not run health checks.

## Private state and identity

`state/node_health.json` (0600) and `state/node_health.lock` (0600) are independent
of the authoritative v3 Fixed registry and selected YAML revision. Health has its
own schema version 2 (read-compatible with v1) and stores scheduling metadata,
per-subscription mode, Last Check and at most 256
per-node records. Records are keyed by SHA256 of canonical, plain supported proxy
configuration **excluding only the root `name` key**. Canonical JSON uses sorted
mapping keys. This covers protocol, server, port, UUID, network, TLS, SNI,
WebSocket/Reality options, ALPN, fingerprints and other ordinary connection
settings. A name-only edit keeps the fingerprint; any connection-config change
gets a new identity and displays Unknown until checked. This hash is an opaque
identifier, not a reversible credential store.

Records contain only status, failure count, connect latency, UTC epoch timestamps
and an allowlisted error code. No server/IP, port, UUID, source or Fixed token,
remote URL, or node URI is written. Logs contain only internal subscription ID and
aggregate counts; neither endpoint nor fingerprint is logged. The private reader
opens with `O_NOFOLLOW|O_NONBLOCK`, checks regular-file type and permission bits,
then validates the schema. Symlinks, FIFO/device files, world-readable files and
corruption fail closed for the health section without resetting state. Public
`/s/<fixed>` and `/healthz` never read auxiliary health state and remain governed
by their original Fixed/web behavior. The auxiliary JSON read is capped at 128 MiB;
duplicate keys and nonfinite JSON numbers are rejected before schema validation.

Mode changes and Check Now never write the Fixed registry, create a Fixed revision,
rewrite `current.yaml`, change its token, or fetch a remote provider. Regenerate
Link keeps health by node identity. When source removal changes the generated
revision, old fingerprints are hidden; a successful Check Now retains only current
fingerprints. Fixed deletion best-effort removes its auxiliary entry. Cleanup
failure cannot undo the authoritative deletion; later health reads prune stale
subscription entries. Install/update preserve the state directory naturally, and
uninstall backup includes `node_health.json` with the rest of private state.

## TCP probe and SSRF controls

Only VMess/VLESS proxies in the current committed YAML are targets. Extraction
requires a nonempty server and integer port 1–65535 (boolean is not an integer);
future unsupported proxy types are ignored. No browser draft, provider response,
source payload or re-aggregation supplies check targets. Proxies are parsed with
the existing safe YAML/structural budget, and the extracted config is used only
for this observation. The health-only YAML input is bounded to 50 MiB.

Each node has a total **three-second budget** for DNS plus TCP connect. Hostnames
are resolved through the existing short-lived bounded DNS child. Every returned
IPv4/IPv6 answer must be globally routable. Loopback, private, link-local,
multicast, unspecified, reserved, transition-encapsulated and metadata addresses
are refused. A mixed public/private response blocks the entire target; it never
filters out only the private answer. IP literals use the same validation without
DNS. The connection is made to the validated **numeric sockaddr**; the hostname
is never resolved again by socket.connect. There is no HTTP library or proxy
environment support. The socket sends no application bytes, then closes.

DNS failure, blocked address, timeout, connection refused, network unreachable
and other connect failures map to fixed error codes. Exception text, DNS response
details and provider content never enter private health records, HTML or logs.
Sixteen threads bound a single manual run. A check of more than **256** supported
nodes stops before any network call or state write and tells the operator the
limit; it never silently checks only a prefix. Identical connection fingerprints
within the same YAML are probed once but remain visible as separate named rows.
The web Gunicorn timeout remains 300 seconds.

## Concurrency and failure handling

The check snapshots the subscription ID, exact selected revision and YAML bytes
under the Fixed registry lock. It releases that lock **before** DNS/TCP. On
completion it verifies the revision is still current while briefly acquiring the
Fixed lock and auxiliary lock in that order, then atomically commits the new health
state. Save, manual or automatic refresh, source changes and Delete make a stale
probe conflict: it is discarded, and old health state is left intact. A concurrent
mode change or second completed check similarly rejects a stale health candidate.
Disable/Enable and Regenerate Link keep the same selected revision; an administrator
may check a disabled subscription, while public access remains disabled.

An auxiliary write failure shows `Health results could not be saved.` and leaves
Fixed output/URL unchanged. Registry corruption remains an authoritative Fixed
error; auxiliary corruption or unsafe permissions are a health-only unavailable
state. Health read/write paths never run from public Fixed or `/healthz` requests.

Full protocol authentication, actual forwarding/egress testing, health-based
exclusion, scheduling, scoring, ranking and fastest-node selection are deferred.
There is no new systemd unit, third-party binary, container or external API.

Operator update uses the existing explicit main channel:

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh \
  | sudo bash -s -- --channel main
systemctl status clash-yaml-manager --no-pager -l
curl -i http://127.0.0.1:8899/healthz
```

The preceding Automatic Refresh build `7051a8a` was verified on a real VPS for
web readiness, timer/oneshot activation, `systemd-analyze verify` and an empty
scan. No real scheduled provider refresh was observed there. This Node Health
phase is verified with controlled fixture probes until a new real-VPS acceptance
is performed; it does **not** claim real provider reachability or full proxy
operation.
