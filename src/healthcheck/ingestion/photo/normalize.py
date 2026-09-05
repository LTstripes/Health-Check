"""Normalize extractor output without silently repairing health values."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from healthcheck.db.repositories import canonical_json, restore_stored_utc
from healthcheck.ingestion.photo.extractor import CandidateField, MeasurementGroup

WEIGHT_METRICS = {"weight"}
PERCENT_METRICS = {"body_fat_pct", "water_pct", "bone_pct"}
KG_METRICS = {"weight", "muscle_mass", "bone_mass"}

_UNIT_ALIASES = {
    "kg": "kg",
    "kilogram": "kg",
    "kilograms": "kg",
    "lb": "lb",
    "lbs": "lb",
    "pound": "lb",
    "pounds": "lb",
    "%": "%",
    "percent": "%",
    "pct": "%",
    "pp": "%",
}

LB_TO_KG = 0.45359237


@dataclass(frozen=True, slots=True)
class NormalizedField:
    metric_code: str
    proposed_value: float | None
    proposed_unit: str | None
    source_text: str | None
    confidence: float | None
    source_local_date: date | None
    source_timestamp: datetime | None
    temporal_precision: str | None
    evidence_region: dict | None
    algorithm_code: str | None
    algorithm_version: str | None
    warnings: tuple[str, ...]
    source_timezone: str | None = None
    source_utc_offset_minutes: int | None = None


def extraction_configuration_fingerprint(
    *,
    extractor_name: str,
    extractor_version: str,
    schema_version: str,
    model_name: str | None = None,
    model_version: str | None = None,
    prompt_version: str | None = None,
    provider_code: str | None = None,
    physical_device_code: str | None = None,
    source_application: str | None = None,
    source_application_version: str | None = None,
) -> str:
    """Canonical hash of interpretation-relevant extraction/acquisition config."""

    payload = {
        "extractor_name": extractor_name,
        "extractor_version": extractor_version,
        "model_name": model_name,
        "model_version": model_version,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "provider_code": provider_code,
        "physical_device_code": physical_device_code,
        "source_application": source_application,
        "source_application_version": source_application_version,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def candidate_set_key(
    extractor_name: str,
    extractor_version: str,
    schema_version: str,
    model_name: str | None = None,
    model_version: str | None = None,
    prompt_version: str | None = None,
    provider_code: str | None = None,
    physical_device_code: str | None = None,
    source_application: str | None = None,
    source_application_version: str | None = None,
) -> str:
    """Build extraction-set identity from the full configuration fingerprint."""

    return extraction_configuration_fingerprint(
        extractor_name=extractor_name,
        extractor_version=extractor_version,
        schema_version=schema_version,
        model_name=model_name,
        model_version=model_version,
        prompt_version=prompt_version,
        provider_code=provider_code,
        physical_device_code=physical_device_code,
        source_application=source_application,
        source_application_version=source_application_version,
    )


def validate_local_date_and_timestamp(
    local_date: date | None,
    timestamp: datetime | None,
    *,
    timezone: str | None = None,
    utc_offset_minutes: int | None = None,
) -> None:
    """Reject impossible local-date / instant pairs without inventing a timezone."""

    if local_date is None or timestamp is None:
        return
    instant = restore_stored_utc(timestamp)
    assert instant is not None
    if timezone:
        try:
            zone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("source timezone is not usable") from exc
        if instant.astimezone(zone).date() != local_date:
            raise ValueError("local date does not match timestamp in source timezone")
        return
    if utc_offset_minutes is not None:
        zone = dt_timezone(timedelta(minutes=utc_offset_minutes))
        if instant.astimezone(zone).date() != local_date:
            raise ValueError("local date does not match timestamp in source offset")
        return
    utc_date = instant.astimezone(UTC).date()
    if abs((local_date - utc_date).days) > 1:
        raise ValueError("local date and timestamp disagree by more than one calendar day")


def normalize_group(
    group: MeasurementGroup,
    *,
    source_timezone: str | None = None,
    source_utc_offset_minutes: int | None = None,
) -> tuple[NormalizedField, ...]:
    group_date = group.source_local_date
    group_timestamp = group.source_timestamp
    group_precision = group.temporal_precision
    return tuple(
        normalize_field(
            field,
            group_date,
            group_timestamp,
            group_precision,
            source_timezone=source_timezone,
            source_utc_offset_minutes=source_utc_offset_minutes,
        )
        for field in group.fields
    )


def normalize_field(
    field: CandidateField,
    group_date: date | None,
    group_timestamp: datetime | None,
    group_precision: str | None,
    *,
    source_timezone: str | None = None,
    source_utc_offset_minutes: int | None = None,
) -> NormalizedField:
    warnings: list[str] = []
    unit = _canonical_unit(field.proposed_unit)
    if field.proposed_unit and unit is None:
        warnings.append("unrecognized_unit")
        unit = field.proposed_unit
    if field.metric_code in KG_METRICS and unit not in {None, "kg", "lb"}:
        warnings.append("impossible_unit")
    if field.metric_code in PERCENT_METRICS and unit not in {None, "%"}:
        warnings.append("impossible_unit")
    if field.confidence is not None and not 0 <= field.confidence <= 1:
        warnings.append("confidence_out_of_range")

    source_timestamp = field.source_timestamp or group_timestamp
    source_local_date = field.source_local_date or group_date
    if source_local_date is None and source_timestamp is not None:
        source_local_date = source_timestamp.date()
    precision = (
        field.temporal_precision
        or group_precision
        or _infer_precision(source_local_date, source_timestamp)
    )
    if precision == "date" and source_timestamp is not None:
        # Date-only evidence stays date-only; extra instants are ignored rather
        # than used to invent a session timestamp.
        warnings.append("date_precision_drops_timestamp")
        source_timestamp = None
    if precision in {"instant", "minute"} and source_timestamp is None:
        warnings.append("missing_timestamp")
    if source_local_date is None:
        warnings.append("missing_source_date")
    if precision in {"instant", "minute"} and source_timestamp is not None:
        validate_local_date_and_timestamp(
            source_local_date,
            source_timestamp,
            timezone=source_timezone,
            utc_offset_minutes=source_utc_offset_minutes,
        )

    return NormalizedField(
        metric_code=field.metric_code,
        proposed_value=field.proposed_value,
        proposed_unit=unit,
        source_text=field.source_text,
        confidence=field.confidence,
        source_local_date=source_local_date,
        source_timestamp=source_timestamp,
        temporal_precision=precision,
        evidence_region=field.evidence_region,
        algorithm_code=field.algorithm_code,
        algorithm_version=field.algorithm_version,
        warnings=tuple(warnings),
        source_timezone=source_timezone,
        source_utc_offset_minutes=source_utc_offset_minutes,
    )


def normalize_confirmed_value(
    metric_code: str, value: float, unit: str | None
) -> tuple[float, str]:
    """Convert to R01 canonical units without otherwise changing the number."""

    canonical_unit = _canonical_unit(unit) or unit
    if canonical_unit is None:
        raise ValueError("measurement unit is required to confirm a candidate")
    if metric_code in KG_METRICS:
        if canonical_unit == "kg":
            return value, "kg"
        if canonical_unit == "lb":
            return value * LB_TO_KG, "kg"
        raise ValueError(f"cannot normalize {metric_code} unit {unit!r} to kg")
    if metric_code in PERCENT_METRICS:
        if canonical_unit == "%":
            return value, "%"
        raise ValueError(f"cannot normalize {metric_code} unit {unit!r} to percent")
    return value, canonical_unit


def field_warnings_from_candidate(
    metric_code: str,
    proposed_unit: str | None,
    confidence: float | None,
    temporal_precision: str | None,
    proposed_source_timestamp: datetime | None,
    proposed_source_local_date: date | None,
) -> list[str]:
    warnings: list[str] = []
    unit = _canonical_unit(proposed_unit)
    if proposed_unit and unit is None:
        warnings.append("unrecognized_unit")
        unit = proposed_unit
    if metric_code in KG_METRICS and unit not in {None, "kg", "lb"}:
        warnings.append("impossible_unit")
    if metric_code in PERCENT_METRICS and unit not in {None, "%"}:
        warnings.append("impossible_unit")
    if confidence is not None and not 0 <= confidence <= 1:
        warnings.append("confidence_out_of_range")
    if temporal_precision == "date" and proposed_source_timestamp is not None:
        warnings.append("date_precision_drops_timestamp")
    if proposed_source_local_date is None:
        warnings.append("missing_source_date")
    return warnings


def _canonical_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    return _UNIT_ALIASES.get(unit.strip().lower())


def _infer_precision(
    source_local_date: date | None, source_timestamp: datetime | None
) -> str | None:
    if source_timestamp is None:
        return "date" if source_local_date is not None else None
    if source_timestamp.second == 0 and source_timestamp.microsecond == 0:
        return "minute"
    return "instant"
