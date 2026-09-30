# Settings Framework MVP (Unreleased main)

`/settings` is an authenticated server-rendered workspace with anchor navigation:
[Overview](../README.md), GeoIP (`/settings#geoip`), Health (`/settings#health`) and
Runtime (`/settings#runtime`). The page uses Flask/Jinja partials, existing terminal
styles and normal HTML forms; core navigation and actions do not require JavaScript.
No new frontend/Python dependency, generic settings registry or systemd unit is added.

## Ownership and composition

Settings is a view/orchestration layer. Each feature retains its existing authority:

| Value | Owner |
| --- | --- |
| MMDB and safe database metadata | `GeoIPStore`, `state/geoip/active.mmdb`, `state/settings.json` |
| Global Full Proxy probe defaults/observations/schedules | `ProxyHealth`, `state/proxy_health.json` |
| Fixed sources, policies and country detection | `FixedSubscriptions`, `state/fixed_subscriptions.json` and revision files |
| Endpoint observations/schedules | `NodeHealth`, `state/node_health.json` |
| Authentication | `AuthStore`, `state/auth.json` |
| Effective runtime/deployment configuration | process environment / `.env`, installation metadata and deployment files |

`state/settings.json` remains exactly the **v1 GeoIP metadata schema**. Its paired
MMDB replacement/rollback transaction is unchanged. No Health or Runtime values
are copied into it, a second settings file, Fixed registry or session. Session is
used only for transient notices/CSRF/authentication as before.

`core/settings_views.py` composes these owners. `core/settings_status.py` contains
small presentation/coercion helpers; it does not import `app.py`, read environment
files, persist settings or invoke network/system tools. Feature-specific partials
live in `templates/settings/`. Add a future section by composing its own safe
view model and authoritative feature API, rather than building a plugin engine.
Notifications, HTTPS/Nginx/certificates and general maintenance controls are outside MVP.

## Overview and best-effort reads

Overview shows base VERSION, the existing `read_install_info()`/`display_build()`
build/channel identity, GeoIP availability, local Mihomo status and total/active/
disabled Fixed counts. VERSION is the only version source; this is not an online
Latest Release check. Missing installation metadata retains the application's
existing base-version/channel display; invalid metadata yields channel `unknown`.
Counts read registry metadata only, without opening current YAML or parsing nodes.
No names, tokens, source URLs or fingerprints are included in the aggregate model.
Optional scheduler configuration counts are omitted rather than coupling to private
state or invoking per-subscription `describe()` paths.

GeoIP, Proxy defaults, engine, counts and Runtime are independently best-effort.
Corrupt/unavailable auxiliary state produces a bounded Unavailable message; other
sections remain usable. Fixed counts and global Probe reads use brief nonblocking
feature locks. Busy reads show Unavailable and never repair, prune or rewrite
state. GeoIP retains its existing brief nonblocking snapshot lock and short-lived
reader. Auth/session state remains authoritative: this does not bypass a failed
security-state check. Existing application request cleanup still runs normally.

GET `/settings` performs local reads only. It does not fetch providers, resolve
DNS, probe nodes, start Mihomo, regenerate subscriptions, read unit status or invoke
`systemctl`, `journalctl`, shell commands or any subprocess. MMDB checks and Mihomo
file integrity checks may read bounded local database/binary content (32 MiB MMDB
and the existing 100 MiB managed binary limit); no global
mutable reader cache or long-lived cross-feature lock is added.

## GeoIP

The existing status/type/size/checksum prefix/upload UTC, Upload / Replace and
Remove controls are preserved under GeoIP. Existing POST `/settings/upload` and
`/settings/remove` remain compatible; successful actions redirect 303 to
`/settings#geoip`. Invalid upload uses a safe 400 page with the previous database
retained. CSRF/oversized request recovery still returns to Settings without replay.

The **32 MiB** limit, private directories/files, controlled active filename,
atomic replacement/rollback, unsafe-file rejection and fail-open generation are
unchanged. No MMDB download or DNS exists. Upload/removal does not change saved
GeoIP mode or regenerate any Fixed YAML. See [GeoIP](GEOIP.md) for operation,
transaction limits, licensing, retention and replacement semantics.

## Health and global Proxy defaults

The canonical editable **Global Full Proxy Probe Defaults** form is now in
Settings → Health. It edits HTTPS URL, expected HTTP status and timeout through
POST `/settings/health/proxy-defaults`. Successful save uses 303
`/settings#health`; invalid input gets a generic 400 with a fresh usable form,
original normalized defaults and no rejected-value echo.

Both this route and the retained compatibility route
`/fixed-subscriptions/proxy-health/defaults` call the **same `ProxyHealth.set_global()`**
and transport coercion helper. No target validation or persistence is duplicated
in the web layer. Existing public HTTPS/no-credentials/no-query/no-fragment,
public DNS/address validation and numeric bounds remain authoritative. Saving a
new target can resolve its hostname under those existing validation rules; the
**zero-network guarantee applies to Settings GET**, not this already authorized
Proxy validation operation.

When defaults actually change, existing observations and schedules for
subscriptions using global settings reset exactly as before. Custom subscriptions
retain their settings/observations/schedules. Saving identical values preserves
existing observations/schedules. These saves directly modify only Proxy Health
state; they do not rotate URLs, change source configuration/cache/history,
GeoIP mode, Policy/Health-aware configuration or current YAML. Existing subsequent
scheduler/reconciliation behavior remains authoritative; no immediate bulk
regeneration is introduced.

The old Fixed route retains subscription validation and redirect to its edit
page. Fixed edit replaces its large global form with a read-only summary and
**Manage Global Defaults in Settings** link. Per-subscription Off/Manual/Automatic,
Use global/Custom, custom URL/status/timeout, interval, Check Proxies Now and result
table remain on Fixed edit. Endpoint Health remains per-subscription TCP reachability,
with no invented global target configuration.

## Mihomo and scheduler evidence

Health displays managed engine status, required/installed version, architecture,
CPU level and build/preferred build when available. Settings calls the existing
status validation with `verify_execution=False`: ownership, permissions,
metadata, pinned binary checksum and CPU compatibility are checked, **no `-v`
execution occurs**. COMPATIBLE here describes local file/metadata compatibility;
it does not prove that the binary executes or that a proxy works. Existing CLI and
probe callers keep `verify_execution=True` and their unchanged execution checks.
A compatible-looking file can still fail a later execution check.

Mihomo install/update/delete/download remains SSH-only. The page lists commands,
never executable web controls. Timer names are deployment guidance, not actual
unit status. Real enabled/active/due execution is an operator/SSH check.

## Runtime and privacy

Runtime shows effective APP_PORT, download URL mode (Automatic / Explicit scheme /
Explicit base URL), secure-cookie and trusted-proxy indicators, upload/output/
backup retention, cleanup interval and 30-day session lifetime. Retention is
shown in seconds, including valid fractional environment durations. A base URL is
shown only as Configured / Not configured, never its raw origin/path/value.
The explicit HTTPS indicator conservatively rejects credentials, query/fragment,
malformed ports and control characters in presentation; it is not a security audit.
No overall Secure/Unsafe/Vulnerable verdict is shown.

Runtime is read-only. Change deployment configuration / `.env` and restart over
SSH when needed; proxy trust, cookies and session implications require operator
management. Flask does not write `.env`, unit files, Nginx config, shell scripts or
`INSTALLATION.json`. No raw environment/file dump, SECRET_KEY, password/hash,
legacy credentials, session cookie, bearer token, provider credential, node URI,
UUID or private node endpoint is displayed. Rejected Probe values/raw exceptions
are never added to notices or operational logs.

All Settings GET/POST routes require login. Mutations are POST-only and protected
by the existing Flask-WTF CSRF layer. Settings responses retain **no-store** and
**no-referrer**. Semantic section links and associated labels/status notices work
at desktop 1440px and mobile 390px without horizontal page overflow.

## Validation boundary

Controlled tests use temporary private state, reader/provider/engine doubles and
synthetic pinned binaries. Browser tests verify real forms and layout against an
isolated Flask copy. No new real VPS acceptance is required or claimed.

- Real GeoIP VPS: **NOT RUN**.
- Automatic Health real due Endpoint: **PENDING**.
- Automatic Health real due Proxy: **PENDING**.
- Real Policy / Real Health-aware Policy: **NOT RUN**.

See [Settings report](SETTINGS_REPORT.md) for this phase's controlled evidence.
