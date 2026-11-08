import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image, ImageDraw, ImageFont
from rapidfuzz import fuzz

from meocosub2 import capture, native_ocr
from meocosub2.core_protocol import CoreProtocolError, validate_payload


def frame(**options):
    return {"width": 1, "height": 1, "stride": 4, "timeoutMs": 1000, **options}


def test_ppocr_binary_request_omits_language():
    validate_payload("ocrRecognizeBgra", frame(engine="ppOcrV6", maxThreads=2), b"1234")


@pytest.mark.parametrize(
    "options",
    [
        {"engine": "ppOcrV6", "language": "zh-CN"},
        {"engine": "ppOcrV6", "language": None},
        {"engine": "ppOcrV6", "maxThreads": 0},
        {"engine": "ppOcrV6", "maxThreads": 5},
        {"engine": "ppOcrV6", "maxThreads": True},
        {"engine": "windows", "language": "ko-KR", "maxThreads": 2},
        {"engine": "unknown", "language": "en-US"},
    ],
)
def test_invalid_engine_options_are_rejected_before_writing(options):
    with pytest.raises(CoreProtocolError):
        validate_payload("ocrRecognizeBgra", frame(**options), b"1234")


@pytest.fixture
def pp_core(mocker):
    client = Mock()
    client.hello_result = {"capabilities": ["ocrPpOcrV6"]}
    client.process_generation = 1
    client.request_sync.return_value = {"engine": "ppOcrV6", "resolvedLanguage": None}

    async def response(method, *_args, **_kwargs):
        if method == "ocrInitialize":
            return {"engine": "ppOcrV6", "resolvedLanguage": None}
        return {"text": "A subtitle", "lines": [], "boxes": []}

    client.request = AsyncMock(side_effect=response)
    mocker.patch.object(native_ocr, "_client", client)
    mocker.patch.object(native_ocr, "_initialized", None, create=True)
    return client


@pytest.mark.asyncio
async def test_ppocr_initialization_precedes_frames_and_repeats_after_process_loss(pp_core):
    await native_ocr.initialize_ppocr()
    await native_ocr.initialize_ppocr()
    assert pp_core.request.await_count == 1
    pp_core.request.assert_called_with(
        "ocrInitialize", {"engine": "ppOcrV6", "maxThreads": 2}, timeout_s=10.0
    )
    assert (
        await native_ocr.recognize(Image.new("RGB", (1, 1)), None, 1.0, engine="ppOcrV6")
        == "A subtitle"
    )
    params = pp_core.request.call_args.args[1]
    assert params["engine"] == "ppOcrV6" and params["maxThreads"] == 2
    assert "language" not in params
    pp_core.process_generation = 2
    await native_ocr.initialize_ppocr()
    assert sum(call.args[0] == "ocrInitialize" for call in pp_core.request.call_args_list) == 2


@pytest.mark.parametrize("engine", ["auto", "ppOcrV6"])
def test_ppocr_reads_traditional_chinese_without_windows_pack(mocker, engine):
    mocker.patch.object(native_ocr, "supports_ppocr", return_value=True, create=True)
    languages = mocker.patch.object(capture, "available_ocr_languages", return_value=[])
    resolution = capture.resolve_ocr_language("zh-TW", engine)
    assert resolution.engine == "ppOcrV6"
    assert resolution.warning_message == ""
    languages.assert_not_called()


def test_missing_capability_retains_windows_and_reports_fallback(mocker):
    mocker.patch.object(native_ocr, "supports_ppocr", return_value=False, create=True)
    mocker.patch.object(capture, "available_ocr_languages", return_value=["en-US"])
    resolution = capture.resolve_ocr_language("en-US", "ppOcrV6")
    assert resolution.engine == "windows"
    assert "unavailable" in resolution.warning_message


@pytest.mark.parametrize("engine", ["auto", "ppOcrV6", "windows"])
def test_korean_always_uses_windows_ocr(mocker, engine):
    pp = mocker.patch.object(native_ocr, "supports_ppocr", return_value=True, create=True)
    mocker.patch.object(capture, "available_ocr_languages", return_value=["ko-KR"])
    resolution = capture.resolve_ocr_language("ko-KR", engine)
    assert resolution.engine == "windows" and resolution.resolved_language == "ko-KR"
    pp.assert_not_called()


@pytest.mark.parametrize("engine", ["auto", "ppOcrV6", "windows"])
def test_missing_korean_pack_stops_with_an_install_action(mocker, engine):
    mocker.patch.object(capture, "available_ocr_languages", return_value=["en-US"])
    resolution = capture.resolve_ocr_language("ko", engine)
    assert resolution.engine == "windows" and not resolution.available
    assert "Install its Windows OCR language pack" in resolution.warning_message


def test_windows_traditional_fallback_accepts_canonical_simplified_tag(mocker):
    mocker.patch.object(capture, "available_ocr_languages", return_value=["zh-CN"])
    resolution = capture.resolve_ocr_language("zh-TW")
    assert resolution.resolved_language == "zh-CN"
    assert "Falling back" in resolution.warning_message


@pytest.mark.asyncio
async def test_automatic_ocr_only_prefers_windows_but_source_matching_uses_ppocr(mocker):
    mocker.patch.object(native_ocr, "supports_ppocr", return_value=True)
    initialize = mocker.patch.object(native_ocr, "initialize_ppocr", new_callable=AsyncMock)
    mocker.patch.object(capture, "available_ocr_languages", return_value=["en-US"])
    assert (await capture.prepare_ocr("en", "auto", prefer_windows=True)).engine == "windows"
    initialize.assert_not_awaited()
    assert (await capture.prepare_ocr("en", "auto")).engine == "ppOcrV6"
    initialize.assert_awaited_once()


@pytest.mark.asyncio
async def test_ocr_only_can_use_ppocr_without_a_windows_language_pack(mocker):
    mocker.patch.object(native_ocr, "supports_ppocr", return_value=True)
    mocker.patch.object(native_ocr, "initialize_ppocr", new_callable=AsyncMock)
    mocker.patch.object(capture, "available_ocr_languages", return_value=[])
    resolution = await capture.prepare_ocr("ja", "auto", prefer_windows=True)
    assert resolution.engine == "ppOcrV6" and resolution.available


@pytest.mark.asyncio
@pytest.mark.parametrize("installed", [[], ["en-US"]])
async def test_initialization_failure_has_an_explicit_windows_fallback(mocker, installed):
    mocker.patch.object(native_ocr, "supports_ppocr", return_value=True)
    mocker.patch.object(
        native_ocr, "initialize_ppocr", new=AsyncMock(side_effect=RuntimeError("model unavailable"))
    )
    mocker.patch.object(capture, "available_ocr_languages", return_value=installed)
    resolution = await capture.prepare_ocr("en", "ppOcrV6")
    assert resolution.engine == "windows"
    assert resolution.available == bool(installed)
    assert "could not start" in resolution.warning_message


@pytest.mark.asyncio
async def test_ppocr_uses_one_original_frame_and_preserves_the_second_speaker(mocker):
    mocker.patch.object(native_ocr, "supports_ppocr", return_value=True)
    mocker.patch.object(native_ocr, "initialize_ppocr", new_callable=AsyncMock)
    mocker.patch.object(capture, "preprocess_for_ocr", side_effect=AssertionError("extra pass"))
    mocker.patch.object(
        capture, "preprocess_white_text_for_ocr", side_effect=AssertionError("mask")
    )
    read = mocker.patch.object(
        native_ocr,
        "recognize_ppocr_lines",
        new=AsyncMock(
            return_value=[
                native_ocr.OcrLine("First subtitle", 0, 0, 200, 30),
                native_ocr.OcrLine("Second speaker", 0, 35, 160, 18),
                native_ocr.OcrLine("Small scenery text", 220, 0, 40, 17.9),
            ]
        ),
    )
    image = Image.new("RGB", (400, 100))
    assert await capture.ocr_image(image, "en", engine="ppOcrV6") == "First subtitle Second speaker"
    read.assert_awaited_once_with(image, 1.0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"lines": ["text"], "boxes": []},
        {"lines": ["text"], "boxes": [{"x": 0, "y": 0, "width": 5, "height": 0}]},
        {"lines": ["text"], "boxes": [{"x": 0, "y": 0, "width": 5, "height": float("nan")}]},
    ],
)
async def test_invalid_line_geometry_is_rejected(pp_core, response):
    pp_core.request.side_effect = None
    pp_core.request.return_value = response
    with pytest.raises(RuntimeError, match="invalid OCR"):
        await native_ocr.recognize_ppocr_lines(Image.new("RGB", (10, 10)), 1)


@pytest.mark.asyncio
async def test_cancellation_reaches_ppocr_initialization(pp_core, mocker):
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def loading(*_args, **_kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    pp_core.request.side_effect = loading
    mocker.patch.object(native_ocr, "supports_ppocr", return_value=True)
    task = asyncio.create_task(capture.prepare_ocr("zh", "ppOcrV6"))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()


@pytest.mark.skipif(
    not Path(os.environ.get("MEOWCAL_CORE_EXE", "missing")).is_file(),
    reason="a real pinned Core executable was not supplied",
)
@pytest.mark.asyncio
async def test_real_pinned_ppocr_reads_a_caption_and_rejects_a_blank_frame(tmp_path, monkeypatch):
    monkeypatch.setenv("MEOWCAL_CORE_PROFILE", "development")
    monkeypatch.setenv("MEOWCAL_CORE_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(native_ocr, "_client", None)
    monkeypatch.setattr(native_ocr, "_initialized", None)
    image = Image.new("RGB", (1000, 140), "black")
    font = ImageFont.truetype(str(Path(os.environ["WINDIR"]) / "Fonts/arial.ttf"), 44)
    expected = "Read the subtitles on the screen."
    ImageDraw.Draw(image).text((30, 35), expected, font=font, fill="white")
    try:
        resolution = await capture.prepare_ocr("en-US", "ppOcrV6")
        assert resolution.engine == "ppOcrV6" and resolution.available
        output = await capture.ocr_image(image, "en-US", engine="ppOcrV6")
        assert fuzz.ratio(output.casefold().strip("."), expected.casefold().strip(".")) >= 95
        assert (
            await capture.ocr_image(Image.new("RGB", image.size), "en-US", engine="ppOcrV6") == ""
        )
    finally:
        native_ocr.shutdown()
