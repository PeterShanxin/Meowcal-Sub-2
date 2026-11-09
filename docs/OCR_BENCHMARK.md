# OCR measurements

Measured on Windows ARM64 (Snapdragon X Elite X1E80100, 12 logical CPUs), released
Core 0.2.2, two PP-OCRv6
threads. These are ordered subtitle images from local video, not generated text.
Private captions and images are not redistributed. The benchmark records Core,
source, label and frame hashes alongside its results.

## Recognition and matching

The Chinese set contains 900 frames at 10 fps, 40 manually labelled cues and 675
stable subtitle frames. The English set contains 591 frames, 20 cues and 458
stable frames. Exact recognition ignores punctuation, spacing and Chinese script
differences. Text matching uses Sub 2's normal threshold of 65, with duplicate
suppression cleared for each frame. It measures whether a read can match the
correct cue, not playback-clock recovery or semantic matching.

| Set / policy | Stable exact | Correct text matches | Wrong matches | Median / P95 ms | Core CPU ms/frame |
| --- | ---: | ---: | ---: | ---: | ---: |
| Chinese / Windows | 60.9% | 671/675 | 0 | 18.0 / 24.6 | 15.4 |
| Chinese / PP + line heights | 100% | 675/675 | 0 | 64.4 / 97.0 | 115.2 |
| English / Windows | 47.6% | 457/458 | 0 | 19.9 / 23.4 | 16.0 |
| English / PP + line heights | 99.1% | 458/458 | 0 | 134.4 / 178.7 | 232.6 |

No recognition failures or frames above 250 ms occurred in these full runs.
Timing includes preprocessing, transport and OCR, excluding PNG loading and
screen capture. CPU is process CPU time, not whole-machine utilization. Tests
ran sequentially without translation inference; timings vary with system load.
Failure counts include any failed pass and PP initialization fallback, even when
another Windows pass still returns usable text. Successful blank reads are separate.

A separate 180-frame PP run with concurrent real GPU HY-MT inference completed
15 translations. It retained 135/135 correct stable text matches, no wrong matches
and no frames over 250 ms, with 68.2/102.9 ms median/P95. OCR and translation use
independent Core processes; this sample does not bound every GPU or CPU workload.

On every fifth frame of three harder Chinese sets, Windows matched 67, 72 and
50 of 75 stable frames. PP with line heights matched 75, 75 and 69. Neither
policy produced a wrong text match. PP retained unrelated scene text on some
subtitle-free frames: 28.6–71.4% in these small negative sets and 66.7% of the
42 English blank frames, versus 0% for Windows on that English set. The matcher
rejected those reads, but OCR-only translation has no source track to reject them.

## Default policy

Automatic mode keeps an exact installed Windows OCR language. The native replay
below did not show greater cue coverage from PP, despite its higher exact OCR
accuracy. PP supplies supported languages whose requested Windows pack is missing
and remains an explicit setting. OCR-only sessions also accept a compatible
Chinese Windows pack to reduce scene-text reads. Korean always uses Windows.
Missing PP capability or initialization failure falls back explicitly to Windows.
If neither engine can supply the language, start stops with an actionable error.

PP reads the original image once and retains lines at least 60% as tall as the
tallest line, preserving comparable speaker rows while excluding small scene
labels. On the same 180-frame Chinese sample, copying Windows' three-pass policy
gave 93.3% exact recognition and 196.2/252.2 ms median/P95. One raw PP pass gave
95.6% and 64.2/89.8 ms; adding line filtering gave 100% and 74.7/115.4 ms. Windows
retains its existing three passes. One-thread PP was slower; four threads used
more CPU than two without improving recognition. Two is the measured compromise.

## Native capture and presentation

On 2026-11-09, the installed ARM64 backend, studio bundle and Core ran through
the native Tauri selector and subtitle plate. The same 900 original Chinese
frames played at 10 fps in a window, with the 40 labelled source cues and authored
target markers. This measures capture, matching, playback timing and presentation;
it does not measure translation quality. The test checked the unlocked console
on each observation and the frame's pixels and visibility every two seconds.
Both runs reached all 900 frames; all 44 pixel checks in each run matched exactly.

| Policy | Cues displayed correctly | Distant wrong-cue observations | Observed cue onset median / P95 ms | Iteration median / P95 ms | Backend CPU, % of host |
| --- | ---: | ---: | ---: | ---: | ---: |
| Windows | 35/40 | 0 | 200 / 300 | 30 / 50 | 4.83 |
| PP + line heights | 35/40 | 0 | 200 / 400 | 89.5 / 172 | 6.07 |

Onset timings include only the 35 observed cues. There were 18 adjacent wrong-cue
observations for Windows and 31 for PP; none was more than one second outside
the displayed cue's interval. The observation counts differ because each run
samples its own display updates. Backend CPU includes its owned OCR, translation
and embedding processes, divided by the host's 12 logical CPUs. The frame player
is excluded. The host continued normal desktop workloads during sequential runs.

The installed app also selected, downloaded and displayed the expected human
translation for four ASSRT members of *八仙！* (2026): Simplified and Traditional
source tracks paired with English, and both bilingual members. Each source had
2,852 cues. These checks rendered text from each selected file; they establish
the selection/download/display path, not complete movie playback.

An installed-payload rollback to Core 0.1.4 and restoration to 0.2.2 verified all
14 changed files. Both installed versions returned the same Windows OCR results
for nine real frames. The original user configuration was unchanged; the new OCR
preference survived in the test profile. Version-specific production storage
remained separate. x64 also passed released-Core checks under ARM64 emulation and
the x64 CI gate; this laptop is not a native x64 device.

## Reproduction

Run `scripts/benchmark_ocr_policies.py --help` with a verified Core package and a
local corpus containing sorted `frames/*.png` plus ordered `truth.csv`, or
`cues.csv` and `labels.csv`. Outputs include private OCR text; do not publish
them as CI artifacts. Native capture, the selector, playback timing and the plate
require separate real App acceptance.
