# Developer guide

Meowcal Sub 2 combines a Python backend, a React studio served over loopback,
and a Tauri desktop shell. Read [AGENT_GUIDE.md](AGENT_GUIDE.md),
[CODING_STANDARDS.md](CODING_STANDARDS.md), and
[MAINTAINABILITY_BASELINE.md](MAINTAINABILITY_BASELINE.md) before changing code.

## Set up a Windows checkout

Install Python 3.11 or newer, Node.js 22 LTS (22.12 or newer) with npm, Rust,
the Microsoft C++ build tools required by Tauri, and Microsoft WebView2.
Vite also supports Node 20.19 or newer. Use PowerShell from the repo root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
npm --prefix src\meocosub2\overlay\ui ci
python -m playwright install chromium
rustup component add rustfmt clippy
```

The debug shell prefers `.venv\Scripts\python.exe` for source development.
`MEOWCAL_PYTHON` can select another development Python executable. Release builds
use the bundled `backend/python.exe` and do not fall back to a developer install.

Launch the development app with `run_app.vbs`. It prepares the pinned Core
resource and builds the UI and debug shell when needed. `run_app.vbs --rebuild`
forces a rebuild. Source development requires the toolchains above; release
packages have their own launch instructions.

For backend-only development:

```powershell
python -m meocosub2.cli serve
```

Open the token-bearing URL printed by `serve`. Browser mode can inspect the
studio, but the native capture selector and desktop strip require the shell.

## Build a Windows distribution

The repository banner reads its version from `src-tauri/tauri.conf.json`, the
same source used to name release packages. After changing the project version
or editing the banner artwork, synchronize its SVG and PNG before committing:

```powershell
python scripts/update_branding.py
```

This uses the existing Playwright Chromium development dependency. The release
build also runs it automatically; unchanged assets are left alone. Verification
rejects a stale version or PNG export, so commit both banner files together.
The README release badge reads the latest published GitHub Release independently
and becomes available when the repository is public.

Use a native x64 or ARM64 Windows environment with PowerShell 7 and the tools
above. Install GitHub CLI and authenticate with `gh auth login`; the build reads
upstream license files that some published crates omit. CI supplies its read-only
GitHub token for this step.

```powershell
.\scripts\verify.ps1
.\scripts\build-windows-release.ps1
```

The build verifies the locked Core and CPython archives, installs hash-locked
backend wheels, collects dependency notices, and produces an NSIS installer,
portable ZIP, and SHA-256 list in `dist/`. Models are not bundled. Use a clean
commit for release artifacts; the portable package records its source commit
and whether the checkout had changes. Move any previous staging directory out
of `dist/` before rebuilding. Native acceptance must pass before publishing.

## Runtime map

| Responsibility | Source |
| --- | --- |
| CLI and local server lifetime | `src/meocosub2/cli.py` |
| HTTP/WebSocket routes | `src/meocosub2/overlay/server.py` |
| Session preparation and lifecycle | `src/meocosub2/overlay/controller.py` |
| Subtitle providers and aggregation | `src/meocosub2/subtitle_sources/` |
| OCR capture and playback sync | `src/meocosub2/capture.py`, `src/meocosub2/sync.py` |
| Target cue presentation | `src/meocosub2/presentation.py` |
| Core translation adapter and private BGE matcher | `src/meocosub2/engine/` |
| Per-run authentication | `src/meocosub2/auth.py` |
| Studio state and views | `src/meocosub2/overlay/ui/src/` |
| Desktop windows and backend process | `src-tauri/src/` |

The server-backed `/` route is the desktop studio. Edit React/TypeScript under
`src/meocosub2/overlay/ui/src/`, then rebuild the committed served bundle:

```powershell
npm --prefix src\meocosub2\overlay\ui run build
```

Do not edit `overlay/static/assets/` directly. The hand-maintained selector and
splash files under `overlay/static/` are embedded by Tauri; changes to them need
a shell rebuild.

`app.tsx` owns the studio's home, preparation, live, and settings flow. Typed
API wrappers and WebSocket hooks connect it to the backend. Provider selection
uses opaque `matchId` and `resultId` values. Source tracks establish playback
position; the presentation track owns target cue intervals, overlaps, and gaps.
See the [agent guide](AGENT_GUIDE.md) for matching and calibration invariants.

## Pinned Meowcal Core

[config/meowcal-core.lock.json](../config/meowcal-core.lock.json) pins a released
Core version, API major, and SHA-256 hashes for x64 and ARM64 packages.
`scripts/fetch-meowcal-core.ps1` selects and verifies the architecture's archive
and package contract, then prepares `src-tauri/resources/core/`. Tauri invokes
it before development and production builds. The shell passes the bundled
executable path to the backend as `MEOWCAL_CORE_EXE`.

Core owns Windows OCR and HY-MT installation, artifact verification, and
inference. The backend owns separate Core transports for OCR and translation;
BGE subtitle matching has a separate Sub 2 process and data directory. Translation
prompt shape and output validation remain product-owned. See
[MEOWCAL_CORE.md](MEOWCAL_CORE.md) for storage and compatibility rules.

For a local build using a previously downloaded, locked archive:

```powershell
.\scripts\fetch-meowcal-core.ps1 -ArchivePath $coreArchive -Offline
```

The offline flag does not bypass lock or digest checks. Candidate verification
and Core upgrades are documented in
[CORE_UPGRADE_AUTOMATION.md](CORE_UPGRADE_AUTOMATION.md); a local candidate lock
must not replace the reviewed release pin.

## Authentication and diagnostics

The backend binds to `127.0.0.1`. The studio and privileged HTTP/WebSocket
routes require a per-run token, sent through `X-Meowcal-Token` or the `token`
query parameter. The backend publishes it to
`%APPDATA%\meowcal-sub-2\runtime.json`; the shell reads that file. Foreign
request origins are rejected even when a token is supplied. Profile access by
software running as the same Windows user remains outside this boundary.

Configuration is at `%APPDATA%\meowcal-sub-2\config.toml`; see
[config.example.toml](../config.example.toml). Logs are under the adjacent
`logs` directory. Normal file and console logging use INFO; launch
`python -m meocosub2.cli --verbose serve` to enable DEBUG OCR/subtitle traces.
Normal logs can still contain titles, errors, and sensitive details. Use
synthetic content for debugging and sanitize excerpts before sharing.

The shell can reuse an existing backend on its configured port. Rebuilding the
shell alone may therefore leave Python changes untested. Stop the session and
close the app, identify any remaining process as task-owned before stopping
it, and check for surviving Core or inference children before restarting.

## Verification

```powershell
.\scripts\verify.ps1
```

This is the authoritative review gate and the command Windows CI runs. It
covers formatting, lint, types, Python/Rust/studio suites, the served dashboard,
and maintainability ratchets. `-List` prints stages; `-Stage <name>` runs a
subset during development.

The served-dashboard smoke refuses to reuse a backend already occupying its
port. A browser pass proves the served page, not Tauri/WebView2 rendering.
Native OCR, capture selection, overlay placement, real translation inference,
and process shutdown require a real Windows run. Evidence from one architecture
does not prove the other.
