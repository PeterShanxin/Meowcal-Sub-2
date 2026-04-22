# Meowcal-Sub-2 User Guide

## What It Does

`meowcal-sub-2` helps you:

- Search across enabled subtitle providers
- Choose a source subtitle and an optional target subtitle
- Fall back to local translation through Foundry Local when a target subtitle is missing
- Fall back to OCR-based live translation when no source subtitle matches
- Sync translated subtitle text to on-screen playback through OCR plus fuzzy matching
- Show the translated line in a local browser overlay while keeping the Tauri desktop shell available on Windows

The main workflow is the local dashboard launched with `meowcal-sub-2 gui` or the Windows launcher `run_app.vbs`.

## Before You Start

Requirements:

- Windows
- Python 3.11+
- Optional subtitle source credentials:
  - OpenSubtitles API key
  - ASSRT token
- Optional but recommended local translation backend:
  - Foundry Local OpenAI-compatible endpoint

Default config path on Windows:

- `%APPDATA%/meowcal-sub-2/config.toml`

Use [config.example.toml](../config.example.toml) as the starting point.

Minimum config for a provider-neutral search flow:

```toml
[subtitle_sources.opensubtitles]
enabled = true
api_key = "YOUR_API_KEY_HERE"

[subtitle_sources.subdl]
enabled = true

[languages]
source = "en"
target = "zht"
```

If you want local translation fallback, also set:

```toml
[translation]
endpoint = "http://127.0.0.1:5273/v1"
model = ""
```

If you want the dashboard debug panel, also set:

```toml
[debug]
mode = true
```

## Install

```bash
pip install -e ".[dev]"
```

## Quick Start With The Dashboard

1. Start the dashboard:

   ```bash
   meowcal-sub-2 gui
   ```

   Or on Windows, launch `run_app.vbs`.

2. Wait for the startup overlay to clear. The studio is ready only after saved settings and language options are loaded.

3. In the search bar:

   - Enter the movie or episode title
   - Set the source language code
   - Set the target language code
   - Click `Find Subtitles`

4. In the results workspace:

   - Pick the matched title
   - Choose a source subtitle from the merged provider list
   - Choose a target subtitle if available, or confirm `Use local translation`
   - If no usable source subtitle exists, choose the OCR fallback source option

5. Click `Prepare Session`

   This downloads the selected subtitle files and, when needed, translates the source lines through Foundry Local.

6. In the settings drawer:

   - Adjust subtitle-source credentials or enable flags
   - Set OCR and capture settings
   - Adjust overlay style
   - Save config if you changed settings

7. Select the capture region if it is not set yet.

8. Click `Start Sync`

   This opens or updates the overlay at:

   - `http://127.0.0.1:8765/overlay`

9. Start your video. The app captures the configured subtitle band, OCRs the visible text, matches it against the prepared session, and broadcasts the translated line to the overlay.

10. Click `Stop Session` when you are done.

## Dashboard Areas

### Dashboard View

- Title search
- Source and target language pickers
- High-level session status

### Results View

- Matched title list
- Source subtitle candidates
- Target subtitle candidates
- OCR fallback option when source coverage is thin

### Session View

- Prepared-session summary
- Current subtitle preview
- Foundry/OCR/capture readiness cards
- Start/stop controls

### Settings Drawer

- Subtitle source toggles and credentials
- Translation endpoint/model fields
- OCR and capture region settings
- Overlay style controls and live preview

## CLI Alternatives

The CLI commands still work when you want a narrower workflow:

```bash
meowcal-sub-2 search "Inception" --source en --target zht
meowcal-sub-2 translate .\movie.en.srt
meowcal-sub-2 start .\movie.en.srt --target-file .\movie.zht.srt
meowcal-sub-2 serve
```

## Important Notes

- The overlay is browser-based. The desktop shell wraps the same served UI, but the overlay itself is not a separate native subtitle compositor.
- If you change the overlay port while the app is already running, restart the dashboard before using the new port.
- If OCR is not matching correctly, fix the capture region first, then verify the OCR language.
- If no target subtitle exists and Foundry Local is unavailable, session preparation or OCR fallback translation will fail.
- Search coverage depends on which subtitle sources are enabled and configured.

## Troubleshooting

### Search returns weak or empty results

Check:

- enabled subtitle sources in the settings drawer
- OpenSubtitles API key, if you rely on OpenSubtitles
- ASSRT token, if you want better Chinese coverage
- your network connection to the enabled providers

### Prepare session fails on translation

Check:

- the Foundry Local endpoint is running
- the endpoint is reachable from the machine
- the model name is valid, or blank if you want the app to auto-select the first available model

### Overlay opens but no subtitles appear

Check:

- the capture region actually covers the video player's subtitle area
- the OCR language matches the language on screen
- the source subtitle choice is the right file for the media you are watching
- the live subtitle text is close enough to the prepared source text for fuzzy matching

### OCR install button keeps appearing

Check:

- whether Windows really installed the OCR language pack
- whether the dashboard reloaded the OCR language catalog after install
- whether you need to restart Windows for the OCR pack to appear

### Overlay style changes do not show up

Check:

- you clicked `Save Changes`
- the overlay page is still connected
- you restarted the dashboard after any port change
