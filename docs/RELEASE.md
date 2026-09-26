# Stable releases and deployment

`VERSION` is the only official version source, containing `MAJOR.MINOR.PATCH` without `v`.
Tags and GitHub Releases use `vMAJOR.MINOR.PATCH`. Web displays the version read from that
file; install/update deploy the source package's VERSION to `/opt/clash-yaml-manager/VERSION`.

## Version policy

- PATCH: compatible bug/security/deployment/documentation fixes or refactors.
- MINOR: backward-compatible user features, such as a future Merge or Preview mode.
- MAJOR: a breaking compatibility change, not simply a large diff.

Before the first formal release, GitHub had **no tags and no Releases**. The historical
CHANGELOG mentioned v1.0.0 without a published artifact. VERSION starts from that documented
1.0.0 baseline; the first formal release is selected as a patch for compatible safety and
deployment work. The release script always queries real GitHub Releases and reports the
absence of a previous stable honestly. Later releases compare against the latest stable.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-install.sh | sudo bash
```

The bootstrap comes from main, but installed application content comes exclusively from
the exact tag of GitHub Latest Stable Release. No main fallback exists. It requires python3
and curl, normally present on Ubuntu; no jq or git is needed. The downloaded install script
installs runtime dependencies. Use an interactive terminal: port defaults to 8899 and the
administrator password is hidden. Only the zero-length password is rejected. Single characters,
digits, Chinese, symbols, all-space values and surrounding spaces remain unchanged before hashing.

Specify a published stable version by replacing X.Y.Z:

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-install.sh | sudo bash -s -- --version vX.Y.Z
```

Existing installations must use update, not install. `install.sh` installs only its current
source package version and refuses overwriting an existing application or credentials.

## Update and pin

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh | sudo bash
cat /opt/clash-yaml-manager/VERSION
```

Update reads installed VERSION and resolves the latest stable. Equal versions report
`Already up to date.` without downloading the archive or changing the service. Legacy installs
without VERSION migrate through the existing preservation/auth migration flow. Malformed
installed VERSION stops rather than guessing. To pin a published release:

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh | sudo bash -s -- --version vX.Y.Z
```

Drafts, prereleases, missing releases and arbitrary branch names are rejected. The resolver
handles API 403/404/rate limits/timeouts and malformed responses by stopping. The archive is
downloaded from `refs/tags/vX.Y.Z`, checked before execution for traversal, symlinks, special
files, required source files, shell syntax and VERSION equality, and extracted into a private
temporary directory. That directory is cleaned on success and normal failure. Trust remains
in the repository's GitHub release/tag and HTTPS; this is not an independent signed-artifact system.

## Downgrade and rollback

Downgrades are refused unless explicitly requested:

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh | sudo bash -s -- --version vX.Y.Z --allow-downgrade
```

Permission to downgrade does not guarantee old code understands newer state. Use versions
known to support that state, or restore a coordinated backup while the service is stopped.
For actual failed-upgrade recovery, use the printed root-private backup path and
[Phase 2 rollback procedure](PHASE2.md#e-migration). Restore the corresponding VERSION along
with code/venv/unit, preserve runtime data, and understand that restoring old auth state also
restores an old password/version and may revive old sessions. No automatic rollback, force
push, historical tag replacement or Release replacement is performed.

## Uninstall

```bash
sudo bash /opt/clash-yaml-manager/uninstall.sh
```

Use the installed version's script. It stops/disables systemd, asks whether to retain the
project, and offers backup of outputs/backups/state/config before complete removal. Keeping
the project keeps its service account and ownership. Removal only deletes a verified dedicated
account without remaining processes; it does not delete other users or external home files.
See [Phase 2](PHASE2.md) for exact runtime/auth ownership and lifecycle.

## Maintainer release command

```bash
python3 scripts/release.py patch --dry-run
python3 scripts/release.py patch
```

`minor`, `major` and `--version X.Y.Z` are also supported. The full workflow, authentication,
automated documentation boundaries and recovery are in [RELEASE_AUTOMATION.md](RELEASE_AUTOMATION.md).
The user can ask Codex “稳定了，发布吧”; repository instructions delegate the whole workflow,
including reading the actual diff and preparing notes, to the agent.
