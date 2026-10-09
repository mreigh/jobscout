import sqlite3

import pytest

from jobscout.store import connect, current_version, migrate

EXPECTED_TABLES = {"companies", "raw_postings", "jobs", "scores", "runs", "schema_migrations"}


def test_schema_created(db):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED_TABLES <= tables
    assert current_version(db) == 1


def test_migrate_is_idempotent(db):
    assert migrate(db) == []
    assert current_version(db) == 1


def test_file_db_persists(tmp_path):
    path = tmp_path / "nested" / "jobscout.db"
    conn = connect(path)
    conn.execute("INSERT INTO companies (name, tier) VALUES ('Q2', 'A')")
    conn.close()
    conn = connect(path)
    assert conn.execute("SELECT tier FROM companies WHERE name='Q2'").fetchone()["tier"] == "A"
    conn.close()


def test_tier_constraint(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO companies (name, tier) VALUES ('Nope', 'Z')")


def test_score_cache_uniqueness(db):
    db.execute("INSERT INTO jobs (fingerprint, title) VALUES ('fp1', 'Implementation Lead')")
    job_id = db.execute("SELECT id FROM jobs").fetchone()[0]
    insert = (
        "INSERT INTO scores (job_id, description_hash, score, recommendation, result_json)"
        " VALUES (?, 'h1', 80, 'apply', '{}')"
    )
    db.execute(insert, (job_id,))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(insert, (job_id,))
