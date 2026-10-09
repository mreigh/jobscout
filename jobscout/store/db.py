"""SQLite connection and versioned migrations.

Migrations are plain .sql files in store/migrations, named NNN_description.sql.
Each one runs exactly once, in order, inside a transaction, and is recorded in
schema_migrations. To change the schema, add a new file; never edit an applied one.
"""

from __future__ import annotations

import re
import sqlite3
from importlib import resources
from pathlib import Path

_MIGRATION_RE = re.compile(r"^(\d{3})_[\w-]+\.sql$")


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open the database, creating its folder if needed, and apply pending migrations."""
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    # Autocommit mode: we manage transactions explicitly where they matter.
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(db_path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def _migration_files() -> list[tuple[int, str, str]]:
    folder = resources.files("jobscout.store") / "migrations"
    found = []
    for entry in folder.iterdir():
        m = _MIGRATION_RE.match(entry.name)
        if m:
            found.append((int(m.group(1)), entry.name, entry.read_text()))
    found.sort()
    versions = [v for v, _, _ in found]
    if len(versions) != len(set(versions)):
        raise RuntimeError(f"Duplicate migration numbers: {versions}")
    return found


def current_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL,"
        " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return row[0] or 0


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply pending migrations. Returns the names applied (empty if up to date)."""
    applied = []
    have = current_version(conn)
    for version, name, sql in _migration_files():
        if version <= have:
            continue
        try:
            conn.execute("BEGIN")
            for statement in _split_sql(sql):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)", (version, name)
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        applied.append(name)
    return applied


def _split_sql(sql: str) -> list[str]:
    """Split a migration file into statements (no semicolons inside our DDL strings)."""
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
