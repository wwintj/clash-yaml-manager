# Real VPS deployment fixes (unreleased main)

VERSION remains **1.0.2**. Latest Stable remains **v1.0.2**. This change is
main-only development work, with no new tag or Release. Installation metadata
continues to identify main as `1.0.2-dev+<commit>`; its schema and meaning are unchanged.

## A. Real VPS issue

The reported Ubuntu/systemd VPS upgraded to `1.0.2-dev+03ceed9` with Gunicorn
26.2.0, two workers and the dedicated `clashyaml` account. It eventually served
HTTP normally, but its journal contained `Control server error` / permission
denied for `/nonexistent`. An initial deployment curl connection refusal also
appeared before the completion messages.

These observations came from the operator. This development environment does
not have access to that VPS; the post-fix Ubuntu acceptance remains outstanding.

## B. Gunicorn control socket root cause

[Gunicorn 26.2.0 configuration](https://github.com/benoitc/gunicorn/blob/26.2.0/gunicorn/config.py)
selects `$XDG_RUNTIME_DIR/gunicorn.ctl`, or `$HOME/.gunicorn/gunicorn.ctl` when
XDG_RUNTIME_DIR is absent, and creates the parent directory. A nologin service
account with HOME `/nonexistent` cannot create that directory. This matches the
reported control-server error, separately from Gunicorn's working HTTP listener.

## C. Why --no-control-socket

The application does not use `gunicornc`. The shared unit generator in
`scripts/deploy-common.sh` now adds `--no-control-socket`. Both install and update
call this generator regardless of channel. User and Group remain `clashyaml`,
with UMask 0077, NoNewPrivileges, PrivateTmp and existing low-port capability
handling. No HOME override, directory creation at `/nonexistent`, permission
expansion or root worker is introduced.

## D. Gunicorn minimum version requirement

`requirements.txt` now requires `gunicorn>=25.1.0`. The flag was introduced in
[25.1.0](https://github.com/benoitc/gunicorn/blob/25.1.0/gunicorn/config.py).
That release requires [Python >=3.10](https://pypi.org/project/gunicorn/25.1.0/).
Its initial default socket path differed from 26.2.0; the HOME fallback described
above was verified against the version reported by the VPS.

Update already installs **the incoming source's** requirements into the deployed
venv and runs `pip check` before stopping the service or writing the new unit.
An old 21.x/22.x/23.x installation no longer satisfies the constraint. On an
unsupported Python interpreter, dependency installation fails before service
stop; the script does not replace the environment's Python interpreter.

A temporary Python 3.12 environment was actually downgraded to Gunicorn 23.0.0,
then `pip install -r requirements.txt` upgraded it to 26.2.0. The actual
`gunicorn --help` advertises the flag and its parser sets control_socket_disable.
The existing local Python 3.9 environment cannot install this dependency floor;
final verification uses Python 3.12 instead.

## E. Health check race

`systemctl restart` completing for a Type=simple service does not establish that
Flask workers can answer HTTP. An initial connection refusal must be retried.

Source inspection of 03ceed9 found **existing 15-attempt loops**, explicit failure
exits, and `subprocess.run(check=True)` in the remote dispatcher. A single curl
error followed by completion can therefore also mean that a later attempt
succeeded; the supplied output alone does not prove that all attempts failed or
that the old dispatcher swallowed an error. The exact VPS sequence is not
reproduced here. The previous check also used `/` and accepted curl-successful
redirects. This fix makes readiness, retries and failure outcomes explicit and
adds regression coverage for the operator's required behavior.

## F. Retry strategy

Both lifecycle scripts call `wait_for_application` from the shared helper after
restart. Default readiness budget: **30 seconds**, up to 30 attempts, **one second
between attempts**. Bash's elapsed SECONDS clock sets one deadline; slow HTTP
attempts consume that same budget. Each curl has connect/total timeouts of at
most two seconds, reduced to the remaining budget. A response after the deadline
cannot pass. Normal command/scheduling overhead and final diagnostic output are
outside this approximate readiness budget.

Success requires curl exit zero, exactly HTTP 200 from
`http://127.0.0.1:${APP_PORT}/healthz`, and `systemctl is-active --quiet` success.
The check bypasses outbound HTTP proxies and does not follow redirects. Expected
curl stderr is suppressed; attempts print `not ready` or `PASS`.

Public GET `/healthz` returns only `OK\n`, text/plain, with Cache-Control no-store.
It skips session invalidation and file cleanup, performs no authentication/state
read and needs no CSRF token. It proves that Flask loaded and can handle a
request; it does not claim to test every feature or worker.

## G. Failure behavior

Failure prints `Health check FAILED`, runs and displays:

```bash
systemctl status clash-yaml-manager --no-pager -l
journalctl -u clash-yaml-manager -n 50 --no-pager
```

The helper returns 1 even if diagnostics fail. Install exits nonzero without its
success message. Update retains its existing backup directory, prints its path
and manual rollback guidance, then exits nonzero without `升级完成`.
The existing remote Python dispatcher propagates the child failure through the
standalone shell entrypoint and never reaches `Update complete`.

No automatic rollback was present; none is added. Failure can leave the incoming
code, venv and metadata installed but unhealthy. Keep the backup and follow the
existing coordinated manual rollback instructions; do not rerun install.

## H. Tests

- Baseline: **335 passed**. Final full suite: **357 passed in 106.13s**, using
  Python 3.12.14 and Gunicorn 26.2.0, with no failures or skips.
- Generated install/update units retain the dedicated account and hardening and
  contain the disable flag; the requirement excludes incompatible old versions.
- Real temporary-environment dependency upgrade: **23.0.0 → 26.2.0**; `pip check`
  and actual Gunicorn CLI/config parser validation pass.
- Immediate readiness, first failure then success, two refusals then third-attempt
  success, five failures then success, and stable/main source metadata coverage.
- All attempts fail, inactive systemd, HTTP unavailable, HTTP 500, redirect,
  curl timeout and a late HTTP 200 after the deadline all fail without success.
- Fresh install and update share the same retry helper. Failure diagnostics,
  backup retention and rollback messages are asserted.
- Both generated remote-update channel paths are executed via stdin with fake
  downloads and a failing child; nonzero status and absence of false completion
  are asserted. Remote lifecycle source and generated entrypoints need no change.
- Anonymous and stale-session `/healthz` calls return only the constant response,
  even when authentication/state reads and cleanup are made unavailable.
- Local process smoke: actual Gunicorn 26.2.0, two workers, HOME `/nonexistent`,
  XDG_RUNTIME_DIR unset, isolated application copy and runtime files, real loopback
  HTTP 200. No control socket or control-server error appeared; processes stopped
  afterward. This uses the macOS developer account, not systemd or the VPS user.
- Full existing feature coverage includes drafts, 30-day sessions, mixed node
  parsing, 249 countries, Unknown warnings, temporary and legacy links, AuthStore,
  rate limits, invalidation, and stable/main selection and downgrade rules.
- Python syntax, all six shell scripts' `bash -n`, ShellCheck 0.11.0, dependency
  consistency, bootstrap synchronization, email exclusion and diff checks pass.
- Default YAML is byte-for-byte identical to v1.0.2, with 10,410 rules. SHA-256:
  `a30bd14fd5b5873d8eaa6c56e3205ddcf8fc39f4efa30675fdb88c8cec9ecf9b`.
  The full YAML round-trip regression remains part of pytest.

## I. Remaining real VPS validation

After main is pushed, rerun on the test VPS:

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh | sudo bash -s -- --channel main
```

Confirm the old main SHA becomes the new commit, readiness PASS precedes both
completion messages, `/healthz` returns HTTP 200, and the generated unit contains
the disable flag while retaining `clashyaml`. Check the journal **since this
restart** for absence of a new control-server permission error; historical errors
will remain in older journal entries. Verify Python >=3.10 and Gunicorn >=25.1.0.

Deployment tests use temporary directories and command doubles. No real /opt,
systemd unit or service account on the developer machine was modified. Both
channels use the same scripts when this revision is selected, but the immutable
published **v1.0.2 archive does not gain this fix**. Stable stays at v1.0.2 until a
separately authorized future release includes it.
