# Developer guide

Meowcal Sub 2 combines a Python backend, a React studio served over loopback,
and a Tauri desktop shell. Read [AGENT_GUIDE.md](AGENT_GUIDE.md),
[CODING_STANDARDS.md](CODING_STANDARDS.md), and
[MAINTAINABILITY_BASELINE.md](MAINTAINABILITY_BASELINE.md) before changing code.

This guide owns the runtime contracts below. Specialized documents own
[Meowcal Core integration](MEOWCAL_CORE.md), [Core upgrades](CORE_UPGRADE_AUTOMATION.md),
[OCR measurements](OCR_BENCHMARK.md), [playback evidence](PLAYBACK_EVIDENCE.md),
and [playing-confidence calibration](PLAYING_CONFIDENCE_CALIBRATION.md).
Files under `docs/plans/` and `docs/audit-20260926/` are dated records, not
statements of current behavior.

## Set up a Windows checkout

Install Python 3.11 or newer, Node.js 22 LTS (22.12 or newer) with npm, Rust,
the Microsoft C++ build tools required by Tauri, and Microsoft WebView2.
Vite also supports Node 20.19 or newer. Use PowerShell from the repo root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
npm --prefix src\meocosub2\overlay\ui ci
python -m playwright install chromium
rustup component add rustfmt clippy
```

The debug shell prefers `.venv\Scripts\python.exe` for source development.
`MEOWCAL_PYTHON` can select another development Python executable. Release builds
use the bundled `backend/python.exe` and do not fall back to a developer install.

## Run modes

| Mode | Start | What runs |
| --- | --- | --- |
| Browser mode | `python -m meocosub2.cli serve`, then open the printed token-bearing URL | Source backend and the committed studio bundle in a browser. No capture selector, subtitle plate, live dock, tray, or updater. |
| Tauri debug | `run_app.vbs` (`--rebuild` forces a rebuild) | Debug shell from `src-tauri/target/debug`, source backend, committed studio bundle. |
| Optimized build | `.\scripts\build-windows-release.ps1` | Release shell with a bundled CPython backend, Core, and a rebuilt studio bundle in `dist/`. |
| Installer | `…-setup.exe` from a build or release | Per-user NSIS installation of the optimized build. Signed releases can update in place. |
| Portable | `…-portable.zip` from a build or release | The same payload as the installer, run from its extracted folder. Updates are manual. |

`run_app.vbs` prepares the pinned Core resource, rebuilds the studio bundle when
its sources are newer than `static/index.html`, and rebuilds the debug shell
when its Rust sources, manifests, or Tauri configuration are newer than the
executable.
Before it starts, it force-stops every `meowcal-sub-2-shell` process, every
Python process running `meocosub2.cli serve`, and any process listening on port
8765. This includes an installed copy that is running. Afterwards, check for
surviving Core children as described in
[the agent guide](AGENT_GUIDE.md#stopping-the-app-without-leaking-the-engine).

### Stale code under test

- The shell reuses any backend that already answers on its configured port.
  Rebuilding only the shell leaves the old Python code running.
- The studio is served from the committed bundle in `overlay/static/`. A source
  change under `overlay/ui/src/` is not visible until
  `npm --prefix src\meocosub2\overlay\ui run build` rewrites that bundle.
- `selector.*` and `splash.html` are compiled into the shell binary. A change to
  them needs a shell rebuild, and `run_app.vbs` does not detect it: use
  `run_app.vbs --rebuild`.
- WebView2 can show an older bundle after a rebuild. The shell adds a
  `desktopLaunch` cache-buster and the server marks `index.html` as `no-store`.
- An installed or portable build runs its own bundled backend. Testing that build
  does not test the checkout, even when both report the same version.

### Profile isolation

Source and installed runs are not isolated by default. Every mode reads and
writes the same configuration, runtime token, logs, corrected subtitles,
subtitle cache, TMDb cache, BGE engine, and WebView2 data (see
[Storage locations](#storage-locations)). They also use the same default port.

Only Core storage has a profile switch. `run_app.vbs` sets
`MEOWCAL_CORE_PROFILE=development`. A backend started directly with `serve`
uses the `production` Core profile unless you set that variable.
`MEOWCAL_CORE_STORAGE_ROOT` moves the Core storage base, and
`MEOCOSUB2_EVENT_LOG_PATH` moves the event log.

To keep test data out of a real profile, point `APPDATA`, `LOCALAPPDATA`, and
`USERPROFILE` at a disposable directory for the processes under test, and use a
different `[overlay] port`. Do not run experiments, benchmarks, or destructive
tests against the real profile or real provider credentials. Provider downloads
spend metered allowances, and a test can overwrite the viewer's configuration.

## Build a Windows distribution

Set the same `X.Y.Z` version in
`tauri.conf.json`, `Cargo.toml`, `Cargo.lock`, `pyproject.toml`, and the studio's
`package.json` and `package-lock.json`, plus the backend's `__init__.py`.
`scripts/check_app_version.py` checks
these files in CI and requires a matching `vX.Y.Z` tag for signed release builds.
The repository banner does not display a release version. After editing its SVG
artwork, regenerate the PNG export before committing:

```powershell
python scripts/update_branding.py
```

This uses the existing Playwright Chromium development dependency. The release
build also runs it automatically; unchanged assets are left alone. Verification
rejects a stale PNG export, so commit the artwork and its export together.
README downloads link to the latest published GitHub Release.

The [product page](https://petershanxin.github.io/Meowcal-Sub/sub-2/) is built
from the Meowcal Sub repository and states the release it describes. After a
release is published, update the Sub 2 version, copy, and screenshot there. See
that repository's [site instructions](https://github.com/PeterShanxin/Meowcal-Sub/blob/main/site/README.md).

Use a native x64 or ARM64 Windows environment with PowerShell 7 and the tools
above. Install GitHub CLI and authenticate with `gh auth login`; the build reads
upstream license files that some published crates omit. CI supplies its read-only
GitHub token for this step.

```powershell
.\scripts\verify.ps1
.\scripts\build-windows-release.ps1
```

The build verifies the locked Core and CPython archives, installs hash-locked
backend wheels, collects dependency notices, and produces an NSIS installer,
portable ZIP, and SHA-256 list in `dist/`. Models are not bundled. Use a clean
commit for release artifacts; the portable package records its source commit
and whether the checkout had changes. Move any previous staging directory out
of `dist/` before rebuilding. Native acceptance must pass before publishing.

For an updater-capable release, configure the repository secret
`TAURI_SIGNING_PRIVATE_KEY`, optional secret
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD`, and variable
`MEOWCAL_UPDATER_PUBLIC_KEY` containing the matching generated `.pub` value.
The public key is compiled into the installed shell; keep the private key out of
the repository. Push an exact `vX.Y.Z` tag after branch-build acceptance. The
tag build requires both keys, signs each architecture's NSIS installer,
verifies each signature against the public key embedded in the shell, and
produces a separate `latest.json` workflow artifact. The workflow does not
publish a GitHub Release. Upload both installers, their `.sig` files, and
`latest.json` to a draft release; publish it only after native acceptance of
the final signed installers. The JSON contains both architecture URLs and signatures.
An unsigned branch build has no in-app updater. Portable packages always
require manual replacement.

### Signed installer acceptance

The disposable runner's three Sub 2 data directories must be absent before
acceptance. The test temporarily links them to its synthetic profile because
NSIS `RunAsUser` recreates the user's environment during automatic restart.
This preserves the same fixture across the handoff without changing persistent
environment settings. Cleanup removes only links whose recorded targets still
match the test directory. The helper refuses local and self-hosted machines.

`installer-acceptance.yml` uses standard disposable Windows x64 and ARM64 hosted
runners with read-only repository/artifact access. It downloads the fixed signed
receiver and target builds in `config/installer-acceptance.json`; it does not
rebuild, sign, publish, or run on a developer's desktop. Expired artifacts fail
the job rather than silently substituting another build.

The test checks hashes, signatures and installed payloads, cancels the target
installer before installation, opens the native Studio and Settings, then upgrades
the signed test receiver in place. It verifies automatic restart, exact settings
and subtitle-cache retention, graceful child-process shutdown, and uninstall.
`report.json` is uploaded on success or failure, without runtime tokens or profiles.
An unavailable native accessibility surface fails acceptance; browser/backend
checks do not substitute for it.

This proves the installer path before publication. It does not prove production
update discovery/download, the app's Later button, mid-download cancellation,
physical monitor behavior, or OCR. Published v0.1.0/v0.2.0 installations still
require a manual first upgrade because those public builds disabled the updater.

## Release applicability

Three things are distinct:

- **Main** is the committed source. It can contain behavior that no published
  package has.
- **A published release** is a GitHub Release with its assets. Only that release's
  assets and notes establish what viewers can download.
- **Local components** are builds from a checkout, candidate Core packages, and
  files copied into an installation by hand. They prove nothing about either
  of the above.

Version fields do not establish release availability. Main can carry the same
app version as the latest release while it contains later changes, and a local
build from main reports that version too. The App version and the Core version
are independent: `config/meowcal-core.lock.json` pins Core for each build. When
user-facing documentation describes a behavior that is on main but not in the
latest published release, say so in that document.

## Runtime map

| Responsibility | Source |
| --- | --- |
| CLI and local server lifetime | `src/meocosub2/cli.py` |
| HTTP/WebSocket routes | `src/meocosub2/overlay/server.py` |
| Session preparation and lifecycle | `src/meocosub2/overlay/controller.py` |
| Subtitle providers and aggregation | `src/meocosub2/subtitle_sources/` |
| Subtitle loading and playback checks | `src/meocosub2/subtitles.py` |
| Subtitle editor documents | `src/meocosub2/overlay/subtitle_editor.py` |
| OCR engine selection and passes | `src/meocosub2/capture.py`, `src/meocosub2/native_ocr.py` |
| Capture loop and session strategies | `src/meocosub2/sync.py` |
| Playback clock | `src/meocosub2/timeline.py` |
| Target cue presentation | `src/meocosub2/presentation.py` |
| Gap filling and idle prefill | `src/meocosub2/gapfill.py`, `src/meocosub2/prefill.py` |
| Core client and process lifetime | `src/meocosub2/core_client.py`, `src/meocosub2/core_process.py` |
| Core translation adapter and private BGE matcher | `src/meocosub2/engine/` |
| Per-run authentication | `src/meocosub2/auth.py` |
| Studio state and views | `src/meocosub2/overlay/ui/src/` |
| Desktop windows and backend process | `src-tauri/src/` |

The server-backed `/` route is the desktop studio. Edit React/TypeScript under
`src/meocosub2/overlay/ui/src/`, then rebuild the committed served bundle:

```powershell
npm --prefix src\meocosub2\overlay\ui run build
```

Do not edit `overlay/static/assets/` directly. The hand-maintained selector and
splash files under `overlay/static/` are embedded by Tauri; changes to them need
a shell rebuild.

### Responsibilities

- **Backend** (`serve`): owns configuration, provider calls, downloads, subtitle
  checks, session preparation, OCR, matching, the playback clock, translation,
  and the Core processes. It binds `127.0.0.1` on the configured port.
- **Studio** (React): owns screen state and selection. It reaches the backend
  through typed HTTP wrappers and the `/ws/app` WebSocket. It does not restate
  backend rules.
- **Shell** (Tauri): owns the windows, the capture selector, the subtitle plate,
  the live dock, the tray, the updater, and the backend process when it starts
  one. It reads the runtime token from `runtime.json`.

### End-to-end sequence

1. **Search.** The studio posts the query and the language pair. The aggregator
   asks each enabled provider at the same time and publishes an interim catalog
   when each provider finishes. A disabled or unconfigured provider adds a
   warning, not results.
2. **Language parsing.** Each adapter maps its own language data to internal
   codes: `zh` is Simplified Chinese and `zht` is Traditional Chinese.
   OpenSubtitles uses `zh-cn`/`zh-tw` on the wire. SubDL buckets are normalized
   from encoding-style keys. ASSRT classifies each archive member by its file
   name.
3. **Filtering and aggregation.** Results outside the requested languages are
   dropped. The rest are grouped into works, seasons, episodes, and matches (see
   [Subtitle discovery](#subtitle-discovery)). When the TMDb merge is on and a
   TMDb key is set, works in different languages can merge.
4. **Selection.** The viewer picks a work and an episode. Selecting an episode
   runs one exact lookup for that episode. The studio then lists Source and
   Target results by opaque IDs. Choosing a Source reads it once to find a
   carried translation before the Target list is shown.
5. **Download and validation.** Preparation downloads the chosen files and
   checks each one (see [Subtitle checks and editing](#subtitle-checks-and-editing)).
6. **Preparation.** The backend builds the source candidates and the target
   presentation track, calibrates the file-clock offset, weighs alternative
   targets within a fixed budget, starts the translation engine when it is
   needed, and begins idle prefill. The studio shows **Session ready**.
7. **Capture.** In the shell, **Start OCR and sync** opens the capture selector,
   and confirming a region starts the session. Browser mode starts with the saved
   region. The backend resolves the OCR engine when the session starts.
8. **Matching and display.** Each capture is read by OCR and matched against the
   source candidates. Matches anchor the playback clock. The presentation track
   and gap filling decide what the plate shows, and the shell draws it.

### Identifiers

`matchId` names one provider-neutral match (a work, or one episode of it).
`resultId` names one subtitle file inside that catalog. Both are opaque: the
studio must not parse them or send provider file IDs. A newer search replaces
the catalog that these IDs refer to.

## Runtime contracts

### Subtitle discovery

Movie matches with valid IMDb IDs use a normalized ID across titles and provider
formats. Missing IDs may use one unambiguous identity for the same title and year;
conflicting IDs stay separate. Unidentified files join by an unambiguous title
alias and year; zero or invalid IDs supply no identity. Progressive catalog
updates preserve selection through stable file IDs. A chosen source determines
its group; without a chosen file, the retained files must agree before selection
follows a regrouping. A target assigned to a different group is cleared.
Catalog identification alone does not replace unchanged prepared files;
choosing another work still blocks starting the previous session.

Episode results carry season and episode numbers. SubDL episode searches use the
series title with season and episode filters. An unpacked SubDL file that reports
season zero takes its pack's season unless its name says `S00`. SubDL's `hi`
parameter filters hearing-impaired tracks, so ordinary searches omit it.

An ASSRT package becomes one result per subtitle member. A member's language
comes from the language tags at the end of its file name, for example `chs&eng`.
A member with two languages appears in both the Source and the Target list. In
a package that has more than one member and more than one language, an
untagged member has an unknown language and appears in both lists. Download
resolves the same member by name. If ASSRT no longer lists that member, the
download fails and asks the viewer to search again; it does not substitute
another member.

Downloads are written under `%USERPROFILE%\.cache\meowcal-sub-2`. An empty
provider answer means that the provider returned nothing for that query. It does
not prove that no subtitle exists.

### Playback timing and presentation

Source subtitles synchronize playback; target subtitles own presentation.
OCR text and semantic matching anchor `PlaybackTimeline` against the selected
source candidate. An anchor unconfirmed for 90 seconds is dropped and its plate
cleared. Recovery from an expired or repeatedly contradicted anchor needs two
different, progressing cues, each supported by strong text or text/semantic
agreement, whose observation times agree on the playback position. A single
high score cannot restore a dropped anchor. Brief ambiguity can retain a strong
cue from the preceding 15 seconds as the first half of that corroboration;
capture loss and stale pauses discard it. A normalized reread of a strongly
matched cue retains its identity without retiming it. Without reliable motion,
this support cannot project past that source cue's end. Motion resumption settles
this bound before the clock advances. Changed reads still match the file when the
gate considers their wording similar. Repairing a first failed read retains its
onset; another file cue inside an already matched gate cue uses its own capture
time. A strong whole-file seek stops the old scene's projection while another
progressing cue confirms the new position.
Three consecutive empty OCR reads end the previous cue's pause hold and allow
the same phrase to match again; while the anchor remains valid, the target track
still owns presentation and silence.
The search window does not authorize a weak clock correction beyond 2 seconds.
Such corrections need different cues observed within 15 seconds whose playback
offsets agree within 2 seconds; repeated reads of one cue cannot confirm a jump.
Whole-file seeks additionally require strong text or text/semantic agreement.
Equal text scores within the search window prefer the occurrence nearest the
position when the current cue was captured. Pause, motion, and audio evidence
are described in [playback evidence](PLAYBACK_EVIDENCE.md).

With a separate target file, `PresentationTrack` retains every target cue's
index, interval, ordering and text. Both immediate matches and the clock renderer
resolve that same track. Its scheduler wakes at target boundaries even when OCR
stalls. Intervals are half-open `[start, end)`; genuine target overlaps remain
simultaneous, and target presentation has no source overlap threshold or stale-line
grace. Each cue's typesetting is flattened independently, except explicit speaker
rows, and the browser supplies natural wrapping.

Each source candidate has its own constant mapping, `target_ms = source_ms +
offset_ms`. The offset is the median midpoint difference from unique, ordered
matching human translations carried by the source and the target file. Model
translations never calibrate it. Calibration requires at least two anchors and
a nearest-rank P90 absolute residual of at most 200 ms around the median. With
insufficient or inconsistent evidence, the files are assumed to use the same
clock (zero offset), and the prepared card marks target timing unverified. This
also applies when multiple automatic source candidates include an uncorroborated
pair. Mismatched releases without corroboration still need independently
established alignment. For the measured S04E08 pair, 384 shared anchors support
-902 ms with 190 ms p90 absolute residual; affine fitting does not improve the
median residual, so no rate parameter is used.

A source cue that has any projected target coverage does not fill the target's
intentional gaps. Wholly uncovered source cues use their carried human translation,
then a local model answer. `gapfill.py` reads target coverage and neighboring human
answers through the presentation track without copying target strings onto source
cues. Idle prefill and playback filling share that lookup; model answers remain
source-aligned and are read when their interval arrives. Without a source anchor,
live OCR translation remains the fallback. Bilingual-only sessions retain their
source-aligned presentation behavior.

### Session modes

| Target choice | Session mode | Needs the translation engine |
| --- | --- | --- |
| A target file | Source file plus target presentation | No. Without it, gaps stay empty and the studio shows a warning. |
| Translation inside the source file | Source rows split into source and target | No. Rows without a carried translation need it to be filled. |
| Local translation | Source file plus model answers | Yes, unless the source carries translations |
| Automatic source candidates (no target file) | Several source candidates; the clock follows the one that locks | When no candidate carries a translation |
| **Use on-screen OCR** source (no matching source file) | OCR fallback, optionally with a target file | Yes. OCR text is translated live. |
| OCR fallback only | Live OCR translation | Yes |

In OCR fallback the target file cannot be scheduled against a source clock.
Live OCR translation can read scene text that a source file would have rejected.

### Subtitle checks and editing

Every playback file is checked when loaded, including automatic candidates and
OCR fallback targets. Empty cues and pure ASS drawing paths retained by conversion
are skipped. Exact same-text/same-interval duplicates are removed, and cues are
stably ordered by start time before matching, bilingual splitting, coverage
measurement or prefill. Other overlaps and repeated dialogue are retained.
Invalid intervals, NUL text and tracks without playable cues stop preparation
with a file-specific error; their timing is not guessed. These changes affect
playback data only. The prepared card reports the per-file results, and original
documents remain available to the optional editor. Time calibration continues to
use the corroborated human anchors described above.

The prepared-session card opens the React subtitle editor. It reads the original
SRT/WebVTT document separately from `load_subtitle_file`, whose plain-text output
is only for matching and presentation. Save checks the prepared session ID and
revisions of all displayed tracks, writes corrected copies, and rebuilds each source
candidate and its target presentation. It rechecks translation engine readiness,
persists the reset playback bias, and resumes idle gap filling on the corrected
track. A failed save removes its new copies and keeps the previous session.
Running or preparing sessions cannot be edited. Editor saves and starts recheck
the session after stopping idle prefill so an old start cannot use a changed track.

### Cancellation and stale results

- **Search.** Each search has an ID. A result that arrives after a newer search
  started returns to its caller but does not change the newer state. Episode and
  season lookups apply only while their own search catalog is current.
- **Source checking and preparation.** A preparation that completes for a
  selection the viewer already left is ignored. A new search clears a session
  that an earlier search prepared.
- **Editing and saving.** Saves check the session ID and track revisions, and
  the session must be idle. A failed save keeps the previous session.
- **Start.** Start resolves OCR, stops idle prefill, then rechecks that the
  prepared session, its runtime, and the start generation are unchanged. If they
  changed, start fails with "Subtitles changed. Start the newly prepared session."
- **Stop.** Stop sets the state to stopping, cancels the sync task, and returns
  to idle with the prepared session kept.
- **Translation.** A cancelled translation discards its answer. Answers for a cue
  that is no longer current are not shown.

### Process ownership

The backend owns separate Core processes for OCR and translation. Core owns its
`llama-server.exe` child. BGE matching has its own Sub 2 process. A Core process
is ready only after its handshake confirms the pinned version and the required
capabilities. A timeout, cancellation, or transport failure ends that owned
process; the next request starts a replacement and confirms readiness again.
Windows job objects end owned processes when the backend exits abnormally. See
[MEOWCAL_CORE.md](MEOWCAL_CORE.md) for deadlines, framing, and capability rules.

When the shell starts the backend, it owns that backend and stops it when the
app closes or installs an update. A backend that the shell reused is not owned
by that shell.

## Storage locations

| Data | Location |
| --- | --- |
| Configuration | `%APPDATA%\meowcal-sub-2\config.toml` |
| Runtime token (deleted when `serve` exits normally) | `%APPDATA%\meowcal-sub-2\runtime.json` |
| TMDb cache | `%APPDATA%\meowcal-sub-2\tmdb_cache.json` |
| Corrected subtitle copies | `%APPDATA%\meowcal-sub-2\subtitles\corrected` |
| Log, rotated daily, seven files kept | `%APPDATA%\meowcal-sub-2\logs\meowcal-sub-2.log` |
| Event log, rotated at 5 MiB, one previous file kept | `%APPDATA%\meowcal-sub-2\logs\meowcal-sub-2.events.jsonl` |
| Downloaded subtitles | `%USERPROFILE%\.cache\meowcal-sub-2` |
| BGE runtime and model | `%LOCALAPPDATA%\com.meowcal.sub2\engine` |
| WebView2 data | `%LOCALAPPDATA%\com.meowcal.sub2\EBWebView` |
| Core runtime and models | `%LOCALAPPDATA%\Meowcal\Core\sub2\<profile>\<version>\<architecture>` |
| Core executable | `core\meowcal-core.exe` in the app folder, or `src-tauri\resources\core\meowcal-core.exe` in a checkout; the shell passes it as `MEOWCAL_CORE_EXE` |

[config.example.toml](../config.example.toml) shows the configuration format.

## Pinned Meowcal Core

[config/meowcal-core.lock.json](../config/meowcal-core.lock.json) pins a released
Core version, API major, and SHA-256 hashes for x64 and ARM64 packages.
`scripts/fetch-meowcal-core.ps1` selects and verifies the architecture's archive
and package contract, then prepares `src-tauri/resources/core/`. Tauri invokes
it before development and production builds. The shell passes the bundled
executable path to the backend as `MEOWCAL_CORE_EXE`.

Core owns Windows OCR, PP-OCRv6 and HY-MT installation, artifact verification,
and inference. Translation prompt shape and output validation remain
product-owned. See [MEOWCAL_CORE.md](MEOWCAL_CORE.md) for OCR engine selection,
storage, and compatibility rules.

For a local build using a previously downloaded, locked archive:

```powershell
.\scripts\fetch-meowcal-core.ps1 -ArchivePath $coreArchive -Offline
```

The offline flag does not bypass lock or digest checks. Candidate verification
and Core upgrades are documented in
[CORE_UPGRADE_AUTOMATION.md](CORE_UPGRADE_AUTOMATION.md); a local candidate lock
must not replace the reviewed release pin.

## Authentication and diagnostics

The backend binds to `127.0.0.1`. The studio and privileged HTTP/WebSocket
routes require a per-run token, sent through `X-Meowcal-Token` or the `token`
query parameter. The backend publishes it to `runtime.json`; the shell reads
that file. Foreign request origins are rejected even when a token is supplied.
Profile access by software running as the same Windows user remains outside
this boundary.

Normal file and console logging use INFO. Launch
`python -m meocosub2.cli --verbose serve` to enable DEBUG OCR/subtitle traces,
which include recognized text and subtitle snippets. The installed app has no
verbose switch. The event log redacts credential-like fields and URL query
values and truncates long strings, but it records titles, queries, file names,
and error text. Normal logs can also contain titles, errors, and sensitive
details. Use synthetic content for debugging and sanitize excerpts before
sharing.

## Verification

```powershell
.\scripts\verify.ps1
```

This is the authoritative review gate and the command Windows CI runs. It
covers formatting, lint, types, Python/Rust/studio suites, the served dashboard,
real pinned-Core handshake and PP-OCRv6 checks, and maintainability ratchets.
`-List` prints stages; `-Stage <name>` runs a subset during development.

The served-dashboard smoke refuses to reuse a backend already occupying its
port.

### What each layer proves

| Layer | Proves | Does not prove |
| --- | --- | --- |
| Unit tests and policy replay | Logic and state transitions on recorded or synthetic inputs | Real OCR, real providers, timing on a device, native windows |
| Real provider APIs and downloads | Current provider responses, language parsing, member resolution, quota reporting for that query | Results for other titles or later dates; they spend allowances |
| Real Core and models | Handshake, capability checks, recognition or inference on known inputs | Capture, playback timing, the plate |
| Browser studio | The served page, its API calls, keyboard and layout in Chromium | WebView2 rendering, the selector, the plate, the dock |
| Native Tauri/WebView2 run | Capture, selector, plate, dock, and process shutdown on that device | Other architectures, monitors, players, or whole films |
| Packaging, installation, upgrade, rollback | Payload, signatures, install/upgrade/uninstall paths, data retention | Production update discovery unless the real feed was used |

Evidence from one architecture does not prove the other.

### Recording performance and playback evidence

A measurement in documentation must name the commit or source hashes, build
mode, device and architecture, sample and its size, warmup, the timing
boundaries, other workloads running at the same time, how CPU and resources were
counted, and the limits of the result. Report each metric separately: OCR text
accuracy, subtitle match rate, unique-cue coverage, adjacent timing errors,
distant mismatches, display latency, and resource use. Do not merge them into
one success rate. Do not extend a short clip, repeated observations, or a
synthetic sample to a claim about a whole film. Do not publish film material,
subtitle dialogue, private screenshots, annotations, or raw session logs.
