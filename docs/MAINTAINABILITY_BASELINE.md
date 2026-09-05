# Maintainability Baseline

This document owns what the numbers in `config/maintainability-baseline.json`
mean. The machine-readable file is what `scripts/check_maintainability.py`
enforces; this is why each value is what it is.

Everything here was measured on the repository as it stood on **2026-09-06**,
before any threshold was chosen. Nothing below is aspirational.

Line counts are measured **after** the formatters were adopted, because that is
now how the repository writes a line. Adopting `cargo fmt` grew `main.rs` from
998 lines to 1,033 and `overlay_window.rs` from 465 to 467 without adding a
thing — counting from before would have spent the ratchet's whole budget on the
formatter.

## What was measured

| Area | Files | Lines |
| --- | ---: | ---: |
| Python (`src/meocosub2`, excluding the studio UI) | 47 | 12,090 |
| TypeScript and CSS (`overlay/ui/src`) | 20 | 7,232 |
| Hand-maintained browser sources (`overlay/static`) | 4 | 502 |
| Rust (`src-tauri/src`) | 3 | 1,620 |
| Scripts | 2 | 189 |

Tests are not counted or capped. A long test file is usually a thorough one, and
a limit on them rewards thin tests.

## File size ratchet

**400 lines** for a new production file. Fifteen existing files are above it and
carry their own measured ceiling instead. The ceiling for each is exactly its
line count on the measurement date, and the checker enforces the ratchet in both
directions:

- a file that grows past its ceiling fails;
- a file that falls **below** its ceiling also fails, naming the new number to
  record.

The second rule is what makes this a ratchet rather than a ceiling nobody ever
lowers. Ground gained has to be written down in the same change, or it is given
straight back.

The four largest are the ones worth naming, because they are where the work is:

| File | Lines | What it holds |
| --- | ---: | --- |
| `overlay/controller.py` | 1,664 | session lifecycle, search orchestration, config, engine startup |
| `overlay/ui/src/app.tsx` | 1,494 | the studio's whole screen state |
| `overlay/ui/src/components/palette.tsx` | 1,478 | the search palette |
| `subtitle_sources/aggregator.py` | 1,445 | provider-neutral search aggregation |

No module is to be split to satisfy a number. A cohesive exception is better
than fake decomposition; these are recorded because they are real, not because
they are scheduled.

## Lint budgets

| Tool | Budget | State |
| --- | ---: | --- |
| Ruff | 0 | clean |
| Clippy (`-D warnings`) | 0 | clean |
| Biome | 26 | debt, described below |

Ruff and Clippy are at zero and enforced at zero, so neither needs a budget so
much as a floor under it. Budgets ratchet the same way ceilings do: beating one
means lowering it in the same change.

Biome's 26 are pre-existing findings in the studio UI, deliberately not fixed
inside a formatting change:

| Rule | Count | Why it is held rather than fixed |
| --- | ---: | --- |
| `a11y/noStaticElementInteractions` | 7 | the palette's rows and cards take clicks as plain elements |
| `a11y/useKeyWithClickEvents` | 6 | the same surfaces need keyboard handling designed, not appended |
| `correctness/useExhaustiveDependencies` | 4 | React hook dependency arrays; changing one blind risks a render loop |
| `suspicious/useIterableCallbackReturn` | 3 | `forEach` callbacks returning values |
| `complexity/noImportantStyles` | 3 | deliberate CSS overrides |
| `suspicious/noArrayIndexKey` | 1 | needs a stable identity to key on |
| `a11y/noSvgWithoutTitle` | 1 | a decorative icon |
| `a11y/noAutofocus` | 1 | the palette focusing its own search field is the intent |

Sixteen findings of `a11y/useButtonType` were fixed rather than budgeted: the
studio has no forms today, so nothing submits by accident yet, but the HTML
default is `submit`, and the first form wrapped around any of those buttons
would turn it into one.

## Coverage

### Python — 79.87%, floored at 79%

5,843 statements, 1,176 uncovered, over `src/meocosub2`. The floor is the
measured figure rounded **down**, which matters: taking `pytest-cov`'s rounded
display of "80%" as the floor set it above the real number and failed the gate
on the first run. It is also honest about where the figure comes from — the
modules that drag it down are the ones that cannot be unit tested without a
machine.

| Module | Covered | Why |
| --- | ---: | --- |
| `engine/runtime.py` | 34% | spawns llama-server processes |
| `engine/install.py` | 34% | downloads and verifies gigabytes |
| `engine/orphans.py` | 40% | walks the real process table and terminates processes |
| `devtools/window_capture.py` | 31% | a developer tool that drives Win32 windows |

Their decision logic is covered where it was separable — `orphans()` is a pure
function over a process table for exactly this reason — and the rest is covered
by the manual Windows gate.

### Frontend — a named scope, not a percentage of everything

`src/state/mappers.ts` is the only studio module under test today, at 88.23%
statements, 74.46% branches, 66.66% functions, 88.23% lines. The floors are
those figures rounded down.

The scope is named in the baseline file rather than left implicit, because a
coverage percentage is meaningless without saying what it is a percentage *of*.
The checker enforces that the scope may **grow but never shrink**: dropping a
module raises the percentage without a line of new test code, which is the
cheapest way there is to make a coverage claim mean less than it says.

A repository-wide frontend floor would be about 3% and would say nothing. Every
module that gains tests joins the scope.

## Proving the gates can fail

`tests/test_maintainability.py` feeds each rule a baseline it must refuse — a
new file over the limit, a legacy file that grew, a legacy file that shrank, a
ceiling for a deleted file, a budget exceeded, a budget beaten, coverage under a
floor, and a scope with a module dropped from it. It also asserts that the
repository's real baseline passes, so no rule can be satisfied by being broken.
