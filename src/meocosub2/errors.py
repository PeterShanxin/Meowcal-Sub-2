"""App-specific errors."""


class MeoCoSubError(Exception):
    """Base exception for the app."""


class OpenSubtitlesError(MeoCoSubError):
    """OpenSubtitles API error."""


class TranslationError(MeoCoSubError):
    """Translation failure."""


class CaptureError(MeoCoSubError):
    """Screen capture or OCR failure."""
