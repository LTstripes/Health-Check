"""Typed runtime configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from healthcheck.ingestion.openscale.binding import (
    classify_ingest_bind_host,
    evaluate_ingest_binding,
)


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
    openscale_source_instance_id: str | None = None
    openscale_ingest_token: str | None = None
    trusted_private_lan_http: bool = False
    openscale_algorithm_identity: str = "openscale-unknown"
    openscale_config_identity: str = "unknown"
    photo_vision_base_url: str | None = None
    photo_vision_model: str | None = None
    photo_vision_api_key: SecretStr | None = None
    photo_vision_timeout_seconds: float = Field(default=45.0, gt=0, le=300)
    photo_vision_provider_code: str | None = None
    photo_vision_physical_device_code: str | None = None
    photo_vision_source_application: str | None = None
    photo_vision_source_application_version: str | None = None

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

    @field_validator(
        "openscale_source_instance_id",
        "openscale_ingest_token",
        "photo_vision_api_key",
        mode="before",
    )
    @classmethod
    def empty_secret_to_none(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator(
        "photo_vision_base_url",
        "photo_vision_model",
        "photo_vision_provider_code",
        "photo_vision_physical_device_code",
        "photo_vision_source_application",
        "photo_vision_source_application_version",
        mode="before",
    )
    @classmethod
    def empty_photo_vision_text_to_none(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("weight_goal_kg")
    @classmethod
    def reject_non_positive_goal(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value <= 0 or value != value or value == float("inf") or value == float("-inf"):
            raise ValueError("HEALTHCHECK_WEIGHT_GOAL_KG must be a finite positive number")
        return value

    @model_validator(mode="after")
    def reject_unsafe_ingest_binds(self) -> Self:
        """Fail closed for public/unspecified binds and untrusted private LAN."""

        kind = classify_ingest_bind_host(self.ingest_host)
        if kind in {"public", "unspecified"}:
            raise ValueError("public internet exposure of the ingest listener is unsupported")
        if kind == "private" and not self.trusted_private_lan_http:
            raise ValueError(
                "plain private-LAN HTTP requires HEALTHCHECK_TRUSTED_PRIVATE_LAN_HTTP=true"
            )
        return self

    def ingest_binding_warning(self) -> str | None:
        """Return a plain-HTTP warning when a trusted private-LAN bind is active."""

        decision = evaluate_ingest_binding(
            self.ingest_host,
            trusted_private_lan_http=self.trusted_private_lan_http,
        )
        if decision.requires_plain_http_warning:
            return decision.message
        return None
