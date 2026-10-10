"""Shared HTTP plumbing: one client config, per-host rate limiting, and retries.

Every outbound request in JobScout goes through `PoliteClient.get/post` so we
never hammer a host, and transient failures (timeouts, 429, 5xx) get retried
with backoff instead of being mistaken for "this company has no job board".
"""

from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urlsplit

import httpx

from jobscout import __version__

log = logging.getLogger(__name__)

USER_AGENT = (
    f"JobScout/{__version__} (personal job-search tool; polite, low-volume; "
    "+https://github.com/mreigh/jobscout)"
)

RETRY_STATUSES = {429, 500, 502, 503, 504}


def make_client(timeout: float = 20.0, **kwargs) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9"},
        timeout=timeout,
        follow_redirects=True,
        **kwargs,
    )


class TransientError(Exception):
    """The request failed in a way that says nothing about whether the resource exists."""


class HostRateLimiter:
    """Enforces a minimum gap between requests to the same host, across threads."""

    def __init__(self, min_interval: float = 0.25):
        self.min_interval = min_interval
        self._next_ok: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_ok.get(host, 0.0))
            self._next_ok[host] = slot + self.min_interval
        delay = slot - now
        if delay > 0:
            time.sleep(delay)


class PoliteClient:
    def __init__(
        self,
        client: httpx.Client | None = None,
        min_interval: float = 0.25,
        retries: int = 2,
        backoff: float = 1.0,
    ):
        self.client = client or make_client()
        self.limiter = HostRateLimiter(min_interval)
        self.retries = retries
        self.backoff = backoff

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Return the response for any non-transient status (including 404).
        Raise TransientError if every attempt hit a timeout, network error, 429, or 5xx."""
        host = urlsplit(url).netloc
        last = "unknown error"
        for attempt in range(self.retries + 1):
            self.limiter.wait(host)
            try:
                resp = self.client.request(method, url, **kwargs)
            except httpx.TransportError as e:
                last = f"{type(e).__name__}: {e}"
            else:
                if resp.status_code not in RETRY_STATUSES:
                    return resp
                last = f"HTTP {resp.status_code}"
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    time.sleep(min(int(retry_after), 30))
            if attempt < self.retries:
                time.sleep(self.backoff * (2**attempt))
        log.debug("giving up on request", extra={"url": url, "reason": last})
        raise TransientError(f"{method} {url}: {last}")

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
