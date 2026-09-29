# Fixed Subscriptions (unreleased main)

External node sources extend this MVP; see [External Sources](EXTERNAL_SOURCES.md)
for formats, SSRF, cache, migration and refresh behavior.

VERSION and Latest Stable remain 1.1.1. Test this feature only with explicit
`--channel main`; this development work creates no tag or Release.

## Configuration and storage

The authenticated navigation links Generate YAML and Fixed Subscriptions. Create
and Edit reuse the generator fields, country preview and core generation service.
Fixed forms restore server configuration and never overwrite the browser's temporary
Generate draft. Save parses the latest input even if Preview was not used.

Private files live under the existing service-owned state directory:

```text
state/fixed_subscriptions.json
state/fixed_subscriptions.lock
state/fixed_subscriptions/<internal-id>/<revision>/current.yaml
state/fixed_subscriptions/<internal-id>/<revision>/base.yaml  (default or custom snapshot)
```

The version-2 registry (with in-memory v1 migration) contains subscription UUID4 ids, name, prefix, token, status,
source type, batch/auxiliary nodes, preview overrides, existing policy options,
node/group/rule counts, UTC timestamps and SHA256 retired-token tombstones.
Directories are 0700 and files 0600. A custom base is persisted separately from
uploads; leaving the edit upload empty reuses it. Default-source subscriptions snapshot
the current built-in template when saved; existing v1 default revisions remain readable.

## Atomic save and concurrency

All registry reads/mutations and public reads use the existing `core.state.file_lock`
on one stable lock inode. Generation uses the shared parser and YAML engine. A private
candidate directory outside subscription homes receives the base, source payloads and validated current YAML via
atomic writes. Directory entries are synced before one atomic registry update selects
the candidate and its source configuration together. This indirection avoids a window
where replacing a single `current.yaml` before metadata would expose mismatched state.

Network and generation work runs outside the registry lock. Commit reacquires the lock
and rejects changes to the snapshotted management identity (excluding Last Access).
Until that commit, the old configuration and YAML remain selected. Candidate-generation,
base/current replacement and metadata-write failures are covered by failure injection,
including an error after metadata replacement. If a registry write reports an error,
the previous registry is restored; if rollback I/O also fails, complete candidate files
are retained for recovery instead of deleting possibly referenced data. Persistent
filesystem failure requires checking state and restoring a consistent backup.

Successful saves remove superseded revisions; there is no generation-history feature.
Interrupted candidates never become public. Orphan revisions under a subscription are
collected on its next successful save. Public readers read complete bytes while holding
the same lock; reads already authorized before a management mutation may finish, while
requests authorized after disable/regenerate/delete observe the new state.

## Public URLs and security

Fixed addresses use `/s/<prefix>-fs_<22-character-token>`. The prefix normalizes to
1–64 lowercase ASCII letters, digits and hyphens; empty results use `subscription`.
The token uses `secrets.token_urlsafe(16)` (128 random bits). Saves preserve it. Prefix
changes invalidate the old prefix; regeneration replaces the token. Regenerated and
deleted tokens are permanently reserved by hash, even across later creates.

The existing single `/s/<slug>` handler recognizes the strict fixed namespace, then
retains existing V2 and legacy parsing. Authorization requires the current prefix,
`hmac.compare_digest` token match, active status and a private regular current YAML file.
Invalid, missing or disabled fixed links return 404. Successful responses use YAML,
`Cache-Control: no-store` and `Referrer-Policy: no-referrer`; `?download=1` downloads.
Registry/schema corruption returns a generic 503 without resetting state.

All management pages require login; all mutations require POST and Flask-WTF CSRF.
Regenerate and Delete ask for browser confirmation. Copy URL uses Clipboard API with
visible manual-copy fallback. Fixed forms are not stored in local browser drafts;
failed form validation re-renders the submitted fields without persisting rejected data.
After CSRF recovery the previously saved server configuration remains available.

Tokens remain in private state and authenticated UI only. Application, Werkzeug and
Gunicorn request logs redact fixed URLs. A separately configured reverse proxy has its
own logging policy and should omit/redact bearer subscription paths. No token is written
to `.env`, installation metadata or documentation. Filesystem traversal and symlinks are
rejected. Custom base upload extensions and the existing 50MB request limit remain unchanged.
External node payloads have a separate 10 MiB limit and do not rely on filename extensions.

Last Access is initially Never and updates on successful public reads at most once per
60 seconds across workers. It does not change Updated. Management operations update
Updated; save additionally updates counts. Fixed state is outside uploads/outputs cleanup.
If an access-statistic write fails on a full/read-only disk, validated current YAML can
still be served; Last Access may remain stale until writes recover. A corrupt or unreadable
registry still returns 503. This keeps failed saves from disabling an already valid URL.

## Deployment preservation

Existing update backup/copy exclusions preserve the entire state tree, uninstall's
keep-backup path copies state, and permission repair assigns service ownership with
0700/0600 modes. No deployment script changes are needed. An isolated real-script
upgrade test verifies both the live fixed URL and the backed-up state still resolve.

## Validation and deferred scope

`pytest` covers lifecycle, URL stability, source persistence, token entropy/non-reuse,
schema corruption, private paths, five atomic failure scenarios, process-shared races,
auth/CSRF, fixed/V2/legacy/temporary route coexistence and upgrade preservation.
`python tests/run_preview_browser.py` runs the existing seven-viewport Generate checks
and Fixed CRUD at desktop size, with mobile list overflow/action checks, custom-base
reuse, Copy, confirmations, failed-save preservation and draft separation.

Deferred: Duplicate, detail tabs, refresh schedules,
node health/latency checks, advanced policies, rule editors, databases and history.
