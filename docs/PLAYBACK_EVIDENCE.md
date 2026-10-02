# Playback timing evidence

The subtitle timeline owns timing. Image motion and audio activity establish
playback activity, not subtitle identity. They cannot create an anchor or revive
one that expired, was contradicted, or belongs to a previous capture source.

The capture adapter recognizes one visible desktop player client containing the
selected OCR rectangle. It rejects browsers and multiple same-process player
windows because process audio cannot establish which tab/video is selected.
For recognized players, a single client capture supplies a reduced motion crop
and the original OCR rectangle. Otherwise the existing OCR capture is used.

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
process's sound, expired sessions and multi-process attribution are ignored.

Actual selected-player audio energy above 0.001 supports playback even over a
static shot. Silence, mute, missing meters, device loss, or a stream simply
remaining active do not establish either progression or pause. FFplay, for
example, can keep rendering zeros through its audio stream while paused. A
previously active selected stream becoming stopped, corroborated by at least
half a second of still content, supplies stopped evidence. Video motion overrides
an inactive audio stream, so silent moving video can continue.

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
until progressing subtitle evidence reacquires timing. This is conservative:
silent static content, video with no audio stream, unsupported player windows and
ambiguous browser attribution can interrupt the scheduled target track. Without
reliable player position/pause telemetry these cases cannot guarantee seamless
pause/resume; they must not be advertised as fully accepted #70 behavior.

Native validation still needs pause/resume, long dialogue-free playback, muted
moving video, static content with audio, other-app sound, source changes and
capture loss. Unit/replay evidence does not replace those runs. Do not close #70
or #42 from the state-machine tests alone.
