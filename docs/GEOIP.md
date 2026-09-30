# GeoIP Country Assist MVP

Current release scope, supported migrations and deferred real acceptance: [Final Audit](FINAL_AUDIT_REPORT.md). New functionality is intended for the next Stable; before publication use explicit `--channel main`.

Before Stable publication, deploy this
feature only with explicit `--channel main`; stable installation/update behavior
is unchanged. This is optional offline country assistance, **Off by default**.

## Priority and privacy

The exact priority is **Manual → Name Detection → GeoIP → Unknown**. Explicit
`COUNTRY|NAME|LINK`, auxiliary countries and Preview country overrides always
win, including deliberately choosing UNKNOWN. Existing name recognition always
wins. Only an otherwise Unknown country can use GeoIP. A successful match uses
the existing display-name builder, country flags and structured group membership.
`core/countries.json` remains the sole authority for 249 countries/regions.

GeoIP only inspects a node's already parsed **literal public IP**. Hostnames are
never resolved. IPv4 and native IPv6 are supported; private, loopback, link-local,
multicast, unspecified, reserved/non-global addresses are skipped using Python
`ipaddress` checks. Scoped IPv6 and IPv4-mapped IPv6 are conservatively skipped.
Python's classifications can change between runtime versions; no additional
address or country-name database is maintained here.

Parsing/generation performs **no DNS or outbound GeoIP requests**, account API,
license-key lookup, automatic download or update. The server IP may describe a
proxy ingress rather than its exit; this is country assistance, not verification
of routing, residence or exit location. Only `country.iso_code` is accepted,
normalized to supported ISO alpha-2. `registered_country` is never substituted.
Missing, malformed or unsupported country codes leave the node Unknown.

## Reader dependency and supplied database

The requirement is **maxminddb>=3.2.0,<4**. Package availability, installed API and
Python **>=3.10** metadata were inspected; Linux CPython3.10 amd64 and arm64
manylinux wheels were downloaded successfully for compatibility verification.
Real Linux/arm64 execution was not performed. The existing installed Gunicorn
also requires Python>=3.10; this work does not provide an older Python runtime.

The [maintained reader](https://pypi.org/project/maxminddb/3.2.0/) supports pure
Python and optional C. This implementation uses the installed public
`maxminddb.MODE_FD` API with verified bounded byte snapshots in a memory reader;
see [the reader documentation](https://maxminddb.readthedocs.io/en/latest/).
Readers are short-lived: one per parsing/aggregation operation, shared by all
manual and external nodes, then closed. There is no global cached reader or
stale inode cache after replacement. GeoIP fallback inspects the existing
parsed node, without adding a second URI parse for its lookup.

Administrators supply their own compatible **country-capable .mmdb**. No
GeoLite2, DB-IP, IP2Location or other third-party geographic dataset is bundled,
committed or downloaded by the application. The reader library's Apache-2.0
license does not grant rights to redistribute a database. Supply a file you are
authorized to use. Country or City database-type metadata is required; only the
geographic country field is consumed. ASN-only databases are not supported.

## System Settings and upload

Authenticated navigation adds a minimal **Settings** page at `/settings`, with
only **GeoIP Database**. It shows Ready / Not installed / Unavailable or Invalid,
bounded safe database type, size, SHA256 prefix and upload time in UTC. Paths,
original upload filename and raw metadata descriptions are not displayed.
All mutations are POST-only, login-protected and use existing Flask-WTF CSRF.
Settings responses use no-store and no-referrer. Healthz remains independent.

Upload/Replace accepts `.mmdb` (case-insensitive), with **32 MiB maximum**.
This conservative limit fits below the existing 50 MiB multipart request limit
and bounds memory snapshot size. Larger City databases are outside this MVP;
use a smaller compatible Country database. Original filenames are checked only
for extension and never used as server paths. Storage is controlled:

```text
state/geoip/active.mmdb       # 0600
state/geoip/                 # 0700
state/settings.json         # 0600; version1, safe metadata only
state/geoip.lock             # private shared lock
```

Upload stages data privately, fsyncs it, opens it with the maintained MMDB reader,
validates safe country-capable metadata, then replaces the active file atomically
and updates metadata under the shared lock. Failed validation never selects the
upload. Database and metadata write failures restore the prior pair, including
failures after replacement; a failed first upload leaves no active database.
Removal uses the same protected transaction and deactivates the database.

Readers copy a verified complete database/metadata pair under a short nonblocking
GeoIP lock, then open their own memory reader after releasing it. A concurrent
reader can finish on the old valid snapshot; the next operation sees the new
one. The Fixed registry lock is never held while opening or looking up GeoIP.
Symlinks, FIFO, devices, directories, unsafe permissions and oversized files are
rejected using the private-state reader. Missing/busy/unsafe/corrupt/unreadable
state fails open for classification; it is not automatically repaired or reset.

Settings metadata is exactly version1 and either `geoip: null` or the safe fields
`database_type`, `size`, `sha256`, `uploaded_at`. No database content is embedded
in JSON. Hash/size mismatches or inconsistent metadata make GeoIP unavailable.
A process crash between the two protected file writes or failure of rollback I/O
can leave an inconsistent pair: classification fails open, and an administrator
must restore a consistent private backup or explicitly replace the database.
No application repair guesses or deletes a corrupt database automatically.
Ready means reader/header, metadata and checksum validation, not a scan of every
possible record. An individual lookup error returns Unknown and does not fail
node parsing. No database content or underlying reader exception is logged.

## Generate, Preview and Fixed v6

Country Detection has **Off / Literal public IP only** on Generate and Fixed
create/edit. Generate's mode is ephemeral: it is not saved in drafts, cookies,
server `/t` state or a new bearer format. Preview uses the same mode and can show
Source **Manual / Name Detection / GeoIP / Unknown**; a valid GeoIP match is Ready.
Preview does not add the node server IP. Missing database warnings are safe and
nonblocking; the mode stays selectable and generation still works.

Fixed registry **v6** stores this authoritative configuration:

```json
{"country_detection":{"geoip":"off"}}
```

Only `off` and `literal-ip` are supported. Unknown keys/modes and duplicate form
values are rejected. Reading v1–v5 supplies Off **in memory only**: no rewrite,
regeneration, revision/Updated change, token/prefix rotation or URL change.
Earlier policy, health and source migrations remain. Public access statistics
retain the legacy disk schema; a legitimate management mutation writes v6.
Corrupt authoritative v6 config remains fail-closed under existing Fixed rules.

Save/edit, source enable/disable/delete, Refresh/Refresh All, Automatic Source
Refresh and Health-aware reconciliation preserve the saved mode. Raw/Base64
VMess/VLESS sources share the manual parser's fallback; Clash sources use the
same literal-IP lookup only when name detection is Unknown. Existing provider
refresh networking is unchanged; GeoIP adds only local reads.

Uploading, replacing or removing the global database **does not regenerate any
Fixed subscription** or change current YAML, tokens, source caches/schedules or
health state. The next normal regeneration uses the currently available global
database; already published YAML remains as committed until then. A database
is never copied into individual Fixed revisions. Health-aware reconciliation,
when enabled for automatic policies, can use the next snapshot during its
existing legitimate cached regeneration; it does not download GeoIP data.

The final country naturally determines Policy Country membership. GeoIP does
not enter the Policy core or decide health status. Country/display-name changes
preserve the existing name-free connection fingerprint. Unknown new fingerprints
still have Unknown Health. Fresh Full Proxy Unhealthy filtering and per-group
minimum/fail-open rules remain independent.

## Deployment, backup and acceptance

Install/update already installs Python requirements; there is no MMDB download,
new unit or background GeoIP process. Existing code deployment excludes `state`
from replacement. Update's private-state backup copies the entire state, including
`geoip` and `settings.json`; controlled tests execute the real backup helper in
temporary directories. Uninstall's existing default Keep Data path includes them
in the private backup. Explicitly declining data retention still deletes user
state under the pre-existing uninstall contract. Recovery restores both database
and metadata with private ownership/permissions, not only one file.

Controlled tests use injected synthetic records and genuine-reader invalid-data
checks. A separate genuine maxminddb3.2.0 smoke check used the upstream synthetic
Country test fixture **outside the repository**, including IPv4/IPv6, parser
integration, upload/remove and forbidden DNS/network. No production database
accuracy or real VPS acceptance is claimed. Browser tests use an isolated Flask
copy and test-only synthetic readers. See [GEOIP_REPORT.md](GEOIP_REPORT.md).

**REAL GEOIP VPS ACCEPTANCE: NOT RUN.** Automatic Health real due Endpoint and
Proxy remain **PENDING**; real Policy and Health-aware Policy remain **NOT RUN**.
Those exercises were deferred independently and are not closed by this phase.
On a dedicated development VPS, deploy explicit main, supply an authorized real
Country MMDB privately, verify Settings Ready, test public IPv4/IPv6 versus known
Manual/Name assignments and hostnames/private addresses, then verify saved Fixed
mode, next-refresh groups, unchanged URL and database removal fail-open. Record
sanitized mode/code/count results, commit and healthz; never publish node IPs,
credentials, provider URLs, subscription bearers or the supplied database.

DNS GeoIP, automatic datasets, MaxMind account management, ASN/ISP/coordinates,
country guessing from latency, routing changes, bulk regeneration, notifications,
HTTPS/Nginx and broad Settings migration remain outside this MVP.
