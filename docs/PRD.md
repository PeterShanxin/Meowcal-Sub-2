# Meowcal-Sub-2 — Product Requirements Document

**Status:** Living document — describes the product goal state.
**Last updated:** 2026-07-07
**Companion docs:** [ARCHITECTURE.md](ARCHITECTURE.md) (how it is built), [user-guide.md](user-guide.md) (how to use it), [gap-analysis-2026-07-07.md](gap-analysis-2026-07-07.md) (distance from this goal state).

---

## 1. Problem

People watch video in players and browsers that either have no subtitles in their language or have hard-burned subtitles in a language they do not fully understand. Existing options fail them:

- **Player-native subtitle loading** does not work for streaming sites, hard-subbed video, or players without subtitle support.
- **Real-time machine translation of on-screen text** (the MeoCoSub1 approach: OCR every frame → local LLM translate → overlay) produces low-quality translations, because the models small enough to run on a local AI PC are not good enough, and every line pays the full translation-quality tax.

Meanwhile, for almost any popular show or movie, **high-quality human-made subtitles in many languages already exist on the internet**. The missing piece is not translation — it is *finding the right subtitle file and keeping it in time with what is on screen*.

## 2. Product Idea

Meowcal-Sub-2 is a Windows desktop subtitle studio that:

1. **Searches** multiple public subtitle sources for the show/movie the user is watching.
2. **Pairs** a source-language subtitle (matching what is visible/audible on screen) with a target-language subtitle (what the user wants to read).
3. **Syncs** to live playback by periodically OCR-ing the on-screen subtitle region and fuzzy-matching the recognized text against the source subtitle file — no player integration, no video-file access needed.
4. **Displays** the matched target-language line in an overlay strip on top of the video.

Machine translation is demoted from the primary mechanism to a **fallback**: it is used only when no target-language subtitle exists (batch-translate the source file up front via Foundry Local) or when no source subtitle matches at all (MeoCoSub1-style live OCR translation).

### Core bet

> Good OCR + good matching against internet subtitles beats local AI translation on quality, and covers the majority of real viewing because subtitle coverage for popular content is excellent.

## 3. Target User

- Windows user watching video in **any** player or browser (streaming sites, local files, anything that puts pixels on screen).
- Primary persona: watches content with hard-burned or spoken source language (e.g. Chinese or English) and wants subtitles in their preferred language (e.g. English or Traditional Chinese).
- Has (or can get) free API keys for subtitle providers; optionally runs Foundry Local for the translation fallback.
- Not expected to understand subtitle formats, provider APIs, or OCR tuning.

## 4. Goals and Non-Goals

### Goals

| # | Goal | Measure |
|---|------|---------|
| G1 | User finds the correct show (right title, right season/episode) in one search | First-page hit for popular titles; episode-level drill-down works for series |
| G2 | Session preparation "just works" once a title is picked | Prepare completes without manual file wrangling; auto mode picks candidates itself |
| G3 | Live sync shows the right target line within one capture interval of the source line appearing | Displayed line matches on-screen dialogue; latency ≤ capture interval (default 1.5 s) |
| G4 | Quality degrades gracefully | Missing target subs → batch translation; missing source subs → live OCR translation; never a dead end |
| G5 | Usable end-to-end by a non-technical user | Dashboard-only flow: search → pick → prepare → select region → start |

### Non-Goals

- **Not** a subtitle editor or authoring tool.
- **Not** a video player; never touches the video stream or file.
- **Not** real-time frame-perfect sync — a periodic (~1.5 s) OCR cadence is accepted.
- **Not** cross-platform in v2 (OCR depends on Windows `winocr`; Tauri shell is Windows-first).
- **No** cloud translation services — translation fallback is local-only (Foundry Local) by design.
- **No** scraping that violates provider terms — provider integrations use official/public APIs.

## 5. User Journey (goal state)

1. Launch via `run_app.vbs` (Tauri shell) or `meowcal-sub-2 gui` (browser dashboard).
2. Type the show title, set source/target languages, hit **Find Subtitles**.
3. Pick the show from a merged, deduplicated works list (with posters and season/episode drill-down for series).
4. Pick the exact episode; the studio shows source-language and target-language subtitle candidates from all providers, ranked.
5. Either pick a source+target pair manually, or accept **Auto** mode (the app keeps the top few source candidates and locks onto whichever matches the on-screen text best during playback).
6. **Prepare Session** — files download; if no target subtitle exists, the app batch-translates through Foundry Local with a progress bar.
7. Select the screen region where subtitles appear (once per player setup).
8. **Start Sync** — the overlay strip appears; the user plays their video normally.
9. The correct translated line appears and updates as playback proceeds, surviving pauses, small seeks, and OCR noise.
10. **Stop Session** when done.

## 6. Functional Requirements

### Search & catalog (the "find the right subtitles" engine)

- Aggregate results from OpenSubtitles, SubDL, and ASSRT (each individually toggleable, keys stored in local config).
- Merge per-provider results into deduplicated **works** using TMDB identity (IMDb/TMDb ids), with posters and season skeletons for series.
- Rank works by title similarity, year match, media-type intent, and provider quality; support query aliases for hard cases.
- Series drill-down: seasons → episodes, with on-demand hydration of episode- and season-level subtitle lists (skeleton episodes fill in when the user expands them).
- Surface provider warnings (missing/invalid keys, provider outages) in the UI without failing the whole search; redact secrets in all logs and messages.

### Session preparation

- Three modes:
  - `subtitle_pair` — explicit source + target files; align pairs line-by-line.
  - `auto_candidates` — top N source candidates + best target; runtime lock-on decides the real match.
  - `ocr_fallback` — no usable source subtitle; live OCR translation (MeoCoSub1 behavior), optionally guided by a target-language file.
- When a target-language file is missing, batch-translate source lines via Foundry Local (5-line batches, rolling context, output sanitization, progress reporting).
- Provider downloads honor per-provider quota/rate limits with clear errors.

### Live sync

- Capture configured screen region every `interval_ms` (default 1500), OCR via Windows OCR with configurable language.
- Fuzzy-match OCR text against the source subtitle file: windowed search (default 30 ahead / 5 back), full-scan fallback, CJK-aware normalization (tag stripping, traditional→simplified folding, WRatio scorer for CJK).
- Auto mode: score all candidate files, lock on at score ≥ 92 or after 2 consistent hits, unlock after 3 consecutive misses.
- Broadcast the target line over WebSocket to the overlay; skip rebroadcast of the same line; fade the overlay when no match persists.
- Debug panel (opt-in) shows per-iteration OCR text, match index/score, and timing.

### Overlay & shell

- Browser overlay page (`/overlay`) styled by config (font, colors, glass theme, position, animation).
- Tauri desktop shell wraps the same served UI; live mode reshapes the window into a bottom-of-screen always-on-top strip with a capture HUD.
- All state served from the local FastAPI backend on `127.0.0.1:8765`; browser-only usage (no shell) must remain fully functional.

### Configuration & observability

- Single TOML config at `%APPDATA%/meowcal-sub-2/config.toml`; editable from the settings drawer; legacy section aliases keep loading.
- Rotating debug log plus structured JSONL event log (search, provider, session lifecycle) for diagnosis.

## 7. Success Criteria for "v2 complete"

The product is complete when a user can, **without touching a terminal or config file**:

1. Search a currently-airing popular series, find the right episode on the first results page,
2. prepare a session in under a minute (excluding translation fallback),
3. start sync and see correct target-language lines for a full episode with match hit-rate high enough that missed lines feel rare (goal: >90% of dialogue lines displayed correctly in a normal-quality capture setup),
4. and repeat this across at least: one English-source movie, one Chinese-source series episode, and one no-target-subtitle case exercising translation fallback.

Anything beyond that (more providers, non-Windows OCR, timing-based prediction between OCR ticks) is post-v2.

## 8. History / Context

- **MeoCoSub1** (`D:/Repos/Meowcal-Sub`, Tauri 2 + Rust): real-time OCR → local LLM translate → overlay. Worked, but translation quality was capped by small local models. Kept as the fallback behavior inside v2.
- **MeoCoSub2 pivot (2026-03):** replace per-frame translation with *retrieve-and-sync* against existing internet subtitles. Original design doc: `D:/Repos/Meowcal-Sub/docs/plans/2026-03-04-meocosub2-design.md` (CLI-first; superseded by the studio UI — see ARCHITECTURE.md for what is actually built).
- **2026-04 → 2026-05:** studio UI (React + Tauri), provider aggregation, TMDB merge, episode/season hydration hardening (PRs #13–#22).
