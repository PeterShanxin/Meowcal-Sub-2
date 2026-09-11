import asyncio
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from meocosub2.capture import (
    capture_region,
    capture_region_jpeg,
    ocr_image,
    preprocess_for_ocr,
    preprocess_white_text_for_ocr,
)


@pytest.fixture(autouse=True)
def installed_ocr_languages(mocker):
    mocker.patch("meocosub2.capture.available_ocr_languages", return_value=["en-US", "zh-CN"])


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
    text = asyncio.run(capture_module.ocr_image(Image.new("RGB", (1, 1)), "zh-CN"))
    assert text == "很自然我们甚至不会察觉"


def test_white_text_mask_separates_subtitles_from_bright_colored_scenery() -> None:
    image = Image.new("RGB", (5, 1))
    image.putdata([(255, 255, 255), (200, 200, 200), (199, 255, 255), (255, 255, 0), (0, 0, 0)])

    assert list(preprocess_white_text_for_ocr(image).getdata()) == [255, 255, 0, 0, 0]


@pytest.mark.asyncio
async def test_white_text_pass_recovers_row_missing_from_whole_scene_passes(mocker) -> None:
    # Boundary results reproduce Windows OCR dropping a row against a busy scene.
    mocker.patch(
        "meocosub2.capture._run_ocr",
        new=mocker.AsyncMock(side_effect=["请 坐 下", "请 坐 下", "大 家 好 请 坐 下"]),
    )

    assert await ocr_image(Image.new("RGB", (4, 2)), "zh-CN") == "大家好请坐下"


@pytest.mark.asyncio
async def test_white_text_pass_does_not_discard_complete_colored_subtitles(mocker) -> None:
    mocker.patch(
        "meocosub2.capture._run_ocr",
        new=mocker.AsyncMock(side_effect=["大 家 好 请 坐", "请 坐", "请勿靠近展览入口服务中心"]),
    )

    assert await ocr_image(Image.new("RGB", (4, 2), "yellow"), "zh-CN") == "大家好请坐"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "original, white_text",
    [
        ("大家请坐下", "大家好欢迎参观展览入口"),
        ("请把门关好", "大家请将窗关好再坐下"),
        ("大家请坐下", "下坐请家大入口服务中心"),
        ("", "欢迎参观展览入口"),
        ("坐", "大家请坐下"),
        ("请坐", "大家请坐下"),
    ],
)
async def test_white_text_needs_corroboration_from_whole_scene(
    mocker, original, white_text
) -> None:
    mocker.patch(
        "meocosub2.capture._run_ocr",
        new=mocker.AsyncMock(side_effect=[original, original, white_text]),
    )

    assert await ocr_image(Image.new("RGB", (4, 2)), "zh-CN") == original


@pytest.mark.asyncio
async def test_white_text_extension_allows_one_recognition_error_in_five_letters(mocker) -> None:
    mocker.patch(
        "meocosub2.capture._run_ocr",
        new=mocker.AsyncMock(side_effect=["请把门关好", "", "大家请把窗关好再坐下"]),
    )

    assert await ocr_image(Image.new("RGB", (4, 2)), "zh-CN") == "大家请把窗关好再坐下"


@pytest.mark.asyncio
@pytest.mark.parametrize("successful_passes", [0, 1, 2])
async def test_ocr_timeout_returns_prior_read_or_blank(mocker, successful_passes) -> None:
    completed = 0

    async def recognize(image, language):
        nonlocal completed
        if completed < successful_passes:
            completed += 1
            return "大家好请坐"
        await asyncio.Event().wait()

    mocker.patch("meocosub2.capture._OCR_PASS_TIMEOUT_SECONDS", 0.01, create=True)
    run_ocr = mocker.patch("meocosub2.capture._run_ocr", side_effect=recognize)

    result = await asyncio.wait_for(ocr_image(Image.new("RGB", (4, 2)), "zh-CN"), timeout=0.2)
    assert result == ("大家好请坐" if successful_passes else "")
    assert run_ocr.await_count == successful_passes + 1


def test_capture_region_jpeg_encodes_what_was_grabbed(mocker) -> None:
    mocker.patch(
        "meocosub2.capture.capture_region", return_value=Image.new("RGB", (4, 3), (10, 20, 30))
    )
    encoded = capture_region_jpeg((0, 0, 4, 3))
    assert Image.open(io.BytesIO(encoded)).format == "JPEG"
