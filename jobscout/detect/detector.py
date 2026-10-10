"""ATS detection: figure out where each watchlist company posts its jobs.

For each company:
  1. If the watchlist has a Board URL override, that wins. Parse it, verify it
     when the ATS has a public API, done.
  2. Otherwise guess slugs from the company name and probe every public ATS
     (hinted ATS first). Stop early on a confirmed hit.
  3. Score each hit's confidence, pick the best, and save the full trail.

Confidence:
  confirmed  the board's own name matches the company (or it's a manual override)
  likely     strong slug match, but the ATS doesn't tell us the company name
  review     a hit that might be a different company with a similar name
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from jobscout.config import ConfigError
from jobscout.detect.probers import PROBERS, VERIFIERS, Probe, safe_probe
from jobscout.detect.slugs import _SUFFIXES, slug_candidates
from jobscout.detect.urls import parse_board_url
from jobscout.http import PoliteClient

log = logging.getLogger(__name__)

# Watchlist ATS values that point at something we can't auto-detect without a URL
NEEDS_URL_HINTS = {"workday", "icims", "rippling", "company careers site", "custom"}
_CONF_RANK = {"confirmed": 0, "likely": 1, "review": 2}


@dataclass
class DetectionResult:
    company: str
    status: str  # found, override, not_found, needs_url, error
    ats: str | None = None
    token: str | None = None
    confidence: str | None = None
    job_count: int | None = None
    message: str = ""
    probes: list[Probe] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


def _norm_words(s: str) -> set[str]:
    s = re.sub(r"\(.*?\)", " ", s.lower()).replace("&", " and ")
    return {w for w in re.findall(r"[a-z0-9]+", s) if w not in _SUFFIXES and w != "and"}


def name_matches(company: str, board_name: str) -> bool:
    """True when the board's name plausibly belongs to this company."""
    names = [company] + re.findall(r"\((.*?)\)", company)
    b = _norm_words(board_name)
    if not b:
        return False
    b_joined = "".join(sorted(b))
    for n in names:
        c = _norm_words(n.replace("formerly", ""))
        # Strict on purpose: "Polly" vs "Polly Pocket Toys" is a different company.
        # A miss isn't a rejection, it just lands in the review pile.
        if c and (c == b or "".join(sorted(c)) == b_joined):
            return True
    return False


def confidence_for(company: str, probe: Probe) -> str:
    if probe.board_name:
        return "confirmed" if name_matches(company, probe.board_name) else "review"
    full = re.sub(r"[^a-z0-9]", "", re.sub(r"\(.*?\)", "", company.lower()))
    slug = probe.slug.replace("-", "")
    # Without a name to check, only trust distinctive slugs that match the whole name
    if slug == full and len(full) >= 5:
        return "likely"
    return "review"


# ---------------------------------------------------------------------------
# Detection for one company
# ---------------------------------------------------------------------------


def _probe_order(hint: str | None) -> list[str]:
    order = list(PROBERS)
    if hint and hint.lower() in PROBERS:
        order.remove(hint.lower())
        order.insert(0, hint.lower())
    return order


def _from_override(http: PoliteClient, company: str, url: str) -> DetectionResult:
    try:
        ref = parse_board_url(url)
    except ConfigError as e:
        return DetectionResult(company, "error", message=str(e))

    verifier = VERIFIERS.get(ref.ats)
    if verifier is None:
        return DetectionResult(
            company, "override", ref.ats, ref.token, "confirmed",
            message=f"{ref.ats} board from override (verified when collected)",
        )
    probe = safe_probe(verifier, http, ref.ats, ref.token)
    if probe.error:
        return DetectionResult(company, "error", ref.ats, ref.token, message=probe.error,
                               probes=[probe])
    if not probe.found:
        return DetectionResult(
            company, "override", ref.ats, ref.token, "review", probes=[probe],
            message="Board URL override didn't answer; check the URL",
        )
    return DetectionResult(company, "override", ref.ats, ref.token, "confirmed",
                           probe.job_count, "verified override", [probe])


def detect_company(
    http: PoliteClient, company: str, ats_hint: str | None = None, board_url: str | None = None
) -> DetectionResult:
    if board_url:
        return _from_override(http, company, board_url)

    slugs = slug_candidates(company)
    probes: list[Probe] = []
    hits: list[tuple[str, Probe]] = []

    for ats in _probe_order(ats_hint):
        for slug in slugs:
            p = safe_probe(PROBERS[ats], http, ats, slug)
            probes.append(p)
            if p.found:
                hits.append((confidence_for(company, p), p))
                break  # one hit per ATS is enough
        if hits and hits[-1][0] == "confirmed":
            break  # stop early, no need to probe the rest

    if hits:
        hint = (ats_hint or "").lower()
        hits.sort(key=lambda h: (_CONF_RANK[h[0]], h[1].ats != hint, -(h[1].job_count or 0)))
        conf, best = hits[0]
        others = [f"{p.ats}:{p.slug}" for _, p in hits[1:]]
        msg = f"{best.ats}/{best.slug}" + (f" (also matched {', '.join(others)})" if others else "")
        if best.board_name:
            msg += f", board name {best.board_name!r}"
        return DetectionResult(company, "found", best.ats, best.slug, conf, best.job_count,
                               msg, probes)

    errors = [p for p in probes if p.error]
    if errors:
        return DetectionResult(
            company, "error", probes=probes,
            message=f"{len(errors)} probe(s) failed, will retry next run: {errors[0].error}",
        )

    hint = (ats_hint or "").strip().lower()
    if hint in NEEDS_URL_HINTS:
        return DetectionResult(
            company, "needs_url", hint, probes=probes,
            message=f"Watchlist says {ats_hint}. Paste the careers page URL into Board URL.",
        )
    return DetectionResult(
        company, "not_found", probes=probes,
        message=f"No public board found for slugs {', '.join(slugs[:4])}. "
                "Paste the careers page URL into Board URL.",
    )


# ---------------------------------------------------------------------------
# Batch detection against the database
# ---------------------------------------------------------------------------


def companies_to_detect(
    conn: sqlite3.Connection,
    refresh: bool = False,
    stale_days: int = 7,
    names: list[str] | None = None,
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM companies WHERE active = 1"
    params: list = []
    if names:
        sql += f" AND lower(name) IN ({', '.join('?' * len(names))})"
        params += [n.lower() for n in names]
    elif not refresh:
        sql += (
            " AND (detected_at IS NULL OR detect_status IS NULL OR detect_status = 'error'"
            " OR detected_at < datetime('now', ?))"
        )
        params.append(f"-{stale_days} days")
    sql += " ORDER BY tier, name"
    return conn.execute(sql, params).fetchall()


def save_result(conn: sqlite3.Connection, row: sqlite3.Row, r: DetectionResult) -> bool:
    """Write a result. Returns True if the company's ATS changed from a previous value."""
    changed = bool(
        row["ats"] and r.ats and r.status in {"found", "override"}
        and (row["ats"], row["ats_token"]) != (r.ats, r.token)
    )
    if changed:
        conn.execute(
            "INSERT INTO ats_changes (company_id, old_ats, old_token, new_ats, new_token)"
            " VALUES (?, ?, ?, ?, ?)",
            (row["id"], row["ats"], row["ats_token"], r.ats, r.token),
        )
        log.warning("ATS changed", extra={"company": r.company, "old": row["ats"], "new": r.ats})

    keep_old = r.status == "error" and row["ats"]  # don't wipe a good answer over a blip
    detail = json.dumps(
        {"message": r.message, "probes": [asdict(p) for p in r.probes]}, default=str
    )
    conn.execute(
        """UPDATE companies SET
               ats = ?, ats_token = ?, detect_status = ?, detect_confidence = ?,
               job_count = ?, detect_detail = ?, detected_at = ?, updated_at = datetime('now')
           WHERE id = ?""",
        (
            row["ats"] if keep_old else r.ats,
            row["ats_token"] if keep_old else r.token,
            r.status,
            row["detect_confidence"] if keep_old else r.confidence,
            row["job_count"] if keep_old else r.job_count,
            detail,
            datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            row["id"],
        ),
    )
    return changed


def run_detection(
    conn: sqlite3.Connection,
    http: PoliteClient,
    rows: list[sqlite3.Row],
    workers: int = 6,
    on_result=None,
) -> list[DetectionResult]:
    """Detect in parallel (the per-host rate limiter keeps it polite), save serially."""

    def work(row):
        return row, detect_company(http, row["name"], row["ats_hint"], row["board_url"])

    results = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for row, result in pool.map(work, rows):
            save_result(conn, row, result)
            results.append(result)
            if on_result:
                on_result(result)
    return results
