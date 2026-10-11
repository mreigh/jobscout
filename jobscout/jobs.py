"""Job storage and lifecycle (E4): one row per real job, tracked from first seen to closed.

    new       first time this posting shows up
    updated   title, location, pay, or description changed
    closed    a posting we had is gone from a board that answered fine this run
    reopened  a closed posting came back

Closing only ever happens after a SUCCESSFUL collection of that company's board:
a timeout or an error must never make every job at a company look closed.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime

from jobscout.collect.base import RawPosting


def now() -> str:
    """UTC timestamp in SQLite's own format, so datetime() comparisons just work."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def fingerprint(company_id: int, source: str, external_id: str) -> str:
    return hashlib.sha1(f"{company_id}|{source}|{external_id}".encode()).hexdigest()[:20]


def text_hash(text: str | None) -> str | None:
    return hashlib.sha1(text.encode()).hexdigest()[:16] if text else None


@dataclass
class SaveResult:
    new: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    reopened: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)
    unchanged: int = 0
    open_count: int = 0


def known_ids(conn: sqlite3.Connection, company_id: int, source: str) -> frozenset[str]:
    """External ids we already hold a description for (Workday skips re-fetching these)."""
    rows = conn.execute(
        "SELECT external_id FROM jobs WHERE company_id = ? AND source = ? AND closed_at IS NULL"
        " AND description IS NOT NULL",
        (company_id, source),
    ).fetchall()
    return frozenset(r[0] for r in rows)


_TRACKED = ("title", "location", "remote", "url", "department", "comp_min", "comp_max")


def save_postings(
    conn: sqlite3.Connection, company_id: int, postings: list[RawPosting], run_id: int | None = None
) -> SaveResult:
    """Upsert one company's full, successful collection and close what disappeared."""
    res = SaveResult()
    ts = now()
    seen: set[str] = set()

    conn.execute("BEGIN")
    try:
        for p in postings:
            fp = fingerprint(company_id, p.source, p.external_id)
            if fp in seen:
                continue  # a board listing the same posting twice
            seen.add(fp)
            row = conn.execute("SELECT * FROM jobs WHERE fingerprint = ?", (fp,)).fetchone()
            dhash = text_hash(p.description)

            if row is None:
                conn.execute(
                    """INSERT INTO jobs (fingerprint, company_id, source, external_id, title,
                           location, remote, comp_min, comp_max, comp_source, url, department,
                           description, description_hash, posted_at, first_seen_at,
                           last_seen_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (fp, company_id, p.source, p.external_id, p.title, p.location,
                     _bool(p.remote), p.comp_min, p.comp_max, p.comp_source, p.url, p.department,
                     p.description, dhash, p.posted_at, ts, ts, ts),
                )
                _raw(conn, run_id, company_id, p)
                res.new.append(p.title)
                continue

            changes = {}
            for col in _TRACKED:
                val = _bool(p.remote) if col == "remote" else getattr(p, col)
                if val is not None and row[col] != val:
                    changes[col] = val
            if p.comp_min is not None and row["comp_source"] != p.comp_source:
                changes["comp_source"] = p.comp_source
            if dhash and dhash != row["description_hash"]:
                changes["description"] = p.description
                changes["description_hash"] = dhash
            if p.posted_at and not row["posted_at"]:
                changes["posted_at"] = p.posted_at

            reopened = row["closed_at"] is not None
            sets = {"last_seen_at": ts, **changes}
            if reopened:
                sets["closed_at"] = None
            # A description arriving for the first time (e.g. Workday detail) is not an "update"
            meaningful = {k for k in changes if k not in ("posted_at", "description_hash")}
            if row["description_hash"] is None:
                meaningful.discard("description")
            if meaningful:
                sets["updated_at"] = ts
            conn.execute(
                f"UPDATE jobs SET {', '.join(f'{c} = ?' for c in sets)} WHERE id = ?",
                [*sets.values(), row["id"]],
            )
            if changes:
                _raw(conn, run_id, company_id, p)
            if reopened:
                res.reopened.append(p.title)
            elif meaningful:
                res.updated.append(p.title)
            else:
                res.unchanged += 1

        # Anything open for this company that the board no longer lists is closed
        for row in conn.execute(
            "SELECT id, fingerprint, title FROM jobs WHERE company_id = ? AND closed_at IS NULL",
            (company_id,),
        ).fetchall():
            if row["fingerprint"] not in seen:
                conn.execute("UPDATE jobs SET closed_at = ? WHERE id = ?", (ts, row["id"]))
                res.closed.append(row["title"])

        res.open_count = len(seen)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return res


def _bool(v: bool | None) -> int | None:
    return None if v is None else int(v)


def _raw(conn: sqlite3.Connection, run_id, company_id, p: RawPosting) -> None:
    conn.execute(
        "INSERT INTO raw_postings (run_id, source, company_id, external_id, url, payload_json)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, p.source, company_id, p.external_id, p.url, json.dumps(p.payload, default=str)),
    )
