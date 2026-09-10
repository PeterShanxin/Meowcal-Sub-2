import asyncio
import logging
import threading
from types import SimpleNamespace

import pytest
from PIL import Image
from winrt.windows.foundation import AsyncStatus

from meocosub2 import capture


class OcrOperation:
    def __init__(self):
        self.status = AsyncStatus.STARTED
        self.callback = None
        self.text = ""
        self.error = None
        self.cancel_error = None
        self.cancel_count = 0

    @property
    def completed(self):
        return self.callback

    @completed.setter
    def completed(self, callback):
        self.callback = callback
        if self.status != AsyncStatus.STARTED:
            callback(self, self.status)

    def finish(self, text="", error=None):
        self.text, self.error = text, error
        self.status = AsyncStatus.ERROR if error else AsyncStatus.COMPLETED
        if self.callback:
            self.callback(self, self.status)
        return self

    def cancel(self):
        self.cancel_count += 1
        if self.cancel_error:
            raise self.cancel_error
        # A native operation may ignore cancellation and remain STARTED.

    def get_results(self):
        assert self.status != AsyncStatus.STARTED
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text)


@pytest.fixture
def native_ocr(mocker):
    mocker.patch.object(capture, "_pending_ocr", None)
    mocker.patch.object(capture, "_OCR_PASS_TIMEOUT_SECONDS", 0.01)
    return mocker.patch("winocr.recognize_pil")


@pytest.mark.asyncio
async def test_native_ocr_handles_completion_before_callback_registration(native_ocr):
    native_ocr.return_value = OcrOperation().finish(" hello ")

    assert await asyncio.wait_for(capture._run_ocr(Image.new("RGB", (4, 2)), "en"), 0.2) == "hello"


@pytest.mark.asyncio
async def test_native_ocr_receives_completion_from_another_thread(native_ocr):
    operation = native_ocr.return_value = OcrOperation()
    task = asyncio.create_task(capture._run_ocr(Image.new("RGB", (4, 2)), "en"))
    await asyncio.sleep(0)
    thread = threading.Thread(target=lambda: operation.finish("hello"), daemon=True)
    thread.start()
    try:
        assert await asyncio.wait_for(task, 0.2) == "hello"
    finally:
        thread.join(timeout=0.2)
    assert not thread.is_alive()


@pytest.mark.asyncio
async def test_timed_out_native_operation_is_not_replaced_until_it_finishes(native_ocr):
    operation = native_ocr.return_value = OcrOperation()
    image = Image.new("RGB", (4, 2))

    assert await asyncio.wait_for(capture.ocr_image(image, "en"), 0.2) == ""
    assert operation.cancel_count == 1
    assert await asyncio.wait_for(capture.ocr_image(image, "en"), 0.2) == ""
    assert native_ocr.call_count == 1

    operation.finish("late result")
    native_ocr.return_value = OcrOperation().finish("new result")
    assert await asyncio.wait_for(capture.ocr_image(image, "en"), 0.2) == "new result"


@pytest.mark.asyncio
async def test_timed_out_native_white_pass_preserves_prior_read(native_ocr):
    pending = OcrOperation()
    native_ocr.side_effect = [
        OcrOperation().finish("please sit down"),
        OcrOperation().finish(),
        pending,
    ]

    result = await asyncio.wait_for(capture.ocr_image(Image.new("RGB", (4, 2)), "en"), 0.2)
    assert result == "please sit down"
    assert pending.cancel_count == 1


@pytest.mark.asyncio
async def test_native_failure_is_logged_and_prior_read_survives(native_ocr, caplog):
    native_ocr.side_effect = [
        OcrOperation().finish("please sit down"),
        OcrOperation().finish(error=RuntimeError("native read failed")),
        OcrOperation().finish(),
    ]

    with caplog.at_level(logging.DEBUG):
        result = await capture.ocr_image(Image.new("RGB", (4, 2)), "en")
    assert result == "please sit down"
    assert "native read failed" in caplog.text


@pytest.mark.asyncio
async def test_native_cancel_failure_does_not_enqueue_more_operations(native_ocr, caplog):
    operation = native_ocr.return_value = OcrOperation()
    operation.cancel_error = RuntimeError("native cancel failed")

    with caplog.at_level(logging.DEBUG):
        result = await asyncio.wait_for(capture.ocr_image(Image.new("RGB", (4, 2)), "en"), 0.2)
    assert result == ""
    assert native_ocr.call_count == 1
    assert "native cancel failed" in caplog.text


@pytest.mark.asyncio
async def test_session_cancellation_reaches_native_operation(native_ocr):
    operation = native_ocr.return_value = OcrOperation()
    task = asyncio.create_task(capture._run_ocr(Image.new("RGB", (4, 2)), "en"))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert operation.cancel_count == 1


@pytest.mark.asyncio
async def test_native_cancel_failure_preserves_session_cancellation(native_ocr, caplog):
    operation = OcrOperation()
    operation.cancel_error = RuntimeError("native cancel failed")
    started = asyncio.Event()

    def recognize(image, language):
        started.set()
        return operation

    native_ocr.side_effect = recognize
    task = asyncio.create_task(capture.ocr_image(Image.new("RGB", (4, 2)), "en"))
    await asyncio.wait_for(started.wait(), 0.2)
    with caplog.at_level(logging.DEBUG):
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert task.cancelled()
    assert operation.cancel_count == 1
    assert "native cancel failed" in caplog.text
