# Hysteria2 feature freeze and v1.4.0 final audit

Audit date: 2026-10-04. **FEATURE FREEZE: PASS. HYSTERIA2 CONTRACT: FROZEN.**
**SEMVER: MINOR. TARGET: v1.4.0.** This is a pre-publication audit. VERSION and
Latest Stable remain **1.3.2 / v1.3.2**; Hysteria2 is available only on main.
No v1.4.0 tag, GitHub Release or formal publishing command is authorized here.

## Baseline and scope

- START HEAD: `b68a84b63af9eb4abc839ccf5c17d44e146ac955`.
- Stable v1.3.2 peeled commit: `32a77e6777e1fb7706d9ab2afb45d3103363fe14`.
- Fresh fetch, branch main, clean tree and merge-base verified. START HEAD equals
  origin/main and the actual remote main ref; GitHub Latest Stable is v1.3.2.
- At entry, v1.3.2..HEAD contains five Hysteria2 commits and 30 changed files.
  This audit adds one documentation commit and this report, for six commits and
  31 changed files. Exact final SHA is recorded in the final task closeout,
  after committing this file and validating that immutable commit.
- Hysteria2 adds a user-visible input protocol. Legacy output contracts remain
  compatible, so MINOR → v1.4.0 is appropriate; neither patch nor major is used.

All 30 changed files were reviewed against the actual stable tag: six core
modules (parser, source parser, YAML validation, node extraction, probe docstring,
UI messages); five templates; eight test/fixture files; README, CHANGELOG and nine
protocol/source/refresh/health/Merge/Diff documentation files. No actual secret,
private provider URI, developer absolute path, screenshot, cache, venv, IDE file
or generated runtime data was added. Test credentials and example hosts are
synthetic. Screenshot output remains outside the repository.

This turn changes documentation only: fix README's four-protocol-only feature
bullet; distinguish Stable v1.3.2 from main-only Hysteria2; correct the current
refresh build example; mark historical reports; freeze the contract and record
this audit. The original Phase 1 Node inventory typo (22) is explicitly annotated;
the fresh inventory is 23. No production algorithm, CSS/JS, dependency, deployment
script, workflow, Mihomo manifest, runtime schema or default YAML is changed.
CHANGELOG retains a concise Unreleased Added note; audit counts do not enter
release notes.

## Frozen supported and deferred contract

[HYSTERIA2_PROTOCOL.md](HYSTERIA2_PROTOCOL.md) is the frozen input contract.
`hysteria2://` and `hy2://` map to `type: hysteria2`; offline hostnames, IPv4 and
bracketed IPv6, default port 443, single ports and bounded hopping are supported.
Whole userinfo is percent-decoded exactly once, preserving literal plus, Unicode,
spaces and encoded password characters. Absent and explicitly empty auth remain
allowed by the original pinned-engine contract; wrong credential types fail.
Obfs supports only Salamander/Gecko and requires nonempty string obfs-password.

The query allowlist remains exactly sni, insecure, obfs, obfs-password and
pinSHA256. Strict types, duplicate/blank/unknown-key rejection and fixed private
errors remain. The documented Clash allowlist additionally retains existing
ALPN, up/down, ports and hop-interval grammar, without arbitrary engine fields.
No URI bandwidth/ALPN/hop extension is admitted during the freeze.

Hopping remains bounded to 512 characters, 28 segments and 65,535 expanded ports.
The fresh extra boundary harness passes seven positive and twelve negative cases,
including exact bounds, order, malformed punctuation, empty/reversed ranges,
zero/overflow and negatives. URI and ports-only imports use the first concrete
port for existing generator/TCP observation; an explicit Clash port is retained.

Realm, ECH, client certificates, advanced QUIC tuning, Gecko packet-size options,
new obfs, bandwidth, ALPN or hop syntax, arbitrary fields, new Health architecture
and new UI workflows remain excluded. Mihomo stays pinned to **v1.19.31**.

## Surface, privacy and output matrix

| Surface / invariant | Fresh controlled result |
| --- | --- |
| Manual / Batch / Auxiliary | PASS; both aliases, mixed five protocols, order, Country/Name edits and duplicate rejection |
| Parse Preview | PASS; English Hysteria2 display; both credentials and private URIs hidden |
| Generate Replace | PASS; existing source handling, Default/Custom and policy variants |
| Generate Merge | PASS; preserve source objects/anchors/order, append only; collision rejects without overwrite/rename/dedupe |
| Full YAML Diff | PASS; 20 HTTP combinations plus browser patch reconstruction equal Generate/download bytes |
| Fixed Manual | PASS; save/edit/manual refresh/regenerated link; stable URL during edit/refresh; v6 schema unchanged and Replace only |
| External Raw / Base64 / Clash | PASS; uploaded and controlled remote; strict bounded parser and mixed source order |
| Automatic Refresh / cache | PASS; success, unchanged bytes, invalid update, last-good cache/output and recovery |
| Endpoint Health | PASS controlled TCP observation; representative port only, no QUIC/auth/forwarding claim |
| Full Proxy Health | PASS existing runner/config/controller/status path; 0700/0600, silent logs and loopback controller |
| Connection identity | PASS; rename stable, connection/credential/obfs/SNI/port changes invalidate identity |
| Country / Special groups | PASS shared generator grouping and membership |
| Policy / Health-aware Policy | PASS; fresh confirmed unhealthy only, stale/suspect retained, Select unchanged, minimum/fail-open preserved |
| GeoIP | PASS offline public literal-IP lookup only, Manual/Name priority, no hostname DNS |
| Warnings/errors/history/logs/notifications | PASS; no auth, obfs-password or complete private URI |
| Authenticated full YAML/Diff | PASS; actual required credentials retained under existing privacy model |

The existing private saved inputs/cache and browser-local input draft model remain
unchanged. No global credential redaction of authenticated YAML is introduced.
Both aliases return fully masked `mask_sensitive` output. Fixed auth/CSRF and
private error boundaries are covered by fresh integration/browser tests.

Ordinary source refresh continues to create a new revision even when YAML bytes
are identical, while retaining the public URL and correct cache/output. Cached
Health-aware reconciliation keeps the revision if YAML is identical. This is the
existing transaction contract, explicitly retained by the current request; no
revision architecture is changed. Source fetching/SSRF protections are unchanged.

## Legacy protocols and default YAML

Fresh isolated extraction of actual `v1.3.2` core code, compared with the current
code, proves all four parser function ASTs unchanged: VMess, VLESS, Trojan and
Shadowsocks. Representative complete Batch records match both the actual stable
code and the pre-feature golden. Replace/Merge serialization matches byte for
byte; the shared Diff implementation is unchanged and legacy Diff cases pass.

- Replace SHA256: `54601483c8b24524995c86d7f582f14641478980845c637e02b57e79d0651b1a`.
- Merge SHA256: `76c7dda3a96fd26177b889a01d9795f2bc3703a97c473690f0eb94b8736257e4`.
- Default YAML SHA256: `a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b`.
- The real default **10,410-rule roundtrip: PASS**, including the full suite and
  Hysteria2 Default integration combinations. The file is never edited.

## Fresh local validation

These are new runs for this freeze, not reused pre-push evidence.

| Check | Result |
| --- | --- |
| Hysteria2 protocol/integration targets | 297 passed in 15.85s, 0 failed |
| Related parser/source/Merge/Diff/Fixed/refresh/health/policy/GeoIP/deployment regression | 1895 passed in 295.41s (0:04:55), 0 failed |
| Full pytest run 1 | 2975 passed in 378.70s (0:06:18), 0 failed |
| Full pytest run 2, consecutive | 2975 passed in 373.62s (0:06:13), 0 failed |
| Existing complete browser runner | All 17 suites PASS |
| Hysteria2 browser | 1440px and 390px PASS; labels/help/Parse/Fixed/External/Diff/Replace/Merge/privacy/XSS/no overflow |
| Full UI consistency | 140 live page/width checks PASS; English, v1.3.1 typography/density retained |
| Python compileall / Python 3.10 AST | PASS, 103 files; runtime Python 3.12.14 |
| Node JS/CJS syntax | PASS, 23 files |
| pip check | PASS |
| bash -n / ShellCheck 0.11.0 | PASS, all eight shell entrypoints |
| Bootstrap synchronization / diff checks | PASS |
| Malformed direct URI corpus | 162/162 fixed non-sensitive rejections, no crash |
| Pinned Mihomo v1.19.31 isolated `-t` | 15/15 PASS; fresh private temporary configs, no live proxy traffic |
| Local systemd-analyze | Unavailable on macOS; separate Ubuntu evidence below |

Pinned Darwin arm64 binary SHA256 is
`fae1f37e28ee53fcf5be7a8bb121099db1fe442e44205734ed49c62579364090`;
its `-v` was rechecked. The exact official archive was verified during development;
this freeze rechecks the binary hash/version and reruns all 15 configurations.
This is config parsing, not real Hysteria2 server or Linux engine forwarding.

No skip/xfail, flaky retry, weakened repository assertion or test suppression was
introduced. One extra audit harness initially expected the protocol-specific
exception from an internal port helper; that helper retains a fixed generic
ValueError. The corrected harness checks the public URI parser's fixed protocol
error. This was an audit-harness correction, not a product/test change.

## Real Ubuntu VPS evidence — user attestation

The user reports that Ubuntu VPS **tim** deployed exact main commit
`b68a84b63af9eb4abc839ccf5c17d44e146ac955` using
`remote-update.sh --channel main`. Codex did not independently access this VPS.
The supplied INSTALLATION.json reports base_version 1.3.2, channel main, that
exact commit, source github-main and tag null.

| User-supplied real VPS check | Result |
| --- | --- |
| REAL VPS MAIN DEPLOYMENT | PASS at the supplied b68a84b commit |
| REAL UBUNTU SYSTEMD FIVE-UNIT VERIFY | PASS; systemd-analyze verify exit 0, no stderr/parser warning |
| REAL MAIN SERVICE / HEALTHZ | PASS; active/running; Gunicorn 26.2.0, two workers, bind 0.0.0.0:8899; local healthz OK |
| REAL REFRESH TIMER | PASS; enabled and active |
| REAL HEALTH TIMER ACTIVATION | PASS; enabled/active and entered an actual scheduled run |
| REAL HYSTERIA2 QUIC/AUTH/FORWARDING | **NOT RUN** |

The five verified units are the app service, refresh service/timer and health
service/timer. The supplied deployment SHA predates this documentation-only
freeze commit; it is not falsely attributed to a later SHA. Hysteria2 server
port hopping and latency also remain unverified. Timer activation alone does not
prove a successful real provider refresh or real Hysteria2 probe.

## Final exact-commit gates and release recommendation

Commit this report and the documentation corrections normally, preserving all
five existing main commits. On that **clean final HEAD**, run local
`python3 scripts/release.py --validate-only`, require PASS, and compare HEAD,
VERSION, tags, working-tree status and all tracked/nonignored file hashes before
and after. Normally push main and verify HEAD = origin/main = actual remote main.

Only then run **`python3 scripts/release.py minor --dry-run`**. Require preflight
and dry-run PASS, current VERSION/stable 1.3.2, proposed v1.4.0, and only planned
VERSION/README/CHANGELOG changes. Compare local files/HEAD/tags and remote
main/tags/all Release objects before and after; no mutation is permitted.

Dispatch **release-candidate.yml** with `ref` set to the exact full final SHA.
Await completed/success and verify the log's Validated commit SHA is that SHA,
Python 3.12 and validation PASS. Ubuntu's available systemd-analyze makes the
existing temporary five-unit and refresh-pair pytest validation paths applicable;
it is separate evidence from the user VPS. Recheck clean main and require local
HEAD = origin/main = actual remote main = Ubuntu validated SHA. Any changed main
or failing gate blocks readiness and requires validation of the new final commit.

The final task closeout records the actual immutable SHA, run URL, local
validate-only/dry-run and Ubuntu RC outcomes after these commands execute. They
cannot be recorded as completed inside the commit before validating that same
commit. This avoids moving main after a successful exact-SHA gate. Local pre-commit
checks and the user Ubuntu evidence above are already completed; final readiness
is conditional on all post-commit gates passing.

Recommendation: **READY FOR FORMAL v1.4.0 RELEASE only after all final gates PASS**.
Preserve Stable v1.3.2 and every published tag/Release. Verify no v1.4.0 local tag,
remote tag or Release exists. Even on success, stop here: this task does not
execute formal `release.py minor`, bump VERSION, create/push a tag or publish.
Real Hysteria2 QUIC/authentication/forwarding remains NOT RUN; previous deferred
HTTPS/Telegram/arm64/Reality acceptance is not promoted by this audit.
