import asyncio
import io
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

from meocosub2.capture import (
    _run_ocr,
    capture_region,
    capture_region_jpeg,
    ocr_image,
    preprocess_for_ocr,
)


def test_capture_region_returns_pil_image(mocker) -> None:
    screenshot = SimpleNamespace(size=(2, 1), bgra=b"\x00\x00\x00\xff\xff\xff\xff\xff")
    sct = mocker.MagicMock()
    sct.grab.return_value = screenshot
    manager = mocker.MagicMock()
    manager.__enter__.return_value = sct
    mocker.patch("meocosub2.capture.mss.mss", return_value=manager)
    image = capture_region((0, 0, 2, 1))
    assert isinstance(image, Image.Image)
    assert image.size == (2, 1)
    assert manager.__enter__.called
    assert manager.__exit__.called


def test_preprocess_for_ocr_pipeline_order(mocker) -> None:
    image = mocker.Mock()
    grayscale = mocker.Mock()
    equalized = mocker.Mock()
    image.convert.return_value = grayscale
    mocker.patch("meocosub2.capture.ImageOps.equalize", return_value=equalized)
    equalized.point.return_value = "binary"
    assert preprocess_for_ocr(image) == "binary"
    image.convert.assert_called_once_with("L")
    equalized.point.assert_called_once()


def test_preprocess_for_ocr_binarizes_at_128() -> None:
    image = Image.new("L", (2, 1))
    image.putdata([127, 128])
    result = preprocess_for_ocr(image.convert("RGB"))
    assert list(result.getdata()) == [0, 255]


@pytest.mark.asyncio
async def test_ocr_image_calls_preprocess_before_run_ocr(mocker) -> None:
    prepared = object()
    preprocess = mocker.patch("meocosub2.capture.preprocess_for_ocr", return_value=prepared)
    run_ocr = mocker.patch("meocosub2.capture._run_ocr", new=mocker.AsyncMock(return_value="hello"))
    mocker.patch(
        "meocosub2.capture.resolve_ocr_language",
        return_value=SimpleNamespace(resolved_language="en-US"),
    )
    image = Image.new("RGB", (1, 1))
    result = await ocr_image(image, "en")
    assert result == "hello"
    preprocess.assert_called_once_with(image)
    assert run_ocr.await_args_list[0].args == (prepared, "en-US")


@pytest.mark.asyncio
async def test_ocr_image_returns_empty_string_on_exception(mocker) -> None:
    mocker.patch(
        "meocosub2.capture._run_ocr", new=mocker.AsyncMock(side_effect=RuntimeError("boom"))
    )
    result = await ocr_image(Image.new("RGB", (1, 1)), "en")
    assert result == ""


@pytest.mark.asyncio
async def test_run_ocr_uses_running_loop(mocker) -> None:
    class FakeLoop:
        def __init__(self) -> None:
            self.called = False

        def run_in_executor(self, executor, func):
            self.called = True
            future = asyncio.Future()
            future.set_result(func())
            return future

    fake_loop = FakeLoop()
    running_loop = mocker.patch(
        "meocosub2.capture.asyncio.get_running_loop", return_value=fake_loop
    )
    sys.modules["winocr"] = SimpleNamespace(
        recognize_pil=lambda image, language: SimpleNamespace(text="hello")
    )
    try:
        result = await _run_ocr(Image.new("RGB", (1, 1)), "en")
    finally:
        sys.modules.pop("winocr", None)
    assert result == "hello"
    running_loop.assert_called_once()
    assert fake_loop.called


def test_ocr_output_is_cleaned_before_it_leaves_capture(monkeypatch) -> None:
    import asyncio

    from meocosub2 import capture as capture_module

    monkeypatch.setattr(
        capture_module,
        "resolve_ocr_language",
        lambda language: capture_module.OcrResolution("zh-CN", "zh-Hans-CN"),
    )

    async def fake_ocr(image, language):
        return "0 = 很 自 然 我 们 甚 至 不 会 察 觉"

    monkeypatch.setattr(capture_module, "_run_ocr", fake_ocr)
    monkeypatch.setattr(capture_module, "preprocess_for_ocr", lambda image: image)
    text = asyncio.run(capture_module.ocr_image(object(), "zh-CN"))
    assert text == "很自然我们甚至不会察觉"


def test_capture_region_jpeg_encodes_what_was_grabbed(mocker) -> None:
    mocker.patch(
        "meocosub2.capture.capture_region", return_value=Image.new("RGB", (4, 3), (10, 20, 30))
    )
    encoded = capture_region_jpeg((0, 0, 4, 3))
    assert Image.open(io.BytesIO(encoded)).format == "JPEG"
