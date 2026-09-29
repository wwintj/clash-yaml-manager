# Full Proxy Validation MVP and CPU compatibility patch — acceptance report

Initial Full Proxy Validation phase, 2026-09-30. Baseline main was
`0d354bd0c5a885e9b21cde079287f9bb2c37ddc8`, equal to `origin/main`
with a clean tree, VERSION **1.1.1**, Latest Stable **v1.1.1** and **794 passed**
in baseline pytest. This is a development-only main change. No VERSION bump,
tag or Release is part of this work.

## CPU compatibility patch — 2026-09-30

Patch baseline main/origin/main: `c66f649bb5678fe6d9123611a0aff7686c20f421`,
clean tree, **877 passed in 166.99s**, VERSION **1.1.1**, Latest Stable **v1.1.1**.
This patch is pushed to main only, with no VERSION bump, new tag or Release.

**Real VPS discovery (operator report):** generic upstream
`mihomo-linux-amd64-v1.19.31.gz` was built with GOAMD64 v3. On the tim x86_64
VPS, download, SHA256 and ELF checks passed but real `-v` execution failed,
leaving NOT INSTALLED. Its Intel Xeon SierraForest model exposed the v2
requirements but lacked AVX2, BMI1/BMI2, FMA, LZCNT and MOVBE. This is real
pre-patch failure evidence; it is not a post-patch successful installation.

**CPU compatibility regression: FIXED IN CONTROLLED TESTS.**
**REAL VPS RE-TEST REQUIRED.** The macOS host did not execute any Linux asset.
Four exact v1.19.31 assets were independently downloaded and checked against
GitHub Release sizes/digests, then decompressed, hashed and checked as ELF.
The exact names, compressed/binary SHA256 and byte sizes are recorded in
[PROXY_HEALTH.md](PROXY_HEALTH.md#pinned-engine-and-supply-chain) and
[mihomo-manifest.json](../mihomo-manifest.json). The upstream build matrix,
Go v2/v3 requirements and Linux flag names/OS-state inference are cited in the
[CPU selection documentation](PROXY_HEALTH.md#cpu-aware-selection-and-vps-migration).

| Patch gate | Result | Controlled evidence |
| --- | --- | --- |
| CPU detection / v1, v2, v3 selection | PASS | Every Go v2 and v3 Linux requirement removed individually; F16C, XSAVE and AVX required; tim/SierraForest/hypervisor fixture selects explicit v2, baseline v1 and complete v3 select their own assets. |
| Multi-CPU intersection | PASS | Heterogeneous CPU order, separately masked features, full v3 and baseline CPU combinations; model text does not affect capability selection. |
| Unknown cpuinfo → v1 | PASS | Missing/unreadable file, invalid encoding, missing CPU/flags, duplicate records, malformed flags and unreasonable processor IDs are conservative v1. Detection is local and injectable. |
| v3 → v2 / v2 → v1 runtime fallback | PASS | Verified nonzero, SIGILL, timeout and launch failure try only lower pinned levels; v3 → v2 → v1 covered; chosen level/asset/hash are persisted. |
| No fallback on integrity/package/download/version errors | PASS | Compressed size/hash, executable hash, invalid gzip, wrong ELF, download failure, wrong/unknown version and invalid successful output stop; no lower URL fetched and old files retained. |
| Atomic failure preserves old engine | PASS | Every candidate fails while live files remain unchanged; second replacement and post-replacement verification failure restore both; private staging is cleaned. |
| Strict manifest | PASS | All four assets validated even when not selected; missing v1/v2/v3/arm64, bad name/URL/hashes/size, boolean size, unexpected fields and duplicate JSON keys refused. |
| Legacy generic amd64 v3 recognition | PASS | Exact old metadata/hash + execution remains COMPATIBLE on v3; legacy execution failure is INCOMPATIBLE, altered metadata is BROKEN; update migrates to explicit asset. |
| CPU downgrade / lower build compatibility | PASS | Valid explicit/legacy v3 on v2 returns INCOMPATIBLE without execution; helper migration selects v2; valid v1/v2 stays COMPATIBLE on higher host; hash drift stays BROKEN. |
| Arm64 / CLI / Web display | PASS | Unchanged arm64 asset, null CPU level and older fieldless metadata accepted; CPU Level/Build/Preferred Build shown; no Web management button added. |
| Full Proxy Validation and existing regressions | PASS | Existing controlled probe lifecycle/API/state unchanged; full pytest and all browser suites cover Fixed/V2/Legacy `/s`, temporary `/t`, Generate, sources, refresh, Endpoint, Proxy, auth/CSRF and deployment/release tooling. |

For tim, follow the updated [operator sequence](PROXY_HEALTH.md#operator-workflow):
explicit main project update → helper status → helper install → status →
`sha256sum` → binary `-v` → `/healthz`. Expected host CPU Level is **v2**,
Build **amd64-v2**; actual execution may choose v1 after verified v2 failure.
Only after COMPATIBLE, test real VMess, real VLESS and deliberately bad UUID
through Full Proxy Validation, preserving Fixed URL and YAML. Arm64 still
requires real Linux/VPS acceptance when available.

## Evidence boundary

Initial-phase functional/proxy observations below are **automated controlled fixtures**
in isolated temporary directories. Tests do not touch the developer machine's
real `/opt`, systemd units or system accounts. A fake controller and controlled
binary/process doubles test application behavior; they do **not** prove a real
VMess/VLESS connection. Official v1.19.31 amd64/arm64 assets were separately
downloaded, checked against upstream Release SHA256 metadata, decompressed
and checked as Linux x86-64/AArch64 ELF. The macOS host **cannot execute** the
Linux binary, so CLI/API behavior was also inspected in pinned upstream tag
source. **REAL MIHOMO BINARY TEST: NOT RUN. REAL VPS FULL PROXY TEST:
NOT VERIFIED ON REAL VPS.** The earlier Automatic Refresh main build had VPS
readiness/timer checks, but no real scheduled provider refresh was observed
there; this phase makes no new real VPS acceptance claim.

| Area | Result | Controlled evidence |
| --- | --- | --- |
| Optional engine; Off default; no automatic probe | PASS | Missing Mihomo leaves Fixed/Generate/public routes available; new and existing subscriptions start Off; only authenticated Manual POST runs the probe. |
| Exact pin; install/update/remove; root-owned files | PASS | amd64/arm64 manifest selection, compressed/decompressed hashes, ELF arch, exact version, metadata, 0755 binary and 0644 metadata; fixture injects temp-root ownership. |
| Engine status | PASS | NOT INSTALLED, COMPATIBLE, INCOMPATIBLE, BROKEN; symlink, wrong owner/mode, corrupt metadata, hash drift, version crash/timeout covered. |
| Atomic engine update; normal project update | PASS | Failed hash/gzip/version/second replace leaves previous managed files intact; deployment fixture preserves `bin/mihomo` and metadata, while an absent engine stays absent. |
| Independent private state and URL stability | PASS | Dedicated schema-v1 JSON/locks, private modes, fail-closed corruption/write errors, Fixed URL and current YAML byte equality, no node or group removal. |
| Global settings and per-subscription override | PASS | Default HTTPS/204/8000 ms, custom settings, strict integer bounds and Manual UI; effective target changes reset old observations to Unknown. |
| HTTPS/public target safety | PASS | Non-HTTPS, credentials, query/fragment, loopback/private/link-local/reserved and mixed DNS answers refused; public fixture accepted. Local validation cannot pin Mihomo/remote DNS. |
| Config validation and unsupported isolation | PASS | Minimal private YAML, opaque aliases, no proxy listener, definite config failure bisection for one/multiple nodes while valid nodes continue. |
| 64-node batching; 16 concurrency; 256 limit | PASS | Sequential 1/64/65/128/200/256 batches, bounded thread pool, 257 rejected before engine or state mutation. |
| Global singleton and Fixed lock | PASS | Second check fails busy; public Fixed and management reads complete while first probe is paused outside the Fixed lock. |
| Controller/security/lifecycle | PASS | Authenticated localhost-only controller client, random per-batch secret, bounded startup readiness and five collision attempts, process group SIGTERM/SIGKILL/reap, private temp cleanup and bounded output. |
| Sensitive scratch backup exclusion | PASS | Upgrade/uninstall backups retain private Proxy Health JSON but skip stale `.proxy-probe-*` config directories. |
| Full proxy result/latency | PASS in fixture | Pinned delay API shape, positive delay and URL-specific `extra[url].alive` required for exact expected status. A status mismatch is not certified healthy. |
| Failure threshold/reset | PASS | Failure 1/2 Suspect, failure 3 Unhealthy, next success Healthy/0; Unsupported does not add failures. |
| Engine error isolation | PASS | Missing/broken engine or controller/process error preserves old node state and shows sanitized job-level notice. |
| Endpoint + Proxy independence | PASS | Browser shows Endpoint Healthy/Proxy Unhealthy and Endpoint Unhealthy/Proxy Healthy, with no combined score. |
| Revision/settings conflict | PASS | Save, automatic refresh, delete and settings changes reject stale result; regenerate link and disable without revision change retain observations. |
| Privacy and public routes | PASS | State/log/HTML/browser storage omit UUID, endpoint, URI, provider URL, Fixed token, controller secret and raw errors; Fixed/V2/Legacy `/s`, temporary `/t`, Generate, External Sources, Automatic Refresh and Endpoint Health regressions pass. |
| Browser/layout | PASS | New proxy flow and all existing suites: seven Preview viewports, Fixed CRUD, External Sources/Refresh, Endpoint Health, and Proxy Health at 1440/390 px with no page overflow. |
| Default YAML and 10,410-rule round trip | PASS | File SHA256 remains `a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b`; full pytest includes the round trip. |

## Final gates (current CPU patch)

| Gate | Result |
| --- | --- |
| Full pytest | PASS; 984 passed in 167.54s, 0 failed (CPU patch baseline: 877 passed); final independent engine fixtures: 117 passed in 2.25s |
| Playwright | PASS; all five suites, including seven Preview viewports and amd64 CPU/Build card at desktop/mobile widths |
| Python / Node syntax | PASS |
| `pip check` | PASS; no broken requirements |
| `bash -n` | PASS; six entrypoints and deployment helper |
| ShellCheck 0.9.0 and 0.11.0 | PASS; same seven shell scripts |
| `build_bootstraps.py --check` | PASS |
| `git diff --check` | PASS |
| VERSION / Latest Stable | 1.1.1 / v1.1.1 |
| New tag / Release | NO / NO |

The remaining **real VPS** acceptance is: deploy explicit main, re-test tim
amd64 CPU selection (and arm64 when available), install pinned Mihomo through `mihomoctl.sh`, confirm COMPATIBLE and hash verification,
then test a real VMess node, a real VLESS node and VLESS Reality if available.
A deliberately wrong UUID/config should fail Proxy Health even if direct TCP
Endpoint Health remains Healthy. Confirm Fixed URL and YAML stay unchanged.
The exact operator commands and the pinned API limitations are in
[PROXY_HEALTH.md](PROXY_HEALTH.md).
