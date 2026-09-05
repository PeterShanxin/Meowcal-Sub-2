# Agent Guide

## Repo Overview
- Meowcal Sub 2 is a desktop subtitle studio with a Python backend and a Tauri shell.
- The live studio UI is served from `http://127.0.0.1:8765/`.
- The Windows launcher is `run_app.vbs`.

## Runtime Map
- Backend server: `python -m meocosub2.cli serve`
- Studio route: [src/meocosub2/overlay/server.py](../src/meocosub2/overlay/server.py)
- Subtitle source aggregator: [src/meocosub2/subtitle_sources](../src/meocosub2/subtitle_sources)
- Capture loop and session strategies: [src/meocosub2/sync.py](../src/meocosub2/sync.py)
- Managed local translation engine: [src/meocosub2/engine](../src/meocosub2/engine)
- Studio UI source (Vite + React + TS): [src/meocosub2/overlay/ui](../src/meocosub2/overlay/ui)
- Studio UI entry: [src/meocosub2/overlay/ui/src/app.tsx](../src/meocosub2/overlay/ui/src/app.tsx)
- Studio UI build output (served at `/`): [src/meocosub2/overlay/static/index.html](../src/meocosub2/overlay/static/index.html) + `static/assets/`
- Tauri shell startup: [src-tauri/src/main.rs](../src-tauri/src/main.rs)
- Tauri window config: [src-tauri/tauri.conf.json](../src-tauri/tauri.conf.json)

## Source Of Truth
- Treat the server-backed `/` route as the real desktop runtime path.
- Edit React source under `src/meocosub2/overlay/ui/src/`; run `npm --prefix src/meocosub2/overlay/ui run build` to refresh `static/index.html` + `static/assets/`.
- Do not edit files under `static/assets/` directly — they are Vite build output.
- `static/splash.html` and `static/selector.*` are hand-maintained Tauri sub-windows; those live outside the React app.
- `docs/plans/` is not authoritative for current behavior and should be ignored for maintenance work.

## Anti-slop quality bar

Stated once, in [`AGENTS.md`](../AGENTS.md), because it is the first thing read
in this repository. It applies to code, comments, documentation, PR and issue
text, UI copy, architecture, configuration, and handoff notes.

## Coding standards

[`docs/CODING_STANDARDS.md`](CODING_STANDARDS.md) is normative for what the code
has to look like. [`docs/MAINTAINABILITY_BASELINE.md`](MAINTAINABILITY_BASELINE.md)
owns the measured limits that `scripts/verify.ps1` enforces.

## What Fills The Subtitle Plate

Three things answer a read of the capture region, in this order:

1. A text match against the downloaded subtitle file (~1ms). Anchors the
   playback clock.
2. The file's own line at the clock's predicted position, when the read matched
   nothing. Measured over a real session, the distance between file position and
   playback held to within a second across six minutes, so one match places
   every line after it. An anchor nothing has agreed with for 90s is dropped.
3. The local model translating the read (~1s), when there is no anchor.

Reads of a cue already on screen may only improve on it by matching outright —
letting the clock answer again would swap the line mid-cue.

## Log Inspection

- Log file: `%APPDATA%\meowcal-sub-2\logs\meowcal-sub-2.log` (always DEBUG level).
- Key patterns to grep:
  - `OCR pass=` — which pass won, score, recognized text, duration
  - `MATCH hit:` — matched subtitle index, score, source snippet
  - `MATCH miss:` — threshold and normalized OCR text that failed to match
  - `MATCH skip:` — OCR text too short to attempt match
  - `Locked subtitle candidate` / `Unlocking subtitle candidate` — which downloaded subtitle the session is following
  - `OS /features query=` — OpenSubtitles feature search: query string and hit count
  - `OS /subtitles params=` — OpenSubtitles subtitle search: params (including language codes) and result count
  - `Discarded unusable translation` — model output refused before it reached the overlay
- Miss rate diagnosis: count `MATCH miss` vs `MATCH hit` over a run window.
- A high miss rate is normal and is not a threshold problem. Streaming sites burn
  in one fansub's translation while the downloaded file carries another's, so
  most reads share no characters with the file — measured at 12% matched on a
  real episode, with the rest peaking at 20-40 against a threshold of 65.
  Lowering `fuzzy_threshold` buys wrong lines, not right ones. Lines that do not
  match are placed by the playback clock instead (see below).
- If OCR text looks garbled → wrong capture region or OCR language; check `capture.region` in config.
- If subtitle search returns 0 results → grep `OS /subtitles params=` to confirm language codes (`zhs` for Simplified Chinese) and `parent_feature_id` are present.
- Live debug panel: set `[debug] mode = true` in config.toml, open the studio while a session is running; panel appears bottom-right showing the last 20 iterations.
- The studio requires a per-run token. Read it from `%APPDATA%/meowcal-sub-2/runtime.json` and send it as `X-Meowcal-Token`, or open `/?token=...`. Unauthenticated requests get 401, foreign origins 403.

## Verification

- The shell reuses whatever backend already answers on port 8765 rather than
  spawning its own. Rebuilding and relaunching the shell therefore does **not**
  pick up Python changes — stop the `python.exe` running the backend first, or
  the session under test is still running the old code.

### Stopping the app without leaking the engine

The backend spawns `llama-server.exe` with the translation model resident, about
**1.1GB each**, on a dynamic loopback port. Two mechanisms keep it from
outliving the app, and both are best-effort:

- the shell puts the backend in a Win32 job object with
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Job membership is inherited, so however
  the shell ends, the backend and the engine go with it
  ([process_lifetime.rs](../src-tauri/src/process_lifetime.rs));
- the backend sweeps engines stranded by earlier runs before it starts one
  ([engine/orphans.py](../src/meocosub2/engine/orphans.py)). Ownership is decided
  by path and by whether the parent is still alive, so another install's working
  engine is never touched.

Neither covers a backend started by hand (`python -m meocosub2.cli serve`) and
then force-killed — that one is only covered by the backend's own job object.

Stop a session the way the app does: `POST /api/session/stop`, then the shell's
own Stop control or closing its window. After stopping, and before launching
again, confirm nothing survived:

```powershell
Get-Process llama-server, meowcal-sub-2-shell -ErrorAction SilentlyContinue |
  Select-Object Id, Name, @{n='MB';e={[int]($_.WorkingSet64/1MB)}}
```

Any engine started by hand for an experiment — an embedding model, a second
runtime — is your own to stop in the same session.

### One command

```powershell
.\scripts\verify.ps1
```

Every gate this repository enforces: formatting, lint, types, the Python, Rust
and studio suites, the served dashboard, and the maintainability ratchets.
[`.github/workflows/windows-ci.yml`](../.github/workflows/windows-ci.yml) calls
the same script, so a green local run and a green CI run mean the same thing.

Prerequisites, once per machine:

```powershell
python -m pip install -e ".[dev]"
npm --prefix src\meocosub2\overlay\ui install
python -m playwright install chromium
rustup component add rustfmt clippy
```

`-Stage <name>` runs part of it while iterating; `-List` names the stages. A
full run is the authoritative result.

What it cannot prove: OCR, WebView2 rendering, the capture selector, and the
overlay plate. Those need a real Windows run of the app.

### While iterating

- `pytest -q` after Python or server changes.
- `npm --prefix src\meocosub2\overlay\ui run build` after studio UI changes
  (rebuilds `static/index.html` + `static/assets/`). The bundle is committed;
  `verify.ps1` checks the sources it is built from, not the bundle.
- `cargo check --manifest-path src-tauri\Cargo.toml` after shell changes.
- `python scripts\run_dashboard_smoke.py` for the served-dashboard check alone.
- For launcher debugging on Windows:
  - `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*meocosub2.cli serve*' }`
  - `Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -eq 8765 }`
  - `python scripts\capture_meowcal_window.py --list-windows`
  - `python scripts\capture_meowcal_window.py`

## Working Notes
- The repo may contain local generated or user-authored changes. Do not revert unrelated work.
- When changing the shared studio markup, keep tests in `tests/test_overlay.py` aligned with the served contract.
- Studio subtitle search is provider-neutral; the main API/UI flow uses opaque `matchId` and `resultId` values instead of provider file ids.
- Prefer short rationale comments in non-obvious logic and hotspot flows. Do not add boilerplate comments to simple code.
- When debugging startup issues, separate three layers:
  - served page correctness
  - launcher/process correctness
  - actual Tauri/WebView2 desktop rendering

## Maintaining this guide
- Update this file when a task uncovers durable repo knowledge that will help future work.
- Update the main sections for stable facts:
  - runtime/source-of-truth paths
  - launcher behavior
  - verification commands
  - debugging workflow
- Update `Lessons Learned` for recurring traps and mistakes worth remembering.
- Do not add one-off session noise; keep additions short, durable, and actionable.

## Lessons Learned
- Browser automation in this harness validates the served Chromium page at `http://127.0.0.1:8765/`, not the actual Tauri/WebView2 desktop window.
- A browser pass is not enough to prove a desktop rendering fix. Desktop-only issues still need real shell verification.
- `python scripts\run_dashboard_smoke.py` is the lightweight served-page smoke path; it validates the dashboard contract but not native Tauri rendering.
- The smoke script should fail rather than silently reuse an already-running dashboard, or it can false-green against stale code on port `8765`.
- This Codex harness can launch Windows apps through shell or URI handlers and can inspect the real desktop app with OS-level screenshots or `scripts/capture_meowcal_window.py`.
- Treat that desktop visibility as a visual inspection capability, not as proof of stable native GUI interaction parity with browser automation.
- Generic active-window OS screenshots can show a black WebView2 surface even when the app is visible; `scripts/capture_meowcal_window.py` is currently the more reliable path for Meowcal desktop captures.
- Relaunching the desktop shell can reuse stale `meocosub2.cli serve` workers on port `8765` if the launcher does not kill them first.
- WebView2 can appear stale during debugging; Vite emits hashed asset URLs under `static/assets/`, so hard-reloading or relaunching the shell after a rebuild is usually enough to break stale-asset symptoms.
- The desktop shell appends a `desktopLaunch` cache-buster when navigating to `/`, and the server marks `index.html` as `no-store`; keep both if WebView2 starts showing an older React bundle after `run_app.vbs`.
- For desktop UI bugs, verify the runtime path before changing the wrong file. The shared `/` route (served from the Vite bundle in `static/`) is the one that matters.
- For real desktop UI inspection, a window-level screenshot helper is more trustworthy than browser-only automation against the served page.
- Tauri will create duplicate tray icons on Windows if the shell uses both `app.trayIcon` in `tauri.conf.json` and a manual `TrayIconBuilder` in Rust. Keep only one creation path.
- Windows OCR capability lookup for this app should use exact BCP-47 tags such as `zh-TW` in the `Language.OCR*<tag>*` query, and the UI should treat post-install re-enumeration as the success signal instead of assuming the installer succeeded.
- `SubDL` is integrated from public structured page data, while `ASSRT` is more reliable through its token-based API than raw page scraping.
- `SubDL` language buckets can arrive as encoding-style keys like `big_5_code` or `gb_code`; normalize separator variants before mapping them to `zht` / `zh` or Chinese results may disappear from the studio search UI.
- This machine runs Windows at 125% scale. Anything reading window bounds must set per-monitor DPI awareness first, or coordinates are scaled and captures come back cropped and offset.
- The selector reports CSS pixels inside its own fullscreen window; the shell converts them with the monitor's scale factor and origin. Compare a stored `capture.region` against a real drag before trusting a coordinate change.
- Driving the real desktop through `SendInput` and `ImageGrab` is the way to verify Tauri-only behavior end to end; browser automation cannot reach the selector, the HUD, or the live strip.
- A full-viewport shell with `overflow: hidden` is still a scroll container: anything reaching past its edge (the decorative glows do) lets a focus call scroll the whole app sideways with no scrollbar to undo it. Use `overflow: clip`.
- Only animate interpolable properties. Transitioning `transform` while `left`/`right`/`width: auto` snap between layouts throws the element a full width off-screen for the duration.
- The studio window loads from `http://127.0.0.1:<port>/`, so Tauri capabilities scoped to local pages do not cover it. Core permissions such as `core:event:allow-listen` need a capability with a `remote` URL scope, or `event.listen` is rejected at runtime while custom `invoke` commands keep working.
- A Tauri command returning `Ok(())` resolves to `null` in JavaScript. Use `isTauri()` to detect the shell; a `null` result proves nothing.
- `frontendDist` assets (`selector.html`, `selector.js`) are embedded into the shell binary at compile time. Editing them needs a `cargo build`, not just an npm build.
