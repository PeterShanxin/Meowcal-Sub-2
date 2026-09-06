"""The maintainability ratchets, proved able to fail.

A gate nobody has watched reject something is not a gate. Every rule here is fed
a baseline it should refuse, and the repository's real baseline is checked too,
so a rule cannot be satisfied by being broken.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_maintainability import (
    DEFAULT_BASELINE,
    REPO_ROOT,
    check_frontend_coverage,
    check_lint_budgets,
    check_python_coverage,
    frontend_coverage,
    run,
)

BASELINE = {
    "newFileMaxLines": 400,
    "legacyFileCeilings": {},
    "lintBudgets": {"ruff": 0, "biome": 26},
    "coverage": {
        "python": {"floorPercent": 80},
        "frontend": {
            "scope": ["src/state/mappers.ts"],
            "floors": {"statements": 88, "branches": 74, "functions": 66, "lines": 88},
        },
    },
}


def make_source(root: Path, relative: str, lines: int) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1\n" * lines, encoding="utf-8")


def rules(failures) -> set[str]:
    return {failure.rule for failure in failures}


def with_baseline(**overrides) -> dict:
    return {**BASELINE, **overrides}


def test_the_repositorys_own_baseline_holds() -> None:
    baseline = json.loads(DEFAULT_BASELINE.read_text(encoding="utf-8"))
    assert run(REPO_ROOT, baseline, {}) == []


def test_a_new_file_over_the_limit_is_refused(tmp_path: Path) -> None:
    make_source(tmp_path, "src/meocosub2/sprawl.py", 401)
    assert "new-file-too-long" in rules(run(tmp_path, BASELINE, {}))


def test_a_new_file_inside_the_limit_is_accepted(tmp_path: Path) -> None:
    make_source(tmp_path, "src/meocosub2/tidy.py", 400)
    assert run(tmp_path, BASELINE, {}) == []


def test_a_legacy_file_that_grew_is_refused(tmp_path: Path) -> None:
    make_source(tmp_path, "src/meocosub2/legacy.py", 900)
    baseline = with_baseline(legacyFileCeilings={"src/meocosub2/legacy.py": 899})
    assert "legacy-file-grew" in rules(run(tmp_path, baseline, {}))


def test_a_legacy_file_that_shrank_must_lower_its_ceiling(tmp_path: Path) -> None:
    """The rule that makes this a ratchet rather than a ceiling nobody lowers."""
    make_source(tmp_path, "src/meocosub2/legacy.py", 700)
    baseline = with_baseline(legacyFileCeilings={"src/meocosub2/legacy.py": 899})
    assert "stale-ceiling" in rules(run(tmp_path, baseline, {}))


def test_a_ceiling_for_a_deleted_file_is_refused(tmp_path: Path) -> None:
    baseline = with_baseline(legacyFileCeilings={"src/meocosub2/gone.py": 500})
    assert "ceiling-without-a-file" in rules(run(tmp_path, baseline, {}))


def test_build_output_is_not_held_to_the_limit(tmp_path: Path) -> None:
    make_source(tmp_path, "src/meocosub2/overlay/static/assets/index-abc.js", 9000)
    assert run(tmp_path, BASELINE, {}) == []


def test_a_lint_budget_may_not_be_exceeded() -> None:
    assert "lint-budget-exceeded" in rules(check_lint_budgets({"biome": 27}, BASELINE))


def test_a_lint_budget_that_is_beaten_must_be_lowered() -> None:
    assert "stale-lint-budget" in rules(check_lint_budgets({"biome": 25}, BASELINE))


def test_coverage_under_the_floor_is_refused() -> None:
    assert "coverage-below-floor" in rules(check_python_coverage(79.99, BASELINE))
    assert check_python_coverage(80.0, BASELINE) == []


def test_a_frontend_floor_that_is_missed_is_refused() -> None:
    report = {
        "scope": ["src/state/mappers.ts"],
        "statements": 87,
        "branches": 74,
        "functions": 66,
        "lines": 88,
    }
    assert "coverage-below-floor" in rules(check_frontend_coverage(report, BASELINE))


def test_dropping_a_module_from_the_scope_is_refused() -> None:
    """Otherwise a floor is met by measuring less, which costs nothing to do."""
    report = {"scope": [], "statements": 100, "branches": 100, "functions": 100, "lines": 100}
    assert "coverage-scope-shrank" in rules(check_frontend_coverage(report, BASELINE))


def a_vitest_summary() -> dict:
    """What vitest writes: every file it can see, plus a project-wide total."""

    def entry(covered: int, total: int) -> dict:
        return {
            metric: {"covered": covered, "total": total, "pct": covered / total * 100}
            for metric in ("statements", "branches", "functions", "lines")
        }

    return {
        "total": entry(30, 1000),
        "C:/repo/src/state/mappers.ts": entry(88, 100),
        "C:/repo/src/components/palette.tsx": entry(0, 900),
    }


def test_the_scope_decides_the_denominator_not_the_whole_project() -> None:
    """The project-wide figure here is 3%, which would say nothing about anything."""
    measured = frontend_coverage(a_vitest_summary(), ["src/state/mappers.ts"])

    assert measured["scope"] == ["src/state/mappers.ts"]
    assert measured["statements"] == 88.0
    assert check_frontend_coverage(measured, BASELINE) == []


def test_a_module_the_baseline_names_but_the_run_never_measured_is_reported() -> None:
    """A module dropped from the run, rather than from the baseline, still counts."""
    baseline = with_baseline(
        coverage={
            "python": BASELINE["coverage"]["python"],
            "frontend": {
                "scope": ["src/state/mappers.ts", "src/lib/gone.ts"],
                "floors": BASELINE["coverage"]["frontend"]["floors"],
            },
        }
    )
    measured = frontend_coverage(a_vitest_summary(), baseline["coverage"]["frontend"]["scope"])
    assert "coverage-scope-shrank" in rules(check_frontend_coverage(measured, baseline))
