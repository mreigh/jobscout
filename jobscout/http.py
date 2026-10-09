"""Shared HTTP client factory.

All collectors get their client here so the user agent and timeouts are consistent.
Per-host rate limiting and retries land in JS-029.
"""

from __future__ import annotations

import httpx

from jobscout import __version__

USER_AGENT = (
    f"JobScout/{__version__} (personal job-search tool; polite, low-volume; "
    "+https://github.com/)"
)


def make_client(timeout: float = 20.0, **kwargs) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9"},
        timeout=timeout,
        follow_redirects=True,
        **kwargs,
    )
