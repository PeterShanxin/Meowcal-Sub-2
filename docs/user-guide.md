# Meowcal-Sub-2 User Guide

## What It Does

`meowcal-sub-2` helps you:

- Search and download subtitles from OpenSubtitles
- Use an existing target-language subtitle when available
- Fall back to local translation through a Foundry Local endpoint when a target subtitle is missing
- Sync translated subtitle text to what is currently visible on screen using OCR and fuzzy matching
- Show the translated text in a browser-based overlay

The main way to use it now is the local web GUI launched with `meowcal-sub-2 gui`.

## Before You Start

Requirements:

- Windows
- Python 3.11+
- An OpenSubtitles API key
- Optional but recommended: a Foundry Local OpenAI-compatible endpoint if you want automatic translation when no target subtitle exists

Default config path on Windows:

- `%APPDATA%/meowcal-sub-2/config.toml`

Use [`config.example.toml`](../config.example.toml) as the starting point.

Minimum config for the GUI flow:

```toml
[opensubtitles]
api_key = "YOUR_API_KEY_HERE"

[languages]
source = "en"
target = "zht"
```

Optional legacy-title fallback:

```toml
[opensubtitles]
enable_org_fallback = true
```

This only scrapes `.org` search result titles as extra aliases when the official `.com` search path misses a title. Downloads still come from the official API.

If you want local translation fallback, also set:

```toml
[translation]
endpoint = "http://127.0.0.1:5273/v1"
model = ""
```

## Install

```bash
pip install -e ".[dev]"
```

## Quick Start With The GUI

1. Start the dashboard:

   ```bash
   meowcal-sub-2 gui
   ```

2. Your browser opens the studio dashboard, usually at:

   - `http://127.0.0.1:8765/`

3. In the top search bar:

   - Enter the movie or episode title
   - Set the source language code
   - Set the target language code
   - Click `Search`

4. In the workflow panel:

   - Choose one source subtitle result
   - Choose one target subtitle result if available
   - Or leave the target side on `Use local translation`

5. Click `Prepare Session`

   This downloads the selected subtitle files and, if needed, translates the source lines through Foundry Local.

6. In the studio panel:

   - Adjust overlay style
   - Set OCR language and capture settings if needed
   - Save config if you changed settings

7. Click `Start Sync`

   This opens the browser overlay at:

   - `http://127.0.0.1:8765/overlay`

8. Start your video. The app captures the configured screen region, OCRs the visible subtitle text, matches it against the prepared source subtitles, and broadcasts the translated line to the overlay.

9. Click `Stop` in the dashboard when you are done.

## Dashboard Layout

### Top Bar

- Title search
- Source and target language codes
- Search trigger

### Workflow Panel

- Search results for source subtitles
- Search results for target subtitles
- Progress state for search, download, translation, and sync
- Prepared-session summary
- Latest subtitle currently sent to the overlay

### Studio Panel

- OpenSubtitles API key input
- Translation endpoint/model fields
- OCR and capture settings
- Overlay style controls
- Inline subtitle preview

## CLI Alternatives

The older CLI flows still work.

Search:

```bash
meowcal-sub-2 search "Inception" --source en --target zht
```

Run the full older flow:

```bash
meowcal-sub-2 run "Inception" --source en --target zht
```

Start the overlay from local subtitle files:

```bash
meowcal-sub-2 start .\movie.en.srt --target-file .\movie.zht.srt
```

## Important Notes

- The overlay is browser-based. It is not a native transparent always-on-top desktop window.
- If you change the overlay port while the GUI is already running, restart the app before using the new port.
- If OCR is not matching correctly, adjust the capture region and OCR language in the studio panel.
- If no target subtitle exists and Foundry Local is not configured, session preparation will fail when translation is needed.
- Search and download require a valid OpenSubtitles API key.

## Troubleshooting

### Search fails immediately

Check:

- `opensubtitles.api_key` is set
- Your internet connection can reach OpenSubtitles

### Prepare session fails on translation

Check:

- The Foundry Local endpoint is running
- The endpoint is reachable from the machine
- The model name is valid, or blank if you want the app to auto-select the first available model

### Overlay opens but no subtitles appear

Check:

- The capture region actually covers the video player's subtitle area
- The OCR language matches the language on screen
- The video subtitle text is close enough to the source subtitle file for fuzzy matching

### Overlay style changes do not show up

Check:

- You clicked `Save Config`
- The overlay page is still connected
- If you changed the port, restart the GUI and reopen the overlay
