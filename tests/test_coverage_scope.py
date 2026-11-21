import json
import subprocess

from scripts.check_coverage_scope import BASELINE, STUDIO, compare_scope


def test_scope_is_checked_against_the_base_commit(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    def commit(scope):
        baseline.write_text(json.dumps({"coverage": {"frontend": {"scope": scope}}}))
        git("add", ".")
        git("commit", "-qm", "coverage fixture")
        return git("rev-parse", "HEAD")

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    baseline = tmp_path / BASELINE
    baseline.parent.mkdir(parents=True)
    studio = tmp_path / STUDIO
    studio.mkdir(parents=True)
    for name in ("a", "b", "c"):
        (studio / f"{name}.ts").write_text(f"export const {name} = 1;")
    base = commit(["a.ts", "b.ts", "c.ts"])
    (studio / "a.ts").rename(studio / "renamed.ts")
    (studio / "c.ts").unlink()
    commit([])
    assert compare_scope(tmp_path, base) == [
        "Keep renamed module a.ts in scope as renamed.ts.",
        "Restore live module b.ts to the frontend coverage scope.",
    ]
    (studio / "new.ts").write_text("export const added = 1;")
    commit(["renamed.ts", "b.ts", "new.ts"])
    assert compare_scope(tmp_path, base) == []
