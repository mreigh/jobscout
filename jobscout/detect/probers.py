"""One prober per ATS with a public, unauthenticated job board API.

Each prober answers: "does board <slug> exist on this ATS, and if so, what's it
called and how many jobs does it have?" A 404 means no. Timeouts, 429s, and 5xx
raise TransientError (from PoliteClient) so they're never mistaken for a no.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from jobscout.detect.urls import workday_api_url
from jobscout.http import PoliteClient, TransientError


@dataclass
class Probe:
    ats: str
    slug: str
    found: bool
    board_name: str | None = None
    job_count: int | None = None
    error: str | None = None


def _json(resp):
    try:
        return resp.json()
    except ValueError:
        return None


def probe_greenhouse(http: PoliteClient, slug: str) -> Probe:
    base = f"https://boards-api.greenhouse.io/v1/boards/{slug}"
    resp = http.get(base)
    data = _json(resp)
    if resp.status_code != 200 or not isinstance(data, dict) or "name" not in data:
        return Probe("greenhouse", slug, False)
    jobs = _json(http.get(f"{base}/jobs")) or {}
    count = (jobs.get("meta") or {}).get("total")
    if count is None and isinstance(jobs.get("jobs"), list):
        count = len(jobs["jobs"])
    return Probe("greenhouse", slug, True, data.get("name"), count)


def probe_lever(http: PoliteClient, slug: str) -> Probe:
    resp = http.get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"})
    data = _json(resp)
    if resp.status_code != 200 or not isinstance(data, list):
        return Probe("lever", slug, False)
    # Lever's API doesn't return the company name.
    return Probe("lever", slug, True, None, len(data))


def probe_ashby(http: PoliteClient, slug: str) -> Probe:
    resp = http.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    data = _json(resp)
    if resp.status_code != 200 or not isinstance(data, dict) or not isinstance(
        data.get("jobs"), list
    ):
        return Probe("ashby", slug, False)
    return Probe("ashby", slug, True, None, len(data["jobs"]))


def probe_smartrecruiters(http: PoliteClient, slug: str) -> Probe:
    resp = http.get(
        f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", params={"limit": 1}
    )
    data = _json(resp)
    # SmartRecruiters answers 200 with zero results for companies that don't exist,
    # so an empty board can't be told apart from no board. Require at least one posting.
    if resp.status_code != 200 or not isinstance(data, dict) or not data.get("totalFound"):
        return Probe("smartrecruiters", slug, False)
    content = data.get("content") or [{}]
    name = (content[0].get("company") or {}).get("name")
    return Probe("smartrecruiters", slug, True, name, data["totalFound"])


def probe_workable(http: PoliteClient, slug: str) -> Probe:
    resp = http.get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
    data = _json(resp)
    if resp.status_code != 200 or not isinstance(data, dict) or "jobs" not in data:
        return Probe("workable", slug, False)
    jobs = data.get("jobs") or []
    return Probe("workable", slug, True, data.get("name"), len(jobs))


def probe_workday(http: PoliteClient, token: str) -> Probe:
    resp = http.post(
        workday_api_url(token),
        json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
    )
    data = _json(resp)
    if resp.status_code != 200 or not isinstance(data, dict) or "total" not in data:
        return Probe("workday", token, False)
    return Probe("workday", token, True, None, data.get("total"))


PROBERS: dict[str, Callable[[PoliteClient, str], Probe]] = {
    "greenhouse": probe_greenhouse,
    "lever": probe_lever,
    "ashby": probe_ashby,
    "smartrecruiters": probe_smartrecruiters,
    "workable": probe_workable,
}
VERIFIERS = {**PROBERS, "workday": probe_workday}


def safe_probe(fn, http: PoliteClient, ats: str, slug: str) -> Probe:
    try:
        return fn(http, slug)
    except TransientError as e:
        return Probe(ats, slug, False, error=str(e))
