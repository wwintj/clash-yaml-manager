# Notifications MVP controlled acceptance report

Starting main HEAD and origin/main:
`5ee118c39cdcec3202549ee95d3295ece2080327`, clean working tree. Baseline full
pytest **1686 passed in 239.67s, 0 failed**, before implementation. VERSION
**1.1.1**, Latest Stable **v1.1.1**. This phase authorizes main-only development
publication, **no new Tag or Release**.

Final full pytest: **1875 passed in 247.43s, 0 failed**. Notification-specific controlled tests:
**189 passed in 9.20s, 0 failed** (private state, transport, UI routes, concurrent
workers and real committed transitions). All eleven browser suites PASS.

## Evidence boundaries

All Telegram operations use controlled doubles. Local loopback HTTP servers with
controlled TLS wrappers exercise real socket deadlines and connection-close
behavior; production TLS context verification is asserted separately. No real
bot, chat, Telegram DNS/connect/POST, service account, `/opt`, `/etc`, `/root`,
Nginx, ACME or live VPS was used. Lifecycle fixtures execute existing scripts with
temporary paths and command doubles. These results do not establish real delivery.

Core evidence: `tests/test_notifications.py`,
`tests/test_notification_transitions.py`, existing automatic health/refresh,
Settings, deployment, GeoIP, policy and generator regressions. UI evidence:
`tests/test_notifications_browser.cjs` plus the original ten browser suites.

## Controlled gates

| Gate | Result / evidence |
| --- | --- |
| NOTIFICATIONS DEFAULT OFF | PASS; missing state yields disabled defaults, no data/lock creation on GET, no transport initialization |
| TELEGRAM PROVIDER | PASS; exactly one fixed-host Bot API POST, explicit fixed-message Test |
| PRIVATE STATE | PASS; regular 0600 data/lock, private owned 0700 directory; unsafe objects rejected without blocking or repair |
| STRICT V1 SCHEMA | PASS; exact keys/types, bounded credentials/revision/timestamps/state, duplicate-key and malformed rejection |
| TOKEN NEVER ECHOED | PASS; blank password input, safe status projection and rejected-input notices |
| MASKED CHAT DESTINATION | PASS; last four digits for longer IDs, short IDs fully masked, replacement input always blank |
| AUTH | PASS; anonymous Settings/actions redirect and expose no notification status |
| CSRF | PASS; all three routes reject missing token; POST-only |
| SAVE ATOMICITY | PASS; injected failures before and after replace restore previous bytes; no partial new file |
| TEST NOTIFICATION | PASS; exactly one controlled send using committed credentials, including disabled provider; unsaved inputs ignored |
| REMOVE CREDENTIALS | PASS; disable/clear token/chat, retain event preferences and unrelated state |
| SETTINGS GET ZERO NETWORK | PASS; guarded DNS/connect/Telegram/source/probe/subprocess calls all remain zero |
| TELEGRAM HTTPS/TLS | PASS (controlled); fixed HTTPSConnection, system CA context, hostname verification and TLS error classification |
| NO ENV PROXY | PASS; direct sockets and no tunnel while all proxy environment variables are set |
| NO ARBITRARY ENDPOINT | PASS; fixed host/path, no endpoint/provider/proxy field; unknown form/state keys rejected |
| NO REDIRECT FOLLOW | PASS; 301/302/307 and other non-200 responses fail after one request without body reads |
| BOUNDED TIMEOUT | PASS; five-second total budget; bounded DNS plus watchdog verified against slow headers and slow body |
| BOUNDED RESPONSE | PASS; 64 KiB body bound, malformed/non-JSON/duplicate/NaN/oversize rejection, no body storage |
| SOURCE INCIDENT | PASS; real committed aggregate 0 → positive, including failed candidate retry metadata |
| SOURCE RECOVERY | PASS; positive → 0, one event per subscription |
| SOURCE CACHE DEGRADED | PASS; last-good cached refresh emits degraded incident; retained payload/YAML remains available |
| ENDPOINT UNHEALTHY INCIDENT | PASS; real third-failure successful automatic job 0 → 1 |
| ENDPOINT RECOVERY | PASS; 1 → 0, subsequent successes silent |
| PROXY UNHEALTHY INCIDENT | PASS; same real committed boundary |
| PROXY RECOVERY | PASS; positive → 0, subsequent successes silent |
| SUSPECT NOT ALERTED | PASS; first/second failures silent, positive unhealthy count changes silent |
| UNKNOWN NOT ALERTED | PASS; initial Unknown → Healthy job silent |
| UNSUPPORTED NOT ALERTED | PASS; completed unsupported Proxy job has no unhealthy/scheduler incident |
| SCHEDULER INCIDENT | PASS; authoritative 0 → 1 job failure; safe error/engine-unavailable result |
| SCHEDULER RECOVERY | PASS; repeated failure silent, successful job resets count and emits once |
| TRANSITION DEDUPE | PASS; source persistent failures, health 1 → 2 / 2 → 1 and scheduler 1 → 2 remain silent |
| BATCHED DELIVERY | PASS; two source incidents in one POST; Endpoint incident + Proxy recovery + scheduler recovery in one health POST |
| MESSAGE TRUNCATION | PASS; 100-event controlled batch stays below 3500 characters and reports remainder count |
| NO NETWORK UNDER FEATURE LOCKS | PASS; transport double acquires all existing feature, probe, notification and singleton locks nonblocking, then reads Fixed state |
| DELIVERY FAILURE ISOLATION | PASS; corrupt config, disabled categories, transport exceptions and bookkeeping failure preserve authoritative scan success/state; no immediate retry |
| CONFIG RACE SAFETY | PASS; paused send permits Remove/Save; old result cannot overwrite new revision; newer attempts win; process-shared concurrent saves retain intact credentials |
| SECRET ABSENCE | PASS; seeded token/chat/Fixed credential/application secret absent from normal HTML, messages and logs |
| LOG REDACTION | PASS; only existing safe scanner logs and fixed Settings notices; no raw transport exception/response |
| NO NODE DATA | PASS; real health alerts contain aggregate counts only, not node names/hostname/URI/UUID/fingerprint |
| NO SOURCE CREDENTIALS | PASS; actual query-credential source and malicious subscription labels redacted; synthetic userinfo URL never copied into event objects (existing source validation continues rejecting userinfo URLs) |
| SOURCE STATE STABILITY | PASS; notification actions preserve all source/cache/history bytes; delivery failures do not alter successful source bookkeeping |
| HEALTH STATE STABILITY | PASS; notification actions preserve Endpoint/Proxy bytes; existing thresholds and backoff unchanged; failed commits emit no observation event |
| FIXED/YAML STABILITY | PASS; byte snapshots retained through notification actions and automatic health jobs; source failure keeps last-good YAML |
| AUTH STATE STABILITY | PASS; notification action snapshot includes private auth bytes; password policy remains unchanged |
| GEOIP STATE STABILITY | PASS; private database/settings bytes untouched and existing regressions/browser retained |
| HTTPS STATE STABILITY | PASS; metadata/environment bytes untouched; Runtime remains read-only |
| UPDATE/BACKUP PRESERVATION | PASS; real-script temporary update/private backup/uninstall retained backup keep exact notification bytes and 0600 mode |
| BROWSER | PASS; all original ten suites plus Notifications, no page errors |
| 390PX | PASS; default/masked/configured/toggles/test outcomes/remove/corrupt state; no horizontal overflow |
| 1440PX | PASS; same states, blank credentials, no unrelated privileged controls |
| DEFAULT.YAML | UNCHANGED; SHA256 `a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b` |
| 10,410 RULE ROUND TRIP | PASS; full generator/Fixed/policy default round-trip regression |

Existing busy/conflict behavior is preserved: short retry, no increment of
`scheduler_failures`, hence no incident for a single transient busy/conflict.
Observation and scheduler events are collected only after successful commits;
manual work and critical bootstrap errors perform no automatic delivery. Context
collectors do not leak to another thread. Notification metadata is auxiliary,
with no durable queue, event history, automatic retries or delivery guarantee.
Changing settings during a scan may skip an event; an in-flight POST cannot be
recalled by Remove. A failed bookkeeping write can leave stale status. Filesystem
failure/power loss may require restoring a consistent private backup. Existing
private backups can retain cleared credentials and must remain protected.

## Full validation and publication

| Check | Result |
| --- | --- |
| Baseline full pytest | 1686 passed in 239.67s, 0 failed |
| Final full pytest | 1875 passed in 247.43s, 0 failed |
| Notification-specific pytest | 189 passed in 9.20s, 0 failed |
| All browser/Playwright suites | PASS; eleven suites, including prior ten; 1440/390px and original layout breakpoints |
| Python syntax | PASS; AST parse of 88 Python files |
| Node syntax | PASS; `node --check` of 16 JS/CJS files |
| pip check | PASS; no broken requirements, requirements.txt unchanged |
| bash -n | PASS; all eight shell scripts unchanged |
| ShellCheck 0.9.0 | PASS; all eight shell scripts |
| ShellCheck 0.11.0 | PASS; all eight shell scripts |
| build_bootstraps.py --check | PASS; source and standalone lifecycle entrypoints unchanged |
| git diff --check | PASS |
| systemd-analyze | UNAVAILABLE on macOS; no new unit/timer or timeout changes; controlled lifecycle regressions retained |

VERSION **1.1.1** / Latest Stable **v1.1.1** remain unchanged. **TAG: NO.
RELEASE: NO.** Main is pushed only after final controlled gates pass. Exact
feature/test/docs commits, final HEAD and origin/main equality are returned in
the completion message, avoiding a self-referential documentation commit hash.

## Real acceptance matrix (unchanged)

| Real gate | State |
| --- | --- |
| REAL TELEGRAM NOTIFICATION | NOT RUN |
| REAL HTTPS VPS | NOT RUN |
| REAL GEOIP VPS | NOT RUN |
| AUTOMATIC HEALTH REAL DUE ENDPOINT | PENDING |
| AUTOMATIC HEALTH REAL DUE PROXY | PENDING |
| REAL POLICY | NOT RUN |
| REAL HEALTH-AWARE POLICY | NOT RUN |
