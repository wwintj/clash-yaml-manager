# Policy Engine MVP — controlled acceptance report

Date: 2026-09-30. Start gate: clean **main**, HEAD = origin/main =
`24fb40141c8ff85345c78864b8f38c3d49f5ff5e`, VERSION **1.1.1**, Latest Stable
**v1.1.1**. Baseline: **1101 passed in 204.93s**, 0 failed.
This phase is Unreleased main development, with no VERSION bump, tag or Release.

## Evidence boundary

The implementation controls generated group semantics; it does not run the
client's URL tests. Exact upstream v1.19.31 syntax and units were inspected in
MetaCubeX/mihomo commit `ab405bad5beeeac8b003bb01f60f134f6df54471`; links and
contracts are recorded in [POLICY_ENGINE.md](POLICY_ENGINE.md#pinned-mihomo-evidence).
Controlled tests use synthetic nodes, command/DNS/probe/controller doubles and
private temporary state. The browser uses an isolated Flask copy. No developer
/opt, systemd accounts, real provider or node credentials were operated on.

**REAL VPS POLICY ACCEPTANCE: NOT RUN.** The pinned Linux executable cannot
execute on this macOS host. There is no claimed real Linux import, client latency,
failover or traffic distribution result. The VPS/client commands and steps are in
[the handoff](POLICY_ENGINE.md#tim-vps--client-handoff).

Automatic Health is a separate acceptance: **PENDING / NOT FULLY CLOSED**.
Operator-attested evidence now includes timer installed/enabled/active(waiting),
one real auto_health timer trigger exited 0 with endpoint=0/proxy=0, real tim
systemd-analyze verify PASS, managed engine COMPATIBLE and healthz HTTP 200.
Due Endpoint and due Proxy jobs after a real timer trigger are still missing.
Codex did not independently reproduce that operator run. Policy completion does
not close it. See [AUTOMATIC_HEALTH_REPORT.md](AUTOMATIC_HEALTH_REPORT.md).

## Functional gates

| Gate | Result / controlled evidence |
| --- | --- |
| Fixed registry v4 | PASS; authoritative normalized policy_config, complete policy/source/YAML candidate commit |
| v1/v2/v3 migration | PASS; Preserve defaults, read bytes/revision/token/prefix/cache/current YAML unchanged; public access statistics retain legacy schema; legitimate mutation writes v4 |
| Strict schema/options | PASS; both scopes, exact keys/types, unknown options/type, NaN/Inf/float/bool-as-int, ranges and duplicate form fields refused |
| Preserve default/regression | PASS; Custom output bytes and full default output hash match goldens captured using pre-policy HEAD; both omitted and explicit Preserve tested |
| Select | PASS; manual/DIRECT/nested ordinary refs retained; known automatic leftovers removed; unrelated metadata retained |
| URL-Test | PASS; exact fields, URL/interval seconds/tolerance ms/lazy, node-only candidates |
| Fallback | PASS; supported common fields, generated order unchanged by unhealthy observations |
| Load-Balance | PASS; exact round-robin spelling, common options; no stale tolerance |
| Pinned v1.19.31 contract | PASS through tagged upstream source inspection and controlled schema fixtures; real binary import NOT RUN |
| Country membership | PASS; Taiwan/US/Singapore structured assignments, misleading US node name containing TW does not leak; unassigned country-looking group untouched |
| Special membership | PASS; explicit selected groups only, generated list/order; unselected/custom/provider groups unaffected |
| General/manual scope | PASS; explicit programmatic inclusion cannot convert general groups; explicit Special scope wins a country overlap |
| Automatic DIRECT/nested/provider exclusion | PASS; proxies are actual generated nodes, provider/use/include-all/filter expansion removed |
| One-node / zero-candidate | PASS; one remains one, explicit zero fails without output; Fixed empty candidate failure retains old revision/registry |
| Custom YAML | PASS; scoped name collision, nested/unrelated groups, comments/quotes/metadata preserved; rules targets unchanged |
| Sequential transitions | PASS; URL-Test → Fallback → Load-Balance → Select → Preserve; no stale options; Preserve returns authoritative custom base output |
| Source refresh policy persistence | PASS; refresh/refresh-all/automatic refresh/enable/disable/delete reconstruct the exact policy; A/B replaced by C/D, same URL |
| Cache / refresh failure atomicity | PASS; last-good cache emits same policy YAML; generation/metadata failure preserves selected output/config/cache |
| Policy vs automatic refresh concurrency | PASS; both winner directions; stale provider/policy candidate conflicts, newer config/payload stays authoritative |
| Fixed URL / public /s | PASS; same prefix/token/slug, public new YAML equals a complete committed revision; failed save keeps old bytes |
| Temporary Generate /t | PASS; all types use existing token/security/retention; no persisted temporary policy state; invalid options redisplayed only in POST response |
| Health is observational | PASS; unhealthy observations do not filter/reorder either node; policy save leaves health JSON and schedule untouched |
| Health revision conflict | PASS; paused Endpoint and Proxy, Manual and Automatic all discard revision-A result after policy revision B; unchanged fingerprints retain visible observations |
| Policy has no network/probe | PASS; socket/DNS/URL/provider/subprocess/probe calls forbidden in controlled generation; local/private HTTP(S) accepted without resolution |
| Safe errors/logging | PASS; fixed validation messages, rejected secrets not logged; no new bearer scheme or credential metadata |
| Browser | PASS; Generate + Fixed defaults, type visibility/enabled fields, restored saved URL/interval/lazy/tolerance, server error recovery, stable URL, all transitions, 1440/390 with no horizontal overflow; section screenshots inspected |
| Existing regressions | PASS; full suite retains auth/CSRF, sources/refresh/health/engine/lifecycle/release tooling, Fixed/V2/Legacy /s and /t; all prior browser suites retained |
| Default YAML | UNCHANGED; SHA256 a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b |
| 10,410 rules | PASS; exact default output golden and existing real-default round trip, rule targets unchanged |

## Final validation

Final full pytest: **1244 passed in 237.18s**, **0 failed** (baseline 1101).
The policy-focused suite passed **143 tests**. The final full run includes the
failed-policy auxiliary-node restoration assertion; all existing regressions remain.

| Gate | Result |
| --- | --- |
| Full pytest | PASS; 1244 passed in 237.18s, 0 failed; baseline 1101 |
| Playwright | PASS; all six suites, seven Preview viewports, Policy and existing health/source controls at 1440/390 |
| Python / Node syntax | PASS |
| Node draft/Generate guard tests | PASS |
| pip check | PASS |
| bash -n | PASS; seven shell scripts |
| ShellCheck 0.9.0 / 0.11.0 | PASS; seven shell scripts |
| build_bootstraps.py --check | PASS; lifecycle source/bootstrap entrypoints unchanged |
| systemd-analyze verify | UNAVAILABLE locally on macOS; existing conditional temp-unit tests retained; operator-reported real tim PASS separately recorded |
| git diff --check | PASS |
| VERSION / Latest Stable | 1.1.1 / v1.1.1 |
| New tag / Release | NO / NO |
| Real timer-triggered due health acceptance | PENDING / NOT FULLY CLOSED |
| Real VPS Policy acceptance | NOT RUN |

The phase adds no new units, dependency, permanent process or scheduler. The
existing generator's targeted structure/reference/removed-rule-target checks
remain; generic Mihomo schema and nested-group cycle validation are not added.
Preserve means existing generation compatibility, including base custom behavior;
it is not a new engine validator. Future health-aware exclusion/freshness/minimum
candidate/fail-open rules remain separate and are not implemented.

Historical phase boundary: the evidence above was captured before optional health
eligibility. Current main uses Fixed v5 and adds that layer separately; see
[HEALTH_AWARE_POLICY_REPORT.md](HEALTH_AWARE_POLICY_REPORT.md). This does not change
the historical Policy real-VPS NOT RUN or health due-job PENDING status.
