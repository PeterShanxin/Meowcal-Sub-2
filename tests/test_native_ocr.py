import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image

from meocosub2 import capture, native_ocr


@pytest.fixture
def core(mocker):
    mocker.patch.object(native_ocr, "_languages", None)
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
    assert method == "ocrRecognizeBgra"
    assert params["language"] == "en-US"
    assert (params["width"], params["height"], params["stride"]) == (2, 1, 8)
    assert core.request.call_args.kwargs["payload"] == bytes([30, 20, 10, 255, 60, 50, 40, 255])
    assert params["timeoutMs"] == 1000
    assert core.request.call_args.kwargs["timeout_s"] == 1.0


@pytest.mark.asyncio
async def test_native_adapter_passes_preprocessed_grayscale_without_resizing(core):
    image = Image.new("L", (2, 1))
    image.putdata([0, 255])
    await capture._run_ocr(image, "zh-Hans-CN")
    params = core.request.call_args.args[1]
    assert core.request.call_args.kwargs["payload"] == bytes([0, 0, 0, 255, 255, 255, 255, 255])
    assert params["language"] == "zh-Hans-CN"


def test_native_languages_use_shared_core(core):
    assert capture.available_ocr_languages() == ["en-US", "zh-Hans-CN"]
    core.request_sync.assert_called_once_with("ocrLanguages", {}, timeout_s=5.0)


def test_language_discovery_is_cached_and_explicit_refresh_replaces_it(core):
    assert capture.resolve_ocr_language("en-US").resolved_language == "en-US"
    assert capture.resolve_ocr_language("en-US").resolved_language == "en-US"
    core.request_sync.assert_called_once()
    core.request_sync.return_value = {"languages": ["en-GB"]}
    assert capture.available_ocr_languages() == ["en-GB"]
    assert capture.resolve_ocr_language("en-US").resolved_language == "en-GB"
    assert core.request_sync.call_count == 2


@pytest.mark.asyncio
async def test_slow_language_discovery_does_not_block_playback_clock(core):
    import threading

    entered = threading.Event()
    release = threading.Event()

    def languages(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return {"languages": ["en-US"]}

    core.request_sync.side_effect = languages
    task = asyncio.create_task(capture.ocr_image(Image.new("RGB", (1, 1)), "en-US"))
    try:
        await asyncio.wait_for(asyncio.to_thread(entered.wait, 1), timeout=1.5)
        assert entered.is_set()
        assert not task.done()
    finally:
        release.set()
        await task


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
