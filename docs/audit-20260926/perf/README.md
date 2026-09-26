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
| `bench_startup.py` | Real `meocosub2.cli serve` + headless Chromium: backend ready, palette in DOM, FCP, web fonts loaded; cold and warm; font CDN `live`, `slow` (+1.5 s), `blocked`, `hang`. Median of 7 (2 for `hang`). |
| `bench_shell_boot.py` | Replays the shell's `wait_for_backend` loop against a real backend for a given poll interval. |
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
`opt3-shell-poll/` are each change on its own; `final/` is the branch head.

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
