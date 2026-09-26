# Performance audit, 2026-09-26

Benchmarks for the two flows a viewer waits on every time:

1. **Opening the studio** - shell starts the backend, waits for it, navigates
   to the studio; the search palette is the first thing a viewer uses.
2. **Preparing a session** - after choosing a source and a target subtitle,
   `prepare_session("subtitle_pair")` loads both files, weighs up to three
   rival targets and builds each presentation track.

The live sync loop (OCR read -> match -> plate) was measured as a candidate
third flow and is not a bottleneck after OCR: see `live.json`.

## Scripts

| Script | Measures |
| --- | --- |
| `fixtures.py` | Deterministic synthetic episodes: seeded word/character lists, no real dialogue. |
| `bench_prepare.py` | Real `GuiController.prepare_session` with downloads served from disk, engine reported ready, 3 rivals. Median of 7, plus the longest event-loop stall (5 ms heartbeat). |
| `bench_live.py` | `CandidateSession.match` per read and renderer ticks on a simulated clock, 10 simulated minutes, 15% of reads matching the file. |
| `bench_startup.py` | Real `meocosub2.cli serve` + headless Chromium: backend ready, palette in DOM, FCP, web fonts loaded; cold and second navigation; cached warm only with live CDN; font CDN `live`, `slow` (+1.5 s), `blocked`, `hang`. Median of 7 (2 for `hang`). |
| `bench_shell_boot.py` | Replays the shell's `wait_for_backend` loop against a real backend for a given poll interval. |
| `bench_overlap.py` | Full-track sign over sparse dialogue; validates answers and records construction time, source hash and environment. |
| `bench_import_ab.py` | Interleaved backend import time between two worktrees. |
| `run.sh <label>` | Runs prepare, live and startup benchmarks into `results/<label>/`. |

## Conditions

Linux cloud container, 4 vCPU Xeon 2.1 GHz, Python 3.11.15, Chromium 141
headless (`results/*/env.json`). Absolute numbers differ from a Windows
desktop with WebView2; compare labels with each other. `bench_startup.py`
needs the container proxy's CA in Chromium's NSS store, or "live" font
requests fail TLS instead of loading; `*-untrusted-ca.json` in `baseline/`
are the runs where that happened and are not used for comparison.

OCR, WebView2 painting and the Tauri shell itself cannot run here.

## Results

`baseline/` is 024e8b3. `opt1-presentation/`, `opt2-fonts/` and
`opt3-shell-poll/` are the incremental measurements; `final/` measures
`b2789ac`, before the review fixes. These historical files are retained unchanged.

| Flow | Case | Baseline | Final |
| --- | --- | ---: | ---: |
| Prepare | 800 cues, bilingual source | 352 ms | 95 ms |
| Prepare | 1600 cues, bilingual source | 1260 ms | 228 ms |
| Prepare | 3000 cues, bilingual source | 4134 ms | 380 ms |
| Prepare | longest event-loop stall, 1600 bilingual | 465 ms | 93 ms |
| Studio | palette ready, cold, font CDN live | 199 ms | 71 ms |
| Studio | palette ready, cold, font CDN +1.5 s | 1718 ms | 71 ms |
| Studio | palette ready, font CDN never answers | > 20 s | 78 ms |
| Shell | wait added after backend ready (replay) | 316 ms | 24 ms |

Prepare outputs (answered cue count, rival ranking, unpaired cues and
milliseconds) are identical between baseline and final for every case.

## Interpretation and review corrections

`palette_ready_ms` marks the search input entering the DOM after navigation.
It does not measure first paint, input handling, or complete desktop startup.
For example, the historical final live-CDN run reports 71 ms to DOM insertion,
132 ms to first contentful paint, and 610 ms from backend spawn to DOM insertion.
The shell's 316 -> 24 ms result is a Linux HTTP polling replay, not a measured
Windows shell improvement. Native Tauri/WebView2 startup remains unverified.

Playwright routing disables HTTP caching. In the historical slow, blocked and
hang files, `warm` therefore means a second navigation with the same backend and
browser context, not a cached warm start. The live mode does use HTTP caching.
The corrected harness uses `repeat_navigation` for routed modes and records
`http_cache_enabled`; do not combine those visits with cached warm results.

The original prefix-maximum overlap query can still scan quadratically when a
long cue outlives many short cues. The reviewed implementation sweeps source and
target boundaries and visits each actual overlap once. For N total cues and K
overlapping pairs, discovery costs O(N log N + K); preserving target order adds
sum(k_i log k_i) for each source's k_i matches. Dense overlaps can inherently
produce quadratic output, so total construction is not unconditionally O(N log N).
The regression suite counts comparisons on a long-cue fixture rather than using
a machine-dependent timing threshold.

The shell replay now has a total startup deadline, detects premature backend
exit, and stops its owned backend and probe on failure. Each HTTP request has a
2-second timeout; deadline handling can exceed the deadline by that in-flight
request, followed by bounded cleanup. Run it only with port 8765 available.

The review fixture on Windows ARM64 / Python 3.14.2 took median 2.3, 4.9, 9.3,
and 20.7 ms for 1,000, 2,000, 4,000 and 8,000 source cues (three runs each).
`results/review-windows/overlap.json` records samples and the source hash; its
HEAD field is the parent commit because the measured fix was not yet committed.
Reproduce with `python docs/audit-20260926/perf/bench_overlap.py --repeat 3`.
These numbers cover presentation construction, not complete session preparation.
