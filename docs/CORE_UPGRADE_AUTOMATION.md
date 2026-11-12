# Meowcal Core upgrade automation

`.github/workflows/core-upgrade.yml` checks the canonical
`PeterShanxin/Meowcal-Sub` releases once a day and on manual dispatch. It only
accepts a published, non-draft, non-prerelease `core-vX.Y.Z` release. The
updater downloads both Windows archives and checksum files, verifies the exact
SHA-256 values, archive contents, package metadata, PE architecture, and the
x64 API/capability contract, then writes `config/meowcal-core.lock.json`.

The workflow does nothing when no stable Core release exists or when the lock
already covers the newest release. It never merges a pull request. A generated
pull request, on branch `automation/core-X.Y.Z`, is the review and CI boundary
for the consumer integration tests, including the native ARM64 gate.

The generated pull request changes only the lock. Merging it changes the Core
that later builds of `main` bundle. It does not change a published App release,
and it does not make Sub 2 use a new Core capability: that needs a separate
change in this repository (see
[versions and capabilities](MEOWCAL_CORE.md#versions-and-capabilities)). Review
the Core release notes and update [MEOWCAL_CORE.md](MEOWCAL_CORE.md) in the
upgrade pull request when protocol, storage, or compatibility behavior changes.
Viewers receive the new Core only through a later App release.

PR creation uses the repository secret `CORE_UPGRADE_TOKEN`. It must be a
maintainer-owned fine-grained token or GitHub App token with Contents read/write
and Pull requests read/write on this repository. The token must be distinct
from `GITHUB_TOKEN`: GitHub suppresses new workflow runs for most events emitted
with `GITHUB_TOKEN`, which would leave the generated pull request without its
required `pull_request` checks. When the secret is missing or empty, a verified
update is reported in the workflow log and no branch or pull request is written.
The workflow does not change the secret or other repository settings.

Run the deterministic updater checks locally with:

```powershell
pwsh -NoProfile -File scripts/tests/core-upgrade.Tests.ps1
pwsh -NoProfile -File scripts/tests/core-candidate.Tests.ps1
```

On ARM64 Windows, run both from a native shell (`pwsh`, `cmd`, or `powershell.exe`
launched directly) rather than an x64 Git-Bash/MSYS2 shell. `RuntimeInformation.OSArchitecture`
reports the emulated x64 architecture when the process tree originates from an
x64 MSYS2 `bash.exe`, which fails `core-candidate.Tests.ps1`'s PE-machine
assertions even though the scripts under test detect architecture correctly
when launched natively.
