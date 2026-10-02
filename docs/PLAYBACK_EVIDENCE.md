# Playback timing evidence

The subtitle timeline owns timing. Image motion and audio activity establish
playback activity, not subtitle identity. They cannot create an anchor or revive
one that expired, was contradicted, or belongs to a previous capture source.

The capture adapter recognizes one visible desktop player client containing the
selected OCR rectangle. For other windows, including browsers, it obtains only
a geometrical image band above the selected rectangle. Both bands must belong
to the same unobscured root; desktop and lock backgrounds are rejected. The OCR
rectangle stays unchanged. Browser audio remains explicitly unattributed. No
player transport API, browser media state, SMTC or UIA enters production.

Motion uses at most eight 96×48 grayscale thumbnails (36 KiB of pixel storage)
covering a one-second window plus the preceding sample when capture scheduling
slips. Comparisons with retained samples avoid aliasing periodic motion. Changes
must exceed six grayscale levels in three content patches spanning both rows and
three columns, on consecutive samples. Controls,
subtitle rows and cursor-sized changes do not establish motion. The one-second
comparison captures slower distributed motion than adjacent-frame differences.
The thresholds were checked against the authored FFplay reproduction and the
negative cursor/control/letterbox/cut/black-frame cases.

WASAPI reads session PID, stream state and peak levels, twice per second with a
250 ms caller deadline. Enumeration is bounded, COM references are worker-local
and released, and a timed-out reader cannot accumulate further workers. No
microphone, loopback recording, ASR, or retained audio buffer is used. Another
process's sound never establishes native-player attribution. Browser ambient
levels can only add bounded support to visible progression. No audio is recorded.

Actual selected-player audio energy above 0.001 supports playback even over a
static shot. Silence, mute, missing meters, device loss, or a stream simply
remaining active do not establish either progression or pause. FFplay, for
example, can keep rendering zeros through its audio stream while paused. A
stream becoming stopped is also ambiguous. It never supplies a video pause
duration. Video motion can continue over silence or an inactive stream.

Independent motion and confirmed OCR changes join sound/silence and repeated
text/stillness in a temporal playing-confidence index. A first confirmed cue is
not a text-change event. Strong evidence decays over one second, with separate
entry/exit thresholds. Still, unchanged text without attributable sound
withdraws projection; changing overlays plus unrelated sound cannot certify
browser progression. See [the measured calibration](PLAYING_CONFIDENCE_CALIBRATION.md).

Activity renews the existing clock's 90-second freshness lease, but does not
corroborate its subtitle-file identity. After five minutes of projected playback
without a fresh accepted subtitle match, the clock must reacquire from two strong
progressing cues. Confirmed stopped time does not spend this playback budget.
Conflicting matches still invalidate the clock through the existing miss/seek
rules. Capture failure, region changes and recognized-player changes invalidate
projection immediately. A late activity sample cannot resurrect an old anchor.

Uncertain observations receive a three-second transition grace period. Sustained
uncertainty invalidates projection instead of calling a static shot a pause or
charging an unobserved gap to playback. The plate then uses live OCR/fallback
until progressing subtitle evidence reacquires timing. On clock loss, the stale
file plate and cue-deduplication cache are cleared, allowing the same visible OCR
to receive live translation while timing remains unanchored. This is conservative:
silent static content, video with no audio stream, unsupported player windows and
ambiguous browser attribution can interrupt the scheduled target track. Identical
silent static-playing and paused frames cannot reveal elapsed media time.
Target-only cues with no observable source cannot be timed exactly through such
intervals. Observable-text fallback must not be reported as seamless target
timing or fully accepted #70 behavior.

Native validation still needs pause/resume, long dialogue-free playback, muted
moving video, static content with audio, other-app sound, source changes and
capture loss. Unit/replay evidence does not replace those runs. Do not close #70
or #42 from the state-machine tests alone.
