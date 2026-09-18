"""Offline persistence for the R04 Google Health contract.

Accepts already-shaped synthetic identity, query context, raw bytes, and a
minimum typed-record shell.  It has no Google client, OAuth, network,
backfill, or analytics behavior, and it never writes ``garmin_*`` tables.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    GoogleNormalizationAttempt,
    GooglePayloadObservation,
    GooglePayloadStatus,
    GoogleRawPayload,
    GoogleRecordInterval,
    GoogleRecordMetric,
    GoogleRecordSourceEvidence,
    GoogleSleepFieldState,
    GoogleSleepInterval,
    GoogleSleepRecord,
    GoogleSource,
    GoogleSourceKind,
    GoogleSourceRecord,
    utc_now,
)
from healthcheck.db.repositories import canonical_json, repositories_for, restore_stored_utc
from healthcheck.google.contracts import (
    GOOGLE_INPUT_METHOD,
    GOOGLE_PROVIDER_CODE,
    GOOGLE_SOURCE_APPLICATION,
    NORMALIZATION_CONTRACT_VERSION,
    OBSERVATION_KEY_VERSION,
    PERSISTENCE_CONTRACT_VERSION,
    SOURCE_CONTRACT_VERSION,
    GoogleDataSourceDTO,
    GoogleIntervalDTO,
    GoogleMetricDTO,
    GoogleMetricState,
    GoogleQueryContext,
    GoogleQueryMode,
    GoogleRecordDTO,
    GoogleSleepStageDTO,
    GoogleSourceIdentity,
    GoogleStream,
    GoogleTemporalDTO,
)
from healthcheck.google.identity import (
    canonical_google_interval_identity,
    is_safe_google_interval_identity,
)
from healthcheck.google.storage import (
    ContentAddressedGooglePayloadStore,
    StoredGooglePayload,
    serialize_google_payload,
)

PATH_FREE_INSTANT_IDENTITY_PREFIX = "google-instant-sample-v1:"
UNIDENTIFIED_INSTANT_IDENTITY_PREFIX = "google-no-instant-identity-v1:"
PATH_FREE_HR_INTERVAL_IDENTITY_PREFIX = "google-hr-interval-v1:"
PATH_FREE_INSTANT_STREAMS = frozenset(
    {
        GoogleStream.HEART_RATE,
        GoogleStream.HRV,
        GoogleStream.SPO2,
        GoogleStream.RESPIRATORY_RATE_SLEEP,
    }
)

PROJECTION_CURRENT = "current"
RawGooglePayload = bytes | bytearray | Mapping[str, object]


@dataclass(frozen=True, slots=True)
class GooglePersistenceOutcome:
    """Identifiers and counts returned by one atomic persistence operation."""

    source: GoogleSource
    raw_payload: GoogleRawPayload
    observation: GooglePayloadObservation
    records: tuple[GoogleSourceRecord, ...]
    inserted_count: int
    updated_count: int
    replayed: bool
    ingest_batch_id: str | None = None
    ingest_event_id: str | None = None
    normalization_attempt: GoogleNormalizationAttempt | None = None


@dataclass(frozen=True, slots=True)
class GoogleInstantIdentityMigrationReport:
    """Aggregate result of a repository-driven legacy identity migration."""

    migrated: int = 0
    retired: int = 0
    conflicts: int = 0


class GoogleSourceRepository:
    """Persist explicit Google source/device identity through R01 provenance."""

    def __init__(self, session: Session):
        self.session = session
        self.provenance = repositories_for(session)

    def get(self, source_id: str) -> GoogleSource | None:
        return self.session.get(GoogleSource, source_id)

    def get_by_identity(
        self, *, provider_code: str, source_instance_id: str
    ) -> GoogleSource | None:
        return self.session.scalar(
            select(GoogleSource).where(
                GoogleSource.provider_code == provider_code,
                GoogleSource.source_instance_id == source_instance_id,
            )
        )

    def get_or_create(
        self,
        identity: GoogleSourceIdentity,
        *,
        input_method: str = GOOGLE_INPUT_METHOD,
        acquisition_source_id: str | None = None,
    ) -> GoogleSource:
        if not isinstance(identity, GoogleSourceIdentity):
            raise TypeError("Google source identity is required")
        if input_method != GOOGLE_INPUT_METHOD:
            raise ValueError("Google persistence uses provider_api as its acquisition method")

        provider = self.provenance.providers.get_or_create(
            GOOGLE_PROVIDER_CODE,
            "Google Health",
            "health_api",
        )
        device = None
        if identity.device_attributed:
            device = self.provenance.physical_devices.get_or_create(
                identity.device_code,
                manufacturer=identity.device_manufacturer,
                model=identity.device_model,
                instance_identifier=identity.device_uid,
                display_name=identity.device_model,
            )

        if acquisition_source_id is None:
            acquisition_source = self.provenance.acquisition_sources.get_or_create(
                provider_id=provider.id,
                physical_device_id=device.id if device is not None else None,
                input_method=input_method,
                source_application=GOOGLE_SOURCE_APPLICATION,
                configuration_snapshot={"persistence_contract": PERSISTENCE_CONTRACT_VERSION},
            )
        else:
            acquisition_source = self.provenance.acquisition_sources.get_by_id(
                acquisition_source_id
            )
            if acquisition_source is None:
                raise KeyError(f"unknown acquisition source {acquisition_source_id}")
            if acquisition_source.provider_id != provider.id:
                raise ValueError("Google acquisition source must belong to google_health")
            if acquisition_source.physical_device_id != (device.id if device is not None else None):
                raise ValueError("Google acquisition source device identity does not match")

        existing = self.get_by_identity(
            provider_code=identity.provider_code,
            source_instance_id=identity.source_instance_id,
        )
        if existing is not None:
            if (
                existing.source_kind != identity.source_kind.value
                or existing.provider_id != provider.id
                or existing.acquisition_source_id != acquisition_source.id
                or existing.physical_device_id != (device.id if device is not None else None)
                or existing.device_attributed != identity.device_attributed
                or existing.device_code != identity.device_code
                or existing.device_model != identity.device_model
                or existing.device_manufacturer != identity.device_manufacturer
                or existing.device_uid != identity.device_uid
                or existing.data_source_name != identity.data_source_name
                or existing.data_source_id != identity.data_source_id
            ):
                raise ValueError("Google source identity already has conflicting provenance")
            return existing

        source = GoogleSource(
            provider_id=provider.id,
            acquisition_source_id=acquisition_source.id,
            physical_device_id=device.id if device is not None else None,
            source_kind=identity.source_kind.value,
            provider_code=identity.provider_code,
            source_instance_id=identity.source_instance_id,
            data_source_name=identity.data_source_name,
            data_source_id=identity.data_source_id,
            platform=identity.platform,
            recording_method=identity.recording_method,
            device_attributed=identity.device_attributed,
            device_code=identity.device_code,
            device_manufacturer=identity.device_manufacturer,
            device_model=identity.device_model,
            device_uid=identity.device_uid,
            source_contract_version=identity.source_contract_version,
        )
        self.session.add(source)
        self.session.flush()
        return source


class GoogleRawPayloadRepository:
    """Repository for immutable Google payload metadata."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, payload_id: str) -> GoogleRawPayload | None:
        return self.session.get(GoogleRawPayload, payload_id)

    def get_by_key(
        self, *, google_source_id: str, stream_code: str, content_hash: str
    ) -> GoogleRawPayload | None:
        return self.session.scalar(
            select(GoogleRawPayload).where(
                GoogleRawPayload.google_source_id == google_source_id,
                GoogleRawPayload.stream_code == GoogleStream(stream_code).value,
                GoogleRawPayload.content_hash == content_hash.lower(),
            )
        )

    def create(
        self,
        *,
        google_source_id: str,
        raw_artifact_id: str,
        content_hash: str,
        stream_code: str | GoogleStream,
        payload_format: str,
        normalization_contract_version: str,
        parse_status: str | GooglePayloadStatus,
        record_count: int,
        source_contract_version: str | None = None,
        fixture_id: str | None = None,
        diagnostics_json: str | None = None,
        unknown_fields_json: str | None = None,
        ingest_event_id: str | None = None,
        sync_run_id: str | None = None,
        source_window_start_utc: datetime | None = None,
        source_window_end_utc: datetime | None = None,
        received_at: datetime | None = None,
    ) -> GoogleRawPayload:
        normalized_stream = GoogleStream(stream_code).value
        normalized_status = GooglePayloadStatus(parse_status).value
        normalized_format = _payload_format(payload_format)
        if record_count < 0:
            raise ValueError("Google payload record_count must be nonnegative")
        start = _as_utc(source_window_start_utc)
        end = _as_utc(source_window_end_utc)
        _validate_optional_interval(start, end, "source payload window")
        normalized_hash = _required_text(content_hash, "Google payload content hash").lower()
        existing = self.get_by_key(
            google_source_id=google_source_id,
            stream_code=normalized_stream,
            content_hash=normalized_hash,
        )
        if existing is not None:
            if existing.raw_artifact_id != raw_artifact_id:
                raise ValueError("Google payload hash is already linked to another raw artifact")
            return existing
        payload = GoogleRawPayload(
            google_source_id=google_source_id,
            raw_artifact_id=raw_artifact_id,
            ingest_event_id=ingest_event_id,
            sync_run_id=sync_run_id,
            stream_code=normalized_stream,
            content_hash=normalized_hash,
            payload_format=normalized_format,
            source_contract_version=source_contract_version,
            normalization_contract_version=_required_text(
                normalization_contract_version, "normalization contract version"
            ),
            fixture_id=fixture_id,
            parse_status=normalized_status,
            record_count=record_count,
            diagnostics_json=diagnostics_json,
            unknown_fields_json=unknown_fields_json,
            source_window_start_utc=start,
            source_window_end_utc=end,
            received_at=start_or_now(received_at),
        )
        self.session.add(payload)
        self.session.flush()
        return payload


class GooglePayloadObservationRepository:
    """Persist immutable acquisition/normalization observations."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, observation_id: str) -> GooglePayloadObservation | None:
        return self.session.get(GooglePayloadObservation, observation_id)

    def get_by_key(self, observation_key: str) -> GooglePayloadObservation | None:
        return self.session.scalar(
            select(GooglePayloadObservation).where(
                GooglePayloadObservation.observation_key
                == _required_text(observation_key, "Google observation key")
            )
        )

    def list(
        self,
        *,
        google_source_id: str | None = None,
        stream_code: str | GoogleStream | None = None,
        google_raw_payload_id: str | None = None,
    ) -> list[GooglePayloadObservation]:
        conditions = []
        if google_source_id is not None:
            conditions.append(GooglePayloadObservation.google_source_id == google_source_id)
        if stream_code is not None:
            conditions.append(
                GooglePayloadObservation.stream_code == GoogleStream(stream_code).value
            )
        if google_raw_payload_id is not None:
            conditions.append(
                GooglePayloadObservation.google_raw_payload_id == google_raw_payload_id
            )
        statement = (
            select(GooglePayloadObservation)
            .where(*conditions)
            .order_by(GooglePayloadObservation.received_at, GooglePayloadObservation.id)
        )
        return list(self.session.scalars(statement))

    def create(
        self,
        *,
        google_raw_payload_id: str,
        raw_artifact_id: str,
        google_source_id: str,
        observation_key: str,
        stream_code: str | GoogleStream,
        query_mode: str | GoogleQueryMode,
        data_source_family: str | None,
        payload_format: str,
        normalization_contract_version: str,
        parse_status: str | GooglePayloadStatus,
        record_count: int,
        source_contract_version: str | None = None,
        fixture_id: str | None = None,
        diagnostics_json: str | None = None,
        unknown_fields_json: str | None = None,
        ingest_event_id: str | None = None,
        sync_run_id: str | None = None,
        source_window_start_utc: datetime | None = None,
        source_window_end_utc: datetime | None = None,
        source_filename: str | None = None,
        received_at: datetime | None = None,
    ) -> GooglePayloadObservation:
        normalized_stream = GoogleStream(stream_code).value
        normalized_status = GooglePayloadStatus(parse_status).value
        normalized_format = _payload_format(payload_format)
        normalized_key = _required_text(observation_key, "Google observation key")
        if len(normalized_key) < 32:
            raise ValueError("Google observation key must be at least 32 characters")
        if record_count < 0:
            raise ValueError("Google observation record_count must be nonnegative")
        start = _as_utc(source_window_start_utc)
        end = _as_utc(source_window_end_utc)
        _validate_optional_interval(start, end, "source observation window")
        existing = self.get_by_key(normalized_key)
        if existing is not None:
            if (
                existing.google_raw_payload_id != google_raw_payload_id
                or existing.raw_artifact_id != raw_artifact_id
                or existing.google_source_id != google_source_id
                or existing.query_mode != GoogleQueryMode(query_mode).value
                or existing.data_source_family != data_source_family
            ):
                raise ValueError("Google observation key is linked to conflicting provenance")
            if ingest_event_id is not None and existing.ingest_event_id != ingest_event_id:
                raise ValueError("Google observation replay has a conflicting ingest event")
            return existing
        observation = GooglePayloadObservation(
            google_raw_payload_id=google_raw_payload_id,
            raw_artifact_id=raw_artifact_id,
            google_source_id=google_source_id,
            ingest_event_id=ingest_event_id,
            sync_run_id=sync_run_id,
            observation_key=normalized_key,
            stream_code=normalized_stream,
            query_mode=GoogleQueryMode(query_mode).value,
            data_source_family=data_source_family,
            payload_format=normalized_format,
            source_contract_version=source_contract_version,
            normalization_contract_version=_required_text(
                normalization_contract_version, "normalization contract version"
            ),
            fixture_id=fixture_id,
            parse_status=normalized_status,
            record_count=record_count,
            diagnostics_json=diagnostics_json,
            unknown_fields_json=unknown_fields_json,
            source_window_start_utc=start,
            source_window_end_utc=end,
            source_filename=source_filename,
            received_at=start_or_now(received_at),
        )
        self.session.add(observation)
        self.session.flush()
        return observation


class GoogleNormalizationAttemptRepository:
    """Append-only repository for bounded normalization-version attempts."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, attempt_id: str) -> GoogleNormalizationAttempt | None:
        return self.session.get(GoogleNormalizationAttempt, attempt_id)

    def get_by_key(self, attempt_key: str) -> GoogleNormalizationAttempt | None:
        return self.session.scalar(
            select(GoogleNormalizationAttempt).where(
                GoogleNormalizationAttempt.attempt_key
                == _required_text(attempt_key, "Google normalization attempt key")
            )
        )

    def list_for_observation(self, observation_id: str) -> list[GoogleNormalizationAttempt]:
        return list(
            self.session.scalars(
                select(GoogleNormalizationAttempt)
                .where(GoogleNormalizationAttempt.observation_id == observation_id)
                .order_by(
                    GoogleNormalizationAttempt.normalization_contract_version,
                    GoogleNormalizationAttempt.attempted_at,
                    GoogleNormalizationAttempt.id,
                )
            )
        )

    def create(
        self,
        *,
        google_source_id: str,
        google_raw_payload_id: str,
        observation_id: str,
        attempt_key: str,
        stream_code: str | GoogleStream,
        query_mode: str | GoogleQueryMode,
        data_source_family: str | None,
        source_contract_version: str | None,
        normalization_contract_version: str,
        parse_status: str | GooglePayloadStatus,
        record_count: int,
        projection_fingerprint: str,
        projection_json: str,
        diagnostics_json: str | None,
        unknown_fields_json: str | None,
        attempted_at: datetime | None = None,
    ) -> GoogleNormalizationAttempt:
        normalized_key = _required_text(attempt_key, "Google normalization attempt key")
        if len(normalized_key) < 32:
            raise ValueError("Google normalization attempt key must be at least 32 characters")
        if record_count < 0:
            raise ValueError("Google normalization attempt record_count must be nonnegative")
        existing = self.get_by_key(normalized_key)
        if existing is not None:
            for field_name, expected in {
                "google_source_id": google_source_id,
                "google_raw_payload_id": google_raw_payload_id,
                "observation_id": observation_id,
                "stream_code": GoogleStream(stream_code).value,
                "query_mode": GoogleQueryMode(query_mode).value,
                "data_source_family": data_source_family,
                "normalization_contract_version": normalization_contract_version,
                "parse_status": GooglePayloadStatus(parse_status).value,
                "record_count": record_count,
                "projection_fingerprint": projection_fingerprint,
                "projection_json": projection_json,
            }.items():
                if getattr(existing, field_name) != expected:
                    raise ValueError(
                        "Google normalization attempt key is linked to conflicting evidence"
                    )
            return existing
        attempt = GoogleNormalizationAttempt(
            google_source_id=google_source_id,
            google_raw_payload_id=google_raw_payload_id,
            observation_id=observation_id,
            attempt_key=normalized_key,
            stream_code=GoogleStream(stream_code).value,
            query_mode=GoogleQueryMode(query_mode).value,
            data_source_family=data_source_family,
            source_contract_version=source_contract_version,
            normalization_contract_version=_required_text(
                normalization_contract_version, "normalization contract version"
            ),
            parse_status=GooglePayloadStatus(parse_status).value,
            record_count=record_count,
            projection_fingerprint=_required_text(
                projection_fingerprint, "Google projection fingerprint"
            ),
            projection_json=_required_text(projection_json, "Google projection JSON"),
            diagnostics_json=diagnostics_json,
            unknown_fields_json=unknown_fields_json,
            attempted_at=start_or_now(attempted_at),
        )
        self.session.add(attempt)
        self.session.flush()
        return attempt


class GoogleSourceRecordRepository:
    """Upsert current typed projections while preserving raw payload history."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, record_id: str) -> GoogleSourceRecord | None:
        return self.session.get(GoogleSourceRecord, record_id)

    def get_by_identity_key(
        self, *, google_source_id: str, record_identity_key: str
    ) -> GoogleSourceRecord | None:
        return self.session.scalar(
            select(GoogleSourceRecord).where(
                GoogleSourceRecord.google_source_id == google_source_id,
                GoogleSourceRecord.record_identity_key == record_identity_key,
            )
        )

    def metrics_for(self, record_id: str) -> list[GoogleRecordMetric]:
        return list(
            self.session.scalars(
                select(GoogleRecordMetric)
                .where(GoogleRecordMetric.record_id == record_id)
                .order_by(GoogleRecordMetric.metric_code, GoogleRecordMetric.id)
            )
        )

    def intervals_for(self, record_id: str) -> list[GoogleRecordInterval]:
        return list(
            self.session.scalars(
                select(GoogleRecordInterval)
                .where(GoogleRecordInterval.record_id == record_id)
                .order_by(GoogleRecordInterval.interval_kind, GoogleRecordInterval.ordinal)
            )
        )

    def sleep_intervals_for(self, record_id: str) -> list[GoogleSleepInterval]:
        return list(
            self.session.scalars(
                select(GoogleSleepInterval)
                .join(
                    GoogleSleepRecord,
                    GoogleSleepRecord.record_id == GoogleSleepInterval.sleep_record_id,
                )
                .where(GoogleSleepRecord.record_id == record_id)
                .order_by(GoogleSleepInterval.interval_kind, GoogleSleepInterval.ordinal)
            )
        )

    def source_evidence_for(self, record_id: str) -> GoogleRecordSourceEvidence | None:
        return self.session.get(GoogleRecordSourceEvidence, record_id)

    def migrate_path_free_instant_identities(
        self,
        *,
        seen_at: datetime | None = None,
        google_source_id: str | None = None,
    ) -> GoogleInstantIdentityMigrationReport:
        """Re-key legacy Google instant/HR interval rows through the repository.

        No raw payload, observation, artifact, metric, or interval row is
        deleted.  Duplicate current projections are retired deterministically;
        same-epoch ambiguity retires the whole group with
        ``identity_conflict`` and leaves no invented winner.  Re-running this
        method is a no-op after the first successful pass.
        """

        retired_at = start_or_now(seen_at)
        statement = select(GoogleSourceRecord).where(
            GoogleSourceRecord.projection_status == PROJECTION_CURRENT,
            GoogleSourceRecord.stream_code.in_(
                tuple(stream.value for stream in PATH_FREE_INSTANT_STREAMS)
            ),
        )
        if google_source_id is not None:
            statement = statement.where(GoogleSourceRecord.google_source_id == google_source_id)
        rows = list(self.session.scalars(statement).all())
        groups: dict[tuple[object, ...], list[GoogleSourceRecord]] = {}
        for row in rows:
            group_key = self._migration_group_key(row)
            if group_key is not None:
                groups.setdefault(group_key, []).append(row)

        report = GoogleInstantIdentityMigrationReport()
        for group in groups.values():
            migrated, retired, conflicts = self._migrate_identity_group(group, retired_at)
            report = replace(
                report,
                migrated=report.migrated + migrated,
                retired=report.retired + retired,
                conflicts=report.conflicts + conflicts,
            )
        self.session.flush()
        return report

    # Compatibility aliases for callers that name this operation as a
    # repository migration or legacy-duplicate retirement.
    migrate_legacy_instant_identities = migrate_path_free_instant_identities
    retire_legacy_instant_duplicates = migrate_path_free_instant_identities

    def _migration_group_key(self, row: GoogleSourceRecord) -> tuple[object, ...] | None:
        context = (
            row.google_source_id,
            row.stream_code,
            row.query_mode,
            row.data_source_family,
        )
        if row.stream_code in {stream.value for stream in PATH_FREE_INSTANT_STREAMS}:
            if row.stream_code == GoogleStream.HEART_RATE.value and row.query_mode in {
                GoogleQueryMode.ROLL_UP.value,
                GoogleQueryMode.DAILY_ROLL_UP.value,
            }:
                interval = self.session.scalar(
                    select(GoogleRecordInterval).where(
                        GoogleRecordInterval.record_id == row.id,
                        GoogleRecordInterval.ordinal == 0,
                    )
                )
                if interval is None or not is_safe_google_interval_identity(interval):
                    return (*context, "unsafe", row.id)
                return (*context, "interval", _stored_interval_identity(interval))
            timestamp = _datetime_key(row.source_timestamp_utc)
            if timestamp is None or row.temporal_precision != "instant":
                return (*context, "unsafe", row.id)
            return (*context, "instant", timestamp.isoformat())
        return None

    def _record_observation_epoch(
        self, row: GoogleSourceRecord
    ) -> tuple[str | None, datetime | None, str | None]:
        """Read persisted refresh provenance for ordering legacy projections."""

        return self._observation_epoch(row.observation_id, row.projection_observed_at)

    def _observation_epoch(
        self, observation_id: str | None, fallback_at: datetime | None
    ) -> tuple[str | None, datetime | None, str | None]:
        observation = (
            self.session.get(GooglePayloadObservation, observation_id)
            if observation_id
            else None
        )
        if observation is None:
            return None, None, None
        raw_payload = self.session.get(GoogleRawPayload, observation.google_raw_payload_id)
        sync_run_id = observation.sync_run_id or (
            raw_payload.sync_run_id if raw_payload is not None else None
        )
        observed_at = _datetime_key(observation.received_at) or _datetime_key(fallback_at)
        if observed_at is None:
            observed_at = _datetime_key(fallback_at)
        return sync_run_id, observed_at, observation.id

    def _migrate_identity_group(
        self, rows: Sequence[GoogleSourceRecord], retired_at: datetime
    ) -> tuple[int, int, int]:
        if not rows:
            return 0, 0, 0
        row = rows[0]
        if (
            row.record_status == GooglePayloadStatus.INVALID.value
            or self._migration_group_key(row)[-2] == "unsafe"
        ):
            for value in rows:
                value.projection_status = "retired"
                value.retired_at = retired_at
                value.retire_reason = "identity_conflict"
            return 0, len(rows), 1
        stream = GoogleStream(row.stream_code)
        if row.query_mode in {GoogleQueryMode.ROLL_UP.value, GoogleQueryMode.DAILY_ROLL_UP.value}:
            interval = self.session.scalar(
                select(GoogleRecordInterval).where(
                    GoogleRecordInterval.record_id == row.id,
                    GoogleRecordInterval.ordinal == 0,
                )
            )
            if interval is None:
                return 0, 0, 0
            canonical_idempotency = _canonical_interval_idempotency(
                stream, _stored_interval_identity(interval)
            )
        else:
            timestamp = _datetime_key(row.source_timestamp_utc)
            if timestamp is None:
                return 0, 0, 0
            canonical_idempotency = _canonical_instant_idempotency(stream, timestamp)
        target_key = build_google_record_identity_key(
            stream_code=stream,
            query_mode=row.query_mode,
            data_source_family=row.data_source_family,
            idempotency_key=canonical_idempotency,
            source_timestamp_utc=(
                None
                if row.query_mode
                in {GoogleQueryMode.ROLL_UP.value, GoogleQueryMode.DAILY_ROLL_UP.value}
                else timestamp
            ),
            interval=(
                interval
                if row.query_mode
                in {GoogleQueryMode.ROLL_UP.value, GoogleQueryMode.DAILY_ROLL_UP.value}
                else None
            ),
        )
        signatures = {
            _record_revision_fingerprint(self.session, value) for value in rows
        }
        if len(signatures) > 1:
            epochs = [self._record_observation_epoch(value) for value in rows]
            if any(epoch[1] is None for epoch in epochs):
                for value in rows:
                    value.projection_status = "retired"
                    value.retired_at = retired_at
                    value.retire_reason = "identity_conflict"
                return 0, len(rows), 1
            latest = max((value[1] for value in epochs if value[1] is not None), default=None)
            latest_rows = [
                value for value, epoch in zip(rows, epochs) if epoch[1] == latest
            ]
            if (
                latest is None
                or len(latest_rows) != 1
            ):
                for value in rows:
                    value.projection_status = "retired"
                    value.retired_at = retired_at
                    value.retire_reason = "identity_conflict"
                return 0, len(rows), 1
            winner = latest_rows[0]
        else:
            winner = max(
                rows,
                key=lambda value: (
                    _datetime_key(value.projection_observed_at)
                    or _datetime_key(value.last_seen_at)
                    or datetime.min.replace(tzinfo=UTC),
                    value.created_at,
                    value.id,
                ),
            )

        # Free a target key held by a loser before assigning it to the winner.
        for value in rows:
            if value.id != winner.id and value.record_identity_key == target_key:
                value.record_identity_key = f"google-retired-legacy-v1:{value.id}"
        self.session.flush()
        changed = (
            winner.record_identity_key != target_key
            or winner.idempotency_key != canonical_idempotency
        )
        winner.record_identity_key = target_key
        winner.idempotency_key = canonical_idempotency
        retired = 0
        for value in rows:
            if value.id == winner.id:
                continue
            value.projection_status = "retired"
            value.retired_at = retired_at
            value.retire_reason = "superseded_logical_sample"
            retired += 1
        return int(changed), retired, 0

    def upsert(
        self,
        *,
        google_source_id: str,
        raw_payload_id: str,
        observation_id: str,
        record: GoogleRecordDTO,
        query: GoogleQueryContext,
        ingest_event_id: str | None,
        seen_at: datetime,
        source_contract_version: str | None,
        normalization_contract_version: str,
    ) -> tuple[GoogleSourceRecord, bool, bool]:
        identity_key = build_google_record_identity_key(
            stream_code=record.stream,
            query_mode=query.query_mode,
            data_source_family=query.data_source_family,
            idempotency_key=record.idempotency_key,
            external_record_id=record.external_record_id,
            source_timestamp_utc=record.temporal.measured_at_utc,
            interval=record.interval,
        )
        values = _record_values(
            google_source_id=google_source_id,
            raw_payload_id=raw_payload_id,
            observation_id=observation_id,
            record=record,
            query=query,
            record_identity_key=identity_key,
            ingest_event_id=ingest_event_id,
            source_contract_version=source_contract_version,
            normalization_contract_version=normalization_contract_version,
            seen_at=seen_at,
        )
        existing = self.get_by_identity_key(
            google_source_id=google_source_id, record_identity_key=identity_key
        )
        if record.stream is GoogleStream.SLEEP and record.external_record_id:
            existing = self._find_or_adopt_sleep_identity(
                google_source_id=google_source_id,
                external_record_id=record.external_record_id,
                logical_identity_key=identity_key,
                exact=existing,
                seen_at=seen_at,
            )
        if existing is None:
            row = GoogleSourceRecord(**values)
            self.session.add(row)
            self.session.flush()
            self._upsert_typed_child(row, record)
            self._upsert_source_evidence(row.id, record.data_source)
            self._upsert_metrics(row.id, record.metrics)
            return row, True, False

        if record.stream is GoogleStream.SLEEP and not _sleep_revision_can_replace(
            self.session, existing, record
        ):
            return existing, False, False

        projected = _datetime_key(existing.projection_observed_at) or _datetime_key(
            existing.last_seen_at
        )
        if (
            record.idempotency_key.startswith(
                (PATH_FREE_INSTANT_IDENTITY_PREFIX, PATH_FREE_HR_INTERVAL_IDENTITY_PREFIX)
            )
            and _record_revision_fingerprint(self.session, existing)
            != _record_revision_fingerprint(self.session, record=record)
        ):
            existing_sync, existing_epoch, existing_observation_id = (
                self._record_observation_epoch(existing)
            )
            incoming_sync, incoming_epoch, incoming_observation_id = self._observation_epoch(
                observation_id, seen_at
            )
            same_refresh = (
                existing_sync is not None
                and existing_sync == incoming_sync
                or existing_observation_id is not None
                and existing_observation_id == incoming_observation_id
                or existing_sync is None
                and incoming_sync is None
                and existing_epoch is not None
                and existing_epoch == incoming_epoch
            )
            ordering_known = (
                existing_epoch is not None
                and incoming_epoch is not None
                and (
                    existing_sync is None
                    and incoming_sync is None
                    or existing_sync is not None
                    and incoming_sync is not None
                )
            )
            if (
                same_refresh
                or not ordering_known
                or incoming_epoch == existing_epoch
            ):
                # Equal/co-observed epochs with divergent metric/revision
                # evidence have no deterministic winner.  Keep all immutable
                # provenance, invalidate the projection, and wait for an
                # unambiguous later epoch instead of silently replacing health
                # history.
                existing.record_status = GooglePayloadStatus.INVALID.value
                existing.diagnostics_json = _append_identity_conflict(
                    existing.diagnostics_json
                )
                self.session.flush()
                return existing, False, False
        current_version = _normalization_version_rank(existing.normalization_contract_version)
        incoming_version = _normalization_version_rank(normalization_contract_version)
        if current_version > incoming_version or (
            record.stream is not GoogleStream.SLEEP
            and current_version == incoming_version
            and projected is not None
            and seen_at < projected
        ):
            return existing, False, False
        for field_name, value in values.items():
            if field_name in {"id", "created_at"}:
                continue
            setattr(existing, field_name, value)
        existing.updated_at = seen_at
        self.session.flush()
        self._upsert_typed_child(existing, record)
        self._upsert_source_evidence(existing.id, record.data_source)
        self._upsert_metrics(existing.id, record.metrics)
        return existing, False, True

    def _find_or_adopt_sleep_identity(
        self,
        *,
        google_source_id: str,
        external_record_id: str,
        logical_identity_key: str,
        exact: GoogleSourceRecord | None,
        seen_at: datetime,
    ) -> GoogleSourceRecord | None:
        """Return one current logical sleep row and retire legacy duplicates.

        Before this repair, the same stable provider id could have one row per
        interval revision (and per query context).  Reusing the strongest
        existing row preserves its id and typed evidence; losing rows remain
        auditable and are only marked retired.
        """

        candidates = list(
            self.session.scalars(
                select(GoogleSourceRecord).where(
                    GoogleSourceRecord.google_source_id == google_source_id,
                    GoogleSourceRecord.stream_code == GoogleStream.SLEEP.value,
                    GoogleSourceRecord.external_record_id == external_record_id,
                    GoogleSourceRecord.projection_status == PROJECTION_CURRENT,
                )
            )
        )
        if (
            exact is not None
            and exact.projection_status == PROJECTION_CURRENT
            and all(candidate.id != exact.id for candidate in candidates)
        ):
            candidates.append(exact)
        winner = _select_sleep_legacy_winner(self.session, candidates)
        if winner is None and exact is not None:
            winner = exact
        if winner is None:
            return None
        if winner.projection_status != PROJECTION_CURRENT:
            winner.projection_status = PROJECTION_CURRENT
            winner.retired_at = None
            winner.retire_reason = None
        if winner.record_identity_key != logical_identity_key:
            winner.record_identity_key = logical_identity_key
        for candidate in candidates:
            if candidate.id == winner.id:
                continue
            candidate.projection_status = "retired"
            candidate.retired_at = seen_at
            candidate.retire_reason = "superseded_logical_session"
        self.session.flush()
        return winner

    def _upsert_typed_child(self, row: GoogleSourceRecord, record: GoogleRecordDTO) -> None:
        if record.stream is GoogleStream.SLEEP:
            typed = self.session.get(GoogleSleepRecord, row.id)
            wake_date = record.wake_date or record.temporal.local_date
            if typed is None:
                typed = GoogleSleepRecord(record_id=row.id, wake_date=wake_date)
                self.session.add(typed)
                self.session.flush()
            elif wake_date is not None:
                typed.wake_date = wake_date

            _upsert_sleep_field_states(
                self.session,
                sleep_record_id=row.id,
                sleep_interval_state=(
                    record.sleep_interval.state
                    if record.sleep_interval is not None
                    else GoogleMetricState.MISSING
                ),
                sleep_stages_state=record.sleep_stages_state,
                out_of_bed_state=record.out_of_bed_state,
            )
            if (
                record.sleep_interval is not None
                and record.sleep_interval.state is GoogleMetricState.VALUE
            ):
                _upsert_sleep_interval(
                    self.session,
                    sleep_record_id=row.id,
                    interval=record.sleep_interval,
                    ordinal=0,
                )
            elif (
                record.sleep_interval is not None
                and record.sleep_interval.state is GoogleMetricState.NULL
            ):
                _clear_sleep_intervals(
                    self.session,
                    sleep_record_id=row.id,
                    interval_kind="sleep_session",
                )
            if record.sleep_stages_state is GoogleMetricState.VALUE:
                _replace_sleep_intervals(
                    self.session,
                    sleep_record_id=row.id,
                    interval_kind="sleep_stage",
                    intervals=record.sleep_stages,
                )
            elif record.sleep_stages_state is GoogleMetricState.NULL:
                _clear_sleep_intervals(
                    self.session,
                    sleep_record_id=row.id,
                    interval_kind="sleep_stage",
                )
            if record.out_of_bed_state is GoogleMetricState.VALUE:
                _replace_sleep_intervals(
                    self.session,
                    sleep_record_id=row.id,
                    interval_kind="sleep_out_of_bed",
                    intervals=record.out_of_bed_segments,
                )
            elif record.out_of_bed_state is GoogleMetricState.NULL:
                _clear_sleep_intervals(
                    self.session,
                    sleep_record_id=row.id,
                    interval_kind="sleep_out_of_bed",
                )
            return

        if record.interval is not None:
            _upsert_record_interval(self.session, record_id=row.id, interval=record.interval)

    def _upsert_source_evidence(
        self, record_id: str, data_source: GoogleDataSourceDTO | None
    ) -> None:
        if data_source is None:
            return
        evidence = self.session.get(GoogleRecordSourceEvidence, record_id)
        if evidence is None:
            self.session.add(
                GoogleRecordSourceEvidence(
                    record_id=record_id,
                    state=data_source.state.value,
                    field_path=data_source.field_path,
                    evidence_json=canonical_json(data_source.as_dict()),
                )
            )
            return
        if data_source.state is GoogleMetricState.MISSING:
            return
        merged = _merge_data_source_evidence(evidence.evidence_json, data_source.as_dict())
        evidence.state = str(merged["state"])
        evidence.field_path = str(merged["field_path"])
        evidence.evidence_json = canonical_json(merged)

    def _upsert_metrics(self, record_id: str, metrics: Iterable[GoogleMetricDTO]) -> None:
        incoming = {metric.metric_code: metric for metric in metrics}
        existing = {
            metric.metric_code: metric
            for metric in self.session.scalars(
                select(GoogleRecordMetric).where(GoogleRecordMetric.record_id == record_id)
            )
        }
        for metric in incoming.values():
            stored = existing.get(metric.metric_code)
            if metric.state is GoogleMetricState.MISSING and stored is not None:
                continue
            values = {
                "metric_code": metric.metric_code,
                "field_path": metric.field_path,
                "state": GoogleMetricState(metric.state).value,
                "value_number": metric.value_number
                if metric.state is GoogleMetricState.VALUE
                else None,
                "value_text": (
                    metric.value_text if metric.state is GoogleMetricState.VALUE else None
                ),
                "unit": metric.unit,
                "reason": metric.reason,
                "collection_json": metric.collection_json
                if metric.state is GoogleMetricState.VALUE
                else None,
            }
            if stored is None:
                self.session.add(GoogleRecordMetric(record_id=record_id, **values))
            else:
                for field_name, value in values.items():
                    setattr(stored, field_name, value)


class GooglePersistenceRepository:
    """Atomic raw-payload plus typed-projection persistence facade."""

    def __init__(
        self,
        session: Session,
        *,
        payload_store: ContentAddressedGooglePayloadStore | None = None,
    ):
        self.session = session
        self.provenance = repositories_for(session)
        self.sources = GoogleSourceRepository(session)
        self.raw_payloads = GoogleRawPayloadRepository(session)
        self.observations = GooglePayloadObservationRepository(session)
        self.attempts = GoogleNormalizationAttemptRepository(session)
        self.records = GoogleSourceRecordRepository(session)
        self.payload_store = payload_store

    def migrate_path_free_instant_identities(
        self, *, seen_at: datetime | None = None, google_source_id: str | None = None
    ) -> GoogleInstantIdentityMigrationReport:
        """Run the idempotent repository migration for legacy projections."""

        return self.records.migrate_path_free_instant_identities(
            seen_at=seen_at, google_source_id=google_source_id
        )

    migrate_legacy_instant_identities = migrate_path_free_instant_identities

    def persist_observation(
        self,
        *,
        identity: GoogleSourceIdentity,
        query: GoogleQueryContext,
        stream: str | GoogleStream,
        payload: RawGooglePayload,
        records: Iterable[GoogleRecordDTO] = (),
        parse_status: str | GooglePayloadStatus = GooglePayloadStatus.OK,
        media_type: str = "application/json",
        payload_format: str | None = None,
        source_contract_version: str | None = None,
        normalization_contract_version: str = NORMALIZATION_CONTRACT_VERSION,
        fixture_id: str | None = None,
        source_filename: str | None = None,
        received_at: datetime | None = None,
        source_window_start_utc: datetime | None = None,
        source_window_end_utc: datetime | None = None,
        sync_run_id: str | None = None,
        ingest_event_id: str | None = None,
        create_ingest_event: bool = True,
        diagnostics: Iterable[Mapping[str, Any]] = (),
        unknown_fields: Iterable[Mapping[str, Any]] = (),
    ) -> GooglePersistenceOutcome:
        if not isinstance(identity, GoogleSourceIdentity):
            raise TypeError("Google source identity is required")
        if not isinstance(query, GoogleQueryContext):
            raise TypeError("Google query context is required")
        if identity.source_kind is GoogleSourceKind.FAMILY_AGGREGATE:
            if query.data_source_family not in (None, identity.source_instance_id):
                raise ValueError(
                    "family-aggregate query context must use that family as dataSourceFamily"
                )
        stream_code = GoogleStream(stream)
        normalized_records = tuple(records)
        for record in normalized_records:
            if record.stream is not stream_code:
                raise ValueError("Google record stream conflicts with observation stream")

        normalized_payload_format = _payload_format(
            payload_format or _payload_format_for_media_type(media_type)
        )
        normalized_source_contract = source_contract_version or SOURCE_CONTRACT_VERSION
        normalized_normalization = _required_text(
            normalization_contract_version, "normalization contract version"
        )
        diagnostics_json = _json_list_or_none(diagnostics)
        unknown_fields_json = _json_list_or_none(unknown_fields)
        window_start = _as_utc(source_window_start_utc)
        window_end = _as_utc(source_window_end_utc)
        _validate_optional_interval(window_start, window_end, "source observation window")
        parsed_status = GooglePayloadStatus(parse_status)

        stored = self._store_payload(
            payload, media_type=media_type, payload_format=normalized_payload_format
        )
        source_row = self.sources.get_or_create(identity)
        artifact = self.provenance.raw_artifacts.get_or_create(
            content_hash=stored.content_hash,
            kind="google_payload",
            media_type=_normalized_media_type(media_type),
            byte_size=stored.byte_size,
            relative_storage_path=stored.relative_storage_path,
            source_filename=source_filename,
        )
        observation_key = build_google_observation_key(
            google_source_id=source_row.id,
            stream_code=stream_code,
            content_hash=stored.content_hash,
            query_mode=query.query_mode,
            data_source_family=query.data_source_family,
            payload_format=normalized_payload_format,
            source_contract_version=normalized_source_contract,
            normalization_contract_version=normalized_normalization,
            fixture_id=fixture_id,
            parse_status=parsed_status,
            record_count=len(normalized_records),
            diagnostics_json=diagnostics_json,
            unknown_fields_json=unknown_fields_json,
            source_window_start_utc=window_start,
            source_window_end_utc=window_end,
            sync_run_id=sync_run_id,
            source_filename=source_filename,
        )
        existing_observation = self.observations.get_by_key(observation_key)
        existing_payload = self.raw_payloads.get_by_key(
            google_source_id=source_row.id,
            stream_code=stream_code,
            content_hash=stored.content_hash,
        )

        batch = None
        event = self.provenance.ingest_events.get(ingest_event_id) if ingest_event_id else None
        if ingest_event_id is not None and event is None:
            raise KeyError(f"unknown ingest event {ingest_event_id}")
        if event is not None and event.acquisition_source_id != source_row.acquisition_source_id:
            raise ValueError("Google ingest event does not belong to the source identity")

        if existing_observation is not None:
            raw_payload = self.raw_payloads.get(existing_observation.google_raw_payload_id)
            if raw_payload is None:
                raise RuntimeError("Google observation references a missing raw payload")
            observation = self.observations.create(
                google_raw_payload_id=raw_payload.id,
                raw_artifact_id=artifact.id,
                google_source_id=source_row.id,
                observation_key=observation_key,
                stream_code=stream_code,
                query_mode=query.query_mode,
                data_source_family=query.data_source_family,
                payload_format=normalized_payload_format,
                source_contract_version=normalized_source_contract,
                normalization_contract_version=normalized_normalization,
                fixture_id=fixture_id,
                parse_status=parsed_status,
                record_count=len(normalized_records),
                diagnostics_json=diagnostics_json,
                unknown_fields_json=unknown_fields_json,
                ingest_event_id=ingest_event_id,
                sync_run_id=sync_run_id,
                source_window_start_utc=window_start,
                source_window_end_utc=window_end,
                source_filename=source_filename,
                received_at=received_at,
            )
            current_records = []
            for record in normalized_records:
                if not _record_has_safe_projection_identity(record, query):
                    continue
                identity_key = build_google_record_identity_key(
                    stream_code=record.stream,
                    query_mode=query.query_mode,
                    data_source_family=query.data_source_family,
                    idempotency_key=record.idempotency_key,
                    external_record_id=record.external_record_id,
                    source_timestamp_utc=record.temporal.measured_at_utc,
                    interval=record.interval,
                )
                stored_record = self.records.get_by_identity_key(
                    google_source_id=source_row.id, record_identity_key=identity_key
                )
                if record.stream is GoogleStream.SLEEP and record.external_record_id:
                    stored_record = self.records._find_or_adopt_sleep_identity(
                        google_source_id=source_row.id,
                        external_record_id=record.external_record_id,
                        logical_identity_key=identity_key,
                        exact=stored_record,
                        seen_at=start_or_now(received_at),
                    )
                if stored_record is not None:
                    current_records.append(stored_record)
            return GooglePersistenceOutcome(
                source=source_row,
                raw_payload=raw_payload,
                observation=observation,
                records=tuple(current_records),
                inserted_count=0,
                updated_count=0,
                replayed=True,
                ingest_event_id=observation.ingest_event_id,
            )

        if event is None and create_ingest_event:
            batch = self.provenance.ingest_batches.create(
                acquisition_source_id=source_row.acquisition_source_id,
                batch_kind="provider_sync",
                parser_name="google-persistence-shell",
                parser_version=normalized_normalization,
                status="received",
            )
            event = self.provenance.ingest_events.get_or_create(
                ingest_batch_id=batch.id,
                acquisition_source_id=source_row.acquisition_source_id,
                raw_artifact_id=artifact.id,
                provider_stream=stream_code.value,
                semantic_fingerprint=f"google-observation:{observation_key}",
                event_type="insert",
                status="parsed",
            )

        event_id = event.id if event is not None else ingest_event_id
        raw_payload = existing_payload or self.raw_payloads.create(
            google_source_id=source_row.id,
            raw_artifact_id=artifact.id,
            content_hash=stored.content_hash,
            stream_code=stream_code,
            payload_format=normalized_payload_format,
            source_contract_version=normalized_source_contract,
            normalization_contract_version=normalized_normalization,
            parse_status=parsed_status,
            record_count=len(normalized_records),
            diagnostics_json=diagnostics_json,
            unknown_fields_json=unknown_fields_json,
            ingest_event_id=event_id,
            sync_run_id=sync_run_id,
            source_window_start_utc=window_start,
            source_window_end_utc=window_end,
            fixture_id=fixture_id,
            received_at=received_at,
        )
        observation = self.observations.create(
            google_raw_payload_id=raw_payload.id,
            raw_artifact_id=artifact.id,
            google_source_id=source_row.id,
            observation_key=observation_key,
            stream_code=stream_code,
            query_mode=query.query_mode,
            data_source_family=query.data_source_family,
            payload_format=normalized_payload_format,
            source_contract_version=normalized_source_contract,
            normalization_contract_version=normalized_normalization,
            fixture_id=fixture_id,
            parse_status=parsed_status,
            record_count=len(normalized_records),
            diagnostics_json=diagnostics_json,
            unknown_fields_json=unknown_fields_json,
            ingest_event_id=event_id,
            sync_run_id=sync_run_id,
            source_window_start_utc=window_start,
            source_window_end_utc=window_end,
            source_filename=source_filename,
            received_at=received_at,
        )

        seen_at = start_or_now(received_at)
        persisted_records: list[GoogleSourceRecord] = []
        inserted_count = 0
        updated_count = 0
        if parsed_status is not GooglePayloadStatus.INVALID:
            seen_keys: dict[str, str] = {}
            for record in normalized_records:
                if not _record_has_safe_projection_identity(record, query):
                    # Missing/invalid/non-instant sample evidence is retained
                    # in the raw payload and normalization attempt only; it
                    # must never become a guessed logical projection.
                    continue
                if record.idempotency_key.startswith(
                    (PATH_FREE_INSTANT_IDENTITY_PREFIX, PATH_FREE_HR_INTERVAL_IDENTITY_PREFIX)
                ):
                    signature = _record_revision_fingerprint(self.session, record=record)
                else:
                    signature = canonical_json({"record": record.as_dict()})
                identity_key = build_google_record_identity_key(
                    stream_code=record.stream,
                    query_mode=query.query_mode,
                    data_source_family=query.data_source_family,
                    idempotency_key=record.idempotency_key,
                    external_record_id=record.external_record_id,
                    source_timestamp_utc=record.temporal.measured_at_utc,
                    interval=record.interval,
                )
                previous = seen_keys.get(identity_key)
                if previous is not None:
                    if previous != signature:
                        raise ValueError(
                            "one Google observation contains conflicting duplicate identities"
                        )
                    continue
                seen_keys[identity_key] = signature
                stored_record, inserted, updated = self.records.upsert(
                    google_source_id=source_row.id,
                    raw_payload_id=raw_payload.id,
                    observation_id=observation.id,
                    record=record,
                    query=query,
                    ingest_event_id=event_id,
                    seen_at=seen_at,
                    source_contract_version=normalized_source_contract,
                    normalization_contract_version=normalized_normalization,
                )
                persisted_records.append(stored_record)
                inserted_count += int(inserted)
                updated_count += int(updated)

        if batch is not None and event is not None:
            final_status = "failed" if parsed_status is GooglePayloadStatus.INVALID else "committed"
            self.provenance.ingest_events.set_status(event.id, final_status)
            self.provenance.ingest_batches.update(
                batch.id,
                status=final_status,
                received_count=1,
                parsed_count=1,
                committed_count=0 if parsed_status is GooglePayloadStatus.INVALID else 1,
                failed_count=1 if parsed_status is GooglePayloadStatus.INVALID else 0,
                completed=True,
            )

        return GooglePersistenceOutcome(
            source=source_row,
            raw_payload=raw_payload,
            observation=observation,
            records=tuple(persisted_records),
            inserted_count=inserted_count,
            updated_count=updated_count,
            replayed=False,
            ingest_batch_id=batch.id if batch is not None else None,
            ingest_event_id=event_id,
        )

    def persist_result(
        self,
        result: object,
        *,
        identity: GoogleSourceIdentity | None = None,
        payload: RawGooglePayload | None = None,
        media_type: str = "application/json",
        payload_format: str | None = None,
        fixture_id: str | None = None,
        source_filename: str | None = None,
        received_at: datetime | None = None,
        source_window_start_utc: datetime | None = None,
        source_window_end_utc: datetime | None = None,
        sync_run_id: str | None = None,
        ingest_event_id: str | None = None,
        create_ingest_event: bool = True,
    ) -> GooglePersistenceOutcome:
        """Persist one explicit normalization result and its immutable attempt."""

        from healthcheck.google.normalization import GoogleNormalizationResult

        if not isinstance(result, GoogleNormalizationResult):
            raise TypeError("Google persistence requires a GoogleNormalizationResult")
        resolved_identity = identity or result.source_identity
        if resolved_identity is None:
            raise ValueError("Google normalization result requires explicit source identity")
        if payload is None:
            raise ValueError("Google normalization persistence requires the original payload")
        diagnostics = tuple(item.as_dict() for item in result.diagnostics)
        unknown_fields = tuple(result.unknown_fields)
        outcome = self.persist_observation(
            identity=resolved_identity,
            query=result.query,
            stream=result.stream,
            payload=payload,
            records=result.records,
            parse_status=result.status,
            media_type=media_type,
            payload_format=payload_format,
            source_contract_version=result.source_contract_version,
            normalization_contract_version=result.normalization_contract_version,
            fixture_id=fixture_id,
            source_filename=source_filename,
            received_at=received_at,
            source_window_start_utc=source_window_start_utc,
            source_window_end_utc=source_window_end_utc,
            sync_run_id=sync_run_id,
            ingest_event_id=ingest_event_id,
            create_ingest_event=create_ingest_event,
            diagnostics=diagnostics,
            unknown_fields=unknown_fields,
        )
        attempt = self.attempts.create(
            google_source_id=outcome.source.id,
            google_raw_payload_id=outcome.raw_payload.id,
            observation_id=outcome.observation.id,
            attempt_key=build_google_normalization_attempt_key(
                observation_id=outcome.observation.id,
                normalization_contract_version=result.normalization_contract_version,
            ),
            stream_code=result.stream,
            query_mode=result.query.query_mode,
            data_source_family=result.query.data_source_family,
            source_contract_version=result.source_contract_version,
            normalization_contract_version=result.normalization_contract_version,
            parse_status=result.status,
            record_count=len(result.records),
            projection_fingerprint=result.projection_fingerprint,
            projection_json=canonical_json(result.as_dict()),
            diagnostics_json=_json_list_or_none(diagnostics),
            unknown_fields_json=_json_list_or_none(unknown_fields),
            attempted_at=received_at,
        )
        return replace(outcome, normalization_attempt=attempt)

    persist_normalized_result = persist_result
    persist_normalization = persist_result

    persist = persist_observation

    def _store_payload(
        self,
        payload: RawGooglePayload,
        *,
        media_type: str,
        payload_format: str | None,
    ) -> StoredGooglePayload:
        if self.payload_store is None:
            raise ValueError("a ContentAddressedGooglePayloadStore is required for raw storage")
        return self.payload_store.put(
            serialize_google_payload(payload),
            media_type=media_type,
            payload_format=payload_format,
        )


def google_persistence_for(
    session: Session,
    *,
    payload_store: ContentAddressedGooglePayloadStore | None = None,
) -> GooglePersistenceRepository:
    """Build the persistence facade for an existing transaction session."""

    return GooglePersistenceRepository(session, payload_store=payload_store)


def _upsert_record_interval(
    session: Session, *, record_id: str, interval: GoogleIntervalDTO
) -> None:
    kind = interval.interval_kind.value
    if kind not in {"roll_up", "daily_roll_up"}:
        raise ValueError("Google record intervals must be roll-up intervals")
    row = session.scalar(
        select(GoogleRecordInterval).where(
            GoogleRecordInterval.record_id == record_id,
            GoogleRecordInterval.interval_kind == kind,
            GoogleRecordInterval.ordinal == 0,
        )
    )
    values = {
        "record_id": record_id,
        "interval_kind": kind,
        "interval_state": interval.state.value,
        "ordinal": 0,
        **_interval_endpoint_values(interval.start, "start"),
        **_interval_endpoint_values(interval.end, "end"),
    }
    if row is None:
        session.add(GoogleRecordInterval(**values))
    else:
        for field_name, value in values.items():
            setattr(row, field_name, value)


def _upsert_sleep_interval(
    session: Session,
    *,
    sleep_record_id: str,
    interval: GoogleIntervalDTO | GoogleSleepStageDTO,
    ordinal: int,
) -> None:
    if isinstance(interval, GoogleSleepStageDTO):
        kind = "sleep_stage"
        interval_state = GoogleMetricState.VALUE
        start = interval.start
        end = interval.end
        stage_type = interval.stage_type
        create_time = interval.create_time
        update_time = interval.update_time
    else:
        kind = interval.interval_kind.value
        if kind not in {"sleep_session", "sleep_out_of_bed"}:
            raise ValueError("Google sleep interval kind is not supported")
        interval_state = interval.state
        start = interval.start
        end = interval.end
        stage_type = None
        create_time = None
        update_time = None
    row = session.scalar(
        select(GoogleSleepInterval).where(
            GoogleSleepInterval.sleep_record_id == sleep_record_id,
            GoogleSleepInterval.interval_kind == kind,
            GoogleSleepInterval.ordinal == ordinal,
        )
    )
    values = {
        "sleep_record_id": sleep_record_id,
        "interval_kind": kind,
        "interval_state": interval_state.value,
        "ordinal": ordinal,
        "stage_type": stage_type,
        "create_time": create_time,
        "update_time": update_time,
        **_interval_endpoint_values(start, "start"),
        **_interval_endpoint_values(end, "end"),
    }
    if row is None:
        session.add(GoogleSleepInterval(**values))
    else:
        for field_name, value in values.items():
            setattr(row, field_name, value)


def _upsert_sleep_field_states(
    session: Session,
    *,
    sleep_record_id: str,
    sleep_interval_state: GoogleMetricState,
    sleep_stages_state: GoogleMetricState,
    out_of_bed_state: GoogleMetricState,
) -> None:
    incoming = {
        "sleep_interval_state": GoogleMetricState(sleep_interval_state),
        "sleep_stages_state": GoogleMetricState(sleep_stages_state),
        "out_of_bed_state": GoogleMetricState(out_of_bed_state),
    }
    row = session.get(GoogleSleepFieldState, sleep_record_id)
    if row is None:
        session.add(
            GoogleSleepFieldState(
                sleep_record_id=sleep_record_id,
                **{field_name: state.value for field_name, state in incoming.items()},
            )
        )
        return
    for field_name, state in incoming.items():
        # A partial provider observation describes only the fields it carries.
        # MISSING and INVALID therefore cannot displace an accepted current
        # state; VALUE and NULL remain authoritative for this dimension.
        if state in {GoogleMetricState.MISSING, GoogleMetricState.INVALID}:
            continue
        setattr(row, field_name, state.value)


def _clear_sleep_intervals(
    session: Session, *, sleep_record_id: str, interval_kind: str
) -> None:
    if interval_kind not in {"sleep_session", "sleep_stage", "sleep_out_of_bed"}:
        raise ValueError("Google sleep interval clearing kind is not supported")
    existing = list(
        session.scalars(
            select(GoogleSleepInterval).where(
                GoogleSleepInterval.sleep_record_id == sleep_record_id,
                GoogleSleepInterval.interval_kind == interval_kind,
            )
        )
    )
    for row in existing:
        session.delete(row)
    if existing:
        session.flush()


def _replace_sleep_intervals(
    session: Session,
    *,
    sleep_record_id: str,
    interval_kind: str,
    intervals: Sequence[GoogleIntervalDTO] | Sequence[GoogleSleepStageDTO],
) -> None:
    if interval_kind not in {"sleep_stage", "sleep_out_of_bed"}:
        raise ValueError("Google sleep interval replacement kind is not supported")
    _clear_sleep_intervals(
        session,
        sleep_record_id=sleep_record_id,
        interval_kind=interval_kind,
    )
    for ordinal, interval in enumerate(intervals):
        _upsert_sleep_interval(
            session,
            sleep_record_id=sleep_record_id,
            interval=interval,
            ordinal=ordinal,
        )


def _interval_endpoint_values(temporal: GoogleTemporalDTO, prefix: str) -> dict[str, object]:
    """Project one DTO endpoint without losing its exact field provenance."""

    if not isinstance(temporal, GoogleTemporalDTO):
        raise TypeError("Google interval endpoint must be temporal evidence")
    as_dict = temporal.as_dict()
    return {
        f"{prefix}_precision": temporal.precision.value,
        f"{prefix}_state": temporal.state.value,
        f"{prefix}_at_utc": _as_utc(temporal.measured_at_utc),
        f"{prefix}_local_date": temporal.local_date,
        f"{prefix}_local_wall_time": temporal.local_wall_time,
        f"{prefix}_source_timestamp": temporal.source_local_timestamp,
        f"{prefix}_utc_offset_minutes": temporal.source_utc_offset_minutes,
        f"{prefix}_source_timezone": temporal.source_timezone,
        f"{prefix}_source_field": temporal.source_field,
        f"{prefix}_source_local_field": temporal.source_local_field,
        f"{prefix}_source_utc_field": temporal.source_utc_field,
        f"{prefix}_temporal_json": canonical_json(as_dict),
    }


def _merge_data_source_evidence(
    existing_json: str, incoming: Mapping[str, object]
) -> dict[str, object]:
    try:
        existing = json.loads(existing_json)
    except (TypeError, json.JSONDecodeError):
        existing = {}
    if not isinstance(existing, Mapping) or incoming.get("state") != GoogleMetricState.VALUE.value:
        return dict(incoming)
    previous_fields = {
        str(item.get("metric_code")): item
        for item in existing.get("fields", ())
        if isinstance(item, Mapping) and item.get("metric_code") is not None
    }
    merged_fields: list[Mapping[str, object]] = []
    for item in incoming.get("fields", ()):
        if not isinstance(item, Mapping):
            continue
        code = str(item.get("metric_code", ""))
        if item.get("state") == GoogleMetricState.MISSING.value and code in previous_fields:
            merged_fields.append(previous_fields[code])
        else:
            merged_fields.append(item)
        previous_fields.pop(code, None)
    merged_fields.extend(previous_fields.values())
    merged_fields.sort(
        key=lambda item: (str(item.get("metric_code", "")), str(item.get("field_path", "")))
    )
    return {
        "state": incoming.get("state"),
        "field_path": incoming.get("field_path"),
        "fields": merged_fields,
    }


def _normalization_version_rank(version: str) -> tuple[int, int, str]:
    """Order the old #86 shell below explicit #87 versions, then by vN."""

    normalized = _required_text(version, "normalization contract version")
    match = re.search(r"-v(\d+)$", normalized)
    revision = int(match.group(1)) if match else 0
    family_rank = 0 if "persistence-shell" in normalized else 1
    return family_rank, revision, normalized


def build_google_observation_key(
    *,
    google_source_id: str,
    stream_code: str | GoogleStream,
    content_hash: str,
    query_mode: str | GoogleQueryMode,
    data_source_family: str | None,
    payload_format: str,
    source_contract_version: str | None,
    normalization_contract_version: str,
    fixture_id: str | None,
    parse_status: str | GooglePayloadStatus,
    record_count: int,
    diagnostics_json: str | None,
    unknown_fields_json: str | None,
    source_window_start_utc: datetime | None,
    source_window_end_utc: datetime | None,
    sync_run_id: str | None,
    source_filename: str | None,
) -> str:
    """Build the stable identity of one raw-byte observation.

    Receive time and ingest event id are excluded so exact retries converge.
    Query mode, family, window, and sync run remain in the key so those
    contexts cannot collide.
    """

    start = _as_utc(source_window_start_utc)
    end = _as_utc(source_window_end_utc)
    _validate_optional_interval(start, end, "source observation window")
    payload = {
        "version": OBSERVATION_KEY_VERSION,
        "google_source_id": google_source_id,
        "stream_code": GoogleStream(stream_code).value,
        "content_hash": _required_text(content_hash, "Google payload content hash").lower(),
        "query_mode": GoogleQueryMode(query_mode).value,
        "data_source_family": data_source_family,
        "payload_format": _payload_format(payload_format),
        "source_contract_version": source_contract_version,
        "normalization_contract_version": _required_text(
            normalization_contract_version, "normalization contract version"
        ),
        "fixture_id": fixture_id,
        "parse_status": GooglePayloadStatus(parse_status).value,
        "record_count": record_count,
        "diagnostics_json": diagnostics_json,
        "unknown_fields_json": unknown_fields_json,
        "source_window_start_utc": start.isoformat() if start is not None else None,
        "source_window_end_utc": end.isoformat() if end is not None else None,
        "sync_run_id": sync_run_id,
        "source_filename": source_filename,
    }
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{OBSERVATION_KEY_VERSION}:{digest}"


def build_google_normalization_attempt_key(
    *, observation_id: str, normalization_contract_version: str
) -> str:
    """Identify one bounded normalization version attempt for an observation."""

    payload = {
        "version": "google-normalization-attempt-v1",
        "observation_id": _required_text(observation_id, "Google observation id"),
        "normalization_contract_version": _required_text(
            normalization_contract_version, "normalization contract version"
        ),
    }
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"google-normalization-attempt-v1:{digest}"


def build_google_record_identity_key(
    *,
    stream_code: str | GoogleStream,
    query_mode: str | GoogleQueryMode,
    data_source_family: str | None,
    idempotency_key: str,
    external_record_id: str | None = None,
    source_timestamp_utc: datetime | None = None,
    interval: GoogleIntervalDTO | None = None,
) -> str:
    """Build a physical source-record identity, separate from revision content.

    Sleep sessions with a provider id deliberately omit query/family context:
    those fields describe acquisition, not a second physical session.  Other
    records retain the pre-existing context-sensitive identity contract.
    """

    stream = GoogleStream(stream_code)
    normalized_external_id = (
        external_record_id.strip() if isinstance(external_record_id, str) else None
    )
    if stream is GoogleStream.SLEEP and normalized_external_id:
        payload = {
            "version": "google-sleep-logical-session-v1",
            "stream_code": stream.value,
            "external_record_id": normalized_external_id,
        }
        digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        return f"google-sleep-logical-session-v1:{digest}"

    normalized_key = _required_text(idempotency_key, "Google record idempotency key")
    if normalized_key.startswith(UNIDENTIFIED_INSTANT_IDENTITY_PREFIX):
        raise ValueError("Google instant evidence has no safe logical identity")
    normalized_query_mode = GoogleQueryMode(query_mode)
    if (
        stream is GoogleStream.HEART_RATE
        and normalized_query_mode
        in {GoogleQueryMode.ROLL_UP, GoogleQueryMode.DAILY_ROLL_UP}
        and interval is None
        and source_timestamp_utc is None
    ):
        raise ValueError("Google HR rollup evidence has no safe interval identity")
    if stream is GoogleStream.HEART_RATE and interval is not None:
        if not is_safe_google_interval_identity(interval):
            raise ValueError("Google HR interval evidence has no safe logical identity")
        normalized_key = _canonical_interval_idempotency(
            stream, canonical_json(_interval_identity_from_dto(interval))
        )
    elif stream in PATH_FREE_INSTANT_STREAMS:
        if source_timestamp_utc is None:
            raise ValueError("Google instant evidence has no safe logical identity")
        normalized_key = _canonical_instant_idempotency(stream, source_timestamp_utc)
    path_free_scope = stream in PATH_FREE_INSTANT_STREAMS or (
        stream is GoogleStream.HEART_RATE and interval is not None
    )
    payload = {
        "version": "google-record-v2" if path_free_scope else "google-record-v1",
        "stream_code": stream.value,
        # Query mode and family are acquisition context, but remain part of
        # persisted GoogleSourceRecord identity for this frozen contract.
        "query_mode": normalized_query_mode.value,
        "data_source_family": data_source_family,
        "idempotency_key": normalized_key,
    }
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"google-record-{'v2' if path_free_scope else 'v1'}:{digest}"


def _sleep_revision_from_metric(
    state: str | GoogleMetricState | None, value_text: object
) -> tuple[GoogleMetricState, datetime | None]:
    """Parse provider revision evidence without treating malformed text as time."""

    try:
        normalized_state = (
            GoogleMetricState(state) if state is not None else GoogleMetricState.MISSING
        )
    except ValueError:
        return GoogleMetricState.INVALID, None
    if normalized_state is not GoogleMetricState.VALUE:
        return normalized_state, None
    if not isinstance(value_text, str) or not value_text.strip():
        return GoogleMetricState.INVALID, None
    text = value_text.strip()
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return GoogleMetricState.INVALID, None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return GoogleMetricState.INVALID, None
    return GoogleMetricState.VALUE, parsed.astimezone(UTC)


def _sleep_revision_for_record(
    record: GoogleRecordDTO,
) -> tuple[GoogleMetricState, datetime | None]:
    for metric in record.metrics:
        if metric.metric_code == "sleep_update_time":
            return _sleep_revision_from_metric(metric.state, metric.value_text)
    return GoogleMetricState.MISSING, None


def _sleep_revision_for_row(
    session: Session, row: GoogleSourceRecord
) -> tuple[GoogleMetricState, datetime | None]:
    metric = session.scalar(
        select(GoogleRecordMetric).where(
            GoogleRecordMetric.record_id == row.id,
            GoogleRecordMetric.metric_code == "sleep_update_time",
        )
    )
    if metric is None:
        return GoogleMetricState.MISSING, None
    return _sleep_revision_from_metric(metric.state, metric.value_text)


def _sleep_revision_can_replace(
    session: Session, existing: GoogleSourceRecord, incoming: GoogleRecordDTO
) -> bool:
    """Accept only a strictly stronger provider revision.

    A valid provider update time outranks receive order.  Missing, invalid,
    or equal revision metadata is fail-closed: exact retries are harmless and
    changed content cannot silently replace the accepted projection.
    """

    existing_state, existing_time = _sleep_revision_for_row(session, existing)
    incoming_state, incoming_time = _sleep_revision_for_record(incoming)
    if existing_state is GoogleMetricState.VALUE and existing_time is not None:
        if incoming_state is not GoogleMetricState.VALUE or incoming_time is None:
            # An unusable incoming revision cannot replace an accepted
            # projection, including explicit interval field-state evidence.
            return False
        if incoming_time > existing_time:
            return True
        if incoming_time < existing_time:
            return False
        # Equal provider revisions may carry an explicit partial field update,
        # but a changed primary interval is ambiguous and must fail closed.
        return _sleep_primary_interval_unchanged(session, existing.id, incoming)
    return incoming_state is GoogleMetricState.VALUE and incoming_time is not None


def _sleep_primary_interval_unchanged(
    session: Session, record_id: str, incoming: GoogleRecordDTO
) -> bool:
    interval = incoming.sleep_interval
    if interval is None or interval.state is not GoogleMetricState.VALUE:
        return True
    current = session.scalar(
        select(GoogleSleepInterval).where(
            GoogleSleepInterval.sleep_record_id == record_id,
            GoogleSleepInterval.interval_kind == "sleep_session",
            GoogleSleepInterval.ordinal == 0,
        )
    )
    if current is None:
        return False
    return (
        current.start_temporal_json == canonical_json(interval.start.as_dict())
        and current.end_temporal_json == canonical_json(interval.end.as_dict())
    )


def _select_sleep_legacy_winner(
    session: Session, candidates: Sequence[GoogleSourceRecord]
) -> GoogleSourceRecord | None:
    if not candidates:
        return None
    with_revision = [
        (row, revision_time)
        for row in candidates
        for state, revision_time in [_sleep_revision_for_row(session, row)]
        if state is GoogleMetricState.VALUE and revision_time is not None
    ]
    if with_revision:
        latest = max(revision_time for _, revision_time in with_revision)
        candidates = [row for row, revision_time in with_revision if revision_time == latest]
    # Equal or unavailable provider revisions have no semantic winner.  Use
    # the existing projection observation only as a deterministic migration
    # fallback; it never outranks valid provider revision evidence above.
    return max(
        candidates,
        key=lambda row: (
            _datetime_key(row.projection_observed_at) or _datetime_key(row.last_seen_at),
            row.created_at,
            row.id,
        ),
    )


def _record_values(
    *,
    google_source_id: str,
    raw_payload_id: str,
    observation_id: str,
    record: GoogleRecordDTO,
    query: GoogleQueryContext,
    record_identity_key: str,
    ingest_event_id: str | None,
    source_contract_version: str | None,
    normalization_contract_version: str,
    seen_at: datetime,
) -> dict[str, Any]:
    temporal = record.temporal
    return {
        "google_source_id": google_source_id,
        "raw_payload_id": raw_payload_id,
        "observation_id": observation_id,
        "ingest_event_id": ingest_event_id,
        "stream_code": record.stream.value,
        "query_mode": query.query_mode.value,
        "data_source_family": query.data_source_family,
        "record_identity_key": record_identity_key,
        "idempotency_key": record.idempotency_key,
        "external_record_id": record.external_record_id,
        "record_index": record.record_index,
        "temporal_precision": temporal.precision.value,
        "source_local_date": temporal.local_date,
        "source_timestamp_utc": _as_utc(temporal.measured_at_utc),
        "local_wall_time": temporal.local_wall_time,
        "source_local_timestamp": temporal.source_local_timestamp,
        "source_utc_offset_minutes": temporal.source_utc_offset_minutes,
        "source_timezone": temporal.source_timezone,
        "source_field": temporal.source_field,
        "source_local_field": temporal.source_local_field,
        "source_utc_field": temporal.source_utc_field,
        "record_status": record.status.value,
        "source_contract_version": source_contract_version,
        "normalization_contract_version": _required_text(
            normalization_contract_version, "normalization contract version"
        ),
        "diagnostics_json": _json_list_or_none(record.diagnostics),
        "unknown_fields_json": _json_list_or_none(record.unknown_fields),
        "projection_status": PROJECTION_CURRENT,
        "projection_observed_at": seen_at,
        "retired_at": None,
        "retire_reason": None,
        "last_seen_at": seen_at,
        "updated_at": seen_at,
    }


def _record_has_safe_projection_identity(
    record: GoogleRecordDTO, query: GoogleQueryContext
) -> bool:
    """Allow projections only when affected streams carry canonical evidence."""

    if record.idempotency_key.startswith(UNIDENTIFIED_INSTANT_IDENTITY_PREFIX):
        return False
    if (
        record.stream is GoogleStream.HEART_RATE
        and query.query_mode in {GoogleQueryMode.ROLL_UP, GoogleQueryMode.DAILY_ROLL_UP}
    ):
        return record.interval is not None and is_safe_google_interval_identity(record.interval)
    if record.stream in PATH_FREE_INSTANT_STREAMS:
        temporal = record.temporal
        return temporal.precision.value == "instant" and temporal.measured_at_utc is not None
    return True


def _record_revision_fingerprint(
    session: Session,
    existing: GoogleSourceRecord | None = None,
    *,
    record: GoogleRecordDTO | None = None,
) -> str:
    """Return comparison evidence without provider paths or positional fields."""

    if (existing is None) == (record is None):
        raise ValueError("exactly one Google record fingerprint input is required")

    def metric(value: GoogleMetricDTO) -> dict[str, object]:
        return {
            "code": value.metric_code,
            "state": value.state.value,
            "number": value.value_number,
            "text": value.value_text,
            "unit": value.unit,
            "collection": value.collection_json,
        }

    if record is not None:
        temporal = record.temporal
        payload: dict[str, object] = {
            "stream": record.stream.value,
            "status": record.status.value,
            "precision": temporal.precision.value,
            "state": temporal.state.value,
            "timestamp": (
                temporal.measured_at_utc.astimezone(UTC).isoformat()
                if temporal.measured_at_utc is not None
                else None
            ),
            "metrics": sorted(
                (metric(value) for value in record.metrics),
                key=canonical_json,
            ),
        }
        if record.interval is not None:
            payload["interval"] = _interval_revision_fingerprint(record.interval)
    else:
        assert existing is not None
        payload = {
            "stream": existing.stream_code,
            "status": existing.record_status,
            "precision": existing.temporal_precision,
            "state": "value" if existing.source_timestamp_utc is not None else "unknown",
            "timestamp": (
                _datetime_key(existing.source_timestamp_utc).isoformat()
                if existing.source_timestamp_utc is not None
                else None
            ),
            "metrics": [
                metric(
                    GoogleMetricDTO(
                        metric_code=value.metric_code,
                        field_path="$.metric",
                        state=value.state,
                        value_number=value.value_number,
                        value_text=value.value_text,
                        unit=value.unit,
                        reason=value.reason,
                        collection_json=value.collection_json,
                    )
                )
                for value in sorted(
                    session.scalars(
                        select(GoogleRecordMetric).where(
                            GoogleRecordMetric.record_id == existing.id
                        )
                    ),
                    key=lambda item: canonical_json(
                        metric(
                            GoogleMetricDTO(
                                metric_code=item.metric_code,
                                field_path="$.metric",
                                state=item.state,
                                value_number=item.value_number,
                                value_text=item.value_text,
                                unit=item.unit,
                                reason=item.reason,
                                collection_json=item.collection_json,
                            )
                        )
                    ),
                )
            ],
        }
        intervals = list(
            session.scalars(
                select(GoogleRecordInterval).where(GoogleRecordInterval.record_id == existing.id)
            )
        )
        if intervals:
            payload["interval"] = [
                {
                    "identity": canonical_google_interval_identity(value),
                    "state": value.interval_state,
                }
                for value in sorted(intervals, key=lambda item: (item.interval_kind, item.ordinal))
            ]
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _interval_revision_fingerprint(interval: GoogleIntervalDTO) -> dict[str, object]:
    return {
        "identity": canonical_google_interval_identity(interval),
        "state": interval.state.value,
    }


def _interval_identity_from_dto(interval: GoogleIntervalDTO) -> dict[str, object]:
    return canonical_google_interval_identity(interval)


def _stored_interval_identity(interval: GoogleRecordInterval) -> str:
    """Canonical endpoint identity for one persisted HR aggregate interval."""
    return canonical_json(canonical_google_interval_identity(interval))


def _canonical_instant_idempotency(stream: GoogleStream, timestamp: datetime) -> str:
    payload = {
        "version": "google-instant-sample-v1",
        "stream": stream.value,
        "sample_time_utc": _as_utc(timestamp).isoformat(),
    }
    return PATH_FREE_INSTANT_IDENTITY_PREFIX + hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _canonical_interval_idempotency(stream: GoogleStream, interval_identity: str) -> str:
    payload = {
        "version": "google-hr-interval-v1",
        "stream": stream.value,
        "interval": json.loads(interval_identity),
    }
    return PATH_FREE_HR_INTERVAL_IDENTITY_PREFIX + hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()


def _append_identity_conflict(existing: str | None) -> str:
    try:
        values = json.loads(existing) if existing else []
    except (TypeError, ValueError):
        values = []
    if not isinstance(values, list):
        values = []
    if not any(
        isinstance(item, Mapping) and item.get("code") == "identity_conflict"
        for item in values
    ):
        values.append(
            {
                "code": "identity_conflict",
                "message": "same accepted epoch has conflicting Google revision evidence",
                "severity": "error",
            }
        )
    return canonical_json(values)


def _payload_format_for_media_type(media_type: str) -> str:
    normalized = _normalized_media_type(media_type)
    if "json" in normalized:
        return "json"
    return "binary"


def _payload_format(value: str) -> str:
    normalized = _required_text(value, "Google payload format").lower()
    if normalized not in {"json", "binary"}:
        raise ValueError("Google payload format must be json or binary")
    return normalized


def _normalized_media_type(media_type: str) -> str:
    normalized = media_type.split(";", 1)[0].strip().lower()
    if not normalized:
        raise ValueError("Google payload media type is required")
    return normalized


def _json_list_or_none(values: Iterable[Mapping[str, Any]]) -> str | None:
    items = list(values)
    return canonical_json(items) if items else None


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Google UTC timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _datetime_key(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    restored = restore_stored_utc(value)
    return restored.astimezone(UTC) if restored is not None else None


def start_or_now(value: datetime | None) -> datetime:
    return _as_utc(value) or utc_now()


def _validate_optional_interval(start: datetime | None, end: datetime | None, label: str) -> None:
    if (start is None) != (end is None):
        raise ValueError(f"{label} requires both boundaries")
    if start is not None and end is not None and end <= start:
        raise ValueError(f"{label} end must be after start")


__all__ = [
    "GOOGLE_INPUT_METHOD",
    "GOOGLE_SOURCE_APPLICATION",
    "GooglePersistenceOutcome",
    "GoogleInstantIdentityMigrationReport",
    "GooglePersistenceRepository",
    "GoogleNormalizationAttemptRepository",
    "GooglePayloadObservationRepository",
    "GoogleRawPayloadRepository",
    "build_google_normalization_attempt_key",
    "GoogleSourceRecordRepository",
    "GoogleSourceRepository",
    "PERSISTENCE_CONTRACT_VERSION",
    "PROJECTION_CURRENT",
    "PATH_FREE_INSTANT_STREAMS",
    "PATH_FREE_INSTANT_IDENTITY_PREFIX",
    "UNIDENTIFIED_INSTANT_IDENTITY_PREFIX",
    "PATH_FREE_HR_INTERVAL_IDENTITY_PREFIX",
    "build_google_observation_key",
    "build_google_record_identity_key",
    "google_persistence_for",
]
