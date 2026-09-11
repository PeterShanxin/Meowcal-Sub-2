import asyncio
import base64
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image

from meocosub2 import capture, native_ocr


@pytest.fixture
def core(mocker):
    client = Mock()
    client.request = AsyncMock(return_value={"text": " hello "})
    client.request_sync.return_value = {"languages": ["en-US", "zh-Hans-CN"]}
    mocker.patch.object(native_ocr, "_client", client)
    return client


@pytest.mark.asyncio
async def test_native_adapter_preserves_pixel_order_and_pass_timeout(core):
    image = Image.new("RGB", (2, 1))
    image.putdata([(10, 20, 30), (40, 50, 60)])

    assert await capture._run_ocr(image, "en-US") == "hello"
    method, params = core.request.call_args.args
    assert method == "ocrRecognize"
    assert params["language"] == "en-US"
    assert (params["width"], params["height"], params["stride"]) == (2, 1, 8)
    assert base64.b64decode(params["bgraBase64"]) == bytes([30, 20, 10, 255, 60, 50, 40, 255])
    assert params["timeoutMs"] == 1000
    assert core.request.call_args.kwargs["timeout_s"] == 1.0


@pytest.mark.asyncio
async def test_native_adapter_passes_preprocessed_grayscale_without_resizing(core):
    image = Image.new("L", (2, 1))
    image.putdata([0, 255])
    await capture._run_ocr(image, "zh-Hans-CN")
    params = core.request.call_args.args[1]
    assert base64.b64decode(params["bgraBase64"]) == bytes([0, 0, 0, 255, 255, 255, 255, 255])
    assert params["language"] == "zh-Hans-CN"


def test_native_languages_use_shared_core(core):
    assert capture.available_ocr_languages() == ["en-US", "zh-Hans-CN"]
    core.request_sync.assert_called_once_with("ocrLanguages", {}, timeout_s=5.0)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [{}, {"text": 5}, {"text": ["hello"]}])
async def test_malformed_native_result_is_rejected(core, response):
    core.request.return_value = response
    with pytest.raises(RuntimeError, match="invalid OCR text"):
        await capture._run_ocr(Image.new("RGB", (1, 1)), "en-US")


@pytest.mark.asyncio
async def test_oversized_frame_is_rejected_before_transport(core):
    with pytest.raises(ValueError, match="dimensions"):
        await capture._run_ocr(Image.new("RGB", (4097, 1)), "en-US")
    core.request.assert_not_called()


@pytest.mark.asyncio
async def test_core_timeout_preserves_prior_read_without_starting_another_pass(core, mocker):
    mocker.patch.object(
        capture, "resolve_ocr_language", return_value=capture.OcrResolution("en-US", "en-US")
    )
    core.request.side_effect = [{"text": "please sit down"}, TimeoutError("OCR_TIMEOUT")]

    assert await capture.ocr_image(Image.new("RGB", (4, 2)), "en") == "please sit down"
    assert core.request.await_count == 2


@pytest.mark.asyncio
async def test_session_cancellation_reaches_owned_core_request(core):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def pending(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    core.request.side_effect = pending
    task = asyncio.create_task(capture._run_ocr(Image.new("RGB", (4, 2)), "en-US"))
    await asyncio.wait_for(started.wait(), 1.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
