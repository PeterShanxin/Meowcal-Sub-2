from types import SimpleNamespace

import pytest

from meocosub2.config import AppConfig
from meocosub2.models import SubtitleLine
from meocosub2.translator import (
    build_translation_prompt,
    parse_batch_response,
    sanitize_output,
    translate_text,
    translate_lines,
)


class FakeModels:
    async def list(self):
        return SimpleNamespace(data=[SimpleNamespace(id="auto-model")])


class FakeCompletions:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.responses.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self.models = FakeModels()
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))

    async def close(self) -> None:
        return None


def make_lines(count: int) -> list[SubtitleLine]:
    return [
        SubtitleLine(index=index, start_ms=index * 1000, end_ms=(index + 1) * 1000, text=f"line {index}")
        for index in range(count)
    ]


def test_sanitize_output_removes_labels_and_quotes() -> None:
    assert sanitize_output('Translation: "1. hello"') == "hello"


def test_build_translation_prompt_includes_last_three_context_lines() -> None:
    prompt = build_translation_prompt(
        ["current line"],
        "en",
        "zht",
        ["one", "two", "three", "four"],
    )
    assert "one" not in prompt
    assert "two" in prompt
    assert "four" in prompt


def test_parse_batch_response_pads_missing_lines() -> None:
    parsed = parse_batch_response("1. 你好", 2)
    assert parsed == ["你好", ""]


@pytest.mark.asyncio
async def test_translate_lines_batches_and_reports_progress() -> None:
    config = AppConfig(foundry_model="manual-model", translation_batch_size=5)
    client = FakeClient(["1. A\n2. B\n3. C\n4. D\n5. E", "1. F"])
    progress: list[tuple[int, int]] = []
    lines = await translate_lines(make_lines(6), config, progress_callback=lambda done, total: progress.append((done, total)), client=client)
    assert [line.translated for line in lines] == ["A", "B", "C", "D", "E", "F"]
    assert progress == [(5, 6), (6, 6)]


@pytest.mark.asyncio
async def test_translate_lines_uses_rolling_three_line_context() -> None:
    config = AppConfig(foundry_model="manual-model", translation_batch_size=3)
    client = FakeClient(["1. uno\n2. dos\n3. tres", "1. cuatro\n2. cinco\n3. seis"])
    await translate_lines(make_lines(6), config, client=client)
    second_prompt = client.chat.completions.calls[1]["messages"][0]["content"]
    assert "uno" in second_prompt
    assert "dos" in second_prompt
    assert "tres" in second_prompt


@pytest.mark.asyncio
async def test_translate_lines_falls_back_to_source_text_when_empty() -> None:
    config = AppConfig(foundry_model="manual-model")
    client = FakeClient(["1. "])
    lines = await translate_lines([SubtitleLine(index=0, start_ms=0, end_ms=1000, text="source")], config, client=client)
    assert lines[0].translated == "source"


@pytest.mark.asyncio
async def test_translate_lines_auto_detects_model_when_blank() -> None:
    config = AppConfig(foundry_model="")
    client = FakeClient(["1. translated"])
    await translate_lines([SubtitleLine(index=0, start_ms=0, end_ms=1000, text="source")], config, client=client)
    assert client.chat.completions.calls[0]["model"] == "auto-model"


@pytest.mark.asyncio
async def test_translate_text_uses_context_and_sanitizes_single_line_output() -> None:
    config = AppConfig(foundry_model="manual-model")
    client = FakeClient(['Translation: "hello there"'])

    output = await translate_text(
        "source line",
        config,
        context_lines=["older", "previous", "latest"],
        client=client,
    )

    assert output == "hello there"
    prompt = client.chat.completions.calls[0]["messages"][0]["content"]
    assert "older" in prompt
    assert "latest" in prompt
    assert "source line" in prompt


@pytest.mark.asyncio
async def test_translate_text_falls_back_to_source_when_model_returns_empty() -> None:
    config = AppConfig(foundry_model="manual-model")
    client = FakeClient([""])

    output = await translate_text("source line", config, client=client)

    assert output == "source line"
