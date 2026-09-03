# AGENTS.md

## Repo Overview
- Meowcal Sub 2 is a desktop subtitle studio with a Python backend and a Tauri shell.
- The live studio UI is served from `http://127.0.0.1:8765/`.
- The Windows launcher is `run_app.vbs`.

## Runtime Map
- Backend server: `python -m meocosub2.cli serve`
- Studio route: [src/meocosub2/overlay/server.py](src/meocosub2/overlay/server.py)
- Subtitle source aggregator: [src/meocosub2/subtitle_sources](src/meocosub2/subtitle_sources)
- Capture loop and session strategies: [src/meocosub2/sync.py](src/meocosub2/sync.py)
- Managed local translation engine: [src/meocosub2/engine](src/meocosub2/engine)
- Studio UI source (Vite + React + TS): [src/meocosub2/overlay/ui](src/meocosub2/overlay/ui)
- Studio UI entry: [src/meocosub2/overlay/ui/src/app.tsx](src/meocosub2/overlay/ui/src/app.tsx)
- Studio UI build output (served at `/`): [src/meocosub2/overlay/static/index.html](src/meocosub2/overlay/static/index.html) + `static/assets/`
- Tauri shell startup: [src-tauri/src/main.rs](src-tauri/src/main.rs)
- Tauri window config: [src-tauri/tauri.conf.json](src-tauri/tauri.conf.json)

## Source Of Truth
- Treat the server-backed `/` route as the real desktop runtime path.
- Edit React source under `src/meocosub2/overlay/ui/src/`; run `npm --prefix src/meocosub2/overlay/ui run build` to refresh `static/index.html` + `static/assets/`.
- Do not edit files under `static/assets/` directly — they are Vite build output.
- `static/splash.html`, `static/selector.*`, and `static/capture-hud.*` are hand-maintained Tauri sub-windows; those live outside the React app.
- `docs/plans/` is not authoritative for current behavior and should be ignored for maintenance work.

## Anti-slop quality bar
- Treat every artifact as maintainer-owned, not as a trace of an AI session. Apply this to code, comments, documentation, PR and issue text, UI copy, architecture, configuration, and handoff notes.
- Do not narrate the prompt, agent, implementation journey, discarded approaches, or direction changes unless future maintainers need that rationale.
- Do not add boilerplate prose, obvious comments, duplicate summaries or rules, ceremonial files or checklists, or placeholder documentation merely to make a change look complete.
- Do not introduce wrappers, abstractions, fallbacks, compatibility paths, feature flags, or configuration "just in case". Each extra mechanism must satisfy a current requirement or documented risk.
- Prefer direct code and concise human-quality prose. Comments should explain non-obvious reasons, invariants, or trade-offs rather than restating the code.
- Current docs, UI copy, PRs, and issues should state current behavior directly. Put history in issues, ADRs, changelogs, or dated plans unless it is required to apply a live safety, compatibility, or unsupported-behavior boundary.
- Before handoff, inspect the diff specifically for AI slop and remove words, files, layers, and indirection that add neither required behavior nor durable information.

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
- If OCR text in logs looks correct but misses dominate → lower `fuzzy_threshold` (try 55).
- If OCR text looks garbled → wrong capture region or OCR language; check `capture.region` in config.
- If subtitle search returns 0 results → grep `OS /subtitles params=` to confirm language codes (`zhs` for Simplified Chinese) and `parent_feature_id` are present.
- Live debug panel: set `[debug] mode = true` in config.toml, open the studio while a session is running; panel appears bottom-right showing the last 20 iterations.
- The studio requires a per-run token. Read it from `%APPDATA%/meowcal-sub-2/runtime.json` and send it as `X-Meowcal-Token`, or open `/?token=...`. Unauthenticated requests get 401, foreign origins 403.

## Verification

- Run `pytest -q` after Python or server changes.
- Run `npm --prefix src\meocosub2\overlay\ui run build` after studio UI changes (rebuilds `static/index.html` + `static/assets/`).
- Run `cargo check --manifest-path src-tauri\Cargo.toml` after shell changes.
- Run `python -m playwright install chromium` once per machine before the smoke script.
- Run `python scripts\run_dashboard_smoke.py` when you need a served-dashboard smoke check.
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
