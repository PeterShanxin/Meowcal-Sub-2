# Meowcal-Sub-2 Developer Guide

## Repo Shape

- Python backend entrypoint: `python -m meocosub2.cli serve`
- Served dashboard: `src/meocosub2/overlay/server.py`
- Studio UI source (Vite + React + TS): `src/meocosub2/overlay/ui/`
- Studio UI entry: `src/meocosub2/overlay/ui/src/app.tsx`
- Studio UI build output (served at `/`): `src/meocosub2/overlay/static/index.html` + `src/meocosub2/overlay/static/assets/`
- Subtitle-source logic: `src/meocosub2/subtitle_sources/`
- Session orchestration: `src/meocosub2/overlay/controller.py`
- Capture loop and session strategies: `src/meocosub2/sync.py`
- Which OCR reads count as a new subtitle: `src/meocosub2/subtitle_gate.py`
- Managed local translation engine: `src/meocosub2/engine/`
- Studio authentication: `src/meocosub2/auth.py`
- Desktop shell: `src-tauri/src/main.rs`

The desktop app is still the same local server-backed UI wrapped by Tauri. The browser path and the Tauri path share the same dashboard contract.

## Source Of Truth

- Live runtime behavior should be read from code under `src/` and `src-tauri/`.
- `config.example.toml` is the current config-schema reference.
- `docs/plans/` is intentionally non-authoritative and repo-ignored.

## Frontend Module Map

Under `src/meocosub2/overlay/ui/src/`:

- `main.tsx`: React mount point.
- `app.tsx`: top-level state machine (`home` → `prep` → `live`, plus `settings` / empty / no-key variants). Bootstraps state via `/api/state`, `/api/config`, `/api/languages`, `/api/engine/status`; wires the WebSocket; drives palette flow.
- `components/primitives.tsx`: `Backdrop`, `TopBar`, `CatMark`, `CatMascot`, `Kbd`, `PaletteTabs`.
- `components/palette.tsx`: the ⌘K command palette, tabs (Titles / Source / Target / Commands), lists, and footer hint.
- `components/prep-card.tsx`: prep-phase session summary + preview card.
- `components/live-dock.tsx`: live-phase subtitle view and bottom dock.
- `components/variants/{empty,no-key,settings}.tsx`: first-launch, missing-provider, and full settings screens.
- `hooks/use-api.ts`: typed REST wrapper.
- `hooks/use-ws.ts`: `/ws/app` connection + dispatch.
- `hooks/use-keybinds.ts`: global keybinds (⌘K / Tab / ↑↓ / ↵ / ⌘↵ / `,` / ⇧⌫).
- `hooks/use-tauri.ts`: thin wrappers around `window.__TAURI__.core.invoke`.
- `state/store.ts` + `state/mappers.ts`: single store (useSyncExternalStore) and backend → palette-shape mappers.

Keep `app.tsx` as the top-level entry even when you move behavior between hooks/components.

## Subtitle Studio Flow

1. Dashboard loads `/api/config`, `/api/state`, and `/api/languages`.
2. User searches for a title through `/api/search`.
3. The dashboard narrows choices by matched title, then source subtitle, then target subtitle or local translation.
4. `POST /api/session/prepare` creates one of:
   - `auto_candidates`: several source subtitles to match against, plus a target file
   - `subtitle_pair`: one chosen source subtitle
   - `ocr_fallback`: no source subtitle, so reads are translated directly
5. `POST /api/session/start` begins sync and pushes updates over the `/ws/app` WebSocket (state, progress, subtitle, style, error, debug).
6. `POST /api/session/stop` ends the active session and clears overlay state.

When the user enters the live phase, the studio calls the Tauri `enter_live_mode` command; the main window reshapes into a bottom-of-screen always-on-top strip. `exit_live_mode` restores the pre-live geometry.

The current provider-neutral selection model uses opaque `matchId` and `resultId` values instead of provider file ids in the UI flow.

## Translation Engine

`src/meocosub2/engine/` adapts the versioned Meowcal Core API to the studio's
status and install controls. Core owns HY-MT artifact verification, installation,
recovery, GPU/CPU policy, and inference. It accepts verified legacy artifacts as
import sources without depending on another application's running installation.
The backend owns its Core processes; OCR and inference have separate transports.
See [MEOWCAL_CORE.md](MEOWCAL_CORE.md) for storage and compatibility rules.

### Pinned Core runtime

`config/meowcal-core.lock.json` binds Sub 2 to one released Core version, API
major, x64 ZIP digest, and ARM64 ZIP digest. A production build must not use a
placeholder digest or depend on a Sub 1 checkout. Generate the reviewed lock
from the checksum files published with the Core release:

```powershell
./scripts/write-meowcal-core-lock.ps1 `
  -Version 0.1.0 `
  -X64ChecksumPath .\downloads\meowcal-core-v0.1.0-windows-x64.zip.sha256 `
  -Arm64ChecksumPath .\downloads\meowcal-core-v0.1.0-windows-arm64.zip.sha256
```

`scripts/fetch-meowcal-core.ps1` selects the current Windows architecture,
downloads the exact locked asset, verifies the archive and package contract,
then writes `src-tauri/resources/core/meowcal-core.exe`. Tauri runs it before
development and production builds and bundles the executable, metadata, and
license. At runtime the
shell passes the absolute bundled path to Python as `MEOWCAL_CORE_EXE`.
The Python client reads the pinned `coreVersion` from the adjacent verified
metadata before sending the handshake, so a Core pin can advance independently
of the application version.

For an offline local build, point the fetcher at an already downloaded archive;
the same lock and digest checks still apply:

```powershell
./scripts/fetch-meowcal-core.ps1 -ArchivePath $archive -Offline
```

To validate an unpublished candidate, generate a separate lock from that
candidate's checksum files using `-OutputPath output/core/meowcal-core.local.lock.json`.
Set these overrides before running the verifier, Tauri, or `run_app.vbs`:

```powershell
$env:MEOWCAL_CORE_LOCK = Join-Path $PWD 'output/core/meowcal-core.local.lock.json'
$env:MEOWCAL_CORE_ARCHIVE = $archive
```

The local lock verifies the candidate; it does not replace the committed release
pin. Before the first Core publication, production packaging is intentionally
blocked until `config/meowcal-core.lock.json` contains the published asset hashes.

`run_app.vbs` prepares the resource when needed and sets
`MEOWCAL_CORE_PROFILE=development`. Installed builds use the production profile.

Prompt shape, sampling, and output validation remain product-owned: the instruction
template is Chinese whenever either side of the language pair is Chinese, and
output that is far longer than its source, loops, restates the context it was
given, or is written in the wrong script is discarded rather than shown.

## Studio Authentication

Every `/api/*` and `/ws/*` route requires a per-run token, presented as the
`X-Meowcal-Token` header or a `token` query parameter. `serve` generates it,
writes it to `%APPDATA%/meowcal-sub-2/runtime.json`, and injects it into the
served page for the studio itself; the Tauri shell reads the same file. Requests
carrying a foreign `Origin` are refused even with a valid token. Only `/static/*`
is public.

## Verification

Use these checks after changes:

```powershell
pytest -q
npm --prefix src\meocosub2\overlay\ui run build
cargo check --manifest-path src-tauri\Cargo.toml
python -m playwright install chromium
python scripts\run_dashboard_smoke.py
```

Install Chromium once per machine before the smoke check. The Playwright smoke script validates the served dashboard path only, fails closed if another dashboard is already occupying port `8765`, and does not prove native WebView2 correctness inside Tauri.

## Commenting Guidance

- Add short rationale comments where the code preserves compatibility, coordinates cross-module state, or handles a non-obvious runtime constraint.
- Prefer comments that explain *why this branch exists* or *what invariant it protects*.
- Avoid “commenting every line” in straightforward code.
