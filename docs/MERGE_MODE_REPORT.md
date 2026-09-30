# Merge Mode MVP — controlled validation report

Validation record for main development on 2026-10-01, not a stable release.
No release publication command, version bump, tag or GitHub Release is run.

## Baseline and validation

START HEAD: `4e2d08acce328c7b319d651c46c8d24a1726a289`.
Initial main was clean, HEAD matched origin/main and the live remote, VERSION
was 1.2.1 and GitHub Latest Stable was v1.2.1.

Baseline full pytest: **2031 passed in 290.92s**, zero failures, before edits.
Final full pytest: **2133 passed in 317.72s**, zero failures, an
increase of **102**: 60 new Merge cases and 42 additions to the existing diff
matrix/side-effect/concurrency cases. Existing cases were not removed.
Focused final run: **326 passed in 71.44s**, zero failures, covering Merge,
Diff, Draft, Policy Engine and YAML utilities.

END HEAD is the documentation commit containing this report. The final task
response records the exact feature/documentation commit SHAs and verified remote
main after publication; a commit cannot embed its own SHA.

## Modified files

| File | Purpose |
| --- | --- |
| `app.py` | Parse/validate mode for existing private Generate/Diff routes; safe rejected-mode redisplay |
| `core/node_update.py` | Pure exact mode normalization and duplicate-field rejection |
| `core/generator.py` | Pass explicit optional mode, default Replace for existing/Fixed callers |
| `core/yaml_utils.py` | One transform pipeline with Merge append/collision/reference preservation branches |
| `core/yaml_diff.py` | Pass mode to the actual shared transformer; limits unchanged |
| `templates/_generator_fields.html` | Generate-only selector and explicit help |
| `static/draft.js` | Mode save/restore/clear, legacy Replace fallback |
| `tests/fixtures/merge/base.yaml` | Mixed synthetic proxy types, comments, quotes, anchors and unrelated fields |
| `tests/test_merge_mode.py` | 60 core/HTTP preservation, collision, policy, exact output and compatibility cases |
| `tests/test_yaml_diff.py` | Extend actual Preview→Generate matrix and side effects/concurrency to both modes |
| `tests/test_draft.js` | Merge/Replace and legacy/unrecognized draft unit coverage |
| `tests/test_merge_browser.cjs` | Real Merge/Draft/Preview/Generate behavior at 1440/390 |
| `tests/run_preview_browser.py` | Add Merge to the existing complete browser runner |
| `README.md` | Current Generate/default mode, Fixed boundary, input protocol and draft behavior |
| `CHANGELOG.md` | One additional Unreleased Added entry |
| `docs/YAML_DIFF_PREVIEW.md` | Current manual describes selected mode; historical report untouched |
| `docs/MERGE_MODE.md` | User contract and limitations |
| `docs/MERGE_MODE_REPORT.md` | This controlled evidence |

No Fixed registry/schema, mode persistence, sources/refresh, health observation,
protocol parser, auth/password policy, dependency, output URL, bootstrap,
installation identity, VERSION or repository default template is changed.

## Replace regression and shared architecture

The default keyword is `node_update_mode='replace'` through generator, process,
shared transform and preview. Replace retains the original reference cleanup,
proxy assignment, removed-rule guard, policy application and output publication.
Normal legacy rejection redirects remain compatible, with or without an explicit
Replace field. Invalid mode alone is an intentional safe HTTP 400.

Four new before-output SHA cases cover Custom/Default and missing/explicit Replace;
the earlier golden cases also remain active. Expected SHA256 values are unchanged:

- Custom: `77812738ec3a51c8f160cacedc24dc97a9e9d3eeabc7bb0c2db78cc2dd222fda`.
- Default: `3c491ae173585c7a42ceadd4d8634753f38d932a36d92aac0ef7bb16a7e80a69`.

No second Merge transform or browser YAML simulation exists. The same current
form parser, ruamel loader, `transform_yaml_config` and serializer feed both
Diff and real Generate. The option branches only where retained names affect
cleanup/append/collision and existing group-name normalization. Fixed callers
still omit mode and receive Replace; even a submitted Generate mode field on a
Fixed form is ignored and not persisted, verified by real Fixed create/read/edit.

## Merge preservation, topology and validation

- Zero, one and multiple source nodes remain in source order; submitted nodes
  follow in their own order. The original ruamel sequence and original node
  objects are retained, not reconstructed from parsed proxy fields.
- Trojan, SS, Hysteria2, WireGuard, unknown vendor type and VLESS mappings survive
  with unknown extra fields. Key order, quotes, comments, YAML merge keys and
  anchor/alias relationships are checked before and after serialization.
- Manual, unselected, provider and unrelated country groups retain original
  memberships. General groups retain old refs and gain only submitted refs;
  selected Special and currently assigned Country groups get the intended new
  membership. No source-wide classification/repopulation occurs.
- A nonempty group is not emptied/filled by Merge. Truly empty automatic groups
  use submitted candidates; empty Select keeps the established manual fallback.
  No old nodes are automatically added as fallback candidates to unrelated groups.
- Policy docs and related tests were read before development. Preserve and Select
  keep ordinary memberships. Only explicit URL-Test/Fallback/Load-Balance in the
  actual managed Country/selected Special scope rebuild candidate lists from
  submitted nodes, exactly as the prior Policy contract requires. Old top-level
  nodes and their other memberships remain; general/manual groups are unaffected.
- Existing proxy references and MATCH/DOMAIN/IP-CIDR no-resolve rule targets stay
  valid in Merge. The same cases still trigger Replace's removed-target guard.
  Retained flag-looking node names do not accidentally undergo group correction.
- New/source name collisions use the exact safe **Node name already exists in
  source YAML.** message. Existing group/built-in/duplicate-new/newly generated
  group collisions remain rejected. Retained names colliding with a resulting
  group also fail safely rather than producing an ambiguous config. No names or
  rejected mode values are echoed into these errors.
- Same connection/UUID under distinct names is preserved, not deduplicated.
  Unsupported new input protocols still fail; source retention is not input
  protocol support. Missing/invalid/duplicate mode has core and HTTP coverage.
- `old_node_count` still means source count; `new_node_count` still means submitted
  count. There is no new total/semantic/risk metric.

## Exact diff, effects and integrity

The public HTTP diff reconstruction matrix now has **80 cases**: Replace/Merge,
Custom/actual Default, all five policy kinds, manual edits off/on and GeoIP
off/literal IP. Reconstructed UTF-8 bytes equal actual subsequent Generate bytes,
counts and downloaded bytes. Two additional rich-source HTTP cases check Custom
and an **isolated default copy containing proxies**; the real default has zero
proxies. This verifies identical source semantics without altering the repository
template. Latest edits after Parse also pass; applying Merge again with a
colliding submitted name is correctly rejected rather than silently deduped.

For each mode, **100 previews** preserve business byte/stat snapshots while
forbidden-call guards reject cleanup, Generate/output/backup, DNS, connection
and subprocess use. Existing corrupt Fixed/health/notification/temp-link
sentinels remain unchanged; missing GeoIP locks are not recreated. For each mode,
**16 parallel requests / 8 workers** remain isolated with unchanged state.

Merge Generate itself retains ordinary private 0600 upload/output/backup, existing
filename format, source-identical backup, `/t/` URL, downloaded bytes and attachment
behavior. Preview creates none of these. No new health state reads/filtering,
commands or network effects were introduced; full health/Fixed regressions remain.

All existing private Preview authentication/POST/CSRF/no-store/no-referrer,
XSS text rendering, private diagnostics, safe errors and body-log boundaries
remain covered. Diff budgets are unchanged: 2 MiB source/result, 20,000 lines,
512 submitted nodes, 256 source groups, 512 KiB complete diff, 2 MiB JSON/form
values. A source with 513 retained mappings and one submitted node can preview;
retained nodes are governed by source/result size, not the submitted node budget.
An oversized merged result is explicitly rejected with no truncated diff while
normal Generate remains available.

DNS, providers, rule-providers, rules and unrelated custom values retain their
source data. Comments, quoted names/password placeholders, group/ref comments,
anchors and aliases have dedicated fixtures. The real
**10,410-rule round trip PASS** is included in the full suite. Repository default SHA256 remains:
`a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b`.

## Browser, static checks and limits

All **13 browser suites PASS** on the final production code: existing Preview,
Fixed, External/Auto Refresh, Endpoint Health, Proxy Health, Policy, Health-aware
Policy, GeoIP, Settings, HTTPS, Notifications, YAML Diff, plus new Merge.
The new suite runs **1440 / 390**: visible/default selector, switching modes,
Merge-sensitive Diff, real Generate/download, direct Generate without Parse/Diff,
Merge draft restore, legacy Replace fallback, Clear→Replace even after server
Merge error redisplay, Custom lost-file feedback, collision errors, stale mode
responses discarded, no page overflow and no selector in Fixed. Screenshots at
both widths were visually inspected. Original breakpoint/layout coverage remains.

- `compileall` PASS; Python 3.10 grammar **94 files PASS**.
- Node syntax **18 files PASS**, draft unit checks PASS, `pip check` PASS.
- `bash -n` all eight required shell files PASS.
- Available ShellCheck 0.9.0 and 0.11.0, all eight shell files PASS.
- Standalone bootstrap synchronization PASS; `git diff --check` PASS.
- Changed documentation links PASS; historical CHANGELOG sections and README
  release metadata markers unchanged. Historical reports are untouched.
- Deterministic tracked/new-file secret-pattern scan reviewed new candidates:
  TEST_ONLY password placeholders, synthetic UUIDs and example-domain URIs only.
  No runtime secrets/data or removed contact-email displays were introduced.

Merge does not promise raw-source formatting byte identity or complete Mihomo
schema/cycle validation. Shared ruamel serialization retains source data while
normalizing formatting as before; preview/generated bytes are exact. Diff still
has no separate process/hard CPU deadline. Source/MMDB/input changes between
requests can change output; preview is not a reserved transaction. Fixed Merge,
external aggregation changes, overwrite/dedupe UI and new input protocols remain
outside scope. Tests use disposable files, loopback servers and command doubles;
no real /opt, system services/accounts or VPS were modified.

VERSION: **1.2.1**

LATEST STABLE: **v1.2.1**

TAG CREATED: **NO**

RELEASE CREATED: **NO**

REAL VPS MERGE MODE: **NOT RUN**
