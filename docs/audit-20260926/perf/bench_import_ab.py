"""Interleaved A/B of backend import time between two source trees.

Usage: bench_import_ab.py <base-src> <candidate-src>, each the `src` of a
`git worktree` in the same directory: trees on different filesystems import at
different speeds. Alternating the order each round keeps machine drift from
landing on one side.
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys

ROUNDS = 60


def _import_ms(src: str) -> float:
    check = f"import meocosub2, meocosub2.cli; assert meocosub2.__file__.startswith({src!r})"
    result = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", check],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": src},
        check=True,
    )
    return int(result.stderr.strip().splitlines()[-1].split("|")[1]) / 1000


def main() -> None:
    trees = {"base": sys.argv[1], "candidate": sys.argv[2]}
    times: dict[str, list[float]] = {name: [] for name in trees}
    for round_ in range(ROUNDS):
        order = list(trees) if round_ % 2 == 0 else list(reversed(trees))
        for name in order:
            times[name].append(_import_ms(trees[name]))
    print(
        json.dumps(
            {
                name: {"median_ms": round(statistics.median(v), 1), "runs_ms": v}
                for name, v in times.items()
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
