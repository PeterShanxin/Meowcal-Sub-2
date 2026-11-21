"""Native OCR through an owned Core process independent of translation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from PIL import Image

from meocosub2.core_client import CoreClient, resolve_core_executable

_client: CoreClient | None = None
_languages: list[str] | None = None
_initialized: tuple[CoreClient, int | None, int] | None = None


@dataclass(frozen=True)
class OcrLine:
    text: str
    x: float
    y: float
    width: float
    height: float


def shutdown() -> None:
    global _client, _languages, _initialized
    _languages = None
    _initialized = None
    client, _client = _client, None
    if client is not None:
        client.close_sync()


def _ocr_client() -> CoreClient:
    global _client
    if _client is None:
        _client = CoreClient(resolve_core_executable())
    return _client


def available_languages(*, refresh: bool = False) -> list[str]:
    global _languages
    if not refresh and _languages is not None:
        return list(_languages)
    _languages = None
    response = _ocr_client().request_sync("ocrLanguages", {}, timeout_s=5.0)
    languages = response.get("languages")
    if not isinstance(languages, list) or not all(isinstance(tag, str) for tag in languages):
        raise RuntimeError("Core returned invalid OCR languages")
    _languages = list(languages)
    return list(languages)


def supports_ppocr() -> bool:
    client = _ocr_client()
    if client.hello_result is None:
        client.request_sync("status", {}, timeout_s=5.0)
    hello = client.hello_result
    return hello is not None and "ocrPpOcrV6" in hello["capabilities"]


async def initialize_ppocr(max_threads: int = 2) -> None:
    global _initialized
    if type(max_threads) is not int or not 1 <= max_threads <= 4:
        raise ValueError("PP-OCRv6 threads must be within 1..=4")
    client = _ocr_client()
    if _initialized == (client, client.process_generation, max_threads):
        return
    if client.hello_result is None:
        await client.request("status", {}, timeout_s=5.0)
    if client.hello_result is None or "ocrPpOcrV6" not in client.hello_result["capabilities"]:
        raise RuntimeError("This Core does not support PP-OCRv6")
    response = await client.request(
        "ocrInitialize", {"engine": "ppOcrV6", "maxThreads": max_threads}, timeout_s=10.0
    )
    if response.get("engine") != "ppOcrV6" or response.get("resolvedLanguage") is not None:
        raise RuntimeError("Core returned invalid PP-OCRv6 initialization")
    _initialized = (client, client.process_generation, max_threads)


async def recognize(
    image: Image.Image,
    language: str | None,
    timeout_s: float,
    *,
    engine: Literal["windows", "ppOcrV6"] = "windows",
    max_threads: int = 2,
) -> str:
    response = await _recognize_response(image, language, timeout_s, engine, max_threads)
    text = response.get("text")
    if not isinstance(text, str):
        raise RuntimeError("Core returned invalid OCR text")
    return text.strip()


async def recognize_ppocr_lines(
    image: Image.Image, timeout_s: float, *, max_threads: int = 2
) -> list[OcrLine]:
    response = await _recognize_response(image, None, timeout_s, "ppOcrV6", max_threads)
    lines, boxes = response.get("lines"), response.get("boxes")
    if not isinstance(lines, list) or not isinstance(boxes, list) or len(lines) != len(boxes):
        raise RuntimeError("Core returned invalid OCR lines")
    result = []
    for text, box in zip(lines, boxes, strict=True):
        if not isinstance(text, str) or not isinstance(box, dict):
            raise RuntimeError("Core returned invalid OCR line geometry")
        coordinates = [box.get(key) for key in ("x", "y", "width", "height")]
        if (
            any(
                type(value) not in (int, float) or not math.isfinite(value) for value in coordinates
            )
            or coordinates[2] <= 0
            or coordinates[3] <= 0
        ):
            raise RuntimeError("Core returned invalid OCR line geometry")
        result.append(OcrLine(text, *coordinates))
    return result


async def _recognize_response(
    image: Image.Image,
    language: str | None,
    timeout_s: float,
    engine: Literal["windows", "ppOcrV6"],
    max_threads: int,
) -> dict[str, object]:
    width, height = image.size
    if not (0 < width <= 4096 and 0 < height <= 4096):
        raise ValueError("OCR frame dimensions must be within 1..=4096")
    # Packed rows in BGRA8 order; Core ignores alpha.
    pixels = image.convert("RGBA").tobytes("raw", "BGRA")
    params: dict[str, object] = {
        "width": width,
        "height": height,
        "stride": width * 4,
        "timeoutMs": max(1, int(timeout_s * 1000)),
    }
    if engine == "ppOcrV6":
        params.update(engine=engine, maxThreads=max_threads)
    elif engine == "windows":
        params["language"] = language
    else:
        raise ValueError("Unknown OCR engine")
    return await _ocr_client().request(
        "ocrRecognizeBgra",
        params,
        timeout_s=timeout_s,
        payload=pixels,
    )
