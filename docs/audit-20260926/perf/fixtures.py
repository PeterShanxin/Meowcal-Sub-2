"""Deterministic synthetic subtitle episodes for the performance benchmark.

No real dialogue: text is drawn from fixed word and character lists with a
seeded RNG, so every run and every machine sees byte-identical inputs.
"""

from __future__ import annotations

import random
from pathlib import Path

WORDS = (
    "the a we you they it is was not never always here there now then why how what "
    "going coming leave stay tonight tomorrow yesterday house door car road river "
    "listen look wait stop run tell know think want need find keep lose remember "
    "friend brother sister father mother captain doctor king queen soldier stranger"
).split()
# A different translation of the same scene shares few words with the file.
OTHER_WORDS = (
    "perhaps certainly quickly slowly across beyond beneath garden window morning evening "
    "promise secret journey answer question reason moment silence letter money trouble "
    "believe forgive follow carry return arrive decide finish begin happen matter"
).split()
HANZI = "我你他她们的是不在有这那了一个人上下来去说要会能好对没就也都还和到看想知道时候现在今天明天"


def _stamp(ms: int) -> str:
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _english(rng: random.Random) -> str:
    return " ".join(rng.choice(WORDS) for _ in range(rng.randint(3, 11))).capitalize() + "."


def _chinese(rng: random.Random) -> str:
    return "".join(rng.choice(HANZI) for _ in range(rng.randint(4, 16)))


def episode(
    cues: int, seed: int = 7, variant: int = 0
) -> tuple[list[tuple[int, int, str, str]], list[tuple[int, int, str]]]:
    """Source cues (start, end, english, chinese) and a differently cut target track.

    `variant` re-cuts the target from the same source, as a rival release would.
    """
    rng = random.Random(seed)
    source: list[tuple[int, int, str, str]] = []
    t = 2_000
    for _ in range(cues):
        t += rng.randint(300, 2_500)
        duration = rng.randint(900, 4_000)
        source.append((t, t + duration, _english(rng), _chinese(rng)))
        t += duration
    # Target: 900 ms later clock, a few cues merged and a few missing, so the
    # track has genuine gaps for the presentation owner to account for.
    rng = random.Random(seed * 1000 + variant)
    target: list[tuple[int, int, str]] = []
    i = 0
    while i < len(source):
        start, end, _, zh = source[i]
        roll = rng.random()
        if roll < 0.06:
            i += 1
            continue
        if roll < 0.14 and i + 1 < len(source):
            end = source[i + 1][1]
            zh = zh + "，" + source[i + 1][3]
            i += 1
        target.append((start + 900, end + 900, zh))
        i += 1
    return source, target


def write_srt(path: Path, rows: list[tuple[int, int, str]]) -> Path:
    body = "\n".join(
        f"{n}\n{_stamp(start)} --> {_stamp(end)}\n{text}\n"
        for n, (start, end, text) in enumerate(rows, 1)
    )
    path.write_text(body, encoding="utf-8")
    return path


def write_episode(directory: Path, cues: int, seed: int = 7, rivals: int = 0) -> dict[str, Path]:
    """Source (English), bilingual source (Chinese over English), target (Chinese)
    and `rivals` alternative target cuts."""
    directory.mkdir(parents=True, exist_ok=True)
    source, target = episode(cues, seed)
    rival_paths = {
        f"rival{n}": write_srt(directory / f"rival{n}-{cues}.srt", episode(cues, seed, n)[1])
        for n in range(1, rivals + 1)
    }
    return rival_paths | {
        "source": write_srt(
            directory / f"source-{cues}.srt", [(s, e, en) for s, e, en, _ in source]
        ),
        "bilingual": write_srt(
            directory / f"bilingual-{cues}.srt", [(s, e, f"{zh}\n{en}") for s, e, en, zh in source]
        ),
        "target": write_srt(directory / f"target-{cues}.srt", target),
    }
