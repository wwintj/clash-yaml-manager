# Shadowsocks Protocol MVP

Development on `main`; not yet included in Stable v1.2.1. VERSION stays 1.2.1.
Supported **new input protocols** are VMess / VLESS / Trojan / Shadowsocks.
This is not support for every Clash proxy type. Generate Merge can separately
retain arbitrary existing proxy mappings, including Hysteria2 and WireGuard.

## URI contract

Lowercase `ss://` accepts these three forms:

```text
ss://BASE64(method:password@server:port)#name
ss://BASE64(method:password)@server:port[/]#name
ss://PERCENT_ENCODED_METHOD:PERCENT_ENCODED_PASSWORD@server:port[/]#name
```

The requested whole-authority Base64 form is the legacy format. The latter two
forms use SIP002 userinfo. The official [SIP002 specification](https://shadowsocks.org/doc/sip002.html)
distinguishes Base64 userinfo from percent-encoded plain userinfo and requires the
plain form for AEAD-2022. This importer also accepts encoded forms without cipher
special cases; it does not claim full SIP002 plugin support or engine validation.

Base64 accepts standard and URL-safe alphabets, with valid explicit padding or
missing padding. Encoded payloads are decoded as UTF-8; malformed alphabet,
padding, UTF-8 and percent escapes fail without a guessed fallback. Percent
encoding around Base64 is decoded once, then Base64 is decoded once. A password
inside Base64 is already plain text and receives **no further percent decoding**.
Plain userinfo percent-decodes method/password exactly once: `%2540` becomes
literal `%40`. Encode reserved characters and whitespace in plain userinfo.

Passwords preserve surrounding spaces, Unicode, `@`, `:`, `/`, plus signs and
all-space values. Both password and cipher must be nonempty strings. There is no
cipher whitelist, normalization, trimming, conversion or password complexity rule.
A nonempty cipher/key can still be rejected by the runtime Mihomo engine.

Hostname, IPv4 and bracketed IPv6 are supported with explicit port 1–65535.
Validation is offline; no DNS resolution occurs. Raw whitespace/control characters,
backslashes, ambiguous raw userinfo `@`, unbracketed/scoped IPv6, bracket suffix
junk, missing fields and unexpected URI paths fail. The endpoint uses
`urllib.parse.urlsplit`; encoded credentials use bounded matching, selecting the
last authority `@` for legacy input. Password delimiters remain data. Fragment
names decode once; empty names use `Node-01` etc.

**All query parameters are rejected**, including an empty query. Plugin, obfs,
simple-obfs, v2ray-plugin and SIP003 queries produce an explicit fixed plugin error.
This includes the requested `ss://BASE64(...)/?plugin=...` form. Plugin execution
is outside this MVP; nothing is silently ignored or copied from URI queries.

Generated mapping: `name`, `type: ss`, `server`, integer `port`, `cipher`, `password`,
`udp: true` (the existing URI-node convention). No UUID, TLS or certificate fields
are invented. These core fields match the pinned
[Mihomo v1.19.31 Shadowsocks adapter](https://raw.githubusercontent.com/MetaCubeX/mihomo/v1.19.31/adapter/outbound/shadowsocks.go).
The mapping was checked against source and controlled config tests, not a live proxy.

Synthetic plain-userinfo examples:

```text
US|Example|ss://aes-256-gcm:TEST_ONLY%40%3A%2F@example.com:443
ss://chacha20-ietf-poly1305:TEST_ONLY@[2001:db8::1]:443#%E6%9D%B1%E4%BA%AC
```

## Shared generation and Fixed workflows

Batch accepts URI alone, `NAME|URI` and `COUNTRY|NAME|URI`; all four protocols can
mix while preserving input order. Auxiliary links use automatic dispatch; no
protocol selector was added. Parse name/country edits use the existing node keys.
Duplicate final display names still fail.

Replace keeps its existing contract. Generate-only Merge preserves source proxy
objects/order, quotes/comments/anchors and ordinary memberships, then appends
submitted nodes. Existing Trojan/Hysteria2/WireGuard/unknown mappings are retained.
A same-name conflict fails: **Node name already exists in source YAML.** No overwrite,
renaming or deduplication occurs. Fixed still uses Replace.

Full YAML Diff and Generate share parsing, transformation and serialization.
The public unified diff reconstructs the exact subsequently generated/downloaded
bytes, including mixed protocols, Auxiliary nodes, selected mode and Policy Options.
Policy uses SS as a normal candidate for Select, URL-Test, Fallback and Load-Balance.
Country priority remains Manual > Name Detection > optional offline public-literal-IP
GeoIP > Unknown. Hostnames never trigger DNS in country detection.

Fixed Manual Batch/Aux, save/edit and overrides inherit the parser. Registry v6,
tokens and URLs are unchanged. External automatic refresh reuses the current
scheduler/lock/revision/cache transaction and last-good behavior without modifications.

## External imports

Raw and Auto accept SS URI lists with blank lines and whole-line comments. Batch
country/name prefixes are not permitted in external Raw lists. External Base64
standard/URL-safe decoding produces the same list, including nested SS Base64
credentials; existing format detection and encoded/decoded 10 MiB limits remain.

Clash/Mihomo YAML `type: ss` requires nonblank string name/server, port 1–65535,
and nonempty string cipher/password; UUID is not required. YAML strings are
preserved without URI decoding. Optional `udp` must be boolean. Unknown extra
**plain fields are retained**, including nested plain mappings/lists. Plugin/obfs
fields (including empty/null values, normalized plugin/obfs option keys,
simple-obfs, v2ray-plugin and SIP003) are rejected with fixed source failure.
No external commands are executed. Unsupported protocol types are skipped with
an aggregate count warning; zero supported nodes fails.

The safe YAML loader, object-tag rejection, depth 32, 100000-item budget, cycle,
non-string-key, finite-number and Unicode defenses are unchanged. Importing SS
does not import base YAML settings. See [External Sources](EXTERNAL_SOURCES.md).

## Credential and Health boundaries

Ordinary Parse hides SS URIs and decoded password text embedded in remarks,
including trimmed remark forms of space-padded credentials. Errors/logs use fixed
messages. Existing instance-local YAML diagnostic suppression prevents warnings
from echoing invalid numeric-looking passwords; global filters are unchanged.
Health observational names/state and notifications contain no password/config.

Editable input/local drafts, generated YAML, Fixed private configs/caches,
authenticated Full YAML Diff and private probe YAML contain administrator-owned
credentials by design. Display redaction does not mutate the actual node password.

Health changes only admit SS and redact passwords through the shared extractor.
Endpoint receives server/port. Full Proxy reuses the existing runner; controlled
checks verify opaque probe names, 0700 work directory, 0600 config, loopback
controller and silent logs. No schema, probe algorithm, scheduler or Mihomo binary
changes were made. No network/subprocess path was added to parser/importer.

No real SS connection or VPS acceptance was performed. See the
[acceptance report](SHADOWSOCKS_PROTOCOL_REPORT.md) for exact validation evidence.
