# v1.1 first development phase (unreleased)

Development base: main `5d1cbd0` / v1.0.2, 2026-09-27. VERSION and Latest Stable
remain **1.0.2**. This work does not create tags or a GitHub Release. The existing
workflow only publishes on `v*` tag pushes; an ordinary main push cannot publish.

## A. Scope

Improve Generate YAML draft persistence, session lifetime, mixed node input,
editable parsing preview, country coverage and temporary output/link lifecycle.
Keep Flask, Jinja, Bootstrap, Vanilla JS and ruamel.yaml. No new runtime dependency,
database, frontend framework or change to the built-in default YAML.

## B. Draft persistence

`static/draft.js` stores a versioned, browser-local draft with `saved_at`. Content:
Batch text, every Auxiliary country/name/link row, policy selections, source
choice and preview overrides. Input is debounced 250 ms; change and form submission
save synchronously. Page hide flushes pending input. Login-only pages cannot
replace a saved draft with an empty form. Success does not clear inputs.

Drafts expire after 30 days from the last save and are removed on the next load.
Corrupt/unsupported drafts are discarded safely. Saving / Draft saved / Draft
restored are quiet status messages. Confirmed Clear Draft removes storage, resets
inputs/policies/preview, and cancels pending writes. Storage failures show an
explicit error; Generate is blocked when the draft cannot be saved.

Uploaded file contents, password, CSRF tokens and session cookies are never stored.
Custom YAML selection is restored with “Custom YAML needs to be selected again.”
Client and server reject a missing custom file instead of silently using defaults.
Drafts persist through logout/login and rejected CSRF/session submissions. They
are plaintext localStorage, scoped to browser profile and origin, not a server
backup or a cross-device sync feature.

## C. Session behavior

Permanent sessions now last 30 days, with `SESSION_REFRESH_EACH_REQUEST=True`.
Tests advance time 29 days, refresh, another 29 days, then 31 inactive days to
verify sliding renewal and inactivity expiry. HttpOnly, SameSite=Lax,
COOKIE_SECURE, auth_version/instance checks, password-change global invalidation,
login rotation and CSRF remain. A token can expire earlier than the session;
refresh obtains a fresh token, and the draft restores without retyping nodes.

## D. Batch input formats

Mixed lines support `COUNTRY|NAME|URI`, `NAME|URI`, and `URI` for VMess/VLESS.
Explicit country wins. Name-less URIs use decoded fragment or VMess ps, otherwise
`Node-<physical line number>` padded to at least two digits. Blank lines are skipped.
Duplicate output names, malformed protocol data and invalid ports are errors.
Auxiliary rows are submitted separately as JSON, avoiding duplicate append-on-submit.

## E. Parse preview

Authenticated, CSRF-protected `/parse-nodes` returns safe preview records only:
name, country, protocol, Ready/Warning/Error, source, line and fixed error messages.
No server, UUID, password or full node URI fields are returned; credential-shaped
text in remarks is masked. Rendering uses textContent and input values.

Parse Nodes is explicit. Changes show “Changes not parsed yet”; no parsing occurs
per keystroke. Name/Country edits save immediately; Apply edit reparses. An input
hash plus duplicate occurrence keys overrides, so unchanged rows retain manual
edits after reordering/reparse. Changing raw input invalidates its old override.
Generate always runs the same server parser on the latest form, regardless of
preview state. Errors block generation; warnings do not. In-flight stale preview
responses are discarded if inputs changed. Bulk selection/edit/delete is deferred.

## F. Country recognition rules

Manual > Name Detection > Unknown. Offline detection accepts flags, bounded
English words, uppercase short/ISO codes, Chinese phrases and curated city aliases.
Specific names supersede contained names (North Korea / Korea, 白俄罗斯 / 俄罗斯).
Separate conflicting hints remain Unknown. Compiled patterns are reused across
nodes. There is no DNS lookup, IP lookup, network request or GeoIP dependency.
`LA` inferred from a name means Los Angeles; explicit `LA|...` means Laos.

## G. Country dataset

249 assigned ISO alpha-2 regions, English and Chinese names, flags and aliases in
`core/countries.json` / `core/countries.py`. Unknown is an additional UI choice,
not an ISO entry. Common-first order: US HK TW JP KR SG MY TH PH ID AU CA GB DE FR NL.
Parser, Auxiliary and Preview all use this catalog. Search covers codes, names and
aliases, including the search-only `tai` alias for Thailand. Dataset provenance,
refresh instructions and Unicode permission notice are included in COUNTRY_DATA.md
and UNICODE_LICENSE.txt. Node is used only for development tests/data preparation.

## H. Unknown handling

Unknown uses 🌐 Unknown, Warning and the group 🌐 其他节点. It never blocks Generate.
Users can manually choose a country. Only countries actually present in the input
create new groups; original YAML groups retain the existing preservation behavior.
No blanket generation of 249 empty groups occurs.

## I. Temporary retention

Defaults: uploads 1 hour, outputs 24 hours, cleanup interval 1 hour, backups 7 days.
New installs write HOURS settings. Existing `.env` is preserved; missing UPLOAD /
OUTPUT HOURS values fall back to FILE_RETENTION_DAYS, cleanup to CLEANUP_INTERVAL_DAYS.
New explicit HOURS settings win. Invalid/nonpositive/nonfinite values use defaults.
BACKUP_RETENTION_DAYS (or higher-priority BACKUP_RETENTION_HOURS) remains separate.

Startup/requests trigger cleanup, using a cheap marker check and cross-process lock
with recheck before directory scans. No background process. Idle instances physically
remove files at the next eligible request, while `/t/` independently rejects expiry.
Uploads and outputs are independent. Symlinks are skipped. Logs and arbitrary state
files are never scanned or deleted; only temporary-link records prune their payloads.

## J. Temporary short-link architecture

New Generate returns `/t/<short_id>`; `secrets.token_urlsafe(12)` yields exactly
16 URL-safe characters / 96 random bits. Dates, sequences and filenames are absent
from the path. Metadata in private `state/temporary_links.json` maps IDs to filename,
created_at and expires_at, defaulting to created_at + 24 hours (configured output
retention applies). A separate flock inode serializes workers. The Phase 2 atomic
writer provides mode 600, fsync and atomic replacement; state directories use 700.

Expiry or deletion replaces each metadata payload with a permanent null tombstone.
All historical keys participate in allocation collision checks, including after
restart/prune; 128 failed attempts stop safely. Tombstones are never automatically
removed. Forced-collision regression tests prove expired/deleted IDs cannot bind to
new files. State corruption fails closed. Unknown/expired/deleted links return 404;
responses use no-store, and successful `/t/` responses suppress referrers.

## K. Legacy compatibility

`core/subscriptions.py` remains unchanged. V2 `/s/`, legacy compact/stem links,
`/sub/` and full signed download URLs retain their original checks and work while
the corresponding file exists. New results advertise only `/t/`; their Download
button uses the same temporary ID with `?download=1`. Old signed routes retain
file-existence lifetime, rather than retroactively acquiring temporary-ID expiry.
Physical output retention still cleans expired files. Base URL and request host /
nonstandard port behavior remain; existing tests cover trusted/untrusted proxies.

## L. UI changes

Retain the dark terminal design, ordered 01 YAML Source / 02 Batch Nodes /
03 Auxiliary / 04 Policy / 05 Generate. Add source selection, draft status and
confirmed clear, searchable country selectors, explicit parsing and a responsive
editable preview. Narrow screens stack preview controls instead of wide tables.
Results show Generation Complete, node count, UTC expiry and temporary-link actions.

Real in-app browser smoke test used an isolated loopback server and synthetic nodes:
country search, mixed parsing, auxiliary input, policy selection, manual correction,
refresh restore, logout/login restore, direct Generate and custom-file reselection.
Generated 4 nodes with 10,410 rules and a 16-character `/t/` ID including port 18999.
At the narrow viewport, measured CSS viewport/document width were both 325 px,
preview cards 259 px, with no horizontal overflow. No physical mobile device tested.

## M. Tests

- Baseline: **249 passed**, 82.67 seconds; syntax and diff checks passed.
- Draft/session checkpoint: **252 passed**, 83.23 seconds.
- Integrated checkpoint: **307 passed**, 94.08 seconds.
- Final full suite: **308 passed**, 103.39 seconds.
- Added coverage: draft expiry/corruption/quota/clear, CSRF/session recovery hooks,
  true sliding session expiry, all 249 country names/codes, mixed input, manual edits,
  credential masking, duplicate repair, dynamic groups, API auth/CSRF, latest Generate,
  concurrent processes, metadata modes/corruption, forced historical collisions,
  independent expiry and retention, cleanup throttling/state preservation, old routes.
- Browser storage/search JS tests use Node's built-in assert, with no browser framework.
  Pytest skips that single JS runner when Node is unavailable; Node was available here.
- Python and JS syntax, pip check, bash -n for five entrypoints plus helper, ShellCheck
  0.11.0, bootstrap synchronization, README email exclusion and git diff --check pass.
- Real default YAML round trip passes: 10,410 rules, unrelated content preserved.
  Default byte-for-byte comparison against v1.0.2 passes. SHA-256:
  `a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b`.

## N. Files changed

Added: core/countries.py, core/countries.json, core/retention.py,
core/temporary_links.py, static/draft.js, static/nodes.js, tests/test_draft.py,
tests/test_draft.js, tests/test_v11_nodes.py, tests/test_temporary_links.py,
docs/COUNTRY_DATA.md, docs/UNICODE_LICENSE.txt, docs/V1_1_DEVELOPMENT.md.

Modified: app.py, core/parser.py, templates/index.html, install.sh,
tests/test_app.py, tests/test_deployment.py, README.md, CHANGELOG.md.

VERSION, default.yaml, release automation and existing stable tags stay unchanged.
Repository-local Git email now uses the verified account's GitHub ID-based noreply
address. Global config and historical commits were not changed.

## O. Remaining risks

- localStorage capacity/privacy settings/browser data removal can prevent persistence;
  status reports failures and Generate refuses to submit without saving. Drafts are
  plaintext and origin-scoped; Clear Draft on shared devices. Multiple tabs share one
  draft and last save wins. No cross-device recovery or storage encryption.
- Country inference can be wrong; Manual/Unknown remain available. Identical duplicate
  input occurrences are distinguished by order; changing raw input invalidates overrides.
- Tombstones deliberately grow without bound to uphold non-reuse; metadata operations
  read the single JSON file. Suitable for a personal single-host tool, not high-volume
  multi-host storage. Never roll back/delete link state while keeping historical links.
- No timer daemon means physical cleanup waits for a request. Old signed routes continue
  their historical lifetime until file deletion. Bearer links must be kept private.
- The deployment scripts were tested with command doubles, not real Ubuntu systemd;
  no production VPS upgrade, real reverse-proxy rollout or Mihomo binary validation.
- Browser smoke tests are desktop and a narrow viewport, not a mobile-device matrix.
  CSRF rejection and session expiry use automated server tests plus browser restoration
  checks; no production credential or real node was used.

## P. Explicitly deferred features

GeoIP; Fixed Subscriptions; external subscriptions; node health checks/speed testing;
advanced policies; HTTPS/SSL scanning; Merge Mode; new protocols (Trojan,
Shadowsocks, Hysteria2, TUIC); Dashboard; React/Vue; database; bulk preview operations.
None is advertised as implemented. This remains unreleased main development.
