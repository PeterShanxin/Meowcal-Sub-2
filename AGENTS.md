# AGENTS.md

This repository's working contract lives in
[`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md).

Before making changes:

1. read [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md), including the anti-slop
   quality bar it sets for every artifact produced here;
2. read [`docs/CODING_STANDARDS.md`](docs/CODING_STANDARDS.md), which is
   normative for what the code has to look like, and
   [`docs/MAINTAINABILITY_BASELINE.md`](docs/MAINTAINABILITY_BASELINE.md), which
   owns the measured limits enforced by `scripts/verify.ps1`.

One command answers whether a checkout is ready for review:

```powershell
.\scripts\verify.ps1
```

Keep this file a short entrypoint. Shared repository rules belong in the guide.
