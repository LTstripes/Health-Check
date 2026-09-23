"""Garmin-native training evidence, bounded acquisition, and private read contract.

The requested date is acquisition context. Only provider dates/timestamps become
source chronology. Associated devices and activity recorders are not metric
producer claims. This module never publishes values to CLI output.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from numbers import Real
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
from healthcheck.db.models import (
    GarminPayloadObservation,
    GarminRecordMetric,
    GarminSourceRecord,
    GarminTrainingAcquisition,
    GarminTrainingObservationRecord,
    GarminTrainingSnapshot,
)
from healthcheck.db.repositories import repositories_for, restore_stored_utc
from healthcheck.external_runtime_lock import ExternalRuntimeOperationLock
from healthcheck.garmin.auth import (
    GarminAuthResult,
    _silence_provider_logging,
    classify_garmin_error,
)
from healthcheck.garmin.capabilities import GarminStream
from healthcheck.garmin.contracts import is_forbidden_payload_key
from healthcheck.garmin.normalization import (
    PROVIDER_SOURCE_KIND,
    GarminFieldState,
    GarminMetricDTO,
    GarminNormalizationResult,
    GarminParseStatus,
    GarminRecordDTO,
    GarminTemporalDTO,
    GarminTemporalPrecision,
    garmin_source_identity,
    parse_garmin_time,
    stable_garmin_idempotency_key,
)
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.garmin.sync import _disable_provider_retries
from healthcheck.runtime import prepare_runtime

TRAINING_CONTRACT_VERSION = "garmin-training-evidence-v1"
MAX_TRAINING_DAYS = 14
_TRAINING_SURFACES = ("training_status", "training_readiness")


@dataclass(frozen=True, slots=True)
class _Field:
    name: str
    path: tuple[str, ...]
    kind: str


_STATUS_FIELDS = (
    _Field("trainingStatus", ("trainingStatus",), "number"),
    _Field("trainingStatusFeedbackPhrase", ("trainingStatusFeedbackPhrase",), "text"),
    _Field("dailyTrainingLoadAcute", ("acuteTrainingLoadDTO", "dailyTrainingLoadAcute"), "number"),
    _Field(
        "dailyTrainingLoadChronic", ("acuteTrainingLoadDTO", "dailyTrainingLoadChronic"), "number"
    ),
    _Field("acwrPercent", ("acuteTrainingLoadDTO", "acwrPercent"), "number"),
    _Field(
        "dailyAcuteChronicWorkloadRatio",
        ("acuteTrainingLoadDTO", "dailyAcuteChronicWorkloadRatio"),
        "number",
    ),
    _Field("acwrStatus", ("acuteTrainingLoadDTO", "acwrStatus"), "text"),
)
_BALANCE_FIELDS = tuple(
    _Field(name, (name,), "number")
    for name in (
        "monthlyLoadAerobicLow",
        "monthlyLoadAerobicHigh",
        "monthlyLoadAnaerobic",
        "monthlyLoadAerobicLowTargetMin",
        "monthlyLoadAerobicLowTargetMax",
        "monthlyLoadAerobicHighTargetMin",
        "monthlyLoadAerobicHighTargetMax",
        "monthlyLoadAnaerobicTargetMin",
        "monthlyLoadAnaerobicTargetMax",
    )
)
_READINESS_FIELDS = tuple(
    _Field(name, (name,), kind)
    for name, kind in (
        ("score", "number"),
        ("level", "text"),
        ("recoveryTime", "number"),
        ("recoveryTimeFactorPercent", "number"),
        ("recoveryTimeFactorFeedback", "text"),
        ("recoveryTimeChangePhrase", "text"),
        ("acuteLoad", "number"),
        ("acwrFactorPercent", "number"),
        ("acwrFactorFeedback", "text"),
        ("inputContext", "text"),
        ("primaryActivityTracker", "boolean"),
        ("validSleep", "boolean"),
    )
)
_ACTIVITY_FIELDS = frozenset(
    {
        "activityTrainingLoad",
        "aerobicTrainingEffect",
        "anaerobicTrainingEffect",
        "trainingEffectLabel",
        "activityRecorderDeviceId",
    }
)


@dataclass(frozen=True, slots=True)
class TrainingProjection:
    result: GarminNormalizationResult
    associations: Mapping[str, tuple[str, str | None, str | None]]


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _provider_identifier(value: Any) -> str | None:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        text = str(value).strip()
        return text[:255] if text else None
    return None


def _source_day(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _field(item: Mapping[str, Any], spec: _Field, kind: str) -> GarminMetricDTO:
    value: Any = item
    for component in spec.path:
        if not isinstance(value, Mapping) or component not in value:
            state, value = GarminFieldState.MISSING, None
            break
        value = value[component]
    else:
        if value is None:
            state = GarminFieldState.NULL
        elif spec.kind == "number" and isinstance(value, Real) and not isinstance(value, bool):
            state = GarminFieldState.VALUE if math.isfinite(value) else GarminFieldState.INVALID
        elif spec.kind == "text" and isinstance(value, str) and value.strip():
            state, value = GarminFieldState.VALUE, value.strip()
        elif spec.kind == "boolean" and isinstance(value, bool):
            state, value = GarminFieldState.VALUE, "true" if value else "false"
        else:
            state, value = GarminFieldState.INVALID, None
    return GarminMetricDTO(
        capability_code="garmin_training",
        metric_code=spec.name,
        field_path=f"{kind}.{'.'.join(spec.path)}",
        state=state,
        value=value if state is GarminFieldState.VALUE else None,
        reason="shape_drift" if state is GarminFieldState.INVALID else None,
        source_device_attributed=False,
    )


def _record(
    *,
    source: Any,
    kind: str,
    item: Mapping[str, Any],
    specs: tuple[_Field, ...],
    device_key: str | None,
) -> GarminRecordDTO | None:
    metrics = tuple(_field(item, spec, kind) for spec in specs)
    if all(metric.state is GarminFieldState.MISSING for metric in metrics):
        return None
    source_day = _source_day(item.get("calendarDate"))
    timestamp = item.get("timestamp") if kind == "readiness" else None
    timestamp_local = item.get("timestampLocal") if kind == "readiness" else None
    local_temporal = (
        parse_garmin_time(timestamp_local, source_field="timestampLocal", field_semantics="local")
        if timestamp_local is not None
        else None
    )
    if timestamp is not None:
        utc_temporal = parse_garmin_time(timestamp, source_field="timestamp", field_semantics="utc")
        if utc_temporal.precision is not GarminTemporalPrecision.UNKNOWN:
            temporal = GarminTemporalDTO(
                precision=utc_temporal.precision,
                measured_at_utc=utc_temporal.measured_at_utc,
                local_wall_time=local_temporal.local_wall_time if local_temporal else None,
                source_local_timestamp=(
                    local_temporal.source_local_timestamp if local_temporal else None
                ),
                local_date=source_day
                or (local_temporal.local_date if local_temporal else None)
                or utc_temporal.local_date,
                source_field="timestamp",
                local_date_source=(
                    "calendarDate"
                    if source_day
                    else "timestampLocal"
                    if local_temporal and local_temporal.local_date
                    else "timestamp"
                ),
                source_local_field="timestampLocal" if local_temporal else None,
                source_utc_field="timestamp",
            )
        else:
            temporal = local_temporal or utc_temporal
    elif local_temporal is not None:
        temporal = GarminTemporalDTO(
            precision=local_temporal.precision,
            measured_at_utc=local_temporal.measured_at_utc,
            local_wall_time=local_temporal.local_wall_time,
            local_date=source_day or local_temporal.local_date,
            source_field="timestampLocal",
            local_date_source="calendarDate" if source_day else "timestampLocal",
            source_local_timestamp=local_temporal.source_local_timestamp,
            source_local_field="timestampLocal",
        )
    elif source_day is not None:
        temporal = GarminTemporalDTO(
            GarminTemporalPrecision.DATE_ONLY,
            local_date=source_day,
            source_field="calendarDate",
            local_date_source="calendarDate",
        )
    else:
        temporal = GarminTemporalDTO(GarminTemporalPrecision.UNKNOWN)
    device_id = _provider_identifier(item.get("deviceId"))
    # A source day or timestamp is required before a stable logical identity is
    # reused. Undated mostRecent structures remain content-addressed snapshots.
    source_token = (
        temporal.time_key()
        if temporal.precision is not GarminTemporalPrecision.UNKNOWN
        else _digest(item)
    )
    if kind == "load_balance" and source_day is None:
        source_token = _digest(item)
    record_id = f"{kind}:{device_key or device_id or 'account'}:{source_token}"
    key = stable_garmin_idempotency_key(source, GarminStream.DAILY_HEALTH, record_id)
    status = (
        GarminParseStatus.PARTIAL
        if any(metric.state is GarminFieldState.INVALID for metric in metrics)
        else GarminParseStatus.OK
    )
    return GarminRecordDTO(
        stream=GarminStream.DAILY_HEALTH,
        source=source,
        temporal=temporal,
        idempotency_key=key,
        record_id=record_id[:255],
        metrics=metrics,
        status=status,
        source_path=f"training.{kind}",
    )


def normalize_training_payload(surface: str, payload: Any) -> TrainingProjection:
    """Project only the Phase A-proven fields without using the request date."""
    if surface not in _TRAINING_SURFACES:
        raise ValueError("unsupported Garmin training surface")
    source = garmin_source_identity(source_kind=PROVIDER_SOURCE_KIND, device_attributed=False)
    rows: list[GarminRecordDTO] = []
    associations: dict[str, tuple[str, str | None, str | None]] = {}
    if payload is None:
        status = GarminParseStatus.PARTIAL
    elif payload == {} or payload == []:
        status = GarminParseStatus.EMPTY
    elif surface == "training_status" and isinstance(payload, Mapping):
        status = (
            GarminParseStatus.OK
            if "mostRecentTrainingStatus" in payload or "mostRecentTrainingLoadBalance" in payload
            else GarminParseStatus.INVALID
        )
        sections = (
            ("status", "mostRecentTrainingStatus", "latestTrainingStatusData", _STATUS_FIELDS),
            (
                "load_balance",
                "mostRecentTrainingLoadBalance",
                "metricsTrainingLoadBalanceDTOMap",
                _BALANCE_FIELDS,
            ),
        )
        for kind, parent, child, specs in sections:
            container = payload.get(parent)
            members = container.get(child) if isinstance(container, Mapping) else None
            if members is None:
                if parent in payload:
                    status = GarminParseStatus.PARTIAL
                continue
            if not isinstance(members, Mapping):
                status = GarminParseStatus.PARTIAL
                continue
            for key, item in members.items():
                if not isinstance(key, str) or not isinstance(item, Mapping):
                    status = GarminParseStatus.PARTIAL
                    continue
                row = _record(source=source, kind=kind, item=item, specs=specs, device_key=key)
                if row is None:
                    continue
                rows.append(row)
                associations[row.idempotency_key] = (
                    kind,
                    key[:255],
                    _provider_identifier(item.get("deviceId")),
                )
        if not rows and status is GarminParseStatus.OK:
            status = GarminParseStatus.EMPTY
    elif (
        surface == "training_readiness"
        and isinstance(payload, Sequence)
        and not isinstance(payload, (str, bytes))
    ):
        status = GarminParseStatus.OK
        for item in payload:
            if not isinstance(item, Mapping):
                status = GarminParseStatus.PARTIAL
                continue
            row = _record(
                source=source, kind="readiness", item=item, specs=_READINESS_FIELDS, device_key=None
            )
            if row is None:
                continue
            rows.append(row)
            associations[row.idempotency_key] = (
                "readiness",
                None,
                _provider_identifier(item.get("deviceId")),
            )
        if not rows and status is GarminParseStatus.OK:
            status = GarminParseStatus.EMPTY
    else:
        status = GarminParseStatus.INVALID
    # Conflicting duplicate identities are never silently collapsed.
    signatures: dict[str, str] = {}
    for row in rows:
        signature = _digest(row.as_dict())
        previous = signatures.setdefault(row.idempotency_key, signature)
        if previous != signature:
            raise ValueError("conflicting Garmin training snapshot identity")
    return TrainingProjection(
        GarminNormalizationResult(
            status=status,
            stream=GarminStream.DAILY_HEALTH,
            source=source,
            records=tuple(rows),
            contract_version=TRAINING_CONTRACT_VERSION,
        ),
        associations,
    )


def _reject_private_shape(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if is_forbidden_payload_key(key):
                raise ValueError("private or credential-shaped Garmin training payload")
            _reject_private_shape(child)
    elif isinstance(value, list):
        for child in value:
            _reject_private_shape(child)


def persist_training_payload(
    session: Session,
    store: ContentAddressedGarminPayloadStore,
    *,
    surface: str,
    requested_date: date,
    payload: Any,
    received_at: datetime,
    sync_run_id: str | None = None,
) -> tuple[int, int, str]:
    """Persist immutable raw observation, acquisition day and typed projections."""
    if surface not in _TRAINING_SURFACES:
        raise ValueError("unsupported Garmin training surface")
    _reject_private_shape(payload)
    projection = normalize_training_payload(surface, payload)
    response_state = (
        "null"
        if payload is None
        else "empty"
        if payload == {} or payload == []
        else "shape_drift"
        if projection.result.status is GarminParseStatus.INVALID
        else "value"
    )
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    window_start = datetime.combine(requested_date, datetime.min.time(), UTC)
    outcome = GarminPersistenceRepository(session, payload_store=store).persist_result(
        projection.result,
        payload=raw,
        stream_code=GarminStream.DAILY_HEALTH,
        source_identity=projection.result.source,
        source_contract_version=TRAINING_CONTRACT_VERSION,
        source_filename=f"{surface}.json",
        received_at=received_at,
        source_window_start_utc=window_start,
        source_window_end_utc=window_start + timedelta(days=1),
        sync_run_id=sync_run_id,
    )
    acquisition = session.get(GarminTrainingAcquisition, outcome.observation.id)
    if acquisition is None:
        session.add(
            GarminTrainingAcquisition(
                observation_id=outcome.observation.id,
                surface=surface,
                requested_date=requested_date,
                response_state=response_state,
            )
        )
    elif (
        acquisition.surface,
        acquisition.requested_date,
        acquisition.response_state,
    ) != (surface, requested_date, response_state):
        raise ValueError("training observation acquisition provenance conflict")
    for row in outcome.records:
        association = projection.associations[row.idempotency_key]
        kind, device_key, device_id = association
        attribution = "associated_device" if device_key or device_id else "account"
        marker = session.get(GarminTrainingSnapshot, row.id)
        if marker is None:
            session.add(
                GarminTrainingSnapshot(
                    record_id=row.id,
                    kind=kind,
                    provider_device_key=device_key,
                    provider_device_id=device_id,
                    attribution=attribution,
                )
            )
        elif (
            marker.kind,
            marker.provider_device_key,
            marker.provider_device_id,
            marker.attribution,
        ) != (kind, device_key, device_id, attribution):
            raise ValueError("training snapshot association conflict")
        membership = session.get(GarminTrainingObservationRecord, (outcome.observation.id, row.id))
        if membership is None:
            session.add(
                GarminTrainingObservationRecord(
                    observation_id=outcome.observation.id, record_id=row.id
                )
            )
    session.flush()
    return outcome.inserted_count, outcome.updated_count, projection.result.status.value


def read_training_evidence(
    session: Session, *, garmin_source_id: str, limit: int = 200
) -> tuple[dict[str, Any], ...]:
    """Deterministic private read contract for a later owner presentation layer."""
    if not 1 <= limit <= 500:
        raise ValueError("training read limit must be between 1 and 500")
    ordering = (
        GarminSourceRecord.source_local_date,
        GarminSourceRecord.source_timestamp_utc,
        GarminSourceRecord.id,
    )
    training_rows = list(
        session.scalars(
            select(GarminSourceRecord)
            .join(GarminTrainingSnapshot)
            .where(GarminSourceRecord.garmin_source_id == garmin_source_id)
            .where(GarminSourceRecord.projection_status == "current")
            .order_by(*ordering)
            .limit(limit)
        )
    )
    activity_rows = list(
        session.scalars(
            select(GarminSourceRecord)
            .join(GarminRecordMetric)
            .where(GarminSourceRecord.garmin_source_id == garmin_source_id)
            .where(GarminSourceRecord.projection_status == "current")
            .where(GarminSourceRecord.stream_code == GarminStream.ACTIVITY.value)
            .where(GarminRecordMetric.metric_code.in_(_ACTIVITY_FIELDS))
            .where(GarminRecordMetric.state == "value")
            .distinct()
            .order_by(*ordering)
            .limit(limit)
        )
    )
    rows = training_rows + activity_rows
    result: list[dict[str, Any]] = []
    for row in rows:
        marker = session.get(GarminTrainingSnapshot, row.id)
        if marker is None and row.stream_code != GarminStream.ACTIVITY.value:
            continue
        metrics = list(
            session.scalars(
                select(GarminRecordMetric).where(GarminRecordMetric.record_id == row.id)
            )
        )
        if marker is None:
            metrics = [metric for metric in metrics if metric.metric_code in _ACTIVITY_FIELDS]
            if not any(metric.state == "value" for metric in metrics):
                continue
            kind = "activity"
            recorder = next(
                (
                    metric.value_text
                    for metric in metrics
                    if metric.metric_code == "activityRecorderDeviceId" and metric.state == "value"
                ),
                None,
            )
            attribution = "activity_recorder" if recorder else "account"
            device_id = recorder
            device_key = None
        else:
            kind = marker.kind
            attribution = marker.attribution
            device_id = marker.provider_device_id
            device_key = marker.provider_device_key
        acquisitions = (
            list(
                session.scalars(
                    select(GarminTrainingAcquisition.requested_date)
                    .join(
                        GarminTrainingObservationRecord,
                        GarminTrainingObservationRecord.observation_id
                        == GarminTrainingAcquisition.observation_id,
                    )
                    .where(GarminTrainingObservationRecord.record_id == row.id)
                    .distinct()
                    .order_by(GarminTrainingAcquisition.requested_date)
                )
            )
            if marker is not None
            else []
        )
        result.append(
            {
                "contract_version": TRAINING_CONTRACT_VERSION,
                "record_id": row.id,
                "kind": kind,
                "requested_dates": tuple(day.isoformat() for day in acquisitions),
                "source_date": row.source_local_date.isoformat() if row.source_local_date else None,
                "source_timestamp_utc": restore_stored_utc(row.source_timestamp_utc).isoformat()
                if row.source_timestamp_utc is not None
                else None,
                "source_local_timestamp": row.source_local_timestamp,
                "attribution": attribution,
                "provider_device_key": device_key,
                "provider_device_id": device_id,
                "metric_producer": "unverified",
                "fields": {
                    metric.metric_code: {
                        "state": metric.state,
                        "value": metric.value_number
                        if metric.value_number is not None
                        else metric.value_text,
                    }
                    for metric in sorted(metrics, key=lambda value: value.metric_code)
                },
            }
        )
    result.sort(
        key=lambda item: (
            item["source_date"] or "",
            item["source_timestamp_utc"] or "",
            item["kind"],
            item["record_id"],
        )
    )
    return tuple(result[:limit])


def read_training_acquisitions(
    session: Session, *, garmin_source_id: str, limit: int = 200
) -> tuple[dict[str, Any], ...]:
    """Read acquisition outcome even when no typed snapshot was available."""
    if not 1 <= limit <= 500:
        raise ValueError("training read limit must be between 1 and 500")
    rows = session.execute(
        select(GarminTrainingAcquisition, GarminPayloadObservation)
        .join(
            GarminPayloadObservation,
            GarminPayloadObservation.id == GarminTrainingAcquisition.observation_id,
        )
        .where(GarminPayloadObservation.garmin_source_id == garmin_source_id)
        .order_by(
            GarminTrainingAcquisition.requested_date,
            GarminTrainingAcquisition.surface,
            GarminTrainingAcquisition.observation_id,
        )
        .limit(limit)
    )
    return tuple(
        {
            "surface": acquisition.surface,
            "requested_date": acquisition.requested_date.isoformat(),
            "response_state": acquisition.response_state,
            "record_count": observation.record_count,
        }
        for acquisition, observation in rows
    )


def validate_training_window(start: date | str, end: date | str) -> tuple[date, date]:
    start_day = date.fromisoformat(start) if isinstance(start, str) else start
    end_day = date.fromisoformat(end) if isinstance(end, str) else end
    if not isinstance(start_day, date) or not isinstance(end_day, date):
        raise ValueError("training window needs explicit dates")
    if end_day < start_day or (end_day - start_day).days >= MAX_TRAINING_DAYS:
        raise ValueError("training window must be one to fourteen days")
    return start_day, end_day


class GarminTrainingSync:
    """Explicit bounded readiness sampling plus one current status read.

    Status is queried only once at the end date because mostRecent does not
    establish historical backfill. Activities remain on the existing listing
    acquisition path in ordinary Garmin sync/backfill.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        client: Any | None,
        auth_result: GarminAuthResult,
    ) -> None:
        self.settings = settings
        self.client = client
        self.auth_result = auth_result

    def run(self, *, start: date | str, end: date | str) -> dict[str, Any]:
        first, last = validate_training_window(start, end)
        if self.client is None or not self.auth_result.ok:
            return _safe_report("reauth_required", 0, 0, 0, 0)
        paths = prepare_runtime(self.settings)
        with ExternalRuntimeOperationLock(paths):
            migrate_database(paths)
            engine = create_sqlite_engine(paths)
            factory = create_session_factory(engine)
            store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            try:
                start_utc = datetime.combine(first, datetime.min.time(), UTC)
                end_utc = datetime.combine(last + timedelta(days=1), datetime.min.time(), UTC)
                with factory() as session:
                    provenance = repositories_for(session)
                    provider = provenance.providers.get_or_create(
                        "garmin_connect", "Garmin Connect", "wearable"
                    )
                    run = provenance.sync.create_run(
                        provider_id=provider.id,
                        stream_code="garmin_training",
                        requested_start=start_utc,
                        requested_end=end_utc,
                    )
                    session.commit()
                    run_id = run.id
                inserted = updated = requests = 0
                failures = accepted = 0
                with _disable_provider_retries(self.client):
                    for surface, day in [("training_status", last)] + [
                        ("training_readiness", first + timedelta(days=index))
                        for index in range((last - first).days + 1)
                    ]:
                        method = getattr(self.client, f"get_{surface}", None)
                        if not callable(method):
                            failures += 1
                            continue
                        requests += 1
                        try:
                            with _silence_provider_logging():
                                payload = method(day.isoformat())
                            with factory() as session:
                                new, changed, parse_status = persist_training_payload(
                                    session,
                                    store,
                                    surface=surface,
                                    requested_date=day,
                                    payload=payload,
                                    received_at=datetime.now(UTC),
                                    sync_run_id=run_id,
                                )
                                session.commit()
                            inserted += new
                            updated += changed
                            if parse_status in {"invalid", "partial"}:
                                failures += 1
                            else:
                                accepted += 1
                        except Exception as exc:
                            error = classify_garmin_error(exc)
                            failures += 1
                            if error.error_class == "authentication":
                                break
                status = "succeeded" if failures == 0 else "partial" if accepted else "failed"
                with factory() as session:
                    repositories_for(session).sync.finish_run(
                        run_id,
                        status=status,
                        item_count=requests,
                        received_count=requests,
                        accepted_count=accepted,
                        failed_count=failures,
                        error_category="surface_failure" if failures else None,
                        diagnostic_reason="surface_failure" if failures else None,
                        actual_start=start_utc,
                        actual_end=end_utc,
                    )
                    session.commit()
                return _safe_report(
                    status,
                    requests,
                    inserted,
                    updated,
                    (last - first).days + 1,
                )
            finally:
                engine.dispose()


def _safe_report(
    status: str, requests: int, inserted: int, updated: int, days: int
) -> dict[str, Any]:
    return {
        "contract_version": TRAINING_CONTRACT_VERSION,
        "status": status,
        "request_count": requests,
        "readiness_requested_days": days,
        "status_historical_backfill": False,
        "inserted_count": inserted,
        "updated_count": updated,
        "raw_values_emitted": False,
        "private_identifiers_emitted": False,
    }
