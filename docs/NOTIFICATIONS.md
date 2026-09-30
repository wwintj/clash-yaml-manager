# Notifications MVP

Current release scope, supported migrations and deferred real acceptance: [Final Audit](FINAL_AUDIT_REPORT.md). New functionality is intended for the next Stable; before publication use explicit `--channel main`.

Telegram is the only provider in this MVP. Notifications are **Off by default**.
An ordinary installation or update makes no Telegram request, prompts for no
Telegram credentials and installs no extra dependency, service or timer. Direct
HTTP and managed HTTPS deployments use the same feature.

## Settings setup

Log in and open **Settings → Notifications** (`/settings#notifications`).

1. Enter your Bot Token and numeric Chat ID, choose event categories and enable
   Telegram when ready. Use your own bot and an accessible destination. Positive
   IDs identify users; negative IDs support groups/supergroups. Usernames, URLs,
   whitespace and oversized IDs are rejected. Token syntax is bounded numeric
   bot ID, colon and URL-safe characters; no configurable API host or proxy.
2. **Save Settings** commits locally and does not contact Telegram. The token
   and replacement Chat ID inputs always render blank. Blank keeps each saved
   credential; disabling retains credentials. Enabling requires both credentials.
3. **Send Test Notification** explicitly attempts one fixed test message using
   saved credentials, even while the provider is disabled. Unsaved fields are
   ignored. A failed test retains configuration and displays a generic notice.
4. **Remove Credentials** disables Telegram and clears token/chat ID in current
   notification state, preserving category preferences and other application data.

All mutations are authenticated, CSRF-protected POST actions followed by a 303
redirect. Settings keeps `no-store` and `no-referrer`. GET reads local files only:
no Telegram DNS/network, source fetch, health probe or subprocess; absent state
creates neither `notifications.json` nor `notifications.lock`. Corrupt/unsafe
notification state makes only this section **Configuration unavailable**, with
no automatic repair or outgoing request. Other Settings sections remain usable.

Status distinguishes provider Disabled/Enabled from last delivery success/failure.
It shows whether a token is configured, a masked destination (only the final four
digits for longer IDs), UTC attempt/success times and safe error codes. It is not
an overall system health verdict. Small IDs are fully masked.

## Automatic transitions

Only automatic `auto_refresh` and `auto_health` scans collect events. Manual
refresh/checks, Fixed/Policy saves, GeoIP, HTTPS, authentication and password
changes do not automatically send messages. Explicit Test is the manual send.

| Category | Incident | Recovery | No repeated alerts |
| --- | --- | --- | --- |
| Source Refresh | Enabled remote sources with `consecutive_failures > 0`: aggregate 0 → positive | Positive → 0 | Persistent failure or changes between positive counts |
| Endpoint Health | Successful automatic job: UNHEALTHY count 0 → positive | Positive → 0 | SUSPECT/UNKNOWN and 1 → 2 / 2 → 1 unhealthy |
| Full Proxy Health | Same boundary for successful automatic Proxy jobs | Positive → 0 | SUSPECT/UNKNOWN/UNSUPPORTED and positive-count changes |
| Scheduler Failures | Committed Endpoint/Proxy `scheduler_failures` 0 → positive | Positive → 0 after successful automatic job | Further job failures while count stays positive |

Source last-good cache fallback is **degraded refresh**, not a complete subscription
outage or provider success. A subscription gets one aggregate event even if several
sources fail together. Source conflicts alert only if authoritative failure state
actually changes. Health messages use aggregate counts, never individual nodes.
Scheduler result labels are restricted to existing safe values. Busy/conflict keep
the existing 300-second retry without incrementing `scheduler_failures`, so a
transient busy/conflict alone creates no scheduler incident. No thresholds,
backoff, filtering or health-aware policy reconciliation rules are changed.

Events are collected immediately after authoritative commits, as transient safe
objects containing category, transition, sanitized label, counts, safe result and
UTC time. Each refresh scan and each health scan sends **at most one message**,
after releasing Fixed, health, probe, notification and scheduler singleton locks.
Categories are checked against committed notification configuration at delivery.
Messages are bounded to 3500 characters; one aggregate omitted-event count replaces
excess events instead of splitting into more requests.

## Private state and data transfer

Only `state/notifications.json` contains notification credentials. Its strict v1
schema comprises version, monotonic configuration revision, Telegram settings,
four Boolean category preferences and last-delivery metadata. Duplicate keys,
unknown fields, wrong types, nonfinite timestamps and invalid credentials are
rejected. State is at most 64 KiB, a regular **0600** file; the separate process-shared
`state/notifications.lock` is also regular 0600. The state directory is 0700.
Ownership must match the runtime effective user/group (deployed
**clashyaml:clashyaml**). Symlinks, FIFOs, directories, devices, wrong ownership or
permissions are rejected without silently fixing existing objects.

Tokens are plaintext in this private file because sending requires them; no
application encryption-at-rest is claimed. Credentials never enter `.env`,
Settings/Fixed/health/GeoIP/auth/HTTPS metadata, Flask session, normal HTML or logs.
The notification state contains no event history, message bodies or Telegram
response data, only the most recent bounded delivery metadata.

Enabling this feature transfers data to Telegram: the bot token is necessarily
part of the Bot API request path, and the Chat ID routes the HTTPS request.
Automatic message text contains sanitized subscription labels and aggregate
operational counts; test text is fixed plus UTC time. Do not put sensitive personal
information in subscription labels. Controls/newlines/whitespace are normalized,
labels are bounded and obvious URLs, node URIs, UUIDs, Fixed bearer shapes, opaque
credentials, IPs and hostnames are redacted. No source or node names/URLs/configs,
server addresses, UUIDs, fingerprints, bearer links, passwords, application secrets,
GeoIP paths or certificate keys are copied into event objects or message text.

The sender makes a direct verified HTTPS POST to fixed **api.telegram.org** using
system CAs and hostname verification. `HTTP_PROXY`, `HTTPS_PROXY` and `ALL_PROXY`
are ignored. No arbitrary endpoint, redirect following or HTTP retry exists.
Only HTTP 200 with JSON Boolean `ok: true` succeeds; non-JSON, duplicate/invalid
JSON, oversized responses and API failures become safe codes (`timeout`, `network`,
`tls`, `http`, `api`, `invalid_response`, `config`). Response bodies and raw exceptions
are never stored, displayed or logged. Response bodies are bounded to 64 KiB.

A five-second total budget covers DNS/connect/TLS/request/headers/body. Socket
reads use the remaining deadline, and a watchdog interrupts slow-drip headers/body.
A timed-out system DNS lookup may finish later in a daemon thread, but that thread
only resolves the fixed hostname and can never send a late POST. No credentials
are given to it. There is no outbound proxy support in this MVP.

Protocol references: [Telegram Bot API](https://core.telegram.org/bots/api) and
[Python HTTPSConnection](https://docs.python.org/3/library/http.client.html).

## Best-effort delivery and concurrency

Source/health state and generated YAML remain authoritative. Telegram/configuration/
bookkeeping failures do not change scanner exit results, source/cache state, health
observations, retry schedules or reconciliation. Disabled providers and categories
perform no delivery. Broken notification state remains untouched while normal
operational work continues. Critical scanner bootstrap/state errors preserve the
existing failing exit result and do not attempt notification delivery.

There is **no durable queue, automatic resend or guaranteed delivery**. A failed
send, disabled category, process interruption, truncated batch or configuration
change can lose a transition. Persistent incidents are not resent on every scan;
recovery remains eligible when the underlying aggregate boundary changes. If a
successful send cannot write delivery bookkeeping, Settings can show stale delivery
status; the sender does not loop or resend. Inspect operational state independently.

Sending snapshots committed credentials/configuration revision under the notification
lock, releases it before network work and records a result only if that revision
is still current and no newer attempt superseded it. Remove/Save can complete during
a slow send; old results cannot overwrite new preferences or resurrect credentials.
An already-dispatched request cannot be recalled by removing credentials. Multiworker
saves are serialized, atomic replaces use the existing private state conventions,
and failed writes attempt restoration of the previous committed bytes. Filesystem
failure/power loss can still require restoring a consistent private backup.

## Updates, backups and scope

Existing update, private-state backup helper and uninstall retained backup preserve
notification state with private permissions. No separate backup system is added.
Backups can retain old credentials after Remove: protect them as secrets and review
retained backups before sharing or disposal. No credentials go into public release
artifacts. Ordinary updates keep the configured provider preference; installations
with missing notification state remain Off.

SMTP/Gmail, Discord, Slack, Webhooks, Pushover, Gotify, provider plugins, alerting
for policy reconciliation and proxy routing are future scope. Controlled evidence is in [NOTIFICATIONS_REPORT.md](NOTIFICATIONS_REPORT.md).
**REAL TELEGRAM NOTIFICATION: NOT RUN**.
