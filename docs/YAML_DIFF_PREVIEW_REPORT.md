# Full YAML Diff Preview MVP — controlled validation report

Validated on 2026-10-01 for the v1.3 development cycle, on `main`.
This is development work, not a stable release. VERSION remains **1.2.1**;
Latest Stable remains **v1.2.1**. No tag, GitHub Release or release publication
command is created/run by this task.

## Repository and test baseline

- START HEAD: `f62bf50721e3ac00d5d2a2a9f784ede4b79b49cf`.
- Before edits, main was clean and HEAD matched origin/main and the live remote.
- VERSION and GitHub Latest Stable were checked, rather than inferred from the
  supplied expected baseline.
- Baseline full pytest: **1949 passed in 253.13s**, zero failures, before edits.
- Final full pytest: **2031 passed in 287.96s**, zero failures: **82 new cases**.
- Final focused diff/route inventory run: **83 passed in 34.05s** (82 new cases
  plus the existing complete route inventory test).
- END HEAD is the documentation commit containing this report. The final task
  response records its full SHA and both commits after publication; no self-SHA
  is embedded here. Feature/tests and documentation are committed separately.

Full pytest includes Generate, Parse Preview, Draft, Temporary Links, Fixed,
External Sources, Automatic Refresh, Endpoint/Proxy Health, Policy, Health-aware
Policy, GeoIP, Settings, HTTPS, Notifications, lifecycle and release automation.
No historical report has been rewritten.

## Modified files

| File | Purpose |
| --- | --- |
| `app.py` | Private preview endpoint, shared source/group selectors, latest form parsing, preview-specific cleanup/error responses |
| `core/yaml_utils.py` | Shared in-memory transformer, loader and exact serializer; existing publication wrapper |
| `core/yaml_diff.py` | Bounded source/transform/diff, safe validation and per-parser diagnostic isolation |
| `core/geoip_store.py` | Read-only GeoIP snapshot lookup without lock creation/chmod |
| `static/nodes.js` | Latest-form preview, text-only rendering, stale-response discard |
| `templates/_generator_fields.html` | Generate-only button with `type="button"` |
| `templates/index.html` | Separate bounded monospace YAML Changes panel |
| `tests/test_yaml_diff.py` | Exact-output, validation, security, side effects, limits and concurrency |
| `tests/test_yaml_diff_browser.cjs` | Real browser behavior at 1440 and 390 pixels |
| `tests/run_preview_browser.py` | Add the diff suite to the existing browser runner |
| `tests/test_final_audit.py` | Extend complete route inventory/auth/CSRF expectations |
| `README.md` | Describe preview and remove the old unimplemented-diff limitation |
| `CHANGELOG.md` | One human-readable Unreleased Added entry |
| `docs/YAML_DIFF_PREVIEW.md` | Usage, contracts, limits and sensitive-data boundary |
| `docs/YAML_DIFF_PREVIEW_REPORT.md` | This current validation record |

No new dependency, Fixed schema, source/refresh persistence, authentication or
password policy, VERSION, default YAML, release markers or deployment script
change. `core/generator.py` still delegates to the existing YAML processing entry
point; its parsing remains the authority for both request paths.

## Shared pipeline and exact YAML evidence

Preview and Generate parse current form inputs, then use shared
`load_yaml_stream`, `transform_yaml_config` and `serialize_yaml`. The extracted
transform retains Replace, cleanup, countries, Special Groups, policy generation,
optional existing Fixed group callback and reference/rule validation. Preview
uses bounded memory; Generate retains streaming atomic publication, backups,
filenames, temporary links, downloads, counts, redirects and cleanup.

- **40 exact HTTP contract cases** reconstruct the generated side from the public
  unified diff, then compare UTF-8 bytes with actual subsequent Generate output
  and download. Matrix: Default/Custom, all five policy types, manual edits
  off/on, GeoIP off/literal IP; selected Special Groups and counts are included.
- Two known before-refactor fixtures were computed using the actual production
  module from START HEAD, then retained as output SHA256 regressions:
  Custom `77812738ec3a51c8f160cacedc24dc97a9e9d3eeabc7bb0c2db78cc2dd222fda`;
  Default `3c491ae173585c7a42ceadd4d8634753f38d932a36d92aac0ef7bb16a7e80a69`.
- CRLF comments, missing EOF newline and UTF-8 BOM cases also reconstruct exact
  Generate bytes. Shared universal-newline loading prevents CRLF comment drift.
- Latest-input-after-Parse and no-change cases pass. Invalid URI, duplicate name,
  group conflict, malformed YAML, unsupported structure, invalid policy, missing
  Custom upload and wrong extension retain Generate validation behavior.
- The source was inspected: random/time fields affect file names and URLs, not
  YAML content. Preview is not a frozen transaction; changing source, MMDB or
  form values between requests can legitimately change the generated result.
- Health-aware policy is currently Fixed-only. No new Generate health integration
  or observation reads were introduced to simulate an input that does not exist.

Default reads the actual template without modification/backup. Custom requires an
actual selected file, including after page refresh; missing files show **Custom
YAML needs to be selected again.** There is no default fallback. Werkzeug's larger
multipart spool was checked as private 0600 temporary storage, closed at request
teardown, with no saved business file.

## Side effects, privacy and concurrency

- **100 previews** leave byte/stat snapshots of uploads, outputs, backups and
  state unchanged, including expired retention candidates, cleanup marker,
  temporary links, Fixed/health/notification sentinels and installation/env data.
  Cleanup, Generate, backup/output creation, DNS, connections and subprocess
  calls are replaced by forbidden-call guards during this test.
- Enabled GeoIP reads verified bytes/hash/metadata without writes. A deleted lock
  is not recreated; a present lock's stat metadata remains unchanged. Busy locks
  fail open; FIFO/symlink/directory lock cases are rejected without mutation.
  Any lock is released before YAML transformation. No Fixed/global state lock
  or new persistent cross-worker state is added.
- **16 simultaneous previews through 8 workers** use isolated clients and unique
  names; every response contains only its own result and business state is unchanged.
- Anonymous POST is rejected, GET is rejected, missing/invalid CSRF is rejected.
  Auth-store failure and multipart 413 have safe JSON responses. Every endpoint
  response has no-store/no-referrer headers. Auth/session/CSRF cookie bookkeeping
  remains normal; there is no business mutation or redirect-followed cleanup.
- No output/backup/temp/public diff URL, application body log, notification,
  diff session storage or localStorage is created. Browser drafts remain the
  existing input drafts and do not store diff/source-upload/generated content.
- HTML/script/image sentinels and Unicode remain literal `textContent`; they do
  not execute or become DOM elements. Authenticated administrators can see full
  YAML credentials; redaction would break exactness.
- Unexpected ValueError/RuntimeError/OSError at input or transform stages cannot
  echo exception text, private paths or traceback into responses/logs/files.
- ruamel's nonfatal duplicate-anchor and YAML 1.1 float warnings can contain
  private source values. Preview suppresses them on its own parser. Global
  warning filters and the shared constructor registry stay unchanged; ordinary
  Generate parsing/diagnostics and YAML bytes remain unchanged. The installed
  float handler's code is reused with private warning globals, not reimplemented.
- A deterministic secret-pattern scan covered tracked and new source files.
  Changed-file candidates were synthetic invalid/test URIs and test UUIDs using
  reserved example domains, not operational credentials. No runtime data was
  staged. No removed contact-email display was reintroduced.

## Resource limits and browser evidence

Preview alone limits source/result to **2 MiB UTF-8 each**, non-file form fields
to **2 MiB**, source/result to **20,000 lines each**, replacement nodes to **512**,
source groups to **256**, complete diff to **512 KiB UTF-8**, and JSON to **2 MiB**.
The existing multipart maximum is unchanged at 50 MiB. Emission stops at the
serialized output budget. Over-limit responses explicitly reject preview, never
show a silently truncated diff; ordinary Generate remains available. All eight
budget paths plus inclusive UTF-8 diff/source boundaries and invalid UTF-8 pass.

All **12 browser suites PASS**: Preview/layout, Fixed, External/Auto Refresh,
Endpoint Health, Proxy Health, Policy, Health-aware Policy, GeoIP, Settings,
HTTPS, Notifications and YAML Diff. The diff suite was additionally rerun on the
final production code and passed at **1440 / 390 pixels**. After the full browser
run, remaining production changes were confined to this new API's
error/diagnostic handling.

The new suite covers visible button, Default/actual Custom, changed/no-change,
validation, latest textarea edits after Parse, escaped script/HTML, long-line
internal horizontal scrolling, unchanged page width, Enter/implicit-submit
guard, direct Generate without Preview, CSRF/session feedback and stale-response
discard. Both panel screenshots were visually inspected. The original Preview
layout suite also passes at 1440, 1024, 390, 1200, 1199, 768 and 767 pixels.

## Integrity and remaining limits

- `compileall` PASS; Python 3.10 grammar check **92 files PASS**.
- Node syntax check **17 files PASS**; dependency `pip check` PASS.
- `bash -n` all eight required shell files PASS.
- Available ShellCheck **0.9.0 and 0.11.0**, all eight shell files PASS.
- Standalone bootstrap synchronization `build_bootstraps.py --check` PASS.
- `git diff --check` PASS; historical CHANGELOG sections and README release
  metadata markers unchanged.
- Default template **525,388 bytes / 10,694 lines**; **10,410-rule round trip PASS**.
- `defaults/default.yaml` SHA256 unchanged:
  `a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b`.

There is no separate process/hard CPU deadline. Limits bound input/output and
rendering, but difflib/YAML work still consumes a normal request worker. Parser
diagnostic isolation uses ruamel's installed constructor interface and is tested
against the current dependency; upgrading ruamel must rerun these cases. Existing
Generate diagnostic policy is outside this preview feature's logging changes.
GeoIP/source updates between requests are not reserved by preview. This is not
semantic diff, a complete Mihomo validator, Fixed Diff, Merge or new protocols.

- VERSION: **1.2.1**
- LATEST STABLE: **v1.2.1**
- TAG CREATED: **NO**
- RELEASE CREATED: **NO**
- REAL VPS YAML DIFF PREVIEW: **NOT RUN**

All browser/lifecycle/state tests use disposable directories, loopback servers
and command doubles. No real VPS, developer-machine /opt, service/account or
privileged deployment environment was modified.
