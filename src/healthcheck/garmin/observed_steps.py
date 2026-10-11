"""Bounded projection of saved Garmin account-level Steps observations.

This contract does not establish full-day coverage, device attribution, timezone,
or correction authority. The caller owns acquisition/runtime; this service reads saved bytes only.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    GarminPayloadObservation,
    GarminRawPayload,
    GarminSource,
    RawArtifact,
)
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.garmin.capabilities import CapabilityStatus, GarminStream
from healthcheck.garmin.normalization import (
    GarminFieldState,
    GarminMetricDTO,
    GarminRecordDTO,
    GarminSourceIdentity,
    GarminTemporalDTO,
    GarminTemporalPrecision,
)
from healthcheck.garmin.persistence import GarminCollectionScope, GarminSourceRecordRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore

CONTRACT_VERSION = "garmin-observed-daily-steps-v1"
METRIC_CODE = "observed_daily_steps"
MAX_ARTIFACTS = 1000
MAX_ARTIFACT_BYTES = 1024 * 1024
MAX_OBSERVATIONS = 4096
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


class SavedStepsEvidenceError(ValueError):
    """The bounded saved-evidence snapshot could not be verified completely."""


@dataclass(frozen=True, slots=True)
class SavedStepsEvidence:
    raw_payload_id: str
    raw_artifact_id: str
    content_hash: str
    observation_ids: tuple[str, ...]
    record_id: str
    state: GarminFieldState
    value: int | None


@dataclass(frozen=True, slots=True)
class ExcludedStepsArtifact:
    raw_payload_id: str
    observation_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class ObservedDailySteps:
    """One source/day's saved observations; never a fused or final daily total."""

    garmin_source_id: str
    calendar_date: date
    state: str
    value: int | None
    reason: str | None
    evidence: tuple[SavedStepsEvidence, ...]
    excluded_artifacts: tuple[ExcludedStepsArtifact, ...]
    metric_code: str = METRIC_CODE
    unit: str = "steps"
    attribution: str = "account"
    coverage: str = "unknown"
    device: str = "unknown"
    timezone: str = "unknown"
    finality: str = "unknown"


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-JSON numeric constant")


def _decode(content: bytes) -> tuple[dict[str, object] | None, str | None]:
    try:
        payload = json.loads(
            content, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (ValueError, UnicodeError, RecursionError):
        return None, "invalid_json"
    if not isinstance(payload, dict):
        return None, "unsupported_payload_shape"
    return payload, None


def _calendar_date(payload: dict[str, object]) -> date | None:
    value = payload.get("calendarDate")
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _metric(payload: dict[str, object]) -> GarminMetricDTO:
    value = payload.get("totalSteps")
    if "totalSteps" not in payload:
        state, reason = GarminFieldState.MISSING, "field_absent_in_payload"
    elif value is None:
        state, reason = GarminFieldState.NULL, "source_null"
    elif type(value) is int and value >= 0:
        state, reason = GarminFieldState.VALUE, None
    else:
        state, reason = GarminFieldState.INVALID, "expected_nonnegative_integer"
    return GarminMetricDTO(
        capability_code=METRIC_CODE,
        metric_code=METRIC_CODE,
        field_path="totalSteps",
        state=state,
        value=value if state is GarminFieldState.VALUE else None,
        unit="steps",
        reason=reason,
        capability_status=CapabilityStatus.UNVERIFIED,
        source_device_attributed=False,
    )


class SavedDailyStepsRepository:
    """Materialize a bounded snapshot from immutable saved daily-summary bytes.

    All eligible artifacts for the source are inspected: acquisition windows
    cannot substitute for the returned calendarDate. Bounds fail closed before
    inserting records, rather than returning a partial same-day answer. The
    caller owns the transaction and explicitly invokes this saved-evidence service.
    """

    def __init__(self, session: Session, *, payload_store: ContentAddressedGarminPayloadStore):
        self.session = session
        self.payload_store = payload_store
        self.records = GarminSourceRecordRepository(session)

    def project_saved_summary(
        self, garmin_source_id: str, observation_id: str, *, start_date: date, end_date: date
    ) -> ObservedDailySteps | None:
        """Project only the saved response day inside one normal refresh window."""
        if type(start_date) is not date or type(end_date) is not date:
            raise ValueError("saved Steps refresh requires civil dates")
        if not 1 <= (end_date - start_date).days + 1 <= 14:
            raise ValueError("saved Steps refresh window must contain 1 to 14 days")
        self._begin_snapshot()
        observation = self.session.get(GarminPayloadObservation, observation_id)
        if (
            observation is None
            or observation.garmin_source_id != garmin_source_id
            or observation.stream_code != "daily_health"
            or observation.payload_format != "json"
            or observation.source_filename != "daily_summary.json"
        ):
            raise SavedStepsEvidenceError("saved daily-summary acquisition mismatch")
        raw = self.session.get(GarminRawPayload, observation.garmin_raw_payload_id)
        artifact = self.session.get(RawArtifact, raw.raw_artifact_id) if raw else None
        if artifact is None or observation.raw_artifact_id != artifact.id:
            raise SavedStepsEvidenceError("saved daily-summary provenance mismatch")
        payload, _reason = self._read_summary(raw, artifact, garmin_source_id, MAX_ARTIFACT_BYTES)
        day = _calendar_date(payload) if payload is not None else None
        if day is None or not start_date <= day <= end_date:
            return None
        return self.project_day(garmin_source_id, day)

    def _begin_snapshot(self) -> None:
        if self.session.new or self.session.dirty or self.session.deleted:
            raise InvalidRequestError("saved Steps projection requires flushed session changes")
        # SQLite's legacy driver needs a physical BEGIN before compound reads.
        # The caller owns this transaction, including rollback of insert savepoints.
        connection = self.session.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")
        self.session.expire_all()

    def _read_summary(
        self, raw: GarminRawPayload | None, artifact: RawArtifact | None,
        source_id: str, max_bytes: int,
    ) -> tuple[dict[str, object] | None, str | None]:
        if (
            raw is None
            or artifact is None
            or raw.garmin_source_id != source_id
            or raw.stream_code != "daily_health"
            or raw.payload_format != "json"
            or artifact.content_hash != raw.content_hash
        ):
            raise SavedStepsEvidenceError("saved daily-summary provenance mismatch")
        if artifact.byte_size > max_bytes:
            raise SavedStepsEvidenceError("saved daily-summary byte bound exceeded")
        try:
            content = self.payload_store.read(artifact.relative_storage_path, max_bytes=max_bytes)
        except (OSError, ValueError) as exc:
            raise SavedStepsEvidenceError("saved daily-summary artifact unreadable") from exc
        if (
            len(content) != artifact.byte_size
            or hashlib.sha256(content).hexdigest() != raw.content_hash
        ):
            raise SavedStepsEvidenceError("saved daily-summary artifact integrity mismatch")
        return _decode(content)

    def project_day(
        self,
        garmin_source_id: str,
        calendar_date: date,
        *,
        max_artifacts: int = MAX_ARTIFACTS,
        max_artifact_bytes: int = MAX_ARTIFACT_BYTES,
        max_observations: int = MAX_OBSERVATIONS,
    ) -> ObservedDailySteps:
        if type(calendar_date) is not date:
            raise TypeError("calendar_date must be a date without a time")
        if type(max_artifacts) is not int or max_artifacts < 1:
            raise ValueError("max_artifacts must be a positive integer")
        if type(max_artifact_bytes) is not int or max_artifact_bytes < 1:
            raise ValueError("max_artifact_bytes must be a positive integer")
        if type(max_observations) is not int or max_observations < 1:
            raise ValueError("max_observations must be a positive integer")
        self._begin_snapshot()
        source = self.session.get(GarminSource, garmin_source_id)
        if source is None or source.provider_code != "garmin_connect":
            raise SavedStepsEvidenceError("unknown Garmin source")
        eligible = select(GarminPayloadObservation.garmin_raw_payload_id).where(
            GarminPayloadObservation.garmin_source_id == garmin_source_id,
            GarminPayloadObservation.stream_code == "daily_health",
            GarminPayloadObservation.payload_format == "json",
            GarminPayloadObservation.source_filename == "daily_summary.json",
        )
        raw_ids = list(
            self.session.scalars(
                eligible.distinct()
                .order_by(GarminPayloadObservation.garmin_raw_payload_id)
                .limit(max_artifacts + 1)
            )
        )
        if len(raw_ids) > max_artifacts:
            raise SavedStepsEvidenceError("saved daily-summary artifact bound exceeded")
        # Bound all source acquisitions before loading complete per-artifact lists.
        # Acquisition windows cannot exclude conflicting saved calendarDate evidence.
        observation_ids = list(
            self.session.scalars(
                select(GarminPayloadObservation.id)
                .where(
                    GarminPayloadObservation.garmin_source_id == garmin_source_id,
                    GarminPayloadObservation.stream_code == "daily_health",
                    GarminPayloadObservation.payload_format == "json",
                    GarminPayloadObservation.source_filename == "daily_summary.json",
                )
                .order_by(GarminPayloadObservation.id)
                .limit(max_observations + 1)
            )
        )
        if len(observation_ids) > max_observations:
            raise SavedStepsEvidenceError("saved daily-summary observation bound exceeded")
        prepared = []
        excluded = []
        for raw_id in raw_ids:
            observations = tuple(
                self.session.scalars(
                    select(GarminPayloadObservation)
                    .where(
                        GarminPayloadObservation.garmin_raw_payload_id == raw_id,
                        GarminPayloadObservation.garmin_source_id == garmin_source_id,
                        GarminPayloadObservation.stream_code == "daily_health",
                        GarminPayloadObservation.payload_format == "json",
                        GarminPayloadObservation.source_filename == "daily_summary.json",
                    )
                    .order_by(GarminPayloadObservation.id)
                )
            )
            observation_ids = tuple(item.id for item in observations)
            raw = self.session.get(GarminRawPayload, raw_id)
            artifact = self.session.get(RawArtifact, raw.raw_artifact_id) if raw else None
            if artifact is None or any(
                item.raw_artifact_id != artifact.id for item in observations
            ):
                raise SavedStepsEvidenceError("saved daily-summary provenance mismatch")
            payload, reason = self._read_summary(
                raw, artifact, garmin_source_id, max_artifact_bytes
            )
            day = _calendar_date(payload) if payload is not None else None
            if day is None:
                excluded.append(
                    ExcludedStepsArtifact(
                        raw_id, observation_ids, reason or "unsupported_calendar_date"
                    )
                )
            elif day == calendar_date:
                prepared.append((raw, artifact, observations, _metric(payload)))

        # The account identity is retained; device attribution is not promoted
        # from an existing source row into this metric's unverified contract.
        identity = GarminSourceIdentity(
            source_kind=source.source_kind,
            provider_code=source.provider_code,
            source_instance_id=source.source_instance_id,
            device_attributed=False,
        )
        evidence = []
        with self.session.begin_nested():
            for raw, artifact, observations, metric in prepared:
                key = hashlib.sha256(
                    json.dumps(
                        [
                            CONTRACT_VERSION,
                            garmin_source_id,
                            calendar_date.isoformat(),
                            raw.content_hash,
                        ],
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                row = self.records.get_by_idempotency_key(
                    garmin_source_id=garmin_source_id, idempotency_key=key
                )
                if row is None:
                    first = min(
                        observations,
                        key=lambda item: (restore_stored_utc(item.received_at), item.id),
                    )
                    row, _, _ = self.records.upsert(
                        garmin_source_id=garmin_source_id,
                        raw_payload_id=raw.id,
                        ingest_event_id=first.ingest_event_id,
                        seen_at=restore_stored_utc(first.received_at),
                        normalization_contract_version=CONTRACT_VERSION,
                        reconciliation_contract_version=CONTRACT_VERSION,
                        collection_scope=GarminCollectionScope(
                            METRIC_CODE,
                            "daily_health",
                            "day_singleton",
                            calendar_date,
                            calendar_date,
                            False,
                        ),
                        record=GarminRecordDTO(
                            stream=GarminStream.DAILY_HEALTH,
                            source=identity,
                            temporal=GarminTemporalDTO(
                                precision=GarminTemporalPrecision.DATE_ONLY,
                                local_date=calendar_date,
                                source_field="calendarDate",
                                local_date_source="calendarDate",
                            ),
                            idempotency_key=key,
                            metrics=(metric,),
                            source_path="$",
                        ),
                    )
                evidence.append(
                    SavedStepsEvidence(
                        raw.id,
                        artifact.id,
                        raw.content_hash,
                        tuple(item.id for item in observations),
                        row.id,
                        metric.state,
                        metric.value,
                    )
                )
        values = {item.value for item in evidence if item.state is GarminFieldState.VALUE}
        states = {item.state.value for item in evidence}
        if len(values) > 1:
            state, value, reason = "ambiguous", None, "divergent_saved_observations"
        elif values:
            state, value, reason = "value", next(iter(values)), None
        elif len(states) == 1:
            state, value, reason = next(iter(states)), None, "no_valid_saved_count"
        else:
            state, value, reason = "unavailable", None, "no_valid_saved_count"
        return ObservedDailySteps(
            garmin_source_id,
            calendar_date,
            state,
            value,
            reason,
            tuple(sorted(evidence, key=lambda item: item.content_hash)),
            tuple(excluded),
        )
