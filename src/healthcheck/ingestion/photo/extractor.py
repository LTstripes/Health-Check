"""Provider-neutral vision extraction contract for historical photo import."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

DEFAULT_SCHEMA_VERSION = "r01-photo-v1"


class ExtractionFailure(Exception):
    """Typed extractor failure that leaves the raw artifact replayable."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ExtractionRequest:
    """Extractor input.  Never carries an arbitrary filesystem path."""

    artifact_id: str
    content_hash: str
    media_type: str
    locale: str | None = None
    timezone: str | None = None
    schema_version: str = DEFAULT_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class CandidateField:
    metric_code: str
    proposed_value: float | None
    proposed_unit: str | None
    source_text: str | None
    confidence: float | None
    source_local_date: date | None = None
    source_timestamp: datetime | None = None
    temporal_precision: str | None = None
    evidence_region: dict[str, Any] | None = None
    algorithm_code: str | None = None
    algorithm_version: str | None = None


@dataclass(frozen=True, slots=True)
class MeasurementGroup:
    key: str
    fields: tuple[CandidateField, ...]
    source_local_date: date | None = None
    source_timestamp: datetime | None = None
    temporal_precision: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    extractor_name: str
    extractor_version: str
    schema_version: str
    provider_code: str
    physical_device_code: str
    groups: tuple[MeasurementGroup, ...]
    model_name: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    source_application: str | None = None
    source_application_version: str | None = None


class ImageMeasurementExtractor(Protocol):
    """Pluggable screenshot/photo extractor used by the import service."""

    name: str
    version: str

    def extract(self, request: ExtractionRequest, image_bytes: bytes) -> ExtractionResult:
        """Return versioned candidate groups or raise ``ExtractionFailure``."""
