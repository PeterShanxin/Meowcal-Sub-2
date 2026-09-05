# CLAUDE.md

This repository's working contract lives in
[`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md).

Before making changes:

1. read [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md), including the anti-slop
   quality bar it sets for every artifact produced here;
2. read [`docs/CODING_STANDARDS.md`](docs/CODING_STANDARDS.md), which is
   normative for what the code has to look like, and
   [`docs/MAINTAINABILITY_BASELINE.md`](docs/MAINTAINABILITY_BASELINE.md), which
   owns the measured limits enforced by `scripts/verify.ps1`.

Two rules this repository learned the hard way, stated in full in the coding
standards, and worth knowing before you run anything:

- **Never leave a translation engine running.** The app spawns
  `llama-server.exe` holding a multi-gigabyte model resident. After stopping the
  app, and before starting it again, confirm nothing survived — a restart loop
  that skipped this once exhausted a machine's memory and forced a hard reboot.
- **No private subtitle or OCR text in logs, issues, or screenshots.** The debug
  log records whatever the user is watching.

Keep this file a Claude entrypoint. Shared repository rules belong in the guide.
