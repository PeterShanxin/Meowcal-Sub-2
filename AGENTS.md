# AGENTS.md - Actively maintain and update this file

## Repo Overview
- Meowcal Sub 2 is a desktop subtitle studio with a Python backend and a Tauri shell.
- The live studio UI is served from `http://127.0.0.1:8765/`.
- The Windows launcher is `run_app.vbs`.

## Runtime Map
- Backend server: `python -m meocosub2.cli serve`
- Studio route: [src/meocosub2/overlay/server.py](src/meocosub2/overlay/server.py)
- Subtitle source aggregator: [src/meocosub2/subtitle_sources](src/meocosub2/subtitle_sources)
- Live studio page: [src/meocosub2/overlay/static/index.html](src/meocosub2/overlay/static/index.html)
- Shared studio logic: [src/meocosub2/overlay/static/app.js](src/meocosub2/overlay/static/app.js)
- Shared studio styles: [src/meocosub2/overlay/static/app.css](src/meocosub2/overlay/static/app.css)
- Tauri shell startup: [src-tauri/src/main.rs](src-tauri/src/main.rs)
- Tauri window config: [src-tauri/tauri.conf.json](src-tauri/tauri.conf.json)

## Source Of Truth
- Treat the server-backed `/` route as the real desktop runtime path.
- Make desktop studio UI fixes in `index.html`, `app.js`, and `app.css` first.
- Keep `desktop-main.html` in sync when markup changes, but do not treat it as the primary runtime path.

## Verification
- Run `pytest -q` after Python or server changes.
- Run `node --check src\meocosub2\overlay\static\app.js` after frontend JS changes.
- Run `cargo check --manifest-path src-tauri\Cargo.toml` after shell changes.
- For launcher debugging on Windows:
  - `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*meocosub2.cli serve*' }`
  - `Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -eq 8765 }`
  - `python scripts\capture_meowcal_window.py --list-windows`
  - `python scripts\capture_meowcal_window.py`

## Working Notes
- The repo may contain local generated or user-authored changes. Do not revert unrelated work.
- When changing the shared studio markup, keep tests in `tests/test_overlay.py` aligned with the served contract.
- Studio subtitle search is provider-neutral now; the main API/UI flow uses opaque `matchId` and `resultId` values instead of provider file ids.
- When debugging startup issues, separate three layers:
  - served page correctness
  - launcher/process correctness
  - actual Tauri/WebView2 desktop rendering

## Self Update
- Update this file when a task uncovers durable repo knowledge that will help future work.
- Update the main sections for stable facts:
  - runtime/source-of-truth paths
  - launcher behavior
  - verification commands
  - debugging workflow
- Update `Lessons Learned` for recurring traps and mistakes worth remembering.
- Do not add one-off session noise; keep additions short, durable, and actionable.

## Lessons Learned
- Browser automation in this harness validated the served Chromium page at `http://127.0.0.1:8765/`, not the actual Tauri/WebView2 desktop window.
- A browser pass is not enough to prove a desktop rendering fix. Desktop-only issues still need real shell verification.
- This Codex harness can launch Windows apps through shell or URI handlers and can inspect the real desktop app with OS-level screenshots or `scripts/capture_meowcal_window.py`.
- Treat that desktop visibility as a visual inspection capability, not as proof of stable native GUI interaction parity with browser automation.
- Generic active-window OS screenshots can show a black WebView2 surface even when the app is visible; `scripts/capture_meowcal_window.py` is currently the more reliable path for Meowcal desktop captures.
- Relaunching the desktop shell can reuse stale `meocosub2.cli serve` workers on port `8765` if the launcher does not kill them first.
- WebView2 can appear stale during debugging, so cache-busting shared asset URLs is useful when the desktop shell seems to ignore new `app.css` or `app.js`.
- For desktop UI bugs, verify the runtime path before changing the wrong file. The shared `index.html` route matters more than `desktop-main.html`.
- For real desktop UI inspection, a window-level screenshot helper is more trustworthy than browser-only automation against the served page.
- Tauri will create duplicate tray icons on Windows if the shell uses both `app.trayIcon` in `tauri.conf.json` and a manual `TrayIconBuilder` in Rust. Keep only one creation path.
- Windows OCR capability lookup for this app should use exact BCP-47 tags such as `zh-TW` in the `Language.OCR*<tag>*` query, and the UI should treat post-install re-enumeration as the success signal instead of assuming the installer succeeded.
- `SubDL` is currently integrated from public structured page data, while `ASSRT` is more reliable through its token-based API than raw page scraping.
