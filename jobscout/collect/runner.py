"""Collect every watchlist company whose job board we can read, and save the results."""

from __future__ import annotations

import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from jobscout.collect.base import COLLECTORS, CollectorError
from jobscout.http import PoliteClient, TransientError
from jobscout.jobs import SaveResult, known_ids, now, save_postings

log = logging.getLogger(__name__)


@dataclass
class CompanyCollection:
    company: str
    tier: str
    ats: str | None
    status: str                    # ok, error, unsupported, review
    saved: SaveResult | None = None
    error: str | None = None


def companies_to_collect(
    conn: sqlite3.Connection, names: list[str] | None = None, tiers: list[str] | None = None
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM companies WHERE active = 1"
    params: list = []
    if names:
        sql += f" AND lower(name) IN ({', '.join('?' * len(names))})"
        params += [n.lower() for n in names]
    if tiers:
        sql += f" AND tier IN ({', '.join('?' * len(tiers))})"
        params += [t.upper() for t in tiers]
    return conn.execute(sql + " ORDER BY tier, name", params).fetchall()


def _plan(row: sqlite3.Row) -> str:
    """'collect', or why not."""
    if row["detect_status"] not in ("found", "override") or not row["ats_token"]:
        return "unsupported"
    if row["ats"] not in COLLECTORS:
        return "unsupported"
    if row["detect_confidence"] == "review":
        return "review"  # might be another company's board; don't fill the list with noise
    return "collect"


def run_collection(
    conn: sqlite3.Connection,
    http: PoliteClient,
    rows: list[sqlite3.Row],
    run_id: int | None = None,
    workers: int = 6,
    on_result=None,
) -> list[CompanyCollection]:
    plans = [(r, _plan(r)) for r in rows]
    to_fetch = [r for r, plan in plans if plan == "collect"]
    known = {r["id"]: known_ids(conn, r["id"], r["ats"]) for r in to_fetch}

    def fetch(row):
        try:
            postings = COLLECTORS[row["ats"]](http, row["ats_token"], known=known[row["id"]])
            return row, postings, None
        except (CollectorError, TransientError) as e:
            return row, None, str(e)
        except Exception as e:  # noqa: BLE001  an unexpected shape shouldn't sink the whole run
            log.exception("collector crashed", extra={"company": row["name"]})
            return row, None, f"{type(e).__name__}: {e}"

    results: list[CompanyCollection] = []
    for row, plan in plans:
        if plan != "collect":
            r = CompanyCollection(row["name"], row["tier"], row["ats"], plan)
            _mark(conn, row["id"], plan, None, None)
            results.append(r)
            if on_result:
                on_result(r)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for row, postings, error in pool.map(fetch, to_fetch):
            if error:
                r = CompanyCollection(row["name"], row["tier"], row["ats"], "error", error=error)
                _mark(conn, row["id"], "error", error, row["open_jobs"])
            else:
                saved = save_postings(conn, row["id"], postings, run_id)
                r = CompanyCollection(row["name"], row["tier"], row["ats"], "ok", saved=saved)
                _mark(conn, row["id"], "ok", None, saved.open_count)
            results.append(r)
            if on_result:
                on_result(r)
    return results


def _mark(conn, company_id, status, detail, open_jobs) -> None:
    conn.execute(
        "UPDATE companies SET collected_at = ?, collect_status = ?, collect_detail = ?,"
        " open_jobs = ? WHERE id = ?",
        (now(), status, detail, open_jobs, company_id),
    )
