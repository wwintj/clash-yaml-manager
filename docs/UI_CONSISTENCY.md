# Web UI consistency contract

UI LANGUAGE: ENGLISH. This contract records the two UI refinement passes.
VERSION is the version source; README Latest Stable identifies the published
release. No new business capability is introduced by these presentation changes.

v1.7.0 Phase 1 的登入介面精修：僅未登入頁面使用 login 專用 flex 排版、400px 卡片與置中的 `Clash YAML Manager` 標題，移除 terminal dashboard 式標記、分隔線及多餘提示。欄位為 `Password`／`Enter password`，按鈕為 `Sign in`（沿用 44px primary control）；保留 `password` form contract、autofocus、`autocomplete="current-password"`、CSRF hidden input，以及經 `ui_message` 處理的 alert／status 訊息。CSRF notice 在登入卡片內顯示，共用動態版本 footer 不變。未修改共用 component 定義、登入後介面或認證行為；正式發布狀態以 README Latest Stable 為準。

v1.7.0 Phase 2 僅精修登入後的 chrome：語義化 `header.app-header` 第一列保留唯一 h1 `Clash YAML Manager`、utility role 的 `Change Password` 與帶 CSRF 的 POST `Logout`，第二列整合 `nav[aria-label="Main navigation"]`。移除靜態 Service／ONLINE、Mode／YAML、Parser／protocol list、Backend／FLASK 與 `YAML NODE MANAGEMENT`，不移動到其他頁面。Desktop title 左、actions 右；Mobile title 獨立一列，actions 與 content-width 導覽自然 wrap，保留 href、aria-current、active geometry 及 focus-visible。Login、authenticated alerts、workspace、Settings 內容、modal 與 backend 均不變。

v1.7.0 Phase 3 僅精簡登入後的全域 feedback：沿用 `.terminal-alert` 與原 error／success 顏色，移除 `ERROR LOG`／`SUCCESS` 呈現標題。單條錯誤使用段落，多條使用同一 alert 內的清單；成功訊息直接顯示。保留 `error_messages`／`success_message`、`ui_message`、Jinja autoescape，以及容器的 `role="alert"`／`role="status"`，不逐條新增 role，不新增 icon、toast、animation 或 auto-dismiss。`Generation Complete`、`Temporary Link`、`YAML Changes`、`Generate Result` 等 contextual headings、登入頁、Phase 2 header 與 backend 均不變；正式發布狀態以 README Latest Stable 為準。

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
| Typography | xs 12px, sm 14px, base 16px, lg 20px, xl 24px; tight 1.25, normal 1.5. Page title 24/600, section 20/600, subsection 18/600, card 16/600, body 16/400, help 14/400, label/button 14/600, badge 12/600. No heading/control tracking. Primary actions retain 600 weight; navigation and ordinary/utility actions use 500. |
| Spacing | 4, 8, 12, 16, 24, 32, 48px through shared tokens. Form groups use 16px; sections 24px; heading-to-content 16px; labels-to-controls 8px, input-to-help 4px, action gaps 8px. |
| Buttons | Primary green, secondary raised, outline, danger, navigation/tab and small utility share inline-flex centering, font, radius and states. Distinct role tokens control height: standard/main nav 40px, tabs 36px, primary 44px, utility 32px on desktop. Horizontal padding 12/16/20px, vertical CSS padding 4px; fixed/minimum height and flex centering control vertical geometry. Width follows content; Login remains deliberately full width. |
| Forms | Text/password/search/number/URL/file inputs and selects 40px desktop / 44px mobile; textarea uses shared font and padding with a larger minimum height. Technical input classes opt into monospace. Nested labels and standalone labels share typography. Check/radio controls retain visible keyboard focus and native semantics. |
| Cards | Dark surface, one border, 6px radius, 24px padding desktop / 20px tablet / 16px mobile. Raised/nested panels use 16px desktop / 12px mobile, avoiding repeated outer padding. Login retains 24px vertical breathing room. |
| Alerts/badges | Alerts use 12px vertical / 16px horizontal padding; badges use 2px / 8px. Shared text, border and radius; success/warning/danger/info colors from the palette. Status text wraps safely. Disabled controls are visibly distinct. |
| Navigation | Main nav and Settings links share design primitives with distinct 40/36px desktop and 42/40px mobile heights. Main/secondary gaps are 6/4px. Inactive links have light transparent borders; active tint/border never changes geometry. Content-dependent width, wrapping on narrow screens, aria-current and visible active/focus styles. Settings hashes retain ordinary no-JS anchor navigation; JS only marks the active section. |
| Code/tables | Monospace diff/code with 14px/1.5 typography and internal scrolling. Tables share 8px vertical / 12px horizontal cell padding and code uses 12px internal padding. Tables share cell rhythm and live in inner scrollers; existing mobile row cards remain. |
| Dialogs | Existing password modal retains Bootstrap behavior, shared surface/border/padding and action controls; 16px mobile safe margin. Native confirm dialogs keep browser keyboard behavior. |

## Density hierarchy — second pass

PAGE SPACING != CONTROL SPACING. The shell retains 24px desktop / 16px mobile
horizontal breathing room; compact controls do not collapse page margins.
**Horizontal padding is intentionally larger than vertical visual spacing.**
Buttons use inline-flex centering and role heights, never large padding-block.

| Role | Desktop / tablet | Mobile <=575px | Horizontal / vertical CSS padding |
| --- | --- | --- | --- |
| Main navigation | 40px, 6px gap | 42px, 6px gap; wrap | 16 / 4px |
| Secondary navigation | 36px, 4px gap | 40px, 4px gap; wrap | 12 / 4px |
| Primary action | 44px, weight 600 | 44px | 20 / 4px |
| Standard action | 40px, weight 500 | 44px | 16 / 4px |
| Utility / destructive utility | 32px, weight 500 | 40px | 12 / 4px |
| Input/select/file | 40px | 44px | 12 / 4px; select reserves arrow space |
| Textarea | >=192px, content/rows determine height | Same | 12 / 8px |
| Card | 24px; 20px <=900px | 16px | Independent from control padding |
| Nested panel/status | 16px | 12px | One inner layer, not another full card |
| Status checkbox / event row | 40 / 32px minimum | 44 / 40px minimum | 8px label gap |

Tokens in `static/ui.css` are authoritative: `--nav-height-main`,
`--nav-height-secondary`, `--control-height-primary/standard/utility`,
`--padding-control-x/y`, `--padding-card`, `--padding-panel-small`, and
`--gap-control/group/section`. Responsive tokens change once at shared
breakpoints; pages select component roles rather than defining private sizes.

Form groups use 16px; label-to-control 8px; help follows inputs at 4px; sections
use 24px. Nested Policy/source panels, Health summaries and metadata rows are
compact, while textarea editing space and Login remain comfortable. Generate,
Save/Create and Download remain prominent; Copy/Refresh/Remove/Test/Apply
are utilities. The Fixed overview uses standard Edit and utility state/link/delete
actions, as specified in [Fixed UX](FIXED_SUBSCRIPTIONS_UX.md). Destructive color does not imply a larger size. Generate and
result actions follow content width and wrap. The existing Preview mobile Apply
button intentionally follows the row width.

The second-pass measurements, screenshots, validation and limitations are in
[UI density refinement report](UI_DENSITY_REFINEMENT_REPORT.md). The original
[UI consistency report](UI_CONSISTENCY_REPORT.md) remains historical evidence.

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

UI consistency 與 Fixed UX 截圖對既有 subscription／temporary URL 欄位加上 capture mask，避免將 bearer URL 留在驗證圖片；遮罩不修改頁面或影響版面量測。

`--suite login` 沿用同一 disposable Flask harness，驗證 320×568、375×667、390×844、768×1024、1440×900、1920×1080 的登入與訊息版面、autofocus、Enter、Tab／Shift+Tab、focus-visible，以及實際 wrong-password、CSRF、rate-limit 與 Change Password 成功回到登入頁的路徑。另以半 CSS viewport／雙 pixel density 檢查 200% 桌面 zoom 的 reflow 等效情境；這不是瀏覽器原生 zoom 設定驗證。截圖與 `login-geometry.json` 存於 `UI_ARTIFACT_DIR`，不含 fixture 密碼或 session secrets。

`--suite header` 驗證 Generate／Fixed／Settings 三個頁面的 scoped header contract、唯一 h1、整合導覽與 active state，涵蓋 320×568、375×667、390×844、768×1024、1024×768、1440×900、1920×1080。檢查 title／actions 不互相擠壓、link text 不裁切、modal Enter／Tab／Escape 與 focus return、Logout POST＋CSRF，以及 page overflow；截圖沿用 bearer URL capture mask，量測保存於 `header-geometry.json`。

`--suite feedback` 透過實際 Generate／Delete Temp Files 表單驗證單條錯誤、多條 parser 錯誤、成功清理訊息與原 contextual result headings，涵蓋 1440×900、390×844、320×568；另使用 inert rendered-HTML fixture 檢查長訊息與已 escaped markup 的換行／溢出，server escaping 由 Flask／Jinja 邊界測試驗證。確認訊息維持顯示，重新載入後仍遵循原有 server 一次性 notice 行為。截圖遮罩 bearer URL 與節點輸入，量測保存於 `feedback-geometry.json`。
