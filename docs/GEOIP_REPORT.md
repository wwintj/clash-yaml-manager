# GeoIP Country Assist — controlled acceptance report

Date: 2026-09-30. Start gate: clean **main**, HEAD = origin/main = actual remote
`03d8f3882542c1fddcbd45e16b6935a862e69df3`. VERSION **1.1.1**, Latest Stable
**v1.1.1**. Baseline **1379 passed in 212.83s**, 0 failed, before source changes.
This phase is Unreleased main development, with no VERSION bump, tag or Release.

Final full pytest: **1503 passed in 206.78s, 0 failed**. GeoIP-focused tests:
**124 passed in 1.63s**, 0 failed. The final full run covers the final implementation and every added assertion.

## Evidence boundary

Unit/lifecycle and browser tests use synthetic reader records, temporary private
state, provider/probe doubles and paused threads. No third-party geographic
MMDB is distributed in the repository. A separate genuine-reader smoke test used
`GeoIP2-Country-Test.mmdb` from the downloaded **maxminddb3.2.0 source archive**
in `/private/tmp`, outside the repository. This is upstream synthetic test data,
not a current production geolocation dataset. Genuine-reader upload/status,
IPv4→GB, IPv6→JP, parser GeoIP source, forbidden DNS/network and removal passed.
Actual invalid/truncated-reader boundaries are also in pytest. No real dataset
accuracy, Linux execution, client routing or real GeoIP VPS result is claimed.

Package availability and installed API were inspected. The chosen requirement
is **maxminddb>=3.2.0,<4**, tested locally with3.2.0 and Python3.12. Package metadata
requires Python>=3.10. Linux CPython3.10 manylinux2014 **x86_64 and aarch64** wheels
were successfully downloaded; installation compatibility is supported by package
artifacts and the pure-Python FD adapter, not by a real amd64/arm64 VPS run.
See [PyPI](https://pypi.org/project/maxminddb/3.2.0/) and
[reader API](https://maxminddb.readthedocs.io/en/latest/).

**REAL GEOIP VPS ACCEPTANCE: NOT RUN.**
**AUTOMATIC HEALTH REAL DUE ENDPOINT: PENDING.**
**AUTOMATIC HEALTH REAL DUE PROXY: PENDING.**
**REAL POLICY: NOT RUN. REAL HEALTH-AWARE POLICY: NOT RUN.**
These acceptances were explicitly deferred and remain separate. Prior operator
Health evidence is still limited to timer installed/enabled/active, one real
trigger with endpoint=0/proxy=0, real tim systemd-analyze verify PASS, engine
COMPATIBLE and healthz200. No invented completion evidence replaces it.

## Functional gates

| Gate | Result / controlled evidence |
| --- | --- |
| GeoIP default Off | PASS; Generate/Fixed defaults, old callers and v1–v5; pre-feature parser SHA golden and existing default generator goldens |
| Manual > Name > GeoIP > Unknown | PASS; conflicting lookup cannot replace explicit TW, explicit UNKNOWN or name/Preview overrides; Unknown public literal gets GeoIP |
| Literal IP only | PASS; domains, malformed encodings, scoped/mapped IPv6 never reach the reader |
| No DNS | PASS; socket.getaddrinfo/gethostbyname and provider resolver forbidden; genuine-reader smoke also forbids DNS |
| Zero network | PASS; socket, urllib HTTP, provider fetch/resolver forbidden during standalone classification; source refresh retains only its existing provider work |
| Public IP only | PASS; loopback/private/link-local/CGNAT/multicast/unspecified/documentation/reserved/non-global addresses skipped |
| IPv4 / IPv6 | PASS; synthetic public literals and genuine upstream synthetic reader records |
| Geographic country ISO | PASS; country.iso_code only, lowercase normalized; registered_country-only/missing/ZZ/malformed/unsupported remain Unknown; mapping unchanged |
| Display and Preview | PASS; existing name builder, GeoIP source/Ready, safe Unknown warning; no added IP display |
| One reader per operation | PASS; eighty nodes share one open, manual/auxiliary/external aggregation shares one reader, close tracked; verified-memory adapter input stream closes |
| MMDB upload | PASS; extension and32MiB bound, server-controlled path, private staging/header validation, safe metadata/time/hash |
| Atomic replacement | PASS; invalid B retains A; valid C replaces; before/after database and metadata failure rollback; failed first upload selects nothing |
| Removal | PASS; existing Fixed YAML/config/URL and health bytes unchanged; future generation falls back; failed removal restores prior pair |
| Unsafe file rejection | PASS; shared private regular-file helper rejects symlink/FIFO/directory/device/nonprivate files; direct GeoIP tests cover unsafe DB/metadata/directory, no FIFO blocking |
| Missing/corrupt DB fail-open | PASS; parser/Fixed stay operational; missing, checksum mismatch, truncation, bad JSON/perms, unreadable or busy state retains Unknown; no auto repair |
| Lookup error | PASS; individual reader exception leaves Unknown without parser failure or secret logs |
| Settings auth/CSRF | PASS; anonymous access blocked, POST-only actions, missing CSRF not replayed, no-store/no-referrer, safe status/errors and oversized request recovery |
| Fixed registry v6 | PASS; strict authoritative country_detection schema; corrupt v6 fails closed without rewriting |
| v1–v5 migration | PASS; read-time Off, unchanged registry/revision/base/current/cache/token/prefix/URL; public stats retain legacy schema; legitimate action writes v6 |
| External Raw / Base64 | PASS; shared manual parser and local fallback |
| External Clash | PASS; only Unknown name can use literal-IP lookup; country membership uses normal mapping |
| Source refresh | PASS; refresh/refresh-all/enable/disable/delete preserve GeoIP/policy/health config and stable URL |
| Auto source refresh | PASS; saved GeoIP mode, new country group, no additional resolver/network path |
| Policy country membership | PASS; classified SG/TW nodes naturally enter corresponding managed automatic groups |
| Health-aware compatibility | PASS; cached reconciliation preserves GeoIP mode/base/caches without fetch; country change keeps Proxy observation/fingerprint, unhealthy B filters in the new SG group while top-level B remains |
| Fixed URL stability | PASS; country/database-driven changes preserve token/prefix/slug |
| Database change semantics | PASS; upload/remove touch only global database/metadata; next explicit save or legitimate cached reconciliation uses new database |
| No per-revision DB | PASS; Fixed stores mode only; database is global private state |
| Temporary Generate | PASS; same /t format, ephemeral mode, no mode in session/local draft or /t metadata |
| Worker/read safety | PASS; old snapshot survives replace/remove, next reader sees new DB; paused MMDB opening holds no Fixed lock, public read remains responsive |
| Backup/update/uninstall | PASS; real private-state backup helper copies database and settings/permissions in tmp; update/uninstall call that helper; code replacement excludes state |
| Browser | PASS; all original seven suites plus GeoIP (eight total), seven Preview viewports, Settings/Fixed 1440/390 with no overflow; section screenshots inspected |
| Default YAML | UNCHANGED; SHA256 a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b |
| 10,410 rule round trip | PASS; existing default round-trip and pre-policy default goldens retained |

## Validation

| Check | Result |
| --- | --- |
| Full pytest | 1503 passed in 206.78s, 0 failed |
| Playwright | PASS; all original seven suites plus GeoIP (eight total), seven Preview viewports, Settings/Fixed 1440/390 with no overflow; section screenshots inspected |
| Python syntax | PASS; app/core/scripts/tests |
| Node syntax / draft guards | PASS;13 JS/CJS files; existing storage/expiry/corruption/keyboard/Generate guards |
| pip check | PASS; no broken requirements |
| bash -n | PASS; seven scripts |
| ShellCheck0.9.0 /0.11.0 | PASS; seven scripts checked together with repository release-tool invocation |
| build_bootstraps.py --check | PASS; lifecycle source/standalone entrypoints unchanged |
| systemd-analyze verify | UNAVAILABLE locally on macOS; conditional temporary-unit tests retained; GeoIP requires no new unit; prior operator tim PASS remains separate |
| git diff --check | PASS |
| VERSION / Latest Stable | 1.1.1 / v1.1.1 |
| New tag / Release | NO / NO |

Settings Ready validates checksum, header and safe metadata, not every possible
record. Partial record errors fail open. Persistent I/O failure or hard kill
between database/metadata commits can leave an inconsistent pair requiring
private backup recovery or explicit replacement. Runtime Python ipaddress
semantics remain authoritative. Large City datasets exceeding32MiB and all DNS,
automatic download, ASN/ISP/latency/routing/bulk-regeneration features remain
outside scope. See [GEOIP.md](GEOIP.md) for operations and dedicated VPS handoff.

Commit SHAs and clean HEAD=origin/main verification are recorded in the final
delivery after pushing the tested main commits.
