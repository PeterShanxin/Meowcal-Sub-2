# Meowcal-Sub-2 User Guide

## What It Does

Meowcal Studio watches a region of your screen while you play something, reads the
subtitle burned into that region with Windows OCR, and shows the line in the
language you want.

It gets that line one of two ways:

- **Matched to a downloaded subtitle.** When a subtitle file exists for what you
  are watching, the app downloads a few candidates, matches what OCR reads against
  them, and shows the paired line from the target-language file.
- **Translated on this machine.** When no source subtitle matches, the app
  translates what OCR reads with its own local engine. Nothing captured from your
  screen leaves the device.

## Before You Start

Requirements:

- Windows
- Python 3.11+
- At least one subtitle source credential:
  - OpenSubtitles API key
  - SubDL API key
  - ASSRT token

Default config path on Windows: `%APPDATA%/meowcal-sub-2/config.toml`. Use
[config.example.toml](../config.example.toml) as the starting point; everything in
it can also be edited from Settings inside the app.

Minimum config for search:

```toml
[subtitle_sources.opensubtitles]
enabled = true
api_key = "YOUR_API_KEY_HERE"

[languages]
source = "en"
target = "zh"
```

Translation needs no configuration. The first time a session needs it, Settings
offers a one-time download of the translation engine (about 1.1 GB). If Meowcal
Sub v1 already installed that engine on this machine, it is reused and nothing is
downloaded.

## Using It

1. Start the app with `run_app.vbs`.

2. Type a title and press Enter.

   The language pair beside the search box is part of the query: `EN → zh` finds
   English subtitles to read from the screen and Chinese ones to show you.
   Changing either language runs the search again.

3. Pick the title. The app prepares the session by itself: it downloads a few
   source candidates and the best target subtitle, and tells you what it found.

   If no subtitle matches your source language, it says so and prepares an
   OCR-and-translate session instead.

4. Choose **Select capture region** and drag a box over the subtitle area of your
   player, then confirm. The box is remembered between sessions.

   Leave room at the bottom of the screen: while a session runs, the app's own
   window becomes a subtitle strip pinned there.

5. Choose **Start sync**.

   The window becomes the subtitle strip. It shows the current line, the previous
   line above it, and a dock with stop, region and settings.

6. Play your video. Lines appear as they are read.

7. Press stop in the dock when you are done. The window returns to the studio with
   the session still prepared, so you can start again without repeating anything.

## Adjusting While Watching

- **Region** in the dock reselects the capture area without stopping the session;
  the next frame uses the new box.
- **Settings** opens the same settings the studio has.

## Notes

- The subtitle strip is the app's own window, not a separate compositor. It sits
  above other windows while a session runs.
- Changing the overlay port needs a restart before the new port is used.
- Search coverage depends on which subtitle sources are enabled and configured. A
  source that fails is reported and the others are still used.

## Troubleshooting

### Search returns weak or empty results

Check the enabled subtitle sources and their credentials in Settings, and your
connection to them. The search notice names any source that failed.

### The strip says the translation engine is not installed

Open Settings → Translation and choose **Download engine**. It is a one-time
download; progress is shown in the same place.

### No subtitles appear

Check, in this order:

- the capture region actually covers the player's subtitle area — reselect it and
  look at what is inside the box while you drag
- the OCR language matches the language on screen
- the title you picked is the one you are watching, so the downloaded subtitles
  line up with it

### The OCR language install keeps asking

Windows sometimes needs a restart before a newly installed OCR language pack is
reported as available.
