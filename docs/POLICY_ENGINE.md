# Policy Engine MVP

Policy Engine 已隨 v1.2.0 提供；正式可用版本以 [README Latest Stable](../README.md) 為準。
[Final Audit](FINAL_AUDIT_REPORT.md) 保留早期推出、migration 與 deferred 驗收的歷史記錄。

Policy Engine controls the type of generated Mihomo proxy groups in both
Generate YAML and Fixed Subscriptions. It is opt-in: **Preserve / Preserve**
is the default, and retains the existing YAML generator's behavior.
只有明確授權的開發部署使用 `--channel main`。

v1.6.0 的 [Default profile](DEFAULT_YAML_COUNTRY_GROUPS.md) 在 Policy／Health
處理後，將主 selector 排為真實節點、首次出現的國家組、`🚀 手动切换`、DIRECT。
它保留 managed group 的候選成員與 Policy metadata，不攤平 automatic groups；
Custom 與特殊組排序維持既有契約。

## Managed scope and candidates

Country Groups are the exact groups associated with actual nodes in this
**generation's structured parser assignments**. A country-looking custom name
alone does not make a group managed. The parser-generated other-nodes group
is included when it has actual Unknown-country membership. Special Groups are only those selected
through the existing special_groups controls; they receive all generated nodes.
General groups (`🚀 节点选择`, `🚀 手动切换`, `🐟 漏网之鱼`) are outside this
Policy Engine even if a programmatic caller includes them in special_groups.
Manual switching remains available. If a programmatic caller selects a country
group as Special, its explicit Special classification takes precedence.
Group names and rule targets do not change through the Policy Engine.

For URL-Test, Fallback and Load-Balance, the candidate list contains only the
actual generated proxy nodes assigned to that group, in generator order.
Country groups never gain members from a second substring classification.
Selected Special groups contain the complete generated list, in the same order.
**DIRECT, REJECT, nested groups, arbitrary group references and old nodes are
excluded** from automatic candidates. Provider/use/include-all and filtering
fields that could expand or alter those candidates are removed on explicit
automatic conversion. Unmanaged custom groups retain their existing behavior.

A single candidate is supported by pinned Mihomo's parser, although it has
little selection value. A selected automatic target with zero candidates fails
safely. Country groups without actual membership are not managed. There is no
DIRECT insertion or automatic downgrade to Select on the explicit policy path.

## Types and options

| Type | Behavior | Emitted options |
| --- | --- | --- |
| Preserve | Keep the base YAML's group type and behavior fields, beyond existing node replacement/population | No new options |
| Select | Manual selection, retaining the normal generated group's ordinary references (including intentional DIRECT/nested/manual refs) | No automatic options |
| URL-Test | Client Mihomo selects a lower-latency candidate with tolerance | url, interval, lazy, tolerance |
| Fallback | Client Mihomo uses ordered fallback candidates | url, interval, lazy |
| Load-Balance | Client Mihomo distributes traffic | url, interval, lazy, strategy=round-robin |

Automatic defaults are `url: https://www.gstatic.com/generate_204`,
`interval: 300` **seconds**, `lazy: true`; URL-Test also has `tolerance: 50`
**milliseconds**. Load-Balance supports only `round-robin` in this MVP.
Interval must be an exact integer **30–86400**, tolerance an exact integer
**0–10000**. These conservative product bounds are narrower than the engine's
integer storage. Booleans are not accepted as integers. Lazy is an exact bool.
NaN, infinity, floats, unknown keys/types/options and options for other types
are refused. Form conversion accepts decimal integers and literal true/false
before the same core validation.

Client test URLs may use **HTTP or HTTPS**, including localhost/private targets
reachable from the client. They are never resolved or fetched by this server.
Empty URLs, userinfo, control characters (including encoded ASCII controls),
whitespace, backslashes, unsupported schemes, invalid ports and URLs over 2048
characters are refused. This is intentionally separate from server Proxy Health's
public-only HTTPS SSRF policy. A syntactically accepted URL may still be
unreachable or unsuitable from an actual client.

Explicit conversions remove known automatic fields: url, interval, lazy,
tolerance, strategy, timeout, max-failed-times and expected-status. Automatic
conversion also removes use, include-all, include-all-proxies,
include-all-providers, filter, exclude-filter, exclude-type and empty-fallback.
Display/custom metadata such as icon, hidden, disable-udp and x-custom is retained.
Preserve does not clean or reinterpret existing group behavior. Switching back
to Preserve regenerates from the authoritative Default/Custom **base YAML**,
not the previously generated revision, so its original behavior returns.

## Pinned Mihomo evidence

The inspected source is **MetaCubeX/mihomo v1.19.31**, commit
`ab405bad5beeeac8b003bb01f60f134f6df54471`; the managed pin is unchanged.

- [parser.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.31/adapter/outboundgroup/parser.go),
  GroupCommonOption / ParseProxyGroup: URL string, interval int, lazy bool,
  default lazy true and automatic interval 300; parses select/url-test/fallback/
  load-balance; accepts a nonempty proxies list including one element.
- [urltest.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.31/adapter/outboundgroup/urltest.go),
  URLTestOption and selection: tolerance uint16 compared to proxy delays.
- [adapter.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.31/adapter/adapter.go),
  URLTest: delay is elapsed time divided by time.Millisecond.
- [healthcheck.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.31/adapter/provider/healthcheck.go),
  NewHealthCheck: interval converted with time.Second and lazy used by scheduler.
- [fallback.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.31/adapter/outboundgroup/fallback.go):
  FallbackOption is empty; URL/interval/lazy are common options, candidate order
  supplies fallback order.
- [loadbalance.go](https://github.com/MetaCubeX/mihomo/blob/v1.19.31/adapter/outboundgroup/loadbalance.go),
  LoadBalanceOption / NewLoadBalance: strategy string, exact `round-robin` spelling;
  common URL/interval/lazy supported. Other engine strategies are outside this MVP.

This evidence and controlled schema/generation tests establish the emitted
contract. The development host is macOS and cannot run the pinned **Linux**
binary. **Real Linux Mihomo import, client behavior and VPS Policy acceptance:
NOT RUN.** No actual latency, failover or traffic distribution is claimed.

## Persistence, refresh and atomicity

Fixed registry **v6** stores authoritative `policy_config` with this exact schema:

```json
{
  "country_groups": {"type": "url-test", "options": {
    "url": "https://www.gstatic.com/generate_204", "interval": 300,
    "lazy": true, "tolerance": 50
  }},
  "special_groups": {"type": "preserve", "options": {}}
}
```

Both scopes and their type/options mappings are required in supplied core
configuration. Empty automatic options are filled with validated defaults;
Preserve/Select options must be empty. Old callers omitting policy_config get
Preserve / Preserve. Registry v1/v2/v3 records migrate in memory to that default;
reading does not write the registry, regenerate YAML or rotate tokens/revisions.
Existing schedules, caches, current YAML and URL remain intact. Older v1/v2
source schedules retain their established Off migration. Existing public access
statistics may still be written without promoting the legacy registry schema.
A legitimate management/scheduler mutation writes v6, including Health-aware Off
for v1–v4 subscriptions. See [HEALTH_AWARE_POLICY.md](HEALTH_AWARE_POLICY.md).

Save, source enable/disable/delete, manual Refresh/Refresh All and Automatic
Source Refresh use the same saved policy and shared generator. Refresh replaces
candidates with the new parsed node membership. Last-good cache behavior is
unchanged. Config and current YAML commit together through the existing private
candidate revision and atomic registry pointer. Failed generation/serialization/
metadata writes preserve the last committed subscription and cache; stale
candidates lose the existing optimistic identity comparison.

Ordinary policy edits preserve prefix/token/public URL. As before, separately
changing URL Prefix, Regenerate Link or Delete can invalidate a URL. Public /s
reads see a complete revision. Temporary Generate uses existing /t security and
retention, with no new policy token scheme or persisted temporary Policy state.
Policy choices are redisplayed in a rejected POST response only; the existing
node draft remains separate. Fixed forms restore policy from server state.

## Health separation and limitations

**With Health-aware Policy Off, observations do not remove candidates.**
Policy core has no network/file I/O, health JSON reads, probes, health latency
ranking or exclusion. Fallback order remains generated order; optional Fixed eligibility can remove
fresh confirmed Proxy Unhealthy candidates without ranking the retained nodes. No permanent Mihomo process is introduced.
Automatic Source Refresh still fetches providers through its established path;
that is separate from the pure policy transformation.

A policy save changes Fixed revision. Old Endpoint/Proxy jobs discard their
results through existing revision guards, for Manual and Automatic alike.
Unchanged node connection fingerprints preserve existing observations. Policy
save itself never rewrites health modes, intervals, due times or failure counts;
existing concurrent revision-conflict retry bookkeeping remains applicable.
Optional exclusion, freshness and per-group fail-open rules now live in a separate
[health eligibility layer](HEALTH_AWARE_POLICY.md), after pure policy application
and before final YAML checks. Temporary Generate has no health dependency;
scoring and ranking remain outside this MVP.

Existing final structure/reference and removed-rule-target checks remain active.
This phase does not add generic Mihomo schema or proxy-group cycle validation;
a custom nested-group cycle can still require operator repair/client validation.

## tim VPS / client handoff

**REAL VPS POLICY ACCEPTANCE: NOT RUN.** Run on the dedicated test VPS:

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh \
  | sudo bash -s -- --channel main
curl -i http://127.0.0.1:8899/healthz
sudo bash /opt/clash-yaml-manager/mihomoctl.sh status
```

Require healthz HTTP 200 and managed engine COMPATIBLE. Create a dedicated
Fixed subscription with at least **two real nodes in one country**; record its
URL privately. Choose country URL-Test, save and privately download/inspect its
YAML. Confirm unchanged URL, unchanged group names/rules, type=url-test,
url/interval/tolerance/lazy, and only intended real proxy nodes as candidates.
Validate/import on Linux pinned Mihomo or the client. A local private test file
may be checked on the VPS with:

```bash
# Test YAML contains credentials: keep permissions private and never paste it.
sudo chmod 600 /path/to/private-policy.yaml
sudo /opt/clash-yaml-manager/bin/mihomo -t -f /path/to/private-policy.yaml
```

Switch URL-Test → Fallback → Load-Balance (round-robin) → Select → Preserve,
saving each time. Confirm the same URL, correct type/options/order, no stale
automatic fields on Select, and original base behavior on Preserve. Run existing
manual Endpoint/Proxy checks and verify healthz stays 200. Real latency/failover/
load distribution needs actual client traffic, beyond schema import.

Automatic Health real timer acceptance remains **PENDING / NOT FULLY CLOSED**:
the operator reported installed/enabled/active timer, one real trigger exited 0
with endpoint=0/proxy=0, real systemd-analyze PASS, COMPATIBLE and healthz 200.
Actual timer-triggered **due Endpoint and due Proxy** evidence is still missing;
follow [the independent checklist](AUTOMATIC_HEALTH.md#tim-vps-acceptance-a-real-timer-run-is-required).

Current main also stores optional country detection in Fixed v6, with
v1–v5 GeoIP Off migration. Country assignment and health identity remain
independent; see [GEOIP.md](GEOIP.md).
