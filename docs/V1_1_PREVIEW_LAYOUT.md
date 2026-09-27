# Parse Preview responsive layout (unreleased main)

## A. Real VPS/browser issue
On Windows, the four-node example parsed correctly: **4 nodes / 3 ready /
1 warning / 0 errors**. The UNKNOWN row's longer warning squeezed Name/Country
and stretched Apply Edit. This is a presentation fix; parser behavior is unchanged.

## B. Root cause
Each preview row independently sized its Info and Action tracks with `auto`.
Long information competed with the flexible input tracks, and default Grid
stretch enlarged the action vertically. The four existing DOM children now have
semantic area classes; their order, labels, ARIA attributes and events are intact.

## C. Desktop ≥1200px
Areas are `name country info action`, with column minima 180/280/220px, flexible
ratios 1/1.35/0.9 and a max-content action track. These fit the existing 1160px
page shell and panel padding. All items align at the top; the button aligns to
the start and stays on one line at its normal height.

## D. Tablet 768–1199px
Two columns: `name country` above `info action`. Input columns use zero-minimum
flexible tracks at 1/1.35, so controls remain inside the available panel width.

## E. Mobile <768px
One column in DOM order: Name → Country → Info → Action. Controls fit the column;
Apply Edit takes its full width. Keyboard focus and activation remain native.

## F. Warning wrapping
Grid children have min-width zero; Info uses overflow-wrap anywhere. Neither the
reported sentence nor a 400-character unbroken warning changes input/action
widths or stretches the button. There are no UNKNOWN-specific style overrides.

## G. Windows flag rendering
Regional-indicator emoji rendering depends on the platform/font combination;
the operator's Windows glyphs were not independently inspected here. Labels and
fonts are unchanged. Browser tests also replace flag indicators with letters to
check layout under that fallback representation. No images, fonts or emoji
library were added. Actual Windows/VPS appearance remains an operator check.

## H. Automated browser verification
Baseline: **368 passed**. Final pytest: **370 passed in 109.07s**, including two
new layout/DOM contract tests. All **seven browser viewport cases pass**.
The opt-in real Chromium test uses the operator's exact four-node data against a
temporary Flask copy and real endpoints, with disposable credentials/runtime.

Viewports: **1440×900, 1024×768, 390×844**, plus **1200, 1199, 768 and 767px**
breakpoint boundaries. Assertions use bounding boxes, computed styles and
scrollWidth, not pixel-perfect screenshot comparisons. Checks cover consistent
Ready/Warning columns, minima, top alignment, normal button height, no page/row
overflow, long-word wrapping, mobile reading order, keyboard Apply Edit, ISO /
English / Chinese search, Enter protection, country/name overrides, Add/DEL,
Generate and draft restoration. The three main viewport screenshots were also
visually inspected; they include the simulated letter-form flag fallback.

To rerun with the project's Python dependencies and Node Playwright/Chromium
available (`NODE_PATH` may point to an existing Playwright installation):

```bash
python tests/run_preview_browser.py
```

Optionally set `BOOTSTRAP_CSS_PATH` to a local copy of the existing Bootstrap
5.3.3 stylesheet to avoid CDN variability. Set `PREVIEW_SCREENSHOT_DIR` to an
existing directory to save inspection images. The runner stops its loopback
server and deletes its temporary runtime after completion.

No backend, requirements, deployment, draft schema or submit/CSRF logic changes.
VERSION remains **1.0.2**, Latest Stable **v1.0.2**; no tag/Release. Default YAML
remains byte-identical with **10,410 rules** and full round-trip coverage.
Python/Node syntax, six shell scripts' bash -n, ShellCheck 0.11.0, dependency
consistency, public-document email exclusion and git diff --check all pass.
