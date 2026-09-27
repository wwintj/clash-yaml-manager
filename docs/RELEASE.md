# Stable releases and development deployments

`VERSION` is the only official version source, containing `MAJOR.MINOR.PATCH` without `v`.
Tags and GitHub Releases use `vMAJOR.MINOR.PATCH`. Web displays the version read from that
file; install/update deploy the source package's VERSION to `/opt/clash-yaml-manager/VERSION`.
Development build identity is separate metadata and never changes repository VERSION.

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

The bootstrap comes from main, but by default installed application content comes exclusively
from GitHub Latest Stable Release. Its tag resolves to an exact commit archive. No main
fallback exists; main requires explicit `--channel main`. The bootstrap requires python3
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

Stable-to-stable update reads installed VERSION and resolves the latest stable. Equal versions report
`Already up to date.` without downloading the archive or changing the service. Legacy installs
without VERSION migrate through the existing preservation/auth migration flow. Malformed
installed VERSION stops rather than guessing. To pin a published release:

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh | sudo bash -s -- --version vX.Y.Z
```

In the stable channel, drafts, prereleases and missing releases are rejected. Arbitrary branch
names are never accepted; the only development option is explicit `--channel main`. The resolver
handles API 403/404/rate limits/timeouts and malformed responses by stopping. The archive is
downloaded by the exact commit resolved from the release tag, checked before execution for traversal, symlinks, special
files, required source files, shell syntax and VERSION equality, and extracted into a private
temporary directory. That directory is cleaned on success and normal failure. Trust remains
in the repository's GitHub release/tag and HTTPS; this is not an independent signed-artifact system.

## Explicit main development channel

Stable is always the default. `--channel stable` is equivalent to omitting the flag;
`--version vX.Y.Z` still selects a published stable tag. Combining `--version` and
`--channel main` is an error, before network requests. Invalid channels also fail early.

On a fresh **test VPS**:

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-install.sh | sudo bash -s -- --channel main
```

On an existing **test VPS**:

```bash
curl -fsSL https://raw.githubusercontent.com/wwintj/clash-yaml-manager/main/remote-update.sh | sudo bash -s -- --channel main
```

The bootstrap resolves GitHub `git/ref/heads/main`, validates a 40-hex commit SHA,
and downloads `https://codeload.github.com/wwintj/clash-yaml-manager/tar.gz/<SHA>`.
It never downloads a moving branch after resolution. A branch movement during the
download does not change the selected build. Both channels validate archive contents
before using the same install/update scripts, data preservation, migration, ownership,
service user and health checks. Main does not introduce an alternate deployment path.

CLI reports Channel, Resolved commit, Base version, Installed build and a development
notice; no additional yes prompt is introduced. Main updates compare SHA, not VERSION.
The same SHA reports `Already up to date.` without downloading or changing the service.
`--resolve-only` is read-only, needs no root, and returns the stable tag or main SHA.

### Installation identity and Web display

`/opt/clash-yaml-manager/INSTALLATION.json` is the public build identity file, outside
`.env` and private auth/temporary-link state. Example:

```json
{
  "channel": "main",
  "base_version": "1.0.2",
  "commit": "a9c2d103969462318ad27e5fc1050e1c455c5d44",
  "tag": null,
  "installed_at": "2026-09-27T00:00:00+00:00",
  "source": "github-main"
}
```

Stable metadata uses channel `stable`, the selected release tag and its resolved SHA,
and source `github-release`. The field allowlist excludes credentials. Atomic tempfile
write + fsync + replacement prevents partial JSON; mode is 644 and deployment ownership
repair makes it root-owned and service-readable. The file does not participate in cleanup.
Current scripts publish it before restart; the bootstrap also finalizes metadata after
successful deployment for older stable scripts that predate this hook. Failure does not
claim installation success. Metadata is not a cryptographic attestation of disk contents.

Web reads the metadata with VERSION. Main shows `v1.0.2-dev+a9c2d10` and a small
DEV / Development Build marker; stable retains `v1.0.2`. Missing metadata on legacy
installs keeps the historical VERSION display. Invalid metadata is visibly marked and
remote updates fail closed rather than ignoring downgrade protection. A direct local
source install/update without resolved metadata is labeled `-local`, without a claimed
commit, so it cannot retain a stale remote build identity.

### Switching channels

- stable → main: `--channel main` authorizes the switch.
- main → main: new SHA updates, same SHA skips; VERSION can remain unchanged.
- main → stable: normal remote-update allows a stable version strictly newer than
  the installed base VERSION, e.g. base 1.0.2 to released 1.1.0.
- main → same/older stable: refused unless `--allow-downgrade` is present. The explicit
  form is `--channel stable --allow-downgrade`. Local unversioned-build identities
  receive the same conservative protection.
- stable → older stable: original `--allow-downgrade` requirement remains.

Version comparison is a release-boundary guard, not proof of state-schema compatibility.
Before returning to an older stable, preserve coordinated code/VERSION/INSTALLATION.json
and runtime backups. Current upgrade/uninstall backups include build identity; historical
stable scripts may not know to back it up. Restoring code should restore its corresponding
build identity while preserving the correct auth and temporary-link state. Never delete
metadata to bypass protection. Do not edit repository VERSION to create a development build.

Lifecycle: main development → test VPS with `--channel main` → validation → explicit
“稳定了，发布” → existing release automation → vX.Y.Z Stable → normal remote-update.
Main is not recommended for normal production use. Creating this channel publishes no
tag or Release and does not change `scripts/release.py` or GitHub Actions.

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

## Development-channel validation

The channel change started from a **308-test** baseline and passed **335 tests** after
implementation. Coverage includes default/explicit stable resolution, both main entrypoints,
exact SHA downloads despite branch movement, metadata for both channels, atomic replacement
failure, mode 644, sequential updates, preserved auth/temporary-link state, stable/dev Web
footers, all channel transitions, argument rejection, and standalone bootstrap execution
without a checkout. Existing draft/parser/session/retention/subscription regressions and the
10,410-rule YAML round trip remain green. Python syntax, dependency checks, bash -n,
ShellCheck and generated bootstrap synchronization also pass; default.yaml is byte-for-byte
unchanged from v1.0.2.

Install/update tests run real shell scripts against temporary directories with system-command
doubles. The main-to-newer-stable case uses a simulated future v1.1.0; it does not publish one.
These checks do not claim a live Ubuntu VPS/systemd install or production upgrade. VERSION,
Latest Stable and the existing release system remain unchanged by channel development.

## Maintainer release command

```bash
python3 scripts/release.py patch --dry-run
python3 scripts/release.py patch
```

`minor`, `major` and `--version X.Y.Z` are also supported. The full workflow, authentication,
automated documentation boundaries and recovery are in [RELEASE_AUTOMATION.md](RELEASE_AUTOMATION.md).
The user can ask Codex “稳定了，发布吧”; repository instructions delegate the whole workflow,
including reading the actual diff and preparing notes, to the agent.
