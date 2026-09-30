# Trojan Protocol MVP

Development on `main`, not included in Stable v1.2.1. VERSION remains 1.2.1.
New URI input protocols are VMess / VLESS / Trojan. Merge can separately retain
arbitrary existing source proxy mappings; that does not enable new SS, Hysteria,
TUIC, WireGuard, SOCKS, HTTP proxy or SSR input.

## URI contract

```text
trojan://PASSWORD@HOST:PORT?QUERY#NAME
```

Use lowercase `trojan://`, matching the existing Batch/Raw scheme convention.
Host can be a DNS hostname, IPv4 or bracketed IPv6. An explicit decimal port
1–65535 is required. Password is a nonempty string; percent encode reserved
characters (`@`, `:`, `/`, `#`, `?`, `%`) and whitespace. It is UTF-8 percent
decoded exactly once: `p%40ss` becomes `p@ss`, `p%3Ass` becomes `p:ss`, and
`p%2540ss` becomes `p%40ss`. Surrounding spaces, Unicode and even an all-space
password are preserved. No trimming or complexity policy applies to passwords.

URI parsing uses `urllib.parse.urlsplit` and its username/hostname/port accessors,
not credential splitting. Existing input-line trimming is retained; within the URI,
raw whitespace/control characters, backslashes, malformed
percent escapes, missing credentials/host/port, ambiguous multiple `@`, raw
credential colons, unbracketed IPv6, bracket suffix junk and scoped IPv6 are rejected.
There is no URI path; use the WS `path` query. DNS names are validated offline,
without lookup. Fragment is decoded once; empty names fall back to `Node-01` etc.

| Query | Contract / output |
| --- | --- |
| `type` | Absent or `tcp` uses plain Trojan TCP; `ws` produces `network: ws`. Other or empty values fail. |
| `security` | Absent or `tls` only. `none` and `reality` fail. TLS is inherent to Trojan. |
| `sni` | Nonempty hostname/IP → `sni`. |
| `peer` | Alias of `sni`; if both exist they must match exactly, with `sni` selected. Conflicts fail. |
| `path` | WS only; decoded once, must start with `/` and contain no controls; defaults to `/`. |
| `host` | WS only; nonempty hostname/IP → `ws-opts.headers.Host`; no custom header injection. |

All repeated query keys are rejected, including repeated identical values. Unknown
keys are rejected rather than passed through or silently ignored. This narrower
Trojan contract leaves existing VMess/VLESS query behavior unchanged. The historical
unsupported-input error text remains byte-compatible; the shared UI/manual advertise
the actual expanded protocol set. No gRPC,
HTTP/H2/XHTTP, Reality, plugin, command, file, environment-proxy or external-config
query is accepted. ALPN/fingerprint URI parameters are outside this MVP.

The generated core mapping is `name`, `type: trojan`, `server`, integer `port`,
`password`, `udp: true`, `skip-cert-verify: false`; optional fields are `sni`,
`network: ws`, `ws-opts.path` and `ws-opts.headers.Host`. It has no `uuid`,
`tls: false` or VLESS `servername` field. Mihomo v1.19.31 defaults SNI to the
server and applies TLS to both TCP and WS. These semantics were checked against
its pinned [Trojan adapter](https://raw.githubusercontent.com/MetaCubeX/mihomo/v1.19.31/adapter/outbound/trojan.go)
and [Trojan transport](https://raw.githubusercontent.com/MetaCubeX/mihomo/v1.19.31/transport/trojan/trojan.go).

Synthetic examples (replace credentials yourself):

```text
US|TCP-Example|trojan://TEST_ONLY@example.com:443?sni=tls.example
Tokyo-WS|trojan://TEST_ONLY%40encoded@example.com:443?type=ws&sni=tls.example&host=cdn.example&path=%2Fws
trojan://TEST_ONLY@[2001:db8::1]:443#%E6%9D%B1%E4%BA%AC
```

## Shared workflow

Batch accepts `COUNTRY|NAME|URI`, `NAME|URI` and URI alone, including mixed
VMess/Trojan/VLESS/Trojan order. Auxiliary links detect protocol automatically.
Parse edits remain keyed to the complete input. Country priority stays Manual >
Name Detection > optional literal-public-IP GeoIP > Unknown; no hostname DNS.
Duplicate final display names remain errors.

Replace retains its current removal/reference contract. Merge appends new Trojan
nodes after unchanged source proxies; collision remains **Node name already exists
in source YAML.** All five policies use normal country/name/membership behavior.
Full YAML Diff shares the exact Generate transformer and serialization; no separate
Trojan conversion exists. See [Merge](MERGE_MODE.md) and [Diff](YAML_DIFF_PREVIEW.md).

Fixed Manual and External Source inputs reuse these parsers. Fixed schema v6,
URL/token model, source order and cache transactions are unchanged. Automatic
refresh inherits imports; scheduling, backoff, history, locks and timers are unchanged.

## External formats

Raw/Auto accepts Trojan with blank lines and whole-line `#` comments, but never
Batch country/name prefixes. Standard/URL-safe Base64 decodes the same list with
existing padding/whitespace rules and no extra fallback. Both encoded and decoded
payloads retain the 10 MiB limit.

Clash YAML requires nonblank string name/server, `type: trojan`, port 1–65535 and
nonempty string password (not UUID). Password is already a YAML string and is
preserved without URI decoding. Required fields and these allowed options are
retained: boolean `udp`/`skip-cert-verify`, `sni`, `network: tcp|ws`, `ws-opts`
with only `path` and optional `headers: {Host: hostname/IP}`, nonempty string
`client-fingerprint`, nonempty list of nonblank strings `alpn`. These options are
checked for structure; this is not full Mihomo engine validation. Unknown Trojan
mapping fields and unsupported transports fail with a fixed SourceError. Existing
VMess/VLESS mapping import behavior is unchanged. Other protocol types are still
skipped with a count warning; zero supported nodes fails. Safe YAML construction,
32-depth/100000-item/cycle/non-string-key protection is unchanged.

## Credential and Health boundaries

Ordinary Parse Preview hides Trojan URIs and decoded password text embedded in
remarks/edits, including the trimmed remark form of a space-padded password.
Errors/logs use fixed text. External YAML float diagnostics are suppressed on the
parser instance so malformed numeric-looking passwords cannot appear in warnings;
other YAML instances and global warning filters are unchanged. Endpoint/Full Proxy observational names hide passwords
and URIs; saved observation state contains hashes/statuses rather than configs.
Notifications remain transient subscription/count events without node configs.

Raw editable inputs and existing local drafts contain the original URI. Generated
YAML, Fixed private config/cache, private 0600 Mihomo probe config and authenticated
Full YAML Diff necessarily contain the administrator's actual credentials. A
preview redaction marker is display text, not an automatic change to a node's
real name unless the administrator explicitly saves it as a name edit.

By explicit user clarification, Health changes are limited to admitting Trojan in
the shared extractor and redacting its password in observational names. Endpoint
still uses server/port; Full Proxy passes the complete in-memory config to the
existing Mihomo runner under opaque probe names. No protocol-specific probe,
state schema, algorithm, scheduler or binary version changes were made. Validation
uses injected probes/runners; no real Trojan connection or VPS test was performed.

Resource limits, Diff/multipart/node budgets and default.yaml are unchanged.
