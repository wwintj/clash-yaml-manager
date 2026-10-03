# Hysteria2 input protocol MVP

**FROZEN: v1.4.0 candidate input contract on main.** No new protocol fields,
grammar, Health architecture or UI workflow are admitted during the freeze.
VERSION and Latest Stable remain **1.3.2 / v1.3.2**;
this feature is not included in that stable release. This is a supported input
subset, not a general validator for all Clash proxy types.

## Sharing URI contract

Both `hysteria2://` and `hy2://` produce `type: hysteria2`:

```text
hysteria2://[auth@]host[:port]/?query#name
hy2://user1:p%40ss@example.com:443/?sni=tls.example#Tokyo-HY2
hysteria2://TEST_ONLY@example.com:443,5000-6000#Singapore-Hopping
```

The last example uses a synthetic credential. Parsing is offline: no DNS,
network request, subprocess or file write. Host accepts DNS names, IPv4 and
bracketed IPv6; the optional path is empty or `/`. Omitted port is 443. Explicit
single ports are decimal integers from 1 through 65535.

Auth is the **entire userinfo**, percent-decoded exactly once with `unquote`.
`user1:p%40ss` becomes `user1:p@ss`; literal `abc+123` stays `abc+123`;
`%252F` becomes `%2F`. Spaces, Unicode and all decoded password characters are
preserved. No complexity rule or trimming is applied. Absent auth omits
`password`; explicitly empty userinfo produces an empty string. The pinned
engine accepts both, but actual authentication still depends on the server.

Manual `COUNTRY|NAME|URI` or `NAME|URI` names take priority. Otherwise the fragment
is decoded once, then existing `Node-XX` fallback applies. Existing country
priority remains Manual → Name → explicitly enabled offline public literal-IP
GeoIP → Unknown. A hostname never triggers DNS for country assistance.

## Query and node fields

Only these query keys are accepted, at most once each:

| URI field | Mihomo field | Contract |
| --- | --- | --- |
| auth | password | Entire decoded userinfo, optional |
| sni | sni | Nonempty offline DNS name or IP |
| insecure | skip-cert-verify | Exactly `0` / `1`; default false |
| obfs | obfs | Exactly `salamander` / `gecko` |
| obfs-password | obfs-password | Nonempty string required with obfs; forbidden alone |
| pinSHA256 | fingerprint | SHA256 hex: 64 hex digits or 32 colon-separated octets; preserve case and colons |

The URI always generates name/type/server/port/udp=true/skip-cert-verify=false,
with query overrides and password only when supplied. It does not invent
bandwidth, ALPN, hop interval or advanced QUIC fields. Literal `+` is preserved
in auth and query values; encode a space as `%20`.

Invalid authority, whitespace/control characters in the raw URI, backslash,
malformed percent encoding, multiple literal `@`, arbitrary path, duplicate,
blank or unknown query parameters fail with fixed non-sensitive errors.

## Port hopping — SUPPORTED

Official comma-separated ports and inclusive ranges map to `ports`, normalized
only to decimal numbers. `443,5000-6000` becomes `port: 443` and
`ports: 443,5000-6000`. The representative port is the first concrete input port,
for existing generator and TCP observation contracts; the engine uses `ports`
for hopping. v1.19.31 accepts ports-only configurations without `port`; Clash
import adds that representative port when it was omitted.
When Clash supplies both `port` and `ports`, its explicit `port` is preserved;
Endpoint observes that port, without claiming to validate the hopping range.

Limits: 512 characters, 28 segments, at most 65535 expanded entries. Empty
segments, reversed ranges, zero, overflow, negatives, slash-separated engine
extensions and nested punctuation are rejected. Segment order is retained.

## External Clash import

Only `type: hysteria2` is recognized; `hy2` is a URI alias, not a YAML type.
Hysteria v1 stays unsupported and follows the existing unknown-type warning.
The explicit allowlist is:

```text
name type server port ports hop-interval password udp obfs obfs-password
sni skip-cert-verify fingerprint alpn up down
```

Name/server are required; a port integer or valid ports expression is required.
Bool and float ports fail. Password must be a string if present, with empty
allowed. Booleans must be actual bool values. UDP false is preserved even though
this Mihomo Hysteria2 adapter internally enables UDP. SNI, obfs and fingerprint
use the URI validation contract.

ALPN is a nonempty list of nonempty strings (maximum 32 strings, 255 characters
each). `up`/`down` accept positive integer Mbps or the pinned bandwidth grammar,
for example `100 Mbps`, `10 MBps`, `200`; malformed/overflow values fail. Values
are preserved, not rewritten. The pinned engine accepts numeric YAML bandwidth
through its weak string decoder. `hop-interval` requires `ports`, and accepts
integer seconds or a decimal string/range, such as `30` or `15-30`, within
5–86400 seconds with ordered endpoints. This safe subset rejects the engine's
silent minimum/default coercions. URI extensions for these fields are rejected.

The existing 10 MiB payload limit, safe YAML loading, depth/item budget, cycle,
object tag, nonfinite number, mapping-key and Unicode protections remain.
Raw and standard/URL-safe Base64 sources reuse the same Batch parser, including
missing padding, mixed protocol order and exact duplicate-name errors.

## Integration and privacy

Batch, Auxiliary, editable Parse Preview, Generate Replace/Merge and exact-byte
YAML Diff all use existing shared paths. Fixed remains Replace only. Manual,
uploaded and remote sources retain existing save/edit/refresh/cache behavior.
Private saved input/source cache and authenticated YAML/Diff retain credentials
as required for subscriptions; ordinary previews, errors, source history,
health state and notifications do not expose password or obfs-password.
Credential-bearing display names and URI remarks are redacted observationally.
`mask_sensitive` returns `hysteria2://***` or `hy2://***`.

Endpoint Health remains a **TCP server/representative-port observation**. It
cannot validate QUIC, Hysteria2, hopping behavior, authentication or forwarding.
Full Proxy Health retains pinned Mihomo config validation and controller delay
probing; no protocol-specific probe is added. Connection identity excludes name
and includes password/server/port/SNI/obfs and all other connection fields.
Policy treats these proxies as ordinary candidates; only fresh confirmed Full
Proxy Unhealthy observations can exclude candidates, with existing fail-open
and minimum-candidate rules.

## Deferred from Hysteria2 MVP

Realm schemes (`hysteria2+realm://`, `hysteria2+realm+http://`), `realm-opts`, ECH,
`ech`/`ech-opts`, custom URI bandwidth/ALPN/hop options, Gecko packet-size tuning,
client certificates, advanced QUIC/common fields and arbitrary subscription-only
extensions are explicitly rejected even where newer engines support them.

Live Hysteria2 server QUIC, authentication, forwarding, hopping and latency remain
unverified. The user supplied separate real Ubuntu VPS main-deployment, service,
healthz and five-unit systemd acceptance; this does not prove Hysteria2 forwarding.
See the [final freeze audit](HYSTERIA2_FINAL_AUDIT_REPORT.md) and the historical
[Phase 1 acceptance report](HYSTERIA2_PROTOCOL_REPORT.md).

## Primary compatibility references

- [Official Hysteria2 sharing URI](https://v2.hysteria.network/docs/developers/URI-Scheme/)
- [Current official Mihomo documentation](https://github.com/MetaCubeX/Meta-Docs/blob/main/docs/config/proxies/hysteria2.en.md)
- [Pinned v1.19.31 outbound options and construction](https://github.com/MetaCubeX/mihomo/blob/v1.19.31/adapter/outbound/hysteria2.go)
- [Pinned certificate SHA256 verifier](https://github.com/MetaCubeX/mihomo/blob/v1.19.31/component/ca/fingerprint.go)
- [Pinned ranges](https://github.com/MetaCubeX/mihomo/blob/v1.19.31/common/utils/ranges.go), [single range](https://github.com/MetaCubeX/mihomo/blob/v1.19.31/common/utils/range.go)
- [Pinned bandwidth grammar](https://github.com/MetaCubeX/mihomo/blob/v1.19.31/common/utils/mbps.go)

Current docs are not the acceptance boundary. Official v1.19.31 source and the
same version's SHA256-verified binary were checked. Fingerprint is certificate
SHA256 pinning, not browser impersonation; the engine also permits a matching
chain certificate, with its own verification rules. Salamander and Gecko are
both accepted by the pinned constructor and real `-t` checks. Realm and ECH
remain deferred for this deliberately smaller input contract.
