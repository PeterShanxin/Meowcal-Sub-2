"""An unreachable provider must not cost the whole request budget."""

from __future__ import annotations

import httpx

from meocosub2.http_timeouts import CONNECT_TIMEOUT_S, provider_timeout
from meocosub2.opensubtitles.client import OpenSubtitlesClient


def test_provider_timeout_bounds_connect_independently_of_read() -> None:
    timeout = provider_timeout(30.0)
    assert timeout.connect == CONNECT_TIMEOUT_S
    assert timeout.read == 30.0


def test_connect_budget_is_shorter_than_the_operating_system_gives_up() -> None:
    # Windows abandons a TCP connect after roughly 21 seconds. A flat timeout above
    # that never fires, so a dead provider costs more than every live one combined.
    assert CONNECT_TIMEOUT_S < 21.0


def test_opensubtitles_client_bounds_its_connect_timeout(tmp_path) -> None:
    client = OpenSubtitlesClient(api_key="test-key", cache_dir=tmp_path)
    assert isinstance(client._client.timeout, httpx.Timeout)
    assert client._client.timeout.connect == CONNECT_TIMEOUT_S
