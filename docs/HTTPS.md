# HTTPS / Nginx Deployment Assistant (Unreleased main)

HTTPS is optional. Ordinary install/update stays HTTP and never installs Nginx,
Certbot or requests a certificate. VERSION and Latest Stable remain **1.1.1**.
This feature is available on development main until a future stable release.

The topology is browser → Nginx on TCP 80/443 → Gunicorn on
`127.0.0.1:${APP_PORT}` → Flask. Gunicorn and Flask remain `clashyaml`, never root.
`httpsctl.sh` is a root/SSH deployment tool. Settings only reads safe metadata and
process configuration; it cannot run privileged commands or change deployment.

## Prerequisites and commands

Use an existing valid non-root application installation on Debian/Ubuntu. Set an
ASCII DNS hostname to this server and make public TCP **80 and 443** reachable.
The MVP listens on IPv4; remove an unusable AAAA record or supply a matching IPv6
Nginx listener manually after reviewing ownership/drift consequences. This tool
never changes DNS, UFW, iptables, nftables, cloud security groups or NAT. It does
not look up a public IP or call DNS/provider APIs. Root must have `ss`, `curl` and
systemd available (ordinary installs supply these requirements).

```bash
sudo bash /opt/clash-yaml-manager/httpsctl.sh status
sudo bash /opt/clash-yaml-manager/httpsctl.sh setup \
  --domain example.com --email admin@example.com
sudo bash /opt/clash-yaml-manager/httpsctl.sh disable
```

`setup` accepts one strict ASCII DNS hostname: no scheme, IP literal, path,
query, fragment, port, userinfo, wildcard, whitespace, controls, localhost or
`.local`. Already-ASCII punycode is accepted; no silent IDNA conversion. Email
uses conservative syntax checking, without mailbox verification, and is passed
only to Certbot registration. Never paste secrets into domain/options.

Only explicit setup may run `apt-get update` and install `nginx certbot` when
missing. It does not install the Certbot Nginx plugin or use `certbot --nginx`.
Existing Nginx and unrelated sites, including `sites-enabled/default` and
`nginx.conf`, remain untouched. An occupied 80/443 port with another process or
unverifiable ownership stops setup. Captured `nginx -T` output is checked for
obvious exact-domain ownership by another enabled configuration. This is a
conservative exact-name check, not a complete interpreter for every Nginx regex,
wildcard, include or dynamic configuration. Resolve ambiguous manual ownership
before setup. It never kills a conflicting service.

## Managed files and trust model

The deterministic project config is
`/etc/nginx/conf.d/clash-yaml-manager.conf`, with a generated ownership marker.
Existing files there or at the renewal-hook path are refused without verified
metadata and matching hashes, even if a marker appears in an orphaned file.

Successful setup requires the whole tuple:

```dotenv
APP_BIND_HOST=127.0.0.1
COOKIE_SECURE=true
TRUST_PROXY_HEADERS=true
DOWNLOAD_URL_SCHEME=https
DOWNLOAD_BASE_URL=https://example.com
```

`APP_BIND_HOST` permits only `0.0.0.0` or `127.0.0.1`; absent means `0.0.0.0`.
Invalid values fail startup and update preflight before stopping services. New
ordinary installs explicitly use `0.0.0.0`. Generated systemd units resolve this
validated bind value and retain `${APP_PORT}` expansion, low-port capability
support and the non-root service account.

ProxyFix trusts one hop only. Managed Nginx overwrites Host with `$host`,
X-Real-IP and X-Forwarded-For with `$remote_addr`, X-Forwarded-Proto with `https`,
X-Forwarded-Host with `$host`, and X-Forwarded-Port with `443`. It does not append
incoming forwarding headers. Both server blocks use the exact validated domain
and reject a different Host, including when selected as Nginx's default server.
The only upstream is `http://127.0.0.1:${APP_PORT}`. Keep loopback binding together
with proxy trust; direct public ingress with trusted client headers is unsafe.

TLS uses 1.2/1.3 and system defaults. HSTS and HTTP/2 are not enabled by this MVP.
HSTS is sticky and should be a separately reviewed manual hardening decision.
Uploads allow 50 MiB; proxy read/send timeout is 300 seconds, matching Gunicorn,
with a 10-second connect timeout. Flask security headers remain unchanged.

## Certificate issuance and renewal

Setup creates a root-owned `/var/lib/clash-yaml-manager-acme` Webroot, stages an
HTTP-only challenge server (other paths return 503), tests with `nginx -t`, then
reloads or starts Nginx. Non-interactive `certbot certonly --webroot` uses only the
exact domain, a deterministic cert name, `--agree-tos`, and HTTP-01. Certificate
files must exist at standard Certbot live/archive paths before final activation.

Final HTTP serves `/.well-known/acme-challenge/` before redirecting all other
paths to the fixed HTTPS domain. Certbot owns its standard certificate, account
and renewal data. The root-owned executable deploy hook
`/etc/letsencrypt/renewal-hooks/deploy/clash-yaml-manager-nginx.sh` checks the exact
`RENEWED_LINEAGE`, runs `nginx -t`, then reloads Nginx. It never changes `.env` or
restarts the app. Certbot's standard system timer/cron performs renewal; this
project does not replace it. Confirm that the package's renewal scheduler is
operational on the target VPS.

After switching the full environment tuple and regenerating the unit, setup
performs daemon-reload, app restart, is-active and direct loopback health HTTP
200. Nginx is then reloaded and checked locally using:

```bash
curl --resolve example.com:443:127.0.0.1 https://example.com/healthz
```

Certificate verification remains enabled; there is no `-k` fallback. Success
requires HTTP 200, with no external HTTP acceptance dependency. Metadata is
written only after those checks pass. Raw command output, `.env`, passwords,
registration email, tokens and private keys are not printed by the assistant.

## Transactions, disable and recovery

Before mutations, setup/disable retain a root-private backup in
`/root/clash-yaml-manager-https-backup-YYYYMMDD_HHMMSS.XXXXXXXX`. Directory mode is
0700; snapshots and the strict hashed manifest are 0600. It contains only known
project `.env`, app unit, owned Nginx config, renewal hook and HTTPS metadata
snapshots, as applicable. **No certificate private keys are copied.**

Selected writes use private temporary files, fsync, atomic replacement and parent
fsync. The manifest journals intended hashes before each publication, allowing
recovery after replacement/fsync failures. On normal errors or catchable signals,
project files and prior app/Nginx active/enabled state are restored as closely as
practical. A restored active app is restarted and checked. Service failures,
unexpected concurrent edits, SIGKILL or power loss can require root recovery;
review the retained backup if automatic rollback is reported incomplete.

Packages installed and certificates obtained before a later failure may remain.
Rollback never uninstalls packages or deletes certificate/operator account data.
It does not promise to reverse arbitrary system-wide apt side effects.

`disable` verifies metadata, ownership, file hashes and the full environment tuple
before touching anything. It restores the **original raw records** of the five
managed keys, including missing settings, quoting and nondefault values, from the
first private backup. Unrelated current `.env` records, including later secret
changes, remain intact. The unit is regenerated from restored bind settings; app
and available Nginx syntax checks must pass before metadata removal. Active
Nginx is reloaded; a stopped or removed Nginx is not started by disable. Certificates, Certbot accounts
and renewal configuration remain. The prior public bind may become directly
reachable again. Review firewall exposure yourself.

Explicit recovery is available for a previously recorded transaction:

```bash
sudo bash /opt/clash-yaml-manager/httpsctl.sh rollback \
  --backup /root/clash-yaml-manager-https-backup-YYYYMMDD_HHMMSS.XXXXXXXX
```

It accepts only an exact absolute root backup path, checks private ownership,
permissions, known filenames, strict manifest, installation identity and hashes,
and restores only that transaction's known files/service state. No tarballs,
URLs, traversal or symlinks. It also refuses current selected-file hashes outside
the saved original and journaled versions, so it cannot silently erase later
administrator edits. Backups are retained and never garbage-collected by this
MVP; protect them as credentials and ensure capacity. For unknown drift, review
and reconcile edits manually against the private snapshots before retrying; do
not blindly copy an entire old `.env` over newer credentials.

Same-domain consistent setup checks certificate-file presence, Nginx syntax, app and
local TLS health, then is a no-op with no Certbot call. A different domain
requires disable then setup. Modified environment, unit, config, hook, unsafe
metadata or invalid previous backup is DRIFT; setup/disable stop. `status` is
read-only, creates no lock/backup, and makes only local health calls. It reports
managed YES/NO/DRIFT, safe runtime flags, certificate-file presence and available
local checks. Presence is not proof of certificate validity. No metadata means
no ownership; manual HTTPS flags can be present without being an error.

## Application data, Settings and lifecycle

HTTPS changes the rendered origin only. Existing Fixed `/s/...` paths, token,
prefix and slug remain; temporary identity/expiry state, SECRET_KEY, auth version,
password hash, instance ID, YAML/source payloads, refresh/health schedules and
observations, policies, GeoIP data/settings and defaults are not changed. Browsers
may need to reconnect through HTTPS; origin-scoped drafts do not migrate across
origins. No password complexity or trimming is introduced.

`HTTPS_DEPLOYMENT.json` is strict version1, 0640 root:clashyaml, with safe domain,
time, cert mode, app port, hashes, full managed tuple and a private-backup reference.
Original values remain in the root-only backup, since an old URL may contain
credentials. Metadata has no email, password, secret, token or key. Authenticated
Settings Runtime displays Configured/Not configured/Metadata unavailable, optional
domain and factual runtime flags. It does not verify live DNS, certificates,
Nginx, firewall or drift. No privileged Web route/action/button exists.

Ordinary update preserves managed `.env`, metadata, certificates, hook and Nginx
config; replaces assistant code; backs up metadata; regenerates the app unit from
current APP_BIND_HOST; does not execute Nginx/Certbot. Uninstall detaches only
verified owned config/hook, tests and reloads active Nginx, and preserves metadata
for an optional retained application backup. Drift/unverifiable ownership leaves
external files in place and reports manual cleanup. Certificates and accounts
always remain; use Certbot's own documented cleanup after reviewing other users
of that lineage, as a separate operator action.

## Acceptance boundary and references

See [HTTPS_REPORT.md](HTTPS_REPORT.md) for controlled tests. **REAL HTTPS VPS:
NOT RUN**; no real Let's Encrypt issuance is claimed. REAL GEOIP VPS NOT RUN,
AUTOMATIC HEALTH REAL DUE ENDPOINT/PROXY PENDING, REAL POLICY NOT RUN and REAL
HEALTH-AWARE POLICY NOT RUN remain deferred.

Primary references: [Certbot manual](https://eff-certbot.readthedocs.io/en/latest/man/certbot.html),
[Certbot usage and renewal](https://github.com/certbot/certbot/blob/main/certbot/docs/using.rst),
[Nginx proxy directives](https://nginx.org/en/docs/http/ngx_http_proxy_module.html),
[Nginx core directives](https://nginx.org/en/docs/http/ngx_http_core_module.html).
