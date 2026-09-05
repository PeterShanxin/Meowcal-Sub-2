"""Enforce the maintainability ratchets in config/maintainability-baseline.json.

Structural debt that already exists is recorded rather than pretended away, but
it may only ever shrink. A file above the ceiling for new files carries its own
measured ceiling; growing past it fails, and shrinking below it also fails, with
the new number to write down. That second rule is what makes it a ratchet rather
than a ceiling nobody ever lowers.

`docs/MAINTAINABILITY_BASELINE.md` owns what the numbers mean.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = REPO_ROOT / "config" / "maintainability-baseline.json"

# Where production code lives. Tests are excluded on purpose: a long test file
# is usually a thorough one, and capping it rewards thin tests.
PRODUCTION_ROOTS = ("src/meocosub2", "src-tauri/src", "scripts")
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".css", ".js", ".rs"}
# Build output and dependencies are nobody's to keep small.
EXCLUDED_PARTS = {"__pycache__", "node_modules", "assets", "target"}


@dataclass
class Failure:
    rule: str
    detail: str


def production_files(root: Path) -> dict[str, int]:
    """Every production source file, by repo-relative path, with its line count."""
    found: dict[str, int] = {}
    for directory in PRODUCTION_ROOTS:
        for path in (root / directory).rglob("*"):
            if path.suffix not in SOURCE_SUFFIXES or EXCLUDED_PARTS & set(path.parts):
                continue
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            found[relative] = len(path.read_text(encoding="utf-8").splitlines())
    return found


def check_file_sizes(sizes: dict[str, int], baseline: dict) -> list[Failure]:
    limit = baseline["newFileMaxLines"]
    ceilings: dict[str, int] = baseline["legacyFileCeilings"]
    failures: list[Failure] = []

    for path, lines in sorted(sizes.items()):
        ceiling = ceilings.get(path)
        if ceiling is None:
            if lines > limit:
                failures.append(
                    Failure(
                        "new-file-too-long",
                        f"{path} is {lines} lines, over the {limit}-line limit for new files. "
                        "Split it by responsibility, or record a measured ceiling for it "
                        "with an architectural reason.",
                    )
                )
            continue
        if lines > ceiling:
            failures.append(
                Failure(
                    "legacy-file-grew",
                    f"{path} grew from {ceiling} to {lines} lines. Legacy ceilings may only fall.",
                )
            )
        elif lines < ceiling:
            failures.append(
                Failure(
                    "stale-ceiling",
                    f"{path} is down to {lines} lines from {ceiling}. Lower its ceiling in "
                    "config/maintainability-baseline.json in this same change, or the "
                    "ground it gained is given straight back.",
                )
            )

    for path in sorted(set(ceilings) - set(sizes)):
        failures.append(
            Failure(
                "ceiling-without-a-file",
                f"{path} has a ceiling but no longer exists. Remove it from the baseline.",
            )
        )
    return failures


def check_lint_budgets(counts: dict[str, int], baseline: dict) -> list[Failure]:
    budgets: dict[str, int] = baseline["lintBudgets"]
    failures: list[Failure] = []
    for tool, found in sorted(counts.items()):
        budget = budgets.get(tool)
        if budget is None:
            continue
        if found > budget:
            failures.append(
                Failure(
                    "lint-budget-exceeded",
                    f"{tool} reports {found} findings against a budget of {budget}.",
                )
            )
        elif found < budget:
            failures.append(
                Failure(
                    "stale-lint-budget",
                    f"{tool} is down to {found} findings from {budget}. Lower the budget in "
                    "this same change.",
                )
            )
    return failures


METRICS = ("statements", "branches", "functions", "lines")


def frontend_coverage(summary: dict, scope: list[str]) -> dict:
    """Aggregate a vitest summary over the named scope, and nothing else.

    The runner reports a percentage of every file it can see, which for this
    repository is about 3% and says nothing. The floors describe a named set of
    modules, so the figure judged against them has to be built from those
    modules alone - otherwise the number and the floor are answering different
    questions.
    """
    counted = {metric: [0, 0] for metric in METRICS}
    found: list[str] = []
    for key, entry in summary.items():
        if key == "total":
            continue
        path = key.replace("\\", "/")
        module = next((wanted for wanted in scope if path.endswith(wanted)), None)
        if module is None:
            continue
        found.append(module)
        for metric in METRICS:
            counted[metric][0] += entry[metric]["covered"]
            counted[metric][1] += entry[metric]["total"]

    report: dict = {"scope": sorted(found)}
    for metric in METRICS:
        covered, total = counted[metric]
        report[metric] = (covered / total * 100) if total else 0.0
    return report


def check_frontend_coverage(report: dict, baseline: dict) -> list[Failure]:
    """Floors over a named scope, because a percentage needs a denominator.

    The scope may grow but never shrink: dropping a module raises the percentage
    without a line of new test code, which is the cheapest way to make a
    coverage claim mean less than it says.
    """
    wanted = baseline["coverage"]["frontend"]
    failures: list[Failure] = []

    covered = set(report.get("scope", []))
    missing = sorted(set(wanted["scope"]) - covered)
    if missing:
        failures.append(
            Failure(
                "coverage-scope-shrank",
                f"these modules left the measured scope: {', '.join(missing)}.",
            )
        )

    for metric, floor in sorted(wanted["floors"].items()):
        found = report.get(metric)
        if found is None:
            failures.append(Failure("coverage-missing", f"the report has no {metric} figure."))
        elif found < floor:
            failures.append(
                Failure(
                    "coverage-below-floor",
                    f"frontend {metric} is {found:.2f}%, under the {floor}% floor.",
                )
            )
    return failures


def check_python_coverage(percent: float, baseline: dict) -> list[Failure]:
    floor = baseline["coverage"]["python"]["floorPercent"]
    if percent < floor:
        return [
            Failure(
                "coverage-below-floor",
                f"Python coverage is {percent:.2f}%, under the {floor}% floor.",
            )
        ]
    return []


def run(root: Path, baseline: dict, extras: dict) -> list[Failure]:
    failures = check_file_sizes(production_files(root), baseline)
    if "lint" in extras:
        failures += check_lint_budgets(extras["lint"], baseline)
    if "pythonCoverage" in extras:
        failures += check_python_coverage(extras["pythonCoverage"], baseline)
    if "frontendCoverageSummary" in extras:
        scope = baseline["coverage"]["frontend"]["scope"]
        measured = frontend_coverage(extras["frontendCoverageSummary"], scope)
        failures += check_frontend_coverage(measured, baseline)
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--report",
        type=Path,
        help="JSON with any of lint, pythonCoverage, frontendCoverage, from verify.ps1",
    )
    args = parser.parse_args(argv)

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    extras = json.loads(args.report.read_text(encoding="utf-8")) if args.report else {}

    failures = run(args.root, baseline, extras)
    for failure in failures:
        print(f"  {failure.rule}: {failure.detail}")
    if failures:
        print(f"\n{len(failures)} maintainability check(s) failed.")
        return 1
    print("Maintainability ratchets hold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
