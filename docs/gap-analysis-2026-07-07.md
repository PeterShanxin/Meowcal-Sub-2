# Gap Analysis — Current State vs. Goal State

**Date:** 2026-07-07
**Goal state:** the "v2 complete" criteria in [PRD.md §7](PRD.md#7-success-criteria-for-v2-complete).
**Method:** code survey, open PR review, live search runs against real providers, and mining of the real usage logs (`%APPDATA%/meowcal-sub-2/logs/`).

---

## 1. Where the product actually stands

The pipeline is **fully built**: multi-provider search + TMDB merge, episode/season hydration, three session modes, batch translation, OCR capture, CJK-aware fuzzy matching, auto-candidate lock-on, overlay, studio UI, Tauri shell, ~220 passing tests.

But the **usage evidence** tells a sharper story:

- Every `SYNC #` / live-loop line in every log file is a test fixture (`'Hello'` → `'你好'`). **No real live-sync session has ever been logged.**
- The real config still has `capture.region = []` — a capture region was never selected on this machine.
- The last real interactive use was **2026-05-25**: a search for "from" plus season hydration — exactly the scope of PR #22, which has been open (green, mergeable) ever since.

Conclusion: development has spent its entire effort budget inside the search stage. The downstream 70% of the product (prepare → capture region → live sync → overlay) is implemented and unit-tested but **has never been proven end to end with real video**. That is the single most important gap.

## 2. Gaps, prioritized

### P0 — Prove the core loop end to end (the actual blocker)

**Gap:** search quality iteration has become an infinite subgoal; the core bet of the product (OCR + fuzzy match against a downloaded subtitle) has never been validated in a real viewing session.

**Definition of done:** one full real session — search → pick episode → prepare → select region → play video → correct target lines appear — for each of:

1. an English-source movie (easy case: `Inception`),
2. a Chinese-source series episode (the real use case: `zh` OCR),
3. a no-target-subtitle case (translation fallback through Foundry Local).

**How to run it cheaply:** search is not even required — `meowcal-sub-2 start .\movie.en.srt --target-file .\movie.zh.srt` starts a sync session directly from local files. Play any clip with matching subtitles, select the region, and watch the debug panel (`[debug] mode = true`). Log grep patterns for diagnosis are in [AGENTS.md](../AGENTS.md#log-inspection).

Until this passes, further search-engine refinement has no measurable payoff.

### P0 — Merge or close PR #22

**Gap:** [PR #22](https://github.com/PeterShanxin/Meowcal-Sub2/pull/22) (durable season hydration) has been green and mergeable since 2026-05-25. The repo's mainline is six weeks behind the working branch, which blocks clean follow-up work.

### P1 — Search latency (partially fixed 2026-07-07)

**Evidence:** live run of `Inception` took **47.8 s**; breakdown: SubDL 42.3 s (for zero results), OpenSubtitles 10.7 s, ASSRT 1.6 s, TMDB enrichment 5.4 s. The aggregator waited for the slowest provider.

**Fixed in this pass:**

- Per-provider search budget (`[subtitle_sources] provider_timeout_s`, default 20 s). A slow provider is dropped with a visible warning ("SubDL: search timed out after 20s; other sources were still used.") instead of stalling the whole search. Verified live: 47.8 s → 24.7 s with SubDL degraded.

**Still open:**

- OpenSubtitles fans out ~38 HTTP calls per search (~5–11 s). Candidates: trim `/features` lookups, cache, or defer non-first-page work.
- SubDL routinely needs > 20 s when its API is degraded (1 list call + up to 5 detail calls at 7–21 s each). Options: fewer detail fetches, shorter per-call HTTP timeout so the budget covers more calls, or partial-result return.
- No progressive rendering: the UI sees nothing until every provider finishes. Streaming provider results as they arrive would beat any backend tuning for perceived speed.

### P1 — SubDL returned zero results for movies (fixed 2026-07-07)

**Evidence:** all SubDL detail calls returned HTTP 200 with 0 subtitles. Live-API bisection showed `full_season=1` makes SubDL return an empty subtitle list for movie `sd_id` queries. The provider sent it unconditionally.

**Fixed:** `full_season=1` is now sent only for TV items ([subdl.py](../src/meocosub2/subtitle_sources/subdl.py)), with a regression test. This also removes the "ghost works" (`Inception ()` with 0 subs) that SubDL matches used to inject into the works list.

### P2 — SubDL/ghost work merge quality

SubDL title matches carry `year: null` (live API), so a SubDL work that does not get TMDB-identified fails to fold into the matching OpenSubtitles work and renders as a separate entry with no year. Mostly masked now that movie results parse again, but the fold key deserves a look (IMDb/TMDb id is present on SubDL matches and should dominate).

### P2 — Search test suite vs. live API drift

The `full_season` bug shipped with a green test suite: tests encoded the app's assumption, not SubDL's behavior. There is no scheduled live-API contract check. A tiny opt-in smoke script (one real query per provider, assert non-zero parse) run manually before releases would catch provider drift; document it rather than wiring it into CI (keys, flakiness).

### P2 — Full pytest run intermittently hangs

A clean `pytest -q` run takes ~14 s (218 tests). But one run in this session hung for >15 minutes and had to be killed, and the app log captured a real `TMDb /search/tv returned 500` during a test run — suggesting at least one test can escape its mocks and hit the live network, hanging when the network misbehaves. Worth auditing TMDb-adjacent tests for unmocked HTTP paths.

### P3 — Docs/product framing (fixed 2026-07-07)

There was no PRD or current-state architecture doc; the only design doc was the outdated CLI-era one in the predecessor repo. Added [PRD.md](PRD.md) and [ARCHITECTURE.md](ARCHITECTURE.md); README now links them.

## 3. Recommended order of work

1. **Merge PR #22** (green since May), then land this session's fixes (SubDL movie fix + provider budget + docs).
2. **Run the three P0 end-to-end sessions** with real video. File concrete bugs from what breaks — those bugs, not search polish, define the remaining work.
3. Fix what the E2E sessions surface (likely candidates: capture-region selector flow, OCR language handling for zh, matcher thresholds under real OCR noise, Foundry warm-up UX).
4. Only then return to search-engine niceties (progressive results, OpenSubtitles call-count reduction, SubDL partial results).

## 4. What was verified in this pass (2026-07-07)

- `pytest -q`: full suite green (including 2 new regression tests).
- Live search `Inception` (en→zht): correct #1 work, 990 subs; latency 47.8 s → 24.7 s after fixes.
- Live search `from` (zh→en): correct #1 work (`From` 2022–2026 series, 40 episode skeleton); SubDL degradation now degrades gracefully with a user-visible warning.
- SubDL live-API bisection: `full_season=1` + movie `sd_id` → 0 subtitles (root cause of P1 bug); fix verified against the live API shape.
