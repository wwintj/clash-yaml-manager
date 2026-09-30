# Final Audit / Release Candidate Readiness — target v1.2.0

This is a feature-freeze audit, **not a publication**. VERSION and Latest Stable
remain **1.1.1 / v1.1.1**. No release commit, tag or GitHub Release is authorized
or created by this audit.

**Controlled conclusion: NOT READY until the clean pushed-head release dry-run
below completes.** All completed controlled gates pass; the dry-run is the last
outstanding gate. Real acceptance is separately and explicitly deferred.

## Identity and evidence

| Item | Evidence |
| --- | --- |
| Start HEAD / initial origin/main | `faaadc9d7c87f43c6f828641af5b96c8789d1b9f`, main, clean, equal to the actual remote |
| Previous Stable | `v1.1.1`; tag object `82b0b88ef2479cb3969f3df1e76ceb0718b4b4c0`, peeled commit `6ff864df84be74755d907032bd9be0f2cd8821de` |
| Original audited diff | `v1.1.1..faaadc9`: 46 commits, 130 files, 18,622 insertions / 174 deletions |
| Audit implementation HEAD | `cd35b07d2f84a4c243b368b3ee141b80795c9d64` |
| End HEAD | The delivered documentation commit containing this report; resolve with `git log -1 --format=%H -- docs/FINAL_AUDIT_REPORT.md`. The final response supplies its full SHA. A commit cannot embed its own SHA. |
| Baseline before editing | Python 3.12.14: **1875 passed in 241.58s**, zero failures |
| Final complete suite | **1949 passed in 255.11s**, zero failures; 74 additional tests, none removed |
| Focused audit/HTTPS/Fixed/release/state suite | **269 passed in 16.52s** |
| Integrated interaction matrix | **40 passed**: five policy types × Health-aware Off/On × GeoIP Off/On × manual/automatic refresh |
| Browser | All **11 suites PASS**; final copy correction rechecked with all suites; Preview additionally covers seven viewports |
| VERSION / default YAML | Unchanged; SHA256 `a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b`, 10,410-rule round trip PASS |

Validation uses temporary application copies, isolated subprocesses and command
or transport doubles. No developer-machine `/opt`, `/etc`, `/root`, real system
accounts, service manager, Certbot, Telegram or provider subscriptions were
operated. Test-created hashes, UUIDs and tokens are synthetic fixtures.

## Scope reviewed from the actual diff

The review used the production diff and current implementations, with historical
reports as supporting evidence. Unchanged auth, signature, migration, retention,
installation identity and remote lifecycle owners were also reviewed for integration.

| Production area | Reviewed files and resulting behavior |
| --- | --- |
| Flask integration | `app.py`: composed authenticated workspaces, independent stores, public subscription dispatch, policy/GeoIP parsing; retained login/session/CSRF/cleanup and readiness boundaries |
| Fixed authority | `fixed_subscriptions.py`, `fixed_views.py`, `fixed_sources.py`: private immutable revisions, one registry commit point, URL continuity, v1–v6 support, source operations and optimistic conflicts |
| External ingestion | `source_fetch.py`, `source_parser.py`, `source_errors.py`: public-address pinning, bounded parsing, last-good data, safe errors |
| Source scheduler | `auto_refresh.py`, `refresh_schedule.py`: Off default, bounded scan, backoff, finite history, singleton |
| Endpoint observations | `node_health.py`, `node_probe.py`, `node_identity.py`: public TCP-only probes, identity fingerprints, independent v2 auxiliary state |
| Proxy observations | `proxy_health.py`, `mihomo_probe.py`: opt-in public HTTPS probe through a short-lived pinned engine, separate settings/observations and guarded commits |
| Managed engine | `mihomo_manager.py`, `mihomoctl.sh`, `mihomo-manifest.json`: unchanged v1.19.31 pin, CPU-aware exact assets, hashes, SSH management and process cleanup |
| Health scheduling | `auto_health.py`, `health_schedule.py`: independent source/health workers, mode-safe v1 migration, per-scan limits and race-safe bookkeeping |
| Policy generation | `policy_engine.py`, `health_policy.py`, `generator.py`, `yaml_utils.py`: pure client policy, optional conservative eligibility, cached reconciliation and final reference checks |
| Country assist | `geoip.py`, `geoip_store.py`, `parser.py`: Manual > Name > GeoIP > Unknown; supplied offline database, no DNS or network |
| Settings | `settings_views.py`, `settings_status.py`: composition/view layer with safe projections; no new shared settings authority or privileged Web operations |
| HTTPS deployment | `https_manager.py`, `https_metadata.py`, `deployment_config.py`, `httpsctl.sh`: SSH-only managed loopback topology, root-owned transaction backup and conservative ownership/drift checks |
| Notifications | `notifications.py`, `notification_events.py`, `telegram.py`: strict private authority, transient committed-transition batches, direct TLS and isolated failures |
| Persistence helpers | `state.py`, existing `security.py`, `rate_limit.py`, `temporary_links.py`, `envfile.py`, `migrate.py`, `subscriptions.py`, `retention.py`: preserve password/signature semantics; narrow unsafe-object fixes |
| Lifecycle | `install.sh`, `update.sh`, `uninstall.sh`, `scripts/deploy-common.sh`, existing `remote_lifecycle.py` / generated bootstraps / `install_info.py`: conservative defaults, preservation, writer stop order, unit handling and immutable deployment identity |
| Release | `scripts/release.py`, `.github/workflows/release.yml`, `AGENTS.md`, release manuals: exact eight-script validation, minor recommendation, immutable annotated releases and dry-run-only authorization |
| Browser/templates | `static/fixed.js`, `policy.js`, `nodes.js`, `fixed.css`; Generate / Fixed / Settings and every added feature partial: escaped Jinja data / tojson, POST+CSRF forms, no external-source browser drafts, responsive tables and status presentation |
| Product documentation | README, Unreleased CHANGELOG and all current feature manuals: current scope, schema versions, HTTPS privacy, safe commands and evidence boundaries |

There is no new protocol, provider, policy type, scheduler, timer, notification
channel, settings framework or UI workflow in this audit. Flask/Python remains
the architecture, and the default YAML is not edited.

## Findings and disposition

| ID | Severity | Finding | Disposition / evidence |
| --- | --- | --- | --- |
| A1 | MEDIUM | Shared JSON reads and the update auth preflight could block on a FIFO. A private FIFO reproduced a blocked child terminated after one second. | **FIXED**: `O_NOFOLLOW\|O_NONBLOCK` open plus regular-file fstat; shared reader does not rewrite files or change legacy permission semantics. Consumers and update preflight reject FIFO/directory/symlinks; regressions have bounded subprocess timeouts. |
| A2 | MEDIUM | A dangling login-attempt state link was treated as missing state, allowing the limiter to start empty. | **FIXED**: fail closed through the same reader; preserve the link and prior data. Auth/limiter/temp-link unsafe-object tests pass. |
| A3 | MEDIUM | The request filter only suppressed Fixed URLs, leaving temporary, legacy and signed request credentials in configured access logging. New managed Nginx blocks inherited request access logging. | **FIXED for current application/new templates**: all `/s/`, `/t/`, `/sub/`, `/download/` records, including encoded paths and Referer aliases, are suppressed; both generated Nginx server blocks set `access_log off`. Ordinary update intentionally preserves older deployed Nginx configuration; operator review is documented. |
| A4 | DOC | README implied no GeoIP, omitted current modules/features, used permanent-looking development labels and omitted HTTPS/Mihomo from validation commands. Current manuals retained Fixed v3/v4, obsolete deferred-health/policy statements and Settings exclusions. | **CORRECTED**: concise feature table, current paths, v6 migration language, all five Settings sections, eight scripts and release-before/main vs released/stable wording. Historical reports/acceptance records remain unchanged. |
| A5 | DOC | Proxy UI claimed checks never change YAML even with enabled Health-aware reconciliation. | **CORRECTED**: explains preserved top-level nodes and optional managed-candidate regeneration. Browser copy rechecked. |
| A6 | LOW | Installed older reverse proxies and infrastructure error logs have their own credential logging policy. The application filter cannot sanitize Nginx/CDN/firewall logs. | **DOCUMENTED LIMIT**: new access-log defaults are safe; protect existing access/error logs, review over SSH and use reviewed integration regeneration where appropriate. No automatic external configuration rewrite. |
| A7 | LOW | Root-only Mihomo download checks a 180s loop deadline, but stdlib DNS/header/per-read behavior is not a hard total DNS cancellation budget. Package/bootstrap/release tooling also has different network policies from provider ingestion. | **DOCUMENTED LIMIT**: fixed operator tooling, checksums and socket limits; no claim of the source fetcher's strict total budget for this path. No architectural refactor during freeze. |

**Release blockers: 0. Unresolved HIGH: 0.** No arbitrary security scores are used.
Remaining limitations are explicit product/deployment boundaries, not evidence
of an unsafe supported upgrade or failing controlled gate.

## Persistent state inventory

Paths below are relative to the installed application unless absolute. `S` means
service-owned private directories **0700**, regular data files **0600** after
normal deployment. `U` means included in the root-private upgrade state snapshot
and optional uninstall data backup. Read-time in-memory normalization does not
mean a disk migration; creation/maintenance of lock files is separate from schema
writes. JSON state is committed atomically with fsync/replacement by its owner.

| Owner | Path / schema | Permissions / migrations | Read, write, backup and corruption behavior |
| --- | --- | --- | --- |
| AuthStore | `state/auth.json`, v1; hash, instance ID, auth_version, update time | S; genuine Stable v1 preserved; legacy HASH/B64/plain environment bootstrap supported | Read current shared hash each auth/session check. Initialize missing state only from nonempty credentials; password change increments auth_version, preserves instance. Migration removes environment credentials only after durable auth. U; invalid state fails closed, no reset. |
| LoginLimiter | `state/login_attempts.json`, v1; IP failures/blocked_until | S; no schema conversion | Bounded 4096 IP records; canonical addresses, prune/window/lockout under shared lock. Successful login clears the IP; blocked attempts do not extend lockout. U; corruption/unsafe objects fail closed, including broken links. |
| TemporaryLinks | `state/temporary_links.json`, v1 | S; genuine Stable format unchanged | Random 96-bit/16-char ID maps filename/creation/expiry; expiration or deletion becomes permanent null tombstone. Resolve can legitimately tombstone an expired link; prune writes maintenance. U; malformed state fails closed without credential rebinding. |
| FixedSubscriptions | `state/fixed_subscriptions.json`, v6 | S; supported disk versions **1–6**; v1 manual source, pre-v3 schedules Off, pre-v4 Preserve, pre-v5 Health-aware Off, pre-v6 GeoIP Off | Validate/normalize in memory, preserve token/prefix/revision/public bytes. Legitimate management or scheduler mutation writes v6; public access stats retain the original older disk schema. Atomic pointer rollback retains the previous revision on normal failures. U; authoritative corruption fails closed (503), no empty replacement. |
| Fixed revisions | `state/fixed_subscriptions/<id>/<revision>/base.yaml`, `current.yaml` | S; IDs are validated 32-hex; no file schema version | Immutable committed base/output, regular private-file reads; candidate staged then selected by registry. v1 historical default-base behavior remains supported. U; missing/corrupt selected content fails closed. Old unreferenced revisions collected only after successful mutation. |
| Fixed source caches | revision `sources/<source-id>/payload.bin` | S; introduced after Stable v1.1.1; v1 registry supplies a manual source only | Self-contained committed remote/upload payloads, 10 MiB bound and safe parser; no provider fetch from public read. Preserve disabled/unchanged last-good data; new URL/format needs valid data. U; missing/unusable cache never certifies changed settings. |
| Source schedules/history | Embedded source fields in Fixed registry; introduced v3 | S; v1/v2 defaults Off; existing v3+ choices preserved | Seven intervals, safe epochs, capped failures, history ≤20 allowlisted records; config/result/history share registry transaction. U; no raw URL/body/exception in history. Corruption is authoritative Fixed failure. |
| NodeHealth | `state/node_health.json`, v2 | S; validated v1→v2 **in memory**, Off/Manual retained | Opaque connection fingerprints and ≤256 records per entry, observations separate from scheduler fields. Read ≤128 MiB, reject duplicate/nonfinite JSON. Write settings/check/legitimate stale-entry pruning under guarded lock. U; auxiliary failure isolated, never resets itself or blocks public Fixed/healthz. |
| ProxyHealth | `state/proxy_health.json`, v2 | S; validated v1→v2 in memory; preserve global/custom settings and observations | Independent global probe settings, entry modes/overrides/observations/schedules; same strict bounded JSON contract. Changed global defaults reset only global users' observations/schedules. U; corrupt state isolated, old bytes retained. |
| Health-aware policy | `health_policy`, `health_policy_audit` in Fixed v6; introduced v5 | S; v1–v4 Off/48h/minimum 2 and empty safe audit | Safe aggregate audit only; cached reconciliation may update audit without new revision if YAML is identical. Existing Proxy observations never rolled back by policy failure. U; auxiliary health invalidity fails open to original candidates, Fixed corruption remains fail-closed. |
| GeoIPStore | `state/settings.json`, v1; GeoIP metadata only | S; absent feature → no database/Off; no generic settings migration | Strict metadata/type/size/SHA/timestamp paired transaction, safe local projection. U; corrupt/unavailable metadata is Unavailable and lookup falls back to Unknown, without resetting auxiliary state. |
| GeoIPStore | `state/geoip/active.mmdb`, operator-supplied bytes, ≤32 MiB | S; no bundled dataset or database conversion | Verify byte/metadata pair under lock, release before opening immutable reader; atomic replacement/removal with ordinary-error rollback. U; missing/corrupt DB fails open, no DNS/network. |
| Notifications | `state/notifications.json`, v1; revision/preferences/Telegram/delivery | Exact 0700 state and 0600 files owned by current service UID/GID; absent → Off | Strict exact keys, duplicate rejection, ≤64 KiB; read-only masked status, no GET transport. Save/Remove atomically update private configuration. Send unlocked; stale config/attempt writeback rejected. U; invalid state disables auxiliary delivery, never resets authority. No durable queue. |
| HTTPS metadata | `HTTPS_DEPLOYMENT.json`, v1 | **root:clashyaml 0640**; strict safe fields; unmanaged if absent | Read bounded regular nonlink metadata; Settings shows only status/domain. SSH setup records five managed settings/hashes and backup reference. Upgrade/uninstall backup includes it; no code-update rewrite. Corrupt/drift ownership prevents external cleanup, requires manual review. |
| HTTPS journal | `/root/clash-yaml-manager-https-backup-*/manifest.json` v1 plus `env`, `unit`, `nginx`, `hook`, `metadata` snapshots when present | Root 0700 folder / 0600 files, strictly validated root ancestry | Known-file hashes, previous file modes, service flags and written-hash journal. Restore only validated project paths; env may contain credentials. Not a general application backup; invalid backup/hash/drift stops recovery. Certificates never copied into it. |
| Installation identity | `INSTALLATION.json`, strict field allowlist, **no numeric schema version** | root 0644; historical absence supported | Public channel/base_version/commit/tag/time/source. Remote deployment records exact resolved identity; local deployment truthfully uses local identity. Upgrade backup keeps prior identity; current successful install/update writes target identity. Invalid identity stops remote downgrade resolution; Web safely marks unavailable. |
| ManagedMihomo | `bin/mihomo.json`, engine `version=v1.19.31`, exact metadata fields; `bin/mihomo` | root:root 0644 metadata / 0755 binary, 0755 bin | CPU level/build/hash validation; supported older generic amd64 metadata recognized as v3, arm64 older metadata supported. SSH explicit install/update stages and replaces pair with ordinary-failure rollback. Ordinary app update retains bin **in place**, no upgrade/uninstall data-backup copy. Invalid hash/type/mode/version → BROKEN/INCOMPATIBLE, no automatic fallback install. |
| Runtime config | `.env`, environment-file syntax, no schema version | root 0600; fixed SECRET_KEY; passwords migrate out | Auth migration removes only three legacy credential keys, preserves other records/characters; HTTPS modifies only five managed keys transactionally. Upgrade and selected uninstall backups preserve env. Invalid essential env stops preflight; not served through Web. |
| Account marker | `.service-account`, `user:uid:gid`, no schema version | root 0600 | Validate dedicated account identity/comment/home/shell before repair/removal. Upgrade backup includes it. Retained uninstall keeps account; remove path deletes only matching idle account, never `userdel -r`. Invalid/foreign marker prevents taking over another account. |
| Retention marker | `state/.last_cleanup`, timestamp bytes/mtime, no schema version | S | Hourly cleanup throttle, atomic write after uploads/outputs/backups scan; logs/state never scanned. U. Marker loss permits another cleanup scan; it does not reset auth or rebind tombstones. |
| Process locks / scratch | See lock inventory; `.fixed-candidate-*`, `.proxy-probe-*`, `bin/.mihomo-install-*`, `.health-units.*` | Locks 0600; private scratch 0700/0600; no schema | Lock inode separate from atomic JSON inode. Scratch is not committed authority; normal exceptions clean it. Hard kill can leave private scratch; review only while writers stopped. Private-state backups deliberately exclude `.proxy-probe-*`; other stranded Fixed candidates may be included and contain secrets. |

Tombstones are intentional permanent reservations, not deletion queues. Auxiliary
cleanup cannot undo an authoritative Fixed deletion. State is not pruned by the
7-day YAML backup policy. Private local filesystem and trusted administrators are
the ownership boundary; these validations are not a defense against a malicious
root or same-service-UID process rewriting directories concurrently.

## Migration and deployment evidence

`tests/test_final_audit.py` extracts **actual Stable commit**
`6ff864df84be74755d907032bd9be0f2cd8821de` into a temporary installation. Python
`-I` excludes the current checkout/PYTHONPATH; the fixture asserts the old security
module comes from that installation. It generates auth, a real Flask session,
temporary links and legacy signatures with old production code. The actual
current `update.sh` then runs with temporary paths and system-command doubles;
the updated real Flask app is loaded separately for route/session verification.

- Genuine v1.1.1 auth bytes, hash, auth_version and instance stay identical;
  password ` 密码 Ω surrounding spaces ` retains every character. The old session
  remains authenticated because its signing key/version/instance remain unchanged.
- The separate legacy environment-bootstrap case deliberately omits auth state:
  supported migration hashes the exact same password, removes only B64 credential
  configuration, preserves other `.env` records and creates a new instance. The
  prior instance's cookie is invalidated as designed. This is not a claim that a
  normal Stable install lacks auth state.
- Temporary state bytes, `/t/`, legacy `/s/`, full signed download and 8-hex legacy
  `/sub/` access remain valid while their output exists. Custom defaults and
  uploads/outputs/backups/logs remain byte-identical at update completion.
- **Fixed did not exist in Stable v1.1.1.** Supported post-Stable Fixed v1–v6
  compatibility is exercised separately by existing Fixed/refresh/policy/GeoIP
  migration tests: reads preserve token, prefix, relative URL, base/current/cache
  bytes and revision; public stats preserve the older schema; legitimate mutation
  writes v6. No invented Stable-to-Fixed reverse migration is claimed.
- Existing Health v1 migration tests exercise both Off and Manual, retaining
  observations and safe null/zero scheduler defaults; all-Off scans do not promote
  files. Corruption and concurrent settings/results fail safely without resets.
- The consolidated lifecycle test seeds Fixed revisions/upload caches, Endpoint/
  Proxy states, notifications, GeoIP artifacts, managed bin and HTTPS metadata,
  then executes real update and **both retain/remove-with-backup uninstall paths**.
  Incoming state/bin/HTTPS metadata are ignored. Update preserves all feature
  artifacts; retained uninstall preserves all; selected data backup preserves
  state and deployment metadata with private modes. Opaque GeoIP/engine/invalid
  HTTPS fixtures test preservation, not database or binary validity. Their owners'
  independent validity tests run in the full suite.
- Fresh-install deployment tests cover single-character, all-space and Unicode
  passwords, direct `APP_BIND_HOST=0.0.0.0`, Secure cookie/proxy trust false,
  absence/Off for optional state and no automatic Mihomo/GeoIP/Telegram/HTTPS work.
  Timer installation/enabling is separate from job modes: missing/Off job state
  does not produce probes/provider fetches/notifications.
- Root HTTPS controlled transactions cover issuance failure, env/unit/config/hook
  drift, exact forwarded headers, loopback app restart, private backups, disable,
  rollback and uninstall detach. Only verified project config/hook is touched;
  certificates, Certbot accounts, unrelated config and foreign users are retained.
- Remote lifecycle/channel tests execute standalone bootstraps, immutable resolved
  archives, API/archive failure stopping, no main fallback, update no-op and
  explicit downgrade boundaries. This is controlled execution, not a live VPS.

Downgrade authorization is **not schema compatibility**. v1.2 state is not promised
to work on v1.1.1. Restore coordinated old code, matching state, configuration,
identity and units where necessary; a restored old auth snapshot can revive old
sessions, so follow the documented auth recovery process. No reverse migration
is introduced.

### Three distinct backup contracts

| Backup | Included / omitted | Protection and recovery boundary |
| --- | --- | --- |
| Upgrade `/root/*-update-backup-*` | Existing code/templates/static/scripts/venv/requirements/identity/HTTPS metadata/account marker, `.env`, custom default and old five units; state snapshot after source/health/app writers stop. Runtime uploads/outputs/backups/logs and managed bin remain in place, not copied wholesale. HTTPS external integration/certificates are not copied. | Root 0700 outer folder; valid private files retain private modes. May contain auth hashes, old plaintext/B64 env, Fixed tokens, provider/node/Telegram credentials and MMDB. Dependencies are updated in the existing venv; manual recovery, not fully staged automatic rollback. |
| Uninstall optional `/root/*-backup-*` | `backups/`, `outputs/`, entire committed/private state excluding probe scratch, `.env`, VERSION, INSTALLATION and HTTPS metadata. No application code/venv/bin/default/uploads/logs/external certs. Retain choice keeps the entire installation instead. | Explicit root ownership, all directories 0700 / files 0600. For coordinated full rollback additionally retain required code/default/bin/units/external transaction backups; this data backup alone is insufficient. |
| HTTPS `/root/*-https-backup-*` | Only the five known project files plus validated journal/service flags; original env may contain secrets. No application state, MMDB, proxy configs or certificate private keys. | Root 0700/0600, hash/drift checks. Used for integration transaction restore, separate from general app update/data backups. |

## Network surface inventory

Server-side user-input policies are intentionally different from SSH/operator and
client-side traffic. No arbitrary target is added to Telegram or GeoIP.

| Surface / trigger | Destination / user control | DNS / redirects / proxy env | Budget / limits / credential handling |
| --- | --- | --- | --- |
| `source_fetch`: authenticated Save/Refresh or explicitly scheduled remote source | User HTTP/HTTPS host/path/query, no URL userinfo | Bounded child DNS; **every** answer public, transition/mixed/private blocked; numeric pinned connection with original TLS SNI/Host. ≤3 redirects, revalidate each. Ignore proxy env. | 15s total including DNS/headers/body/redirects; ≤5s connect/TLS, ≤10 MiB payload, identity encoding, truncated/oversized rejected. Allowlisted errors only; no URL/query/body/credential logs. Sequential multi-source total can exceed one request budget. |
| `node_probe`: opt-in Endpoint manual/due job | Saved VMess/VLESS server/port | Same all-public answer policy and bounded DNS child; numeric pinned TCP, no redirects/proxy env/application bytes | 3s total/node, 16 workers, 256 nodes max; fixed error enums and aggregate logs. No server/port/UUID persisted in observations. |
| `ProxyHealth.parse_target`: setting/check validation | Public HTTPS probe URL, no userinfo/query/fragment/local host | Bounded local DNS/all-answer validation; **does not pin Mihomo's later proxy-side resolver/egress** | Target validation ≠ full-engine SSRF sandbox; preserve distinct proxy/operator threat boundary. No invalid URL echo in error/session/log. |
| `mihomo_probe`: opt-in Full Proxy check | Saved node config and validated HTTPS target | Direct controller HTTP to random 127.0.0.1 port; Mihomo's traffic uses configured proxy transport/resolver. Controller does not follow redirects; target behavior belongs to pinned Mihomo. Subprocess has minimal PATH/HOME/LANG env, no proxy env. | Up to 256 nodes, batches ≤64, workers ≤16, total probe budget 235s / batch 55s; private config/secret, controller response ≤64 KiB, deterministic cleanup. TLS/protocol suitability is the actual observation, not proof all sites or DNS paths are safe. |
| `telegram`: explicit saved-credential Test or one automatic transition batch after scan | **Fixed `api.telegram.org:443` only**; token determines API path, numeric chat body | Fixed-host bounded daemon DNS; verified system-CA TLS/SNI, numeric socket connect, no redirects or environment proxies. Resolver can outlive caller but cannot send a late POST. | Hard caller budget 5s with socket watchdog, ≤64 KiB response; one request, no retry/queue. Fixed messages/clean labels/counts only; no response/error-body/raw exception/token logs. |
| `geoip`: explicit offline lookup/upload | Operator-supplied local MMDB, public literal IP only | **No DNS, network, redirects or proxy env** | ≤32 MiB supplied DB, immutable byte snapshot / MODE_FD, invalid/missing fail-open. No geographic data downloaded or transmitted. |
| `policy_engine`: generated client test settings | Valid client HTTP/HTTPS URL, including client-local targets | **Server never fetches it**; future client DNS/proxy behavior belongs to client | Pure generation, validated options and references. No server SSRF policy claimed for client test URL. |
| `mihomo_manager`: explicit root SSH install/update | Exact pinned GitHub asset URLs/manifest hashes; no Web arbitrary download URL | Normal stdlib DNS, HTTPS-only redirect handling; verified TLS; ProxyHandler({}) | 20s socket timeout; 180s checked loop deadline, **not strict total DNS cancellation**; ≤40 MiB archive / ≤100 MiB binary plus exact size/archive+binary SHA/ELF/version. Generic errors; no binary stdout/stderr exposed. |
| HTTPS SSH setup/renewal | Strict domain/email to Certbot webroot; distro package and ACME endpoints selected by operator tooling | Certbot/APT use their own DNS/proxy/redirect policies; no uniform source-fetch policy. Local curl uses direct HTTP or HTTPS `--resolve host:443:127.0.0.1`, `--noproxy '*'`, verified TLS. | Root command timeouts (normal 60s, Certbot 300s, local health 40s subprocess with curl own bounds). No remote body in Web/status errors. Certificates stay in Certbot-owned storage. Tool does not change DNS/firewall. |
| Remote install/update bootstrap | Fixed GitHub Release/commit APIs and exact codeload SHA archive; only explicit main uses main ref | System curl DNS, verified HTTPS including redirects; operator proxy env permitted, not provider pinning | 10s connect / 120s total per curl; archive validates ≤10,000 entries / ≤200 MiB extracted size, regular paths only, VERSION exact tag. Transport has no streamed archive-byte cap before extraction. Failure stops without channel fallback. |
| Install/update package/readiness/IP display | Distro apt, pip configured index; install public-IP display `api.ipify.org`; local readiness 127.0.0.1 | Operator package/index/proxy policies; readiness direct curl no redirects/proxy env | pip/apt are not globally deadline bounded. Readiness 30s total with per-attempt ≤2s and active service required; ipify display ≤3s. No optional provider/Telegram/GeoIP/Certbot request during ordinary install/update. |
| Release / maintainer verification | gh/Git to fixed repository GitHub API/remotes | Git/gh operator credential/proxy transport; no arbitrary Web URL | Read-only resolution/dry-run; publication separate explicit authorization. No explicit source-style DNS/body/deadline guarantee; never print credentials. |
| Browser assets | Bootstrap 5.3.3 at jsDelivr, existing client asset load | Browser TLS/DNS policy, not server egress | Browser runner uses cached CSS; external CDN availability/infrastructure logs outside controlled server tests. |

SSRF tests rerun in the full suite cover mixed DNS, literals, IPv6 transitions,
redirect rebinding, numeric pinning, proxy-env isolation, slow DNS/header/body,
response limits and exception sanitization. GeoIP and Settings GET tests forbid
network/subprocess execution. These results do not turn Mihomo/proxy-side DNS,
APT/Certbot or operator proxy logging into a complete sandbox guarantee.

## Process-shared locks and concurrency

| Lock | Owner / role | Known nested order / network behavior |
| --- | --- | --- |
| `auth.lock` | Auth read/change/migrate | LoginLimiter → Auth; local hash/state only |
| `login_attempts.lock` | Atomic limit/auth/record | Acquires Auth only via callback; no reverse Auth→Limiter path |
| `temporary_links.lock` | Mapping/tombstones | Cleanup → TemporaryLinks; no reverse nested cleanup path |
| `cleanup.lock` | Retention singleton | Local scans, output revocation/tombstones; no network |
| `fixed_subscriptions.lock` | Authoritative registry/output selection | Fixed → Endpoint or Proxy for short guarded result commits; Fixed → Proxy for health eligibility guard; no network/probe/generation under commit lock |
| `auto_refresh.lock` | Whole-scan nonblocking singleton | May span provider work, intentionally separate from public authoritative registry; notification delivery after release |
| `auto_health.lock` | Whole-scan nonblocking singleton | May span probes/reconcile; bounded scan, no authoritative data lock held across probes; notification delivery after release |
| `node_health.lock` | Auxiliary Endpoint snapshots/commits | Snapshot and release before Fixed/probe work; commit Fixed → Endpoint |
| `proxy_health.lock` | Auxiliary Proxy settings/snapshots/commits | Release snapshots before Fixed/probe/reconcile; commit Fixed → Proxy |
| `proxy_probe.lock` | Nonblocking global engine/probe serialization | Spans Mihomo execution intentionally; does not serialize public Fixed reads; never holds proxy state lock while doing network |
| `geoip.lock` | Paired metadata/database byte snapshots and commits | Copy verified immutable bytes then release before reader/generation/Fixed commit; no nested GeoIP→Fixed lock |
| `notifications.lock` | Config and delivery bookkeeping | Snapshot then unlock before Telegram; reacquire only for current-revision writeback, after feature/singleton locks are released |
| `bin/.mihomoctl.lock` | Root component installation serialization | Intentionally spans fixed-asset download/execution; no Web authoritative registry/health lock |
| `.httpsctl.lock` | Root deployment transaction serialization | Intentionally spans package/certificate operations; no Flask feature authority lock. Explicit app restart can interrupt service during root maintenance. |

“No network under authoritative locks” means data/config locks, not independent
worker/probe/deployment serialization locks. Provider fetch, DNS/TCP/Proxy work,
Mihomo subprocesses, Telegram and Certbot are outside the corresponding feature
state locks. Existing thread/process races, nonblocking double-scans, paused
fetch/probe/reader public access, delete/settings/revision conflicts, busy cleanup,
config-save-during-Telegram and post-commit delivery tests all PASS. Results are
committed only if the expected state still matches; notification failures do not
change successful exit/result semantics. `/healthz` skips all state/cleanup/auth
I/O; public Fixed reads use only their authoritative registry/output path, with
normal brief data-file locks and optional access-stat writes.

## Secrets, HTML and operational errors

| Secret / sensitive value | Storage / display boundary | Logs / backup handling |
| --- | --- | --- |
| SECRET_KEY | root .env/systemd environment; no Runtime value, only configured projection | Not logged; root upgrade/uninstall/HTTPS env backups can contain it. Rotation invalidates sessions/signatures. |
| Password hash / auth instance/version | S auth state; no HTML hash; password form accepts original input only | No password/hash logs; private state backups. Hash method remains PBKDF2-SHA256 1,000,000 (existing scrypt hashes also accepted). |
| Legacy HASH/B64/plain credential values | One-way migration input, never password complexity/trimmed | Removed from env only after durable state; old root backup may retain them, never public artifact |
| Fixed bearer / retired hash | S registry; **intended** Fixed URL UI and bearer-authorized YAML | All subscription request records suppressed; never event/history/error payload. Private backups retain active tokens. Password change does not revoke public bearers. |
| Temporary ID / signed and legacy tokens | S mapping or HMAC-derived URL; intended Generate result links | Same log filter; expiry/deletion/tombstone tested. Historical weak 8/12-hex tokens only for legacy filenames, never new nonce namespace. |
| VMess/VLESS UUID, URI, server | S revisions/source payloads and intended authenticated node editor/YAML; health UI sanitizes names | No operational-error/history/notification exposure; private YAML/state backups and browser Generate draft can contain node links. LocalStorage is not encrypted. |
| Provider URL query credentials | S Fixed registry; **intended** authenticated source editor, absent list/Settings/health/browser drafts | Allowlisted errors/history, no source URL logs; private backups retain URL and last-good payload |
| Telegram token / numeric chat | Strict S notifications; token never refilled, chat masked including short IDs | No URL/response/error logging; only direct Telegram transfer; private backups can retain removed credentials |
| HTTPS original .env | Root transaction backup 0700/0600 | Web sees only safe metadata/domain; no backup-content echo. Root diagnostics/infrastructure policies still require protection. |
| Certificate private key | Certbot lineage under operator/root storage, no app copy/upload | Not placed in metadata, Web or app backups; certificates never removed by assistant/uninstall |
| Mihomo controller secret | Random per short-lived batch; private config600/tempdir700 only | Never observation/HTML/journal/notification; no normal backup of probe scratch; process group cleanup on normal error/timeout/signal |

Authenticated editors and explicitly bearer-authorized YAML necessarily expose
their own credentials. “HTML secret absence” applies to unintended projections,
anonymous management pages, Settings, observational health rows and generic errors;
it does not pretend that an authenticated editable source URL or node field is
secret-free. Distinctive sentinel tests capture login success/failure, source,
Endpoint, Proxy/Mihomo, health reconciliation, GeoIP, HTTPS, Telegram and scheduler
failure paths. Raw exceptions are replaced by fixed messages/enums. Tests verify
no hashes/SECRET_KEY/Telegram token/full masked chat/provider credentials/private
endpoints/backup bodies in those surfaces. Existing and new request-filter tests
include percent-encoded aliases and full Referer suppression.

### Deterministic tracked-file secret scan

Local deterministic scans (no third-party service) inspect every tracked text file
for Telegram token shapes, UUID/node URIs, Basic-auth URLs, password-looking samples,
SECRET_KEY literals, private-key headers, Fixed bearer URLs and email-shaped values.
Candidates are reviewed by file/line and safe fingerprints; credential contents
are not printed in audit output. Test fixtures intentionally use synthetic
`TEST_ONLY`, repeated/synthetic UUIDs and invalid/sample credentials. README/template
URIs are placeholders, parser self-test credentials are fake, HTTPS registration
uses example-domain documentation, and the removed-contact string in release
validation is a guard, not a display. No real credential/private key/Fixed URL
leak was found. Scan is a bounded pattern/manual review, not proof against every
possible encoded secret. Final tracked-file counts are recorded with the dry-run
closure below; runtime state/backups are not scanned or uploaded.
The final scan covers **187 tracked files**. Candidate counts: 12 Basic-auth URLs,
34 email-shaped values, 43 node URIs, 5 password literals, 5 SECRET_KEY patterns,
2 Telegram shapes and 37 UUIDs; all are code patterns or reviewed synthetic/example
fixtures. No private-key header or concrete Fixed bearer URL matched.

## Actual Flask route classification

The new route-inventory regression enumerates the live Flask `url_map` (29 rules,
28 distinct endpoints) and verifies every management route against an anonymous
client plus every POST against a missing-CSRF authenticated client. HEAD/OPTIONS
are Flask defaults; no accidental newly public management route was found.

| Routes | Boundary / methods |
| --- | --- |
| `/`, `/static/<path:filename>` | Public GET: login shell/static assets; authenticated `/` shows Generate workspace |
| `/healthz` | Public GET readiness, returns local OK only; no state/network/auth I/O |
| `/login`, `/logout` | POST only, CSRF required; login rate-limited, logout clears session |
| `/change-password`, `/parse-nodes`, `/process`, `/delete-temp` | Authenticated POST + CSRF only |
| `/t/<short_id>` | Public bearer GET, exact ID mapping and expiry, no-store/no-referrer for output |
| `/s/<slug>` | Public bearer GET: Fixed exact prefix/token/active status, otherwise existing validated V2/legacy signature; not a management login bypass |
| `/download/<path:filename>`, `/sub/<token>/<path:filename>` | GET with authenticated session **or** exact full HMAC / scoped legacy credential; safe existing output only |
| `/fixed-subscriptions`, `/fixed-subscriptions/new`, `/fixed-subscriptions/<key>/edit` | Authenticated GET; new/edit POST additionally CSRF |
| Fixed `/<key>/<action>`, `/<key>/health/<operation>`, `/<key>/proxy-health/<operation>`, `/proxy-health/defaults` | Authenticated POST+CSRF, allowlisted operation; no GET mutation |
| Fixed `/<key>/sources/refresh-all`, `/<key>/sources/<identifier>/<operation>` | Authenticated POST+CSRF only; no public fetch endpoint |
| `/settings` | Authenticated GET; local projections, no provider/probe/Telegram/subprocess/systemctl/Nginx work |
| Settings `/upload`, `/remove`, `/health/proxy-defaults`, `/notifications`, `/notifications/test`, `/notifications/remove` | Authenticated POST+CSRF only; Test is the sole explicit notification Web send |

Passwords remain **nonempty only**, every surrounding space and Unicode character
preserved. Session contains auth_version + instance; existing Stable upgrade does
not rotate either, password change invalidates old sessions. 30-day sliding expiry,
HttpOnly, SameSite=Lax, Secure only when configured, POST logout, finite CSRF token
expiry/recovery, login limits and trusted-header opt-in remain unchanged.

`TRUST_PROXY_HEADERS=false` is the direct default. Managed HTTPS requires
`APP_BIND_HOST=127.0.0.1` and trusted single-proxy mode; generated Nginx **overwrites**
Host/X-Real-IP/X-Forwarded-For/Proto/Host/Port, never appends a client-provided chain.
Generated unit/env tests enforce loopback and no direct-public trusted Gunicorn.
Fixed token regeneration/deletion creates permanent hash tombstones; prefix changes
invalidate old path without rotating token, disable/enable preserves its identity.
Temporary tombstones prevent rebinding. These credential classes retain their
separate expiry/revocation rules.

## YAML, engine, scheduling and dependency gates

Default bytes stay at the exact required SHA and full **10,410 rules** survive
round trip. Preserve goldens and ordinary custom-field/comment/reference tests
pass. The 40-case integrated matrix combines remote/uploaded/manual nodes, all
five policies, GeoIP, three committed unhealthy observations and manual/automatic
source refresh. It checks stable bearer, base bytes, preserved health state, all
four top-level nodes, exact rules and no dangling group reference. Only enabled
managed automatic groups exclude confirmed unhealthy candidates; minimums fail
open. Generic full Mihomo YAML validation/group-cycle validation remains outside
scope; do not claim every arbitrary imported YAML is proven executable.

Mihomo remains **v1.19.31**. Every amd64 v1/v2/v3 and arm64 asset has exact pinned
name, size, archive and executable SHA in the unchanged manifest. CPU selection
uses the intersection of all visible Linux flags, not model names; unknown flags
fall back conservatively. Only verified execution failure permits trying a lower
CPU build; download/hash/architecture/version/schema failure never does. Existing
generic amd64 metadata is recognized as v3 and CPU downgrade is INCOMPATIBLE.
Root-owned binary/modes, TLS/hash verification, private configs, randomized secret
controller, finite test/startup/probe waits and TERM→KILL process-group/temp cleanup
are covered by controlled tests. No Linux binary is run on the developer host.

Source scheduler: Off default, ≤32 due sources normally; one unsplit subscription
may run alone with up to 63 sources, so 32 is **not a hard universal cap**. Provider
failures keep unchanged last-good data and use 5m/15m/30m/1h/2h/6h backoff, with
≤20 history entries. Health scheduler: max 4 Endpoint, max 1 Proxy, max 3 periodic
policy reconciles plus at most 1 reactive completion; busy/conflict retries after
5m without increasing failure count; engine unavailable preserves observations.
Notification batching follows committed transitions, no retry storm/durable queue.

Both timer families run as clashyaml with UMask 0077, NoNewPrivileges and PrivateTmp.
Source timeout 20min; Health timeout 15min, stop 10s, control-group cleanup. Both use
OnBootSec 2min / OnUnitActiveSec 5min / accuracy 30s / random delay 30s. **Persistent=true
only has catch-up semantics for calendar timers**; current timers are monotonic,
so overdue saved epoch jobs are found on a normal resumed scan, not replayed ticks.
See [systemd's timer definition](https://github.com/systemd/systemd/blob/main/man/systemd.timer.xml).
Structural/double-backed unit tests PASS; native verification is unavailable here.

Runtime/dev dependency separation remains `requirements-dev.txt` including runtime
requirements plus pytest8<9; no dependency updated solely for novelty. maxminddb
≥3.2<4 and Flask-WTF≥1.2.2<2 have upper bounds; existing Flask/ruamel/Werkzeug/Gunicorn
minimum ranges remain open and installations are not lockfile-reproducible.
PyPI's declared floors for [maxminddb3.2](https://pypi.org/pypi/maxminddb/3.2.0/json)
and [Gunicorn25.1](https://pypi.org/pypi/gunicorn/25.1.0/json) are Python≥3.10.
`pip check` passes in the tested Python 3.12 environment. All 90 Python sources parse
with Python 3.10 grammar and compile on 3.12; **3.10 runtime unavailable**, no full
3.10 test PASS claimed. OS/CPU/C extension and future dependency combinations
remain real deployment/compatibility checks.

## Documentation and release automation

README now covers all current functionality concisely and links to owners' manuals;
country wording reflects optional offline GeoIP. Current tree/commands list both
root assistants, all schedulers, Settings and all eight shell checks. Readiness
labels distinguish pre-publication testing from future Stable availability, without
rewriting historical reports. Obsolete Fixed versions, health/policy deferred
claims, Settings exclusions and Proxy explanatory copy are corrected. Rollback
instructions stop all writers and restore matching five units. Public contact-email
display remains removed. Release README markers and all historical released
CHANGELOG sections are untouched.

Unreleased notes are reviewed prose from the actual diff, grouped only under
Added/Changed/Fixed/Security/Deployment; duplicate GeoIP/Settings notes were merged.
No raw git log was pasted or notes promoted. **SemVer recommendation: v1.2.0**,
a minor for backward-compatible user-visible functionality since v1.1.1, not a
patch merely because the final audit fixes are narrow. No compatibility break
requires a major; reverse downgrade compatibility is not promised.

`release.py.SHELL_SCRIPTS` is exactly install, remote-install, update, remote-update,
uninstall, httpsctl, mihomoctl and deploy-common. New regression runs the actual
validation function with tool-call recording and proves both assistants receive
bash -n/ShellCheck alongside bootstrap sync, dependency/full-suite and diff gates.
Workflow remains tag `v*`, Python 3.12, requirements-dev install, `--publish-tag`,
contents:write only, per-tag concurrency without cancellation. No GitHub permission
expanded or workflow changed. Stable installs resolve Releases and exact tag
commits; API/archive failures stop, main is explicit only. Annotated tags/Releases
remain immutable, Actions/local races verify identical metadata, interrupted
publication uses the existing-tag flow. Audit authorization stops at **dry-run**.

### Controlled gate matrix

| Gate | Result / boundary |
| --- | --- |
| Baseline full pytest | PASS — 1875 |
| Final full pytest | PASS — 1949, zero failures |
| Browser suites | PASS — 11, all include relevant 1440/390 checks, Preview seven widths; navigation/labels/overflow/tables/status/actions covered |
| v1.1.1→current / auth / temporary links | PASS — actual old code fixture, real update control flow and new app; system commands doubled |
| Fixed v1–v6 / Health migrations | PASS — preserved read bytes/URL, conservative defaults, legitimate write paths |
| Update / fresh install / uninstall & backups | PASS — controlled script execution; native ownership/system services not exercised |
| State inventory / network / SSRF-DNS / lock order | PASS — actual owners and concurrency/transport tests, limits described above |
| No network under authoritative locks | PASS — serialization-lock distinction explicit |
| Secret inventory / tracked scan | PASS — deterministic patterns and manual classification, no real leak found |
| Log redaction / HTML secret absence | PASS — intended authenticated editor/output fields excepted; external infrastructure logs excluded and documented |
| Public routes / auth-session / header trust / subscription security | PASS — complete live route inventory and existing credential/session tests |
| YAML / Mihomo / Source Refresh / Auto Health | PASS — controlled; unchanged default/pin, no real due-job claim |
| Policy / Health-aware / GeoIP / Settings / HTTPS / Notifications | PASS — controlled; independent real acceptance remains deferred |
| Current docs / README / reviewed CHANGELOG | PASS — historical snapshots retained, no release metadata promotion |
| Release automation / tag workflow | PASS — tests/structural review; no new tag workflow executed |
| Python syntax / Python 3.10 grammar | PASS — 90 sources; full 3.10 runtime NOT RUN |
| Node syntax | PASS — 16 tracked JS/CJS files |
| pip check | PASS — no broken requirements |
| bash -n | PASS — 8 intended shell files |
| ShellCheck 0.9.0 / 0.11.0 | PASS / PASS — both binaries actually available and executed |
| Bootstrap synchronization / diff check | PASS / PASS |
| systemd-analyze | **UNAVAILABLE** on this macOS host; structural unit tests only |
| Native Nginx | **UNAVAILABLE / NOT RUN**; generated-config/command-double tests only |
| Default.yaml | UNCHANGED — exact SHA above, 10,410-rule round trip PASS |
| Release dry-run | PENDING until clean pushed-head execution below |

## Real acceptance debt — explicitly deferred

| Required real acceptance label | Status |
| --- | --- |
| REAL TELEGRAM NOTIFICATION | **NOT RUN** |
| REAL HTTPS VPS | **NOT RUN** |
| REAL GEOIP VPS | **NOT RUN** |
| AUTOMATIC HEALTH REAL DUE ENDPOINT | **PENDING** |
| AUTOMATIC HEALTH REAL DUE PROXY | **PENDING** |
| REAL POLICY | **NOT RUN** |
| REAL HEALTH-AWARE POLICY | **NOT RUN** |

Historical operator-attested manual Mihomo/VMess/VLESS and empty timer evidence
remains in prior reports, attributed to the operator. It does not close this
matrix, establish real due jobs, prove current Telegram/Certbot operation or GeoIP
accuracy, or become an independent reproduction. Real provider timer acceptance
is also not newly claimed. These explicitly deferred optional/environment checks
do not themselves block controlled RC readiness.

## Dry-run closure

Required command after all audit fixes/docs are committed and pushed:

```bash
python3 scripts/release.py minor --dry-run
```

Expected current VERSION/stable 1.1.1, proposed 1.2.0 and tag v1.2.0. Result currently
PENDING. The closure records the exact pushed checkpoint, actual output and local
file/ref/remote tag/Release invariance, then reruns against the final delivered
clean pushed documentation commit. Neither run invokes publication. Until it
passes, the conclusion remains NOT READY; after successful closure and all gates,
the permitted conclusion is READY WITH DOCUMENTED DEFERRED REAL ACCEPTANCE.
