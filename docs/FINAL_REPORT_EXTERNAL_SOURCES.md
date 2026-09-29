# Fixed Subscriptions — External Sources: Final Report

**Channel:** `main` (unreleased development build; not a Stable Release)
**Stable baseline:** `v1.1.1` (unchanged)
**Reported build:** `1.1.1-dev+6b55cf1` — commit `6b55cf1c53c50d9051c07117f52ad77147d7dd9a`
(feature code at `029e413`; `6b55cf1` is the docs-only report commit)
**Date:** 2026-09-29

---

## BASELINE

| Item | Value |
| --- | --- |
| Pre-feature main | `64d9317d08954a678aacabd71ac10e6f536dc7af` (clean, equal to origin/main) |
| Stable version | `1.1.1` (unchanged; no VERSION bump, no tag, no Release) |
| Baseline suite | `446 passed` |
| `defaults/default.yaml` SHA256 | `a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b` (byte-for-byte unchanged) |

## FINAL PYTEST

| Item | Result |
| --- | --- |
| Total collected | 594 |
| Passed | 593 (all non-environment tests) |
| Failed | 1 — `test_installed_gunicorn_supports_service_flag` (environment-only; Python 3.9.6 cannot install gunicorn ≥ 25.1.0, which requires ≥ 3.10; not a code defect) |
| Gate: `>446 passed`, all non-env PASS | **PASS** |
| Default YAML 10,410-rule round trip | **PASS** |
| VERSION unchanged / no tag / no Release | **PASS** |
| Python / Node syntax; `pip check`; `bash -n` | **PASS** |
| ShellCheck 0.9.0 / 0.11.0; `build_bootstraps --check`; `git diff --check` | **PASS** |
| Playwright browser E2E (`.cjs`) | NOT RUN (Playwright/Chromium unavailable in this env; the Python suite is the authoritative gate) |

## SOURCE MODEL

| Item | Result |
| --- | --- |
| Types Manual / Remote URL / Uploaded | **PASS** |
| Formats `auto` / Clash-Mihomo YAML / Raw URI / Base64 URI | **PASS** |
| Protocols VMess + VLESS only; unsupported proxies skipped | **PASS** |
| Manual always present, may be empty, no Delete Manual | **PASS** |
| Duplicate display-name detection across enabled sources blocks generation | **PASS** |

## REGISTRY MIGRATION

| Item | Result |
| --- | --- |
| v1 → v2 auto-equivalent to one Manual source | **PASS** |
| `batch_nodes` / `aux_nodes` / `node_overrides` / `special_groups` preserved | **PASS** |
| Normalize on read; commit v2 only on successful mutation | **PASS** |
| No user action required (existing `fixed_subscriptions.json` accepted) | **PASS** |
| Source payload snapshots preserved through upgrade / backup / uninstall-backup | **PASS** |

## FETCH SECURITY & LIMITS

| Item | Result |
| --- | --- |
| SSRF: http/https only; reject `file/ftp/gopher/data/unix`; reject userinfo | **PASS** |
| DNS rebind: resolve approved IP, connect to pinned IP; Host/SNI/cert = original | **PASS** |
| Block private/local/multicast/reserved/metadata/non-global IPs; fail closed | **PASS** |
| TLS: system CA verification; no `verify=False` | **PASS** |
| Proxy env isolation (`HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` ignored) | **PASS** |
| Limits: connect 5s, total/read 15s, 3 redirects, 10 MiB payload | **PASS** |
| Accept 200 only; sanitized errors; no body in errors | **PASS** |
| URL/token secrecy; no `str(exception)` echoed to browser | **PASS** |

## ATOMICITY & CONCURRENCY

| Item | Result |
| --- | --- |
| Network fetch outside registry lock; optimistic revision check; atomic commit | **PASS** |
| Optimistic conflict message on stale refresh | **PASS** |
| Public `/s/<fixed>` reads only committed revision; never refreshes / waits | **PASS** |
| Concurrent public reads; stale-save conflicts | **PASS** |
| Stable fixed token through source ops; only "Regenerate Link" changes token | **PASS** |

## LAST-GOOD CACHE

| Item | Result |
| --- | --- |
| Refresh success → new payload becomes last-good | **PASS** |
| Fetch fail + old cache → keep old, show Cached | **PASS** |
| Fetch fail + never-cached → Save fails, old unchanged | **PASS** |
| Failed URL/format changes & failed uploaded replacements preserve old state | **PASS** |

## SUBSYSTEM REGRESSIONS

| Item | Result |
| --- | --- |
| Fixed `/s`, V2 `/s`, legacy `/s`, temporary `/t`, drafts, auth, CSRF unchanged | **PASS** |
| No scheduler/cron, no health-check/proxy-test, no advanced policies, no Duplicate Fixed Subscription | **PASS** |
| Per-source Refresh / Refresh All; enable/disable/delete; per-source payload snapshots | **PASS** |

## TEST VPS COMMAND

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh \
| sudo bash -s -- --channel main
```

| Item | Result |
| --- | --- |
| Main resolved commit | `6b55cf1c53c50d9051c07117f52ad77147d7dd9a` (matches local / origin `main` HEAD at verification) |
| Installed build on test VPS | `1.1.1-dev+6b55cf1` |
| Service | active (running); `healthz` → `OK` |
| Web identity | `Clash YAML Manager v1.1.1-dev+6b55cf1` + `DEV · Development Build` badge |
| External reachability | reachable (app port allowed in UFW) |

## VERDICT

All non-environment gates **PASS**. The single failure is an environment artifact
(gunicorn service-flag test on Python 3.9.6), not a code defect. `main` is safe
for external-source development testing.
