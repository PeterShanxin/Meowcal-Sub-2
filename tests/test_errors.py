from meocosub2.errors import CaptureError, MeoCoSubError, OpenSubtitlesError, TranslationError


def test_base_error_inheritance() -> None:
    assert issubclass(OpenSubtitlesError, MeoCoSubError)
    assert issubclass(TranslationError, MeoCoSubError)
    assert issubclass(CaptureError, MeoCoSubError)


def test_error_string_round_trip() -> None:
    error = MeoCoSubError("failure")
    assert str(error) == "failure"
