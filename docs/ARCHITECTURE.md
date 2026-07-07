# Meowcal-Sub-2 — Architecture (current state)

**Last updated:** 2026-07-07
**Audience:** developers/agents working on this repo. Describes what is actually built, at file level. Product intent lives in [PRD.md](PRD.md).

---

## 1. System Overview

```
                        ┌─────────────────────────────────────────────┐
                        │                Tauri shell (optional)       │
                        │   src-tauri/src/main.rs                     │
                        │   wraps the served UI in WebView2, adds     │
                        │   live-mode strip, capture HUD, tray        │
                        └──────────────────┬──────────────────────────┘
                                           │ http://127.0.0.1:8765
┌───────────────┐   REST + WebSocket  ┌────┴─────────────────────────┐
│ Studio UI     │◄───────────────────►│ FastAPI server               │
│ (React+Vite)  │  /api/*  /ws/app    │ overlay/server.py            │
│ overlay/ui/   │                     └────┬─────────────────────────┘
│ built into    │                          │
│ overlay/static│                     ┌────┴─────────────────────────┐
└───────────────┘                     │ AppController                │
┌───────────────┐                     │ overlay/controller.py        │
│ Overlay page  │◄─── /ws (subtitle)──│  - search / hydrate          │
│ /overlay      │                     │  - prepare (3 modes)         │
└───────────────┘                     │  - start/stop sync           │
                                      └──┬──────────┬───────────┬────┘
                                         │          │           │
                     ┌───────────────────┴──┐  ┌────┴────────┐ ┌┴──────────────┐
                     │ SubtitleSearch-      │  │ sync.py     │ │ translator.py │
                     │ Aggregator           │  │ 3 loops:    │ │ Foundry Local │
                     │ subtitle_sources/    │  │ pair/auto/  │ │ (openai SDK,  │
                     │  - opensubtitles     │  │ ocr-fallback│ │ 5-line batch) │
                     │  - subdl             │  └──┬───────┬──┘ └───────────────┘
                     │  - assrt             │     │       │
                     │  - tmdb (identity,   │  ┌──┴───┐ ┌─┴─────────┐
                     │    posters, seasons) │  │capture│ │ matcher.py│
                     └──────────────────────┘  │ .py   │ │ rapidfuzz │
                                               │mss+   │ │ windowed  │
                                               │winocr │ └───────────┘
                                               └───────┘
```

Everything runs locally. The only network calls are to subtitle providers, TMDB, and the local Foundry endpoint.

## 2. Module Map (Python backend, `src/meocosub2/`)

| Module | Responsibility |
|--------|---------------|
| `cli.py` | Typer entry points: `search`, `download`, `translate`, `start`, `run`, `gui`, `serve`. `gui`/`serve` boot the FastAPI app; `start` runs a sync session directly from local subtitle files (no search needed). |
| `config.py` | TOML config load/save (`%APPDATA%/meowcal-sub-2/config.toml`), legacy `[opensubtitles]` alias, payload mapping for the settings UI. |
| `models.py` | Dataclasses: `SubtitleLine`, `SubtitlePair`, `MatchResult`, `SearchRequest`, `PreparedSession`, `PreparedRuntime`, `AppStateSnapshot`, `AppProgress`, `SourceSubtitleCandidate`. |
| `subtitles.py` | pysubs2 parsing (.srt/.ass/.ssa, encoding fallbacks), `align_subtitles`, `assign_target_translations` (time-overlap based pairing). |
| `matcher.py` | `SubtitleMatcher` — see §5. |
| `capture.py` | `mss` region capture + `winocr` OCR; OCR language catalog/resolution/installation helpers. |
| `sync.py` | The three live loops — see §6. |
| `translator.py` | Foundry Local batch translation (numbered 5-line prompts, rolling 3-line context, output sanitization, per-line fallback to source text). |
| `foundry.py` | Foundry service/model detection and warm-up (`make_foundry_ready`). |
| `languages.py` | Language code normalization, Chinese-family logic (`zh`/`zhs`/`zht` handling), OCR-tag mapping. |
| `textnorm.py` | CJK cleaning, traditional→simplified folding (OpenCC), compactable-char detection. |
| `titleutil.py` | Title canonicalization helpers shared by search ranking. |
| `errors.py` | Error hierarchy (`SubtitleSourceError`, `TranslationError`, …). |
| `event_log.py` | Structured JSONL event log (`%APPDATA%/meowcal-sub-2/logs/meowcal-sub-2.events.jsonl`) with correlation ids. |
| `opensubtitles/` | Low-level OpenSubtitles REST client (search/features/download, rate-limit handling, org-mirror fallback). |
| `devtools/window_capture.py` | Window-level screenshot helper used by `scripts/capture_meowcal_window.py` for desktop-shell debugging. |

## 3. Subtitle Source Layer (`subtitle_sources/`)

- `types.py` — provider-neutral result model: `ProviderSubtitleResult` → aggregated into `AggregatedSubtitleResult`, `AggregatedTitleMatch`, `AggregatedWork` (with `AggregatedSeason`/`AggregatedEpisode`), all addressed by opaque `matchId` / `resultId` (UI never sees provider file ids).
- Providers (each implements `SubtitleSourceProvider`):
  - `opensubtitles.py` — REST API (`/subtitles`, `/features`), episode direct lookup for season queries, parent-series identity propagation.
  - `subdl.py` — SubDL public API; normalizes encoding-style language buckets (`big_5_code`, `gb_code` → `zht`/`zh`); tolerates partial detail-fetch failures.
  - `assrt.py` — ASSRT token API; infers parent titles/episode metadata from filenames and filelists (Chinese-content strength).
  - `tmdb.py` — not a subtitle source: TMDB identity resolution (IMDb/TMDb ids), posters, and season/episode catalogs.
  - `season_skeleton.py` — builds placeholder ("skeleton") episode grids from TMDB season data so series render completely before per-episode subtitle lists are fetched.
- `aggregator.py` — fans out to enabled providers concurrently, merges works via TMDB identity, folds series duplicates, ranks (title similarity + year + media-type intent + provider rank + download counts), produces per-work info chips and provider warnings. Query aliases handle known-bad searches. Search returns an `AggregatedSearchCatalog` cached on the controller for the follow-up prepare/hydrate calls.
- **Hydration:** episode and season subtitle lists are fetched lazily. `controller.hydrate_episode` / `hydrate_season` re-query providers scoped to the series identity and merge results into the cached catalog, guarded by work-identity checks (IMDb/TMDb id match, year range) so a generic title cannot pollute the selected work.

## 4. Session Lifecycle (`overlay/controller.py`)

State machine held by `AppController` (single instance, asyncio-locked):

1. **search** (`/api/search`) → `SubtitleSearchAggregator.search_catalog` → catalog cached; works/matches/results payloads pushed to UI.
2. **hydrate** (`/api/search/episode`, `/api/search/season`) → lazy per-episode/season provider queries merged into the catalog.
3. **prepare** (`/api/session/prepare`, one of three modes):
   - `subtitle_pair` — download source (+ optional target) via aggregator; parse; if no target: warm Foundry and `translate_lines` with progress; `align_subtitles` → `PreparedRuntime`.
   - `auto_candidates` — top 3 source candidates for the selected title + best target file; each candidate parsed into its own `SubtitlePair`; target translations assigned where timing overlaps.
   - `ocr_fallback` — optional target file only; live translation planned at runtime.
4. **start** (`/api/session/start`) → spawns the matching loop from `sync.py` as an asyncio task; overlay updates flow over `/ws` (overlay) and `/ws/app` (studio state/progress/debug).
5. **stop** (`/api/session/stop`) → cancels the task, clears overlay.

Errors surface via `AppStateSnapshot.error_message` and WebSocket `error` events; progress via `AppProgress` (download/translation stages).

## 5. Matcher (`matcher.py`)

- Normalization at build time: strip formatting tags/brackets, lowercase, collapse whitespace; CJK lines additionally cleaned and (unless target is `zht`) folded to simplified.
- Per frame:
  1. Skip frames whose normalized OCR hash equals the previous frame (dedup).
  2. Skip too-short text (<3 ASCII chars; single CJK char allowed).
  3. Windowed search: `[last−5 … last+30]` (configurable); first-time window `[0 … 35]`; full-scan fallback on window miss.
  4. Scorer: `fuzz.WRatio` for CJK (space-stripped CJK degenerates under token scorers), `fuzz.token_set_ratio` otherwise; cutoff = `fuzzy_threshold` (default 65).
- Returns `MatchResult(line_index, score, source_text, target_text)`.

## 6. Sync Loops (`sync.py`)

| Loop | Used by mode | Behavior |
|------|--------------|----------|
| `run_sync_loop` | `subtitle_pair` | capture → OCR → match → broadcast target text when the matched line changes. |
| `run_auto_candidate_sync_loop` | `auto_candidates` | Runs one matcher per candidate. Lock-on: score ≥ 92 instantly, or 2 consistent best-candidate hits; unlock after 3 consecutive misses (repeat frames don't count). Missing per-line translations are translated on demand through Foundry with an LRU cache. |
| `run_ocr_fallback_loop` | `ocr_fallback` | OCR → dedupe → translate via Foundry (rolling 3-line context, 32-entry cache) → optionally snap to a target-file line when it fuzzy-matches → broadcast. |

All loops honor `capture.interval_ms` (default 1500 ms), log per-iteration diagnostics (`SYNC #`, `AUTO match`, `MATCH hit/miss/skip`), and feed the opt-in debug panel via a debug broadcast callback.

## 7. Server & Frontends

- `overlay/server.py` — FastAPI app: serves the built React studio at `/` (no-store on `index.html`), overlay page at `/overlay`, REST under `/api/*` (state, config, languages, search, hydrate, session, foundry, OCR-language install), WebSockets at `/ws` (overlay subtitles/styles) and `/ws/app` (studio events).
- Studio UI (`overlay/ui/`, Vite + React + TS): `app.tsx` state machine (`home` → `prep` → `live`), ⌘K command palette as the primary picker, settings drawer, live dock. Build output is committed under `overlay/static/` and served directly. See [developer-guide.md](developer-guide.md) for the frontend module map.
- Tauri shell (`src-tauri/`): WebView2 window over the same served URL, `enter_live_mode`/`exit_live_mode` window reshaping, capture-region selector and HUD sub-windows (`static/selector.*`, `static/capture-hud.*`), single tray icon, `desktopLaunch` cache-buster.
- `run_app.vbs`: Windows launcher — starts/reuses the backend, opens the Tauri shell if built, otherwise falls back to `pythonw` GUI mode.

## 8. Configuration

Single source of truth: `config.example.toml`. Sections: `subtitle_sources.{opensubtitles,subdl,assrt,tmdb}`, `languages`, `capture`, `matching`, `translation`, `overlay`, `debug`. Legacy top-level `[opensubtitles]` still loads. Config edits flow through the settings drawer → `/api/config` → `save_config`.

## 9. Observability

- Rotating debug log: `%APPDATA%/meowcal-sub-2/logs/meowcal-sub-2.log` (always DEBUG). Grep patterns documented in [AGENTS.md](../AGENTS.md#log-inspection).
- Structured events: `meowcal-sub-2.events.jsonl` — provider HTTP calls, search/aggregation timings, session lifecycle, launcher/boot events; correlation ids tie a search to its provider calls.
- Opt-in dashboard debug panel (`[debug] mode = true`): last 20 sync iterations live.

## 10. Testing & Verification

- `pytest -q` — unit + API-level tests (~215), including provider contract tests with mocked HTTP (`respx`), controller flows, matcher/CJK cases, overlay contract.
- `npm --prefix src/meocosub2/overlay/ui run build` — rebuild studio bundle (required after UI changes; output is committed).
- `cargo check --manifest-path src-tauri/Cargo.toml` — shell.
- `python scripts/run_dashboard_smoke.py` — Playwright smoke of the served dashboard (fails closed if port 8765 is already occupied).
- `scripts/capture_meowcal_window.py` — desktop-shell screenshot verification (WebView2 rendering cannot be proven by browser automation).

## 11. Known Design Tensions

- **Committed build output** (`overlay/static/assets/`) keeps the server self-contained but makes PR diffs noisy and stale-bundle bugs possible (mitigated by no-store + cache-buster).
- **Search latency**: fan-out + TMDB enrichment costs seconds on broad queries (observed ~10 s worst case); hydration was made lazy to compensate.
- **OCR cadence vs. subtitle rhythm**: 1.5 s polling can straddle short lines; timing-based interpolation between OCR ticks is a known post-v2 idea, not implemented.
- **Provider fragility**: SubDL/ASSRT behaviors (partial 403s, encoding-key language buckets, filename-only metadata) are handled case-by-case; new failure shapes surface as search warnings rather than hard failures.
