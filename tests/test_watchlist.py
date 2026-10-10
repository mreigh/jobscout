from pathlib import Path

import pytest
from openpyxl import Workbook

from jobscout.config import ConfigError
from jobscout.watchlist import import_watchlist, load_watchlist

SAMPLE = Path(__file__).parents[1] / "samples" / "watchlist.sample.csv"
HEADERS = ["Company", "Segment", "Tier", "Status / history", "ATS", "Board URL (override)"]


def write_csv(path, rows):
    import csv

    with path.open("w", newline="") as f:
        csv.writer(f).writerows([HEADERS, *rows])
    return path


def test_sample_watchlist_loads():
    entries = load_watchlist(SAMPLE)
    assert len(entries) == 10
    assert all(e.tier in "ABC" for e in entries)
    # The committed sample must stay scrubbed: no history, no contacts
    assert all(e.status == "Never engaged" for e in entries)
    assert all(e.warm_angle is None for e in entries)


def test_xlsx_reads_companies_sheet(tmp_path):
    wb = Workbook()
    wb.active.title = "Read Me"
    ws = wb.create_sheet("Companies")
    ws.append(HEADERS)
    ws.append(["  Narmi ", "Digital Banking", "a", None, "Auto-detect", None])
    ws.append([None] * len(HEADERS))  # blank rows are skipped
    path = tmp_path / "w.xlsx"
    wb.save(path)
    [e] = load_watchlist(path)
    assert (e.name, e.tier, e.ats_hint, e.board_url) == ("Narmi", "A", "Auto-detect", None)


def test_errors_are_collected_with_row_numbers(tmp_path):
    p = write_csv(tmp_path / "w.csv", [
        ["Q2", "x", "A", "", "", ""],
        ["Nope", "x", "Z", "", "", ""],
        ["q2", "x", "B", "", "", ""],
    ])
    with pytest.raises(ConfigError) as e:
        load_watchlist(p)
    msg = str(e.value)
    assert "row 3" in msg and "tier" in msg
    assert "row 4" in msg and "duplicate" in msg


def test_missing_required_column(tmp_path):
    p = tmp_path / "w.csv"
    p.write_text("Company,Segment\nQ2,Banking\n")
    with pytest.raises(ConfigError, match="tier"):
        load_watchlist(p)


def test_missing_file_points_to_sample(tmp_path):
    with pytest.raises(ConfigError, match="watchlist.sample.csv"):
        load_watchlist(tmp_path / "nope.xlsx")


def _companies(db):
    return {r["name"]: r for r in db.execute("SELECT * FROM companies")}


def test_import_upserts_and_deactivates(db, tmp_path):
    p = write_csv(tmp_path / "w.csv", [
        ["Q2", "Banking", "A", "Never engaged", "Auto-detect", ""],
        ["Plaid", "Data", "B", "Never engaged", "Auto-detect", ""],
    ])
    r = import_watchlist(db, load_watchlist(p))
    assert sorted(r.added) == ["Plaid", "Q2"]

    # Simulate a detection result, then re-import with changes
    db.execute("UPDATE companies SET ats='greenhouse', ats_token='q2', detect_status='found'"
               " WHERE name='Q2'")
    write_csv(p, [["Q2", "Banking", "B", "Applied", "Auto-detect", ""]])
    r = import_watchlist(db, load_watchlist(p))
    rows = _companies(db)
    assert r.updated == ["Q2"] and r.deactivated == ["Plaid"]
    assert rows["Q2"]["tier"] == "B" and rows["Q2"]["status"] == "Applied"
    assert rows["Q2"]["ats"] == "greenhouse"  # detection survives a normal re-import
    assert rows["Plaid"]["active"] == 0

    # Bringing a company back reactivates it
    write_csv(p, [["Q2", "Banking", "B", "Applied", "Auto-detect", ""],
                  ["Plaid", "Data", "B", "Never engaged", "Auto-detect", ""]])
    import_watchlist(db, load_watchlist(p))
    assert _companies(db)["Plaid"]["active"] == 1


def test_board_url_change_queues_redetection(db, tmp_path):
    p = write_csv(tmp_path / "w.csv", [["FIS", "Core", "A", "", "Workday", ""]])
    import_watchlist(db, load_watchlist(p))
    db.execute("UPDATE companies SET detect_status='needs_url', detected_at=datetime('now')")
    write_csv(p, [["FIS", "Core", "A", "", "Workday", "https://fis.wd5.myworkdayjobs.com/SearchJobs"]])
    r = import_watchlist(db, load_watchlist(p))
    row = _companies(db)["FIS"]
    assert r.override_changed == ["FIS"]
    assert row["detect_status"] is None and row["detected_at"] is None
    assert row["board_url"].endswith("/SearchJobs")


def test_reimport_unchanged_is_a_noop(db):
    entries = load_watchlist(SAMPLE)
    import_watchlist(db, entries)
    r = import_watchlist(db, entries)
    assert r.unchanged == 10 and not (r.added or r.updated or r.deactivated)
