> **Historical pre-release record.** Stable v1.4.0 was published on 2026-10-04.
> Current contract: [Hysteria2 Protocol](HYSTERIA2_PROTOCOL.md).

# Hysteria2 local pre-push audit

Historical pre-push record. The subsequent feature-freeze audit, fresh validation
and separately attributed user VPS evidence are in
[Hysteria2 Final Audit](HYSTERIA2_FINAL_AUDIT_REPORT.md).

Audit date: 2026-10-04. Development main only. VERSION and Latest Stable remain
**1.3.2 / v1.3.2**. No version bump, release command, tag, GitHub Release,
candidate workflow dispatch, managed engine installation or real VPS update.

## Baseline and original commits

Fetch verified remote main `32a77e6777e1fb7706d9ab2afb45d3103363fe14`.
Local main started clean at `c7032c554d93aa6c1950a8faad4eeec0da11e2f6`,
exactly three commits ahead. Merge-base equals remote main. The existing
v1.3.1 deployment-fixture fix is already part of this baseline.

| Commit | Purpose | Files |
| --- | --- | --- |
| `a2bbabebaa61af487b13830b824bbde2eeb3c07e` | Add strict offline Hysteria2 parsing/import and extend existing observation/redaction paths | 11 production/template files |
| `c055e6508b9e2110ecefdd36a7ebe6c6bd7e3cd8` | Add protocol, HTTP/pipeline, privacy, browser and four-protocol golden coverage; replace obsolete unsupported-type fixtures | 8 test/fixture files |
| `c7032c554d93aa6c1950a8faad4eeec0da11e2f6` | Document supported input fields, pinned-engine evidence, deferred checks and Unreleased feature | 7 documentation files |

All three complete diffs and per-commit whitespace checks were reviewed. No
merge, history rewrite, accidental artifact/cache/venv/IDE file, private URL,
developer-specific path or actual credential was found. Test secrets and
example addresses are synthetic. Screenshot destinations are test-only temporary
paths; generated screenshots are not committed.

## Scope and compatibility

The supported contract remains [Hysteria2 Protocol](HYSTERIA2_PROTOCOL.md):
Manual/Batch/Auxiliary, editable Parse Preview, Generate Replace/Merge,
authenticated exact YAML Diff/download, Fixed Manual and External
Raw/Base64/Clash/Auto, source cache and Automatic Refresh. Existing arbitrary
Merge proxy objects, anchors, order and exact collision errors remain preserved.
Country/Special groups, Policy, conservative Health-aware Policy and offline
literal-IP GeoIP use the shared pipeline. No new DNS lookup or health architecture
was introduced.

URI accepts `hysteria2://` and `hy2://`, DNS/IPv4/bracketed IPv6, default 443 and
bounded port hopping. Complete auth is decoded once; literal plus, Unicode and
surrounding spaces are preserved. Absent/empty string auth remains deliberately
allowed by the original pinned-engine contract. Wrong credential types are
rejected; obfs requires a nonempty string password. Raw URI whitespace/controls
are rejected, while percent-encoded credential characters are preserved.

Query keys are explicitly limited to `obfs`, `obfs-password`, `sni`, `insecure`
and `pinSHA256`. Unknown, duplicate, blank and unsupported options fail with
fixed non-sensitive errors. The documented Clash allowlist additionally accepts
ALPN, bandwidth, ports and hop interval; it does not silently import arbitrary
advanced fields. Realm, ECH, client certificates, QUIC tuning and custom URI
bandwidth/ALPN/hop extensions remain rejected/deferred.

Ordinary Parse/Health observations, warnings, errors, logs, source history and
notifications hide both credentials and complete private URIs. Existing private
saved inputs/cache and authenticated full YAML/Diff retain required credentials.
No privacy-model, Fixed v6 schema, bearer or URL change was made.

Endpoint remains TCP-only. URI hopping and ports-only import use the first
concrete port; an explicit Clash `port` remains preserved even alongside `ports`.
Full Proxy retains its existing Mihomo runner/config/controller/status path.
Neither isolated config parsing nor TCP reachability proves live Hysteria2
authentication, QUIC forwarding or delay performance.

## Refresh decision

This request audits the existing revision behavior and authorizes main push after
the gates pass. It supersedes the pending scope decision in the original Phase 1
report. Ordinary source refresh creates a new revision even for identical YAML;
the YAML bytes/cache and Fixed URL remain correct. Health-aware cached
regeneration retains revision when YAML is identical. Both contracts remain
covered; automatic refresh transactions were not changed.

## Audit fixes

- Screenshot review found the Generate header's Parser capability list omitted
  Hysteria2. Add that label and assert it in the Hysteria2 browser suite.
- Assert Hysteria2 in Batch help and both schemes in Auxiliary help.
- Correct stale current-protocol descriptions in source-parser, Merge, Diff
  and Automatic Refresh documentation. Clarify explicit-port observation and
  preserve the original acceptance report as historical evidence.
- Append the audit changes in a new commit; preserve all three original commits.

No Hysteria2 production algorithm bug was found. CSS, browser JavaScript,
dependencies, VERSION, default YAML, Mihomo manifest and release workflows are
unchanged. Five fresh-process parser/source import samples were approximately
0.057–0.059 seconds for both remote baseline and local code. This limited import
measurement is not a live application-startup or throughput benchmark.

## Validation before the final commit

| Check | Result |
| --- | --- |
| Hysteria2 protocol/integration targets | 297 passed, 0 failed |
| Parser/generator/Fixed/source/refresh/health/policy/GeoIP/Diff/deployment related targets | 1895 passed, 0 failed |
| Corrected-tree full pytest run 1 | 2975 passed in 374.72s, 0 failed |
| Corrected-tree full pytest run 2 | 2975 passed in 374.98s, 0 failed |
| Four legacy parser ASTs vs actual remote baseline | Identical: VMess, VLESS, Trojan, Shadowsocks |
| Four-protocol Batch and Replace/Merge goldens vs actual remote baseline | Byte-for-byte identical |
| Default YAML / 10,410-rule round trip | PASS |
| Malformed direct URI boundary corpus | 140 fixed, non-sensitive rejections |
| SHA256-verified pinned Mihomo v1.19.31 isolated `-t` | 15/15 PASS |
| Browser suites | All 17 passed; affected Hysteria2 and UI suites rerun after header fix |
| Final Hysteria2 browser | 1440px and 390px PASS |
| Final UI consistency/density | 140 live page/width checks PASS |
| Python compileall / 3.10 syntax | PASS, 103 files; runtime tests use Python 3.12.14 |
| Node syntax | PASS, 23 files; amended browser file checked again |
| pip check | PASS |
| bash -n / ShellCheck 0.11.0 | PASS, all eight shell entrypoints |
| Bootstrap synchronization / diff checks | PASS |
| systemd-analyze | NOT AVAILABLE on this macOS host; temporary unit-generation tests PASS |

The first incomplete full run was deliberately interrupted after screenshot
review found the header omission: 320 tests had passed, no assertion failed.
Its raw output and exit 2 are retained separately. The two completed runs above
were started after fixing and rechecking the UI. No failure suppression, test
retry, skip, xfail or assertion weakening was introduced.

Default SHA256:

```text
a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b
```

Replace golden SHA256:
`54601483c8b24524995c86d7f582f14641478980845c637e02b57e79d0651b1a`.
Merge golden SHA256:
`76c7dda3a96fd26177b889a01d9795f2bc3703a97c473690f0eb94b8736257e4`.

## Final exact-commit gate

After committing these notes, run only `python3 scripts/release.py --validate-only`
on the clean final commit. That command includes another full pytest run and
does not plan a version or publish. Require unchanged HEAD, tracked/nonignored
file bytes, working tree, VERSION and tags before normal main push. Recheck
remote main ancestry and published tags/Releases, then verify HEAD = origin/main
= actual remote main after pushing. Exact final SHA, validation-only output and
push result are recorded in the final task report, so recording the outcome does
not mutate the already-validated commit.

The read-only Ubuntu candidate workflow was reviewed and left unchanged; it is
not dispatched here. A dedicated feature freeze and real-environment acceptance
remain separate from this main push. Real VPS Hysteria2, actual Ubuntu systemd,
QUIC/authentication/forwarding and previously deferred environment checks remain
unverified. No Stable release is authorized by this audit.
