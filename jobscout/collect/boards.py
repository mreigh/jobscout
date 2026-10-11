"""Collectors for the ATSs with public JSON job board APIs.

Each takes the board token found by detection (E1) and returns every open posting.
A non-200 answer raises CollectorError so the company is marked failed for this
run and none of its jobs are wrongly closed.
"""

from __future__ import annotations

from jobscout.collect.base import CollectorError, RawPosting, register
from jobscout.collect.text import html_to_text, iso_date, remote_from, salary_from_text
from jobscout.http import PoliteClient


def _get_json(http: PoliteClient, url: str, **kwargs):
    resp = http.get(url, **kwargs)
    if resp.status_code != 200:
        raise CollectorError(f"GET {url} answered HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as e:
        raise CollectorError(f"GET {url} did not return JSON") from e


def _with_text_comp(p: RawPosting) -> RawPosting:
    """Fill comp from the description when the ATS didn't give it structured."""
    if p.comp_min is None:
        rng = salary_from_text(p.description)
        if rng:
            p.comp_min, p.comp_max, p.comp_source = rng[0], rng[1], "text"
    return p


# --- Greenhouse -------------------------------------------------------------


@register("greenhouse")
def collect_greenhouse(http: PoliteClient, token: str, known: frozenset[str] = frozenset()
                 ) -> list[RawPosting]:
    data = _get_json(http, f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
                     params={"content": "true"})
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise CollectorError("Greenhouse response had no jobs list")
    out = []
    for j in data["jobs"]:
        loc = (j.get("location") or {}).get("name")
        depts = [d.get("name") for d in j.get("departments") or [] if d.get("name")]
        desc = html_to_text(j.get("content"))
        out.append(_with_text_comp(RawPosting(
            source="greenhouse",
            external_id=str(j["id"]),
            title=j.get("title") or "",
            url=j.get("absolute_url"),
            location=loc,
            remote=remote_from(loc),
            department=", ".join(depts) or None,
            description=desc,
            posted_at=iso_date(j.get("first_published") or j.get("updated_at")),
            payload=j,
        )))
    return out


# --- Lever ------------------------------------------------------------------


@register("lever")
def collect_lever(http: PoliteClient, token: str, known: frozenset[str] = frozenset()
                 ) -> list[RawPosting]:
    data = _get_json(http, f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"})
    if not isinstance(data, list):
        raise CollectorError("Lever response was not a list")
    out = []
    for j in data:
        cats = j.get("categories") or {}
        loc = cats.get("location")
        parts = [j.get("descriptionPlain")]
        for section in j.get("lists") or []:
            parts.append(section.get("text"))
            parts.append(html_to_text(section.get("content")))
        parts.append(j.get("additionalPlain"))
        desc = "\n\n".join(p for p in parts if p) or None
        workplace = j.get("workplaceType")
        p = RawPosting(
            source="lever",
            external_id=str(j["id"]),
            title=j.get("text") or "",
            url=j.get("hostedUrl"),
            location=loc,
            remote=True if workplace == "remote" else False if workplace in ("hybrid", "onsite")
            else remote_from(loc),
            department=cats.get("team") or cats.get("department"),
            description=desc,
            posted_at=iso_date(j.get("createdAt")),
            payload=j,
        )
        sal = j.get("salaryRange") or {}
        yearly = "year" in (sal.get("interval") or "")
        if sal.get("currency") == "USD" and yearly and sal.get("min"):
            lo = int(sal["min"])
            p.comp_min, p.comp_max, p.comp_source = lo, int(sal.get("max") or lo), "ats"
        out.append(_with_text_comp(p))
    return out


# --- Ashby ------------------------------------------------------------------


def _ashby_comp(job: dict) -> tuple[int, int] | None:
    for c in ((job.get("compensation") or {}).get("summaryComponents") or []):
        if (
            c.get("compensationType") == "Salary"
            and c.get("currencyCode") == "USD"
            and "YEAR" in (c.get("interval") or "").upper()
            and c.get("minValue")
        ):
            return int(c["minValue"]), int(c.get("maxValue") or c["minValue"])
    return None


@register("ashby")
def collect_ashby(http: PoliteClient, token: str, known: frozenset[str] = frozenset()
                 ) -> list[RawPosting]:
    data = _get_json(http, f"https://api.ashbyhq.com/posting-api/job-board/{token}",
                     params={"includeCompensation": "true"})
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise CollectorError("Ashby response had no jobs list")
    out = []
    for j in data["jobs"]:
        if j.get("isListed") is False:
            continue
        loc = j.get("location")
        workplace = (j.get("workplaceType") or "").lower()
        remote = (
            True if j.get("isRemote") or workplace == "remote"
            else False if workplace in ("hybrid", "onsite")
            else remote_from(loc)
        )
        p = RawPosting(
            source="ashby",
            external_id=str(j["id"]),
            title=j.get("title") or "",
            url=j.get("jobUrl"),
            location=loc,
            remote=remote,
            department=j.get("department") or j.get("team"),
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
            posted_at=iso_date(j.get("publishedAt")),
            payload=j,
        )
        comp = _ashby_comp(j)
        if comp:
            p.comp_min, p.comp_max, p.comp_source = comp[0], comp[1], "ats"
        out.append(_with_text_comp(p))
    return out


# --- Workable ---------------------------------------------------------------


@register("workable")
def collect_workable(http: PoliteClient, token: str, known: frozenset[str] = frozenset()
                 ) -> list[RawPosting]:
    data = _get_json(http, f"https://apply.workable.com/api/v1/widget/accounts/{token}",
                     params={"details": "true"})
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise CollectorError("Workable response had no jobs list")
    out = []
    for j in data["jobs"]:
        loc = ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x) or None
        out.append(_with_text_comp(RawPosting(
            source="workable",
            external_id=str(j.get("shortcode") or j.get("id")),
            title=j.get("title") or "",
            url=j.get("url") or j.get("shortlink"),
            location=loc,
            remote=True if j.get("telecommuting") else remote_from(loc),
            department=j.get("department"),
            description=html_to_text(j.get("description")),
            posted_at=iso_date(j.get("published_on") or j.get("created_at")),
            payload=j,
        )))
    return out


# --- SmartRecruiters ----------------------------------------------------------


@register("smartrecruiters")
def collect_smartrecruiters(http: PoliteClient, token: str, known: frozenset[str] = frozenset()
                 ) -> list[RawPosting]:
    out, offset, total = [], 0, None
    while total is None or offset < total:
        data = _get_json(http, f"https://api.smartrecruiters.com/v1/companies/{token}/postings",
                         params={"limit": 100, "offset": offset})
        if not isinstance(data, dict) or not isinstance(data.get("content"), list):
            raise CollectorError("SmartRecruiters response had no content list")
        total = data.get("totalFound") or 0
        for j in data["content"]:
            loc_d = j.get("location") or {}
            bits = (loc_d.get("city"), loc_d.get("region"), loc_d.get("country"))
            loc = ", ".join(x for x in bits if x) or None
            out.append(RawPosting(
                source="smartrecruiters",
                external_id=str(j["id"]),
                title=j.get("name") or "",
                url=f"https://jobs.smartrecruiters.com/{token}/{j['id']}",
                location=loc,
                remote=True if loc_d.get("remote") else remote_from(loc),
                department=(j.get("department") or {}).get("label"),
                posted_at=iso_date(j.get("releasedDate")),
                payload=j,
            ))
        if not data["content"]:
            break
        offset += len(data["content"])
    return out
