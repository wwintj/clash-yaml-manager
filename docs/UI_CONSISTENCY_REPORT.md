# v1.3.1 UI consistency readiness report

Audit date: 2026-10-02. Development on main only; this is not a release.

START HEAD: `9d10ac6253facb351604538cad808ef87ed5a825`

IMPLEMENTATION HEAD: `52243949d9bb6903fa4e2f93fc26c9b2e1f0c7fc`

END HEAD is the following documentation-only commit adding this report. Resolve
its exact SHA with `git log -1 --format=%H -- docs/UI_CONSISTENCY_REPORT.md`.
The delivery report records the exact final local/origin/remote SHA after push.

Commits: `style: unify English UI typography controls and responsive layouts`,
then `docs: record v1.3.1 UI consistency validation`.

## Scope and design

UI LANGUAGE: ENGLISH.

The [UI consistency contract](UI_CONSISTENCY.md) documents the full design.
System fonts replace mixed heading/button fonts; monospace remains on code,
YAML/diff, URI and technical values. Body is 16px, help/labels/buttons 14px,
badges 12px, page titles 24px, sections 20px and subsections 18px. Line heights
are 1.25/1.5; buttons have no excess tracking. Spacing is 4/8/12/16/24/32/48px.

Buttons share inline-flex centering and primary/secondary/outline/danger styles;
ordinary controls/nav are 44px, utility actions 36px and large actions 48px.
Input/select/file controls share height, padding and border. Textareas keep a
larger minimum height. Cards share the surface/border/radius and 32/24/16px
responsive padding. Raised status cards use 16px. Alerts, badges, tables,
password dialogs and local code scrolling use the same palette and spacing.

The shell is centered with a 1200px maximum and >=16px mobile horizontal
padding. Both navigation groups wrap at narrow widths, keep content-dependent
width and mark their active item. The mobile header uses two status columns;
Preview retains four columns >=1200, two at 768–1199 and one below 768.

The small legacy-message adapter changes display only: Jinja HTML and browser
Parse/Diff text are English; parser/JSON/CLI messages and generated values are
preserved. Only Generate/Fixed editing receives the browser phrase data.
Country search aliases stay multilingual; option labels are English. All eight
Policy options remain labelled, with their original submitted/YAML values.

## Pages and visual audit

Audited Login and failed login; Generate inputs, parsed preview, errors,
unknown-country warning, success/result, temporary link, draft and confirmations;
Full YAML Diff; Fixed empty/populated list, create/edit, remote/uploaded source
editor, policy controls, Endpoint/Full Proxy Health; Settings Overview, GeoIP,
Health, Runtime/HTTPS and Notifications; main/secondary navigation; and password
modal keyboard behavior. All live routes inherit the shared UI. The two archived
unrouted templates are not alternative application interfaces.

Mandatory screenshots: Login, Generate, Generate parsed, Diff, Fixed list,
Fixed edit, Settings Overview, Runtime and Notifications at 1440 and 390px:
**18/18 saved and actually visually inspected**. Additional source/health,
GeoIP, result, navigation, modal and full-page/detail screenshots were inspected.
102 PNG artifacts include full-page/viewport/detail captures and a review crop;
these use synthetic disposable data only. Tall mobile pages were also inspected
through readable section details, not just compressed whole-page thumbnails.

Local evidence root:
`/Users/t/.codex/artifacts/clash-yaml-manager/v1.3.1-ui/`

- `screenshots/geometry.json`: all 133 live page/width measurements.
- `screenshots/{page}-{1440,390}.png`, `*-detail.png`, `*-full.png`: retained visuals.
- `performance.json`: isolated before/after payload measurement.
- `final-report.md`: final exact SHA, push and stable-boundary verification.

## Controlled validation

BASELINE PYTEST: **2658 passed in 365.64s**, before any repository edits.

FINAL PYTEST: **2668 passed in 353.99s**, **0 failed**. Ten display-boundary
regressions were added; original coverage was retained when HTML text assertions
were adapted to English. Final display/collision subset: **15 passed**.
Independent real-default round trip: **1 passed**.

Browser suites: **16/16 PASS**. Existing Preview, Fixed, External, Endpoint,
Proxy, Policy, Health-aware Policy, GeoIP, Settings, HTTPS, Notifications,
YAML Diff, Merge, Trojan and Shadowsocks suites all pass. New UI Consistency
suite passes **133 checks** (19 live page states at each of seven widths), with
final screenshot/label refinements rechecked in the same isolated harness.

| Width | Result | Page states | Navigation heights | Page overflow |
| --- | --- | --- | --- | --- |
| 1440 | PASS | 19 | 44px | 0px |
| 1280 | PASS | 19 | 44px | 0px |
| 1024 | PASS | 19 | 44px | 0px |
| 768 | PASS | 19 | 44px | 0px |
| 430 | PASS | 19 | 44px | 0px |
| 390 | PASS | 19 | 44px | 0px |
| 360 | PASS | 19 | 44px | 0px |

Existing Preview breakpoint checks at 1200, 1199 and 767 also PASS.
Both navigation groups differ in height by <=1px; inputs/selects differ by
<=1px; button text centers are within 2px of their containers. Long controls
remain visible; Diff scrolls internally and its displayed bytes equal the JSON
response. Tests audit known UI copy rather than banning CJK in user/YAML data.

| Gate | Result |
| --- | --- |
| Horizontal overflow | PASS: document scrollWidth <= clientWidth at all target widths |
| Font consistency | PASS: computed system font matches across ordinary UI; explicit technical monospace exceptions |
| Language consistency | PASS: English labels/help/status/errors; user data and YAML names untouched |
| Accessibility | PASS: labelled controls, visible focus, keyboard modal close/focus restoration, active aria state, disabled controls, native confirmation dismissal, no-JS form/anchor navigation |
| Business logic regression | PASS: existing protocol, Fixed, sources, refresh, health, policy, GeoIP, notification, HTTPS, auth and temporary-link coverage retained |
| Replace golden | PASS: legacy parser AST/goldens and exact rich/default output tests |
| Merge golden | PASS: preserved fixtures, collisions and exact generated/downloaded output |
| Diff exact | PASS: default/custom/Replace/Merge/protocol tests and browser DOM text equals response |
| Security | PASS: auth/CSRF, Jinja autoescape, textContent, private warning suppression, credential redaction; no unsafe innerHTML introduced |
| Python syntax | PASS: compileall app.py/core/scripts/tests; Python 3.10 AST parsing of 101 files |
| Node syntax | PASS: 22 JS/CJS files |
| Dependencies | PASS: pip check; no added runtime dependency |
| Shell syntax | PASS: bash -n for all eight lifecycle/deployment shell files |
| ShellCheck | PASS: 0.11.0, all eight shell files |
| Bootstrap synchronization | PASS: scripts/build_bootstraps.py --check |
| Diff hygiene | PASS: git diff --check |

Palette contrast on the main card surface: ordinary text 14.10:1, help text
7.22:1, danger text 7.70:1; primary-button text 10.17:1. Focus indicators are
visible. These checks do not constitute a full assistive-device certification.

Default YAML SHA-256:
`a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b`

10,410-rule round trip: **PASS**. Default bytes, non-node YAML fields and proxy
reference validation are preserved. Business modules, fixtures, VERSION and
lifecycle entrypoints remain unchanged; app.py only registers the display
adapter and translates the existing plain HTML error message.

## Performance and limits

No web font, new external request, runtime dependency or business request was
added. Two small local shared assets replace the inline style and supply display/
active-anchor behavior; they can be cached. Isolated Generate HTML decreases by
about 6KB; first-visit HTML plus shared assets increases by about 10KB (roughly
6%). The payload measurement uses a fixed synthetic render rather than a network
latency benchmark. Existing Bootstrap version/CDN URLs remain unchanged; browser
checks use cached pinned CSS and the actual bundle.

Validation is controlled Chromium on this workstation. Python runtime is 3.12;
3.10 compatibility was syntax-checked locally. No real VPS update, systemd,
Telegram, public HTTPS, GeoIP download or live proxy operation was performed.
Native confirm/file-picker copy and system-font rendering can depend on the
browser/OS locale. Application-owned UI copy is English. User-authored names,
configuration, aliases and historical YAML strategy names can contain any
language. No unresolved UI blocker was found in the controlled audit.

VERSION: 1.3.0

LATEST STABLE: v1.3.0

TAG CREATED: NO

RELEASE CREATED: NO

REAL VPS UI CONSISTENCY: NOT RUN

V1.3.1 UI READINESS: READY
