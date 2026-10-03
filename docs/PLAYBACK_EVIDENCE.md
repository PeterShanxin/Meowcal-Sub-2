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
remaining active do not establish progression or pause by themselves. FFplay, for
example, can keep rendering zeros through its audio stream while paused. A
stream becoming stopped is also ambiguous. It never supplies a video pause
duration. Video motion can continue over silence or an inactive stream.

Independent motion and confirmed OCR changes join sound/silence and repeated
text/stillness in a temporal playing-confidence index. A first confirmed cue is
not a text-change event. Strong evidence decays over one second, with separate
entry/exit thresholds. Still, unchanged text without attributable sound
withdraws progression evidence; changing overlays plus unrelated sound cannot certify
browser progression. See [the measured calibration](PLAYING_CONFIDENCE_CALIBRATION.md).

Activity renews the existing clock's 90-second freshness lease, but does not
corroborate its subtitle-file identity. After five minutes of projected playback
without a fresh accepted subtitle match, the clock must reacquire from two strong
progressing cues. Confirmed stopped time does not spend this playback budget.
Conflicting matches still invalidate the clock through the existing miss/seek
rules. Capture failure, region changes and recognized-player changes invalidate
projection immediately. A late activity sample cannot resurrect an old anchor.

A separate practical pause policy confirms two seconds of reliable near-frozen
video without distributed motion, confirmed text progression or attributable
audible energy. It holds the existing source clock at the first unchanged sample
after progression stopped; the confirmation interval is not charged to playback.
The target scheduler keeps the cue or blank interval at that position. Naturally
static silent content can trigger the same heuristic. This accepted tradeoff is
not a calibrated pause probability or proof of media transport state.

Two consecutive distributed image changes or attributable audible energy resume
the clock. Image resume credits the first qualifying change rather than the later
confirmation frame, so repeated pauses do not accumulate confirmation latency.
Unrelated sound and OCR changes cannot release a confirmed stop. Existing source
matches still correct a paused seek while keeping its new position frozen; normal
seeks and a constant video/source head offset continue to use existing reanchors.
Target-file scheduling and source/target mapping are unchanged.

Black or unreliable crops cannot establish a pause. Capture/source loss, a black
frame during a confirmed stop or a sampling outage longer than five seconds
invalidates it rather than charging an unobserved gap to paused time. Other
uncertain observations retain their three-second transition grace period before
projection is invalidated. On clock loss, the stale file plate and deduplication
cache are cleared; live OCR/fallback remains available until source evidence
reacquires timing. Target-only cues during unavailable captures cannot be timed
exactly. Do not report fallback as seamless target timing or full #70 acceptance.

Native validation still needs pause/resume, long dialogue-free playback, muted
moving video, static content with audio, other-app sound, source changes and
capture loss. Unit/replay evidence does not replace those runs. Do not close #70
or #42 from the state-machine tests alone.
