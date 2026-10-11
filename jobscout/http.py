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


# Hosts that want a slower pace than the default. Workable answered HTTP 429 to
# about 45 of 114 companies on the first real run at 4 requests/second.
HOST_INTERVALS = {"apply.workable.com": 1.5}
MAX_INTERVAL = 10.0


class HostRateLimiter:
    """Enforces a minimum gap between requests to the same host, across threads.

    Each host starts at its configured pace; a 429 from a host doubles its gap
    (up to MAX_INTERVAL) for the rest of the run, so we back off instead of
    hammering a server that already said slow down.
    """

    def __init__(self, min_interval: float = 0.25, host_intervals: dict[str, float] | None = None):
        self.enabled = min_interval > 0
        self.min_interval = min_interval
        self.intervals: dict[str, float] = dict(
            HOST_INTERVALS if host_intervals is None else host_intervals
        )
        self._next_ok: dict[str, float] = {}
        self._lock = threading.Lock()

    def interval(self, host: str) -> float:
        return max(self.min_interval, self.intervals.get(host, 0.0))

    def wait(self, host: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_ok.get(host, 0.0))
            self._next_ok[host] = slot + self.interval(host)
        delay = slot - now
        if delay > 0:
            time.sleep(delay)

    def slow_down(self, host: str, pause: float = 0.0) -> float:
        """Double this host's gap and hold every thread off it for `pause` seconds."""
        if not self.enabled:
            return 0.0
        with self._lock:
            new = min(MAX_INTERVAL, self.interval(host) * 2)
            self.intervals[host] = new
            self._next_ok[host] = max(self._next_ok.get(host, 0.0), time.monotonic() + pause)
        log.info("slowing down", extra={"host": host, "interval_s": new})
        return new


class PoliteClient:
    def __init__(
        self,
        client: httpx.Client | None = None,
        min_interval: float = 0.25,
        retries: int = 3,
        backoff: float = 1.0,
        host_intervals: dict[str, float] | None = None,
    ):
        self.client = client or make_client()
        self.limiter = HostRateLimiter(min_interval, host_intervals)
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
                if resp.status_code == 429 and attempt < self.retries:
                    retry_after = resp.headers.get("Retry-After", "")
                    pause = (
                        min(int(retry_after), 60)
                        if retry_after.isdigit()
                        else self.backoff * 4 * (2**attempt)
                    )
                    self.limiter.slow_down(host, pause)
                    continue  # the limiter now holds this host off for `pause`
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
