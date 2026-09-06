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

A ceiling may be raised, but only in the change that needs it and only with the
reason in that change's commit message. The rule exists because the alternative
is worse: a file pinned at its ceiling either blocks a fix or gets split to
satisfy a number, and a module split for arithmetic is harder to maintain than
the long one it replaced. What the ratchet buys is that the raise is visible in
the diff and has to be argued for, not that it can never happen.

Raised so far, all of them by live testing against a real player:

| File | From | To | Why |
| --- | ---: | ---: | --- |
| `matcher.py` | 405 | 492 | drawing the cues that genuinely run at once, and only those |
| `matcher.py` | 492 | 516 | flattening a cue the file wrapped, so a row on the plate means a second voice |
| `sync.py` | 614 | 634 | holding the plate behind the dialogue, and keeping stale answers off it |
| `engine/runtime.py` | 479 | 489 | stopping the engine a new one replaces, instead of dropping its handle |
| `overlay/controller.py` | 1664 | 1684 | opening the translator once however many reads ask at the same moment, and publishing a search catalog with the results it describes |
| `subtitle_sources/aggregator.py` | 1445 | 1446 | one import, for title-group ids that survive a provider answering out of order |
| `subtitle_sources/subdl.py` | 621 | 623 | asking SubDL for a whole season only when the title is a series, so movie lookups come back with subtitles |
| `engine/runtime.py` | 489 | 521 | running one throwaway completion, so the viewer's first subtitle does not pay the model's cold start |
| `overlay/controller.py` | 1684 | 1785 | starting the translation engine while preparing, reading the viewer's timing offset while the session runs, and weighing the target candidates against the source file |
| `config.py` | 502 | 535 | a timing offset the viewer sets, normalised on every way in |
| `sync.py` | 634 | 702 | the viewer's offset at the clock's single entry point, and the task that answers the cues the target file left unpaired |
| `overlay/ui/src/app.tsx` | 1494 | 1511 | handing the dock the offset, and the prep card a way to take a better-aligned target |
| `overlay/controller.py` | 1785 | 1809 | letting a session with a target file prepare when the translation engine is missing, and saying what that costs |
| `matcher.py` | 516 | 533 | keeping the rows of a cue that holds two speakers, which a dash opening every row is the file marking |
| `sync.py` | 702 | 720 | filling only where a target file left gaps, and following the candidate the session locks onto next |
| `overlay/ui/src/app.tsx` | 1511 | 1519 | queueing the timing presses, so two that overlap do not both send the same offset |
| `overlay/controller.py` | 1809 | 1812 | a warning that names the stale line the viewer will see rather than a blank plate |
| `sync.py` | 720 | 737 | remembering which files were filled all the way through, and bounding how long the renderer sleeps past a retime |
| `opensubtitles/client.py` | 877 | 885 | keeping the download allowance the provider reports on every download, instead of discarding it |
| `subtitle_sources/aggregator.py` | 1446 | 1458 | asking a provider what is left of its download allowance |
| `overlay/controller.py` | 1812 | 1840 | keeping back enough of a metered download allowance for the viewer to start a session with |
| `matcher.py` | 533 | 544 | telling the two rows of a Korean bilingual cue apart, which asks about script rather than about spacing |
| `overlay/controller.py` | 1840 | 1910 | reading a chosen source for the translation it carries, and preparing a session from it |
| `overlay/ui/src/app.tsx` | 1519 | 1566 | reading the chosen source at the target step, and holding what it found |
| `overlay/ui/src/components/palette.tsx` | 1478 | 1489 | the target step waiting on that read, and the row it can add |
| `overlay/controller.py` | 1906 | 1947 | reusing the source the target step fetched, and measuring candidates over what the file already answers |
| `overlay/controller.py` | 1947 | 2051 | answering the target file's gaps while the app is idle, before a session starts |
| `sync.py` | 742 | 762 | filling from the cue the video has reached, and wrapping to the ones behind |
| `matcher.py` | 544 | 553 | naming the position the video has reached, which `line_at` leaves blank between cues |
| `overlay/ui/src/app.tsx` | 1580 | 1581 | handing the prep card the count of gaps still to write |
| `overlay/ui/src/app.tsx` | 1566 | 1580 | keeping the target list unreachable by keyboard while that read is in flight |
| `sync.py` | 737 | 742 | judging a session by what has been answered rather than by whether a target file exists |
| `src-tauri/src/overlay_window.rs` | 467 | 469 | a dock wide enough for the timing control |

The four largest are the ones worth naming, because they are where the work is:

| File | Lines | What it holds |
| --- | ---: | --- |
| `overlay/controller.py` | 1,947 | session lifecycle, search orchestration, config, engine startup |
| `overlay/ui/src/app.tsx` | 1,580 | the studio's whole screen state |
| `overlay/ui/src/components/palette.tsx` | 1,489 | the search palette |
| `subtitle_sources/aggregator.py` | 1,458 | provider-neutral search aggregation |

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

`src/state/mappers.ts` is the only studio module under test today, at 89.94%
statements, 78.33% branches, 71.42% functions, 89.94% lines. The floors are
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
