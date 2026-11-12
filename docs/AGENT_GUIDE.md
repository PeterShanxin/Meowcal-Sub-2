# Agent Guide

## Repo Overview
- Meowcal Sub 2 is a desktop subtitle studio with a Python backend and a Tauri shell.
- The live studio UI is served from `http://127.0.0.1:8765/` (the default `[overlay] port`).
- [The developer guide](developer-guide.md) covers setup, run modes, the runtime
  map, storage locations, and release applicability.
- The Windows launcher is `run_app.vbs`.

## Runtime Map
- Backend server: `python -m meocosub2.cli serve`
- Studio route: [src/meocosub2/overlay/server.py](../src/meocosub2/overlay/server.py)
- Subtitle source aggregator: [src/meocosub2/subtitle_sources](../src/meocosub2/subtitle_sources)
- Capture loop and session strategies: [src/meocosub2/sync.py](../src/meocosub2/sync.py)
- Managed local translation adapter: [src/meocosub2/engine](../src/meocosub2/engine)
- Shared runtime contract: [docs/MEOWCAL_CORE.md](MEOWCAL_CORE.md)
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

Treat every artifact as maintainer-owned, not as a trace of an AI session. This
applies to code, comments, documentation, PR and issue text, UI copy,
architecture, configuration, and handoff notes.

- Do not narrate the prompt, agent, implementation journey, discarded
  approaches, or direction changes unless future maintainers need that
  rationale.
- Do not add boilerplate prose, obvious comments, duplicate summaries or rules,
  ceremonial files or checklists, or placeholder documentation merely to make a
  change look complete.
- Do not introduce wrappers, abstractions, fallbacks, compatibility paths,
  feature flags, or configuration "just in case". Each extra mechanism must
  satisfy a current requirement or documented risk.
- Prefer direct code and concise human-quality prose. Comments should explain
  non-obvious reasons, invariants, or trade-offs rather than restating the code.
- Current docs, UI copy, PRs, and issues should state current behavior directly.
  Put history in issues, ADRs, changelogs, or dated plans unless it is required
  to apply a live safety, compatibility, or unsupported-behavior boundary.
- Before handoff, inspect the diff specifically for AI slop and remove words,
  files, layers, and indirection that add neither required behavior nor durable
  information.

## Coding standards

[`docs/CODING_STANDARDS.md`](CODING_STANDARDS.md) is normative for what the code
has to look like. [`docs/MAINTAINABILITY_BASELINE.md`](MAINTAINABILITY_BASELINE.md)
owns the measured limits that `scripts/verify.ps1` enforces.

## Product behavior

[The developer guide](developer-guide.md#runtime-contracts) owns the runtime
contracts: subtitle discovery, playback timing and presentation, session modes,
subtitle checks and editing, cancellation, and process ownership.
[MEOWCAL_CORE.md](MEOWCAL_CORE.md) owns OCR engine selection and the Core
protocol. Change those documents in the same PR as the behavior.

## Log Inspection

- Log file: `%APPDATA%\meowcal-sub-2\logs\meowcal-sub-2.log` (INFO by default),
  rotated daily with seven previous files kept. Explicit
  `python -m meocosub2.cli --verbose serve` enables DEBUG OCR/subtitle traces.
  Normal logs can still contain titles, errors, and sensitive details; use
  synthetic viewing content and sanitize excerpts before sharing.
- Event log: `meowcal-sub-2.events.jsonl` beside it, one JSON record per line
  from the backend, the shell and the launcher. At 5 MiB the backend renames it
  to `meowcal-sub-2.events.jsonl.1`, replacing the previous one, so a window
  that spans a rotation needs both files.
- Key patterns to grep. All of them are DEBUG lines, so they need `--verbose`:
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
  match are placed by the playback clock instead (see
  [playback timing](developer-guide.md#playback-timing-and-presentation)).
- If OCR text looks garbled → wrong capture region, OCR language, or OCR engine;
  check `capture.region` and `capture.ocr_engine` in config, and the
  `ocr.engine.ready` event, which names the requested and the resolved engine.
  Engine selection and passes are described in
  [MEOWCAL_CORE.md](MEOWCAL_CORE.md#ocr-engine-selection).
- If OpenSubtitles returns 0 results → grep `OS /subtitles params=` to confirm the
  language codes (`zh-cn` for Simplified Chinese, `zh-tw` for Traditional) and
  `parent_feature_id` are present.
- `[debug] mode = true` (**Settings → Debug**) makes the running session send a
  `debug` event per capture iteration on `/ws/app`. The studio does not render
  these events; read them from the WebSocket.
- The studio requires a per-run token. Read it from `%APPDATA%/meowcal-sub-2/runtime.json` and send it as `X-Meowcal-Token`, or open `/?token=...`. Unauthenticated requests get 401, foreign origins 403.

## Verification

- The shell reuses whatever backend already answers on port 8765 rather than
  spawning its own. Rebuilding and relaunching the shell therefore does **not**
  pick up Python changes — stop the `python.exe` running the backend first, or
  the session under test is still running the old code.

### Stopping the app without leaking the engine

The backend owns separate Core processes for OCR and HY-MT inference. Core owns
its `llama-server.exe` child and installation lease. Closing the transport,
timeout, cancellation, or application shutdown ends that owned process tree.
Windows job objects cover abnormal exits; a failed lifetime attachment must
prevent launch from continuing. BGE has its own Sub 2 process lifetime.

Stop a session the way the app does: `POST /api/session/stop`, then the shell's
own Stop control or closing its window. After stopping, and before launching
again, confirm nothing survived:

```powershell
Get-Process llama-server, meowcal-core, meowcal-sub-2-shell -ErrorAction SilentlyContinue |
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
[`.github/workflows/windows-ci.yml`](../.github/workflows/windows-ci.yml) runs
the same full script on main and on every PR that changes more than prose.
The required `Verify x64` and `Verify ARM64` checks stay present on prose-only
PRs, but run routing regression tests and a whole-PR whitespace check instead.
`scripts/ci_scope.py` owns the Markdown allowlist; scripts, tests, assets,
workflows, manifests, deletions and uncertain comparisons require full CI.
Classification compares the checked-out merge against its verified base parent,
so a final README-only commit cannot hide an earlier code change.

CI covers the minimum Python 3.11 on x64 and the packaged Python 3.14.7 on
ARM64, with Node 22 on both. CI installs only Playwright's headless shell.

Prerequisites, once per machine:

```powershell
python -m pip install -e ".[dev]"
npm --prefix src\meocosub2\overlay\ui install
python -m playwright install chromium
rustup component add rustfmt clippy
```

`-Stage <name>` runs part of it while iterating; `-List` names the stages. A
full run is the authoritative result.

### Dependency updates

[`.github/dependabot.yml`](../.github/dependabot.yml) opens monthly grouped
minor/patch PRs per ecosystem and a separate PR per major update. Two committed
outputs must be regenerated on the PR branch before CI passes:

- `config/backend-requirements.txt` is the hash-locked wheel set both Windows
  packages embed. `python scripts\lock_backend_requirements.py` resolves it from
  `pyproject.toml` for win_amd64 and win_arm64, holding current pins; it needs
  Windows Python at the packaged minor version (3.14), because pip evaluates
  markers against the running interpreter. `--upgrade-package NAME` releases
  one pin. `--check` is the `verify.ps1` gate wherever `python` is that version,
  including the ARM64 CI job.
  The ARM64 CI job installs this lock before the dev extras, so its tests run
  the versions that ship.
- The studio bundle in `static/` must match a rebuild from the lockfile:
  `npm --prefix src\meocosub2\overlay\ui run build`.

Core and the embedded CPython are not Dependabot ecosystems; they change only
through their own locks and reviewed upgrade flow.

`config/meowcal-core.lock.json` is checked in, so CI and `verify.ps1` verify
against the released Core artifacts it pins. CI uses the source candidate in
`config/meowcal-core.candidate.json` (through `verify.ps1 -CoreCandidateSource`)
only when no release lock exists. Every Tauri development or production build
requires the reviewed release hashes enforced by `fetch-meowcal-core.ps1`.

What it cannot prove: OCR on real video, WebView2 rendering, the capture
selector, and the overlay plate. Those need a real Windows run of the app. The
[developer guide](developer-guide.md#what-each-layer-proves) lists what each
validation layer proves and how to record measurements.

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
- Prefer short rationale comments in non-obvious logic and hotspot flows. Do not add boilerplate comments to simple code.
- When debugging startup issues, separate three layers:
  - served page correctness
  - launcher/process correctness
  - actual Tauri/WebView2 desktop rendering

## Documentation maintenance

A change that alters documented behavior updates that documentation in the same
PR. Use this map:

| The change affects | Update |
| --- | --- |
| User workflows, controls, settings, messages, or troubleshooting | [user-guide.md](user-guide.md), and [README.md](../README.md) when its summary changes |
| Data flow, configuration, interfaces, states, cancellation, recovery, storage, or process lifecycle | [developer-guide.md](developer-guide.md), or the specialized document that owns the contract |
| Core protocol, capabilities, OCR engines, models, or installation compatibility | [MEOWCAL_CORE.md](MEOWCAL_CORE.md); also [CORE_UPGRADE_AUTOMATION.md](CORE_UPGRADE_AUTOMATION.md) when the upgrade workflow changes |
| OCR, synchronization, performance method, metrics, or acceptance criteria | [OCR_BENCHMARK.md](OCR_BENCHMARK.md), [PLAYBACK_EVIDENCE.md](PLAYBACK_EVIDENCE.md), or [PLAYING_CONFIDENCE_CALIBRATION.md](PLAYING_CONFIDENCE_CALIBRATION.md) |
| Packaging, signing, updates, migration, or recovery | The build and release sections of [developer-guide.md](developer-guide.md), and the user guide's install and update text |
| Agent workflow, verification gates, or repository traps | This guide |

Each document owns its contract. Link to it from other documents; do not copy
it. Describe behavior on main separately from what the latest published release
contains (see [release applicability](developer-guide.md#release-applicability)).
Leave dated records (`docs/plans/`, `docs/audit-*/`, `CHANGELOG.md` entries)
as they were written.

Every delivery — a PR description, a handoff, or a final report — names the
documentation it updated, or states why the change has no documentation impact.

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

## Writing clarity

Follow [STE-inspired clarity](WRITING_GUIDE.md) for new or changed text and delivery
notes. This project-wide standard applies to human contributors and agents.
