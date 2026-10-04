# Fixed Subscriptions: External Sources

Historical migration and acceptance evidence is recorded in the
[v1.3 Final Audit](V1_3_FINAL_AUDIT_REPORT.md). Earlier embedded acceptance records
below retain their historical versions; current published availability follows
[Latest Stable release notes](https://github.com/wwintj/clash-yaml-manager/releases/latest).

Ordinary installs use the default Stable channel. Base YAML remains Default / Custom and is
separate from the ordered Node Sources used to replace its proxies.

## Using sources

The single Create/Edit page retains Batch Nodes, Auxiliary Nodes, Parse Preview,
overrides and existing Policy Options. Manual Nodes is always first and cannot be
deleted or disabled; it may be empty. Add Remote URL and Add Uploaded Source append
sources. Multiple sources of each kind are supported (up to 63 external sources).
Names must be nonblank, 1–128 characters, and distinct within the subscription.

Formats are Auto, Clash / Mihomo YAML, Raw URI List and Base64 URI List. VMess,
VLESS, Trojan, Shadowsocks and Hysteria2 are imported. Hysteria2 / HY2 is included
in Stable v1.4.0 with its input contract frozen. It validates an
explicit pinned subset, including optional string auth; see [Hysteria2 Protocol](HYSTERIA2_PROTOCOL.md)
and the historical [Final Freeze Audit](HYSTERIA2_FINAL_AUDIT_REPORT.md). Raw lists accept blank lines and whole-line `#` comments;
URI fragments remain node names. Base64 accepts standard/URL-safe alphabets and
whitespace. Auto detects a YAML mapping with a proxies list, then URI lists, then
Base64. YAML content types and filename extensions do not decide the format.

Clash imports require nonblank name/type/server, ports 1–65535 (not booleans),
and UUID for VMess/VLESS or a nonempty string password for Trojan/SS; SS also requires a nonempty
string cipher. Passwords and SS ciphers are never stripped or normalized. Existing VMess/VLESS plain options (TLS, WebSocket, Reality,
ALPN, UDP and fingerprints) are retained unchanged. Trojan imports validate and
retain the explicit TCP/WS mapping subset documented in [Trojan Protocol](TROJAN_PROTOCOL.md);
unknown Trojan fields/transports fail, without weakening the general YAML defenses.
Shadowsocks imports retain unknown plain extra fields and reject plugin/obfs
fields, including empty values. There is no cipher whitelist or UUID requirement
for SS; optional UDP must be boolean. URI queries are rejected, with explicit
plugin errors for Manual inputs and fixed source failures for External inputs.
See [Shadowsocks Protocol](SHADOWSOCKS_PROTOCOL.md) for SIP002 userinfo and legacy
whole-authority Base64, percent-decoding and password-preservation rules. SS is part of the v1.3.0 release scope.
Unsupported protocols are skipped with a count warning; zero supported nodes is an error. The
safe YAML loader rejects object construction; structural limits reject cycles,
deep nesting, non-string keys and oversized alias expansion. Payloads are limited
to 10 MiB, including decoded Base64. Node names use the existing country detection,
flags and Unknown group. The aggregate preserves source and internal node order;
duplicate final display names and an empty aggregate stop the entire operation.

Save fetches all enabled remote sources. Refresh fetches the selected enabled
remote; Refresh All fetches enabled remotes. Other sources use their saved content.
Refresh buttons operate on **saved settings**; save form edits first. Public fixed
URLs never fetch or parse sources. Remote sources now support a separate systemd
timer with Off by default; see [Automatic Refresh](AUTO_REFRESH.md) for v3 migration,
scheduling, history and operations. The source worker does not perform health probes. Independent Health and Policy
controls are documented in their own modules; no refresh thread or duplicate action is added.

Status shows Never fetched, Ready, Cached, Error or Disabled, imported node count,
last successful refresh in UTC, and sanitized warnings. Refresh buttons show
Refreshing and reject duplicate clicks. Uploaded sources show that a file is saved;
leave the upload empty to keep it. Invalid replacement uploads preserve the old
payload and output. Filenames are not stored or used as paths.

## Last-good cache and configuration changes

Fetch and parse must both succeed before a remote payload becomes last-good. HTTP
200 with malformed/unsupported content is a failure. For an unchanged URL and
format, failed fetch/parse may use the last successfully parsed payload. A new
manual edit can therefore be combined with cached external nodes. The source shows
Cached and keeps its successful timestamp while recording the new attempt/error.

A new enabled source without usable data fails the whole Save/Create. No partial
source record is committed. A changed remote URL or format must successfully fetch
and parse before that configuration is committed; the previous URL's cache cannot
validate new settings. Disabled sources make no network request and contribute no
nodes, while retaining saved payloads. To change a disabled remote's URL/format,
enable it and save so the new configuration can be validated. A newly added disabled
remote can remain Never fetched until enabled. Upload replacements are validated
even when disabled. Re-enabling a remote attempts an update with the same fallback
rules. Delete requires confirmation and regenerates the whole subscription; failure
preserves the source and output. Source operations preserve the fixed public token.

## Fetch security and limits

`core/source_fetch.py` performs direct HTTP/HTTPS requests, ignoring all proxy
environment variables. URL userinfo, control characters, non-HTTP schemes, invalid
ports and IPv6 zone identifiers are rejected. Query tokens are allowed. Non-ASCII
path/query characters must be URL-encoded. The minimal headers contain Host,
User-Agent, Accept, Accept-Encoding: identity and Connection: close; no admin cookie,
authorization or Referer is forwarded.

Every DNS answer must be globally routable according to `ipaddress`, and cannot be
loopback, private, link-local, multicast, unspecified or reserved. Documentation
networks and metadata endpoints are blocked as fetch destinations. IPv6 transition
addresses are also rejected. A mixed public/private answer fails closed. The chosen
numeric sockaddr is passed directly to `socket.connect`: HTTP never resolves the
hostname again. Host and HTTPS SNI retain the original hostname. TLS uses the system
CA trust store with hostname verification enabled; there is no insecure/private-IP
override.

Redirects 301/302/303/307/308 are handled manually, with at most three hops. Each new
URL, including a relative Location, repeats URL, DNS and IP validation and pinning.
Only final HTTP 200 is accepted. Content-Length over 10 MiB aborts before reading;
streamed responses are also bounded. Compressed HTTP responses are rejected (the
request asks for identity encoding), and truncated declared bodies fail.

Connect/TLS operations have a maximum five-second timeout within a 15-second total
budget per fetch including redirects and DNS. The system resolver runs in a
synchronous short-lived Python child with a subprocess timeout, so stalled DNS is
terminated and reaped; this is not a background refresh worker. Header/body reads
reset the socket timeout to the **remaining total budget** on every receive, which
also bounds slow trickle responses. Multiple sources are fetched sequentially;
the total Save time can exceed 15 seconds. Service/reverse-proxy request deadlines
may terminate a large multi-source save; its old committed revision stays selected.

Transport and parser exception details are never displayed or stored. Errors use
allowlisted codes/messages (or numeric HTTP status), with no URL, query token,
response body, node URI or credential. Full URLs are editable only in the
authenticated form, never shown on the list and never placed in browser storage.
Forms/public responses retain no-store and no-referrer. Existing fixed bearer
access-log redaction, login and POST+CSRF controls remain in place.

## Registry and private revisions

Each source has a server-generated UUID4 hex id, type, name, enabled, format,
node_count, last_attempt_at, last_success_at, last_error, using_cache and warnings.
Remote sources additionally have url. The registry keeps the existing manual
batch/auxiliary/override fields for compatibility; its first source describes that
manual input. Source list order is persistent. Array indices are used only to
associate multipart uploads with this submitted form, never as stored identifiers.

```text
state/fixed_subscriptions.json                           # version 6 (v1–v5 readable in memory)
state/fixed_subscriptions.lock
state/fixed_subscriptions/<subscription-id>/<revision>/
  base.yaml                                             # default OR custom snapshot
  current.yaml
  sources/<source-id>/payload.bin                        # last-good remote / saved upload
```

All directories are 0700 and files 0600, outside uploads/outputs retention. Each new
revision is self-contained, including disabled source payloads. Payload path ids,
directory permissions and regular files are validated; symlinks are rejected.
Existing lifecycle backups/upgrades preserve the whole state tree and its files.

Version 1 is strictly validated and normalized in memory into one Manual source.
Its existing subscription UUID is reused as the scoped manual source id so reads
are deterministic without writing. Manual batch, auxiliary rows, overrides,
prefix, token, current revision and public bytes are unchanged. Public access-stat
writes preserve the original v1–v5 schema. A successful management mutation atomically
writes version 6 under the process-shared lock, retaining authoritative policy settings (see [POLICY_ENGINE.md](POLICY_ENGINE.md)). The automatic worker also writes
v6 when a due refresh requires mutation, while all-Off scans leave v1–v5 untouched.
See [Automatic Refresh](AUTO_REFRESH.md) for remote scheduling fields. A failed migration never resets
state; corruption fails closed. No deletion of the old registry is required.

## Atomicity and concurrency

1. Under the registry lock, snapshot configuration, current identity, custom base
   and all last-good payload bytes.
2. Release the lock. Fetch/parse/aggregate and generate a candidate in a private
   `state/.fixed-candidate-*` staging directory outside subscription homes.
3. Reacquire the lock and compare the saved revision/configuration/status/token
   with the snapshot. Ignore only Last Access, which may legitimately advance.
4. On conflict return “Subscription changed while refreshing. Please retry.”
   Otherwise move the complete candidate into its home, sync directory entries,
   and commit config/cache/output together through one atomic registry pointer.

Other subscriptions and public reads remain available during slow network I/O.
Two concurrent refreshes cannot overwrite one another, and a stale refresh cannot
undo editing, disabling, link regeneration or deletion. Last Access updates survive
the successful commit. Cleanup cannot remove another request's staged candidate.
Superseded committed revisions are collected only after success. Failed candidates
are removed; a process crash can leave a private `.fixed-candidate-*` directory,
which is never public and can be removed while the service is stopped. There is no
background cleanup of potentially active candidates.

Registry replacement failure restores the old pointer, including a reported failure
after replacement. If rollback itself cannot write, complete potentially referenced
candidate files are retained for recovery. Persistent filesystem failure still
requires restoring a consistent backup. The old current/cache remain selected on
ordinary fetch, parse, generation, file-write or registry-commit failure.

## Verification

`pytest` includes offline parsing, controlled-loopback HTTP with DNS/socket doubles,
pinning and proxy isolation, redirects, TLS verification errors, DNS/header/body
deadlines, size limits, v1 migration, cached failure/recovery, seven-node ordered
aggregation/country groups, source actions, replacement/configuration failures,
metadata failure before/after replacement, concurrent public reads and stale-save
conflicts, private paths, auth/CSRF and upgrade/backup payload preservation.

`python tests/run_preview_browser.py` also runs existing preview/Fixed CRUD and the
external-source browser flow: create remote, refresh, failure/cache, changed manual,
recovery at the same URL, uploaded YAML, invalid replacement, disable/enable/delete,
1440/390 layouts and browser-storage isolation. Its source fixture lives only in
the test harness; production has no private-network bypass. These checks do not
claim operation on a real VPS or real provider subscription.

## Acceptance record — 2026-09-29

Baseline main: `64d9317d08954a678aacabd71ac10e6f536dc7af`, clean and equal to
origin/main; **446 passed**. Final full suite on supported Python 3.12.14:
**594 passed, 0 failed** (148 additional cases). The complete browser suite also
passed: seven preview viewports, Fixed CRUD, and the external-source lifecycle.
Repository runtime data and the developer machine's system services/accounts
were not changed.

A separate run on Python 3.9.6 recorded 593 passes and one Gunicorn service-flag
failure because that runtime cannot satisfy the current Gunicorn requirement.
That unsupported-environment result does not replace the successful Python 3.12
and browser acceptance gates. See [the final report](FINAL_REPORT_EXTERNAL_SOURCES.md).

| Gate | Result |
| --- | --- |
| v1 → v2 migration; existing fixed URL/prefix/token/output; manual edits | PASS |
| Manual / Remote URL / Uploaded; custom base persistence | PASS |
| Raw / Base64 / Clash; VMess / VLESS; unsupported proxy skip | PASS |
| Seven-node ordered aggregation, country groups, duplicate detection | PASS |
| Remote fetch, SSRF, DNS pinning, redirect validation | PASS |
| TLS verification, proxy environment isolation | PASS |
| 10 MiB payload limit; 5-second connect and 15-second total budget | PASS |
| Last-good fallback, first-fetch failure, invalid-200 preservation | PASS |
| Failed URL/format changes and failed uploaded replacements preserve old state | PASS |
| Refresh one/all; enable/disable/delete; source payload snapshots | PASS |
| Network outside lock; optimistic conflicts across threads and processes | PASS |
| Atomic revision/cache selection, including failed registry replacement | PASS |
| Failed saves preserve public YAML; stable fixed URL through source operations | PASS |
| Fixed /s, V2 /s, legacy /s, temporary /t, drafts, auth, CSRF | PASS |
| Upgrade/live state/backup/uninstall-backup preserve source payloads | PASS |
| Existing browser previews at 7 viewports; Fixed CRUD; external source flow | PASS |
| External form at 1440 / 390 px; no credential browser storage | PASS |
| Python / Node syntax; pip check; bash -n | PASS |
| ShellCheck 0.9.0 / 0.11.0; build_bootstraps --check; git diff --check | PASS |
| Default YAML 10,410-rule round trip | PASS |

`defaults/default.yaml` is byte-for-byte unchanged, SHA256:
`a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b`.
VERSION remains `1.1.1`, Latest Stable remains `v1.1.1`; this work creates no tag or
Release. The existing stable tag object is
`82b0b88ef2479cb3969f3df1e76ceb0718b4b4c0`, resolving to release commit
`6ff864df84be74755d907032bd9be0f2cd8821de`.

Test VPS update (run on the intended test VPS):

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh \
| sudo bash -s -- --channel main
```

The installed Web identity should be `v1.1.1-dev+<resolved-main-sha>` with `DEV`.
Live provider/VPS acceptance remains a deployment check; the automated network
and browser tests above use controlled fixtures only.
