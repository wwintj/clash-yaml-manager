# Full Proxy Validation MVP (main development)

This feature is on the explicit `--channel main` development build. VERSION is
**1.1.1** and Latest Stable remains **v1.1.1**. It checks whether a saved
VMess/VLESS proxy can carry Mihomo's HTTPS URL probe to one configured target,
including the proxy protocol's authentication and transport path. It is not a
throughput benchmark, general website guarantee, exit-IP check, ranking or
policy engine. TCP Endpoint Health remains an independent observation.

## Operator workflow

Mihomo is optional. The Web app never downloads or installs it, and a normal
project install/update never installs or upgrades it. Generate, public Fixed
subscriptions, External Sources, Automatic Refresh, Endpoint Health and
`/healthz` work without it. On an Ubuntu Linux amd64 or arm64 VPS, first
deploy the development build, then use SSH and sudo:

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh \
  | sudo bash -s -- --channel main
sudo bash /opt/clash-yaml-manager/mihomoctl.sh status
sudo bash /opt/clash-yaml-manager/mihomoctl.sh install
sudo bash /opt/clash-yaml-manager/mihomoctl.sh status
systemctl status clash-yaml-manager --no-pager -l
curl -i http://127.0.0.1:8899/healthz
```

The same helper supports `update` (reverify and replace the pinned version)
and `remove`. No Web install/update button exists. On the Fixed Subscription
Edit page, choose Full Proxy Checks **Manual**, save, then **Check Proxies Now**.
The default is **Off** for existing and new subscriptions, and Automatic Refresh
never launches a proxy check. A disabled Fixed Subscription can still be
checked by an administrator; its public URL remains disabled.

Global probe defaults are `https://www.gstatic.com/generate_204`, expected
HTTP **204**, timeout **8000 ms**. A subscription may use these defaults or
override URL/status/timeout. The target must be public HTTPS without userinfo,
query or fragment; expected status is an integer 100–599; timeout is
3000–15000 ms. The UI offers 5, 8, 10 and 15 seconds. A node unable to reach
this target may still work for another site. The displayed Proxy Latency is
**Mihomo URL probe latency**, not TCP ping or server RTT.
Changing a subscription's effective URL, expected status or timeout clears its
old proxy observations to **UNKNOWN**; changing global defaults does not clear
subscriptions with an unchanged custom override.

## Pinned engine and supply chain

`mihomo-manifest.json` is the sole asset manifest. It pins upstream
[MetaCubeX/mihomo v1.19.31](https://github.com/MetaCubeX/mihomo/releases/tag/v1.19.31)
exactly, for Linux amd64 and arm64 only:

| Platform | Release asset | Compressed SHA256 | Decompressed SHA256 |
| --- | --- | --- | --- |
| amd64 | `mihomo-linux-amd64-v1.19.31.gz` | `d5e74bbddbdfff49a1aef7775bf5911da59f0d7196ed509a0ac914b3653dd5f1` | `08787faafea19c1ab0f83fa5a1b22363b7d03ea78da18091a4c883aecaaa5979` |
| arm64 | `mihomo-linux-arm64-v1.19.31.gz` | `9e0f11afbf38426b8bd88fdc594678f8161c57eccb4e1b77acb12b493904f1d4` | `1b315bc038d05f84ee86d232f3c3d2b020b5044e9b971bb8fe215b6e6a2148f3` |

These hashes were checked against the upstream Release asset metadata and
independently downloaded compressed assets; the decompressed files identify as
Linux ELF x86-64 and AArch64. The macOS development host cannot execute either
Linux binary, so actual CLI behavior and real proxy acceptance still require a
Linux VPS check. The implementation was also checked against upstream
v1.19.31 source at commit
`ab405bad5beeeac8b003bb01f60f134f6df54471`.

`mihomoctl.sh` downloads only the exact manifest URL over HTTPS, bypasses proxy
environment settings, rejects an HTTP redirect, checks exact compressed size
and SHA256, decompresses privately with a size cap, checks the decompressed hash
and ELF architecture, then runs bounded `mihomo -v` and requires
`Mihomo Meta v1.19.31 linux <arch>`. It stages the binary and metadata before
replacing either live file and restores both on an ordinary replacement error.
The managed paths are `/opt/clash-yaml-manager/bin/mihomo` (root:root 0755)
and `bin/mihomo.json` (root:root 0644); the Web service account executes the
binary but cannot modify it. Status reports **NOT INSTALLED**, **COMPATIBLE**,
**INCOMPATIBLE**, or **BROKEN**. Unsafe files, ownership, permissions, metadata,
hash or version command fail closed without exposing raw command output. Normal
project updates preserve the entire `bin/` directory and do not repair or
replace Mihomo. The code and engine are separate versioned components: after a
code rollback, a mismatched installed engine blocks only Proxy Health until an
operator aligns the component. No stable Release is changed by this feature.

## Probe lifecycle and pinned controller behavior

Check Now snapshots the internal Fixed ID, current selected revision and
`current.yaml` bytes under the Fixed registry lock, then releases it before
starting Mihomo or network work. Only committed VMess/VLESS configs from that
snapshot are included; no source refresh, provider fetch, unsaved browser draft
or re-aggregation occurs. More than **256** supported nodes abort before a
probe or health write. Up to **64** nodes enter each sequential batch, with at
most **16** concurrent controller URL probes. One short-lived Mihomo instance
serves each batch. The batch budget is 55 seconds and the whole check budget is
235 seconds, below the existing 300-second Gunicorn timeout.

Each batch gets a private 0700 directory under `state/`; its minimal 0600
configuration contains only the batch's proxy configs, renamed to opaque
`probe-0001` aliases, and a controller on `127.0.0.1:<random-port>` with a
fresh 256-bit secret. It does not copy user rules, DNS, TUN, proxy providers,
listeners, external UI or other unrelated YAML. There is no mixed, HTTP or
SOCKS proxy listener and no permanent daemon or systemd unit. Mihomo runs as
the Web service account in a separate process session with its home/temp/work
directory inside that private batch directory. The application runs
`mihomo -d <dir> -f <config> -t` first; pinned v1.19.31 source returns exit 1
for a parse/config failure. Only a definite validation failure is recursively
bisected to individual **UNSUPPORTED** nodes. A crash, timeout or other system
error is an **ENGINE ERROR** for the whole check. The runtime uses
`mihomo -d <dir> -f <config>`, polls authenticated `GET /version` about every
100 ms for at most 5 seconds, and retries a startup/port collision at most
five times with a new localhost port.

The controller client connects directly to `127.0.0.1` through
`http.client.HTTPConnection`, sends `Authorization: Bearer <secret>`, and
does not use HTTP proxy environment variables. The v1.19.31 route is
`GET /proxies/<opaque-name>/delay?url=<url>&timeout=<ms>&expected=<status>`.
Success returns JSON `{"delay": <milliseconds>}`; proxy failure returns
HTTP 503 and timeout HTTP 504. **A delay response alone does not certify the
expected status.** Pinned v1.19.31 source updates a URL-specific
`extra[<url>].alive` flag for the expected-status check but may still return
HTTP 200 and a delay for a status mismatch. The application therefore requests
`GET /proxies/<opaque-name>` after a successful delay call and requires
`extra[<url>].alive == true`. Mihomo's URL test uses an HTTP **HEAD** request
and its pinned source disables automatic redirects; a redirect is accepted only
if the administrator deliberately configures that redirect status as the
expected status. Choose a stable, no-redirect HTTPS endpoint in normal use.
These API/CLI details were reviewed in pinned source; executing the Linux
binary on a real VPS remains an acceptance item.

Mihomo output is drained into a private 16 KiB bounded memory buffer and never
forwarded raw to Gunicorn logs, browser or state. Controller errors are reduced
to allowlisted codes. Process cleanup sends SIGTERM to the process group,
waits up to two seconds, escalates to SIGKILL if needed, reaps the parent, and
deletes the private batch directory in `finally`. A hard-killed Web worker
may leave a private stale directory; remove it only after confirming no managed
process is using it. Project update and uninstall backups exclude
`.proxy-probe-*` scratch directories so a leftover config cannot enter a
backup. The next ordinary check does not guess from a PID file or kill an
unknown process.

## Results, safety and concurrency

`state/proxy_health.json`, `proxy_health.lock`, and `proxy_probe.lock` are
separate from `node_health.json` and the authoritative Fixed registry.
`state/` is 0700 and auxiliary JSON/locks are 0600. Invalid schema, symlink,
FIFO, device or unsafe permissions make only Proxy Health unavailable; Fixed
URLs, Generate, Automatic Refresh, Endpoint Health and `/healthz` remain
available. The JSON contains global settings and per-subscription mode,
override, timestamps, and records keyed by the same opaque SHA256 connection
fingerprint used by Endpoint Health. A name-only rename keeps identity; server,
port, UUID, protocol, network, TLS, SNI, WS/Reality/ALPN or other connection
options change identity. Only allowlisted status, failure count, latency,
timestamps and error codes persist. No node name, server/IP, port, URI, UUID,
source URL/token, Fixed bearer, controller secret or proxy config is saved.

No observation is **UNKNOWN**. A successful exact-status URL probe is
**HEALTHY** with latency and zero failures. Network/proxy failures 1 and 2
become **SUSPECT**; the third and later become **UNHEALTHY**. A later success
resets the count immediately. Config validation failure is **UNSUPPORTED**
without incrementing failure count. Engine/process/controller failure is a
job-level **ENGINE ERROR**: it preserves the entire prior result set and does
not penalize nodes. Endpoint and Proxy columns can independently show any
combination. No state triggers node removal, policy switching, URL-Test groups,
Fallback, Load Balance, ranking or a background schedule.

Only one VPS-wide proxy check runs at a time through a nonblocking file lock;
a second returns a safe busy message. Results accumulate in memory and commit
once after all batches succeed and the Fixed revision and proxy settings still
match the snapshot. A Save, source change, automatic/manual refresh or Delete
during the probe discards the candidate. Regenerate Link or Disable without a
revision change preserves observations; public access still follows the Fixed
disabled state. A failed auxiliary write restores the previous state where
possible and never changes `current.yaml`, Fixed URL or groups. Fixed deletion
best-effort removes its auxiliary record; uninstall's existing state backup
includes Proxy Health, while the downloadable engine binary is not user data.
Public `/s` reads do not acquire the long-running probe lock.

The target validator rejects non-HTTPS, local/private/link-local/multicast/
reserved/non-global IPs and hostnames for which **any** locally resolved
address is unsafe. This blocks obvious unsafe targets and mixed DNS answers.
It **cannot pin Mihomo's internal or remote proxy-side DNS resolution**: the
URL test may resolve the hostname again through a different resolver. Operators
should select trusted, stable public probe hosts; this local validation is not
a guarantee about the final DNS destination.

## Verification boundary

Offline pytest and Playwright use controlled binary, process, DNS and
controller fixtures. The upstream Linux assets were downloaded and hashed, but
the current macOS host did **not** execute them. No real VPS VMess/VLESS or
Reality node was probed in this phase: **NOT VERIFIED ON REAL VPS**. Real VPS
acceptance should verify arm64 installation and COMPATIBLE status, one real
VMess and VLESS (plus Reality if available) becoming HEALTHY, a deliberately
wrong UUID/config producing a Proxy failure while Endpoint may remain HEALTHY,
and an unchanged Fixed URL/YAML throughout. See
[PROXY_HEALTH_REPORT.md](PROXY_HEALTH_REPORT.md) for automated gates.
