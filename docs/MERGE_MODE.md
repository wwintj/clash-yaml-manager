# Node Update Mode — Merge MVP

Generate supports **Replace existing nodes** (default) and explicit **Merge with
existing nodes**. This feature is included in the v1.3.0 release scope. Ordinary install/update uses Latest Stable; see the
[published release notes](https://github.com/wwintj/clash-yaml-manager/releases/latest)
for availability. Explicit `--channel main` is only for development testing.
Controlled evidence is recorded in [MERGE_MODE_REPORT.md](MERGE_MODE_REPORT.md).

## Modes and ordering

Replace removes source proxies, clears the old node references as before, and
uses the currently submitted nodes. Existing Replace bytes, cleanup, validation
and publication behavior remain compatible.

Merge retains every source proxy mapping, in source order, and appends submitted
nodes in input/parser order. It extends the original ruamel sequence rather than
rebuilding source proxies from parsed fields. No sorting, overwriting, renaming,
URI/server/UUID deduplication or protocol conversion occurs.

```text
source:     old-a, old-b
submitted:  new-c, new-d
Merge:      old-a, old-b, new-c, new-d
Replace:    new-c, new-d
```

Existing Trojan, SS, Hysteria, WireGuard or unknown proxy mappings can be retained,
including opaque extra fields. New input uses the shared supported-protocol
parser, including the frozen [Hysteria2/HY2 subset](HYSTERIA2_PROTOCOL.md) released
in Stable v1.4.0. Normal source structure/name checks still apply;
this is not a complete Mihomo schema/protocol validator.

## Collision rules

Merge compares exact final proxy names, including the flags/manual name edits
applied by the existing parser. A submitted name already present in the source
is rejected with **Node name already exists in source YAML.** Distinct names may
have the same connection credentials; they are not silently deduplicated.

Duplicate submitted names and submitted names matching source/generated groups
or built-in policies retain existing validation. A retained source name that
would collide with a resulting managed/general group is also rejected with
**Source node name conflicts with a proxy group.** Resolve the conflict in the
source/input; the server never chooses which entity to rename or delete.

The POST field is `node_update_mode`: only exact `replace` / `merge` are accepted.
Missing means `replace`; empty, unknown, whitespace-padded or duplicate values
are invalid. Invalid mode returns safe HTTP 400 before source publication or
backup. Core callers receive the same safe validation result. Rejected values
are never included in messages.

## Groups, policies and rules

Ordinary existing memberships remain in place. Only submitted nodes are added
to General Groups, selected Special Groups and their current structured Country
groups. Old proxies are not reclassified by name/GeoIP or distributed across
other groups. Unselected/custom/provider groups keep their existing memberships.

The existing flag correction for legacy group names still applies. When an
actual retained proxy has a flag-looking name, its references and rule targets
are protected from being mistaken for group-name corrections.

`fill_empty_proxy_groups` still skips groups with proxies, provider `use` or
include-all behavior. A truly empty automatic group gets submitted node names;
an empty Select uses the existing manual-switching fallback. Only the existing
manual switching empty-group case gets submitted names directly. This preserves
the established fallback without injecting all source nodes into empty groups.

[Policy Engine](POLICY_ENGINE.md) retains its existing managed scope and options:

| Explicit policy | Merge membership behavior |
| --- | --- |
| Preserve | Keep source type/options and existing references, then ordinary submitted-node additions |
| Select | Keep ordinary existing/submitted references; convert type and clear automatic options as before |
| URL-Test / Fallback / Load-Balance | Rebuild only this generation's managed Country and selected Special groups from submitted candidates, in order |

Explicit automatic conversion deliberately removes old/manual/DIRECT/nested/
provider-derived candidates **inside those managed groups**, as its prior contract
requires. It does not remove old top-level proxies or alter their other groups.
General/manual groups are outside Policy Engine. Special precedence on overlaps
and all client-side options remain unchanged. Preserve is the default.

Rules targeting retained proxies remain valid in Merge. The existing
`validate_removed_rule_targets` remains shared: preserved names are still
available, so they cannot be classified as removed. Replace still rejects rules
targeting nodes it removed. Reference validation runs against the resulting
complete proxy/group set.

[Health-aware Policy](HEALTH_AWARE_POLICY.md) remains Fixed-specific. Generate
Merge adds no health-state reads, filtering, ranking, probes or commands.

## Preview, source and draft behavior

[Full YAML Diff Preview](YAML_DIFF_PREVIEW.md) uses the selected mode and latest
form, including inputs modified after Parse. Generate and Diff share
`transform_yaml_config(..., node_update_mode='replace')`, loader and serializer.
With the same source/form/mode/local country data, the diff's generated side
matches actual subsequent Generate YAML bytes. A later edit invalidates the old
diff and discards any in-flight stale response. Preview is optional.

Default and Custom use the same Merge semantics. The current repository default
has zero proxies, so both modes produce the same proxy list for that particular
template; a default containing proxies is preserved exactly like Custom in Merge.
The real `defaults/default.yaml` is never edited or backed up by preview.
Custom still requires an actual selected file; after refresh it must be selected
again. No silent Default fallback is permitted.

The existing 30-day localStorage input draft saves/restores mode. Old drafts with
no field, or an unrecognized stored field, restore **Replace**. Clear Draft
explicitly resets mode to Replace, including after a failed Merge response.
There is no server-side mode persistence. Uploads and diff bodies remain outside
drafts; existing draft node URIs remain sensitive local-browser data.

Preview remains authenticated POST with CSRF, no-store, no-referrer, text-only
display and no private-body logging. It creates no output, backup, temporary link,
business state, network request or process. Normal Generate still creates its
usual private output/backup and `/t/` link after successful validation; ordinary
Generate failure/cleanup semantics are not converted into a new transaction.

Statistics are unchanged: `old_node_count` counts source proxies;
`new_node_count` counts submitted proxies, not total merged proxies.
No new total/semantic/risk metrics are introduced.

## Limits and excluded scope

Diff limits are unchanged: source/result 2 MiB UTF-8 each, source/result 20,000
lines each, submitted nodes 512, source groups 256, complete diff 512 KiB, encoded
JSON 2 MiB, non-file form values 2 MiB. The 512 node budget counts submitted nodes,
not retained source mappings. The source/result budgets still bound the latter.
Over-limit preview fails explicitly without truncation; Generate stays available.
There is no new hard CPU deadline or separate processing worker.

No Fixed Merge or selector/schema/mode persistence, External Sources aggregation
change, refresh change, new protocol parser, overwrite/dedupe controls or public
endpoint is added. Fixed and External→Fixed keep their Replace contract. Shared
serialization aims to retain comments/quotes/anchors, but does not promise
byte-identical source formatting; the exact byte contract compares preview with
actual Generate serialization, not output with raw input.

**REAL VPS MERGE MODE: NOT RUN.** Controlled Flask/browser/YAML fixtures are not
real VPS/client import acceptance.
