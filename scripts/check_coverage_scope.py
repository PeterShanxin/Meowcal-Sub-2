"""Check that a PR keeps measuring live studio modules covered by its base."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.ci_scope import git

BASELINE = "config/maintainability-baseline.json"
STUDIO = "src/meocosub2/overlay/ui/"


def scope_at(repo: Path, ref: str) -> set[str]:
    baseline = json.loads(git(repo, "show", f"{ref}:{BASELINE}"))
    return set(baseline["coverage"]["frontend"]["scope"])


def compare_scope(repo: Path, base: str) -> list[str]:
    before, after = scope_at(repo, base), scope_at(repo, "HEAD")
    removed = before - after
    if not removed:
        return []

    names = git(repo, "ls-tree", "-r", "-z", "--name-only", "HEAD", "--", STUDIO)
    live = set(names.decode().split("\0"))
    changes = git(repo, "diff", "--name-status", "-z", "--find-renames", base, "HEAD")
    fields = iter(changes.decode().rstrip("\0").split("\0"))
    renames = {}
    for status in fields:
        path = next(fields)
        if status.startswith("R"):
            renames[path] = next(fields)
    problems = []
    for module in sorted(removed):
        path = STUDIO + module
        if path in live:
            problems.append(f"Restore live module {module} to the frontend coverage scope.")
        elif path in renames and renames[path].startswith(STUDIO):
            new = renames[path].removeprefix(STUDIO)
            if new not in after:
                problems.append(f"Keep renamed module {module} in scope as {new}.")
        else:
            print(f"Retired from studio coverage: {module}")
    return problems


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", help="Base commit of the pull request")
    args = parser.parse_args()
    errors = compare_scope(Path(__file__).resolve().parents[1], args.base)
    for message in errors:
        print(message)
    raise SystemExit(bool(errors))
