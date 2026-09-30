# Settings Framework MVP — controlled acceptance report

Date: 2026-09-30. Start gate: clean **main**, HEAD = origin/main = actual remote
`88e28f6cc21c98bb9002e96abc736e9f6319e1ba`, VERSION **1.1.1**, Latest Stable
**v1.1.1**. Baseline **1503 passed in 221.19s, 0 failed** before editing source.
The prior temporary Python environment had been removed; a fresh Python3.12
virtual environment was created outside the repository before the baseline run.

This is Unreleased main development, with no version bump, new tag or Release.
Final full pytest: **1547 passed in222.01s, 0 failed**. New Settings coverage adds
**44 tests**. All original eight browser suites plus Settings (nine total) PASS.

## Evidence boundary

Tests use isolated Flask copies, temporary private state, synthetic pinned engine
files, MMDB readers and provider/probe doubles. New Settings tests include real
forms/CSRF, byte comparisons across source/YAML/config state and the same Proxy
core method used by both routes. Network/subprocess guard tests record attempted
calls (rather than merely swallowing a forbidden exception). No real VPS, MMDB
accuracy, live proxy routing, Nginx or systemd acceptance is claimed.

- **REAL GEOIP VPS: NOT RUN**.
- **AUTOMATIC HEALTH REAL DUE ENDPOINT: PENDING**.
- **AUTOMATIC HEALTH REAL DUE PROXY: PENDING**.
- **REAL POLICY: NOT RUN**.
- **REAL HEALTH-AWARE POLICY: NOT RUN**.

Prior operator evidence is retained in historical reports. None of those deferred
acceptances is closed by these local controlled tests.

## Functional gates

| Gate | Result / controlled evidence |
| --- | --- |
| Settings Overview | PASS; existing build identity, local availability and registry total/active/disabled counts; no current-YAML reads |
| Modular sections | PASS; Overview/GeoIP/Health/Runtime partials and semantic anchors; normal Flask/Jinja, no frontend engine |
| GeoIP regression | PASS; all original GeoIP unit/lifecycle/browser tests retained |
| GeoIP transaction unchanged | PASS; `core/geoip.py`/`geoip_store.py` byte-unchanged from start; private upload, invalid replacement retention, rollback/removal regressions retained |
| state/settings.json compatibility | PASS; unchanged exact v1 GeoIP schema and DB pair; Health saves leave both files byte-identical; no generic settings store |
| Global Proxy defaults in Settings | PASS; one canonical form, success303→/settings#health, normalized defaults and safe invalid400 recovery |
| Existing Fixed route compatibility | PASS; same set_global operation/coercion, byte-identical Proxy state with frozen clock and same initial state; old Fixed redirect retained |
| Fixed global form cleanup | PASS; read-only global summary/link replaces edit form; no global fields on Fixed |
| Per-subscription Proxy settings | PASS; modes/global-custom/custom URL/status/timeout/interval/check/results remain on Fixed; original Proxy browser flow updated to canonical form |
| Proxy Health validation reused | PASS; actual public-target/DNS/numeric validation belongs to existing ProxyHealth.set_global; no validator duplication |
| Invalid global target atomicity | PASS; non-HTTPS/private/credentials/query/fragment/mixed-address targets leave Proxy and all other state unchanged; rejected values absent from HTML/logs |
| Existing reset semantics | PASS; global users reset observations/check/schedule on changes, custom users untouched, identical values unchanged |
| Mihomo status | PASS; safe local ownership/permissions/pins/metadata/CPU checks; no -v; oversized binary rejected before hashing; amd64/arm64 synthetic installed fixtures prove this branch and preserve full execution checks |
| No Mihomo web install | PASS; only read-only status/SSH guidance, no engine action route or controls |
| Runtime read-only / No .env writes | PASS; safe effective values/build/channel, configuration remains deployment-owned; .env/INSTALLATION bytes unchanged, no Runtime forms |
| Secret absence | PASS; distinctive env/key/password hash, real Fixed bearer token, provider credential, node URI/UUID and private base URL absent from Settings HTML |
| Auth | PASS; anonymous Settings information blocked; mutation routes require login |
| CSRF | PASS; all mutations POST-only, rejected body not applied, refreshed form can be submitted |
| No-store / No-referrer | PASS; existing private-response headers preserved |
| No network on Settings GET | PASS; provider fetch, DNS, socket connect, Mihomo/TCP runner and subprocess forbidden; zero recorded calls |
| Auxiliary failure isolation | PASS; GeoIP/Proxy/engine/count/Runtime/install failures safely represented; no raw path/exception; other sections usable |
| Locking | PASS; busy Proxy/Fixed read returns Unavailable while page stays responsive; no cross-feature lock hierarchy |
| Fixed URL stability | PASS; registry/token/prefix/slug unchanged across Settings actions |
| YAML stability | PASS; global Probe and GeoIP Settings changes never directly change revisions/current YAML |
| Source state stability | PASS; fetched and uploaded payloads/cache/history/schedules/config unchanged; no refetch |
| Country / Policy stability | PASS; GeoIP mode, policy_config and health_policy config unchanged |
| Browser /390px /1440px | PASS; all nine suites, seven Preview viewports; four Settings sections at1440/390, no overflow, screenshots inspected; native submit with JavaScript disabled |
| Default YAML | UNCHANGED; SHA256 a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b |
| 10,410-rule round trip | PASS; existing real-default round-trip/pre-policy tests unchanged and full run passed |

## Full validation

| Check | Result |
| --- | --- |
| Baseline pytest | 1503 passed in221.19s, 0 failed |
| Final full pytest | 1547 passed in222.01s, 0 failed |
| New Settings pytest | 44 passed in7.95s, 0 failed |
| GeoIP/Proxy/Mihomo targeted regressions | 288 passed in11.50s, 0 failed |
| Browser | PASS; all nine suites (existing eight plus Settings); seven Preview viewports; Settings modules at1440/390; no-JS native form submit |
| Python syntax | PASS; app/core/scripts/tests |
| Node syntax / draft guards | PASS;13 JS/CJS files plus executed draft storage/Generate guards |
| pip check | PASS; no broken requirements; requirements.txt unchanged |
| bash -n | PASS; seven scripts |
| ShellCheck0.9.0 | PASS; seven scripts together, checksum-verified Homebrew arm64 bottle; upstream x86_64 binary cannot execute on this host |
| ShellCheck0.11.0 | PASS; all seven scripts together |
| build_bootstraps.py --check | PASS; lifecycle source/entrypoints unchanged |
| systemd-analyze verify | UNAVAILABLE locally on macOS; conditional temporary-unit tests retained, no new unit |
| git diff --check | PASS |
| Deployment / default / VERSION | UNCHANGED |
| VERSION / Latest Stable | 1.1.1 /v1.1.1 |
| New tag / Release | NO /NO |

Settings engine COMPATIBLE is explicitly qualified as local file/metadata
validation, not execution or routing evidence. CLI/probe execution remains
unchanged. Auth/security-state failures remain authoritative and are not bypassed.
Existing process request cleanup still runs normally. Settings GET can read
bounded database/binary data to verify local integrity; aggregate overview does
not parse current YAML/nodes. No scheduler-state polling, generic persisted
settings framework or immediate health-policy regeneration is introduced.

Commit SHAs and clean HEAD=origin/main verification are included in final delivery
after pushing the tested commits. See [SETTINGS.md](SETTINGS.md) for ownership,
operation, security and extension boundaries.
