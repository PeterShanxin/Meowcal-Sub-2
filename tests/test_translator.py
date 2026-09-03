import httpx
import pytest

from meocosub2.errors import TranslationError
from meocosub2.translator import (
    TranslationClient,
    build_prompt,
    drop_restated_context,
    is_untranslatable,
    is_usable_translation,
    looks_like_a_loop,
    sanitize_output,
)


def test_sanitize_output_removes_labels_and_quotes() -> None:
    assert sanitize_output('Translation: "你好"') == "你好"
    assert sanitize_output("译文：你好") == "你好"
    assert sanitize_output("Note: this is an explanation") == ""


def test_sanitize_output_joins_wrapped_lines_into_one_subtitle() -> None:
    assert sanitize_output("I don't know\nwhat to say.") == "I don't know what to say."


def test_build_prompt_uses_the_chinese_template_for_chinese_targets() -> None:
    prompt = build_prompt("Hello there", "en", "zh")
    assert "将以下文本翻译为" in prompt
    assert "Hello there" in prompt


def test_build_prompt_uses_the_chinese_template_for_chinese_sources() -> None:
    prompt = build_prompt("你好", "zh", "en")
    assert "将以下文本翻译为英语" in prompt
    assert "你好" in prompt


def test_build_prompt_uses_the_english_template_when_neither_side_is_chinese() -> None:
    prompt = build_prompt("Bonjour", "fr", "en")
    assert "Translate the following segment into English" in prompt
    assert "Bonjour" in prompt


def test_build_prompt_carries_recent_lines_as_context() -> None:
    prompt = build_prompt("Third", "en", "zh", ["First", "Second"])
    assert prompt.startswith("First\nSecond")
    assert "参考上面的信息" in prompt


def test_build_prompt_clips_context_to_the_most_recent_lines() -> None:
    prompt = build_prompt("now", "fr", "en", ["x" * 500, "recent"])
    assert "recent" in prompt
    assert "x" * 500 not in prompt


@pytest.mark.parametrize("text", ["", "  ", "-", "1", "//"])
def test_untranslatable_reads_are_rejected(text: str) -> None:
    assert is_untranslatable(text)


@pytest.mark.parametrize("text", ["OK", "好的", "No."])
def test_short_real_subtitles_are_translatable(text: str) -> None:
    assert not is_untranslatable(text)


def _client(handler) -> TranslationClient:
    client = TranslationClient("http://engine.test", "model-id", 5.0)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


@pytest.mark.asyncio
async def test_translate_posts_the_prompt_and_returns_the_cleaned_reply() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        return httpx.Response(
            200, json={"choices": [{"message": {"content": 'Translation: "你好"'}}]}
        )

    client = _client(handler)
    assert await client.translate("Hello", "en", "zh") == "你好"
    assert seen["url"] == "http://engine.test/v1/chat/completions"
    assert "将以下文本翻译为" in str(seen["body"])
    await client.close()


@pytest.mark.asyncio
async def test_translate_skips_the_engine_for_ocr_noise() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("noise should never reach the engine")

    client = _client(handler)
    assert await client.translate("//", "en", "zh") == ""
    await client.close()


@pytest.mark.asyncio
async def test_translate_reports_an_unreachable_engine() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _client(handler)
    with pytest.raises(TranslationError):
        await client.translate("Hello", "en", "zh")
    await client.close()


def test_a_translation_of_the_line_is_usable() -> None:
    assert is_usable_translation("请给我们五分钟", "Please give us five minutes.", "en")
    assert is_usable_translation("Hello there", "你好", "zh")
    assert is_usable_translation("好的", "OK", "en")


def test_output_that_swallowed_the_context_is_refused() -> None:
    assert not is_usable_translation(
        "请给我们五分钟",
        "Why do dreamers even participate at all? Please give us five minutes. "
        "Five minutes? We talked for at least an hour.",
        "en",
    )


def test_a_repetition_loop_is_refused() -> None:
    assert not is_usable_translation("Hello", "no no no no no no no no no", "zh")
    assert looks_like_a_loop("go go go go and then go go go go")


def test_ordinary_output_is_not_a_loop() -> None:
    assert not looks_like_a_loop("I don't know what to say about any of this.")


def test_empty_output_is_refused() -> None:
    assert not is_usable_translation("Hello", "", "zh")


@pytest.mark.asyncio
async def test_unusable_output_is_not_shown() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "x " * 400}}]},
        )

    client = _client(handler)
    assert await client.translate("请给我们五分钟", "zh", "en") == ""
    await client.close()


def test_a_sentence_the_model_said_twice_is_refused() -> None:
    assert not is_usable_translation(
        "人类只使用了大脑的一小部分",
        "Yes, humans use only a small part of their brains. "
        "Yes, humans use only a small part of their brains.",
        "en",
    )


def test_chinese_returned_for_an_english_target_is_refused() -> None:
    assert not is_usable_translation("真正的灵感 对吧", "真正的灵感，对吧？", "en")


def test_english_returned_for_a_chinese_target_is_refused() -> None:
    assert not is_usable_translation("Hello there", "Hello there", "zh")


def test_a_name_the_model_left_alone_is_accepted() -> None:
    assert is_usable_translation("Ariadne", "Ariadne", "zh")
    assert is_usable_translation("SAITO", "SAITO", "zh")


def test_a_short_latin_answer_is_not_judged_by_script() -> None:
    assert is_usable_translation("好的", "OK", "en")
    assert is_usable_translation("是", "Yes", "zh")


def test_an_english_answer_with_a_quoted_chinese_name_is_kept() -> None:
    assert is_usable_translation(
        "他叫做小明", "His name is 小明, and he lives nearby.", "en"
    )


def test_leading_sentences_that_restate_the_context_are_dropped() -> None:
    context = [
        "I understand; it's like I'm trying to uncover something within it.",
        "Isn't that the real inspiration, right?",
    ]
    answer = (
        "I understand; it's as if I'm trying to uncover something within it. "
        "Isn't that the real inspiration, right? "
        "Yes, we will continue to do so in our dreams."
    )
    assert (
        drop_restated_context(answer, context)
        == "Yes, we will continue to do so in our dreams."
    )


def test_a_fresh_translation_is_left_alone() -> None:
    context = ["Please give us five minutes."]
    assert drop_restated_context("Five minutes? We talked for an hour.", context) == (
        "Five minutes? We talked for an hour."
    )


def test_an_answer_that_is_only_restatement_is_dropped() -> None:
    context = ["Please give us five minutes.", "Five minutes?"]
    answer = "Please give us five minutes. Five minutes?"
    assert drop_restated_context(answer, context) == ""


def test_nothing_is_dropped_without_context() -> None:
    assert drop_restated_context("One. Two.", []) == "One. Two."


def test_trailing_sentences_that_restate_the_context_are_dropped() -> None:
    context = [
        "In our dreams, we will continue to do this.",
        "Also, design and create your own world.",
    ]
    answer = (
        "Everything happens naturally; we don't even realize it. "
        "In our dreams, we will continue to do this. "
        "Also, design and create your own world."
    )
    assert (
        drop_restated_context(answer, context)
        == "Everything happens naturally; we don't even realize it."
    )


@pytest.mark.parametrize("text", ["好", "是", "ハ"])
def test_a_single_cjk_character_is_a_whole_word(text: str) -> None:
    assert not is_untranslatable(text)


@pytest.mark.parametrize("text", ["a", "1", "-"])
def test_a_single_latin_glyph_is_still_noise(text: str) -> None:
    assert is_untranslatable(text)
