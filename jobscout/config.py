"""Configuration: secrets and paths from the environment, rules from YAML.

Everything is typed with pydantic so bad config fails fast with a readable message
instead of blowing up halfway through a run.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, field_validator


class ConfigError(Exception):
    """Raised when configuration is missing or invalid. Message is meant for humans."""


# ---------------------------------------------------------------------------
# Environment settings
# ---------------------------------------------------------------------------

LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


class Settings(BaseModel):
    anthropic_api_key: str | None = None
    db_path: Path = Path("data/jobscout.db")
    config_dir: Path = Path("config")
    log_dir: Path = Path("logs")
    log_level: str = "INFO"
    watchlist_path: Path = Path("profile/watchlist.xlsx")

    @field_validator("log_level")
    @classmethod
    def _check_level(cls, v: str) -> str:
        v = v.upper()
        if v not in LOG_LEVELS:
            raise ValueError(f"must be one of {sorted(LOG_LEVELS)}")
        return v

    @property
    def filters_path(self) -> Path:
        return self.config_dir / "filters.yaml"


def load_settings(env_file: Path | None = None) -> Settings:
    """Read settings from the environment (and .env if present)."""
    load_dotenv(env_file or Path(".env"), override=False)
    raw = {
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY") or None,
        "db_path": os.getenv("JOBSCOUT_DB_PATH", "data/jobscout.db"),
        "config_dir": os.getenv("JOBSCOUT_CONFIG_DIR", "config"),
        "log_dir": os.getenv("JOBSCOUT_LOG_DIR", "logs"),
        "log_level": os.getenv("JOBSCOUT_LOG_LEVEL", "INFO"),
        "watchlist_path": os.getenv("JOBSCOUT_WATCHLIST", "profile/watchlist.xlsx"),
    }
    try:
        return Settings(**raw)
    except ValidationError as e:
        raise ConfigError(_format_errors("environment settings", e)) from e


# ---------------------------------------------------------------------------
# filters.yaml
# ---------------------------------------------------------------------------


class LocationRules(BaseModel):
    allow_remote_us: bool = True
    hybrid_metros: list[str] = Field(default_factory=list)


class CompRules(BaseModel):
    floor_usd: int = Field(ge=0, le=1_000_000)


class TitleRules(BaseModel):
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)


class ExclusionRules(BaseModel):
    description_phrases: list[str] = Field(default_factory=list)


class FiltersConfig(BaseModel):
    location: LocationRules = Field(default_factory=LocationRules)
    comp: CompRules
    titles: TitleRules = Field(default_factory=TitleRules)
    exclusions: ExclusionRules = Field(default_factory=ExclusionRules)
    score_thresholds: dict[str, int] = Field(default_factory=lambda: {"A": 55, "B": 65, "C": 75})

    @field_validator("score_thresholds")
    @classmethod
    def _check_thresholds(cls, v: dict[str, int]) -> dict[str, int]:
        missing = {"A", "B", "C"} - set(v)
        if missing:
            raise ValueError(f"missing tiers: {sorted(missing)}")
        bad = {k: s for k, s in v.items() if not 0 <= s <= 100}
        if bad:
            raise ValueError(f"thresholds must be 0-100, got {bad}")
        return v


def load_filters(path: Path) -> FiltersConfig:
    if not path.exists():
        raise ConfigError(
            f"Filters file not found at {path}. "
            "Run `jobscout init` to create a starter config, or set JOBSCOUT_CONFIG_DIR."
        )
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"{path} is not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path} should be a mapping of sections, got {type(data).__name__}")
    try:
        return FiltersConfig(**data)
    except ValidationError as e:
        raise ConfigError(_format_errors(str(path), e)) from e


def _format_errors(source: str, e: ValidationError) -> str:
    lines = [f"Invalid {source}:"]
    for err in e.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)
