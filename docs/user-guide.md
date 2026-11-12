# User guide

Meowcal Sub 2 reads subtitles visible in a selected screen region and shows
the target language in an always-on-top subtitle strip. A source subtitle file
helps it follow playback; a target file supplies human translations and their
own presentation timings. When a cue has no human translation, the local
translation engine can fill it. Without a matching source, OCR reads can be
translated directly.

This guide describes the current source on `main`. The latest published release
(v0.2.2) does not yet include these parts of it:

- the **OCR engine** setting and PP-OCRv6, which need Meowcal Core 0.2.2
  (v0.2.2 includes Core 0.1.4 and uses Windows OCR);
- the **Use on-screen OCR** source choice when no source file matches;
- per-file language detection inside ASSRT packages;
- the playback-continuity and movie-grouping corrections made after v0.2.2.

A build from `main` also reports version 0.2.2. The
[developer guide](developer-guide.md#release-applicability) explains the difference.

## Install and first launch

Get the Windows package matching your architecture from
[Latest release](https://github.com/PeterShanxin/Meowcal-Sub-2/releases/latest). Choose `arm64`
for Windows on ARM, or `x64` for Intel/AMD Windows. Windows **Settings → System →
About → System type** identifies your architecture.

Run `meowcal-sub-2-v*-windows-{arm64,x64}-setup.exe` for a per-user
installation. Alternatively, extract the complete
`meowcal-sub-2-v*-windows-{arm64,x64}-portable.zip` and open
**Meowcal Sub 2.exe** inside the extracted folder. Keep the `backend` and `core`
folders beside the executable. Both packages include Python and the Core
executable; translation models are installed separately through Settings.

The published v0.1.0 and v0.2.0 cannot check for app updates. Install v0.2.1 or
later manually. Signed installer releases check for updates when the app opens
and offer **Install update** in the app and under **Settings → Updates**
(**Check for updates** asks again). Portable copies must be replaced manually.

Each architecture has a `meowcal-sub-2-v*-windows-{arm64,x64}-SHA256SUMS.txt`
file; the release also provides an aggregate checksum list. To check a downloaded
package in PowerShell, compare its result with the matching entry:

```powershell
Get-FileHash .\meowcal-sub-2-v*-windows-arm64-portable.zip -Algorithm SHA256
```

Source-checkout setup is in the [developer guide](developer-guide.md).

The desktop app needs Microsoft WebView2. Windows OCR needs the Windows language
pack for the language on screen. To add one, add the language in Windows
**Settings → Time & language → Language & region**; Windows may ask for
administrator permission or a restart. Restart Meowcal Sub 2 after the pack is
installed.

### Subtitle sources

Open **Settings → Subtitle sources** and turn on at least one source:

| Source | Credential |
| --- | --- |
| OpenSubtitles | **API key**; **Username** and **Password** when the provider requires them |
| SubDL | **API key** |
| ASSRT | **Token** |

Each source has an **Enabled**/**Disabled** switch. A source that is enabled but
has no credential is skipped, and the search screen shows a notice such as
"OpenSubtitles key missing". Disable sources you do not use. Coverage, service
access, and download allowances depend on the provider. OpenSubtitles limits
downloads per day; the app does not spend the last two remaining downloads on
comparing alternative target files.

**TMDb cross-lingual merge** with a **TMDb API key** groups the same title across
languages. TMDb is not a subtitle source.

### Languages

The two language buttons beside the search field show the source and target
codes, for example `ZH → EN`. The source language is the one in the subtitles
visible in the player; the target language is the one you want to read. Chinese
has two choices: **Chinese (Simplified)** (`zh`) and **Chinese (Traditional)**
(`zht`). Choosing the language already used on the other side
swaps the pair. Changing a language clears the current selection and runs the
last search again.

The OCR language follows the source language. **Settings → Capture → OCR
language** shows it.

### Local translation

Open **Settings → Translation** and choose **Download engine**. This downloads
about 1.1 GB of model data plus the runtime. If the download fails, choose
**Retry download**. Meowcal Core verifies and stores the translation engine
separately from the app. Matching verified artifacts from an earlier Meowcal
installation can be imported; Sub 1 is not required.

Without the translation engine, these sessions work:

- a source file with a target file;
- a source file that carries its own translation.

The studio then shows the notice "Local translation is not installed. Human
subtitles remain available after a match, but untranslated gaps cannot be
filled." These choices need the engine: **Local translation**, **OCR fallback only**, and
**Use on-screen OCR**.

## Watch with subtitles

1. Start your video in its player and open Meowcal Sub 2.
2. Search for the title. Choose the movie, or the series, season, and episode.
   Choosing an episode runs one exact search for that episode, which can add
   subtitle versions; the results from the title search stay available.
3. Choose **Select source subtitle** and pick a file in the source language.
   Then choose **Select target subtitle** and pick one target. The Target list
   can offer:
   - **Translation inside the source file**, when the chosen source is bilingual;
   - target-language files;
   - **Local translation**, which translates the source lines on this device;
   - **OCR fallback only**, which translates OCR text live without a file.
4. Wait while the studio shows **Preparing**. When **Session ready** appears,
   check the **Source**, **Target**, **Lines**, and **Coverage** rows. A different
   release can use different timings. Open **Subtitles checked automatically** to
   see what preparation changed.
5. Choose **Start OCR and sync** (or press Ctrl+Enter). The capture selector
   opens on the screen. Drag a box around the player's subtitle area and choose
   **Confirm**. Choose **Switch display** if the player is on another screen, or
   **Cancel** to return without starting.
6. The studio becomes the subtitle strip with a live dock. Play the video. OCR
   matches establish the playback position; target-file cues then appear
   according to their own intervals, including silent gaps.
7. Choose **Stop sync** in the dock when finished. The prepared session stays
   available to start again.

Each start asks for the capture region. Include the complete visible subtitle
lines and exclude player controls and other text. Keep the Meowcal strip and the
dock outside the region so OCR does not read the app's own translation.

Closing the studio window stops the session and exits the app. The tray's
**Exit** action does the same.

For keyboard selection, use arrows and Enter from the search field, or Tab to
a title, season, episode or subtitle result and press Enter or Space. Arrows
move focus between result buttons. Expanded and selected results expose their
state to assistive technology, and activating a result returns focus to search
for the next step. Arrow keys outside the palette keep their usual behavior.

### Choosing subtitle files

- **Release.** Prefer a file named for the same release as your video (for
  example the same streaming source or disc). Files for a different cut can
  drift or skip.
- **Language tags.** A file's row shows its language and format. A package that
  contains several files lists each file separately. A file marked with two
  languages, for example Chinese and English, is bilingual and appears in both
  lists. A file without a language tag in a mixed package can appear in both
  lists; open its name to check.
- **Bilingual sources.** When the chosen source carries a translation, the Target
  list puts **Translation inside the source file** first. It has exact timing and
  needs no download.
- **Better targets.** After preparation, the card can suggest another target file
  that answers more lines. Choose **Use it** to prepare with that file.
- **Target timing is unverified.** This note means that no shared human
  subtitle text confirmed that the source and target files use the same clock.
  Watch the first minutes and correct the target file in the editor if needed.

### When no source file matches

If the chosen title has no file in the source language, the Source list offers
**Use on-screen OCR**. This reads the screen and translates live, with an
optional target file. It is slower than the source-file workflow, needs the
translation engine, and can translate scene text that is not dialogue. Target
file timing cannot follow a source clock in this mode.

### Empty results and source failures

| What you see | Meaning | What to do |
| --- | --- | --- |
| `No titles found for "…"` | The search finished, and the enabled sources returned nothing | Try another spelling, the original title, or the other language. An empty answer does not prove that no subtitle exists. |
| `No results — the search did not finish` with a notice | Every source that ran failed | Read the notice. It names each source's error. |
| "Every subtitle source is switched off. Turn one on in Settings." | No source is enabled | Enable a source in **Settings → Subtitle sources**. |
| A notice such as "SubDL key missing" or "ASSRT is disabled, so Chinese subtitle coverage may be thin." | A source was skipped | Add the credential or enable the source if you need it. |
| Results with a notice | Some sources failed and others answered | Results from the working sources are usable. |
| `No subtitles for this episode` | The open Source or Target list has no file for this episode | Choose another episode, check the language pair, or use the fallback choices in the list. |

## OCR engine

**Settings → Capture → OCR engine** has three choices. The choice applies when a
session starts.

- **Automatic** uses Windows OCR when the exact Windows language pack is
  installed. Otherwise, it uses PP-OCRv6 for English, Chinese, Japanese,
  Spanish, French, and German. A session without a source file also accepts a
  compatible installed Windows pack, for example Simplified Chinese for
  Traditional Chinese text, because PP-OCRv6 reads more scene text.
- **Windows OCR** always uses Windows OCR and its language packs.
- **PP-OCRv6** uses PP-OCRv6 for the languages above. Korean always uses
  Windows OCR.

PP-OCRv6 is included in Core and needs no Windows language pack. In the
recorded tests it read text more accurately than Windows OCR, but it did not
display more cues, and each frame took longer and used more CPU (see
[OCR measurements](OCR_BENCHMARK.md)).

When PP-OCRv6 is not available in Core, cannot start, or does not support the
language, the session uses Windows OCR. The studio does not show this change
while the session runs; the event log records which engine was used
(`ocr.engine.ready`). When Windows OCR has no usable language pack either,
start stops with a message that names the missing pack.

## Repair a subtitle before sync

At **Session ready**, choose **Edit subtitles**. The workspace opens the prepared
source and target files, including source candidates in automatic selection mode.
Stop a running session before editing.

- Select a track, then a subtitle. Edit its text or start/end time and choose
  **Keep edit**. Times use whole milliseconds: 1000 ms is one second.
- **Shift all subtitles** fixes a constant delay. A negative shift makes the file
  earlier; a positive shift makes it later.
- **Match two points** fixes gradual drift. Enter the subtitle and video times
  for one early and one late cue. Both pairs must advance in time.
- Choose **Preview timing**, inspect the before/after columns, then **Apply timing**.
  Paging and subtitle-number jumps also work during preview. Each track retains
  its own timing fields and up to 50 undo steps while the workspace is open.
- **Import replacement** loads a local UTF-8 SRT or WebVTT into the selected track.
  **Export copy** downloads the current corrected file without changing the session.
- **Save & use** saves changed tracks as new files and rebuilds the prepared session.
  The playback offset returns to 0 ms; start sync to use the corrected tracks.

Errors such as empty bodies, invalid intervals or text that cannot be encoded
safely block saving. Overlaps, duplicates and out-of-order cues are warnings,
because some are intentional. Unsupported WebVTT structures, including STYLE
and REGION blocks, are rejected instead of discarded. Supported notes, cue
identifiers, settings and text are preserved; output uses LF line endings and
consecutive SRT numbering. Files must be UTF-8 and at most 4 MiB.

If saving fails, the new copies are removed and the previous prepared session
stays unchanged. Correct the reported problem and save again. Original files stay
untouched. Corrected session copies live under
`%APPDATA%\meowcal-sub-2\subtitles\corrected`. Export a copy to keep it somewhere
else or import it into another session.

## Adjust while watching

The live dock has these controls:

- **Region** reselects the capture box without ending the session. Use it after
  you move the player or change monitors.
- **Settings** changes capture, language, and subtitle appearance options.
- **+** shows subtitles earlier and **−** shows them later. Use small steps and
  watch the next few cues. The timing control cannot repair a file from a
  different cut of the video.
- **Stop sync** ends the session.

Seeking or resuming playback may need new visible cues before matching recovers.
If the app cannot confirm its playback position for a prolonged period, it clears
the old line rather than keeping a stale subtitle indefinitely. While no source
match is current, live OCR translation can appear in place of the file cue.

## Stored data and connections

Configuration lives at `%APPDATA%\meowcal-sub-2\config.toml`.
[config.example.toml](../config.example.toml) shows the configuration format;
Settings is the usual way to edit it. Changing the studio port requires a restart.
Downloaded subtitles are cached under `%USERPROFILE%\.cache\meowcal-sub-2`.

OCR and local translation inference run on the machine. Enabled subtitle
providers receive searches and download requests. Optional TMDb lookups, studio
fonts from Google Fonts, and runtime/model installation also use the network.

## Logs and diagnostics

Logs are in `%APPDATA%\meowcal-sub-2\logs`:

- `meowcal-sub-2.log` records the app at INFO level. A new file starts each day,
  and seven previous files are kept.
- `meowcal-sub-2.events.jsonl` records app events, one per line. At 5 MiB it is
  renamed to `meowcal-sub-2.events.jsonl.1`, which replaces the previous one.

The event log removes credential-like values and URL query values, but both logs
can contain titles, search queries, file names, and error text. Detailed OCR and
subtitle traces, which contain recognized text and subtitle lines, are written
only when a developer runs the backend in verbose mode.

**Settings → Debug → Enable debug overlay** sends per-capture timing and match
data over the studio connection for developers. The studio does not display it,
and it does not add detail to the log files.

Do not share raw logs, provider credentials, the token-bearing studio URL, or
screenshots of private viewing content.

## Uninstall

Uninstall the installed app from Windows **Settings → Apps**. Check **Delete
the application data** to also remove the folders below. Earlier versions kept
the translation engine in `%LOCALAPPDATA%\Meowcal\Core\production`, which
Meowcal Sub shares; the uninstaller removes it only when Meowcal Sub has never
run on the machine.

The portable package has no uninstaller. Close the app, delete the extracted
folder, then delete these folders:

| Folder | Contents |
| --- | --- |
| `%APPDATA%\meowcal-sub-2` | Configuration, logs, corrected subtitles |
| `%USERPROFILE%\.cache\meowcal-sub-2` | Downloaded subtitles |
| `%LOCALAPPDATA%\com.meowcal.sub2` | Embedding model, WebView data |
| `%LOCALAPPDATA%\Meowcal\Core\sub2` | Translation engine |

Delete `%LOCALAPPDATA%\Meowcal\Core\production` as well if you do not use
Meowcal Sub.

## Troubleshooting

### Search is empty or a source fails

Use the table in [Empty results and source failures](#empty-results-and-source-failures).
Check the source's switch and credentials, the title and language pair, your
connection, and the provider's download allowance.

### A download fails

If ASSRT reports "ASSRT no longer provides the selected file. Search again.",
run the search again and choose the file again. If a provider reports that the
download allowance is used up, choose a file from another source or wait for the
allowance to renew.

### Preparation stops with an error

A file-specific error, for example "cue 12 has invalid timing", means that the
file cannot be played safely. Choose another file, or fix the file and import it
with the subtitle editor. If the error is about the translation engine, install
it under **Settings → Translation**, or choose a target file.

### No line appears or OCR reads the wrong text

Choose **Region** and check that the box contains the full player subtitle.
Check the source language and the **OCR engine** setting. For Windows OCR,
confirm that Windows lists the language pack as installed. Avoid capturing
player controls or the Meowcal strip. Protected playback surfaces may not be
capturable; OCR cannot read a blank or black capture.

### Subtitles drift or the wrong line appears

Check the selected episode and release. Try a small timing adjustment for a
constant delay. For a different video cut, choose another source/target file.
Do not lower the matching threshold to force unrelated dialogue to match.

### Translation is unavailable

Check **Settings → Translation** for installation progress or an error. Retry
the engine download if it failed. Translation speed depends on the machine;
an answer that times out or fails validation is not shown.

### The app does not start or shows an old screen

Close the app from the tray's **Exit** action and open it again. If the problem
remains, restart Windows before reporting it.

## Report a problem

For a reproducible app problem, [open an issue](https://github.com/PeterShanxin/Meowcal-Sub-2/issues).
Include:

- the app version, from **Settings → Updates** or the release you installed;
- whether you use the installer, the portable package, or a source build;
- the Windows version and architecture;
- the steps, the OCR engine setting, and which sources were enabled;
- the exact error text, with titles and personal details removed.

Do not attach private subtitle dialogue, viewing screenshots, raw logs,
credentials, or tokens. If a log excerpt is needed, copy only the relevant lines
and remove titles, file names, recognized text, and paths that contain your
user name.
