"""Bounded offline Google Health v4 exercise sessions, without OAuth or HTTP.

V1 reads explicitly selected google-wearables list evidence. The family describes
the query partition, not a physical device or a reconciled workout total.
Calories, routes, telemetry, free text and activity equivalence are not projected.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from healthcheck.db.repositories import canonical_json
from healthcheck.google.contracts import (
    FAMILY_GOOGLE_WEARABLES,
    GoogleDataSourceDTO,
    GoogleIntervalKind,
    GoogleMetricDTO,
    GoogleMetricState,
    GooglePayloadStatus,
    GoogleQueryContext,
    GoogleQueryMode,
    GoogleRecordDTO,
    GoogleSourceIdentity,
    GoogleStream,
)
from healthcheck.google.normalization import (
    GoogleNormalizationDiagnostic,
    GoogleNormalizationResult,
    _parse_data_source,
    _parse_source_interval,
    _ParseContext,
)
from healthcheck.google.sync import source_identity_from_point

CONTRACT = "google-exercise-session-v1"
ACQUISITION_CONTRACT = "google-exercise-acquisition-v1"
MAX_PAGE_BYTES = 1024 * 1024
MAX_PAGE_RECORDS = 25
QUERY = GoogleQueryContext(GoogleQueryMode.LIST, FAMILY_GOOGLE_WEARABLES)
_NAME = re.compile(r"users/[^/\s]+/dataTypes/exercise/dataPoints/[^/\s]{1,128}\Z")
_TYPE = re.compile(r"[A-Z][A-Z0-9_]{0,79}\Z")
_DURATION = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,9})?s\Z")
_STAMP = re.compile(
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.([0-9]{1,9}))?(Z|[+-]\d{2}:\d{2})\Z"
)
_MISSING = object()


def revision_key(value: object) -> tuple[datetime, int]:
    """Order RFC3339 provider revisions without dropping nanoseconds."""
    match = _STAMP.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ValueError("invalid exercise revision")
    clock, fraction, zone = match.groups()
    if zone != "Z" and (int(zone[1:3]) > 23 or int(zone[4:6]) > 59):
        raise ValueError("invalid exercise timestamp offset")
    instant = datetime.fromisoformat(clock + ("+00:00" if zone == "Z" else zone))
    return instant.astimezone(UTC), int((fraction or "").ljust(9, "0"))


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate exercise JSON key")
        result[key] = value
    return result


def normalize_exercise_payload(
    payload: Mapping[str, object] | bytes | bytearray,
    *,
    source_identity: GoogleSourceIdentity,
    query: GoogleQueryContext = QUERY,
) -> GoogleNormalizationResult:
    """Normalize one list page; unusable page never projects a successful prefix.

    Select exact source metadata with the existing Google identity contract.
    Missing optional duration stays missing, distinct from explicit 0.
    A valid updateTime is required for typed promotion and correction ordering.
    """
    if query != QUERY or not isinstance(source_identity, GoogleSourceIdentity):
        raise ValueError("exercise v1 requires explicit google-wearables list partition")
    context = _ParseContext([], [])
    records = []
    token_state = GoogleMetricState.MISSING
    try:
        raw_bytes = (
            bytes(payload)
            if isinstance(payload, (bytes, bytearray))
            else (canonical_json(payload).encode("utf-8"))
        )
        if len(raw_bytes) > MAX_PAGE_BYTES:
            raise ValueError("exercise page too large")
        page = json.loads(raw_bytes, object_pairs_hook=_unique_keys)
        if not isinstance(page, dict) or set(page) - {"dataPoints", "nextPageToken"}:
            raise ValueError("exercise envelope invalid")
        points = page.get("dataPoints", [])
        if not isinstance(points, list) or len(points) > MAX_PAGE_RECORDS:
            raise ValueError("exercise list invalid")
        if "nextPageToken" in page:
            token = page["nextPageToken"]
            if not isinstance(token, str) or len(token) > 8192:
                raise ValueError("exercise continuation invalid")
            token_state = GoogleMetricState.VALUE if token else GoogleMetricState.MISSING
        names = set()
        contexts = []
        for point in points:
            context = _ParseContext([], [])
            if not isinstance(point, dict) or set(point) - {"name", "dataSource", "exercise"}:
                raise ValueError("exercise point invalid")
            name = point.get("name")
            value = point.get("exercise")
            if not isinstance(name, str) or not _NAME.fullmatch(name) or name in names:
                raise ValueError("exercise identity missing or duplicated")
            names.add(name)
            if not isinstance(value, dict) or not _TYPE.fullmatch(
                str(value.get("exerciseType", ""))
            ):
                raise ValueError("exercise type invalid")
            revision_key(value.get("updateTime"))
            interval_raw = value.get("interval")
            if not isinstance(interval_raw, dict):
                raise ValueError("exercise interval invalid")
            # Current shared storage uses microseconds and whole-minute offsets.
            # Refuse sub-microsecond physical times rather than silently round.
            for key in ("startTime", "endTime"):
                _, nanos = revision_key(interval_raw.get(key))
                if nanos % 1000:
                    raise ValueError("exercise time precision unsupported")
            for civil_key in ("civilStartTime", "civilEndTime"):
                if civil_key in interval_raw:
                    civil = interval_raw[civil_key]
                    if not isinstance(civil, dict):
                        raise ValueError("exercise civil time invalid")
                    nanos = civil.get("time", {}).get("nanos", 0)
                    if type(nanos) is not int or nanos % 1000:
                        raise ValueError("exercise civil precision unsupported")
            interval = _parse_source_interval(
                interval_raw,
                "$.exercise.interval",
                context,
                interval_kind=GoogleIntervalKind.EXERCISE_SESSION,
                civil_start_field="civilStartTime",
                civil_end_field="civilEndTime",
            )
            if context.material_error or context.partial:
                raise ValueError("exercise interval invalid")
            for endpoint in (interval.start, interval.end):
                expected = (
                    endpoint.measured_at_utc + timedelta(minutes=endpoint.source_utc_offset_minutes)
                ).replace(tzinfo=None)
                if datetime.fromisoformat(endpoint.local_wall_time) != expected:
                    raise ValueError("exercise civil time contradicts physical time")
            elapsed = (
                interval.end.measured_at_utc - interval.start.measured_at_utc
            ).total_seconds()
            duration = value.get("activeDuration", _MISSING)
            duration_state = (
                GoogleMetricState.MISSING
                if duration is _MISSING
                else GoogleMetricState.NULL
                if duration is None
                else GoogleMetricState.VALUE
            )
            seconds = None
            if duration_state is GoogleMetricState.VALUE:
                if not isinstance(duration, str) or not _DURATION.fullmatch(duration):
                    duration_state = GoogleMetricState.INVALID
                else:
                    seconds = Decimal(duration[:-1])
                    if seconds > Decimal(str(elapsed)):
                        duration_state, seconds = GoogleMetricState.INVALID, None
            metrics = (
                GoogleMetricDTO(
                    "exercise_type",
                    "$.exercise.exerciseType",
                    GoogleMetricState.VALUE,
                    value_text=value["exerciseType"],
                ),
                GoogleMetricDTO(
                    "exercise_update_time",
                    "$.exercise.updateTime",
                    GoogleMetricState.VALUE,
                    value_text=value["updateTime"],
                ),
                GoogleMetricDTO(
                    "exercise_active_duration_seconds",
                    "$.exercise.activeDuration",
                    duration_state,
                    value_number=float(seconds) if seconds is not None else None,
                    value_text=duration if seconds is not None else None,
                    unit="seconds",
                ),
                GoogleMetricDTO(
                    "exercise_elapsed_seconds",
                    "$.exercise.interval",
                    GoogleMetricState.VALUE,
                    value_number=elapsed,
                    unit="seconds",
                ),
            )
            status = (
                GooglePayloadStatus.OK
                if duration_state is GoogleMetricState.VALUE
                else GooglePayloadStatus.PARTIAL
            )
            data_source = (
                _parse_data_source(point["dataSource"], "$.dataSource", context)
                if "dataSource" in point
                else GoogleDataSourceDTO()
            )
            if data_source.state is GoogleMetricState.INVALID or context.material_error:
                raise ValueError("exercise source metadata invalid")
            if context.partial:
                status = GooglePayloadStatus.PARTIAL
            point_identity = source_identity_from_point(point, query)
            record = GoogleRecordDTO(
                stream=GoogleStream.EXERCISE,
                idempotency_key="google-exercise-name-v1:"
                + hashlib.sha256(name.encode()).hexdigest(),
                temporal=interval.start,
                external_record_id=name,
                metrics=metrics,
                interval=interval,
                status=status,
                data_source=data_source,
            )
            content_hash = hashlib.sha256(canonical_json(record.as_dict()).encode()).hexdigest()
            record = replace(
                record,
                metrics=(
                    *metrics,
                    GoogleMetricDTO(
                        "exercise_projection_hash",
                        "$.exercise",
                        GoogleMetricState.VALUE,
                        value_text=content_hash,
                    ),
                ),
            )
            contexts.append(context)
            if (point_identity.source_kind, point_identity.source_instance_id) == (
                source_identity.source_kind,
                source_identity.source_instance_id,
            ):
                records.append(record)
        context = _ParseContext(
            [d for c in contexts for d in c.diagnostics],
            [field for c in contexts for field in c.unknown_fields],
            partial=any(c.partial for c in contexts),
        )
    except (TypeError, ValueError, OverflowError, UnicodeError, RecursionError, AttributeError):
        return GoogleNormalizationResult(
            GoogleStream.EXERCISE,
            query,
            GooglePayloadStatus.INVALID,
            source_identity=source_identity,
            source_contract_version=CONTRACT,
            normalization_contract_version=CONTRACT,
            diagnostics=(
                GoogleNormalizationDiagnostic(
                    "exercise_page_invalid", "Exercise page cannot be projected", severity="error"
                ),
            ),
        )
    status = (
        GooglePayloadStatus.PARTIAL
        if context.partial or any(r.status is GooglePayloadStatus.PARTIAL for r in records)
        else GooglePayloadStatus.OK
        if records
        else GooglePayloadStatus.EMPTY
    )
    return GoogleNormalizationResult(
        GoogleStream.EXERCISE,
        query,
        status,
        records=tuple(sorted(records, key=lambda r: r.external_record_id)),
        source_identity=source_identity,
        source_contract_version=CONTRACT,
        normalization_contract_version=CONTRACT,
        next_page_token_state=token_state,
        diagnostics=tuple(context.diagnostics),
        unknown_fields=tuple(context.unknown_fields),
    )


def exercise_revision_can_replace(session, existing, incoming) -> bool:
    """Provider updateTime, never receive order; equal conflicts stay unavailable."""
    from sqlalchemy import select

    from healthcheck.db.models import GoogleRecordMetric

    old = {
        m.metric_code: m
        for m in session.scalars(
            select(GoogleRecordMetric).where(GoogleRecordMetric.record_id == existing.id)
        )
    }
    new = {m.metric_code: m for m in incoming.metrics}
    try:
        previous = revision_key(old["exercise_update_time"].value_text)
        current = revision_key(new["exercise_update_time"].value_text)
    except (KeyError, ValueError, TypeError):
        existing.record_status = GooglePayloadStatus.INVALID.value
        existing.diagnostics_json = canonical_json([{"code": "exercise_revision_unknown"}])
        return False
    if current < previous:
        return False
    if current == previous:
        fingerprint = new["exercise_projection_hash"].value_text
        if old.get("exercise_projection_hash") is None or (
            old["exercise_projection_hash"].value_text != fingerprint
        ):
            existing.record_status = GooglePayloadStatus.INVALID.value
            existing.diagnostics_json = canonical_json([{"code": "exercise_revision_conflict"}])
        return False
    return True


def persist_exercise_page(session, *, payload_store, payload, received_at=None):
    """Persist one already-acquired page in the caller's atomic transaction.

    Each explicit source gets its own observation over the immutable full page;
    list position or family never merges physical-source projections. This is
    not an acquisition success checkpoint and does not imply page exhaustion.
    """
    from healthcheck.google.persistence import GooglePersistenceRepository
    from healthcheck.google.sync import query_level_source_identity

    raw = (
        bytes(payload)
        if isinstance(payload, (bytes, bytearray))
        else (canonical_json(payload).encode())
    )
    if len(raw) > MAX_PAGE_BYTES:
        raise ValueError("exercise page too large")
    fallback = query_level_source_identity(QUERY)
    identities = {fallback.source_instance_id: fallback}
    try:
        page = json.loads(raw, object_pairs_hook=_unique_keys)
        points = page.get("dataPoints", [])
        if isinstance(points, list) and 0 < len(points) <= MAX_PAGE_RECORDS:
            identities = {}
            for point in points:
                identity = source_identity_from_point(point, QUERY)
                identities[identity.source_instance_id] = identity
    except (ValueError, TypeError, AttributeError, RecursionError):
        pass
    repo = GooglePersistenceRepository(session, payload_store=payload_store)
    return tuple(
        repo.persist_result(
            normalize_exercise_payload(raw, source_identity=identities[key]),
            payload=raw,
            received_at=received_at,
        )
        for key in sorted(identities)
    )
