"""Shared test fixtures.

Recorded HTTP fixtures live in tests/fixtures/<source>/. Collectors are tested
offline by replaying them with respx (see test_http_fixtures.py for the pattern).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobscout.store import connect

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(relpath: str):
    """Load a recorded response. .json files are parsed; anything else returns text."""
    path = FIXTURES / relpath
    text = path.read_text()
    return json.loads(text) if path.suffix == ".json" else text


@pytest.fixture
def db():
    conn = connect(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """Isolated working folder with env pointed at it, so tests never touch real data."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JOBSCOUT_DB_PATH", str(tmp_path / "data" / "test.db"))
    monkeypatch.setenv("JOBSCOUT_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("JOBSCOUT_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("JOBSCOUT_LOG_LEVEL", "WARNING")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return tmp_path
