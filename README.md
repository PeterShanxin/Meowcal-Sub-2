# Meowcal-Sub-2

`meowcal-sub-2` is a Windows-first subtitle studio with a Python backend, a local web dashboard, and a Tauri desktop shell. It searches multiple subtitle sources, prepares subtitle-pair or OCR-fallback sessions, translates through Foundry Local when needed, and syncs overlay text to live playback with OCR plus fuzzy matching.

Docs:

- [docs/PRD.md](docs/PRD.md) — product goals and success criteria
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — current-state architecture
- [docs/user-guide.md](docs/user-guide.md)
- [docs/developer-guide.md](docs/developer-guide.md)
- [docs/gap-analysis-2026-07-07.md](docs/gap-analysis-2026-07-07.md) — distance from goal state, prioritized

## Requirements

- Python 3.11+
- Windows for OCR support via `winocr`
- Optional desktop shell: WebView2/Tauri runtime on Windows
- Optional subtitle sources:
  - OpenSubtitles API key
  - ASSRT token
- Optional translation backend:
  - Foundry Local OpenAI-compatible endpoint

## Install

```bash
pip install -e ".[dev]"
python -m playwright install chromium
```

The `dev` extra installs the Playwright Python package. Run `python -m playwright install chromium` once on each machine before using the served-dashboard smoke script.

## Runtime Modes

- Desktop launch: `run_app.vbs`
- Local dashboard server: `python -m meocosub2.cli serve`
- Browser dashboard URL: `http://127.0.0.1:8765/`
- Browser overlay URL: `http://127.0.0.1:8765/overlay`

`run_app.vbs` is the supported Windows launcher. It opens the built Tauri shell when present and falls back to the Python GUI path through `pythonw.exe`.

## Config

Default config path on Windows:

- `%APPDATA%/meowcal-sub-2/config.toml`

Use [config.example.toml](config.example.toml) as the source of truth for the current schema.

Main sections:

- `[subtitle_sources.opensubtitles]`: enable/credentials/legacy alias fallback
- `[subtitle_sources.subdl]`: enable flag
- `[subtitle_sources.assrt]`: enable flag and token
- `[languages]`: source and target language codes
- `[capture]`: region, interval, OCR language
- `[matching]`: fuzzy threshold and search window
- `[translation]`: Foundry Local endpoint/model/batch settings
- `[overlay]`: style and layout settings for the subtitle overlay
- `[debug]`: dashboard debug panel toggle

Legacy `[opensubtitles]` config still loads for backward compatibility, but new edits should use `subtitle_sources.opensubtitles`.

## Commands

```bash
meowcal-sub-2 --help
```

Available commands:

- `search TITLE`
- `download FILE_ID`
- `translate PATH_TO_SRT`
- `start SOURCE_SUBTITLE [--target-file TARGET_SUBTITLE]`
- `run TITLE`
- `gui`
- `serve`

Examples:

```bash
meowcal-sub-2 gui
meowcal-sub-2 serve
meowcal-sub-2 search "Inception" --source en --target zht
meowcal-sub-2 translate .\movie.en.srt
```

## Verification

```bash
pytest -q
Get-ChildItem src\meocosub2\overlay\static\app*.js | ForEach-Object { node --check $_.FullName }
cargo check --manifest-path src-tauri\Cargo.toml
python scripts\run_dashboard_smoke.py
```

Before the smoke check, install the browser once with `python -m playwright install chromium`.

The Playwright smoke script validates the served dashboard path only. It also refuses to reuse an already-running dashboard by default, so you do not accidentally smoke-test stale code. It does not prove native WebView2 rendering correctness inside the Tauri shell.
