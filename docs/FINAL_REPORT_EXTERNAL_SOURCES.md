# Fixed Subscriptions — External Sources: Final Report

**Channel:** `main` (unreleased development build; not a Stable Release)
**Stable baseline:** `v1.1.1` (unchanged)
**Verified feature code:** `029e4132aac86d30b067b025550d68ad8eed5118`
**Report reconciliation base:** `fd0a2c225608bee0be6ba161cf011859d6cc9cf1`
(the two intervening commits only changed documentation; application/test code is identical)
**Previously recorded test VPS build:** `1.1.1-dev+6b55cf1`
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
| Passed | **594** on Python **3.12.14** |
| Failed | **0** in the supported acceptance environment |
| Gate: `>446 passed`, every test PASS | **PASS** |
| Default YAML 10,410-rule round trip | **PASS** |
| VERSION unchanged / no tag / no Release | **PASS** |
| Python / Node syntax; `pip check`; `bash -n` | **PASS** |
| ShellCheck 0.9.0 / 0.11.0; `build_bootstraps --check`; `git diff --check` | **PASS** |
| Playwright browser E2E (`.cjs`) | **PASS** — seven preview viewports, Fixed CRUD and external-source lifecycle (desktop/mobile) |

The supported run uses an isolated Python 3.12.14 environment with current project
dependencies. A separate Python 3.9.6 run recorded 593 passes and a failure in
`test_installed_gunicorn_supports_service_flag`; that older runtime cannot satisfy
Gunicorn ≥25.1.0 and is not the acceptance environment. No test was excluded or
reclassified to obtain the **594 passed** result.

The browser run uses the existing Node/Playwright/Chromium runtime and the isolated
`tests/run_preview_browser.py` harness. It covers remote success → failure/cache →
recovery at the same Fixed URL, changed manual nodes with cached remote data,
uploaded YAML, invalid replacement preservation, enable/disable/delete, and no
credential browser storage. Network tests use controlled fixtures, not real
provider credentials. The repository's existing Python 3.9 `.venv` is preserved.

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
| Previously resolved VPS commit | `6b55cf1c53c50d9051c07117f52ad77147d7dd9a` (historical deployment record; later commits only adjust documentation) |
| Installed build on test VPS | `1.1.1-dev+6b55cf1` |
| Service | active (running); `healthz` → `OK` |
| Web identity | `Clash YAML Manager v1.1.1-dev+6b55cf1` + `DEV · Development Build` badge |
| External reachability | reachable (app port allowed in UFW) |

The VPS rows above preserve the earlier deployment acceptance record. Report
reconciliation did not reconnect to or redeploy that VPS. Local isolated Web
rendering at `fd0a2c2` verified the main build suffix and DEV badge; later report
commits naturally have a different development suffix after installation.

## VERDICT

All required automated gates **PASS**, including **594/594 pytest tests** and the
complete Playwright browser suite. VERSION/Latest Stable remain 1.1.1; no tag or
Release was created. `main` is ready for external-source development testing.
The prior VPS record remains separate from the controlled local acceptance tests.
