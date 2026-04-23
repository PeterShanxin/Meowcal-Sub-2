# Meowcal-Sub-2 Developer Guide

## Repo Shape

- Python backend entrypoint: `python -m meocosub2.cli serve`
- Served dashboard: `src/meocosub2/overlay/server.py`
- Studio UI source (Vite + React + TS): `src/meocosub2/overlay/ui/`
- Studio UI entry: `src/meocosub2/overlay/ui/src/app.tsx`
- Studio UI build output (served at `/`): `src/meocosub2/overlay/static/index.html` + `src/meocosub2/overlay/static/assets/`
- Subtitle-source logic: `src/meocosub2/subtitle_sources/`
- Session orchestration: `src/meocosub2/overlay/controller.py`
- Desktop shell: `src-tauri/src/main.rs`

The desktop app is still the same local server-backed UI wrapped by Tauri. The browser path and the Tauri path share the same dashboard contract.

## Source Of Truth

- Live runtime behavior should be read from code under `src/` and `src-tauri/`.
- `config.example.toml` is the current config-schema reference.
- `docs/plans/` is intentionally non-authoritative and repo-ignored.

## Frontend Module Map

Under `src/meocosub2/overlay/ui/src/`:

- `main.tsx`: React mount point.
- `app.tsx`: top-level state machine (`home` → `prep` → `live`, plus `settings` / empty / no-key variants). Bootstraps state via `/api/state`, `/api/config`, `/api/languages`, `/api/foundry/status`; wires the WebSocket; drives palette flow.
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
4. `POST /api/session/prepare` creates either:
   - `subtitle_pair`
   - `ocr_fallback`
5. `POST /api/session/start` begins sync and pushes updates over the `/ws/app` WebSocket (state, progress, subtitle, style, error, debug).
6. `POST /api/session/stop` ends the active session and clears overlay state.

When the user enters the live phase, the studio calls the Tauri `enter_live_mode` command; the main window reshapes into a bottom-of-screen always-on-top strip. `exit_live_mode` restores the pre-live geometry.

The current provider-neutral selection model uses opaque `matchId` and `resultId` values instead of provider file ids in the UI flow.

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
