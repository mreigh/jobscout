"""Pattern for testing collectors offline against recorded responses.

Every collector in E2 gets a test like this: record a real response once into
tests/fixtures/<source>/, then replay it with respx so tests never hit the network.
"""

import httpx
import respx

from jobscout.http import USER_AGENT, make_client
from tests.conftest import load_fixture

BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/example/jobs"


@respx.mock
def test_replay_recorded_board_response():
    route = respx.get(BOARD_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("greenhouse/sample_board.json"))
    )
    with make_client() as client:
        data = client.get(BOARD_URL).json()

    assert route.called
    assert route.calls.last.request.headers["User-Agent"] == USER_AGENT
    titles = [j["title"] for j in data["jobs"]]
    assert "Implementation Manager" in titles


@respx.mock(assert_all_called=False)
def test_network_is_blocked_by_default():
    # Any request without a matching mock raises, so a test can't silently hit the internet.
    with make_client() as client:
        try:
            client.get("https://example.com")
        except respx.models.AllMockedAssertionError:
            return
    raise AssertionError("unmocked request should not have gone through")
