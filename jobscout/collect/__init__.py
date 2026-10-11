"""Collectors: pull open postings from each company's job board (E2)."""

from jobscout.collect import boards, workday  # noqa: F401  (registers collectors)
from jobscout.collect.base import COLLECTORS, CollectorError, RawPosting

__all__ = ["COLLECTORS", "CollectorError", "RawPosting"]
