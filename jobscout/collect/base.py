"""The shape every collector returns, plus the registry of collectors by ATS."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RawPosting:
    """One open job as a source reported it, lightly normalized.

    Collectors fill what their source provides and leave the rest None.
    `payload` keeps the source's original record for replay (JS-043).
    """

    source: str                     # greenhouse, lever, ashby, workable, smartrecruiters, workday
    external_id: str                # the source's own id; unique within one company's board
    title: str
    url: str | None = None
    location: str | None = None
    remote: bool | None = None      # True remote, False onsite/hybrid, None unknown
    department: str | None = None
    description: str | None = None  # plain text
    posted_at: str | None = None    # ISO date (YYYY-MM-DD) when known
    comp_min: int | None = None     # annual USD
    comp_max: int | None = None
    comp_source: str | None = None  # 'ats' or 'text'
    payload: dict[str, Any] = field(default_factory=dict)


class CollectorError(Exception):
    """The board answered, but not in a shape we understand (or not at all)."""


# collector(http, board_token, known=frozenset of external ids already stored) -> postings
Collector = Callable[..., list[RawPosting]]
COLLECTORS: dict[str, Collector] = {}


def register(ats: str):
    def deco(fn: Collector) -> Collector:
        COLLECTORS[ats] = fn
        return fn

    return deco
