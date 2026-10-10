import pytest

from jobscout.config import ConfigError
from jobscout.detect import parse_board_url, slug_candidates


@pytest.mark.parametrize(
    "name, expected_first, must_include",
    [
        ("Q2", "q2", []),
        ("Modern Treasury", "moderntreasury", ["modern-treasury"]),
        ("Proof (formerly Notarize)", "proof", ["notarize"]),
        ("Partner One (Mortgage Cadence)", "partnerone", ["mortgagecadence", "mortgage-cadence"]),
        ("Dark Matter Technologies", "darkmattertechnologies", ["darkmatter", "dark-matter"]),
        ("ICE Mortgage Technology", "icemortgagetechnology", ["icemortgage"]),
        ("Baker Tilly", "bakertilly", ["baker-tilly"]),
        ("Interface.ai", "interfaceai", ["interface-ai", "interface"]),
        ("Zest AI", "zestai", ["zest-ai", "zest"]),
    ],
)
def test_slug_candidates(name, expected_first, must_include):
    slugs = slug_candidates(name)
    assert slugs[0] == expected_first
    for s in must_include:
        assert s in slugs
    assert len(slugs) == len(set(slugs)) <= 8


@pytest.mark.parametrize("name, word", [
    ("First Citizens Bank", "first"), ("Modern Treasury", "modern"),
    ("Jack Henry", "jack"), ("West Monroe", "west"), ("Robert W. Baird", "robert"),
])
def test_lone_first_words_not_tried(name, word):
    # a lone first word would match some other company's board
    assert word not in slug_candidates(name)


@pytest.mark.parametrize(
    "url, ats, token",
    [
        ("https://boards.greenhouse.io/mercury", "greenhouse", "mercury"),
        ("https://job-boards.greenhouse.io/mercury/jobs/123", "greenhouse", "mercury"),
        ("https://boards-api.greenhouse.io/v1/boards/mercury/jobs", "greenhouse", "mercury"),
        ("jobs.lever.co/plaid", "lever", "plaid"),
        ("https://jobs.ashbyhq.com/snapdocs/abc", "ashby", "snapdocs"),
        ("https://apply.workable.com/partner-one/", "workable", "partner-one"),
        ("https://careers.smartrecruiters.com/Visa", "smartrecruiters", "Visa"),
        ("https://fis.wd5.myworkdayjobs.com/en-US/SearchJobs", "workday", "fis|wd5|SearchJobs"),
        ("https://associatedbank.wd1.myworkdayjobs.com/External/job/x", "workday",
         "associatedbank|wd1|External"),
        ("https://careers-firstcitizens.icims.com/jobs", "icims",
         "careers-firstcitizens.icims.com"),
        ("https://ats.rippling.com/trovata/jobs", "rippling", "trovata"),
    ],
)
def test_parse_board_url(url, ats, token):
    ref = parse_board_url(url)
    assert (ref.ats, ref.token) == (ats, token)


def test_unknown_site_is_custom():
    ref = parse_board_url("https://www.jackhenry.com/careers")
    assert ref.ats == "custom"
    assert ref.token == "https://www.jackhenry.com/careers"


def test_workday_without_site_explains_itself():
    with pytest.raises(ConfigError, match="site name"):
        parse_board_url("https://fis.wd5.myworkdayjobs.com/")


def test_garbage_url():
    with pytest.raises(ConfigError):
        parse_board_url("not a url")
