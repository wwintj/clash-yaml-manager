# Full YAML Diff Preview MVP

Available on explicit `--channel main` during the v1.3 development cycle. This
feature is not in Latest Stable v1.2.1; VERSION stays 1.2.1 and this work creates
no tag or Release. Controlled evidence is in [the report](YAML_DIFF_PREVIEW_REPORT.md).

## Using the preview

On Generate, optionally use **Parse Nodes**, then **Preview YAML Changes**, then
**Generate YAML**. Parsing or diff preview is never a prerequisite for Generate.
The **YAML Changes** panel shows Changed with a complete unified diff, No YAML
changes, or Preview unavailable with a safe validation/size/session message.

The comparison covers the whole source and actual would-be serialized YAML:

```diff
--- source.yaml
+++ generated.yaml
@@ -1,3 +1,4 @@
```

Context is three lines. The summary reuses existing old/new node, total group and
rule counts. Groups is a total, not a count of semantically changed groups. This
is text diff, not a semantic YAML validator or risk score. Comments, quote choices,
formatting, rules and unrelated fields participate in the comparison.

Long lines scroll horizontally inside a bounded monospace panel. YAML is displayed
with `textContent`, never HTML injection. Input changes clear the old diff and
require another preview; a response computed before a later edit is discarded.
Refreshing/navigation discards the diff.

## Exact-preview contract

Both paths parse the latest form, including Batch, Auxiliary and manual Preview
name/country edits. The server never trusts the cached Parse DOM. It uses current
Special Groups, Policy Engine fields and Country Detection/GeoIP choice.
Node Update Mode also participates: Replace is the default, while explicit
[Merge](MERGE_MODE.md) preserves source nodes and appends submitted nodes through
the same transformer. Fixed remains Replace.
Health-aware eligibility is a Fixed-only feature today; this MVP does not add it
to Generate or read health observations.

Both paths share `yaml_utils.load_yaml_stream`, `transform_yaml_config` and
`serialize_yaml` with the same ruamel engine settings. Default/file and in-memory
loading use identical universal-newline handling, including comment tokens.
Randomness and time belong only to filenames/URLs, not YAML content.

```text
latest form → current local country lookup → parsed nodes
source YAML → shared load / selected node update / policies / reference validation
            → shared serialization
              ├─ Preview: bounded in-memory unified diff JSON
              └─ Generate: existing backup / atomic output / temporary link
```

For unchanged source bytes, local GeoIP data and form values, reconstructed
generated-side UTF-8 bytes match subsequent Generate output exactly. Preview is
not a reserved transaction or frozen server snapshot: an administrator replacing
the default/MMDB or changing inputs between requests can change the result.

Generate retains default Replace and VMess/VLESS new input, filenames, backups, counts, redirects,
cleanup, expiry, downloads and `/t/` behavior. Fixed callers still use the same
shared transformer; no Fixed schema, sources, refresh or policy persistence change.

## Default and Custom YAML

Default reads the current `defaults/default.yaml` without writing or backing it
up. Custom consumes the selected `.yaml`/`.yml` upload stream. Refresh restores the
source selector but cannot restore a browser file; the message is:

> Custom YAML needs to be selected again.

No silent default fallback is permitted when Custom is selected without a file.
The existing Generate upload selection/extension rules are shared. Preview does
not save Custom content in uploads/backups/outputs/state. Werkzeug may privately
spool larger multipart parts in framework temporary storage; those files are
0600, outside business directories, and closed/deleted at request teardown.

## Side effects and country data

Preview skips retention cleanup, does not construct page/Settings state projections,
and never calls output/backup/link creation. It does not write Fixed, source caches,
health, notification, policy, GeoIP settings, installation identity or `.env`.
There is no provider request, DNS, probe, Mihomo, Telegram or system command.

Authentication/session/CSRF checks remain in force, including ordinary session
cookie renewal and CSRF recovery. They are not new business persistence. An expired
API session returns private JSON rather than following a GET that runs cleanup.

Opt-in GeoIP consumes a verified immutable byte/hash/metadata snapshot. A present
GeoIP lock is reused nonblockingly without creation/chmod; it is released before
parsing/transformation. A missing lock is not recreated; byte/hash pairing still
checks consistency. Busy, corrupt or unavailable GeoIP fails open to Unknown.
Off mode makes no GeoIP lookup. No Fixed/global transform lock or new persistent
cross-worker state is introduced; each YAML engine/result belongs to its request.

## Limits and validation

The existing multipart HTTP maximum remains **50 MiB**. Preview alone applies:

| Preview resource | Maximum |
| --- | --- |
| Source YAML / serialized generated YAML | 2 MiB UTF-8 each |
| Combined non-file form values | 2 MiB UTF-8 |
| Source / generated text | 20,000 lines each |
| Parsed replacement nodes | 512 |
| Source proxy groups | 256 |
| Complete unified diff | 512 KiB UTF-8 |
| Encoded JSON response | 2 MiB |

The current default is 525,388 bytes / 10,694 lines and previews normally. Bounded
serialization stops while emitting, before collecting an oversized result. Limits
bound work and browser rendering; no separate process or hard CPU deadline is added.

Any exceeded budget returns **Diff is too large to display. Generate YAML is still
available.** No truncated diff is shown as complete. These preview budgets do not
restrict ordinary Generate beyond its existing limits.

Malformed YAML, unsupported structure, invalid URI, duplicate/conflicting names,
policy and country validation use existing parsers/validators. Identical supported
inputs cannot bypass Generate validation through Preview. Errors omit paths,
tracebacks and exception internals. Nonfatal ruamel diagnostics can contain source anchors/scalars. Preview suppresses
those on its own parser instance, without changing global warning filters or the
shared constructor registry. It reuses the installed float handler's exact code;
normal Generate behavior and resulting YAML remain unchanged.

No changes returns `changed: false`, `diff: ""`
and an explicit No YAML changes message.

## Sensitive-data boundary and limitations

`POST /api/preview-yaml-diff` requires authentication and CSRF. Every response,
including rejection, is `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.
Success is JSON; CSRF/session errors are recoverable JSON. No public/downloadable
diff URL exists. Diff content is never logged, notified, placed in session or stored
in localStorage. Request access logs contain only the endpoint/status, not its body.

The authenticated administrator intentionally sees full YAML credentials, UUIDs,
servers, passwords and provider details. Do not share that panel. Redacting YAML
would break the exact-preview contract. Existing input drafts remain independent;
this feature does not store its source upload/generated output/diff in drafts.

This is Generate-only: no Fixed diff/Merge, additional input protocols, semantic
diff, complete Mihomo validation or server-side network testing. Real VPS YAML Diff
Preview is **NOT RUN**; controlled tests/browser checks are not VPS acceptance.
