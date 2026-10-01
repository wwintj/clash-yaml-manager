# v1.3.1 UI density refinement — second-pass readiness report

Audit date: 2026-10-02. Main development only; no release or VPS update.
The original `UI_CONSISTENCY_REPORT.md` is retained without alteration.

START HEAD: `176cf92cf43c392bf888eafa0609eaa483c0846d`

IMPLEMENTATION HEAD: de5937fdd507d23be9ce3111619fefeb36bc70d3

END HEAD is the subsequent documentation commit adding this report. Resolve its
SHA using `git log -1 --format=%H -- docs/UI_DENSITY_REFINEMENT_REPORT.md`.
The local delivery report records the exact final SHA and remote verification.

Commits: `style: tighten ui density and navigation rhythm` (styles, markup and
browser geometry coverage), then `docs: record ui density refinement`.

## Start and release boundaries

Fetched origin. Branch main, clean worktree, local HEAD == origin/main == actual
remote main at START HEAD. VERSION 1.3.0; Latest Stable v1.3.0. Baseline was run
before repository edits: **2668 passed in 363.28s**, 0 failed.

VERSION, README stable markers, default YAML, app.py, all core modules, scripts,
protocols, APIs, routes, persistence, schema, authentication, schedulers, Health,
Policy, Fixed, Sources, Merge and Diff behavior were not changed. No new runtime
dependency, CDN, font request or framework was introduced. Only classes/wrappers
and technical-value font selection changed in live templates; form/action IDs,
names, values, types, disabled/required and submission attributes remain intact.
The only production JS diff adds a utility class to Preview Apply; ui.js stays
1169 bytes. Historical unrouted templates remain untouched.

## Density decisions and actual geometry

PAGE SPACING != CONTROL SPACING. The 1200px shell retains its 24px desktop and
16px mobile horizontal margins. The card token changes from 32/24/16px to
24/20/16px for desktop/tablet/mobile. Nested panels use 16px / 12px mobile.
The header has compact vertical padding; Login retains 24px vertical breathing
room. Control groups use 8px gaps, form groups 16px, sections 24px. Labels are
8px from controls and ordinary input help is 4px away. Checkboxes, table rows,
badges, status summaries, alert and Diff padding are reduced independently.

Horizontal padding is intentionally larger than vertical visual spacing.
Buttons use inline-flex centering, 4px vertical CSS padding and explicit role
heights. Active/inactive navigation uses identical border width and font weight;
inactive links are lighter, with a visible tint/border for current navigation.

| Control role | Desktop / tablet height | <=575px height | Horizontal padding |
| --- | --- | --- | --- |
| Main Nav | 40px | 42px | 16px |
| Secondary Nav | 36px | 40px | 12px |
| Primary | 44px | 44px | 20px |
| Standard | 40px | 44px | 16px |
| Utility / danger utility | 32px | 40px | 12px |
| Form input/select/file | 40px | 44px | 12px plus select-arrow reservation |

Textarea retains >=192px and content/rows determine its height; internal padding
is 8px vertical / 12px horizontal. Technical text remains monospace; ordinary
text uses the shared local system font. Primary font weight is 600; ordinary
navigation/buttons 500, body 400. Generate, Download, cleanup and save/back bars
follow content width and wrap. Login retains full width; existing mobile Preview
Apply follows its card width intentionally.

| Navigation measurement | 1440 before → after | 390 before → after |
| --- | --- | --- |
| Main container height | 44 → 40px | 96 → 90px (wrapped) |
| Main button height | 44 → 40px | 44 → 42px |
| Main gap | 8 → 6px | 8 → 6px |
| Main outer padding | 0 → 0px | 0 → 0px |
| Main band incl. adjacent margins | 92 → 72px | 144 → 122px |
| Header panel height | 248 → 188px | 373 → 317px |
| Header padding, vertical / horizontal | 32/32 → 16/24px | 16/16 → 12/16px |
| Settings nav container height | 44 → 36px | 96 → 84px (wrapped) |
| Settings button height | 44 → 36px | 44 → 40px |
| Settings gap | 8 → 4px | 8 → 4px |
| Settings nav outer padding | 0 → 0px | 0 → 0px |
| Settings parent card padding | 32 → 24px | 16 → 16px |
| Settings parent card height | 188 → 160px | 229 → 213px |

Inspection of actual main found no padded outer navigation container: padding
was already zero. It remains zero rather than introducing another panel. The
excess came from button weight/height, 24px surrounding margins and the padded
status header. Those are reduced, and inactive buttons no longer look like cards.
Settings is a lighter secondary toolbar with smaller height, padding and gap.

| Form/page measurement | 1440 before → after | 390 before → after |
| --- | --- | --- |
| Generate form | 2154 → 1801px (−16.4%) | 3246 → 2905px (−10.5%) |
| Generate document | 3620 → 3047px | 5183 → 4668px |
| Fixed Edit form | 3139 → 2690px (−14.3%) | 4743 → 4248px (−10.4%) |
| Fixed Edit document | 5858 → 4995px | 10235 → 9102px |

Measurements use identical synthetic isolated fixtures and width/state matches;
full-page heights are evidence of density, not universal pixel requirements.
Desktop tables share 8px vertical / 12px horizontal padding; mobile tables keep
local scrolling/card layouts. Diff retains exact monospace bytes, internal
scrolling and 12px code padding. No page overflow is hidden by clipping.

Endpoint action bars now center buttons rather than stretching them to label
height. Removing Bootstrap d-block from interval labels lets the existing
hidden attributes work; the same JS still controls visibility and disabled state.
No check, save or scheduling code changed. Runtime technical values gain the
mono class while keeping the original metadata/text contract.

## Screenshots and manual review

Actually viewed Login, Generate, parsed Preview, Diff, Result, Fixed List, Fixed
Edit, Settings Overview, GeoIP, Health, Runtime and Notifications at **1440 and
390px**: all **24 required views**. Also viewed all four main/Settings navigation
crops, before navigation/page captures, source editing, expanded automatic Policy,
Automatic Endpoint/Proxy/custom forms, password dialog and readable lower-form
mobile detail tiles. Tall screenshots were checked through readable details and
crops, not merely scaled full-page thumbnails.

Evidence root: `/Users/t/.codex/artifacts/clash-yaml-manager/v1.3.1-density/`.
`before/` retains START screenshots and 133 measurements; `after/` retains final
screenshots and 140 measurements. `main-nav-comparison.png` and
`settings-nav-comparison.png` show desktop and mobile before/after. Synthetic test
credentials and loopback URLs in private source/Diff views are fixture data only.

## Tests and accessibility

FINAL PYTEST: **2668 passed in 363.23s**, **0 failed**. No Python tests were deleted or
weakened. Display/Preview/Merge/Diff subset: **195 passed in 67.58s**. Runtime
metadata recheck: **18 passed in 3.29s**; original assertions remain unchanged.
The first full run found two strict HTML-order assertions after adding a class;
class was moved before data-runtime to preserve those existing assertions, then
the entire suite was rerun. That failed attempt is not the final validation.

Browser suites: **16/16 PASS**. Preview, Fixed, External, Endpoint, Proxy, Policy,
Health-aware Policy, GeoIP, Settings, HTTPS, Notifications, YAML Diff, Merge,
Trojan, Shadowsocks and UI Consistency all pass. Final extended UI suite adds
existing expanded Policy/Automatic Health/custom probe states: **140 checks**,
20 page states × 1440/1280/1024/768/430/390/360. After Runtime attribute ordering,
Settings browser was rechecked and PASS. The existing Preview suite retains
1200/1199/767 boundary checks.

Geometry asserts hierarchy rather than requiring all buttons to match. Within
each role, heights differ <=1px; every button text center is within 2px; padding
is wider horizontally; mobile buttons are >=40px. Secondary nav is shorter than
Main Nav. Active geometry does not shift. Input/select heights match <=1px.
Document scrollWidth == clientWidth at every width/state; local Diff scroll is
allowed and rendered Diff equals JSON exactly. Font and reviewed English copy
checks remain; user data/YAML group names are exempt.

Focus-visible outlines, keyboard Tab, native confirms, modal Escape/focus restore,
labels, disabled controls, current section/page and no-JS Settings anchors PASS.
All eight special-group options retain visible English labels and original form
values. core/ui.py remains the small display adapter; longest-first compound and
indexed error translations pass existing tests, with no global translator added.

## Business/output and static gates

| Gate | Result |
| --- | --- |
| VMess / VLESS / Trojan / Shadowsocks | PASS: full parser/import/privacy/browser regression |
| Replace golden / Merge golden | PASS: pinned prechange mapping and YAML bytes |
| Diff exact | PASS: exact subsequent Generate response bytes and browser JSON/text parity |
| Fixed / Sources / Refresh / Health / Policy / GeoIP | PASS: full pytest and disposable browser suites |
| Settings / HTTPS / Notifications / Auth / temporary links | PASS: full pytest and controlled browser suites |
| Original form attributes/order | PASS: input/select/textarea/button/form/option/link/label attributes versus START, excluding classes |
| Backend and business JS freeze | PASS: app.py/core/scripts/defaults/VERSION unchanged; JS diff is one class |
| Default YAML SHA | `a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b` |
| 10,410 rules round trip | PASS: independent real-default round trip, 1 passed in 0.95s |
| Golden subset | PASS: 6 pinned prechange/default tests |
| compileall | PASS: app.py/core/scripts/tests |
| Python 3.10 syntax | PASS: 101 files parsed using 3.10 AST grammar |
| Node syntax | PASS: 22 JS/CJS files |
| pip check | PASS: no broken requirements |
| bash -n / ShellCheck 0.11.0 | PASS: all 8 required shell entrypoints |
| Bootstrap synchronization | PASS: build_bootstraps.py --check |
| git diff --check | PASS |

The shared CSS replaces old density tokens in place and consolidates table/alert
rules; it does not stack page-specific compact overrides. No !important or inline
style was added. CSS total changes **18,961 → 20,776 bytes** (+1,815 bytes); gzip
estimate **4,551 → 5,011 bytes** (+460 bytes). This is local compression evidence,
not a network latency benchmark. Asset/request count and dependencies are unchanged.

## Publication and limits

Main is committed and pushed; delivery records exact local/origin/actual remote
SHA and a clean worktree. Local and remote tag-object lists and GitHub Release
metadata match START snapshots. README/VERSION still report v1.3.0 / 1.3.0.
Unreleased Changed/Fixed notes contain this work; no v1.3.1 section was created.

Validation uses Chromium in a disposable loopback Flask harness, synthetic nodes,
cached existing Bootstrap and controlled providers. No real VPS UI or systemd,
live Mihomo forwarding, public HTTPS, DNS, Telegram delivery or deployment update
was run. Python runtime was 3.12; 3.10 compatibility is syntax-only. Other browser
engines, operating-system font rendering and physical touch remain unverified.
The UI candidate is ready for the user's real VPS main-channel visual acceptance;
this report does not authorize or perform a stable release.

VERSION: 1.3.0
LATEST STABLE: v1.3.0
TAG CREATED: NO
RELEASE CREATED: NO

REAL VPS UI DENSITY: NOT RUN

V1.3.1 UI READINESS:
READY
