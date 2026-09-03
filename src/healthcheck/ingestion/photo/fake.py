"""Deterministic extractor used by tests and the R01 development runtime."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from healthcheck.ingestion.photo.extractor import (
    DEFAULT_SCHEMA_VERSION,
    CandidateField,
    ExtractionFailure,
    ExtractionRequest,
    ExtractionResult,
    MeasurementGroup,
)
from healthcheck.ingestion.photo.synthetic import decode_synthetic_payload


class FakeImageMeasurementExtractor:
    """Read structured payloads from synthetic PNGs.  No live model is called."""

    def __init__(
        self,
        *,
        version: str = "1",
        value_delta: float = 0.0,
        model_name: str = "synthetic-fixture",
        model_version: str | None = None,
        prompt_version: str | None = None,
        provider_code: str | None = None,
        field_algorithms: dict[str, tuple[str, str]] | None = None,
    ):
        self.name = "healthcheck-synthetic-extractor"
        self.version = version
        self.value_delta = value_delta
        self.model_name = model_name
        self.model_version = version if model_version is None else model_version
        self.prompt_version = prompt_version
        self.provider_code_override = provider_code
        self.field_algorithms = field_algorithms or {}

    def extract(self, request: ExtractionRequest, image_bytes: bytes) -> ExtractionResult:
        try:
            payload = decode_synthetic_payload(image_bytes)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ExtractionFailure(
                "extractor_invalid_payload", "synthetic payload is not valid"
            ) from exc
        if payload is None:
            raise ExtractionFailure(
                "extractor_unsupported_image",
                "image has no synthetic extraction payload",
            )
        schema_version = str(
            payload.get("schema_version") or request.schema_version or DEFAULT_SCHEMA_VERSION
        )
        groups = tuple(self._group(raw_group) for raw_group in payload.get("groups") or ())
        if not groups:
            raise ExtractionFailure(
                "extractor_empty_result", "extractor returned no measurement groups"
            )
        if "provider_code" in payload:
            provider_code = payload.get("provider_code")
        else:
            provider_code = "xiaomi_home"
        if self.provider_code_override is not None:
            provider_code = self.provider_code_override
        return ExtractionResult(
            extractor_name=self.name,
            extractor_version=self.version,
            schema_version=schema_version,
            provider_code=str(provider_code) if provider_code else "",
            physical_device_code=str(payload.get("physical_device_code") or "xiaomi_s400"),
            groups=groups,
            model_name=self.model_name,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
            source_application=payload.get("source_application"),
            source_application_version=payload.get("source_application_version"),
        )

    def _group(self, raw_group: Any) -> MeasurementGroup:
        if not isinstance(raw_group, dict):
            raise ExtractionFailure(
                "extractor_invalid_payload", "measurement group must be an object"
            )
        fields = tuple(self._field(raw_field) for raw_field in raw_group.get("fields") or ())
        if not fields:
            raise ExtractionFailure("extractor_empty_result", "measurement group has no fields")
        return MeasurementGroup(
            key=str(raw_group.get("key") or "weigh-in"),
            fields=fields,
            source_local_date=_parse_date(raw_group.get("source_local_date")),
            source_timestamp=_parse_timestamp(raw_group.get("source_timestamp")),
            temporal_precision=_optional_text(raw_group.get("temporal_precision")),
        )

    def _field(self, raw_field: Any) -> CandidateField:
        if not isinstance(raw_field, dict):
            raise ExtractionFailure(
                "extractor_invalid_payload", "candidate field must be an object"
            )
        metric_code = str(raw_field.get("metric_code") or "").strip()
        if not metric_code:
            raise ExtractionFailure(
                "extractor_invalid_payload", "candidate field is missing metric_code"
            )
        # Confidence is retained only when the payload actually reports it.
        # There is no fallback numeric default.
        confidence = raw_field.get("confidence")
        if confidence is not None:
            confidence = float(confidence)
        value = raw_field.get("value")
        if value is not None:
            value = float(value) + self.value_delta
        algorithm_code = _optional_text(raw_field.get("algorithm_code"))
        algorithm_version = _optional_text(raw_field.get("algorithm_version"))
        if metric_code in self.field_algorithms:
            algorithm_code, algorithm_version = self.field_algorithms[metric_code]
        return CandidateField(
            metric_code=metric_code,
            proposed_value=value,
            proposed_unit=_optional_text(raw_field.get("unit")),
            source_text=_optional_text(raw_field.get("source_text")),
            confidence=confidence,
            source_local_date=_parse_date(raw_field.get("source_local_date")),
            source_timestamp=_parse_timestamp(raw_field.get("source_timestamp")),
            temporal_precision=_optional_text(raw_field.get("temporal_precision")),
            evidence_region=raw_field.get("evidence_region"),
            algorithm_code=algorithm_code,
            algorithm_version=algorithm_version,
        )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
