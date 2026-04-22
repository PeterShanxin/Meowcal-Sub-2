# Meowcal-Sub-2 Developer Guide

## Repo Shape

- Python backend entrypoint: `python -m meocosub2.cli serve`
- Served dashboard: `src/meocosub2/overlay/server.py`
- Dashboard HTML: `src/meocosub2/overlay/static/index.html`
- Dashboard JS entrypoint: `src/meocosub2/overlay/static/app.js`
- Dashboard JS modules: `src/meocosub2/overlay/static/app-*.js`
- Subtitle-source logic: `src/meocosub2/subtitle_sources/`
- Session orchestration: `src/meocosub2/overlay/controller.py`
- Desktop shell: `src-tauri/src/main.rs`

The desktop app is still the same local server-backed UI wrapped by Tauri. The browser path and the Tauri path share the same dashboard contract.

## Source Of Truth

- Live runtime behavior should be read from code under `src/` and `src-tauri/`.
- `config.example.toml` is the current config-schema reference.
- `docs/plans/` is intentionally non-authoritative and repo-ignored.

## Frontend Module Map

- `app.js`: tiny browser entrypoint
- `app-bootstrap.js`: startup flow, websocket wiring, and bootstrap orchestration
- `app-shell.js`: render scheduling, loading shell, settings drawer, and Tauri hooks
- `app-language.js`: language normalization, pickers, OCR-language derivation, and language preference persistence
- `app-render.js`: read-model and DOM rendering for dashboard/results/session views
- `app-session.js`: search/prepare/start/stop/config event handlers
- `app-debug.js`: dashboard debug panel
- `app-dom.js` and `app-state.js`: shared DOM lookup and mutable UI state

Keep `app.js` as the stable entrypoint even when you move behavior between internal modules.

## Subtitle Studio Flow

1. Dashboard loads `/api/config`, `/api/state`, and `/api/languages`.
2. User searches for a title through `/api/search`.
3. The dashboard narrows choices by matched title, then source subtitle, then target subtitle or local translation.
4. `POST /api/session/prepare` creates either:
   - `subtitle_pair`
   - `ocr_fallback`
5. `POST /api/session/start` begins sync and pushes updates over `/ws/app` and overlay websocket channels.
6. `POST /api/session/stop` ends the active session and clears overlay state.

The current provider-neutral selection model uses opaque `matchId` and `resultId` values instead of provider file ids in the UI flow.

## Verification

Use these checks after changes:

```powershell
pytest -q
Get-ChildItem src\meocosub2\overlay\static\app*.js | ForEach-Object { node --check $_.FullName }
cargo check --manifest-path src-tauri\Cargo.toml
python -m playwright install chromium
python scripts\run_dashboard_smoke.py
```

Install Chromium once per machine before the smoke check. The Playwright smoke script validates the served dashboard path only, fails closed if another dashboard is already occupying port `8765`, and does not prove native WebView2 correctness inside Tauri.

## Commenting Guidance

- Add short rationale comments where the code preserves compatibility, coordinates cross-module state, or handles a non-obvious runtime constraint.
- Prefer comments that explain *why this branch exists* or *what invariant it protects*.
- Avoid “commenting every line” in straightforward code.
