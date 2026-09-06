"""Preparing a session from a source that carries its own translation."""

from pathlib import Path

import pytest

from tests.test_controller import _pair_controller

BILINGUAL_SRT = (
    "1\n00:00:00,000 --> 00:00:02,000\n你好\nHello there\n\n"
    "2\n00:00:03,000 --> 00:00:05,000\n再见\nGoodbye now\n"
)
MONOLINGUAL_SRT = (
    "1\n00:00:00,000 --> 00:00:02,000\n你好\n\n2\n00:00:03,000 --> 00:00:05,000\n再见\n"
)


def _bilingual_pair(tmp_path: Path, mocker):
    """A controller whose chosen source carries its own English."""
    controller, _, download = _pair_controller(tmp_path, mocker)
    source = tmp_path / "bilingual-source.srt"
    source.write_text(BILINGUAL_SRT, encoding="utf-8")
    download.side_effect = [source, source, source]
    return controller, download


@pytest.mark.asyncio
async def test_a_bilingual_source_answers_itself_without_downloading_a_target(
    tmp_path: Path, mocker
) -> None:
    """The rows of one cue are aligned by construction, so nothing is paired.

    Measured on a real file, pairing a separate target file against a bilingual
    source showed different words on 25% to 64% of the episode, depending on
    which target was picked.
    """
    controller, download = _bilingual_pair(tmp_path, mocker)

    payload = await controller.prepare_session(
        mode="subtitle_pair",
        feature_id="match-1",
        source_file_id="result-1",
        target_file_id="__source__",
    )

    assert payload["target_match_mode"] == "source_own_translation"
    assert payload["target_line_count"] == 2
    assert payload["used_translation"] is False
    # The source, and nothing else: no target file, and no rivals weighed.
    assert download.await_count == 1
    assert payload["target_alignment"] == []


@pytest.mark.asyncio
async def test_the_split_translations_are_what_the_session_will_draw(
    tmp_path: Path, mocker
) -> None:
    controller, _ = _bilingual_pair(tmp_path, mocker)

    await controller.prepare_session(
        mode="subtitle_pair",
        feature_id="match-1",
        source_file_id="result-1",
        target_file_id="__source__",
    )

    runtime = controller._prepared_runtime
    assert runtime is not None
    lines = runtime.source_candidates[0].pair.source_lines
    assert [line.text for line in lines] == ["你好", "再见"]
    assert [line.translated for line in lines] == ["Hello there", "Goodbye now"]


@pytest.mark.asyncio
async def test_inspecting_a_source_says_whether_it_carries_a_translation(
    tmp_path: Path, mocker
) -> None:
    """Asked at the target step: the first moment it is knowable, the last it helps."""
    controller, _ = _bilingual_pair(tmp_path, mocker)

    report = await controller.inspect_source("result-1", "match-1")

    assert report["carriesTranslation"] is True
    assert report["totalCues"] == 2
    assert report["translatedCues"] == 2


@pytest.mark.asyncio
async def test_inspecting_a_monolingual_source_says_it_carries_nothing(
    tmp_path: Path, mocker
) -> None:
    controller, _, download = _pair_controller(tmp_path, mocker)
    plain = tmp_path / "plain.srt"
    plain.write_text(MONOLINGUAL_SRT, encoding="utf-8")
    download.side_effect = [plain]

    report = await controller.inspect_source("result-1", "match-1")

    assert report["carriesTranslation"] is False
    assert report["translatedCues"] == 0


@pytest.mark.asyncio
async def test_a_source_that_turns_out_not_to_be_bilingual_still_prepares(
    tmp_path: Path, mocker
) -> None:
    """Nothing splits, so the model answers the lines as it does with no target."""
    controller, _, download = _pair_controller(tmp_path, mocker)
    plain = tmp_path / "plain.srt"
    plain.write_text(MONOLINGUAL_SRT, encoding="utf-8")
    download.side_effect = [plain]

    payload = await controller.prepare_session(
        mode="subtitle_pair",
        feature_id="match-1",
        source_file_id="result-1",
        target_file_id="__source__",
    )

    assert payload["used_translation"] is True
    assert payload["target_line_count"] == 0
