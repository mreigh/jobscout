"""Gate tests. Cases are lifted from the real A-tier export of Oct 11, which is
exactly the noise the gates exist to kill."""

from pathlib import Path

import pytest

from jobscout.config import load_filters
from jobscout.gates import apply_gates, classify

FILTERS = load_filters(Path(__file__).parents[1] / "config" / "filters.yaml")


def gate(title, location=None, url=None, description=None, remote=None, comp_min=None,
         comp_max=None):
    return classify(title, location, url, description, remote, comp_min, comp_max, FILTERS)


# --- Real keepers from the Oct 11 export ------------------------------------

@pytest.mark.parametrize("title, loc, remote, lo, hi", [
    ("Implementation Manager", "Remote", True, 166000, 185000),                  # Valon
    ("Senior Manager, Customer Success", "Remote", True, 160000, 195000),        # Vesta
    ("Senior Software Implementation Engineer", "Remote", True, 145000, 165000), # Lumin
    ("Deployment Strategist", "Remote", True, 140000, 240000),                   # Valon
    ("Strategic Solutions Architect", "Remote", True, 142000, 178000),           # Alkami
])
def test_real_keepers_pass(title, loc, remote, lo, hi):
    assert gate(title, loc, remote=remote, comp_min=lo, comp_max=hi) == "pass"


def test_milwaukee_workday_office_code_is_commutable():
    # FIS Consultant Senior - IBS Loan Conversions: "3 Locations", URL names US-WI-MKE
    assert gate("Consultant Senior - IBS Loan Conversions", "3 Locations",
                url="https://fis.wd5.myworkdayjobs.com/SearchJobs/job/US-WI-MKE-4900/x") == "pass"


def test_unknown_location_passes():
    assert gate("Product Owner, Digital Banking", "2 Locations") == "pass"
    assert gate("Implementation Manager") == "pass"


def test_description_remote_rescues_a_city_header():
    assert gate("Implementation Manager", "Jacksonville, FL",
                description="This position is remote eligible within the US") == "pass"


def test_mainframe_merged_into_the_one_list():
    assert gate("COBOL Engineer Lead, Professional Services", "Remote", remote=True) == "pass"


# --- Real rejects from the Oct 11 export -------------------------------------

@pytest.mark.parametrize("title, loc, url, want", [
    ("Consultant Lead, Professional Services", "POL WRSW 75", None, "location:non-us"),
    ("Consultant II, Professional Services", "IND CHNN 32 A&B 3RD FL U", None, "location:non-us"),
    ("Senior Client Success Manager - Core Banking Solutions", "GBR LNDN 25 Walbrook FL5", None,
     "location:non-us"),
    ("Program Manager II", "TUN ARIA 150", None, "location:non-us"),
    ("Manager, Delivery Management", "Bangalore, India", None, "location:non-us"),
    ("Customer Service Delivery Advocate", "New Westminster, British Columbia", None,
     "location:non-us"),
    ("Banking PMO Program Manager Sr. Lead", "US GA ATL 201 STE 900", None,
     "location:not-commutable"),
    ("Service Delivery Manager", "US FL JAX 347", None, "location:not-commutable"),
])
def test_wrong_place(title, loc, url, want):
    assert gate(title, loc, url=url) == want


def test_madison_and_chicago_onsites_excluded_per_decision():
    assert gate("Technical Program Manager", "Madison, WI") == "location:not-commutable"
    assert gate("Implementation Manager", "Hybrid - Chicago", remote=False) == \
        "location:not-commutable"


@pytest.mark.parametrize("title, want", [
    ("Sales Executive, Lending Solutions", "title:sales executive"),
    # "pre-sales representative" contains "sales representative"; either reason is a correct kill
    ("Pre-Sales Representative Lead, Solutions Architecture", "title:sales representative"),
    ("Presales Representative Lead, Solutions Specialist (D1C)", "title:sales representative"),
    ("Pre-Sales Solutions Consultant, Integrity TMS", "title:pre-sales"),
    ("Consulting & Implementations Early Talent Pipeline", "title:early talent"),
    ("Renewals Manager Lead - Front Office Solutions", "title:renewals"),
    ("Implementation Analyst II", "title:analyst i"),
    ("Project Implementation Conversion - Regular Night shift", "title:night shift"),
    ("Software Engineer II", "lane:no-match"),
    ("Staff Accountant", "lane:no-match"),
])
def test_wrong_role(title, want):
    assert gate(title, "Remote", remote=True) == want


@pytest.mark.parametrize("title, lo, hi", [
    ("GETPAID Consultant II, Professional Services", 65000, 111000),   # FIS
    ("Implementation Project Manager - Mortgage", 76000, 90000),       # MeridianLink
    ("Sr. Implementation Specialist", 78000, 98000),                   # Alkami
])
def test_below_the_pay_floor(title, lo, hi):
    assert gate(title, "Remote", remote=True, comp_min=lo, comp_max=hi) == "pay:below-floor"


def test_unstated_pay_still_shown():
    assert gate("Senior Customer Success Manager", "Remote", remote=True) == "pass"


def test_sales_title_dies_even_with_great_pay():
    assert gate("Sales Executive, Lending Solutions", "Remote", remote=True,
                comp_min=133000, comp_max=227000) == "title:sales executive"


# --- apply_gates --------------------------------------------------------------


def test_apply_gates_grades_open_jobs_and_is_idempotent(db):
    db.execute("INSERT INTO companies (name, tier) VALUES ('Valon', 'A')")
    jobs = [
        ("a", "Implementation Manager", "Remote", 1, 166000, 185000, None),
        ("b", "Sales Executive, Treasury", "Remote", 1, None, None, None),
        ("c", "Consultant II, Professional Services", "POL WRSW 75", None, None, None, None),
        ("d", "Delivery Manager", "Remote", 1, None, None, "2026-01-01 00:00:00"),  # closed
    ]
    for fp, title, loc, rem, lo, hi, closed in jobs:
        db.execute(
            "INSERT INTO jobs (fingerprint, company_id, title, location, remote, comp_min,"
            " comp_max, closed_at) VALUES (?, 1, ?, ?, ?, ?, ?, ?)",
            (fp, title, loc, rem, lo, hi, closed))
    v = apply_gates(db, FILTERS)
    assert v == {"pass": 1, "title:sales executive": 1, "location:non-us": 1}
    got = {r["fingerprint"]: r["filter_result"] for r in db.execute("SELECT * FROM jobs")}
    assert got == {"a": "pass", "b": "title:sales executive", "c": "location:non-us", "d": None}
    assert apply_gates(db, FILTERS) == v  # unchanged on a second run
