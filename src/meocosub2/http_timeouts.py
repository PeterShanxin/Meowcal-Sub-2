"""Timeouts for outbound subtitle-provider HTTP.

A single flat timeout lets an unreachable provider spend the whole budget. The
operating system abandons a TCP connect on its own after roughly 21 seconds, so a
30-second flat timeout never fires and a provider nobody can reach costs more
than every reachable provider put together. Bounding the connect phase on its own
makes a dead provider cheap without shortening how long a slow but live one has
to answer.
"""

from __future__ import annotations

import httpx

#: How long to spend opening a connection before giving up on the host.
CONNECT_TIMEOUT_S = 5.0


def provider_timeout(read_s: float) -> httpx.Timeout:
    """Quick to give up connecting, patient once the host is answering."""
    return httpx.Timeout(read_s, connect=CONNECT_TIMEOUT_S)
