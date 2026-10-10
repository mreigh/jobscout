"""Parse a careers-page URL someone pasted into the watchlist into a board reference.

Supported:
    https://boards.greenhouse.io/acme             (also job-boards.greenhouse.io)
    https://jobs.lever.co/acme
    https://jobs.ashbyhq.com/acme
    https://apply.workable.com/acme
    https://careers.smartrecruiters.com/Acme      (also jobs.smartrecruiters.com)
    https://acme.wd5.myworkdayjobs.com/en-US/External
    https://careers-acme.icims.com/jobs
    https://ats.rippling.com/acme/jobs
Anything else becomes ats="custom" and is handled by the generic page collector (E2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from jobscout.config import ConfigError


@dataclass(frozen=True)
class BoardRef:
    ats: str
    token: str  # board slug; for workday "tenant|wdN|site"; for icims/custom the host or URL
    url: str


_LOCALE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")


def _first_segment(path: str) -> str | None:
    parts = [p for p in path.split("/") if p]
    return parts[0] if parts else None


def parse_board_url(raw: str) -> BoardRef:
    url = raw.strip()
    if not re.match(r"^https?://", url):
        url = "https://" + url
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host or "." not in host:
        raise ConfigError(f"Board URL doesn't look like a web address: {raw!r}")
    path = parts.path

    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io", "boards-api.greenhouse.io"}:
        segs = [p for p in path.split("/") if p]
        if host == "boards-api.greenhouse.io" and len(segs) >= 3:
            slug = segs[2]  # /v1/boards/<slug>/jobs
        else:
            slug = segs[0] if segs else None
        if slug:
            return BoardRef("greenhouse", slug, url)

    if host == "jobs.lever.co" and (slug := _first_segment(path)):
        return BoardRef("lever", slug, url)

    if host == "jobs.ashbyhq.com" and (slug := _first_segment(path)):
        return BoardRef("ashby", slug, url)

    if host == "apply.workable.com" and (slug := _first_segment(path)):
        return BoardRef("workable", slug, url)

    if host in {"careers.smartrecruiters.com", "jobs.smartrecruiters.com"} and (
        slug := _first_segment(path)
    ):
        return BoardRef("smartrecruiters", slug, url)

    m = re.match(r"^([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com$", host)
    if m:
        tenant, pod = m.groups()
        segs = [p for p in path.split("/") if p and not _LOCALE.match(p)]
        if not segs:
            raise ConfigError(
                f"Workday URL needs the site name after the domain, e.g. "
                f"https://{host}/External (got {raw!r})"
            )
        return BoardRef("workday", f"{tenant}|{pod}|{segs[0]}", url)

    if host.endswith(".icims.com"):
        return BoardRef("icims", host, url)

    if host == "ats.rippling.com" and (slug := _first_segment(path)):
        return BoardRef("rippling", slug, url)

    return BoardRef("custom", url, url)


def workday_api_url(token: str) -> str:
    tenant, pod, site = token.split("|")
    return f"https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
