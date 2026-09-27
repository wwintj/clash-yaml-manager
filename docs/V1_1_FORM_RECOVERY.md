# Generate-only submission and CSRF recovery (unreleased main)

VERSION stays **1.0.2**, Latest Stable stays **v1.0.2**. No version bump, tag or
Release is part of this work. Gunicorn, requirements, deployment scripts,
readiness checks and installation metadata are unchanged.

## A. Real browser reproduction

The operator's VPS was running `1.0.2-dev+0cf44e2`. The preceding Gunicorn and
readiness fixes passed VPS acceptance. Draft restoration also passed: after a
CSRF failure and login, the original browser draft returned.

The new reported sequence was Auxiliary Multi Nodes → country search → Enter →
unexpected POST /process → stale CSRF error page. This repair targets that
interaction and recovery behavior, without replacing the draft implementation.

## B. Root cause: implicit form submission

Country search inputs live inside process-form. Native form behavior can submit
the default submit button when Enter is pressed in a text/search input. The old
nodes.js submit handler accepted every submit event, saved/serialized inputs and
showed the generation overlay without checking the submitter. Its country-search
input handler only filtered options; it did not suppress the Enter default.

The old CSRFError handler rendered index.html directly with status 400 and an
error message. An anonymous or invalidated session therefore saw a login error
page, while an authenticated session could remain on an error response at /process.

## C. Why Country Search Enter must not submit

Search is only a country filter. A delegated keydown listener on process-form
cancels Enter's default for ordinary input controls, covering auxiliary rows,
restored/new rows, preview country searches and preview name editors. It does
not clear the search text, parse nodes or show the progress overlay. Other keys,
country selection and textarea newlines retain their normal behavior.

The listener is scoped to this form. Login and password-change forms keep their
Enter behavior. Button keyboard activation remains available.

## D. Explicit Generate-only rule

The Generate button has id `generate-yaml`, name `action`, value `generate` and
type submit. The submit handler first requires `event.submitter` to be that exact
button. Null/absent/other submitters are cancelled before serialization, custom
file validation or progress display. No persistent click flag is used, so a
cancelled attempt cannot poison subsequent generation or back/forward navigation.

Clicking Generate, keyboard activation of that button, and
`form.requestSubmit(generateButton)` follow the existing saveDraft → serialize →
custom YAML check → progress → POST flow. Enter key cancellation is necessary in
addition to the submitter guard, because a browser's implicit submission can name
the default Generate button as its submitter.

Parse, Add Row, DEL, Apply Edit and Clear Draft remain type button. Parse and Apply
Edit use /parse-nodes only. Null submitters fail closed on browsers without the
standard SubmitEvent identity rather than authorizing unknown submissions.

## E. CSRF recovery UX

Flask-WTF still rejects missing, invalid and expired tokens before route execution.
The handler removes the old session token seed, stores only a fixed one-time
notice, and returns **303 to GET /** for browser forms. GET generates a new token
and consumes the notice. No rejected POST is replayed or saved in the session.

- Logged in: stay logged in, show the editor and a quiet role=status notice:
  “安全令牌已刷新，请重试；如有草稿，将自动恢复。”
- Logged out or authentication invalidated: show login and
  “请重新登录；如有草稿，将在登录后自动恢复。”
- Login's own invalid/expired token follows the same one-redirect flow; submitting
  the refreshed login form works. Passwords are not saved or restored.
- /parse-nodes returns **400 JSON**, code `csrf_failed`, with a refresh/login
  instruction. The existing fetch error display handles it without navigating,
  generating YAML or replaying the request. The message does not assume a draft
  exists. Existing redirected/non-JSON response handling remains compatible.

The HTML 400 CSRF error page is removed. The API's 400 is deliberate and contains
no HTML login/error page. The CSRF lifetime is not disabled or extended, no route
is exempted, and CSRFProtect remains enabled. Existing Flask-WTF logs contain
reason categories only; no form body, node URI, UUID or password is added to logs.

## F. Effective CSRF lifetime/config

Inspected the installed **Flask-WTF 1.3.0** source (`CSRFProtect.init_app` and
`validate_csrf`) and asserted the initialized Flask config in tests:

| Setting | Effective value |
| --- | --- |
| WTF_CSRF_TIME_LIMIT | 3600 seconds (one hour), existing package default |
| WTF_CSRF_ENABLED / WTF_CSRF_CHECK_DEFAULT | True / True |
| PERMANENT_SESSION_LIFETIME | 30 days |
| SESSION_REFRESH_EACH_REQUEST | True |

These are separate clocks. A logged-in page can outlive its CSRF token. Keeping
the finite one-hour token lifetime with predictable refresh/retry handles that
case without removing protection. Tests create correctly signed tokens aged
3601 seconds, not merely malformed strings, and prove fresh tokens validate.

## G. Draft preservation verification

static/draft.js is unchanged. The existing input/change listeners continue saving
ordinary and search input activity; the draft schema retains actual node values
and selected countries rather than transient search queries. Preview overrides
continue saving through the existing edit handler.

Generation retains its draft; CSRF recovery does not clear localStorage; login
pages do not overwrite it; returning to the editor restores it and displays
“Draft restored” only when a draft exists. Manual Clear Draft and the 30-day TTL
remain intact. No new storage path, password storage or server-side node-body
copy is introduced.

## H. Tests

- Clean baseline export at 0cf44e2: **357 passed in 104.87s**. Full updated suite:
  **368 passed in 107.53s**, on Python 3.12.14 / Flask-WTF 1.3.0, with no skips.
- Node regression exercises auxiliary/preview search and name/link Enter,
  prevention of the otherwise-implicit default, retained query text, textarea
  newlines, navigation keys, exact/null/absent/other submitters and repeated
  explicit generation. Static HTML checks ensure only Generate is a process
  submitter and all auxiliary actions retain type button.
- Backend tests cover invalid/missing/actually expired CSRF, authenticated and
  anonymous recovery, invalidated authentication, login without loops, new-token
  validity and one-time notices. Generation is replaced with a fail-fast sentinel;
  runtime file snapshots prove no rejected request creates YAML or link metadata.
  Session/log assertions exclude sensitive form input.
- Real headless Chromium against an isolated copy of the Flask application:
  auxiliary/restored/new-row and preview Enter, normal input Enter, textarea
  newline, Add/DEL/Apply/Parse, null/other submitters, real click and requestSubmit
  generation, CSRF redirect/token refresh, parse JSON recovery, logout/login draft
  restore, and confirmed manual clear all pass. The browser test uses temporary
  runtime files and a disposable test account, never the user's VPS or real data.
- Existing backend and Node tests retain coverage of draft expiry, sliding
  sessions, nodes/countries, links, authentication and deployment behavior.
- Python syntax, Node syntax, all six deployment shell scripts' bash -n,
  ShellCheck 0.11.0, pip check, public-document email exclusion and git diff --check
  pass. Default YAML remains byte-for-byte identical to v1.0.2; the 10,410-rule
  round-trip passes in the full suite.

## I. Remaining VPS/browser validation

Standard keydown/preventDefault and SubmitEvent.submitter are used, with no
Chromium-only API in the application. Chromium was exercised locally. Edge,
Safari (including mobile Search keys) and Firefox were considered in the design
but were not independently run here; validate the actual devices before release.

After this main commit is pushed:

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh | sudo bash -s -- --channel main
```

Enter JP in Auxiliary country search, press Enter/Search, and confirm no /process
or /parse-nodes request, no overlay and no navigation. Filtering and choosing
Japan must still work. Repeat in a newly added row and Parse Preview; verify
textarea Enter inserts a newline and Generate alone starts generation.

Then leave a page open beyond one hour: explicit Generate should recover through
GET with a new token, retain/restore any draft, and wait for another explicit
Generate. Repeat with Parse and an expired login page. The immutable v1.0.2
Release does not include these unreleased main changes.
