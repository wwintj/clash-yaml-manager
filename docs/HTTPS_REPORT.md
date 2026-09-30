# HTTPS / Nginx Deployment Assistant MVP — acceptance report

Date: 2026-09-30. Start gate PASS: clean **main**, HEAD = origin/main = actual
remote `b3ac3fc22484b989a016509c08f46f8ef2d82446`, VERSION **1.1.1**, Latest Stable
**v1.1.1**. Baseline full pytest **1547 passed in 223.87s, 0 failed**, before edits.
No tag, Release or version bump is part of this phase.

Final full pytest: **1686 passed in 233.10s, 0 failed**. New coverage adds
**139 tests**, including concurrency, lock preservation, missing-helper uninstall,
invalid runtime drift and stopped/removed Nginx regressions. All ten Playwright suites PASS: Preview, Fixed,
External Sources, Endpoint Health, Full Proxy Health, Policy, Health-aware Policy,
GeoIP, Settings and new HTTPS Settings. The new suite checks four runtime states
at **1440px and 390px**, without overflow or privileged controls.

## Evidence boundary

Deployment tests execute Python orchestration against a temporary filesystem and
command doubles. Existing lifecycle tests execute real shell scripts with fake
PATH commands and temporary application/systemd paths. Certbot returns synthetic
certificate files; no real issuance, Nginx, systemd, public port binding, apt,
firewall, DNS or production `/opt`, `/etc`, `/root` or account mutation occurred.
A separate isolated real Flask startup also verified loopback bind, a Secure
session cookie, one-hop ProxyFix, exact spaced Unicode password, HTTPS URL
builders and byte-unchanged live temporary ID/expiry state. Browser tests use an
isolated Flask copy and a test-only metadata control server;
production contains no fixture bypass or privileged Web endpoint.

Metadata refers to a **root-private original backup**, rather than embedding raw
previous values: a prior DOWNLOAD_BASE_URL can contain credentials. The backup
retains exact previous records, and Settings sees only strict safe fields.

| Gate | Controlled result / evidence |
| --- | --- |
| APP_BIND_HOST | PASS; missing→0.0.0.0, strict public/loopback values, invalid startup and update preflight stop safely |
| DEFAULT DIRECT HTTP COMPATIBILITY | PASS; existing missing-key installs retain public bind and current port semantics |
| ORDINARY INSTALL DOES NOT ENABLE HTTPS | PASS; explicit public bind, no Nginx/Certbot commands/packages |
| ORDINARY UPDATE DOES NOT ENABLE HTTPS | PASS; no external integration commands or HTTPS enablement |
| HTTPSCTL ROOT ONLY | PASS; shell and Python entry-point guards, safe invalid-option diagnostics |
| HTTPSCTL STATUS | PASS; read-only, no lock/backup creation, safe NO/YES/DRIFT, only local checks |
| HTTPSCTL SETUP | PASS; phased challenge/final configs, full tuple and metadata published last |
| HTTPSCTL DISABLE | PASS; original five raw records including absent/nondefault/quoted values restored |
| TRANSACTIONAL ROLLBACK | PASS; Certbot, first/final nginx -t, app restart and local TLS failure; signal and post-replace fsync failure; private recovery command validates known snapshots |
| ROOT PRIVATE BACKUPS | PASS; 0700 dirs / 0600 snapshots and hashed strict manifest, no private keys |
| DOMAIN VALIDATION | PASS; schemes/paths/ports/controls/IP/localhost/.local/wildcards/invalid DNS rejected; ASCII punycode accepted |
| EMAIL VALIDATION | PASS; conservative syntax, no mailbox checks, no email metadata/output |
| NGINX OWNERSHIP ISOLATION | PASS; marker+strict metadata+hashes, orphan/unowned paths refused |
| DOMAIN COLLISION | PASS; exact names including multiline/quoted case variants in nginx -T |
| PORT COLLISION | PASS; other/unknown ownership fails; Nginx ownership accepted, no process killing |
| NGINX -T / -t VALIDATION | PASS; captured command-double checks; both staged config failures restore previous state |
| FORWARDED HEADER TRUST | PASS; all six exact controlled headers, no append/client-authoritative forwarding |
| LOOPBACK GUNICORN | PASS; non-root clashyaml and 127.0.0.1:${APP_PORT}; safe low-port capability retained |
| COOKIE_SECURE | PASS; full successful managed tuple requires true |
| TRUST_PROXY_HEADERS | PASS; full successful tuple requires true with loopback binding |
| DOWNLOAD HTTPS ORIGIN | PASS; exact configured domain via existing URL builders |
| CERTBOT WEBROOT | PASS; certonly --webroot, one cert name/domain, noninteractive agree-tos, no --nginx |
| ACME CHALLENGE | PASS; dedicated root webroot, location before fixed-origin HTTP redirect |
| RENEWAL HOOK | PASS; exact lineage guard, root-only, nginx -t then reload, no app/env changes |
| CERT DATA PRESERVED ON DISABLE | PASS; synthetic certificate/key bytes retained; no cert delete calls |
| DRIFT DETECTION | PASS; env/config/hook/unit/metadata/permissions/private backup changes refused; same-domain missing cert refused without issuance |
| MANUAL NGINX PRESERVED | PASS; unrelated config bytes survive setup, rollback, disable and detach |
| UNRELATED ENV PRESERVED | PASS; quoted Unicode/literal shell characters and later secret/unrelated changes preserved |
| UPDATE PRESERVATION | PASS; HTTPS tuple, metadata0640, lock0600 and assistant replacement; loopback unit regeneration, metadata backup |
| UNINSTALL OWNERSHIP SAFETY | PASS; detach only verified config/hook, syntax/reload, no env/app writes; drift leaves external files; retained backup includes metadata |
| SETTINGS RUNTIME | PASS; configured/absent/invalid/manual state, authenticated domain, bind and factual runtime flags; metadata is not live proof |
| NO WEB PRIVILEGED ACTION | PASS; no HTTPS setup/disable routes, forms/buttons or privileged JS |
| NO WEB SUBPROCESS | PASS; normal Settings GET records zero process/DNS calls; original Settings guard regressions retained |
| SECRET ABSENCE | PASS; metadata/HTML omit key/password, email, private key, bearer/provider/credential URL sentinels; strict schema rejects unknown secret fields |
| FIXED URL TOKEN STABILITY | PASS; existing slug/token and relative path preserved across origin switch |
| TEMP LINK STATE STABILITY | PASS; existing token/URL identity and expiry state semantics untouched; original temporary-link regressions retained |
| AUTH STATE STABILITY | PASS; snapshot byte comparison and unchanged owner modules; password policy remains nonempty only |
| HEALTH STATE STABILITY | PASS; observations and schedules not touched; original health regression/browser suites retained |
| SOURCE STATE STABILITY | PASS; Fixed registry/YAML/payload/cache state untouched; original update/source regressions retained |
| GEOIP STATE STABILITY | PASS; MMDB/settings bytes untouched and original GeoIP regression/browser suite retained |
| BROWSER | PASS; ten suites, including original nine and new HTTPS reporting |
| 390PX | PASS; four HTTPS states, no horizontal overflow |
| 1440PX | PASS; four HTTPS states, no privileged controls or secrets |
| DEFAULT.YAML | UNCHANGED; SHA256 a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b |
| 10,410 RULE ROUND TRIP | PASS; full generator/Fixed/policy default round-trip regression retained |

## Validation and publication

Python AST syntax (83 files), Node syntax (15 files), pip check, bash -n,
ShellCheck **0.9.0** and **0.11.0** (all eight deployment scripts including
httpsctl), build_bootstraps.py --check and git diff --check PASS. Default YAML
hash exactly matches the required baseline. The developer host is macOS;
**systemd-analyze and nginx unavailable**, so real unit verification and native
Nginx syntax fixture execution were not run. Config semantics are tested by
controlled render/command assertions; real Ubuntu/Debian integration is deferred.

Known limits: packages, ACME webroot and newly issued certificates may remain
after rollback; no package removal/certificate deletion. Exact-name collision
detection is conservative, not an interpreter for all wildcard/regex configs.
MVP Nginx listeners are IPv4. Renewal relies on Certbot's standard scheduler.
Power loss/SIGKILL or unexpected concurrent manual edits may require root review
of the retained backup. Unknown edits are never blindly overwritten by rollback.
Same-domain setup checks local health/certificate presence before its no-op.

VERSION **1.1.1** / Latest Stable **v1.1.1** unchanged. **TAG: NO. RELEASE: NO.**
Feature/tests/docs commits are published to main only after the final controlled
gates pass; exact commit and remote equality evidence are returned in the task
completion message (avoiding a self-referential report commit hash).

## Real acceptance remains deferred

- **REAL HTTPS VPS: NOT RUN** (REAL HTTPS VPS ACCEPTANCE: NOT RUN).
- **REAL GEOIP VPS: NOT RUN**.
- **AUTOMATIC HEALTH REAL DUE ENDPOINT: PENDING**.
- **AUTOMATIC HEALTH REAL DUE PROXY: PENDING**.
- **REAL POLICY: NOT RUN**.
- **REAL HEALTH-AWARE POLICY: NOT RUN**.

No real Let's Encrypt, DNS, firewall or live HTTPS evidence is claimed.
