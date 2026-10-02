# Authored playing-confidence calibration

On 2026-10-02, an unlocked Windows ARM64 desktop supplied 288 physical samples
at approximately 400 ms intervals, serialized to avoid concurrent players:

| Fixture | Samples | Scope |
| --- | ---: | --- |
| FFplay | 154 | Silent movement, movement with audio, native pause/resume, static sound/silence/zero stream, unrelated background sound |
| FFplay changing dialogue | 44 | Static picture with changing English captions, with and without audio |
| Edge HTML video | 68 | Actual browser motion, pause/resume, static sound/silence and unrelated sound |
| Edge paused overlay | 22 | Paused static video with changing authored text above it; a negative for treating text changes as image motion |

Core OCR read the actual subtitle crop; WASAPI supplied levels without recording
audio. Native FFplay pause used guarded input to the owned window. Browser DOM
time/paused values were test oracles only. Production receives no such values.
Physical capture checked the owned root window. An earlier locked-desktop run,
an unavailable-Core OCR run and wrongly scaled browser crops were excluded.

Only Boolean features and counts enter the committed ledger at
`tests/fixtures/playing-confidence-calibration.json`. Its source hashes identify
the local authored measurements without exposing desktop images or text. Paired
opposite labels balance indistinguishable static observations; this explicitly
prevents sample class proportions from pretending to resolve pause ambiguity.

Reproduce the fit without devices, network or dependencies:

```powershell
python scripts/fit_playing_confidence.py
```

The fit uses 2,500 gradient steps, learning rate 0.2 and ridge 0.005. Progression
weights are constrained nonnegative; silence/repetition/stillness weights are
nonpositive. These are semantic constraints, not manually assigned weights.
The measured motion window remains one second; OCR change requires two reads.
Native positive peak levels crossed 0.001; silent/zero streams stayed below it.

| Term | Fitted weight |
| --- | ---: |
| Intercept | 0.311437 |
| Distributed motion | 1.422677 |
| Confirmed OCR change | 0.029923 |
| Audible energy | 2.251407 |
| Silence | -0.356064 |
| Stable OCR | 0.000000 |
| Sustained stillness | -0.103645 |

Repeated OCR added no independent predictive value after other features in
these fixtures. Its change pulse decays; it cannot subtract media time. The
small text-change weight reflects the real paused-overlay negative, not a
claim that repeated text means a repeated image.

Reference scores were 0.551762 ambiguous static, 0.559150 text-only, 0.849938
motion-only and 0.921232 attributable audio. Entry 0.704544 is the midpoint
between the higher ambiguous/text-only score and the lower strong-channel
score. Exit 0.628153 lies halfway between ambiguity and entry. Unknown sound
without image motion is capped below entry, including when text changes.
Explicit ambiguity guards withhold timing rather than infer stopped duration.

This authored calibration is reproducible evidence for an initial index, not
population calibration, player support certification, elapsed-time recovery,
or an exact-head packaged-overlay acceptance result. New representative media
may justify recalibration; hardware and long-running release gates remain.
