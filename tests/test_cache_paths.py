import io
import zipfile
from pathlib import Path

import pytest

from meocosub2.errors import SubtitleSourceError
from meocosub2.subtitle_sources.cache_paths import (
    contained_path,
    safe_segment,
    subtitle_file_name,
)
from meocosub2.subtitle_sources.utils import extract_zip_bytes

TRAVERSALS = [
    "../escape.srt",
    "..\\..\\escape.srt",
    "/etc/passwd",
    "C:\\Windows\\System32\\evil.srt",
    "a/b/../../../../escape.srt",
    "....//escape.srt",
]


@pytest.mark.parametrize("name", TRAVERSALS)
def test_traversal_names_are_reduced_to_a_single_segment(name: str) -> None:
    segment = safe_segment(name, "fallback")
    assert "/" not in segment
    assert "\\" not in segment
    assert segment not in {"..", "."}


@pytest.mark.parametrize("name", ["..", "...", "", "   ", "con", "NUL.srt", "lpt1"])
def test_names_windows_cannot_use_fall_back_to_our_own(name: str) -> None:
    assert safe_segment(name, "fallback") == "fallback"


def test_normal_provider_names_survive_untouched() -> None:
    assert safe_segment("Inception.2010.1080p.srt", "fb") == "Inception.2010.1080p.srt"
    assert safe_segment("盗梦空间.chs.ass", "fb") == "盗梦空间.chs.ass"


def test_a_name_without_a_subtitle_extension_gets_one() -> None:
    assert subtitle_file_name("Inception - 2010", "fb") == "Inception - 2010.srt"
    assert subtitle_file_name("subs.zip", "fb") == "subs.srt"
    assert subtitle_file_name("subs.ass", "fb") == "subs.ass"


def test_contained_path_accepts_a_safe_name(tmp_path: Path) -> None:
    assert contained_path(tmp_path, "ok.srt") == (tmp_path / "ok.srt").resolve()


@pytest.mark.parametrize("segments", [("..", "escape.srt"), ("..", ".."), ("sub", "..", "..")])
def test_contained_path_refuses_to_leave_the_cache_directory(
    tmp_path: Path, segments: tuple[str, ...]
) -> None:
    with pytest.raises(SubtitleSourceError):
        contained_path(tmp_path, *segments)


def _zip_with(names: list[str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, "1\n00:00:01,000 --> 00:00:02,000\nhi\n")
    return buffer.getvalue()


def test_a_malicious_archive_cannot_write_outside_the_cache(tmp_path: Path) -> None:
    destination = tmp_path / "cache" / "result"
    outside = tmp_path / "escape.srt"
    extract_zip_bytes(_zip_with(["../../escape.srt"]), destination)
    assert not outside.exists()
    assert list(destination.glob("*.srt")) == [destination / "escape.srt"]


def test_a_normal_archive_still_extracts(tmp_path: Path) -> None:
    destination = tmp_path / "cache" / "result"
    path = extract_zip_bytes(_zip_with(["Inception.2010.srt"]), destination)
    assert path == destination / "Inception.2010.srt"
    assert path.read_text(encoding="utf-8").startswith("1")
