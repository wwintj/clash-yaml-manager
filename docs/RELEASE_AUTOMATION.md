# Release automation

## Stable and development channels

Remote install/update defaults remain **stable**, equivalent to `--channel stable`.
Only explicit `--channel main` resolves main HEAD and installs its exact commit archive
for a test VPS. Both use the existing safe deployment scripts. `--version` is stable-only.
This development path does not invoke the release orchestrator, create a tag/Release,
or change VERSION. Build identity is recorded separately in root-owned, atomic
`INSTALLATION.json`; Web shows a `-dev+<short SHA>` suffix and DEV marker for main.

Main-to-main updates compare full SHA. Returning to a strictly newer Stable is allowed;
returning to a same/older stable base requires `--allow-downgrade`. Stable version-pinning
and downgrade rules remain. Details, metadata schema and recovery limitations are in
[RELEASE.md](RELEASE.md#explicit-main-development-channel).

The intended flow is: main development → real VPS `--channel main` acceptance →
local release dry-run → Ubuntu Release Candidate Validation → only after Ubuntu PASS,
explicit stable publication → tag-triggered immutable verification → ordinary remote-update.
The Ubuntu candidate gate runs **before tag or Release creation**. A normal main push or
successful candidate validation alone does not publish or authorize a release.

## Single command and agent workflow

The official orchestrator is `scripts/release.py`, using Python stdlib, Git and an already
authenticated GitHub CLI. VERSION is authoritative. README's Latest Stable block is generated
metadata, not an independent version source.

```bash
python3 scripts/release.py patch --dry-run
python3 scripts/release.py patch
python3 scripts/release.py minor --dry-run
python3 scripts/release.py major --dry-run
python3 scripts/release.py --version X.Y.Z --dry-run
python3 scripts/release.py --validate-only
```

When asked to publish, Codex follows root `AGENTS.md`: inspect the real previous-stable..HEAD
diff, select the SemVer bump, prepare concise Unreleased prose describing implemented changes,
commit that work, run dry-run and the Ubuntu candidate gate on the exact main commit,
then run the real command without waiting for separate push/tag/Release permission.
If a task explicitly stops before publication, a passing gate leaves the version and published
objects unchanged. No manual user edits to VERSION/README/CHANGELOG are needed. Semantic
summarization is the agent's responsibility; the script deliberately refuses empty Unreleased
notes instead of inventing features from filenames or pasting raw commit subjects.

The orchestrator promotes those reviewed notes to `## vX.Y.Z - YYYY-MM-DD`, retains an empty
Unreleased heading for future development, and uses only that version's body as Release Notes.
Allowed categories are Added, Changed, Fixed, Security and Deployment; empty categories are omitted
when preparing notes. README changes are confined to RELEASE/INSTALL/UPDATE marker pairs.

For a feature-freeze audit, use `python3 scripts/release.py minor --dry-run` only
after committing/pushing a clean main. A passing audit does not authorize publication;
VERSION, tags and Releases remain unchanged until an explicit release instruction.

## Preflight and dry-run

Required checks before mutation:

1. Clean main, expected GitHub origin, identical fetch/push remote, origin/main ancestry.
2. Valid current/requested SemVer and monotonically increasing version; real GitHub stable
   releases are queried. Both local and remote tags and all GitHub Releases are checked for
   conflicts. Existing versions are immutable; no overwrite, deletion or force push.
3. GitHub repository write access, fixed default branch main, complete README markers and
   reviewed Unreleased notes.
4. Full pytest (including 10,410-rule round trip), Python compilation in memory, pip check,
   bash -n for exactly eight shell files (`install.sh`, `remote-install.sh`,
   `update.sh`, `remote-update.sh`, `uninstall.sh`, `httpsctl.sh`, `mihomoctl.sh`,
   `scripts/deploy-common.sh`), generated bootstrap synchronization, diff check,
   removed-email exclusion and a fixed byte checksum for the default YAML.
5. ShellCheck when present; otherwise print unavailable. ShellCheck is not a runtime dependency.

Dry-run prints current stable, current VERSION, proposed version/tag, included commits, diff
scope, complete metadata diff, files that would change, tests and remote. It performs no
project file/ref or remote mutations. Tests use temporary directories; Python bytecode and
pytest's repository cache are disabled during validation. GitHub reads still require network
and authentication. The working tree/HEAD is rechecked after tests.

Formal execution performs the same preflight again and rechecks remote conflicts, then:

1. Write only VERSION, CHANGELOG.md and marked README metadata.
2. Create `chore(release): vX.Y.Z` containing only those metadata files.
3. Create `git tag -a vX.Y.Z -m "Release vX.Y.Z"`.
4. Push main, then the tag, without force options.
5. Create the stable GitHub Release with title equal to tag and the exact current notes body.
   `gh release create --verify-tag` prevents implicit creation of a tag at the wrong commit.
6. Verify the remote annotated tag commit, origin/main, Latest Release, title/body and both
   lifecycle stable resolvers. Report the actual URL.

## GitHub Actions

### Manual pre-release Ubuntu gate

`.github/workflows/release-candidate.yml` uses only `workflow_dispatch` and `contents: read`.
It checks out the optional `ref` input (default `main`) with full history, logs the validated
commit SHA, sets up Python 3.12, installs `requirements-dev.txt`, and runs:

```bash
python scripts/release.py --validate-only
```

This CLI directly reuses `validate()`: Python syntax, README checks, fixed default YAML hash,
eight bash syntax checks, bootstrap synchronization, ShellCheck when present, pip check,
full pytest (including the 10,410-rule round trip), and git diff check. The Ubuntu workflow
also requires ShellCheck to be available and logs systemd-analyze availability/version.
It does not plan a version, change VERSION/README/CHANGELOG, commit, tag, push, publish,
or call GitHub write APIs. It needs no publication credentials and also runs locally on macOS.
Combining `--validate-only` with a bump, `--version`, `--dry-run` or `--publish-tag` is rejected.
Validation failures return nonzero; release notes or a proposed bump are not required.

After committing and normally pushing clean main, pin the dispatch input to its full SHA:

```bash
candidate_sha=$(git rev-parse HEAD)
gh workflow run release-candidate.yml --ref main -f ref="$candidate_sha"
gh run list --workflow release-candidate.yml
gh run watch RUN_ID --exit-status
```

Require SUCCESS and verify the logged checkout SHA matches the intended main commit.
If the candidate fails, stop before creating a tag/Release; fix on main and dispatch a new
candidate for the new exact SHA. If main changes after a successful candidate, validate
the new commit before publication. The release orchestrator still repeats its local preflight;
candidate acceptance is a required workflow step, not an automatic bypass or publisher.

The v1.3.2 recovery audit deliberately runs its final patch dry-run after the Ubuntu gate,
then stops awaiting a separate formal-publication instruction. VERSION and Latest remain
v1.3.1 throughout that audit.

### Tag-triggered immutable verification

`.github/workflows/release.yml` triggers on pushes of `v*` tags. It checks out full tag history,
sets up Python 3.12, installs `requirements-dev.txt`, runs the same validation, verifies annotated
tag == HEAD and VERSION == tag without v, then publishes. It uses only the built-in
`${{ github.token }}` through GH_TOKEN with `contents: write`; no repository PAT secret is needed.

Local publication and tag-triggered Actions may race. Formal new-version preflight always
rejects an existing tag/Release. In the post-tag publication step only, an already-created
Release is accepted **only when** tag, title, stable flags and body exactly match; no edit API
is called. Mismatch fails. Workflow retries therefore verify an immutable release rather than
creating duplicates. Per-tag Actions concurrency also prevents redundant concurrent jobs.

The first v1.0.1 run exposed an Actions checkout behavior: after fetching an annotated tag,
checkout fetched the event commit SHA into the runner's same-named local tag ref. All 247
tests passed, but the local-ref annotation check failed. The follow-up patch checks the remote
tag object ID/type and its peeled commit against HEAD instead; if needed it fetches that exact
object without rewriting any tag refs. A genuinely lightweight remote tag still fails. The
v1.0.1 tag/Release remain unchanged; the fix ships as a new patch release.

v1.3.1 remains **published with failed final tag-triggered Actions validation** (run
37086419255). Its Linux unsafe-auth-object test compared an entire lstat result and rejected
an access-time-only change to a broken symlink. Recovery preserves that tag/Release and fixes
the assertion on main for a future patch, retaining structural and link-target checks.
Rerunning the old workflow still checks out the unchanged v1.3.1 code; it is not the recovery
path. The pre-release Ubuntu gate addresses the gap that previously allowed v1.2.0 and
v1.3.1 to encounter CI failure after publication.

Official references: [GitHub release API](https://docs.github.com/en/rest/releases/releases)
and [gh release create](https://cli.github.com/manual/gh_release_create).

## Authentication and interruptions

Use existing `gh auth` / Git credentials / GH_TOKEN or GITHUB_TOKEN. Never write tokens to
the repository, documentation, command arguments or notes. The local release process needs
both Git push access and GitHub Releases write access; workflow-file pushes may also require
the corresponding OAuth scope. The first publication environment had existing repo/workflow
scopes and repository push permission. Network/API/permission failures stop safely.

Publication is a sequence, not a distributed transaction. If main/tag push or Release creation
fails, existing local commits/tags remain for diagnosis; nothing is reset, deleted or rewritten.
To recover, the agent first verifies the release metadata, clean tree, annotated local/remote tag
and commit identity. Retry only missing normal pushes, then check out the exact release commit
and run:

```bash
python3 scripts/release.py --publish-tag vX.Y.Z
```

That command revalidates tests and metadata and publishes/verifies the already-pushed exact tag.
It never creates/replaces tags. If conflicting content already exists, stop; do not hide a conflict
by editing the Release. After recovery, return to main when appropriate and verify the workflow.

## Tests and deployment boundaries

Release tests cover SemVer, bumping, tag normalization/conflicts, clean-main checks, bounded
README editing/email exclusion, CHANGELOG promotion/extraction, no-mutation dry-run, exact
VERSION/tag matching, immutable metadata, and actual temporary-repository commit/tag sequencing.
Lifecycle tests cover stable/pinned resolution, exact tag archives, current-version no-op,
upgrades/downgrade opt-in, old installs without VERSION, malformed/API/download/archive failures,
path safety, temporary cleanup, installed VERSION and standalone bootstrap execution outside a checkout.
Deployment tests run real scripts against temporary paths with systemctl/account/chown/pip doubles.
Password tests exercise empty rejection, a single letter/digit/Chinese character/symbol, Unicode,
surrounding spaces and an all-space password through Web and installer flows.

These are not proof of a real Ubuntu systemd install. Actual account ownership, low-port
capabilities, interactive terminal on each deployment platform, reverse proxy behavior and
Mihomo binary validation remain environment checks. Do not smoke-test against the developer
machine's real /opt or system accounts. See [RELEASE.md](RELEASE.md) for user deployment commands.

## Maintaining the bootstrap

Edit `scripts/remote_lifecycle.py` and run `python3 scripts/build_bootstraps.py`; commit both
generated `remote-install.sh` and `remote-update.sh`. `--check` detects drift. The duplicate
embedded source (including the stdlib build-metadata helper from `core/install_info.py`)
makes curl|bash self-contained. By default only the resolved stable commit archive supplies
the installation scripts. Explicit main selection uses its resolved commit archive; network
failure never switches channels or falls back to moving main content.
