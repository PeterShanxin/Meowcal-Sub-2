# OCR deadline performance — 2026-09-11

Async OCR reuses the event-loop request deadline instead of creating a second
timer thread for each recognition pass. Both saturation and 250 ms cadence
comparisons pass the existing latency budgets and preserve recognized text in
all five synthetic fixtures. These results do not establish native playback UX.

## Cause and boundary

The preceding saturation run failed colored-text P95: 39.4043 ms against a
38.1824 ms limit. Profiling 500 complete OCR calls found thread-start stalls:
one 66.23 ms frame spent 45.51 ms in `Timer.start`, while its pipe exchange took
14.43 ms. Another 56.50 ms frame spent 36.89 ms starting its timer. This is
measured client overhead, not an estimate of pipe-copy cost.

The existing async deadline now aborts the owned OCR process and drains its
worker. Real-pipe tests cover blocked body writes and blocked response reads,
assert process exit, and successfully start a replacement. Synchronous requests
and translations retain independent timers, including cancelled translations
whose responses are still draining. Async OCR abort requires a responsive event
loop; Core also enforces its native OCR deadline.

## Paired results

Windows ARM64, Snapdragon X Elite, Python 3.14.2, Windows build 26200. Each case
uses ABBA order, five warmups per block and 200 measured calls per variant.
The benchmark invokes the complete product OCR policy, including preprocessing
and pass selection. No compiler or other task test ran during either benchmark.
Slow samples are retained. Baseline load varied between runs, so absolute times
from separate runs do not isolate the effect of this change.

Milliseconds below are baseline → candidate. All rows pass text parity and the
unchanged budgets: P50 +max(10 ms, 15%), P95 +max(15 ms, 20%), and at most one
percentage point increase in calls exceeding 250 ms.

| Case | Saturation P50 | Saturation P95 | 250 ms cadence P50 | 250 ms cadence P95 |
| --- | ---: | ---: | ---: | ---: |
| English | 22.446 → 22.981 | 44.456 → 28.892 | 62.689 → 45.369 | 91.688 → 83.576 |
| Large region | 108.811 → 112.979 | 203.224 → 186.541 | 163.108 → 135.632 | 214.396 → 196.000 |
| Color | 23.806 → 19.826 | 48.325 → 25.704 | 52.967 → 50.044 | 97.648 → 84.352 |
| Chinese | 130.563 → 26.212 | 225.011 → 47.112 | 158.426 → 47.356 | 252.615 → 85.658 |
| Blank | 12.353 → 11.719 | 18.329 → 18.146 | 29.868 → 24.944 | 65.302 → 61.414 |

No candidate saturation call exceeded 250 ms. In the paced run, one Chinese
candidate call took 802.608 ms; the rate over 250 ms was 0.5%, versus baseline
6.5%. All other candidate cases had zero calls over 250 ms. Passing P95 and
rate budgets does not eliminate isolated stalls on this shared host.

## Reproduction and source identity

Run `scripts/benchmark_core_ocr.py` with the original checkout as `--baseline`,
the release Core executable as `--core`, `--runs 100 --warmup 5`, and either
`--interval-ms 0` or `--interval-ms 250`. Reports, raw block samples, cold starts
and fixture hashes are retained under `output/ocr-async-deadline/` and
`output/ocr-async-deadline-paced/`; instrumentation is under
`output/core/profile-ocr-boundary.json`.

- Baseline Sub2: `a2d13f97254f7489c214154d96d18472affd798a`.
- Candidate: the deadline change accompanying this report, based on
  `2c6e9f2b13379eb720845cb8f671d0a05aef5d51`. The report's recorded HEAD predates
  the uncommitted change; it alone does not identify the measured source.
- Measured `core_client.py` SHA256 (working-tree bytes):
  `2b63ac62c8f2bb9f1acc355e2d45eecb5049cd0875302974da03c269eb6403b8`.
- Measured `core_process.py` SHA256 (working-tree bytes):
  `43bde31d3ccb3ee1c7c6be0585b2463c609fed5c4489af918323e63d414d255e`.
- Canonical Core source: `52a3916504f1d35dc6bb31894409d4cc6d08f7ae`.
- Core executable SHA256:
  `3b3245e4e8105212766ba3e2ecf8fb0bfa05c094daf9b9daeac77370e1c227e9`.

The earlier failed measurement remains in the canonical repository's
`docs/plans/2026-09-11-core-ocr-performance.md`. Core and Sub1 are unchanged by
this deadline adjustment. Physical x64 performance, native capture/overlay and
the required playback and packaged migration gates remain outstanding.
