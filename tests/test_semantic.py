"""Tests for semantic matching against the embedding engine."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from meocosub2.semantic import ENCODE_BATCH, SemanticError, SemanticIndex

ENDPOINT = "http://127.0.0.1:11437"

# A toy vector per phrase. Two ways of saying the same thing point in nearly the
# same direction; a damaged read points somewhere else entirely.
VECTORS = {
    "Morty 等下 你看这个": [1.0, 0.0, 0.0],
    "嘿 莫迪 等等 瞧瞧这个": [0.96, 0.28, 0.0],
    "我们该走了": [0.0, 1.0, 0.0],
    "趁天还没黑": [0.0, 0.0, 1.0],
    "一了岔子一虽然可能": [0.5, 0.5, 0.71],
}


def _embeddings(request: httpx.Request) -> httpx.Response:
    texts = json.loads(request.content)["input"]
    return httpx.Response(
        200,
        json={
            "data": [
                {"index": position, "embedding": VECTORS.get(text, [0.0, 0.0, 0.0])}
                for position, text in enumerate(texts)
            ]
        },
    )


async def built_index(lines: list[str]) -> SemanticIndex:
    index = SemanticIndex(ENDPOINT)
    await index.build(lines)
    return index


@respx.mock
@pytest.mark.asyncio
async def test_a_read_matches_the_line_that_means_the_same_thing() -> None:
    respx.post(f"{ENDPOINT}/v1/embeddings").mock(side_effect=_embeddings)
    index = await built_index(["我们该走了", "Morty 等下 你看这个", "趁天还没黑"])

    hit = await index.best("嘿 莫迪 等等 瞧瞧这个")

    assert hit is not None
    # The two share almost no characters, which is the case fuzzy matching loses.
    assert hit.index == 1
    assert hit.score > 0.9


@respx.mock
@pytest.mark.asyncio
async def test_a_damaged_read_scores_below_a_genuine_one() -> None:
    respx.post(f"{ENDPOINT}/v1/embeddings").mock(side_effect=_embeddings)
    index = await built_index(["Morty 等下 你看这个"])

    genuine = await index.best("嘿 莫迪 等等 瞧瞧这个")
    junk = await index.best("一了岔子一虽然可能")

    assert genuine is not None and junk is not None
    assert junk.score < genuine.score


@respx.mock
@pytest.mark.asyncio
async def test_only_the_lines_the_clock_left_in_the_window_are_scored() -> None:
    respx.post(f"{ENDPOINT}/v1/embeddings").mock(side_effect=_embeddings)
    index = await built_index(["我们该走了", "Morty 等下 你看这个", "趁天还没黑"])

    hit = await index.best("嘿 莫迪 等等 瞧瞧这个", indices=[0, 2])

    assert hit is not None and hit.index in {0, 2}


@respx.mock
@pytest.mark.asyncio
async def test_the_file_is_encoded_in_batches() -> None:
    route = respx.post(f"{ENDPOINT}/v1/embeddings").mock(side_effect=_embeddings)
    lines = ["我们该走了"] * (ENCODE_BATCH + 1)

    index = await built_index(lines)

    assert route.call_count == 2
    assert index.ready


@respx.mock
@pytest.mark.asyncio
async def test_vectors_are_matched_to_lines_by_the_index_the_engine_reports() -> None:
    """Nothing promises the engine answers in the order the lines went out."""

    def shuffled(request: httpx.Request) -> httpx.Response:
        rows = json.loads(_embeddings(request).content)["data"]
        return httpx.Response(200, json={"data": list(reversed(rows))})

    respx.post(f"{ENDPOINT}/v1/embeddings").mock(side_effect=shuffled)
    index = await built_index(["我们该走了", "Morty 等下 你看这个"])

    hit = await index.best("嘿 莫迪 等等 瞧瞧这个")

    assert hit is not None and hit.index == 1


@respx.mock
@pytest.mark.asyncio
async def test_a_short_answer_from_the_engine_is_an_error_rather_than_a_silent_gap() -> None:
    respx.post(f"{ENDPOINT}/v1/embeddings").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    with pytest.raises(SemanticError):
        await built_index(["我们该走了"])


@respx.mock
@pytest.mark.asyncio
async def test_an_engine_that_does_not_answer_is_an_error() -> None:
    respx.post(f"{ENDPOINT}/v1/embeddings").mock(return_value=httpx.Response(503))
    with pytest.raises(SemanticError):
        await built_index(["我们该走了"])


@respx.mock
@pytest.mark.asyncio
async def test_an_empty_read_is_not_sent_to_the_engine() -> None:
    route = respx.post(f"{ENDPOINT}/v1/embeddings").mock(side_effect=_embeddings)
    index = await built_index(["我们该走了"])
    calls_after_build = route.call_count

    assert await index.best("   ") is None
    assert route.call_count == calls_after_build


@respx.mock
@pytest.mark.asyncio
async def test_an_engine_that_stops_answering_takes_the_index_out_of_service() -> None:
    """Otherwise every later read pays the timeout and is abandoned with it.

    The caller treats a failed query as a failed read, so an engine that exits
    mid-session left the plate blank until the session was restarted.
    """
    route = respx.post(f"{ENDPOINT}/v1/embeddings").mock(side_effect=_embeddings)
    index = await built_index(["Morty 等下 你看这个"])
    assert index.ready

    route.mock(side_effect=httpx.ConnectError("the engine is gone"))

    assert await index.best("嘿 莫迪 等等 瞧瞧这个") is None
    assert not index.ready
