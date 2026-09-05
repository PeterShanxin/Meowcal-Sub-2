# AGENTS.md

This repository's working contract lives in
[`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md).

Read it before making changes, then read
[`docs/CODING_STANDARDS.md`](docs/CODING_STANDARDS.md), which is normative for
what the code has to look like, and
[`docs/MAINTAINABILITY_BASELINE.md`](docs/MAINTAINABILITY_BASELINE.md), which
owns the measured limits `scripts/verify.ps1` enforces.

One command answers whether a checkout is ready for review:

```powershell
.\scripts\verify.ps1
```

## Anti-slop quality bar

Treat every artifact as maintainer-owned, not as a trace of an AI session. This
applies to code, comments, documentation, PR and issue text, UI copy,
architecture, configuration, and handoff notes.

- Do not narrate the prompt, agent, implementation journey, discarded
  approaches, or direction changes unless future maintainers need that
  rationale.
- Do not add boilerplate prose, obvious comments, duplicate summaries or rules,
  ceremonial files or checklists, or placeholder documentation merely to make a
  change look complete.
- Do not introduce wrappers, abstractions, fallbacks, compatibility paths,
  feature flags, or configuration "just in case". Each extra mechanism must
  satisfy a current requirement or documented risk.
- Prefer direct code and concise human-quality prose. Comments should explain
  non-obvious reasons, invariants, or trade-offs rather than restating the code.
- Current docs, UI copy, PRs, and issues should state current behavior directly.
  Put history in issues, ADRs, changelogs, or dated plans unless it is required
  to apply a live safety, compatibility, or unsupported-behavior boundary.
- Before handoff, inspect the diff specifically for AI slop and remove words,
  files, layers, and indirection that add neither required behavior nor durable
  information.

Keep this file a short entrypoint. Other contract changes belong in the guide.
