"""Offline persistence for the R04 Google Health contract.

Accepts already-shaped synthetic identity, query context, raw bytes, and a
minimum typed-record shell.  It has no Google client, OAuth, network,
backfill, or analytics behavior, and it never writes ``garmin_*`` tables.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    GooglePayloadObservation,
    GooglePayloadStatus,
    GoogleRawPayload,
    GoogleRecordMetric,
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
    GoogleMetricDTO,
    GoogleMetricState,
    GoogleQueryContext,
    GoogleQueryMode,
    GoogleRecordDTO,
    GoogleSourceIdentity,
    GoogleStream,
)
from healthcheck.google.storage import (
    ContentAddressedGooglePayloadStore,
    StoredGooglePayload,
    serialize_google_payload,
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
        if existing is None:
            row = GoogleSourceRecord(**values)
            self.session.add(row)
            self.session.flush()
            self._upsert_typed_child(row, record)
            self._upsert_metrics(row.id, record.metrics)
            return row, True, False

        projected = _datetime_key(existing.projection_observed_at) or _datetime_key(
            existing.last_seen_at
        )
        if projected is not None and seen_at < projected:
            return existing, False, False
        for field_name, value in values.items():
            if field_name in {"id", "created_at"}:
                continue
            setattr(existing, field_name, value)
        existing.updated_at = seen_at
        self.session.flush()
        self._upsert_typed_child(existing, record)
        self._upsert_metrics(existing.id, record.metrics)
        return existing, False, True

    def _upsert_typed_child(self, row: GoogleSourceRecord, record: GoogleRecordDTO) -> None:
        if record.stream is not GoogleStream.SLEEP:
            return
        typed = self.session.get(GoogleSleepRecord, row.id)
        wake_date = record.wake_date or record.temporal.local_date
        if typed is None:
            self.session.add(GoogleSleepRecord(record_id=row.id, wake_date=wake_date))
        else:
            typed.wake_date = wake_date

    def _upsert_metrics(self, record_id: str, metrics: Iterable[GoogleMetricDTO]) -> None:
        incoming = {metric.metric_code: metric for metric in metrics}
        existing = {
            metric.metric_code: metric
            for metric in self.session.scalars(
                select(GoogleRecordMetric).where(GoogleRecordMetric.record_id == record_id)
            )
        }
        for metric in incoming.values():
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
            stored = existing.get(metric.metric_code)
            if stored is None:
                self.session.add(GoogleRecordMetric(record_id=record_id, **values))
            else:
                for field_name, value in values.items():
                    setattr(stored, field_name, value)
        for metric_code, stored in existing.items():
            if metric_code not in incoming:
                self.session.delete(stored)


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
        self.records = GoogleSourceRecordRepository(session)
        self.payload_store = payload_store

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
                identity_key = build_google_record_identity_key(
                    stream_code=record.stream,
                    query_mode=query.query_mode,
                    data_source_family=query.data_source_family,
                    idempotency_key=record.idempotency_key,
                )
                stored_record = self.records.get_by_identity_key(
                    google_source_id=source_row.id, record_identity_key=identity_key
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
                signature = canonical_json(
                    {
                        "idempotency_key": record.idempotency_key,
                        "external_record_id": record.external_record_id,
                        "status": record.status.value,
                    }
                )
                identity_key = build_google_record_identity_key(
                    stream_code=record.stream,
                    query_mode=query.query_mode,
                    data_source_family=query.data_source_family,
                    idempotency_key=record.idempotency_key,
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


def build_google_record_identity_key(
    *,
    stream_code: str | GoogleStream,
    query_mode: str | GoogleQueryMode,
    data_source_family: str | None,
    idempotency_key: str,
) -> str:
    """Keep list evidence distinct from reconcile/rollup of the same fact."""

    payload = {
        "version": "google-record-v1",
        "stream_code": GoogleStream(stream_code).value,
        "query_mode": GoogleQueryMode(query_mode).value,
        "data_source_family": data_source_family,
        "idempotency_key": _required_text(idempotency_key, "Google record idempotency key"),
    }
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"google-record-v1:{digest}"


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
        "source_local_date": temporal.local_date
        or (temporal.measured_at_utc.date() if temporal.measured_at_utc is not None else None),
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
        "projection_status": PROJECTION_CURRENT,
        "projection_observed_at": seen_at,
        "retired_at": None,
        "retire_reason": None,
        "last_seen_at": seen_at,
        "updated_at": seen_at,
    }


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
    "GooglePersistenceRepository",
    "GooglePayloadObservationRepository",
    "GoogleRawPayloadRepository",
    "GoogleSourceRecordRepository",
    "GoogleSourceRepository",
    "PERSISTENCE_CONTRACT_VERSION",
    "PROJECTION_CURRENT",
    "build_google_observation_key",
    "build_google_record_identity_key",
    "google_persistence_for",
]
