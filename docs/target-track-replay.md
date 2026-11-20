# How Path 2 finds the current scene

A match has two jobs. It can supply the words on the strip immediately. To start playing later lines from the file, the app also checks that different screen captions point to the same part of the movie. For example, if the second caption appeared 2.5 seconds after the first one, their places in the file should also be about 2.5 seconds apart.

## English-to-Chinese replay

This locally authored example has 12 timed Chinese captions, 11 English reads, two jumps, an OCR typo, a paraphrase and two occurrences of “Thank you.” Nine reads identify distinct lines. Each method received the same source reads and target text. We recorded the local models' actual results and warm response times on a Windows NUC. The test replays those measurements through the playback clock and target intervals with a simulated advancing player. It samples the strip every 10 ms with the adjustable display delay set to zero. It excludes camera, OCR, model startup and index building. [Fixture](../tests/fixtures/target-track-replay.json) · [Replay script](../scripts/compare_target_track.py).

| Result | Translate, then compare wording (app) | Direct multilingual comparison (experiment) |
| --- | --- | --- |
| Correct candidate on distinct reads | 6/9 at the app's default text threshold | 9/9 ranked first, 8/9 passed the confidence cutoff |
| Correctly located scenes | 1/3 | 3/3 |
| First position from scene start | 3.26 s | 2.51 s |
| Time to recover after forward / backward jump | Neither scene confirmed before the next jump or replay end | 2.51 s / 2.51 s |
| Wrong new locks | 0 | 0 |
| Time still projecting the previous scene after a jump, total | 3.32 s | 0.02 s |
| Start of next target cue after a correct lock | On time at 10 ms sampling resolution, 1/1 | On time at that resolution, 3/3 |

The local HY-MT1.5 (Q4, CPU, four threads, fixed seed 52) produced one translation for each new OCR string using the app's rolling context. Uncached reads took 0.55–1.04 seconds. A misspelled “bridge” became a closed metro station. “No need to hurry” also differed enough from the reference wording to miss. The app could still show available translations during recovery.

The experiment indexed the Chinese file with quantized multilingual MiniLM-L12-v2 (ONNX, CPU), then compared each English read directly with its target sentences using normalized, mean-pooled vectors. Warm query times were 3–4 ms. It accepted a cosine score of at least 0.66 and a margin of at least 0.10 over the runner-up. Accepted semantic hits entered the same clock as strong observations. Both copies of “Thank you” tied and supplied no timing evidence. These numbers describe one small language pair and one cut. The experiment used an extra inference runtime. The app uses its installed translator and text matcher.

A second independently written set used six captions rendered as images, actual Windows OCR, and separate human Chinese wording. The text matcher found 5/6 correct lines and abstained on one. With one new line every six seconds and the measured OCR plus translation delays, the clock first confirmed the third read at 16.992 seconds and made zero wrong locks. The same hardware took 3.7–5.0 seconds per translation in that run under a different load. If captions change every two seconds, the app finishes the current translation, shows that delayed answer while it is still looking for the scene, then translates the newest confirmed caption. Intermediate captions may be skipped. Only an answer to a still-current caption can supply timing evidence. Capture loss or a cleared subtitle region discards unfinished screen evidence. Once the file is following the clock, later model answers cannot overwrite its scheduled lines.

Run the checked-in comparison from a development environment with `python scripts/compare_target_track.py`. The fixture records cue times, source and target text. Each read records its simulated onset, labeled cue index, OCR text, measured translation, translation time in ms, multilingual winner, cosine score, margin and query time in ms. The automated playback tests also send both shipping paths through the same pause, resume, backward seek, blank interval, simultaneous lines and capture-loss events. [Playback tests](../tests/test_target_track_playback.py).

