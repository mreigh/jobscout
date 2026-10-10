"""Detection tests. All network is mocked; anything unmocked 404s via the catch-all."""

import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from jobscout.detect import detect_company, run_detection
from jobscout.detect.detector import companies_to_detect, confidence_for, name_matches, save_result
from jobscout.detect.probers import Probe
from jobscout.http import PoliteClient
from tests.conftest import load_fixture

GH = "https://boards-api.greenhouse.io/v1/boards"
LEVER = "https://api.lever.co/v0/postings"
ASHBY = "https://api.ashbyhq.com/posting-api/job-board"
SR = "https://api.smartrecruiters.com/v1/companies"
WORKABLE = "https://apply.workable.com/api/v1/widget/accounts"


@pytest.fixture
def http():
    with PoliteClient(min_interval=0, backoff=0) as c:
        yield c


@pytest.fixture
def net():
    """respx router where every unmocked request 404s, like a real missing board.
    SmartRecruiters is special: it answers 200 with zero results for unknown companies."""
    with respx.mock(assert_all_called=False) as router:
        yield router
        # catch-alls are registered last so specific routes win
    # (nothing after yield)


def finish(router):
    router.get(url__startswith=SR).respond(200, json=load_fixture("smartrecruiters/empty.json"))
    router.route().respond(404, json={"ok": False})


# ---------------------------------------------------------------------------
# Confidence helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "company, board, ok",
    [
        ("Q2", "Q2", True),
        ("Guidewire", "Guidewire Software", True),
        ("Proof (formerly Notarize)", "Notarize", True),
        ("CliftonLarsonAllen (CLA)", "CLA", True),
        ("Polly", "Polly Pocket Toys", False),
        ("Unit", "United Health", False),
    ],
)
def test_name_matches(company, board, ok):
    assert name_matches(company, board) is ok


def test_confidence_without_board_name():
    assert confidence_for("Ocrolus", Probe("lever", "ocrolus", True)) == "likely"
    assert confidence_for("MX", Probe("lever", "mx", True)) == "review"  # too short to trust
    assert confidence_for("Modern Treasury", Probe("ashby", "modern", True)) == "review"


# ---------------------------------------------------------------------------
# detect_company
# ---------------------------------------------------------------------------


def test_greenhouse_confirmed_stops_early(net, http):
    net.get(f"{GH}/q2").respond(200, json=load_fixture("greenhouse/board.json"))
    net.get(f"{GH}/q2/jobs").respond(200, json=load_fixture("greenhouse/jobs.json"))
    lever = net.get(url__startswith=LEVER).respond(404)
    finish(net)

    r = detect_company(http, "Q2", ats_hint="Auto-detect")
    assert (r.status, r.ats, r.token, r.confidence, r.job_count) == (
        "found", "greenhouse", "q2", "confirmed", 2)
    assert not lever.called  # confirmed hit on the first ATS, no need to keep probing


def test_hint_is_probed_first(net, http):
    workable = net.get(f"{WORKABLE}/partnerone").respond(
        200, json=load_fixture("workable/account.json"))
    gh = net.get(url__startswith=GH).respond(404)
    finish(net)

    r = detect_company(http, "Partner One (Mortgage Cadence)", ats_hint="Workable")
    assert (r.ats, r.token, r.confidence) == ("workable", "partnerone", "confirmed")
    assert workable.called and not gh.called


def test_lever_hit_is_likely(net, http):
    net.get(f"{LEVER}/ocrolus").respond(200, json=load_fixture("lever/postings.json"))
    finish(net)
    r = detect_company(http, "Ocrolus")
    assert (r.status, r.ats, r.confidence, r.job_count) == ("found", "lever", "likely", 3)


def test_ashby_hit(net, http):
    net.get(f"{ASHBY}/alloy").respond(200, json=load_fixture("ashby/job_board.json"))
    finish(net)
    r = detect_company(http, "Alloy")
    assert (r.ats, r.token, r.job_count) == ("ashby", "alloy", 1)


@pytest.mark.parametrize("url, body", [
    (f"{WORKABLE}/q2", {"name": "Q2", "jobs": []}),           # seen live: stub for any slug
    (f"{ASHBY}/q2", {"apiVersion": "1", "jobs": []}),
    (f"{LEVER}/q2", []),
])
def test_empty_boards_are_not_hits(net, http, url, body):
    net.get(url__startswith=url).respond(200, json=body)
    finish(net)
    assert detect_company(http, "Q2").status == "not_found"


def test_smartrecruiters_empty_board_is_not_a_hit(net, http):
    finish(net)
    r = detect_company(http, "Nobody Corp")
    assert r.status == "not_found"
    assert "Board URL" in r.message


def test_smartrecruiters_hit_uses_company_name(net, http):
    net.get(url__startswith=f"{SR}/guidewire/").respond(
        200, json=load_fixture("smartrecruiters/postings.json"))
    finish(net)
    r = detect_company(http, "Guidewire")
    assert (r.ats, r.confidence, r.job_count) == ("smartrecruiters", "confirmed", 14)


def test_name_mismatch_flagged_for_review(net, http):
    net.get(f"{GH}/polly").respond(200, json={"name": "Polly Pocket Toys"})
    net.get(f"{GH}/polly/jobs").respond(200, json={"jobs": [], "meta": {"total": 0}})
    finish(net)
    r = detect_company(http, "Polly")
    assert (r.status, r.confidence) == ("found", "review")


def test_confirmed_beats_review_across_ats(net, http):
    net.get(f"{GH}/polly").respond(200, json={"name": "Polly Pocket Toys"})
    net.get(f"{GH}/polly/jobs").respond(200, json={"jobs": [], "meta": {"total": 0}})
    net.get(f"{WORKABLE}/polly").respond(200, json={"name": "Polly", "jobs": [{"title": "x"}]})
    finish(net)
    r = detect_company(http, "Polly")
    assert (r.ats, r.confidence) == ("workable", "confirmed")
    assert "also matched greenhouse:polly" in r.message


def test_workday_hint_without_url_needs_url(net, http):
    finish(net)
    r = detect_company(http, "Associated Bank", ats_hint="Workday")
    assert r.status == "needs_url"
    assert "Workday" in r.message


def test_transient_errors_are_not_not_found(net, http):
    route = net.get(url__startswith=GH).respond(503)
    finish(net)
    r = detect_company(http, "Narmi")
    assert r.status == "error"
    assert "will retry" in r.message
    assert route.call_count >= 3  # initial try + 2 retries, for the first slug


def test_workday_override_verified(net, http):
    net.post("https://fis.wd5.myworkdayjobs.com/wday/cxs/fis/SearchJobs/jobs").respond(
        200, json=load_fixture("workday/jobs.json"))
    finish(net)
    r = detect_company(http, "FIS", "Workday", "https://fis.wd5.myworkdayjobs.com/en-US/SearchJobs")
    assert (r.status, r.ats, r.token, r.confidence, r.job_count) == (
        "override", "workday", "fis|wd5|SearchJobs", "confirmed", 312)


def test_broken_override_flagged(net, http):
    finish(net)
    r = detect_company(http, "Mercury", board_url="https://boards.greenhouse.io/mercury-typo")
    assert (r.status, r.confidence) == ("override", "review")


def test_custom_override_needs_no_network(net, http):
    r = detect_company(http, "Jack Henry", board_url="https://www.jackhenry.com/careers")
    assert (r.status, r.ats, r.confidence) == ("override", "custom", "confirmed")
    assert not net.calls


# ---------------------------------------------------------------------------
# Saving and batch runs
# ---------------------------------------------------------------------------


def _add(db, name, **cols):
    cols = {"tier": "A", **cols}
    keys = ["name", *cols]
    db.execute(f"INSERT INTO companies ({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})",
               [name, *cols.values()])
    return db.execute("SELECT * FROM companies WHERE name = ?", (name,)).fetchone()


def test_error_keeps_previous_good_answer(db):
    from jobscout.detect import DetectionResult

    row = _add(db, "Q2", ats="greenhouse", ats_token="q2", detect_status="found",
               detect_confidence="confirmed", job_count=40)
    save_result(db, row, DetectionResult("Q2", "error", message="timeout"))
    r = db.execute("SELECT * FROM companies WHERE name='Q2'").fetchone()
    assert (r["ats"], r["ats_token"], r["detect_status"], r["job_count"]) == (
        "greenhouse", "q2", "error", 40)


def test_ats_change_is_recorded(db):
    from jobscout.detect import DetectionResult

    row = _add(db, "Q2", ats="lever", ats_token="q2")
    changed = save_result(db, row, DetectionResult("Q2", "found", "greenhouse", "q2", "confirmed"))
    assert changed
    c = db.execute("SELECT * FROM ats_changes").fetchone()
    assert (c["old_ats"], c["new_ats"]) == ("lever", "greenhouse")


def test_companies_to_detect_skips_fresh_results(db):
    _add(db, "Fresh", detect_status="found", detected_at="2999-01-01 00:00:00")
    _add(db, "Stale", detect_status="found", detected_at="2000-01-01 00:00:00")
    _add(db, "Errored", detect_status="error", detected_at="2999-01-01 00:00:00")
    _add(db, "New")
    _add(db, "Gone", active=0)
    names = lambda rows: sorted(r["name"] for r in rows)  # noqa: E731
    assert names(companies_to_detect(db)) == ["Errored", "New", "Stale"]
    assert names(companies_to_detect(db, refresh=True)) == ["Errored", "Fresh", "New", "Stale"]
    assert names(companies_to_detect(db, names=["fresh"])) == ["Fresh"]


def test_run_detection_saves_everything(db, net, http):
    _add(db, "Q2", ats_hint="Auto-detect")
    _add(db, "Nobody Corp")
    net.get(f"{GH}/q2").respond(200, json=load_fixture("greenhouse/board.json"))
    net.get(f"{GH}/q2/jobs").respond(200, json=load_fixture("greenhouse/jobs.json"))
    finish(net)
    rows = companies_to_detect(db)
    results = run_detection(db, http, rows, workers=2)
    assert {r.company: r.status for r in results} == {"Q2": "found", "Nobody Corp": "not_found"}
    q2 = db.execute("SELECT * FROM companies WHERE name='Q2'").fetchone()
    assert q2["ats"] == "greenhouse" and q2["detected_at"]
    assert json.loads(q2["detect_detail"])["probes"][0]["found"] is True


# ---------------------------------------------------------------------------
# CLI end to end on the sample watchlist
# ---------------------------------------------------------------------------


def test_cli_import_detect_show(workdir, monkeypatch):
    import functools

    import jobscout.http as jhttp
    from jobscout.cli import app

    monkeypatch.setattr(jhttp, "PoliteClient",
                        functools.partial(jhttp.PoliteClient, min_interval=0, backoff=0))
    runner = CliRunner()
    from pathlib import Path

    sample = Path(__file__).parents[1] / "samples" / "watchlist.sample.csv"
    assert runner.invoke(app, ["init"]).exit_code == 0

    result = runner.invoke(app, ["detect"])
    assert result.exit_code == 2 and "watchlist import" in result.output

    result = runner.invoke(app, ["watchlist", "import", "--file", str(sample)])
    assert result.exit_code == 0, result.output
    assert "added 10" in result.output

    with respx.mock(assert_all_called=False) as router:
        router.get(f"{GH}/q2").respond(200, json=load_fixture("greenhouse/board.json"))
        router.get(f"{GH}/q2/jobs").respond(200, json=load_fixture("greenhouse/jobs.json"))
        router.get(f"{LEVER}/ocrolus").respond(200, json=load_fixture("lever/postings.json"))
        finish(router)
        result = runner.invoke(app, ["detect"])
    assert result.exit_code == 0, result.output
    assert "Found 2" in result.output and "not found 8" in result.output

    result = runner.invoke(app, ["detect"])
    assert "up to date" in result.output

    result = runner.invoke(app, ["watchlist", "show", "--unresolved"])
    assert "Board URL" in result.output and "Q2" not in result.output

    result = runner.invoke(app, ["runs"])
    assert "detect" in result.output and "found=2" in result.output


def test_unmocked_network_is_blocked():
    with respx.mock:
        with pytest.raises(respx.models.AllMockedAssertionError):
            httpx.get("https://boards-api.greenhouse.io/v1/boards/x")
