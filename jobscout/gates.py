"""Hard gates (R1): deterministic rules that keep bulk away from the user.

Every open posting gets a verdict stored in jobs.filter_result: 'pass', or the
rule that killed it ("location:non-us", "pay:below-floor", "title:sales executive").
The default views show only 'pass'; --all shows everything with its reason.

Philosophy: a gate fails a posting only on positive evidence the user would
reject it on sight. A maybe (unknown location, unstated pay) passes, and the
scorer sorts it out later. Decisions encoded here, in the user's words
(Requirements Audit, Oct 11): US remote always; onsite/hybrid only within the
Milwaukee metro ("madison and chicago onsites should be excluded, not
travelling that far"); $120k floor with unstated pay still shown; quota sales
and early-career out; mainframe roles merged into the one list.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter

from jobscout.config import FiltersConfig

# --- Location evidence ------------------------------------------------------

US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV",
    "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN",
    "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}

# Office codes the big Workday tenants use (FIS style), matched as exact uppercase tokens
FOREIGN_CODES = {
    "IND", "GBR", "POL", "JPN", "TUN", "SGP", "AUS", "BRA", "CHE", "PHL", "DEU", "FRA",
    "CAN", "MEX", "NLD", "ESP", "ITA", "IRL", "ISR", "ARE", "CHN", "HKG", "KOR", "THA",
    "MYS", "IDN", "VNM", "EGY", "ZAF", "COL", "ARG", "CHL", "CRI", "SRB", "ROU", "BGR",
    "PRT", "AUT", "BEL", "SWE", "NOR", "DNK", "FIN", "CZE", "SVK", "HUN", "UKR", "LTU",
    "LVA", "EST", "GRC", "TUR", "NZL", "LUX", "CYP", "SAU", "QAT", "PAK", "BGD", "LKA",
    "TWN", "MAC", "MAR", "NGA", "KEN", "UK",
}

# Country, province, and well-known foreign city names, matched on word boundaries
FOREIGN_WORDS = (
    "india", "united kingdom", "poland", "japan", "tunisia", "singapore", "australia",
    "brazil", "switzerland", "philippines", "germany", "france", "canada", "mexico",
    "netherlands", "spain", "italy", "ireland", "israel", "china", "hong kong", "korea",
    "thailand", "malaysia", "indonesia", "vietnam", "egypt", "colombia", "argentina",
    "chile", "costa rica", "serbia", "romania", "bulgaria", "portugal", "austria",
    "belgium", "sweden", "norway", "denmark", "finland", "czech", "slovakia", "hungary",
    "ukraine", "lithuania", "latvia", "estonia", "greece", "turkey",
    "london", "bangalore", "bengaluru", "pune", "chennai", "mumbai", "hyderabad", "noida",
    "tokyo", "warsaw", "sydney", "melbourne", "toronto", "vancouver", "montreal",
    "ontario", "quebec", "alberta", "british columbia", "nova scotia", "manitoba",
    "dublin", "berlin", "frankfurt", "paris", "madrid", "barcelona", "amsterdam",
    "zurich", "geneva", "manila", "sao paulo", "tel aviv", "dubai",
    "cyprus", "nicosia", "lisbon", "porto", "glasgow", "edinburgh", "mississauga",
    "ottawa", "calgary", "winnipeg", "prague", "krakow", "gdansk", "bratislava",
    "budapest", "bucharest", "sofia", "belgrade", "athens", "istanbul", "cairo",
    "nairobi", "lagos", "johannesburg", "cape town", "karachi", "dhaka", "colombo",
    "taipei", "osaka", "bangkok", "jakarta", "kuala lumpur", "hanoi", "auckland", "baden",
)
_FOREIGN_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in FOREIGN_WORDS) + r")\b")
_US_RE = re.compile(r"\b(usa|united states|u\.s\.)\b")

# Metro name (as used in filters.yaml hybrid_metros) -> markers for that metro
METRO_MARKERS = {
    "milwaukee": ("milwaukee", "mke", "wauwatosa", "brookfield", "waukesha", "glendale",
                  "west allis", "menomonee falls"),
    "madison": ("madison",),
    "chicago": ("chicago",),
}

# A description rescues a city-headed posting only with a POSITIVE remote phrase.
# A bare "remote" is not enough: onsite JDs mention remote teams, remote Fridays,
# even "this role is not remote" (the Qualia Austin leak).
_REMOTE_DESC_RE = re.compile(
    r"remote eligible|remote[- ]first|fully remote|100% remote|work remotely"
    r"|work from home|work from anywhere|remote position|remote role"
    r"|remote within the|us[- ]remote|remote[,-] ?us\b", re.I)

# Large US hub cities count as a specific place even without a state code
# (the "Atlanta" / "Austin, TX" leaks from the Oct 11 pass list)
_US_CITY_RE = re.compile(
    r"\b(new york|nyc|san francisco|seattle|boston|denver|atlanta|austin|dallas|houston"
    r"|charlotte|chicago|jacksonville|phoenix|columbus|minneapolis|st\.? louis|kansas city"
    r"|salt lake|tampa|orlando|pittsburgh|cincinnati|cleveland|detroit|nashville|raleigh"
    r"|richmond|baltimore|philadelphia|los angeles|san diego|san jose|portland|sacramento"
    r"|las vegas|san antonio|miami|washington|omaha)\b", re.I)


def _tokens(*texts: str | None) -> set[str]:
    out: set[str] = set()
    for t in texts:
        if t:
            out.update(re.split(r"[^A-Za-z]+", t))
    return out - {""}


def _location_verdict(location, url, description, remote, filters: FiltersConfig) -> str:
    """'pass' or a location reason. Unknowns pass: the gate only kills clear rejects."""
    text = " ".join(x for x in (location, url) if x)
    low = text.lower()
    toks = _tokens(text)

    foreign = bool(toks & FOREIGN_CODES) or bool(_FOREIGN_RE.search(low))
    # State codes alone are weak evidence: FIS office strings use "FL" for "floor"
    # ("GBR LNDN 25 Walbrook FL5"), so against a foreign marker only an explicit
    # US/USA/United States counts.
    us_strong = "US" in toks or "USA" in toks or bool(_US_RE.search(low))
    if foreign and not us_strong:
        return "location:non-us"

    if remote is True:
        return "pass"

    metros: tuple[str, ...] = ()
    for name in filters.location.hybrid_metros:
        metros += METRO_MARKERS.get(name.lower(), (name.lower(),))
    commutable = any(m in low for m in metros) or ("MKE" in toks and "milwaukee" in metros)

    if commutable:
        return "pass"
    if description and _REMOTE_DESC_RE.search(description):
        return "pass"  # the body says remote even though the header names a city

    # Positive evidence of a specific, non-commutable place with no remote signal
    has_place = (bool(toks & US_STATE_CODES) or bool(_US_RE.search(low)) or foreign
                 or bool(_US_CITY_RE.search(low)))
    if remote is False and text:
        return "location:not-commutable"
    if has_place:
        return "location:not-commutable"
    return "pass"  # "3 Locations", blank, or otherwise unknown


def classify(title, location, url, description, remote, comp_min, comp_max,
             filters: FiltersConfig) -> str:
    """One posting's gate verdict: 'pass' or the first rule that kills it."""
    t = (title or "").lower()
    for kw in filters.titles.exclude_keywords:
        if kw.lower() in t:
            return f"title:{kw.lower()}"
    inc = filters.titles.include_keywords
    if inc and not any(kw.lower() in t for kw in inc):
        return "lane:no-match"

    top = comp_max or comp_min
    if top is not None and top < filters.comp.floor_usd:
        return "pay:below-floor"

    if description:
        d = description.lower()
        for phrase in filters.exclusions.description_phrases:
            if phrase.lower() in d:
                return f"phrase:{phrase.lower()}"

    return _location_verdict(location, url, description, remote, filters)


def apply_gates(conn: sqlite3.Connection, filters: FiltersConfig) -> Counter:
    """(Re)grade every open posting. Cheap and idempotent; run after every collect
    and after any filters.yaml change. Returns a Counter of verdicts."""
    rows = conn.execute(
        "SELECT id, title, location, url, description, remote, comp_min, comp_max,"
        " filter_result FROM jobs WHERE closed_at IS NULL"
    ).fetchall()
    verdicts: Counter = Counter()
    conn.execute("BEGIN")
    try:
        for r in rows:
            remote = None if r["remote"] is None else bool(r["remote"])
            v = classify(r["title"], r["location"], r["url"], r["description"], remote,
                         r["comp_min"], r["comp_max"], filters)
            verdicts[v] += 1
            if v != r["filter_result"]:
                conn.execute("UPDATE jobs SET filter_result = ? WHERE id = ?", (v, r["id"]))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return verdicts
