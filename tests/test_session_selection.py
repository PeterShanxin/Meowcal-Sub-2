"""The newest source/target choice owns the session, even when old I/O finishes late."""

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from meocosub2.models import SearchRequest
from tests.test_controller import _pair_controller


@pytest.mark.parametrize("mode", ["subtitle_pair", "auto_candidates", "ocr_fallback"])
@pytest.mark.parametrize("failure", [False, True])
async def test_late_prepare_cannot_replace_a_newer_choice(tmp_path: Path, mocker, mode, failure):
    controller, _, download = _pair_controller(tmp_path, mocker)
    entered, release = asyncio.Event(), asyncio.Event()
    events = AsyncMock()
    controller._emit_app_event = events

    async def slow(entry):
        entered.set()
        await release.wait()
        if failure:
            raise OSError("old download failed")
        return tmp_path / entry.file_name

    download.side_effect = slow
    first = asyncio.create_task(controller.prepare_session(mode, "match-1", "result-1", "result-2"))
    await asyncio.wait_for(entered.wait(), 2)
    latest = await controller.prepare_session("ocr_fallback", "match-1")
    events.reset_mock()
    release.set()
    with pytest.raises(RuntimeError, match="Subtitle selection changed"):
        await first
    assert controller.state_snapshot()["prepared_session"]["session_id"] == latest["session_id"]
    assert controller.state_snapshot()["status"] == "idle"
    events.assert_not_awaited()


async def test_a_new_search_rejects_the_old_prepare_and_discards_its_files(tmp_path: Path, mocker):
    controller, _, download = _pair_controller(tmp_path, mocker)
    catalog = controller._search_catalog
    for entry in catalog.results:
        entry.provider_result = SimpleNamespace(display_label=lambda: "Example")
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(entry):
        entered.set()
        await release.wait()
        return tmp_path / entry.file_name

    download.side_effect = slow
    old = asyncio.create_task(controller.prepare_session("subtitle_pair", "match-1", "result-1"))
    await asyncio.wait_for(entered.wait(), 2)
    mocker.patch.object(controller._aggregator, "search_catalog", return_value=catalog)
    await controller.search(SearchRequest("A new search", "zht", "en"))
    release.set()
    with pytest.raises(RuntimeError, match="Subtitle selection changed"):
        await old
    assert controller.state_snapshot()["prepared_session"] is None
    await controller.inspect_source("result-1", "match-1")
    assert download.await_count == 2


@pytest.mark.parametrize("wrong_file", ["source", "target"])
async def test_files_belong_to_the_requested_title_before_downloading(
    tmp_path: Path, mocker, wrong_file
):
    controller, _, download = _pair_controller(tmp_path, mocker)
    if wrong_file == "target":
        catalog = controller._search_catalog
        catalog.results[1] = replace(catalog.results[1], match_id="another")
    title = "another" if wrong_file == "source" else None
    with pytest.raises(ValueError, match=f"Selected {wrong_file} subtitle does not belong"):
        await controller.prepare_session("subtitle_pair", title, "result-1", "result-2")
    download.assert_not_awaited()


async def test_pair_without_explicit_title_uses_source_membership(tmp_path: Path, mocker):
    controller, _, _ = _pair_controller(tmp_path, mocker)
    prepared = await controller.prepare_session("subtitle_pair", None, "result-1", "result-2")
    assert prepared["feature_id"] == "match-1"


async def test_inspection_and_preparation_share_an_inflight_download(tmp_path: Path, mocker):
    controller, _, download = _pair_controller(tmp_path, mocker)
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(entry):
        entered.set()
        await release.wait()
        return tmp_path / entry.file_name

    download.side_effect = slow
    first = asyncio.create_task(controller.inspect_source("result-1"))
    await asyncio.wait_for(entered.wait(), 2)
    second = asyncio.create_task(controller.inspect_source("result-1"))
    prepared = asyncio.create_task(
        controller.prepare_session("subtitle_pair", None, "result-1", "__source__")
    )
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert (await second)["sourceFileId"] == (await prepared)["source_file_id"]
    download.assert_awaited_once()


async def test_later_inspection_finishing_first_is_reused(tmp_path: Path, mocker):
    controller, _, download = _pair_controller(tmp_path, mocker)
    entered, release = asyncio.Event(), asyncio.Event()

    async def by_file(entry):
        if entry.result_id == "result-1":
            entered.set()
            await release.wait()
        return tmp_path / entry.file_name

    download.side_effect = by_file
    first = asyncio.create_task(controller.inspect_source("result-1"))
    await asyncio.wait_for(entered.wait(), 2)
    await controller.inspect_source("result-2")
    release.set()
    await first
    prepared = await controller.prepare_session("subtitle_pair", None, "result-2", "__source__")
    assert prepared["source_file_name"] == "target.srt"
    assert download.await_count == 2


async def test_a_failed_inspection_can_retry(tmp_path: Path, mocker):
    controller, _, download = _pair_controller(tmp_path, mocker)
    download.side_effect = [OSError("download interrupted"), tmp_path / "source.srt"]
    with pytest.raises(OSError):
        await controller.inspect_source("result-1")
    assert (await controller.inspect_source("result-1"))["sourceFileId"] == "result-1"
    assert download.await_count == 2
