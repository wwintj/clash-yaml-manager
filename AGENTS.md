# Working in this repository

Preserve the existing Flask/Python architecture and runtime data. Never rewrite Git history,
force-push, change the origin, replace an existing stable tag/Release, or modify
`defaults/default.yaml` without an explicit request to review that change.

## Stable release requests

When the user asks to release a stable version (for example “稳定了，发布吧”, “正式发布”,
“发布新版”, or “推 GitHub”), complete the entire release workflow. This is authorization
to commit, create an annotated tag, push main/tag and create the GitHub Release for this
repository. Do not stop after preparing files or ask separately whether to push/create a Release.
Stop only for a failing check, unavailable write permission, or a conflict that cannot safely
be resolved. Never expose credentials.

1. Read `docs/RELEASE_AUTOMATION.md`; inspect VERSION, local/remote tags, GitHub Releases,
   and the actual diff since the previous stable tag. VERSION is the only version source.
2. Choose patch for compatible fixes/security/deployment/docs/refactors, minor for a user
   feature, major only for a compatibility break. When no bump is stated, determine it from
   that diff rather than its size. Document the choice.
3. Maintain reviewed human-readable `CHANGELOG.md` Unreleased notes from the diff using
   Added/Changed/Fixed/Security/Deployment categories. Never paste raw git log. The agent
   performs this editorial step; the user does not have to edit release metadata.
4. Commit feature work and notes first. Keep a clean main. Run
   `python3 scripts/release.py patch --dry-run` (or the selected bump / `--version X.Y.Z`).
5. On success, run the same command without `--dry-run`. The orchestrator validates,
   promotes notes, updates only README markers and VERSION, commits `chore(release): vX.Y.Z`,
   creates an annotated tag, pushes main then tag, publishes and verifies the Release.
6. Inspect GitHub Actions and verify origin/main, tag, Release title/body, README metadata,
   and both remote lifecycle `--resolve-only` commands. Report the exact version, SHAs,
   URLs and validation limits. Recover interrupted publication using the documented
   existing-tag flow; never delete or overwrite published objects.

## Development constraints

- Password policy is non-empty only. Preserve every character, including surrounding
  spaces and Unicode. Do not introduce password complexity rules or strip passwords.
- Do not reintroduce removed contact-email displays in README or public documentation.
- Default/stable installs and updates resolve GitHub Releases and exact tag commits,
  never main content. Only explicit `--channel main` may deploy a resolved main commit
  for development testing. API or archive failures must stop without channel fallback.
- Edit `scripts/remote_lifecycle.py`, then run `python3 scripts/build_bootstraps.py` to
  regenerate the two standalone entrypoints. Tests enforce synchronization.
- Run pytest, Python syntax, bash -n, dependency and diff checks before publishing.
  Use ShellCheck if available. Do not operate on the developer machine's real /opt,
  systemd or system accounts; lifecycle tests use temporary directories and command doubles.
