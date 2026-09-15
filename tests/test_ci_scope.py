from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.ci_scope import is_prose, prose_base

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ci_scope.py"


class ProsePathsTests(unittest.TestCase):
    def test_only_known_markdown_locations_are_prose(self) -> None:
        for path in (
            "README.md",
            "CLA.md",
            "docs/developer-guide.md",
            "docs/notes/new topic.md",
        ):
            with self.subTest(path=path):
                self.assertTrue(is_prose(path))
        for path in (
            "LICENSE",
            "unknown.md",
            "docs/assets/banner.svg",
            "docs/assets/banner.png",
            "scripts/update_branding.py",
            "tests/test_branding.py",
            "pyproject.toml",
            "src-tauri/tauri.conf.json",
            ".github/workflows/windows-ci.yml",
            "src/meocosub2/overlay/static/selector.js",
            "src/readme.md",
            "docs/../scripts/example.md",
            "/docs/example.md",
            "docs//example.md",
            "docs\\example.md",
            "docs/./example.md",
            "docs/example.MD",
        ):
            with self.subTest(path=path):
                self.assertFalse(is_prose(path))


class ProseMergeTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = Path(directory.name)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "CI scope test")
        self.git("config", "user.email", "ci-scope@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "core.filemode", "false")
        self.git("config", "core.symlinks", "false")
        self.write("README.md", "Initial documentation.\n")
        self.write("src/app.py", "print('example')\n")
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-b", "topic")

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout

    def write(self, path: str, content: str) -> None:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        # Match the repository's LF policy independently of the host newline default.
        target.write_text(content, encoding="utf-8", newline="\n")

    def commit(self, *, stage: bool = True) -> None:
        if stage:
            self.git("add", "--all")
        self.git("commit", "--allow-empty", "-m", "Test change")

    def merge(self) -> dict:
        self.head = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "main")
        self.git("merge", "--no-ff", "topic", "-m", "Synthetic PR merge")
        return {"pull_request": {"base": {"sha": self.base}, "head": {"sha": self.head}}}

    def run_scope(self, event: dict | str, event_name: str = "pull_request") -> tuple[int, str]:
        event_file = self.repo / "event.json"
        output_file = self.repo / "output.txt"
        event_file.write_text(
            event if isinstance(event, str) else json.dumps(event), encoding="utf-8"
        )
        output_file.write_text("", encoding="utf-8")
        env = os.environ | {
            "GITHUB_EVENT_NAME": event_name,
            "GITHUB_EVENT_PATH": str(event_file),
            "GITHUB_OUTPUT": str(output_file),
        }
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=self.repo,
            env=env,
            capture_output=True,
            timeout=30,
        )
        if result.returncode:
            print((result.stdout + result.stderr).decode("utf-8", errors="replace"))
        return result.returncode, output_file.read_text(encoding="utf-8")

    def test_prose_only_merge_and_cli(self) -> None:
        self.write("README.md", "Updated documentation.\n")
        self.write("docs/新文档 with spaces.md", "New documentation.\n")
        self.commit()
        event = self.merge()
        self.assertEqual((self.repo / "README.md").read_bytes(), b"Updated documentation.\n")
        self.assertEqual(prose_base("pull_request", event, self.repo), self.base)
        self.assertEqual(self.run_scope(event), (0, "scope=docs\n"))

    def test_earlier_code_commit_is_not_hidden_by_last_readme_commit(self) -> None:
        self.write("src/app.py", "print('changed')\n")
        self.commit()
        self.write("README.md", "Updated documentation.\n")
        self.commit()
        event = self.merge()
        self.assertIsNone(prose_base("pull_request", event, self.repo))
        self.assertEqual(self.run_scope(event), (0, "scope=full\n"))

    def test_code_renamed_into_docs_requires_full_verification(self) -> None:
        (self.repo / "docs").mkdir()
        self.git("mv", "src/app.py", "docs/example.md")
        self.commit()
        self.assertIsNone(prose_base("pull_request", self.merge(), self.repo))

    def test_readme_deletion_requires_full_verification(self) -> None:
        self.git("rm", "README.md")
        self.commit()
        self.assertIsNone(prose_base("pull_request", self.merge(), self.repo))

    def test_empty_diff_requires_full_verification(self) -> None:
        self.commit()
        self.assertIsNone(prose_base("pull_request", self.merge(), self.repo))

    def test_push_or_untrusted_event_never_takes_the_shortcut(self) -> None:
        self.write("README.md", "Updated documentation.\n")
        self.commit()
        event = self.merge()
        for name in ("push", "workflow_dispatch", "pull_request_target", ""):
            with self.subTest(name=name):
                self.assertIsNone(prose_base(name, event, self.repo))
        for invalid in ({}, {"pull_request": None}, [], None):
            with self.subTest(event=invalid):
                self.assertIsNone(prose_base("pull_request", invalid, self.repo))
        event["pull_request"]["head"]["sha"] = self.base
        self.assertIsNone(prose_base("pull_request", event, self.repo))
        event["pull_request"]["head"]["sha"] = "--help"
        self.assertIsNone(prose_base("pull_request", event, self.repo))
        self.assertEqual(self.run_scope("malformed json"), (0, "scope=full\n"))

    def test_head_checkout_is_not_mistaken_for_tested_merge(self) -> None:
        self.write("README.md", "Updated documentation.\n")
        self.commit()
        event = self.merge()
        self.git("checkout", self.head)
        self.assertIsNone(prose_base("pull_request", event, self.repo))

    def test_shallow_checkout_contains_both_required_parents(self) -> None:
        self.write("README.md", "Updated documentation.\n")
        self.commit()
        event = self.merge()
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "clone"
            self.git("clone", "--depth=2", self.repo.as_uri(), str(clone))
            self.assertEqual(prose_base("pull_request", event, clone), self.base)
        with tempfile.TemporaryDirectory() as directory:
            clone = Path(directory) / "clone"
            self.git("clone", "--depth=1", self.repo.as_uri(), str(clone))
            self.assertIsNone(prose_base("pull_request", event, clone))

    def test_git_failure_requires_full_verification(self) -> None:
        event = {"pull_request": {"base": {"sha": self.base}, "head": {"sha": self.base}}}
        with patch("scripts.ci_scope.git", side_effect=subprocess.TimeoutExpired("git", 30)):
            self.assertIsNone(prose_base("pull_request", event, self.repo))

    def test_mode_only_markdown_change_requires_full_verification(self) -> None:
        self.git("update-index", "--chmod=+x", "README.md")
        self.commit(stage=False)
        self.assertIsNone(prose_base("pull_request", self.merge(), self.repo))

    def test_executable_markdown_addition_requires_full_verification(self) -> None:
        blob = self.git("hash-object", "-w", "README.md").strip()
        self.git("update-index", "--add", "--cacheinfo", "100755", blob, "docs/tool.md")
        self.commit(stage=False)
        self.assertIsNone(prose_base("pull_request", self.merge(), self.repo))

    def test_markdown_symlink_requires_full_verification(self) -> None:
        blob = self.git("hash-object", "-w", "README.md").strip()
        self.git("update-index", "--add", "--cacheinfo", "120000", blob, "docs/link.md")
        self.commit(stage=False)
        self.assertIsNone(prose_base("pull_request", self.merge(), self.repo))

    def test_markdown_gitlink_requires_full_verification(self) -> None:
        self.git("update-index", "--add", "--cacheinfo", "160000", self.base, "docs/module.md")
        self.commit(stage=False)
        self.assertIsNone(prose_base("pull_request", self.merge(), self.repo))

    def test_binary_markdown_requires_full_verification(self) -> None:
        self.write("docs/binary.md", "Not text.\0\n")
        self.commit()
        self.assertIsNone(prose_base("pull_request", self.merge(), self.repo))

    def test_non_utf8_markdown_requires_full_verification(self) -> None:
        (self.repo / "README.md").write_bytes(b"\xff\n")
        self.commit()
        self.assertIsNone(prose_base("pull_request", self.merge(), self.repo))

    def test_markdown_hard_line_break_is_valid(self) -> None:
        self.write("README.md", "First line.  \nSecond line.\n")
        self.commit()
        self.assertEqual(self.run_scope(self.merge()), (0, "scope=docs\n"))

    def test_prose_whitespace_failure_does_not_emit_green_scope(self) -> None:
        self.write("README.md", " \tIncorrect indentation.\n")
        self.commit()
        code, output = self.run_scope(self.merge())
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "")


if __name__ == "__main__":
    unittest.main()
