from pathlib import Path

import pytest

from jobscout.config import ConfigError, load_filters, load_settings

REPO_FILTERS = Path(__file__).parents[1] / "config" / "filters.yaml"


def test_repo_filters_file_is_valid():
    f = load_filters(REPO_FILTERS)
    assert f.comp.floor_usd > 0
    assert set(f.score_thresholds) == {"A", "B", "C"}


def test_missing_filters_file_gives_helpful_message(tmp_path):
    with pytest.raises(ConfigError, match="jobscout init"):
        load_filters(tmp_path / "nope.yaml")


def test_invalid_values_are_named(tmp_path):
    p = tmp_path / "filters.yaml"
    p.write_text("comp:\n  floor_usd: -5\nscore_thresholds: {A: 50, B: 60}\n")
    with pytest.raises(ConfigError) as e:
        load_filters(p)
    msg = str(e.value)
    assert "comp.floor_usd" in msg
    assert "score_thresholds" in msg


def test_bad_yaml(tmp_path):
    p = tmp_path / "filters.yaml"
    p.write_text("comp: [unclosed\n")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_filters(p)


def test_settings_from_env(workdir, monkeypatch):
    monkeypatch.setenv("JOBSCOUT_LOG_LEVEL", "debug")
    s = load_settings()
    assert s.log_level == "DEBUG"
    assert s.db_path.name == "test.db"


def test_bad_log_level(workdir, monkeypatch):
    monkeypatch.setenv("JOBSCOUT_LOG_LEVEL", "LOUD")
    with pytest.raises(ConfigError, match="log_level"):
        load_settings()
