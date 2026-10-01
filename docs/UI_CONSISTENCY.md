# Web UI consistency contract

UI LANGUAGE: ENGLISH. This is main development work for a future patch; VERSION
and Latest Stable remain 1.3.0 / v1.3.0. No new product capability is introduced.

## Audit and scope

All routed pages inherit `index.html`. The former inline stylesheet supplied a
dark palette but mixed proportional/monospace headings, excessive tracking,
46px buttons with Bootstrap padding, and unrelated card/mobile spacing. Fixed
and Settings extended that stylesheet. Navigation and most product labels were
already English; Generate help, authentication copy and legacy validation errors
were mixed. English is the smallest coherent change.

The shared stylesheet extends the existing palette and retains Preview grid
areas and breakpoints. Historical `index-cn.html` / `index-backup.html` are not
routed or included by any live template; they are archival, not alternate UIs.

## Tokens and components

| Role | Contract |
| --- | --- |
| Font | Local system sans stack for body, headings, labels, navigation, buttons, controls, badges and status. System monospace only for code, YAML, diff, URI and technical values. No font downloads. |
| Typography | xs 12px, sm 14px, base 16px, lg 20px, xl 24px; tight 1.25, normal 1.5. Page title 24/600, section 20/600, subsection 18/600, card 16/600, body 16/400, help 14/400, label/button 14/600, badge 12/600. Minimal heading tracking; none on controls. |
| Spacing | 4, 8, 12, 16, 24, 32, 48px through shared tokens. Form groups/sections use 24px; heading-to-content 16px; labels-to-controls and action gaps 8px. |
| Buttons | Primary green, secondary raised, outline, danger, navigation/tab and small utility share inline-flex centering, font, radius and states. Ordinary/nav 44px, utility 36px, large 48px; horizontal padding 16px. Width follows content, with deliberate full-width actions where already used. |
| Forms | Text/password/search/number/URL/file inputs and selects 44px; textarea uses shared font and padding with a larger minimum height. Technical input classes opt into monospace. Nested labels and standalone labels share typography. Check/radio controls retain visible keyboard focus and native semantics. |
| Cards | Dark surface, one border, 6px radius, 32px padding desktop / 24px tablet / 16px mobile. Raised inner status cards use 16px padding. Nested form panels use the same tokens. |
| Alerts/badges | Shared text, padding, border and radius; success/warning/danger/info colors from the palette. Status text wraps safely. Disabled controls are visibly distinct. |
| Navigation | Main nav and Settings links share one class and 44px height. Content-dependent width, wrapping on narrow screens, aria-current and visible active/focus styles. Settings hashes retain ordinary no-JS anchor navigation; JS only marks the active section. |
| Code/tables | Monospace diff/code with 14px/1.5 typography and internal scrolling. Tables share cell rhythm and live in inner scrollers; existing mobile row cards remain. |
| Dialogs | Existing password modal retains Bootstrap behavior, shared surface/border/padding and action controls; 16px mobile safe margin. Native confirm dialogs keep browser keyboard behavior. |

## Responsive and accessibility rules

One 1200px maximum shell, centered, 24px horizontal padding desktop and at least
16px on mobile. Header/actions wrap; cards and controls shrink within their grid.
Preview stays four columns at >=1200, two at 768–1199, one below 768; long warnings
wrap inside their own region. No page-level horizontal clipping is used to hide
overflow. Code and table scrolling is local. Validate at 1440, 1280, 1024, 768,
430, 390 and 360; retain the existing 1200/1199/767 breakpoint regression suite.

Focus-visible outlines are retained across links/buttons/controls. Form labels
either wrap their control or use explicit associations/accessible names, including
cloned auxiliary rows. Status regions keep live announcements and buttons keep
their existing submit/type/form semantics. Reduced-motion preferences suppress
decorative transitions.

## Message and data boundary

`core/ui.py` is a small reviewed legacy-message display adapter, shared by Jinja
and the existing Parse/Diff frontend. It is not a locale framework: no language
selection, routing, catalog files or persistence. Parser/JSON/CLI messages stay
unchanged; only their displayed safe phrases are English. Jinja autoescaping and
JS textContent remain authoritative. User data is never passed through the
adapter. Country option labels use English, while search aliases still support
all existing languages. Special-group checkboxes have English labels but retain
their original YAML/form values. Generated YAML, diff bytes, node names, password
characters, routes, state, tokens, schedulers and network behavior are unchanged.

## Controlled browser reproduction

Use the existing disposable `tests/run_preview_browser.py` harness with Node,
Playwright and Chromium available. Supply cached copies of the existing pinned
Bootstrap 5.3.3 CSS and bundle through `BOOTSTRAP_CSS_PATH` and
`BOOTSTRAP_JS_PATH`; the UI suite uses the real bundle for keyboard/modal checks.
Set `UI_ARTIFACT_DIR` to retain screenshots and `geometry.json` outside runtime
state. Run all suites, or `--suite ui_consistency` for the full UI matrix. Fixture
controls remain loopback-only and never change production network policy.
