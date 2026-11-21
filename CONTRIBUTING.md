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
any manual Windows checks that remain. Update the affected documentation in the
same pull request, following the agent guide's
[documentation map](docs/AGENT_GUIDE.md#documentation-maintenance). Name the
documents you updated, or state why the change has no documentation impact.

Run the repository's review gate from PowerShell:

```powershell
.\scripts\verify.ps1
```

Python and browser checks cannot prove native OCR, WebView2 rendering, capture
selection, or subtitle placement. Changes to those paths also need a real
Windows run.

### Interface translations

The interface is in English and Simplified Chinese. Add or change English and
Chinese text in the same change: studio text in
`src/meocosub2/overlay/ui/src/i18n/en-zh.json`, backend and editor messages in
`messages-zh.json` beside it, and the splash, selector and subtitle plate in
`src/meocosub2/overlay/static/i18n.js`. Use the same `{name}` placeholders in
both languages. Write natural Chinese product copy rather than a word-for-word
translation. The [developer guide](docs/developer-guide.md#interface-language)
describes how the language is chosen and applied.

When a user-visible behavior or label changes, update `README.md` and
`README.zh-CN.md`, and `docs/user-guide.md` and `docs/user-guide.zh-CN.md`, in
the same pull request. Developer documents stay in English.

## Issues and pull requests

Include reproduction steps, the app version, Windows version and architecture,
and the checks you ran. Use a small synthetic subtitle or image when a sample
is needed. Do not attach private subtitle dialogue, viewing screenshots,
credentials, access tokens, or unredacted logs.

Report vulnerabilities through [the security policy](SECURITY.md).

## Writing clarity

Human contributors and agents follow the project-wide
[STE-inspired clarity standard](docs/WRITING_GUIDE.md) for new or changed README,
documentation, help, error and UI text, comments, and delivery notes.
