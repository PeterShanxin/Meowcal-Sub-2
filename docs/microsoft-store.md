# Microsoft Store edition

The Store edition runs on Windows 11 on Intel, AMD and ARM PCs. Microsoft Store installs the matching build and handles updates. Studio shows the app version. Partner Center uses a separate four-part package version and requires each update to increase it.

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
3. Download the `store-submission` artifact and check its bundle against `SHA256SUMS.txt`. Upload the `.msixbundle` in the Packages section of the reserved Partner Center product. Microsoft runs certification and signs the package it distributes. Track the submission in Partner Center to confirm publication.

For a single native build, use the [Windows build prerequisites](developer-guide.md#build-a-windows-distribution) and run `./scripts/build-store.ps1 -Architecture x64` or `-Architecture arm64` on the matching machine. Find the unsigned `.msix` under `dist/`. Store builds do not require the GitHub updater signing key.

## Where user data lives

Windows provides a writable directory at `%LOCALAPPDATA%\Packages\ShanxinLi.MeowcalSub2_hs4jcn39rmtjt\LocalState`. Studio saves settings, subtitle provider credentials and logs under `meowcal-sub-2` there. Core uses `Core` for its data, and the embedded browser uses `WebView2`. Windows removes local package data when the user uninstalls the Store edition.

The Store edition starts with its own settings. A user who also has the GitHub version can enter their provider credentials in the Store edition's Settings. Each edition uses its own Studio connection by default. The Store edition listens on the PC's loopback port 8766 and the GitHub edition uses 8765. An explicitly configured port takes precedence.
