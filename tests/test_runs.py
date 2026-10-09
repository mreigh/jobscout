import json

import pytest

from jobscout.runs import recent_runs, tracked_run


def test_successful_run_recorded(db):
    with tracked_run(db, "collect") as run:
        run.incr("postings", 3)
        run.incr("postings")
        run.add_cost(0.02)
    row = recent_runs(db, 1)[0]
    assert row["status"] == "success"
    assert row["finished_at"] is not None
    assert json.loads(row["counts_json"]) == {"postings": 4}
    assert row["cost_usd"] == pytest.approx(0.02)


def test_failed_run_recorded_and_reraised(db):
    with pytest.raises(RuntimeError):
        with tracked_run(db, "collect"):
            raise RuntimeError("greenhouse timed out")
    row = recent_runs(db, 1)[0]
    assert row["status"] == "failed"
    assert "greenhouse timed out" in row["error"]


def test_recent_runs_newest_first(db):
    for cmd in ("detect", "collect", "digest"):
        with tracked_run(db, cmd):
            pass
    assert [r["command"] for r in recent_runs(db, 2)] == ["digest", "collect"]
