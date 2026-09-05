# Meowcal-Sub-2

`meowcal-sub-2` is a Windows-first subtitle studio with a Python backend, a local web dashboard, and a Tauri desktop shell. It searches multiple subtitle sources, prepares subtitle-matched or OCR-only sessions, translates on the machine through a managed local engine, and syncs overlay text to live playback with Windows OCR plus fuzzy matching.

Docs:

- [docs/user-guide.md](docs/user-guide.md)
- [docs/developer-guide.md](docs/developer-guide.md)

## Requirements

- Python 3.11+
- Windows for OCR support via `winocr`
- Optional desktop shell: WebView2/Tauri runtime on Windows
- Optional subtitle sources:
  - OpenSubtitles API key
  - SubDL API key
  - ASSRT token

Translation runs on this machine. The app installs and manages its own engine
(Tencent HY-MT1.5 on `llama-server`, about 1.1 GB) the first time you ask for it
from Settings; an existing Meowcal Sub v1 engine install is reused as-is.

## Install

```powershell
pip install -e ".[dev]"
npm --prefix src\meocosub2\overlay\ui install
python -m playwright install chromium
rustup component add rustfmt clippy
```

That is everything `scripts\verify.ps1` needs. The `dev` extra installs the
Playwright Python package; `python -m playwright install chromium` downloads the
browser it drives, once per machine. `rustfmt` and `clippy` are only needed to
work on the Tauri shell.

## Verify

```powershell
.\scripts\verify.ps1
```

One command for every gate this repository enforces, and the same one CI runs.
See [docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md) for what it does and does not
prove.

## Runtime Modes

- Desktop launch: `run_app.vbs`
- Studio backend: `python -m meocosub2.cli serve`

`run_app.vbs` is the supported Windows launcher: it builds the studio UI and the
Tauri shell when they are out of date, then starts the shell, which starts the
backend and navigates to the served studio.

The studio HTTP and WebSocket surface requires a per-run token. `serve` prints the
URL carrying it and writes the token to `%APPDATA%/meowcal-sub-2/runtime.json` for
the desktop shell to read. Unauthenticated requests are refused, so another local
process cannot read session state or drive the app.

## Config

Default config path on Windows:

- `%APPDATA%/meowcal-sub-2/config.toml`

Use [config.example.toml](config.example.toml) as the source of truth for the current schema.

Main sections:

- `[subtitle_sources.opensubtitles]`: enable/credentials/legacy alias fallback
- `[subtitle_sources.subdl]`: enable flag and API key
- `[subtitle_sources.assrt]`: enable flag and token
- `[languages]`: source and target language codes
- `[capture]`: region, interval, OCR language
- `[matching]`: fuzzy threshold and search window
- `[translation]`: how long one line may take before it is dropped
- `[overlay]`: style and layout settings for the subtitle overlay
- `[debug]`: dashboard debug panel toggle

Legacy `[opensubtitles]` config still loads for backward compatibility, but new edits should use `subtitle_sources.opensubtitles`.

## Commands

```bash
meowcal-sub-2 serve
```

`serve` runs the studio backend that the desktop shell talks to. Everything else
is done from the app.

## Verification

```bash
pytest -q
```

```bash
npm --prefix src\meocosub2\overlay\ui run build
```

```bash
cargo check --manifest-path src-tauri\Cargo.toml
```

```bash
python scripts\run_dashboard_smoke.py
```

Before the smoke check, install the browser once with `python -m playwright install chromium`.

The Playwright smoke script validates the served dashboard path only. It also refuses to reuse an already-running dashboard by default, so you do not accidentally smoke-test stale code. It does not prove native WebView2 rendering correctness inside the Tauri shell.
