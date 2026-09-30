# Full Proxy Validation MVP

Current release scope, supported migrations and deferred real acceptance: [Final Audit](FINAL_AUDIT_REPORT.md). New functionality is intended for the next Stable; before publication use explicit `--channel main`.

Before its Stable publication, test with explicit `--channel main`. It checks whether a saved
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
sudo sha256sum /opt/clash-yaml-manager/bin/mihomo
sudo /opt/clash-yaml-manager/bin/mihomo -v
systemctl status clash-yaml-manager --no-pager -l
curl -i http://127.0.0.1:8899/healthz
```

The same helper supports `update` (reverify and replace the pinned version)
and `remove`. No Web install/update button exists. On the Fixed Subscription
Edit page, choose Full Proxy Checks **Manual** or **Automatic**, save, then **Check Proxies Now**.
Opt-in Automatic scheduling uses a separate health timer; see
[AUTOMATIC_HEALTH.md](AUTOMATIC_HEALTH.md).
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

| Build | Release asset | Compressed SHA256 | Decompressed SHA256 | Bytes |
| --- | --- | --- | --- | --- |
| amd64-v1 | `mihomo-linux-amd64-v1-v1.19.31.gz` | `d4304c546c3cddcb6fafd4b4fddb0ba1a95ffa36606fda56d75db2e59ad24114` | `12d97b7b7fa22cb4456e62c6e35db4be952dbb1c53eacaa9ef437c95d5068a9d` | 22821828 |
| amd64-v2 | `mihomo-linux-amd64-v2-v1.19.31.gz` | `560a14ba51482e85e90b6c9b141f3b7b1543795f9ecd82eb9a6c5153a1b7960b` | `8a9d3e867c422605bb61f572636f1e50b05c16f6b78b4eabff9857947ad2eb35` | 22805792 |
| amd64-v3 | `mihomo-linux-amd64-v3-v1.19.31.gz` | `4e8808e79f1e452a0300ce1ee89fcaf2cccd5249a100f2238877214e5ca316b3` | `81d4e533a66d17b8ac12b92e1891d681d2a34c788dfaf57f8b1bd0bb22a34cec` | 22789796 |
| arm64 | `mihomo-linux-arm64-v1.19.31.gz` | `9e0f11afbf38426b8bd88fdc594678f8161c57eccb4e1b77acb12b493904f1d4` | `1b315bc038d05f84ee86d232f3c3d2b020b5044e9b971bb8fe215b6e6a2148f3` | 20757911 |

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
replacing either live file and restores both on an ordinary replacement error
or failed post-replacement verification.
The managed paths are `/opt/clash-yaml-manager/bin/mihomo` (root:root 0755)
and `bin/mihomo.json` (root:root 0644); the Web service account executes the
binary but cannot modify it. Status reports **NOT INSTALLED**, **COMPATIBLE**,
**INCOMPATIBLE**, or **BROKEN**. Unsafe files, ownership, permissions, metadata,
hash or version command fail closed without exposing raw command output. Normal
project updates preserve the entire `bin/` directory and do not repair or
replace Mihomo. The code and engine are separate versioned components: after a
code rollback, a mismatched installed engine blocks only Proxy Health until an
operator aligns the component. No stable Release is changed by this feature.

## CPU-aware selection and VPS migration

New amd64 installs use only the explicit `amd64-v1`, `amd64-v2` and
`amd64-v3` assets above. The manifest validates every variant, exact asset name,
URL, hash and positive bounded size, including unselected variants. It never
queries latest, discovers assets dynamically or installs the generic amd64
or compatible-named build. Arm64 continues to use its unchanged pinned asset.

The pure detector parses `/proc/cpuinfo` and intersects flags from **every
visible processor**. It ignores model names. Missing/unreadable cpuinfo,
missing flags on any CPU, duplicate processor/flag records or malformed input
choose portable **v1**. Hypervisors can mask capabilities even on a modern Xeon,
EPYC or Ryzen, so a model name cannot guarantee a GOAMD64 level.

[Go minimum requirements](https://go.dev/wiki/MinimumRequirements) and
[Go runtime checks](https://go.dev/src/runtime/asm_amd64.s) define v2 as
CMPXCHG16B, LAHF/SAHF, POPCNT, SSE3, SSSE3, SSE4.1 and SSE4.2. Their
[Linux names](https://github.com/torvalds/linux/blob/v6.17/arch/x86/include/asm/cpufeatures.h)
are `cx16 lahf_lm popcnt pni ssse3 sse4_1 sse4_2`.
V3 additionally requires AVX, AVX2, BMI1, BMI2, FMA, F16C, LZCNT (`abm`),
MOVBE and OSXSAVE with OS XMM/YMM state enabled. Linux does not export an
`osxsave` cpuinfo name; this detector uses kernel-enabled `xsave`, `avx` and
`avx2` as its local OS-support signal. This is an inference from
[Linux's enabled-flags contract](https://docs.kernel.org/arch/x86/cpuinfo.html)
and [xstate setup](https://github.com/torvalds/linux/blob/v6.17/arch/x86/kernel/fpu/xstate.c),
not a direct XGETBV measurement. The verified candidate's three-second `-v`
execution is the final compatibility check, including Go's OSXSAVE/XGETBV check.

The preferred build is the highest detected level. Only after exact archive
size/hash, gzip, executable hash and ELF class/endian/architecture checks pass,
an execution failure (nonzero, SIGILL, timeout or launch failure) can try the
next lower pinned build: v3 → v2 → v1. Download, integrity, package, malformed
version output and wrong version/architecture failures stop immediately;
they never trigger downgrade. All attempts stay in private staging. If no
candidate executes correctly, existing binary and metadata remain unchanged.

New `bin/mihomo.json` records exact version, platform, `cpu_level`, asset,
archive SHA256 and binary SHA256. Arm64 writes `cpu_level: null`; its older
metadata without that field remains accepted. CLI and the existing Web engine
card display host **CPU Level**, installed **Build** and **Preferred Build**.
A valid v1/v2 install remains COMPATIBLE on a v3 host. A verified installed
build above the detected host level is INCOMPATIBLE without executing it;
run `sudo bash /opt/clash-yaml-manager/mihomoctl.sh update` over SSH to migrate.
Unsafe ownership/modes, corrupt metadata, hash drift and unexpected execution
failure for a supposedly compatible explicit build are BROKEN.

The earlier generic `mihomo-linux-amd64-v1.19.31.gz` is a **legacy v3** build,
confirmed in the [pinned upstream build matrix](https://github.com/MetaCubeX/mihomo/blob/ab405bad5beeeac8b003bb01f60f134f6df54471/.github/workflows/build.yml).
Its exact old metadata is recognized only with archive SHA256
`d5e74bbddbdfff49a1aef7775bf5911da59f0d7196ed509a0ac914b3653dd5f1`
and binary SHA256
`08787faafea19c1ab0f83fa5a1b22363b7d03ea78da18091a4c883aecaaa5979`.
Safe metadata, matching executable hash, host v3 support and successful exact
version execution keep it COMPATIBLE. CPU downgrade or legacy runtime failure
reports INCOMPATIBLE rather than corrupt metadata. Explicit helper `update`
selects the new pinned variant; ordinary project update preserves `bin/`.

A real tim x86_64 VPS reported the generic upstream v3 artifact downloading,
hashing and passing ELF validation, then failing the real version execution.
Its Intel Xeon SierraForest model exposed v2 flags but lacked AVX2, BMI1/BMI2,
FMA, LZCNT and MOVBE. Installation correctly remained NOT INSTALLED. The patch
is **FIXED IN CONTROLLED TESTS**, with the tim amd64 path now covered by
**OPERATOR-ATTESTED REAL VPS ACCEPTANCE** below. On that VPS, the
expected CPU Level is v2 and Build amd64-v2; if verified v2 cannot execute, the
helper should select v1. Run the operator sequence above and confirm actual
detector output, hash and `-v`, then recheck real VMess, real VLESS and bad UUID.
Fixed URL and YAML must remain unchanged throughout this engine-only acceptance
(with Health-aware Policy Off).

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
combination. Checks never delete top-level nodes or rank them. With
[Health-aware Policy](HEALTH_AWARE_POLICY.md) Off, observations do not affect YAML.
When explicitly enabled, successful checks trigger separate cache-only candidate
reconciliation; reconciliation failure does not turn the health job into a failure.
Automatic probe scheduling still requires explicit Automatic mode.

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

## Verification boundary and real VPS closeout

**OPERATOR-ATTESTED REAL VPS ACCEPTANCE**, supplied by the operator on
2026-09-30; Codex did not independently connect to or reproduce the VPS run.
The tim VPS ran application build `1.1.1-dev+e2e430d`, amd64, CPU Level v2,
Build amd64-v2, Preferred Build amd64-v2, managed engine COMPATIBLE and
Mihomo v1.19.31. Its real binary SHA256 was
`8a9d3e867c422605bb61f572636f1e50b05c16f6b78b4eabff9857947ad2eb35`;
real execution returned `Mihomo Meta v1.19.31 linux amd64`, and `/healthz`
returned HTTP 200 OK.

The operator explicitly attested PASS for real VMess and VLESS full proxy
validation, bad UUID differentiation, reachable Endpoint with failing proxy
credentials, Suspect/Unhealthy progression, healthy recovery, unchanged Fixed
URL and YAML, and continued application health. No latency, endpoint, UUID,
node name or count was supplied or inferred. Reality and real arm64 acceptance
remain unevidenced. This closes the tim manual proxy/CPU compatibility check;
it does not establish automatic timer-triggered health acceptance.

Offline pytest and Playwright use controlled binary, process, DNS and
controller fixtures. The upstream Linux assets were independently downloaded
and hashed; the macOS development host did not execute them. See
[PROXY_HEALTH_REPORT.md](PROXY_HEALTH_REPORT.md) for the controlled gates and
operator evidence boundary.

## Global defaults UI (Settings Framework)

Edit global HTTPS URL/status/timeout under **Settings → Health**. Fixed edit now
shows a summary and link; custom per-subscription targets/modes/intervals remain
on Fixed edit. The existing Fixed POST route stays compatible and both paths
reuse `ProxyHealth.set_global()`, including observation/schedule resets for global
users only. Settings engine status checks local pinned files/metadata without
executing Mihomo; CLI/probe execution validation remains unchanged. See
[Settings](SETTINGS.md) for authority, privacy and read-only Runtime boundaries.
