# Changelog

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
