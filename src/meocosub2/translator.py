"""Batch subtitle translation through a Foundry Local OpenAI-compatible endpoint."""

from __future__ import annotations

import asyncio
import inspect
import re
from typing import Callable

from openai import APIConnectionError, APIError, APITimeoutError, AsyncOpenAI

from meocosub2.config import AppConfig
from meocosub2.errors import TranslationError
from meocosub2.foundry import resolve_foundry_api_base, select_model
from meocosub2.models import SubtitleLine


def sanitize_output(text: str) -> str:
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        line = re.sub(r"^\s*(translation|output)\s*:\s*", "", line, flags=re.IGNORECASE)
        line = line.strip().strip("\"'")
        line = re.sub(r"^\s*\d+[\.\)]\s*", "", line)
        line = line.strip().strip("\"'")
        if not line:
            continue
        if re.match(r"^(here|note|explanation)\b", line, flags=re.IGNORECASE):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def build_translation_prompt(
    lines: list[str],
    source_lang: str,
    target_lang: str,
    context_lines: list[str] | None = None,
) -> str:
    prompt = [
        f"Translate these subtitle lines from {source_lang} into {target_lang}.",
        "Output ONLY the translations, numbered to match the input. No explanations.",
    ]
    if context_lines:
        prompt.append("")
        prompt.append("Context:")
        prompt.extend(context_lines[-3:])
    prompt.append("")
    for index, line in enumerate(lines, start=1):
        prompt.append(f"{index}. {line}")
    return "\n".join(prompt)


def parse_batch_response(response: str, expected_count: int) -> list[str]:
    numbered: dict[int, str] = {}
    for raw_line in response.splitlines():
        match = re.match(r"^\s*(\d+)[\.\)]\s*(.*)$", raw_line)
        if match:
            numbered[int(match.group(1))] = match.group(2).strip()

    if numbered:
        parsed = [numbered.get(index, "") for index in range(1, expected_count + 1)]
    else:
        parsed = [line.strip() for line in response.splitlines() if line.strip()]

    if len(parsed) < expected_count:
        parsed.extend([""] * (expected_count - len(parsed)))
    return parsed[:expected_count]


async def _resolve_model(client: AsyncOpenAI, config: AppConfig) -> str:
    try:
        models = await client.models.list()
    except (APIConnectionError, APITimeoutError, APIError) as exc:
        raise TranslationError(f"Foundry Local model discovery failed: {exc}") from exc
    if not getattr(models, "data", None):
        raise TranslationError("No models available from Foundry Local")
    model_ids = [str(model.id) for model in models.data]
    selected = select_model(config.foundry_model or None, model_ids)
    if not selected:
        raise TranslationError("Foundry Local did not return a usable model.")
    return selected


async def open_translation_client(config: AppConfig) -> tuple[AsyncOpenAI, str]:
    api_base = await asyncio.to_thread(resolve_foundry_api_base, config)
    client = AsyncOpenAI(
        base_url=api_base,
        api_key="foundry-local",
        timeout=config.translation_timeout_s,
    )
    try:
        model = await _resolve_model(client, config)
    except Exception:
        await client.close()
        raise
    return client, model


async def _emit_progress(
    callback: Callable[[int, int], object] | None,
    done: int,
    total: int,
) -> None:
    if callback is None:
        return
    result = callback(done, total)
    if inspect.isawaitable(result):
        await result


async def translate_lines(
    lines: list[SubtitleLine],
    config: AppConfig,
    progress_callback: Callable[[int, int], object] | None = None,
    client: AsyncOpenAI | None = None,
) -> list[SubtitleLine]:
    if not lines:
        return []

    own_client = client is None
    if client is None:
        client, model = await open_translation_client(config)
    else:
        model = await _resolve_model(client, config)

    try:
        context: list[str] = []
        total = len(lines)

        for start in range(0, total, config.translation_batch_size):
            batch = lines[start : start + config.translation_batch_size]
            prompt = build_translation_prompt(
                [line.text for line in batch],
                config.source_language,
                config.target_language,
                context[-3:],
            )
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                )
            except (APIConnectionError, APITimeoutError, APIError) as exc:
                raise TranslationError(f"Foundry Local translation request failed: {exc}") from exc
            content = response.choices[0].message.content or ""
            outputs = parse_batch_response(content, len(batch))

            for line, output in zip(batch, outputs):
                translated = sanitize_output(output)
                if not translated:
                    translated = line.text
                line.translated = translated
                context.append(translated)

            await _emit_progress(progress_callback, min(start + len(batch), total), total)

        return lines
    finally:
        if own_client:
            await client.close()


async def translate_text(
    text: str,
    config: AppConfig,
    context_lines: list[str] | None = None,
    client: AsyncOpenAI | None = None,
    model: str | None = None,
) -> str:
    if not text.strip():
        return ""

    own_client = client is None
    if client is None:
        client, model = await open_translation_client(config)
    elif model is None:
        model = await _resolve_model(client, config)

    try:
        prompt = build_translation_prompt(
            [text],
            config.source_language,
            config.target_language,
            context_lines,
        )
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
        except (APIConnectionError, APITimeoutError, APIError) as exc:
            raise TranslationError(f"Foundry Local translation request failed: {exc}") from exc

        content = response.choices[0].message.content or ""
        outputs = parse_batch_response(content, 1)
        translated = sanitize_output(outputs[0] if outputs else content)
        return translated or text
    finally:
        if own_client:
            await client.close()
