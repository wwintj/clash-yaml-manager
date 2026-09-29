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

The intended flow is: main development → `--channel main` test VPS → validation →
explicit “稳定了，发布” → the unchanged release automation below → vX.Y.Z Stable →
ordinary remote-update. A normal main push alone does not publish a release.

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
```

When asked to publish, Codex follows root `AGENTS.md`: inspect the real previous-stable..HEAD
diff, select the SemVer bump, prepare concise Unreleased prose describing implemented changes,
commit that work, then run dry-run and the real command without waiting for separate push/tag/
Release permission. No manual user edits to VERSION/README/CHANGELOG are needed. Semantic
summarization is the agent's responsibility; the script deliberately refuses empty Unreleased
notes instead of inventing features from filenames or pasting raw commit subjects.

The orchestrator promotes those reviewed notes to `## vX.Y.Z - YYYY-MM-DD`, retains an empty
Unreleased heading for future development, and uses only that version's body as Release Notes.
Allowed categories are Added, Changed, Fixed, Security and Deployment; empty categories are omitted
when preparing notes. README changes are confined to RELEASE/INSTALL/UPDATE marker pairs.

## Preflight and dry-run

Required checks before mutation:

1. Clean main, expected GitHub origin, identical fetch/push remote, origin/main ancestry.
2. Valid current/requested SemVer and monotonically increasing version; real GitHub stable
   releases are queried. Both local and remote tags and all GitHub Releases are checked for
   conflicts. Existing versions are immutable; no overwrite, deletion or force push.
3. GitHub repository write access, fixed default branch main, complete README markers and
   reviewed Unreleased notes.
4. Full pytest (including 10,410-rule round trip), Python compilation in memory, pip check,
   bash -n for six entrypoints and the helper, generated bootstrap synchronization, diff check,
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

`.github/workflows/release.yml` triggers on pushes of `v*` tags. It checks out full tag history,
sets up Python, installs test dependencies, runs the same validation, verifies annotated
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
