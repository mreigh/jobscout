"""Run tracking: every command that does work gets a row in `runs`.

    with tracked_run(conn, "collect") as run:
        run.incr("postings_fetched", 42)
        run.add_cost(0.03)

On exit the row is marked success, or failed with the error message, and the
exception is re-raised so callers still see it.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Run:
    id: int
    command: str
    counts: Counter = field(default_factory=Counter)
    cost_usd: float = 0.0

    def incr(self, key: str, n: int = 1) -> None:
        self.counts[key] += n

    def add_cost(self, usd: float) -> None:
        self.cost_usd += usd


@contextmanager
def tracked_run(conn: sqlite3.Connection, command: str) -> Iterator[Run]:
    cur = conn.execute(
        "INSERT INTO runs (command, started_at, status) VALUES (?, ?, 'running')",
        (command, _now()),
    )
    run = Run(id=cur.lastrowid, command=command)
    log.info("run started", extra={"run_id": run.id, "command": command})
    try:
        yield run
    except BaseException as e:
        _finish(conn, run, "failed", error=f"{type(e).__name__}: {e}")
        log.error("run failed", extra={"run_id": run.id, "error": str(e)})
        raise
    else:
        _finish(conn, run, "success")
        log.info("run finished", extra={"run_id": run.id, **dict(run.counts)})


def _finish(conn: sqlite3.Connection, run: Run, status: str, error: str | None = None) -> None:
    conn.execute(
        "UPDATE runs SET finished_at = ?, status = ?, counts_json = ?, error = ?, cost_usd = ?"
        " WHERE id = ?",
        (_now(), status, json.dumps(dict(run.counts)), error, run.cost_usd, run.id),
    )


def recent_runs(conn: sqlite3.Connection, limit: int = 10) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
