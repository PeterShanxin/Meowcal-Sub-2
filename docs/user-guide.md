# User guide

Meowcal Sub 2 reads subtitles visible in a selected screen region and shows
the target language in an always-on-top subtitle strip. A source subtitle file
helps it follow playback; a target file supplies human translations and their
own presentation timings. When a cue has no human translation, the local
translation engine can fill it. Without a matching source, OCR reads can be
translated directly.

## Install and first launch

Get the Windows package matching your architecture from
[Releases](https://github.com/PeterShanxin/Meowcal-Sub-2/releases). Choose `arm64`
for Windows on ARM, or `x64` for Intel/AMD Windows. Windows **Settings → System →
About → System type** identifies your architecture.

Run `meowcal-sub-2-v0.1.0-windows-{arm64,x64}-setup.exe` for a per-user
installation. Alternatively, extract the complete
`meowcal-sub-2-v0.1.0-windows-{arm64,x64}-portable.zip` and open
**Meowcal Sub 2.exe** inside the extracted folder. Keep the `backend` and `core`
folders beside the executable. Both packages include Python and the Core
executable; translation models are installed separately through Settings.

Each architecture has a `meowcal-sub-2-v0.1.0-windows-{arm64,x64}-SHA256SUMS.txt`
file; the release also provides an aggregate checksum list. To check a downloaded
package in PowerShell, compare its result with the matching entry:

```powershell
Get-FileHash .\meowcal-sub-2-v0.1.0-windows-arm64-portable.zip -Algorithm SHA256
```

Source-checkout setup is in the [developer guide](developer-guide.md).

The desktop app needs Microsoft WebView2 and the Windows OCR language pack for
the text on screen. Settings reports available OCR languages and provides the
Windows installation control. Windows may request administrator permission or
a restart to complete a language-pack installation.

Open **Settings** and enable at least one subtitle source:

| Source | Credential |
| --- | --- |
| OpenSubtitles | API key; account credentials when required by the provider |
| SubDL | API key |
| ASSRT | Token |

Disable sources you do not use. Search coverage, service access, and download
allowances depend on the provider. An optional TMDb API key enables metadata
and cross-language title grouping; it is not a subtitle source.

Set the source language to the subtitles visible in the player and the target
language to the one you want to read. The OCR language must also match the
visible text.

For local translation, open **Settings → Translation → Download engine**.
This downloads about 1.1 GB of model data plus the runtime. Meowcal Core verifies
and stores the translation engine separately from the app. Matching verified
artifacts from an earlier Meowcal installation can be imported; Sub 1 is not
required. If a target subtitle supplies the needed translations, the session
can start without the translation engine; uncovered cues cannot be translated
until it is installed.

## Watch with subtitles

1. Start your video in its player and open Meowcal Sub 2.
2. Search for the title. Choose the correct movie, series, season, or episode.
3. Choose a source subtitle and a target subtitle or local translation. Check
   the prepared-session summary; a different release may use different timings.
4. Choose **Select capture region**, drag a box around the player's subtitle
   area, and confirm. Include the complete visible lines and exclude unrelated
   interface text. The region is remembered.
5. Choose **Start sync**. The studio becomes the subtitle strip with a live dock.
6. Play the video. OCR matches establish playback position; target-file cues
   then appear according to their own intervals, including silent gaps.
7. Use **Stop** in the dock when finished. The studio returns with the prepared
   session available to start again.

Keep the Meowcal strip outside the capture region so OCR does not read the
app's own translation.

## Adjust while watching

**Region** reselects the capture box without ending the session. **Settings**
changes capture, language, and subtitle appearance options. The timing control
moves presentation earlier with **+** and later with **−**. Use small adjustments
and watch the next few cues. It cannot repair a subtitle file from a different
cut of the video.

Seeking or resuming playback may need new visible cues before matching recovers.
If the app cannot confirm its playback position for a prolonged period, it clears
the old line rather than keeping a stale subtitle indefinitely.

## Stored data and connections

Configuration lives at `%APPDATA%\meowcal-sub-2\config.toml`.
[config.example.toml](../config.example.toml) shows the configuration format;
Settings is the usual way to edit it. Changing the studio port requires a restart.
Downloaded subtitles are cached under `%USERPROFILE%\.cache\meowcal-sub-2`.

OCR and local translation inference run on the machine. Enabled subtitle
providers receive searches and download requests. Optional TMDb lookups, studio
fonts from Google Fonts, and runtime/model installation also use the network.

Normal logs in `%APPDATA%\meowcal-sub-2\logs` use INFO. Explicit verbose mode
adds detailed OCR and subtitle traces. Even normal logs can include titles,
errors, and sensitive details. Do not share raw logs, provider credentials,
the token-bearing studio URL, or screenshots of private viewing content.

## Troubleshooting

### Search is empty or a source fails

Check the source's enabled switch and credentials in Settings, the title and
language pair, your connection, and the provider's download allowance. The
search notice identifies failed sources; other configured sources can still
return results.

### No line appears or OCR reads the wrong text

Reselect the region and check that it contains the full player subtitle. Verify
the OCR language and that Windows reports its language pack as installed. Avoid
capturing player controls or the Meowcal strip. Protected playback surfaces may
not be capturable; OCR cannot read a blank or black capture.

### Subtitles drift or the wrong line appears

Check the selected episode and release. Try a small timing adjustment for a
constant delay. For a different video cut, choose another source/target file.
Do not lower the matching threshold to force unrelated dialogue to match.

### Translation is unavailable

Check **Settings → Translation** for installation progress or an error. Retry
the engine download if it failed. Translation speed depends on the machine;
an answer that times out or fails validation is not shown.

### OCR installation is offered again

Wait for Windows installation to finish and reopen the language list. Restart
Windows if the new pack is not reported. The app's post-install language list,
not the completion of the installer alone, determines availability.

For a reproducible app problem, [open an issue](https://github.com/PeterShanxin/Meowcal-Sub-2/issues)
with the app version, Windows architecture, steps, and sanitized error details.
