"""App-specific errors."""


class MeoCoSubError(Exception):
    """Base exception for the app."""


class SubtitleSourceError(MeoCoSubError):
    """Provider-neutral subtitle source error."""


class OpenSubtitlesError(SubtitleSourceError):
    """OpenSubtitles API error."""


class TranslationError(MeoCoSubError):
    """Translation failure."""


class CaptureError(MeoCoSubError):
    """Screen capture or OCR failure."""
