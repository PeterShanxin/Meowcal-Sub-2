"""Keep prose-only PRs off the build path; uncertain comparisons require full CI."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT_PROSE = frozenset(
    {
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CLA.md",
        "AGENTS.md",
        "CLAUDE.md",
    }
)


def is_prose(path: str) -> bool:
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts) or "\\" in path:
        return False
    return path in ROOT_PROSE or (
        parts[0] == "docs" and len(parts) > 1 and PurePosixPath(path).suffix == ".md"
    )


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout


def prose_base(event_name: str, event: dict, repo: Path) -> str | None:
    """Return the verified base parent only when every changed entry is prose."""
    if event_name != "pull_request":
        return None
    try:
        base = event["pull_request"]["base"]["sha"]
        head = event["pull_request"]["head"]["sha"]
        if not all(
            isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (base, head)
        ):
            return None
        parents = git(repo, "rev-list", "--parents", "-n", "1", "HEAD").decode("ascii").split()
        if len(parents) != 3 or parents[1:] != [base, head]:
            return None
        # Disabling rename detection exposes removals, including code moved into docs.
        data = git(
            repo, "diff", "--no-ext-diff", "--no-renames", "--name-status", "-z", base, "HEAD", "--"
        )
        if not data or not data.endswith(b"\0"):
            return None
        fields = data[:-1].decode("utf-8").split("\0")
        if len(fields) % 2:
            return None
        changes = zip(fields[::2], fields[1::2], strict=True)
        if all(status in {"A", "M"} and is_prose(path) for status, path in changes):
            return base
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        return None
    return None


def main() -> int:
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    event = {}
    if event_name == "pull_request":
        try:
            event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        except (KeyError, OSError, ValueError):
            print("Cannot read PR event; requiring full verification.")
    base = prose_base(event_name, event, Path.cwd())
    scope = "docs" if base else "full"
    if base:
        # .editorconfig permits Markdown hard breaks made from trailing spaces.
        check = subprocess.run(
            [
                "git",
                "-c",
                "core.whitespace=-blank-at-eol",
                "diff",
                "--no-ext-diff",
                "--check",
                base,
                "HEAD",
                "--",
            ],
            check=False,
            timeout=30,
        )
        if check.returncode:
            return check.returncode
        print("Prose-only PR: whole-PR whitespace check passed; routing tests follow.")
    else:
        print("Full verification required (non-prose change or unverified PR comparison).")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"scope={scope}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
