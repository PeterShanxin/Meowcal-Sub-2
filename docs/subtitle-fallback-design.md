# Subtitle playback paths

The path names below describe what the viewer has when starting. The same
session can switch from a live answer to a timed subtitle without restarting
the video. The studio controls are listed in the [user guide](user-guide.md#choose-by-available-files).

| Path | Files at the start | Available today | Proposed addition |
| --- | --- | --- | --- |
| **Path 1 · Dual-track playback** (双轨跟播) | Source and target | Match screen text to source cues, then show target cues on their own schedule. | This is the reference for timed playback. |
| **Path 2 · Target-track playback** (译文跟播) | Target only | Translate OCR, compare the translation with the file, and use its wording on a hit. | Use a confirmed match to follow the target clock between reads. |
| **Path 3 · Source-track translation** (原文补译) | Source only | On main, watch with live answers while the local engine builds a timed target. The finished target joins Path 1 at the current position. A bilingual source uses its own translations. | Implemented on main. |
| **Path 4 · Live screen translation** (屏幕直译) | Neither | Translate readable on-screen captions as they appear after title selection. | This also supplies text while another path is waiting for a reliable position or translation. |

## Where the paths meet

The diagram shows the intended connections. Dashed arrows mark work still to
implement. The existing clock estimates the player's position, and the existing
target scheduler decides when text appears or clears. Path 2 joins Path 1 as soon as a target cue places the video. Path 3 uses the source clock while translating, then joins Path 1 at the target scheduler once its track is ready. Both components belong to the
[playback loop](../src/meocosub2/sync.py).

```mermaid
flowchart TD
    Dual["Path 1 · Dual-track playback"] --> Src["Locate screen cue in source file"]
    Src --> Clock["Playback clock and pause / seek handling"]
    Target["Path 2 · Target-track playback"] --> OCR["Read screen cue and compare with target"]
    OCR --> Live["Display a live answer"]
    OCR -. "Confirmed target position" .-> Clock
    Source["Path 3 · Source-track translation"] --> Src
    Source --> Now["Translate current dialogue on demand"]
    Now --> Live
    Source -->|"While watching"| Build["Generate a timed target track"]
    Build -->|"Track ready for this session"| Display
    Clock --> Display["Shared target scheduler"]
    Dual --> Display
    Display --> Strip["Subtitle strip"]
    Neither["Path 4 · Live screen translation"] --> Live
    Live --> Strip
```

**Which clock?** With two files, map the source position to the target file
using the calibrated offset, or the unverified zero-offset default. With only a
target file, a reliable hit is already in target time. For a generated track,
copy the source intervals, so source and target time are equal. Applying the
two-file offset twice would move the subtitle away from the matched scene.

## Follow a target file using screen observations

Implementation is tracked in [Target-track playback, #164](https://github.com/PeterShanxin/Meowcal-Sub-2/issues/164).

Today `DirectTranslationSession.translate` returns the matched wording. The
match already contains a cue index and start time. The missing connection is to
retain its identity, the first capture time and the strength of the evidence.
A late model answer must refer to the moment the viewer saw the cue.

Use a short sequence of readings to distinguish two occurrences of “Thank you.”
A paused reread counts as the same cue. Compare translate-then-match, direct
multilingual matching and combinations on the same labeled scenes. Measure wrong
locks, correctly located scenes, time to first lock and time to recover after
a seek. Also measure when the *following* target cue actually appears.

Once the position is reliable, feed target time to the existing
[`PlaybackTimeline`](../src/meocosub2/timeline.py) and use the existing
[`PresentationTrack`](../src/meocosub2/presentation.py) and boundary renderer.
Carry the same motion, pause, seek and capture-loss evidence through that path.
If the clock loses its place, clear the old scheduled line, show live answers
when available and keep looking. A shared playback test should run both file
paths through two overlapping cues, silence, a pause in silence, a backward
seek and recovery. Only the way they establish the position should differ.

## Build a target track while the viewer watches

On main, **Start** works as soon as the capture and translation engine are ready.
If the source clock knows the position, the engine translates the matching file
cue. While the app is looking for the position, it translates the screen text.
An existing bilingual source uses its own translations.

```mermaid
sequenceDiagram
    participant V as Viewer
    participant S as Session
    participant M as Local translator
    participant T as Target scheduler
    V->>S: Start at any point
    par During playback
        S->>M: Current cue needs an answer
        M-->>S: Show live answer
    and In spare capacity
        S->>M: Translate upcoming source cues with context
        M-->>S: Save validated answers with source timings
    end
    S->>T: Complete track ready for this session
    T-->>V: Show the cue at the current position
```

The app shares one local model. Watching gets priority over starting another
background cue. A live request can wait for one translation already in progress.
Skipping to another scene shifts the next background request to that part of
the file. The model sees neighboring source lines alongside their translations
when available. Waiting before pressing **Start** gives it a head start.

Each answer belongs to one source cue. Once all cues have an answer, the app
builds a separate in-memory target with their original start and end times.
Path 1's scheduler reads the completed target on the same clock, preserving a
pause or a moment with no text. The original file stays on disk as supplied.
Stopping keeps completed answers in the prepared session. Editing the file or
preparing another video gives the new session its own track. If the model
declines a line, live viewing continues. The implementation and local timing
measurements are in [PR #182](https://github.com/PeterShanxin/Meowcal-Sub-2/pull/182).
