"""Workday collector.

Workday career sites expose a JSON search API behind every *.myworkdayjobs.com
board. The list call pages 20 postings at a time and carries only title, location
and a "Posted N Days Ago" label; the description needs one more call per posting.

Big tenants (FIS, Fiserv) carry hundreds of openings, so descriptions are only
fetched for postings we haven't seen before. Known postings come back with the
list fields alone, which is enough to mark them still open.
"""

from __future__ import annotations

from jobscout.collect.base import CollectorError, RawPosting, register
from jobscout.collect.text import html_to_text, remote_from, salary_from_text, workday_posted
from jobscout.http import PoliteClient

PAGE = 20              # Workday rejects larger pages on many tenants
MAX_PAGES = 100        # 2,000 postings: a safety stop, not a real limit
MAX_DETAILS = 400      # description fetches per company per run


def _parts(token: str) -> tuple[str, str, str]:
    try:
        tenant, pod, site = token.split("|")
    except ValueError as e:
        raise CollectorError(f"Workday token should be tenant|wdN|site, got {token!r}") from e
    return tenant, pod, site


@register("workday")
def collect_workday(http: PoliteClient, token: str, known: frozenset[str] = frozenset()
                    ) -> list[RawPosting]:
    tenant, pod, site = _parts(token)
    host = f"https://{tenant}.{pod}.myworkdayjobs.com"
    api = f"{host}/wday/cxs/{tenant}/{site}"

    listings, total, offset = [], None, 0
    for _ in range(MAX_PAGES):
        resp = http.post(f"{api}/jobs", json={"appliedFacets": {}, "limit": PAGE,
                                              "offset": offset, "searchText": ""})
        if resp.status_code != 200:
            raise CollectorError(f"Workday search answered HTTP {resp.status_code}")
        data = resp.json()
        page = data.get("jobPostings") or []
        if total is None:
            total = data.get("total") or 0  # only the first page reports the total
        listings.extend(page)
        offset += len(page)
        if not page or offset >= total:
            break

    out, details = [], 0
    for j in listings:
        path = j.get("externalPath")
        if not path:
            continue
        p = RawPosting(
            source="workday",
            external_id=path,
            title=j.get("title") or "",
            url=f"{host}/{site}{path}",
            location=j.get("locationsText"),
            remote=remote_from(j.get("locationsText"), j.get("remoteType")),
            posted_at=workday_posted(j.get("postedOn")),
            payload=j,
        )
        if path not in known and details < MAX_DETAILS:
            details += 1
            resp = http.get(f"{api}{path}")
            if resp.status_code == 200:
                info = (resp.json() or {}).get("jobPostingInfo") or {}
                p.description = html_to_text(info.get("jobDescription"))
                p.url = info.get("externalUrl") or p.url
                p.remote = remote_from(info.get("remoteType"), info.get("location"), p.location)
                p.payload = {"listing": j, "detail": info}
                rng = salary_from_text(p.description)
                if rng:
                    p.comp_min, p.comp_max, p.comp_source = rng[0], rng[1], "text"
        out.append(p)
    return out
