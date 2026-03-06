# Meowcal-Sub-2

`meowcal-sub-2` is a Python CLI that searches OpenSubtitles, downloads and caches subtitle files, batch-translates them with Foundry Local when needed, and syncs translated overlay text against on-screen subtitles using OCR plus fuzzy matching.

User guide:

- [`docs/user-guide.md`](docs/user-guide.md)

## Requirements

- Python 3.11+
- Windows for OCR support via `winocr`
- An OpenSubtitles API key
- Optional: a Foundry Local OpenAI-compatible endpoint for subtitle translation

## Install

```bash
pip install -e ".[dev]"
```

## Config

Default config path:

- Windows: `%APPDATA%/meowcal-sub-2/config.toml`

See [`config.example.toml`](config.example.toml) for the full schema.

Sections:

- `[opensubtitles]`: `api_key`, `username`, `password`, `enable_org_fallback`
- `[languages]`: `source`, `target`
- `[capture]`: `region`, `interval_ms`, `ocr_language`
- `[matching]`: `fuzzy_threshold`, `window_size`
- `[translation]`: `endpoint`, `model`, `timeout_s`, `batch_size`
- `[overlay]`: `port`, `font_size`, `font_family`, `text_color`, `bg_color`, `position`

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

Examples:

```bash
meowcal-sub-2 search "Inception" --source en --target zht
meowcal-sub-2 download 123456
meowcal-sub-2 translate .\movie.en.srt
meowcal-sub-2 start .\movie.en.srt --target-file .\movie.zht.srt
meowcal-sub-2 run "Inception" --source en --target zht
meowcal-sub-2 gui
```

Optional legacy-title fallback:

- Set `opensubtitles.enable_org_fallback = true` in the config file to let the app scrape `.org` search result titles as extra aliases when the official `.com` API misses a title.
- The fallback only contributes title hints. Search, download, and session prep still use the official `.com` API.

## Tests

```bash
pytest -v --tb=short
```
