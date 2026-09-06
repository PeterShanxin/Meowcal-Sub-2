# Coding Standards

Normative for this repository. Where this document and a tool disagree, the tool
is authoritative for formatting and the document is authoritative for design.
`docs/AGENT_GUIDE.md` covers how to work here; this covers what the code has to
look like when you are done.

Formatting is not a matter of opinion here: Ruff formats Python, Biome formats
TypeScript and CSS, `cargo fmt` formats Rust, and `scripts/verify.ps1` fails if
any of them disagrees with the tree.

## General

- **Make the smallest change that satisfies the contract you agreed.** Not the
  most complete-looking one. A diff that touches a file for no reason is a
  reviewer's problem.
- **One owner per state machine or lifecycle.** Two places that both decide when
  a session starts will eventually disagree, and the bug will be intermittent.
- **Keep data typed and stable across the backend, the studio, and the shell.**
  These three processes only agree by contract; an untyped dict crossing that
  boundary is a runtime error waiting for a user to find.
- **Adapters stay thin; the logic they wrap stays testable without them.** The
  reason `orphans()` is a pure function over a list is that deciding which
  process to kill is the part that has to be right, and it should be provable
  without a process table.
- **Comments explain a reason, an invariant, or a trade-off.** Never the syntax.
  If the code needs a comment to say what it does, rename something instead.
- **Documentation states current behaviour.** History belongs in issues, commit
  messages and this repository's dated notes — not in a comment explaining what
  the code used to do.

## Two rules this repository learned the hard way

### Child-process ownership must be explicit

The app spawns a Python backend, which spawns `llama-server.exe` holding a
multi-gigabyte model resident. Windows does not tie a child's lifetime to its
parent's. An engine that outlives the app is a **defect**, not an inconvenience:
they accumulate one per crash until the machine runs out of memory, which has
already happened here once and cost a hard reboot.

Any change that spawns a process must say, in the code, what ends it on every
path — including the paths where our own cleanup code does not run. See
`src-tauri/src/process_lifetime.rs` and `src/meocosub2/engine/orphans.py`.

### No private subtitle or OCR text in logs by default

The log runs at DEBUG and currently records recognised dialogue, which is
whatever the user happens to be watching. Truncate it, and never copy it into an
issue, a PR, a screenshot or a CI artifact.

## Python

- Type the public surface of a module. Internal helpers can be obvious instead.
- **Every network, subprocess and async wait is bounded.** An unbounded await in
  the capture loop stalls the overlay with no way for the user to tell why.
- Handle errors where you can say what they mean. A `try` that spans thirty
  lines cannot.
- **Do not hide a global lifecycle.** Module-level process registries exist here
  (`engine/runtime.py`), and they are explicit, locked, and have one owner.
- Keep provider adapters (`subtitle_sources/*`) free of provider-neutral
  orchestration, and the aggregator free of provider specifics.
- `zip()` over sequences whose lengths are guaranteed equal says `strict=True`.
  If they are not guaranteed equal, say why in a comment or use `pairwise`.

## TypeScript and React

- `strict` stays on, with the unused-locals and fallthrough checks it has now.
- State ownership is explicit. A component that starts holding session state has
  become a state machine and needs an owner named.
- Backend contracts go through the typed API wrappers, not through inline
  `fetch` with an `any`.
- Do not restate a backend rule in a UI string or a UI branch. It will drift.
- New interaction surfaces are keyboard reachable and focus visible. The
  existing gaps are recorded in `MAINTAINABILITY_BASELINE.md` as a budget that
  may only shrink; do not add to it.
- Every `<button>` carries an explicit `type`.

## Rust and Tauri

- `cargo fmt --check` and `cargo clippy -- -D warnings` both pass. There is no
  warning budget, because there are no warnings.
- No `unwrap` or `expect` on I/O, runtime, or network paths. A panic in the
  shell takes the WebView with it.
- Tauri commands are boundary adapters: parse, delegate, return. Logic lives in
  a module that can be unit tested without Tauri.
- Win32 lifecycle invariants are commented with the failure they prevent, not
  the call they make.

## Tests

- A bug fix comes with a test that fails without it. If that is impractical, say
  so in the commit message rather than skipping it silently.
- Test behaviour, not implementation. A test that asserts a private attribute is
  a test that will fail on a refactor that changed nothing.
- **A new threshold or gate needs a negative proof** — a test that feeds it a
  violating input and asserts it fails. See `tests/test_maintainability.py`.
- Distinguish the evidence: `pytest` and `vitest` prove logic, the Playwright
  smoke proves the served page, and only a real Windows run proves OCR, WebView2
  rendering, the selector, and the overlay plate.
- Tests must not start engines, download artifacts, or reach the network. Where
  a session needs one, it takes a factory it can be handed a stub for.
