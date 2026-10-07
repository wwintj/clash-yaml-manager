# Fixed Subscriptions list UX

Fixed Subscriptions 管理改善已隨
[Stable v1.5.0](https://github.com/wwintj/clash-yaml-manager/releases/tag/v1.5.0)
正式發布；目前 VERSION 為 1.5.0，README Latest Stable 為 v1.5.0。
[發布前最終審計](V1_5_FINAL_AUDIT_REPORT.md) 記錄當時的功能凍結、真實 VPS 驗收
及恢復至 v1.4.1 Stable 的結果；[Phase 1 報告](FIXED_SUBSCRIPTIONS_UX_REPORT.md)
同樣保留為歷史驗收證據，不代表目前尚未發布。

## Search, filter and order

The management toolbar enhances `/fixed-subscriptions` in the browser. Search
matches subscription name or URL prefix, trims surrounding query whitespace and
uses case-insensitive JavaScript lowercase comparison. Unicode names are accepted.
The management index contains only name, prefix, active/disabled status, numeric
node count, numeric Updated timestamp and original row order. It never indexes
bearer tokens, full public URLs, source URLs, credentials or node URIs.

Status options are All Status, Active and Disabled. Filtering changes visibility
only. No query parameters, requests, server preferences or browser storage are
used. The count reports all subscriptions or `X of Y subscriptions`; zero matches
shows `No subscriptions match your filters.` separately from an empty registry.
Clear filters restores an empty search, All Status and Updated — Newest.

| Sort | Comparison |
| --- | --- |
| Updated — Newest / Oldest | Numeric committed UTC timestamp, descending / ascending |
| Name — A to Z / Z to A | Lowercased strings, deterministic Unicode code-unit order, ascending / descending |
| Nodes — High to Low / Low to High | Numeric node count, descending / ascending |

Updated — Newest is the enhanced default. Every tie retains original server DOM
order, including descending sorts. The backend `store.list()` order is unchanged.
Token values and internal IDs are not sort keys. Updated and Last Access remain
server-rendered UTC and are never converted to browser-local time.

## Source and Health summaries

External Sources is the configured source count excluding the always-present
Manual source. It includes enabled and disabled remote/uploaded sources; it does
not imply that a source was fetched or contributed nodes.

Endpoint and Proxy are displayed separately. Each summary contains only a mode,
safe state words and aggregate counts. It excludes node names, endpoints, ports,
fingerprints, UUIDs, passwords, authentication/obfuscation fields and probe URLs.

`NodeHealth.summary_many(entries)` and `ProxyHealth.summary_many(entries)` are
read-only observation APIs. Each reads its Health JSON at most once per list,
uses the existing Fixed-to-Health lock order, and matches records to fingerprints
from the current committed YAML. A changed/deleted revision is Unknown; an old
fingerprint cannot mark a replacement connection Healthy. An unchanged connection
can retain its matching observation across revisions under the existing identity
contract. No Health schema or observation lifecycle is changed.

| Condition | Overview behavior |
| --- | --- |
| No auxiliary state or subscription settings | Off, using existing defaults |
| Off mode with old observations | Off; old counts are not presented as active checks |
| Enabled, matching current observations | Manual/Automatic and aggregate counts |
| Enabled, missing or stale fingerprints | Unknown for unmatched current nodes |
| Unsafe, corrupt, unreadable or busy auxiliary state | Unavailable; the Fixed list remains usable |
| Corrupt authoritative Fixed registry | Existing fail-closed response |

Summary priority is Unavailable, Unhealthy, Suspect, Unsupported, Healthy, Unknown,
then Off. Off describes the configured mode and suppresses old observations.
Within an enabled summary, problem counts appear before healthy/unknown counts.
Unsupported remains distinct from Unhealthy. Detailed timestamps, latency and
per-node results remain on Edit.

List GET does not call `describe`, prune, commit, settings, check, probe, DNS,
Mihomo, subprocesses, source refresh or schedulers. It neither writes nor creates
the Fixed registry or either Health JSON. Existing lock primitives may create
private lock files; empty lists skip Health locks entirely. The summary does not
modify committed YAML, source caches, revisions, access statistics or tokens.

## Copy and management actions

The existing authenticated readonly public-URL input remains the only list
location containing its bearer URL. Each Copy URL button uses its own input.
On success the button says Copied for two seconds and a status region announces
`URL copied.`; then the original text returns. Clipboard failure focuses and
selects that input and displays `Copy failed — select the URL and copy manually.`
Feedback is per-row; no alert, console logging, analytics or URL-state persistence
is introduced.

Create Fixed Subscription is the list-level primary action. Edit is a standard
action; Enable/Disable, Regenerate Link, Delete, Copy URL and Clear filters use
utility density. Regenerate retains `This will invalidate the old subscription
URL.` and Delete retains `Delete this fixed subscription? Its URL will stop
working permanently.` All mutation forms retain authentication, CSRF, POST and
303 redirects. Existing public URL invalidation and token retirement are unchanged.

## Responsive, accessible and no-JS behavior

The page uses the existing `static/ui.css` tokens and Bootstrap. Toolbar controls
wrap without document overflow. Desktop/tablet tables scroll within their region
where necessary; at <=767px rows become stacked cards in identification, status,
health, time, URL and action order. Long names/prefixes wrap, URL inputs can scroll
their readonly value, and action buttons wrap at content width. Mobile utility
height is 40px and standard/primary height 44px under the shared <=575px tokens.

Search, Status and Sort have explicit labels. Counts use a polite atomic live
region, Copy uses a status region, table headers have column scope, and state
text accompanies every color. Controls retain visible keyboard focus; clearing
filters returns focus to Search. The table's local scrolling region is keyboard
focusable.

Without JavaScript, the server renders every subscription and hides the inactive
enhancement controls. Create/Edit remain ordinary navigable links and existing
Enable/Disable/Regenerate/Delete server forms remain usable. This is the list's
progressive-enhancement contract: the existing editor still uses JavaScript to
restore/serialize node and source fields, and native confirmation dialogs retain
their existing JavaScript dependency. This phase does not add a no-JS editor or
change server mutation semantics.

## Deferred scope

No pagination, bulk mutation, duplicate action, revision history/rollback,
three-dot menus, new dashboard, preference framework, source refresh or Check Now
is added to the list. Detailed source and Health actions remain on Edit. Storage,
generation, policies, probes, authentication, deployment and release lifecycle
retain their existing contracts.

Controlled Phase 1 validation is recorded in the
[Fixed UX acceptance report](FIXED_SUBSCRIPTIONS_UX_REPORT.md). Subsequent real
VPS acceptance, its observation limits and the final candidate gates are recorded
in the [v1.5 final audit](V1_5_FINAL_AUDIT_REPORT.md).
