# OCR measurements

Measured on Windows ARM64 (12 logical CPUs), released Core 0.2.2, two PP-OCRv6
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
| Chinese / Windows | 60.9% | 671/675 | 0 | 16.4 / 23.1 | 13.2 |
| Chinese / PP + line heights | 100% | 675/675 | 0 | 67.9 / 97.4 | 122.0 |
| English / Windows | 47.6% | 457/458 | 0 | 16.7 / 20.1 | 13.4 |
| English / PP + line heights | 99.1% | 458/458 | 0 | 138.7 / 181.2 | 237.5 |

No recognition failures or frames above 250 ms occurred in these full runs.
Timing includes preprocessing, transport and OCR, excluding PNG loading and
screen capture. CPU is process CPU time, not whole-machine utilization. Tests
ran sequentially without translation inference; timings vary with system load.

On every fifth frame of three harder Chinese sets, Windows matched 67, 72 and
50 of 75 stable frames. PP with line heights matched 75, 75 and 69. Neither
policy produced a wrong text match. PP retained unrelated scene text on some
subtitle-free frames: 28.6–71.4% in these small negative sets and 66.7% of the
42 English blank frames, versus 0% for Windows on that English set. The matcher
rejected those reads, but OCR-only translation has no source track to reject them.

## Default policy

Automatic mode uses PP-OCRv6 with source files and prefers an installed Windows
OCR language for OCR-only sessions. Korean always uses Windows. Missing Windows
packs can use PP for supported languages; missing PP capability or initialization
failure falls back explicitly to Windows. A missing Windows language stops start
with an actionable error.

PP reads the original image once and retains lines at least 60% as tall as the
tallest line, preserving comparable speaker rows while excluding small scene
labels. On the same 180-frame Chinese sample, copying Windows' three-pass policy
gave 93.3% exact recognition and 269.7/690.3 ms median/P95. One raw PP pass gave
95.6% and 66.6/88.0 ms; adding line filtering gave 100% and 79.6/116.7 ms. Windows
retains its existing three passes. One-thread PP was slower; four threads used
more CPU than two without improving recognition. Two is the measured compromise.

## Reproduction

Run `scripts/benchmark_ocr_policies.py --help` with a verified Core package and a
local corpus containing sorted `frames/*.png` plus ordered `truth.csv`, or
`cues.csv` and `labels.csv`. Outputs include private OCR text; do not publish
them as CI artifacts. Native capture, the selector, playback timing and the plate
require separate real App acceptance.
