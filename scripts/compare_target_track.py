"""Replay recorded matching results through the subtitle clock without model downloads."""

import json
from pathlib import Path
from unittest.mock import patch

from meocosub2.config import AppConfig
from meocosub2.models import SubtitleLine
from meocosub2.target_follower import TargetTrackFollower
from meocosub2.timeline import PlaybackState

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/target-track-replay.json"


def measure(method, data):
    """Sample the real target clock and the rendered target intervals at 10 ms."""
    lines = [SubtitleLine(i, row[0], row[1], row[3]) for i, row in enumerate(data["cues"])]
    follower = TargetTrackFollower(lines, AppConfig(), lambda: 0)
    events = {}
    for read in data["reads"]:
        onset, expected, text, translation, translation_ms, index, score, margin, embedding_ms = (
            read
        )
        events[onset] = ("read", onset)
        elapsed = translation_ms if method == "translated" else embedding_ms
        # Model results enter the renderer at the first sample after completion.
        delivered = max(onset + 10, (onset + elapsed + 9) // 10 * 10)
        events[delivered] = ("answer", read)
    scenes = data["scenes"]
    locks, following, wrong = [], [], 0
    last_accepted = None
    scene = -1
    first_correct = False
    next_change = None
    target_at_change = ""
    old_clock_ms = 0
    for wall_ms in range(0, data["end_ms"] + 1, 10):
        now = wall_ms / 1000
        if scene + 1 < len(scenes) and wall_ms == scenes[scene + 1][0]:
            scene += 1
            first_correct = False
            next_change = None
            locks.append(None)
            following.append(None)
        start, media = scenes[scene]
        actual = media + wall_ms - start
        with patch("meocosub2.timeline.monotonic", return_value=now):
            follower.timeline.observe_playback(PlaybackState.ADVANCING, now)
            event = events.get(wall_ms)
            if event and event[0] == "read":
                follower.new_cue(now)
            elif event:
                onset, expected, _, translation, _, index, score, margin, _ = event[1]
                if method == "translated":
                    follower.answer(translation, onset / 1000, current=True)
                elif score >= 0.66 and margin >= 0.10:
                    # Only uniquely ranked semantic hits can serve as evidence.
                    follower.timeline.accepts(
                        lines[index].start_ms, index, 100, seen_at=onset / 1000
                    )
            position = follower.position_ms(0)
            anchor = follower.timeline.anchor_ms
            if anchor != last_accepted and position is not None and abs(position - actual) > 100:
                wrong += 1
            last_accepted = anchor
            if position is None:
                continue
            if abs(position - actual) > 100:
                old_clock_ms += 10
                continue
            if not first_correct:
                first_correct = True
                locks[scene] = wall_ms - start
                # First target start strictly after lock. Compare the actual
                # resolved strip against the wording at the labeled boundary.
                next_change = next(
                    (line.start_ms for line in lines if line.start_ms > actual), None
                )
                if next_change is not None:
                    target_at_change = follower.track.resolve_at(next_change).text
            if (
                next_change is not None
                and follower.track.resolve_at(position).text == target_at_change
            ):
                following[scene] = actual - next_change
                next_change = None
    return {
        "lock_ms": locks,
        "next_cue_error_ms": following,
        "wrong_locks": wrong,
        "old_scene_clock_ms": old_clock_ms,
    }


if __name__ == "__main__":
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for method in ["translated", "multilingual"]:
        print(method, measure(method, fixture))
