# Contributing

Meowcal Sub 2 is licensed under **AGPL-3.0-only**. Contributions are governed
by the [Contributor License Agreement](CLA.md).

By intentionally submitting code, documentation, a patch, or other material
for inclusion after receiving notice of these terms, you accept the CLA for
that contribution. You keep your copyright and grant the maintainer the rights
described there, including relicensing. Viewing, starring, forking, opening an
issue, or joining a discussion does not by itself accept the CLA. No separate
signature or per-PR acceptance checkbox is required.

## Before changing code

Read [the agent guide](docs/AGENT_GUIDE.md),
[coding standards](docs/CODING_STANDARDS.md), and
[maintainability baseline](docs/MAINTAINABILITY_BASELINE.md). The
[developer guide](docs/developer-guide.md) covers setup and the runtime map.

Keep changes focused. Describe the user-visible problem and how the change
addresses it. Add a regression test for a bug where practical, and identify
any manual Windows checks that remain.

Run the repository's review gate from PowerShell:

```powershell
.\scripts\verify.ps1
```

Python and browser checks cannot prove native OCR, WebView2 rendering, capture
selection, or subtitle placement. Changes to those paths also need a real
Windows run.

## Issues and pull requests

Include reproduction steps, the app version, Windows version and architecture,
and the checks you ran. Use a small synthetic subtitle or image when a sample
is needed. Do not attach private subtitle dialogue, viewing screenshots,
credentials, access tokens, or unredacted logs.

Report vulnerabilities through [the security policy](SECURITY.md).
