# Trojan Protocol MVP Acceptance Report

Audit date: 2026-10-01. Development only; no release/version/tag operation.

## Starting evidence

- Branch `main`; clean before work.
- START HEAD: `8d5ba5f19445fa619efcfba1ca99c5754691a0b3`.
- Local HEAD, origin/main and actual remote main matched before editing.
- VERSION `1.2.1`; actual GitHub Latest Stable title/tag `v1.2.1`.
- Full baseline completed **before any edits**: **2133 passed in 321.68s**.
- Stable annotated tag object `457787de1ee12d441605709bc59dc8d2e84737be`,
  peeled commit `f62bf50721e3ac00d5d2a2a9f784ede4b79b49cf`.
- Publication target is main only. Final commit IDs and remote equality are
  verified after committing/pushing and recorded in the task's final response.

## Implementation evidence

| Area | Evidence |
| --- | --- |
| URI | `urllib.parse.urlsplit`; lowercase scheme; IPv4/DNS/bracketed IPv6; explicit port 1–65535; percent decode once; no credential `split('@')`. |
| Password | Nonempty string only; preserves surrounding spaces, Unicode, reserved characters and all-space values; YAML imports are not URI-decoded. |
| TLS/SNI/transport | TCP and WS; inherent TLS; `sni`/`peer` aliases must match; WS path/Host; unknown, repeated, empty or unsupported parameters fail. Pinned-source references in the manual. |
| Batch/Aux/Parse | All three line forms; mixed VMess/Trojan/VLESS/Trojan input order; Aux WS; editable name/country; duplicate final names remain errors. |
| Replace/Merge | Same shared transformer; append after preserved arbitrary source mappings in Merge; fixed name-conflict error; no overwrite/conversion. |
| Exact Diff | 20 real HTTP cases across Default/Custom × Replace/Merge × all five policies, with mixed Batch/Aux and Manual/Name/GeoIP/Unknown coverage. Public unified diff reconstruction equals subsequent Generate output and downloaded bytes. |
| Fixed Manual | Batch/Aux, manual overrides, save/edit; private revision changes but token/URL stable; registry remains v6. |
| External | Raw/Auto comments/order; standard and URL-safe Base64; explicit bounded Clash Trojan fields; unsupported skip count; tags/cycles/non-string keys rejected. Uploaded Raw/Base64/Clash/Auto integration. |
| Auto Refresh | VMess/VLESS → mixed Trojan; new revision/cache commit; malformed Trojan → last-good bytes/cache; fixed 300s first backoff; recovery resets to existing 900s interval and keeps URL. |
| Policy | Preserve/Select/URL-Test/Fallback/Load-Balance; country and selected Special groups use names/membership, no protocol branch. |
| GeoIP | Manual > Name > offline public literal IPv4/IPv6 > Unknown; private/documentation addresses and hostname do not resolve. |
| Endpoint Health | Explicit user scope clarification allowed only protocol admission/password redaction in shared extraction. Existing injected TCP probe gets server/port; no probe algorithm/state/scheduling changes. |
| Full Proxy Health | Same extraction and injected runner; success/failure thresholds and private observation state; full config in 0600 opaque-name probe YAML, loopback controller, silent logging. No protocol-specific probe or binary upgrade. |
| Credential safety | URI/remark/override redaction; fixed errors/logs; instance-local suppression of YAML 1.1 float warnings that could echo malformed credentials; no configs/password in observational names/state or notification events. Raw inputs/drafts and authenticated final YAML/Diff retain credentials by design. |
| VMess/VLESS | Four parser mappings captured from START HEAD before edits. Replace/Merge byte SHA goldens captured at the same time; existing Default/custom and policy byte goldens remain enforced. |
| Mobile | Existing long output filename overflow exposed by the new browser case was fixed with local wrapping; no filename/download semantics change. |

`tests/test_trojan_protocol.py`: 165 offline cases.
`tests/test_trojan_integration.py`: 36 end-to-end controlled cases.
**201 added pytest cases**, with one obsolete Trojan-unsupported parameter removed
from the existing negative matrix (other unsupported input protocols remain tested).
The old Clash skipped-protocol fixture now uses SS, retaining that original test.

Before-change hashes, in `tests/trojanfixtures/before.json`:

```text
Custom Replace: 77812738ec3a51c8f160cacedc24dc97a9e9d3eeabc7bb0c2db78cc2dd222fda
Custom Merge:   f9be22dfd2ad1493c524a00d596e02700858af55cc5c1442ec97394828ebab81
Default output: 3c491ae173585c7a42ceadd4d8634753f38d932a36d92aac0ef7bb16a7e80a69
GeoIP Off parser: 87846180e8e41a305c0247e359c9a08aaa3adf31e63048080f4d06da727a6ab4
```

## Validation gates

- All **14 browser suites PASS**: Preview, Fixed, External, Endpoint Health,
  Full Proxy, Policy, Health-aware Policy, GeoIP, Settings, HTTPS, Notifications,
  YAML Diff, Merge and Trojan. Trojan explicitly covers 1440px/390px helper text,
  mixed protocols, Aux, credential-safe Parse, edits, Diff, Replace/Merge Generate,
  downloaded YAML and no horizontal overflow. Preview also retains all seven
  existing breakpoint checks.
- Final full pytest: **2333 passed in 352.13s**, **0 failed**. Baseline 2133;
  201 added cases and one removed obsolete unsupported-Trojan parameter: net +200.

Static gates completed: compileall and Python 3.10 syntax for 96 Python files,
Node syntax for all 19 JS/CJS files, pip check, all eight bash syntax checks, all eight
ShellCheck checks with both 0.9.0 and 0.11.0, bootstrap synchronization and
`git diff --check`. Secret-pattern review includes untracked additions and Trojan
URI patterns; added examples/fixtures are synthetic, with no operational credentials.

The full regression includes Generate/Parse/Draft/Temporary Links/Diff/Replace/Merge,
Fixed/External/Auto Refresh, Endpoint/Full Proxy/Scheduler, all policies/Health-aware
Policy/GeoIP, Settings/HTTPS/Notifications and release/lifecycle automation.

Existing real default round-trip tests assert unchanged non-proxy sections and
rules; Default policy tests assert all **10,410 rules**. Source default SHA remains:

```text
a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b
```

External Source 10 MiB, plain depth 32/budget 100000/cycle protections, Diff source
and result 2 MiB, form 2 MiB, 20000 lines, 512 nodes, 256 source groups, 512 KiB diff,
2 MiB response and multipart 50 MiB remain unchanged. Parser/import additions make
no network, DNS or subprocess calls and introduce no persistent protocol state.

## Validation limits

Health/refresh integrations use fake clocks, resolver/probe/runner/fetch injections;
browser uses an isolated Flask copy and loopback fixtures at 1440px and 390px.
No live Trojan endpoint, Linux Mihomo process or real Ubuntu VPS acceptance was run.
Pinned upstream source review establishes mapping semantics, not real network proof.
No /opt, systemd, accounts, runtime data, defaults, auth, dependencies, Fixed schema,
Mihomo manifest/version or release source was changed. No release command was run.

VERSION: 1.2.1
LATEST STABLE: v1.2.1
TAG CREATED: NO
RELEASE CREATED: NO
REAL VPS TROJAN PROTOCOL: NOT RUN
