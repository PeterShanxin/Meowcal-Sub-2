"""Matching a read to a subtitle line by meaning rather than by characters.

The streaming site burns in one fansub's translation and the file we downloaded
carries another's, so the same dialogue often shares almost no characters -
burned-in `嘿 莫迪 等等 瞧瞧这个` against the file's `Morty 等下 你看这个`.
Character-level matching measured 8 of 64 cues on a real episode, and the other
56 peaked at 20-40 against a threshold of 65, so no threshold recovers them.

Meaning survives the rewording. Measured over the same session with
`bge-small-zh` on the llama.cpp runtime the app already ships: genuine matches
scored 0.62-0.93, reads too damaged to be anything scored 0.47-0.55, and the
lines it picked climbed monotonically through the episode.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Encoding the whole file is one request per batch at session start, not a cost
# any read pays. Bounded so a long episode does not build one enormous body.
ENCODE_BATCH = 64
BUILD_TIMEOUT_S = 120.0
QUERY_TIMEOUT_S = 5.0


class SemanticError(RuntimeError):
    """The embedding engine could not answer."""


@dataclass(frozen=True)
class SemanticHit:
    index: int
    score: float


def _normalized(vector: Sequence[float]) -> list[float]:
    length = math.sqrt(sum(value * value for value in vector))
    if not length:
        return [0.0] * len(vector)
    return [value / length for value in vector]


class SemanticIndex:
    """The subtitle file as vectors, and the line nearest to a read.

    Vectors are stored normalised so similarity is a plain dot product - the
    comparison runs on every read, against every candidate the playback clock
    left in the window, and the square roots are the expensive part of it.
    """

    def __init__(self, endpoint: str) -> None:
        self._endpoint = endpoint
        self._vectors: list[list[float]] = []

    @property
    def ready(self) -> bool:
        return bool(self._vectors)

    async def build(self, texts: Sequence[str]) -> None:
        """Encode every line in the file. Once per session, at about 1.3s / 450 lines."""
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=BUILD_TIMEOUT_S) as client:
            for start in range(0, len(texts), ENCODE_BATCH):
                batch = texts[start : start + ENCODE_BATCH]
                vectors.extend(await self._encode(client, list(batch)))
        self._vectors = vectors
        logger.debug("Semantic index built over %d subtitle lines", len(vectors))

    async def best(self, text: str, indices: Iterable[int] | None = None) -> SemanticHit | None:
        """The nearest line to this read, among `indices` or the whole file."""
        if not self._vectors or not text.strip():
            return None
        async with httpx.AsyncClient(timeout=QUERY_TIMEOUT_S) as client:
            query = (await self._encode(client, [text]))[0]
        candidates = range(len(self._vectors)) if indices is None else indices

        hit: SemanticHit | None = None
        for index in candidates:
            if not 0 <= index < len(self._vectors):
                continue
            vector = self._vectors[index]
            score = sum(a * b for a, b in zip(query, vector, strict=True))
            if hit is None or score > hit.score:
                hit = SemanticHit(index=index, score=score)
        return hit

    async def _encode(self, client: httpx.AsyncClient, texts: list[str]) -> list[list[float]]:
        try:
            response = await client.post(f"{self._endpoint}/v1/embeddings", json={"input": texts})
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise SemanticError(f"The embedding engine did not answer: {error}") from error

        rows = payload.get("data") or []
        if len(rows) != len(texts):
            raise SemanticError(
                f"The embedding engine returned {len(rows)} vectors for {len(texts)} lines."
            )
        # The response carries its own ordering, and nothing promises it matches
        # the order the lines went out in.
        rows = sorted(rows, key=lambda row: row.get("index", 0))
        return [_normalized(row["embedding"]) for row in rows]
