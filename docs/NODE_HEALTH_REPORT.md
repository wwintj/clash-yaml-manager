# Node Health — Endpoint Reachability MVP acceptance

Date: 2026-09-30. This is a **main development** change. VERSION stays
**1.1.1**, Latest Stable stays **v1.1.1**, and there is no new tag or Release.
Baseline main was `7051a8af0cff9fb3309d8806bf39123dacc59f39`; baseline
pytest was **667 passed**. Final full pytest was **794 passed in 153.85s,
0 failed**. Final commit identities and the origin/main equality
check are recorded in the development handoff after pushing.

The result means only that this machine can open a TCP connection to a saved
VMess/VLESS endpoint. It does **not** authenticate a proxy or demonstrate
end-to-end forwarding, TLS/WebSocket/Reality negotiation, internet egress,
throughput, or a usable proxy service. All endpoint observations below use
deterministic test doubles or local fixture servers; no real VPS node-health
acceptance is claimed.

| Acceptance item | Result | Evidence |
| --- | --- | --- |
| Health state; private permissions | PASS | Independent schema-v1 `node_health.json` and lock, both 0600 in private state; unsafe files and corrupt schema fail closed. |
| Mode Off default | PASS | Existing Fixed entries read Off without health JSON write or network call. |
| Manual mode; Check Now | PASS | Authenticated, CSRF-protected POST controls; GET is 405; Off check is rejected. |
| TCP reachability; connect latency | PASS | Direct socket to validated numeric address; no application bytes; monotonic elapsed time and integer UI rendering. |
| Unknown; Healthy; Suspect; Unhealthy | PASS | New identity Unknown; TCP success Healthy; failures 1/2 Suspect and 3+ Unhealthy. |
| Success reset; Last Success | PASS | Next success resets failures to zero; failed checks preserve the previous success time. |
| Node fingerprint | PASS | SHA256 of canonical proxy configuration excluding only root name; no reversible credential stored. |
| Name-only rename; config change | PASS | Rename retains health; server, port, UUID and protocol-option changes make a new Unknown identity. |
| Private address block; mixed DNS block | PASS | IPv4/IPv6 loopback, private, link-local, multicast, reserved, metadata and transition addresses refused; any unsafe DNS answer blocks the target. |
| DNS pinning; no proxy environment | PASS | Socket connects to approved numeric sockaddr without hostname re-resolution; HTTP proxy variables cannot influence the direct socket. |
| Timeout; bounded concurrency; 256 limit | PASS | One three-second DNS-plus-connect budget per node; 16 workers; 257 nodes fail before probes or state mutation. |
| No network under Fixed lock | PASS | Concurrent public Fixed read and management operation finish while a probe is paused. |
| Revision conflict | PASS | Save, source refresh/disable, automatic refresh and deletion discard stale results; concurrent health mode/result changes also conflict. |
| Health corruption and write failure | PASS | Health UI reports a sanitized error; Fixed `/s` and `/healthz` remain available; injected before/after-write failure restores previous auxiliary bytes. |
| Secret redaction | PASS | State, logs, health HTML and browser storage exclude endpoint address, UUID, URI, provider URL, Fixed token and node fingerprint. |
| No unhealthy exclusion | PASS | Failed observations do not alter `current.yaml`, proxy groups, source settings or selected revision. |
| Fixed URL stability | PASS | Mode changes, checks, failures and corruption preserve the Fixed URL and served YAML. |
| Fixed `/s`; V2 `/s`; Legacy `/s`; Temp `/t` | PASS | Full pytest route regression suite. |
| External Sources; Automatic Refresh | PASS | Full pytest and browser regression, including overlap with an automatic revision update. |
| Browser | PASS | Seven Preview viewports, Fixed CRUD, External Sources/refresh UI and Node Health success/failure lifecycle at 1440/390 widths. |
| Uninstall backup | PASS | Deployment fixture retains `state/node_health.json` in upgrade and uninstall backups. |
| Default YAML; 10,410-rule round trip | PASS | File byte-for-byte unchanged; full pytest round-trip test. |

| Validation gate | Result |
| --- | --- |
| Final complete pytest | PASS; 794 passed, 0 failed (baseline: 667 passed) |
| Playwright browser suite | PASS; all four suites, including seven Preview viewports |
| Python syntax; Node syntax | PASS |
| `pip check` | PASS; no broken requirements |
| Six shell scripts `bash -n` | PASS |
| ShellCheck 0.9.0 and 0.11.0 | PASS; all six shell files |
| `build_bootstraps.py --check` | PASS; standalone entrypoints unchanged |
| `git diff --check` | PASS |
| `defaults/default.yaml` SHA256 | `a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b` |
| VERSION; Latest Stable | `1.1.1`; `v1.1.1` |
| Tag; Release | NO; NO |

Checks ran on macOS in an isolated Python 3.12 environment and disposable
application/deployment state. They did not operate on the developer machine's
real `/opt`, systemd units or service accounts. The previous Automatic Refresh
main commit `7051a8a` was verified on a real VPS for web readiness,
`/healthz`, timer/oneshot operation, `systemd-analyze verify` and an empty scan.
A real scheduled provider refresh was not observed there, and this phase has no
real VPS Node Health result. A real deployment should use explicit
`--channel main`; default installs and updates still resolve the stable Release.

Implementation details, safety limits and future full-proxy-check scope are in
[NODE_HEALTH.md](NODE_HEALTH.md).
