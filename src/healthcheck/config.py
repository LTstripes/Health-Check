"""Typed runtime configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_data_dir() -> Path:
    """Return the Windows-compatible default runtime directory."""

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Health-Check"
    return Path.home() / "AppData" / "Local" / "Health-Check"


class Settings(BaseSettings):
    """Configuration loaded from environment with safe local defaults."""

    model_config = SettingsConfigDict(
        env_prefix="HEALTHCHECK_",
        case_sensitive=False,
        extra="ignore",
    )

    data_dir: Path = Field(default_factory=default_data_dir)
    ui_port: int = Field(default=8000, ge=1, le=65535)
    ingest_enabled: bool = False
    ingest_host: str = "127.0.0.1"
    ingest_port: int = Field(default=8001, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    weight_goal_kg: float | None = None
    weight_cadence_days: int = Field(default=7, ge=1, le=365)

    @field_validator("data_dir", mode="before")
    @classmethod
    def normalize_data_dir(cls, value: object) -> Path:
        if value is None:
            return default_data_dir()
        return Path(value).expanduser()

    @field_validator("ingest_host")
    @classmethod
    def reject_empty_ingest_host(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("HEALTHCHECK_INGEST_HOST must not be empty")
        return value

    @field_validator("weight_goal_kg")
    @classmethod
    def reject_non_positive_goal(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value <= 0 or value != value or value == float("inf") or value == float("-inf"):
            raise ValueError("HEALTHCHECK_WEIGHT_GOAL_KG must be a finite positive number")
        return value
