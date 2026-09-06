from meocosub2.prompts import build_paired_prompt, build_prompt


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


def test_a_paired_prompt_shows_the_model_what_the_file_already_says() -> None:
    prompt = build_paired_prompt(
        "第三句",
        "zh",
        "en",
        [("第一句", "The first line"), ("第二句", "The second line")],
    )
    assert "第一句 => The first line" in prompt
    assert "第二句 => The second line" in prompt
    assert "第三句" in prompt


def test_a_paired_prompt_keeps_the_pairs_nearest_the_gap() -> None:
    far = ("x" * 400, "y" * 400)
    near = ("第二句", "The second line")
    prompt = build_paired_prompt("第三句", "zh", "en", [far, near])
    assert "The second line" in prompt
    assert "y" * 400 not in prompt


def test_a_paired_prompt_falls_back_when_no_neighbour_is_answered() -> None:
    # A file that answers almost nothing gives the model no voice to match, and
    # the plain instruction is a better ask than an empty example list.
    assert build_paired_prompt("你好", "zh", "en", []) == build_prompt("你好", "zh", "en")


def test_a_paired_prompt_uses_the_english_template_when_neither_side_is_chinese() -> None:
    prompt = build_paired_prompt("Trois", "fr", "en", [("Un", "One")])
    assert "This subtitle file already renders these lines:" in prompt
    assert "Un => One" in prompt
