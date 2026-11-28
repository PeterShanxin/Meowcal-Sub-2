# Changelog

## 0.4.1

- Check for updates at startup at most once per day, or manually in Settings.
- GitHub installations keep signed in-app updates. Portable copies open the GitHub release page for a matching ZIP without running an installer.
- Microsoft Store builds check for Store updates and open the Store to install them.

See the [release notes](docs/releases/v0.4.1.md).

## 0.4.0

- Start live screen translation when no subtitle provider is configured or no title matches.
- Follow a target subtitle file after several translated captions identify the scene.
- Start watching with only a source file while the local model translates the rest.
  The completed target track takes over at the current position.
- Keep the latest subtitle selection when preparations finish out of order, and
  restore the current caption when the floating strip reconnects.

See the [release notes](docs/releases/v0.4.0.md) for downloads and upgrade guidance.

## 0.3.0 — 2026-11-16

- Add a Simplified Chinese interface and the subtitle-card icon.
- Add PP-OCRv6 recognition with Meowcal Core v0.2.2.
- Improve subtitle selection, movie matching and playback continuity.
- Keep session warnings visible in the live dock.

See the [release notes](docs/releases/v0.3.0.md) for downloads and upgrade guidance.

## 0.2.1 — 2026-10-04

- Hold subtitles and playback timing during sustained pauses, including silent
  target gaps; resume from observed playback motion or sound.
- Enable signed automatic updates for installed copies. Versions 0.1.0 and 0.2.0
  require a manual first upgrade; portable copies remain manual.

Static, silent playback with an unchanged picture can resemble a pause. This
release uses observed playback activity and cannot distinguish those cases.

## 0.1.0 — 2026-09-15

First public release of Meowcal Sub 2 for Windows x64 and ARM64.

- Search subtitle sources and prepare source/target tracks in a desktop studio.
- Follow on-screen dialogue with Windows OCR and subtitle matching.
- Present target subtitles on a floating plate, with playback timing controls.
- Translate on device with Meowcal Core and HY-MT; fill gaps where subtitles are missing.
- Install with a per-user Windows installer or extract the portable package. Python and Core are included; translation models download separately.
- Introduce the dark, gold cat-and-subtitle identity and AGPL-3.0-only licensing.

This first release has no automatic updater or Windows code-signing certificate.
OCR quality depends on the capture area, installed language packs, and visible
text. Protected video can block capture. Subtitle providers need credentials and
network access; translation model downloads have separate upstream licenses.
