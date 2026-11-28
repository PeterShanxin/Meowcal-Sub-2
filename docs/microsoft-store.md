# Microsoft Store edition

The Store edition runs on Windows 11 on Intel, AMD and ARM PCs. Microsoft Store installs the matching build and applies updates. Studio checks for an update for its installed package and opens the Store listing when the user chooses to update. Studio shows the app version. Partner Center uses a separate four-part package version and requires each update to increase it.

| Partner Center field | Value |
| --- | --- |
| Product ID | `9NH782JNLWJP` |
| Reserved name | Meowcal Sub 2 |
| Publisher display name | Shanxin Li |
| Package family | `ShanxinLi.MeowcalSub2_hs4jcn39rmtjt` |
| First package version | `1.0.0.0` (Studio `0.4.0`) |

The [package manifest](../store/AppxManifest.xml) contains the full identity and minimum Windows build. Its full-trust desktop permission lets Studio capture the selected window, show captions over the video and start its bundled Python backend and Meowcal Core. The Store package includes the backend, Core, license notices and app icons. Users download the optional local models when they need them.

## Build and submit

1. Start **Microsoft Store package** in GitHub Actions for the source revision being released. The workflow builds and installs the app on separate x64 and ARM64 Windows machines.
2. On each machine it signs a disposable test copy, starts Studio by its Start menu identity, opens the actual Studio window and saves a setting in its Windows package data. The workflow bundles the two original unsigned packages. It reopens the bundle and checks the Store identity, package and app versions, source commit, bundled files and native executables.
3. Download the `store-submission` artifact and check its bundle against `SHA256SUMS.txt`. Upload the `.msixbundle` in the Packages section of the reserved Partner Center product. For the listing's square logo, use the 300 × 300 PNG in the `store-catalog` artifact. Microsoft runs certification and signs the package it distributes. Track the submission in Partner Center to confirm publication.

For a single native build, use the [Windows build prerequisites](developer-guide.md#build-a-windows-distribution) and run `./scripts/build-store.ps1 -Architecture x64` or `-Architecture arm64` on the matching machine. Find the unsigned `.msix` under `dist/`. Store builds do not require the GitHub updater signing key.

## Release automation

When enabled, publishing the latest stable GitHub release from `main` as a
maintainer starts **Microsoft Store package** from the exact tagged revision.
The submitted Store bundle is the one tested on both Windows architectures.
A separate **Sync GitHub release to Microsoft Store** workflow on `main`
checks the build and package identities before sending it to certification
with publication after approval. It does not change listing copy, availability
or pricing. An unrelated or unfinished Partner Center submission is left alone.
GitHub releases and Store package versions are independent: bump the
four-part version in `store/AppxManifest.xml` before tagging, higher than
every currently published package version and any used flight version.

### Enable it for a future release

- Create the `store-submission` GitHub Actions environment and restrict it
  to deployments from the `main` **branch**, not tags. Keep the repository's
  release tags and `main` restricted to maintainers.
- Authorize a Microsoft Entra application for this product in Partner Center.
  Set the environment secrets `AZURE_AD_TENANT_ID`, `AZURE_AD_APPLICATION_CLIENT_ID`,
  `AZURE_AD_APPLICATION_SECRET` and `SELLER_ID`. Do not put these in repository
  secrets used by tagged builds. [Store Submission API setup](https://learn.microsoft.com/windows/uwp/monetize/create-and-manage-submissions-using-windows-store-services)
- Run **Sync GitHub release to Microsoft Store** with `inventory` checked
  from `main`. It reads the current package versions and pending status
  without creating a submission. Confirm the product ID above.
- Set repository variables `STORE_FIRST_RELEASE_TAG` to the first **future**
  stable tag (`v0.4.2` or later; `v0.4.1` remains manual) and
  `STORE_RELEASE_NOT_BEFORE` to a UTC
  ISO timestamp after the last manual release and before the next release.
  Set `STORE_RELEASE_AUTOMATION_ENABLED=true` only after the inventory check.
  Existing GitHub releases are not replayed; leave the flag unset to disable
  automatic Store submission.

If upload or commit fails, read inventory and inspect the reported submission
ID before retrying. Do not delete or overwrite a pending submission to unblock
the workflow. A GitHub release can succeed while the Store submission is still
in certification; use Partner Center or inventory to confirm publication.

## Where user data lives

Windows provides a writable directory at `%LOCALAPPDATA%\Packages\ShanxinLi.MeowcalSub2_hs4jcn39rmtjt\LocalState`. Studio saves settings, subtitle provider credentials and logs under `meowcal-sub-2` there. Core uses `Core` for its data, and the embedded browser uses `WebView2`. Windows removes local package data when the user uninstalls the Store edition.

The Store edition starts with its own settings. A user who also has the GitHub version can enter their provider credentials in the Store edition's Settings. Each edition uses its own Studio connection by default. The Store edition listens on the PC's loopback port 8766 and the GitHub edition uses 8765. An explicitly configured port takes precedence.
