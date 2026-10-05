"""R297 source-explicit read projection for persisted Google daily vitals.

This module is a bounded, read-only projection over the accepted R04 Google
persistence rows (``google_source_records`` + ``google_record_metrics`` +
``google_sources``).  It is deliberately Google-specific and typed: there is
no generic provider/EAV abstraction, no Garmin join, no canonical-source
selection and no provider call.

Frozen contract (issue #297, Integrator comment 6001780889):

- exactly four daily streams/metrics: daily HRV average, daily resting heart
  rate, daily SpO2 average and daily respiratory rate;
- source identity is ``google_sources.id``; every source is its own series and
  is never merged or resolved against another source;
- a point is placed only when ``source_local_date`` is non-NULL and
  ``temporal_precision = 'date'``;
- only ``projection_status = 'current'`` records participate; more than one
  current record for one ``(source, stream, source_local_date)`` is ambiguous
  and yields no value (no winner, average, query-mode or family preference);
- the target metric row decides value eligibility.  Missing/null/invalid/value
  stay distinct; an explicit finite zero is a real eligible value with
  ``is_zero=True``; a unit mismatch or non-finite value is ineligible;
- the requested window is an explicit inclusive ``[start_date, end_date]``
  bounded to 400 calendar days;
- ``latest`` is the newest date in the window with an eligible value; newer
  ambiguous/ineligible dates may be skipped only for this operation and the
  actual ``source_local_date`` is always returned.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    GoogleMetricState,
    GoogleRecordMetric,
    GoogleSource,
    GoogleSourceRecord,
)
from healthcheck.google.contracts import GoogleStream

GOOGLE_DAILY_VITALS_CONTRACT_VERSION = "r297-google-daily-vitals-read-v1"
MAX_GOOGLE_DAILY_VITALS_CALENDAR_DAYS = 400
_CURRENT = "current"
_DATE_PRECISION = "date"
_ROW_CHUNK = 400


@dataclass(frozen=True, slots=True)
class GoogleDailyVitalDefinition:
    """Frozen identity of one v1 Google daily-vital metric."""

    metric_code: str
    stream: GoogleStream
    unit: str
    provider_field: str

    @property
    def stream_code(self) -> str:
        return self.stream.value


GOOGLE_DAILY_VITALS: tuple[GoogleDailyVitalDefinition, ...] = (
    GoogleDailyVitalDefinition(
        metric_code="daily_hrv_average_ms",
        stream=GoogleStream.DAILY_HRV,
        unit="ms",
        provider_field=(
            "dailyHeartRateVariability."
            "averageHeartRateVariabilityMilliseconds"
        ),
    ),
    GoogleDailyVitalDefinition(
        metric_code="daily_resting_heart_rate_bpm",
        stream=GoogleStream.DAILY_RESTING_HR,
        unit="bpm",
        provider_field="dailyRestingHeartRate.beatsPerMinute",
    ),
    GoogleDailyVitalDefinition(
        metric_code="daily_oxygen_saturation_average_percentage",
        stream=GoogleStream.DAILY_SPO2,
        unit="%",
        provider_field="dailyOxygenSaturation.averagePercentage",
    ),
    GoogleDailyVitalDefinition(
        metric_code="daily_respiratory_rate_breaths_per_minute",
        stream=GoogleStream.DAILY_RESPIRATORY_RATE,
        unit="breaths_per_minute",
        provider_field="dailyRespiratoryRate.breathsPerMinute",
    ),
)

_DEFINITIONS_BY_METRIC: dict[str, GoogleDailyVitalDefinition] = {
    definition.metric_code: definition for definition in GOOGLE_DAILY_VITALS
}

_STATE_REASONS = {
    GoogleMetricState.MISSING.value: "metric_state_missing",
    GoogleMetricState.NULL.value: "metric_state_null",
    GoogleMetricState.INVALID.value: "metric_state_invalid",
}


def get_google_daily_vital(metric_code: str) -> GoogleDailyVitalDefinition:
    """Return the frozen v1 definition or reject an unknown metric code."""

    try:
        return _DEFINITIONS_BY_METRIC[metric_code]
    except KeyError as exc:
        raise ValueError(f"unknown Google daily vital metric: {metric_code}") from exc


def validate_google_daily_vitals_window(start_date: date, end_date: date) -> int:
    """Validate the explicit inclusive window and return its calendar-day span."""

    if end_date < start_date:
        raise ValueError("Google daily vitals window end must be on or after start")
    span = (end_date - start_date).days + 1
    if span > MAX_GOOGLE_DAILY_VITALS_CALENDAR_DAYS:
        raise ValueError(
            f"Google daily vitals window spans {span} calendar days; "
            f"max allowed is {MAX_GOOGLE_DAILY_VITALS_CALENDAR_DAYS}"
        )
    return span


@dataclass(frozen=True, slots=True)
class GoogleDailyVitalCandidate:
    """One current record participating in an ambiguous same-date group."""

    record_id: str
    metric_row_id: str | None
    state: str | None
    reason: str | None
    unit: str | None
    record_status: str
    query_mode: str
    data_source_family: str | None
    external_record_id: str | None
    raw_payload_id: str
    observation_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "metric_row_id": self.metric_row_id,
            "state": self.state,
            "reason": self.reason,
            "unit": self.unit,
            "record_status": self.record_status,
            "query_mode": self.query_mode,
            "data_source_family": self.data_source_family,
            "external_record_id": self.external_record_id,
            "raw_payload_id": self.raw_payload_id,
            "observation_id": self.observation_id,
        }


@dataclass(frozen=True, slots=True)
class GoogleDailyVitalPoint:
    """One provider-local date for one source/metric, state kept explicit."""

    source_local_date: date
    state: str
    value: float | None
    unit: str | None
    is_zero: bool
    eligible: bool
    exclusion_basis: str | None
    record_id: str | None
    metric_row_id: str | None
    record_status: str | None
    query_mode: str | None
    data_source_family: str | None
    field_path: str | None
    candidates: tuple[GoogleDailyVitalCandidate, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_local_date": self.source_local_date.isoformat(),
            "state": self.state,
            "value": self.value,
            "unit": self.unit,
            "is_zero": self.is_zero,
            "eligible": self.eligible,
            "exclusion_basis": self.exclusion_basis,
            "record_id": self.record_id,
            "metric_row_id": self.metric_row_id,
            "record_status": self.record_status,
            "query_mode": self.query_mode,
            "data_source_family": self.data_source_family,
            "field_path": self.field_path,
            "candidates": [item.as_dict() for item in self.candidates],
        }


@dataclass(frozen=True, slots=True)
class GoogleDailyVitalSource:
    """One explicit Google source; never merged with another source."""

    source_id: str
    provider_code: str
    source_kind: str
    source_instance_id: str
    data_source_name: str | None
    data_source_id: str | None
    platform: str | None
    recording_method: str | None
    device_attributed: bool
    device_code: str | None
    device_manufacturer: str | None
    device_model: str | None
    device_uid: str | None
    points: tuple[GoogleDailyVitalPoint, ...]
    latest: GoogleDailyVitalPoint | None
    latest_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "provider_code": self.provider_code,
            "source_kind": self.source_kind,
            "source_instance_id": self.source_instance_id,
            "data_source_name": self.data_source_name,
            "data_source_id": self.data_source_id,
            "platform": self.platform,
            "recording_method": self.recording_method,
            "device_attributed": self.device_attributed,
            "device_code": self.device_code,
            "device_manufacturer": self.device_manufacturer,
            "device_model": self.device_model,
            "device_uid": self.device_uid,
            "latest": self.latest.as_dict() if self.latest is not None else None,
            "latest_reason": self.latest_reason,
            "points": [point.as_dict() for point in self.points],
        }


@dataclass(frozen=True, slots=True)
class GoogleDailyVitalsResult:
    """Result of one bounded per-metric read across explicit Google sources."""

    contract_version: str
    metric_code: str
    stream_code: str
    unit: str
    start_date: date
    end_date: date
    window_state: str
    sources: tuple[GoogleDailyVitalSource, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "metric_code": self.metric_code,
            "stream_code": self.stream_code,
            "unit": self.unit,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "window_state": self.window_state,
            "sources": [source.as_dict() for source in self.sources],
        }


def read_google_daily_vitals(
    session: Session,
    *,
    metric_code: str,
    start_date: date,
    end_date: date,
) -> GoogleDailyVitalsResult:
    """Read one frozen metric from persisted current Google evidence only."""

    definition = get_google_daily_vital(metric_code)
    validate_google_daily_vitals_window(start_date, end_date)
    records = list(
        session.scalars(
            select(GoogleSourceRecord)
            .where(
                GoogleSourceRecord.stream_code == definition.stream_code,
                GoogleSourceRecord.projection_status == _CURRENT,
                GoogleSourceRecord.temporal_precision == _DATE_PRECISION,
                GoogleSourceRecord.source_local_date.is_not(None),
                GoogleSourceRecord.source_local_date >= start_date,
                GoogleSourceRecord.source_local_date <= end_date,
            )
            .order_by(
                GoogleSourceRecord.source_local_date,
                GoogleSourceRecord.google_source_id,
                GoogleSourceRecord.id,
            )
        )
    )
    if not records:
        return _empty_result(definition, start_date, end_date)

    sources = _load_sources(session, records)
    metrics = _load_metric_rows(session, records, definition.metric_code)
    groups: dict[tuple[str, date], list[GoogleSourceRecord]] = {}
    for record in records:
        assert record.source_local_date is not None
        groups.setdefault((record.google_source_id, record.source_local_date), []).append(record)

    by_source: dict[str, list[GoogleDailyVitalPoint]] = {}
    for (source_id, local_date), group in groups.items():
        point = _point_for_group(definition, local_date, group, metrics)
        by_source.setdefault(source_id, []).append(point)

    source_rows = tuple(
        _source_result(sources[source_id], by_source[source_id])
        for source_id in sorted(by_source)
        if source_id in sources
    )
    return GoogleDailyVitalsResult(
        contract_version=GOOGLE_DAILY_VITALS_CONTRACT_VERSION,
        metric_code=definition.metric_code,
        stream_code=definition.stream_code,
        unit=definition.unit,
        start_date=start_date,
        end_date=end_date,
        window_state="records_in_window",
        sources=source_rows,
    )


def _empty_result(
    definition: GoogleDailyVitalDefinition, start_date: date, end_date: date
) -> GoogleDailyVitalsResult:
    return GoogleDailyVitalsResult(
        contract_version=GOOGLE_DAILY_VITALS_CONTRACT_VERSION,
        metric_code=definition.metric_code,
        stream_code=definition.stream_code,
        unit=definition.unit,
        start_date=start_date,
        end_date=end_date,
        window_state="no_current_record_in_window",
        sources=(),
    )


def _load_sources(
    session: Session, records: Sequence[GoogleSourceRecord]
) -> dict[str, GoogleSource]:
    source_ids = sorted({record.google_source_id for record in records})
    loaded: dict[str, GoogleSource] = {}
    for offset in range(0, len(source_ids), _ROW_CHUNK):
        for source in session.scalars(
            select(GoogleSource).where(
                GoogleSource.id.in_(source_ids[offset : offset + _ROW_CHUNK])
            )
        ):
            loaded[source.id] = source
    return loaded


def _load_metric_rows(
    session: Session, records: Sequence[GoogleSourceRecord], metric_code: str
) -> dict[str, GoogleRecordMetric]:
    record_ids = sorted({record.id for record in records})
    loaded: dict[str, GoogleRecordMetric] = {}
    for offset in range(0, len(record_ids), _ROW_CHUNK):
        for row in session.scalars(
            select(GoogleRecordMetric).where(
                GoogleRecordMetric.record_id.in_(record_ids[offset : offset + _ROW_CHUNK]),
                GoogleRecordMetric.metric_code == metric_code,
            )
        ):
            loaded[row.record_id] = row
    return loaded


def _point_for_group(
    definition: GoogleDailyVitalDefinition,
    local_date: date,
    group: Sequence[GoogleSourceRecord],
    metrics: Mapping[str, GoogleRecordMetric],
) -> GoogleDailyVitalPoint:
    if len(group) > 1:
        return GoogleDailyVitalPoint(
            source_local_date=local_date,
            state="ambiguous",
            value=None,
            unit=definition.unit,
            is_zero=False,
            eligible=False,
            exclusion_basis="ambiguous_same_date_records",
            record_id=None,
            metric_row_id=None,
            record_status=None,
            query_mode=None,
            data_source_family=None,
            field_path=None,
            candidates=tuple(
                _candidate(record, metrics.get(record.id)) for record in group
            ),
        )
    record = group[0]
    row = metrics.get(record.id)
    if row is None:
        return _state_point(
            local_date,
            record,
            state=GoogleMetricState.MISSING.value,
            value=None,
            unit=definition.unit,
            exclusion_basis="metric_row_missing",
        )
    row_state = str(row.state)
    if row_state != GoogleMetricState.VALUE.value:
        return _state_point(
            local_date,
            record,
            state=row_state,
            value=None,
            unit=row.unit if row.unit is not None else definition.unit,
            exclusion_basis=row.reason or _STATE_REASONS.get(row_state, row_state),
            metric_row=row,
        )
    number = _finite_number(row.value_number)
    if number is None:
        return _state_point(
            local_date,
            record,
            state=GoogleMetricState.INVALID.value,
            value=None,
            unit=row.unit if row.unit is not None else definition.unit,
            exclusion_basis="metric_value_invalid",
            metric_row=row,
        )
    if row.unit != definition.unit:
        return _state_point(
            local_date,
            record,
            state=GoogleMetricState.VALUE.value,
            value=None,
            unit=row.unit,
            exclusion_basis="metric_unit_mismatch",
            metric_row=row,
        )
    return GoogleDailyVitalPoint(
        source_local_date=local_date,
        state=GoogleMetricState.VALUE.value,
        value=number,
        unit=definition.unit,
        is_zero=number == 0,
        eligible=True,
        exclusion_basis=None,
        record_id=record.id,
        metric_row_id=row.id,
        record_status=record.record_status,
        query_mode=record.query_mode,
        data_source_family=record.data_source_family,
        field_path=row.field_path,
    )


def _state_point(
    local_date: date,
    record: GoogleSourceRecord,
    *,
    state: str,
    value: float | None,
    unit: str | None,
    exclusion_basis: str,
    metric_row: GoogleRecordMetric | None = None,
) -> GoogleDailyVitalPoint:
    return GoogleDailyVitalPoint(
        source_local_date=local_date,
        state=state,
        value=value,
        unit=unit,
        is_zero=False,
        eligible=False,
        exclusion_basis=exclusion_basis,
        record_id=record.id,
        metric_row_id=metric_row.id if metric_row is not None else None,
        record_status=record.record_status,
        query_mode=record.query_mode,
        data_source_family=record.data_source_family,
        field_path=metric_row.field_path if metric_row is not None else None,
    )


def _candidate(
    record: GoogleSourceRecord, row: GoogleRecordMetric | None
) -> GoogleDailyVitalCandidate:
    return GoogleDailyVitalCandidate(
        record_id=record.id,
        metric_row_id=row.id if row is not None else None,
        state=str(row.state) if row is not None else None,
        reason=row.reason if row is not None else None,
        unit=row.unit if row is not None else None,
        record_status=record.record_status,
        query_mode=record.query_mode,
        data_source_family=record.data_source_family,
        external_record_id=record.external_record_id,
        raw_payload_id=record.raw_payload_id,
        observation_id=record.observation_id,
    )


def _source_result(
    source: GoogleSource, points: Iterable[GoogleDailyVitalPoint]
) -> GoogleDailyVitalSource:
    ordered = tuple(sorted(points, key=lambda item: item.source_local_date))
    latest = next((point for point in reversed(ordered) if point.eligible), None)
    return GoogleDailyVitalSource(
        source_id=source.id,
        provider_code=source.provider_code,
        source_kind=source.source_kind,
        source_instance_id=source.source_instance_id,
        data_source_name=source.data_source_name,
        data_source_id=source.data_source_id,
        platform=source.platform,
        recording_method=source.recording_method,
        device_attributed=bool(source.device_attributed),
        device_code=source.device_code,
        device_manufacturer=source.device_manufacturer,
        device_model=source.device_model,
        device_uid=source.device_uid,
        points=ordered,
        latest=latest,
        latest_reason=None if latest is not None else "no_eligible_value_in_window",
    )


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if isfinite(number) else None


__all__ = [
    "GOOGLE_DAILY_VITALS",
    "GOOGLE_DAILY_VITALS_CONTRACT_VERSION",
    "MAX_GOOGLE_DAILY_VITALS_CALENDAR_DAYS",
    "GoogleDailyVitalCandidate",
    "GoogleDailyVitalDefinition",
    "GoogleDailyVitalPoint",
    "GoogleDailyVitalSource",
    "GoogleDailyVitalsResult",
    "get_google_daily_vital",
    "read_google_daily_vitals",
    "validate_google_daily_vitals_window",
]
