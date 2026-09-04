"""Offline persistence for the R02 Garmin normalization contract.

This module accepts already-normalized synthetic DTOs and stores their raw
bytes plus a typed current projection.  It deliberately has no Garmin client,
authentication, network, backfill loop, or analytics behavior.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    CoverageInterval,
    GarminActivityRecord,
    GarminDailyRecord,
    GarminFitRecord,
    GarminIntradayRecord,
    GarminMetricState,
    GarminPayloadStatus,
    GarminRawPayload,
    GarminRecordMetric,
    GarminSleepRecord,
    GarminSleepStageInterval,
    GarminSource,
    GarminSourceRecord,
    SyncStreamState,
    utc_now,
)
from healthcheck.db.repositories import canonical_json, repositories_for, restore_stored_utc
from healthcheck.garmin.capabilities import (
    GARMIN_PROVIDER_CODE,
    GARMINCONNECT_VERSION,
    GarminStream,
)
from healthcheck.garmin.contracts import (
    GarminCapabilityFixture,
)
from healthcheck.garmin.normalization import (
    NORMALIZATION_CONTRACT_VERSION,
    GarminFieldState,
    GarminMetricDTO,
    GarminNormalizationResult,
    GarminRecordDTO,
    GarminSourceIdentity,
    GarminTemporalDTO,
)
from healthcheck.garmin.storage import (
    ContentAddressedGarminPayloadStore,
    StoredGarminPayload,
    serialize_garmin_payload,
)

PERSISTENCE_CONTRACT_VERSION = "r02-garmin-persistence-contract-v1"
GARMIN_INPUT_METHOD = "provider_api"
GARMIN_SOURCE_APPLICATION = "python-garminconnect"
GARMIN_COVERAGE_RULE_VERSION = "garmin-coverage-v1"

RawGarminPayload = bytes | bytearray | Mapping[str, object] | GarminCapabilityFixture


@dataclass(frozen=True, slots=True)
class GarminPersistenceOutcome:
    """Identifiers and counts returned by one atomic persistence operation."""

    source: GarminSource
    raw_payload: GarminRawPayload
    records: tuple[GarminSourceRecord, ...]
    inserted_count: int
    updated_count: int
    replayed: bool
    ingest_batch_id: str | None = None
    ingest_event_id: str | None = None


class GarminSourceRepository:
    """Persist explicit Garmin source/device identity through R01 provenance."""

    def __init__(self, session: Session):
        self.session = session
        self.provenance = repositories_for(session)

    def get(self, source_id: str) -> GarminSource | None:
        return self.session.get(GarminSource, source_id)

    def get_by_identity(
        self, *, provider_code: str, source_instance_id: str
    ) -> GarminSource | None:
        return self.session.scalar(
            select(GarminSource).where(
                GarminSource.provider_code == provider_code,
                GarminSource.source_instance_id == source_instance_id,
            )
        )

    def get_or_create(
        self,
        identity: GarminSourceIdentity,
        *,
        input_method: str = GARMIN_INPUT_METHOD,
        acquisition_source_id: str | None = None,
    ) -> GarminSource:
        if not isinstance(identity, GarminSourceIdentity):
            raise TypeError("Garmin source identity is required")
        if input_method != GARMIN_INPUT_METHOD:
            raise ValueError("Garmin persistence uses provider_api as its acquisition method")
        source_instance_id = identity.source_instance_id
        if source_instance_id is None:
            raise ValueError("Garmin source identity must have a source_instance_id")

        provider = self.provenance.providers.get_or_create(
            GARMIN_PROVIDER_CODE,
            "Garmin Connect",
            "wearable",
        )
        device = None
        if identity.device_attributed:
            if identity.device_code is None or identity.device_model is None:
                raise ValueError("attributed Garmin identity requires device code and model")
            device = self.provenance.physical_devices.get_or_create(
                identity.device_code,
                manufacturer="Garmin",
                model=identity.device_model,
                display_name=identity.device_model,
            )

        if acquisition_source_id is None:
            acquisition_source = self.provenance.acquisition_sources.get_or_create(
                provider_id=provider.id,
                physical_device_id=device.id if device is not None else None,
                input_method=input_method,
                source_application=GARMIN_SOURCE_APPLICATION,
                source_application_version=GARMINCONNECT_VERSION,
                configuration_snapshot={"persistence_contract": PERSISTENCE_CONTRACT_VERSION},
            )
        else:
            acquisition_source = self.provenance.acquisition_sources.get_by_id(
                acquisition_source_id
            )
            if acquisition_source is None:
                raise KeyError(f"unknown acquisition source {acquisition_source_id}")
            if acquisition_source.provider_id != provider.id:
                raise ValueError("Garmin acquisition source must belong to garmin_connect")
            if acquisition_source.physical_device_id != (device.id if device is not None else None):
                raise ValueError("Garmin acquisition source device identity does not match")

        existing = self.get_by_identity(
            provider_code=identity.provider_code,
            source_instance_id=source_instance_id,
        )
        if existing is not None:
            if (
                existing.source_kind != identity.source_kind
                or existing.provider_id != provider.id
                or existing.acquisition_source_id != acquisition_source.id
                or existing.physical_device_id != (device.id if device is not None else None)
                or existing.device_attributed != identity.device_attributed
                or existing.device_code != identity.device_code
                or existing.device_model != identity.device_model
            ):
                raise ValueError("Garmin source identity already has conflicting provenance")
            return existing

        source = GarminSource(
            provider_id=provider.id,
            acquisition_source_id=acquisition_source.id,
            physical_device_id=device.id if device is not None else None,
            source_kind=identity.source_kind,
            provider_code=identity.provider_code,
            source_instance_id=source_instance_id,
            device_attributed=identity.device_attributed,
            device_code=identity.device_code,
            device_model=identity.device_model,
        )
        self.session.add(source)
        self.session.flush()
        return source


class GarminRawPayloadRepository:
    """Repository for immutable Garmin payload metadata."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, payload_id: str) -> GarminRawPayload | None:
        return self.session.get(GarminRawPayload, payload_id)

    def get_by_key(
        self, *, garmin_source_id: str, stream_code: str, content_hash: str
    ) -> GarminRawPayload | None:
        return self.session.scalar(
            select(GarminRawPayload).where(
                GarminRawPayload.garmin_source_id == garmin_source_id,
                GarminRawPayload.stream_code == GarminStream(stream_code).value,
                GarminRawPayload.content_hash == content_hash.lower(),
            )
        )

    def list(
        self,
        *,
        garmin_source_id: str | None = None,
        stream_code: str | GarminStream | None = None,
    ) -> list[GarminRawPayload]:
        conditions = []
        if garmin_source_id is not None:
            conditions.append(GarminRawPayload.garmin_source_id == garmin_source_id)
        if stream_code is not None:
            conditions.append(GarminRawPayload.stream_code == GarminStream(stream_code).value)
        statement = (
            select(GarminRawPayload)
            .where(*conditions)
            .order_by(GarminRawPayload.received_at, GarminRawPayload.id)
        )
        return list(self.session.scalars(statement))

    def create(
        self,
        *,
        garmin_source_id: str,
        raw_artifact_id: str,
        content_hash: str,
        stream_code: str | GarminStream,
        payload_format: str,
        normalization_contract_version: str,
        parse_status: str | GarminPayloadStatus,
        record_count: int,
        source_contract_version: str | None = None,
        fixture_id: str | None = None,
        diagnostics: Iterable[Mapping[str, Any]] = (),
        unknown_fields: Iterable[Mapping[str, Any]] = (),
        ingest_event_id: str | None = None,
        sync_run_id: str | None = None,
        source_window_start_utc: datetime | None = None,
        source_window_end_utc: datetime | None = None,
        received_at: datetime | None = None,
    ) -> GarminRawPayload:
        normalized_stream = GarminStream(stream_code).value
        normalized_status = GarminPayloadStatus(parse_status).value
        if payload_format not in {"json", "fit", "binary"}:
            raise ValueError("Garmin payload format must be json, fit, or binary")
        if record_count < 0:
            raise ValueError("Garmin payload record_count must be nonnegative")
        start = _as_utc(source_window_start_utc)
        end = _as_utc(source_window_end_utc)
        _validate_optional_interval(start, end, "source payload window")
        normalized_hash = _required_text(content_hash, "Garmin payload content hash").lower()
        existing = self.get_by_key(
            garmin_source_id=garmin_source_id,
            stream_code=normalized_stream,
            content_hash=normalized_hash,
        )
        if existing is not None:
            if existing.raw_artifact_id != raw_artifact_id:
                raise ValueError("Garmin payload hash is already linked to another raw artifact")
            return existing
        payload = GarminRawPayload(
            garmin_source_id=garmin_source_id,
            raw_artifact_id=raw_artifact_id,
            ingest_event_id=ingest_event_id,
            sync_run_id=sync_run_id,
            stream_code=normalized_stream,
            content_hash=normalized_hash,
            payload_format=payload_format,
            source_contract_version=source_contract_version,
            normalization_contract_version=_required_text(
                normalization_contract_version, "normalization contract version"
            ),
            fixture_id=fixture_id,
            parse_status=normalized_status,
            record_count=record_count,
            diagnostics_json=_json_list_or_none(diagnostics),
            unknown_fields_json=_json_list_or_none(unknown_fields),
            source_window_start_utc=start,
            source_window_end_utc=end,
            received_at=start_or_now(received_at),
        )
        self.session.add(payload)
        self.session.flush()
        return payload


class GarminSourceRecordRepository:
    """Upsert current typed projections while preserving raw payload history."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, record_id: str) -> GarminSourceRecord | None:
        return self.session.get(GarminSourceRecord, record_id)

    def get_by_idempotency_key(
        self, *, garmin_source_id: str, idempotency_key: str
    ) -> GarminSourceRecord | None:
        return self.session.scalar(
            select(GarminSourceRecord).where(
                GarminSourceRecord.garmin_source_id == garmin_source_id,
                GarminSourceRecord.idempotency_key == idempotency_key,
            )
        )

    def list(
        self,
        *,
        garmin_source_id: str | None = None,
        stream_code: str | GarminStream | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[GarminSourceRecord]:
        conditions = []
        if garmin_source_id is not None:
            conditions.append(GarminSourceRecord.garmin_source_id == garmin_source_id)
        if stream_code is not None:
            conditions.append(GarminSourceRecord.stream_code == GarminStream(stream_code).value)
        if start_date is not None:
            conditions.append(GarminSourceRecord.source_local_date >= start_date)
        if end_date is not None:
            conditions.append(GarminSourceRecord.source_local_date <= end_date)
        statement = (
            select(GarminSourceRecord)
            .where(*conditions)
            .order_by(
                GarminSourceRecord.source_local_date,
                GarminSourceRecord.source_timestamp_utc,
                GarminSourceRecord.id,
            )
        )
        return list(self.session.scalars(statement))

    def metrics_for(self, record_id: str) -> list[GarminRecordMetric]:
        return list(
            self.session.scalars(
                select(GarminRecordMetric)
                .where(GarminRecordMetric.record_id == record_id)
                .order_by(GarminRecordMetric.metric_code, GarminRecordMetric.id)
            )
        )

    def sleep_stages_for(self, record_id: str) -> list[GarminSleepStageInterval]:
        sleep_record = self.session.get(GarminSleepRecord, record_id)
        if sleep_record is None:
            return []
        return list(
            self.session.scalars(
                select(GarminSleepStageInterval)
                .where(GarminSleepStageInterval.sleep_record_id == sleep_record.record_id)
                .order_by(GarminSleepStageInterval.ordinal, GarminSleepStageInterval.id)
            )
        )

    def upsert(
        self,
        *,
        garmin_source_id: str,
        raw_payload_id: str,
        record: GarminRecordDTO,
        ingest_event_id: str | None = None,
        seen_at: datetime | None = None,
    ) -> tuple[GarminSourceRecord, bool, bool]:
        if not isinstance(record, GarminRecordDTO):
            raise TypeError("GarminSourceRecordRepository expects a GarminRecordDTO")
        stream_code = record.stream.value
        incoming = _record_values(
            garmin_source_id=garmin_source_id,
            raw_payload_id=raw_payload_id,
            record=record,
            ingest_event_id=ingest_event_id,
        )
        existing = self.get_by_idempotency_key(
            garmin_source_id=garmin_source_id,
            idempotency_key=record.idempotency_key,
        )
        inserted = existing is None
        semantic_changed = inserted
        if existing is None:
            existing = GarminSourceRecord(**incoming)
            self.session.add(existing)
            self.session.flush()
        else:
            if existing.stream_code != stream_code:
                raise ValueError("Garmin idempotency key cannot change stream identity")
            for field_name, value in incoming.items():
                if field_name in {"garmin_source_id", "raw_payload_id", "ingest_event_id"}:
                    continue
                current = getattr(existing, field_name)
                if field_name == "source_timestamp_utc":
                    equal = _same_datetime(current, value)
                else:
                    equal = current == value
                if not equal:
                    semantic_changed = True
                setattr(existing, field_name, value)
            if existing.raw_payload_id != raw_payload_id:
                semantic_changed = True
                existing.raw_payload_id = raw_payload_id
            if ingest_event_id is not None and existing.ingest_event_id != ingest_event_id:
                semantic_changed = True
                existing.ingest_event_id = ingest_event_id

        seen = start_or_now(seen_at)
        if _datetime_key(existing.last_seen_at) is None or seen > _datetime_key(
            existing.last_seen_at
        ):
            existing.last_seen_at = seen
        if semantic_changed:
            existing.updated_at = seen
        self.session.flush()
        self._ensure_typed_record(existing, record)
        self.session.flush()
        self._upsert_metrics(existing.id, record.metrics)
        self.session.flush()
        return existing, inserted, semantic_changed and not inserted

    def _ensure_typed_record(self, row: GarminSourceRecord, record: GarminRecordDTO) -> None:
        local_date = record.temporal.local_date
        if record.stream is GarminStream.DAILY_HEALTH:
            typed = self.session.get(GarminDailyRecord, row.id)
            if typed is None:
                self.session.add(GarminDailyRecord(record_id=row.id, calendar_date=local_date))
            else:
                typed.calendar_date = local_date
        elif record.stream is GarminStream.SLEEP:
            typed = self.session.get(GarminSleepRecord, row.id)
            if typed is None:
                self.session.add(GarminSleepRecord(record_id=row.id, wake_date=local_date))
            else:
                typed.wake_date = local_date
        elif record.stream is GarminStream.ACTIVITY:
            typed = self.session.get(GarminActivityRecord, row.id)
            if typed is None:
                self.session.add(
                    GarminActivityRecord(record_id=row.id, activity_type=record.activity_type)
                )
            else:
                typed.activity_type = record.activity_type
        elif record.stream is GarminStream.INTRADAY:
            typed = self.session.get(GarminIntradayRecord, row.id)
            if typed is None:
                self.session.add(
                    GarminIntradayRecord(
                        record_id=row.id,
                        sample_date=local_date,
                        sample_sequence=record.record_index,
                    )
                )
            else:
                typed.sample_date = local_date
                typed.sample_sequence = record.record_index
        elif record.stream is GarminStream.ORIGINAL_FIT:
            if self.session.get(GarminFitRecord, row.id) is None:
                self.session.add(GarminFitRecord(record_id=row.id))

    def _upsert_metrics(self, record_id: str, metrics: Iterable[GarminMetricDTO]) -> None:
        normalized_metrics = tuple(metrics)
        incoming_codes = {metric.metric_code for metric in normalized_metrics}
        is_sleep_record = self.session.get(GarminSleepRecord, record_id) is not None
        existing_metrics = {
            metric.metric_code: metric
            for metric in self.session.scalars(
                select(GarminRecordMetric).where(GarminRecordMetric.record_id == record_id)
            )
        }
        for metric in normalized_metrics:
            value_number, value_text = _metric_values(metric)
            collection_json = _metric_collection_json(metric)
            values = {
                "capability_code": metric.capability_code,
                "metric_code": metric.metric_code,
                "field_path": metric.field_path,
                "state": GarminMetricState(metric.state).value,
                "value_number": value_number,
                "value_text": value_text,
                "unit": metric.unit,
                "reason": metric.reason,
                "capability_status": _enum_value(metric.capability_status),
                "source_device_attributed": metric.source_device_attributed,
                "collection_json": collection_json,
            }
            stored = existing_metrics.get(metric.metric_code)
            if stored is None:
                self.session.add(GarminRecordMetric(record_id=record_id, **values))
            else:
                for field_name, value in values.items():
                    setattr(stored, field_name, value)

            if metric.metric_code == "sleep_stages":
                self._upsert_sleep_stages(
                    record_id,
                    metric.collection if metric.state is GarminFieldState.VALUE else (),
                )

        for metric_code, stored in existing_metrics.items():
            if metric_code not in incoming_codes:
                self.session.delete(stored)
        if is_sleep_record and "sleep_stages" not in incoming_codes:
            self._upsert_sleep_stages(record_id, ())

    def _upsert_sleep_stages(self, record_id: str, stages: Iterable[Any]) -> None:
        sleep_record = self.session.get(GarminSleepRecord, record_id)
        if sleep_record is None:
            raise ValueError("sleep stages require a typed sleep record")
        normalized_stages = tuple(stages)
        stored_stages = {
            stage.ordinal: stage
            for stage in self.session.scalars(
                select(GarminSleepStageInterval).where(
                    GarminSleepStageInterval.sleep_record_id == sleep_record.record_id
                )
            )
        }
        seen_ordinals: set[int] = set()
        for ordinal, stage in enumerate(normalized_stages):
            start = stage.start
            end = stage.end
            values = _sleep_stage_values(
                sleep_record_id=sleep_record.record_id,
                ordinal=ordinal,
                start=start,
                end=end,
                activity_level=stage.activity_level,
            )
            stored = stored_stages.get(ordinal)
            if stored is None:
                self.session.add(GarminSleepStageInterval(**values))
            else:
                for field_name, value in values.items():
                    if field_name != "sleep_record_id":
                        setattr(stored, field_name, value)
            seen_ordinals.add(ordinal)
        for ordinal, stored in stored_stages.items():
            if ordinal not in seen_ordinals:
                self.session.delete(stored)


class GarminCoverageRepository:
    """Record Garmin coverage facts and stream freshness in R01 tables."""

    def __init__(self, session: Session):
        self.session = session
        self.provenance = repositories_for(session)
        self.sources = GarminSourceRepository(session)

    def get_state(
        self, source: GarminSource | str, stream_code: str | GarminStream
    ) -> SyncStreamState | None:
        source_row = self._source(source)
        stream = GarminStream(stream_code).value
        return self.session.scalar(
            select(SyncStreamState).where(
                SyncStreamState.provider_id == source_row.provider_id,
                SyncStreamState.acquisition_source_id == source_row.acquisition_source_id,
                SyncStreamState.stream_code == stream,
            )
        )

    def record(
        self,
        source: GarminSource | str,
        *,
        stream_code: str | GarminStream,
        metric_code: str,
        interval_start: datetime,
        interval_end: datetime,
        resolution: str,
        status: str,
        observed_count: int | None = None,
        expected_count: int | None = None,
        calculation_rule_version: str = GARMIN_COVERAGE_RULE_VERSION,
        diagnostic_reason: str | None = None,
        attempted_at: datetime | None = None,
        succeeded_at: datetime | None = None,
        watermark: datetime | None = None,
        trailing_window_days: int | None = None,
    ) -> CoverageInterval:
        source_row = self._source(source)
        stream = GarminStream(stream_code).value
        attempted = start_or_now(attempted_at)
        normalized_status = str(getattr(status, "value", status))
        success = (
            _as_utc(succeeded_at) or attempted
            if normalized_status in {"present", "confirmed_empty"}
            else None
        )
        interval = self.provenance.coverage.record(
            provider_id=source_row.provider_id,
            acquisition_source_id=source_row.acquisition_source_id,
            stream_code=stream,
            metric_code=_required_text(metric_code, "coverage metric code"),
            interval_start=_as_utc(interval_start),
            interval_end=_as_utc(interval_end),
            resolution=_required_text(resolution, "coverage resolution"),
            status=normalized_status,
            calculation_rule_version=_required_text(
                calculation_rule_version, "coverage rule version"
            ),
            observed_count=observed_count,
            expected_count=expected_count,
            diagnostic_reason=diagnostic_reason,
        )
        previous = self.get_state(source_row, stream)
        previous_success = _datetime_key(previous.last_success_at) if previous else None
        previous_attempt = _datetime_key(previous.last_attempt_at) if previous else None
        previous_watermark = _datetime_key(previous.watermark) if previous else None
        stored_success = _max_datetime(previous_success, _datetime_key(success))
        stored_attempt = _max_datetime(previous_attempt, _datetime_key(attempted))
        stored_watermark = _max_datetime(previous_watermark, _as_utc(watermark))
        self.provenance.sync.get_or_create_state(
            provider_id=source_row.provider_id,
            acquisition_source_id=source_row.acquisition_source_id,
            stream_code=stream,
            watermark=stored_watermark,
            trailing_window_days=trailing_window_days,
            diagnostic_status=diagnostic_reason or normalized_status,
            last_success_at=stored_success,
            last_attempt_at=stored_attempt,
        )
        return interval

    upsert = record

    def _source(self, source: GarminSource | str) -> GarminSource:
        source_row = (
            source if isinstance(source, GarminSource) else self.session.get(GarminSource, source)
        )
        if source_row is None:
            raise KeyError("unknown Garmin source identity")
        return source_row


class GarminPersistenceRepositories:
    """Convenience bundle for code that wants the R02 repositories separately."""

    def __init__(
        self,
        session: Session,
        *,
        payload_store: ContentAddressedGarminPayloadStore | None = None,
    ):
        self.session = session
        self.provenance = repositories_for(session)
        self.sources = GarminSourceRepository(session)
        self.source_identities = self.sources
        self.raw_payloads = GarminRawPayloadRepository(session)
        self.records = GarminSourceRecordRepository(session)
        self.source_records = self.records
        self.coverage = GarminCoverageRepository(session)
        self.persistence = GarminPersistenceRepository(session, payload_store=payload_store)


class GarminPersistenceRepository:
    """Atomic raw-payload plus typed-projection persistence facade."""

    def __init__(
        self,
        session: Session,
        *,
        payload_store: ContentAddressedGarminPayloadStore | None = None,
    ):
        self.session = session
        self.provenance = repositories_for(session)
        self.sources = GarminSourceRepository(session)
        self.raw_payloads = GarminRawPayloadRepository(session)
        self.records = GarminSourceRecordRepository(session)
        self.coverage = GarminCoverageRepository(session)
        self.payload_store = payload_store

    def persist_result(
        self,
        result: GarminNormalizationResult,
        *,
        payload: RawGarminPayload,
        media_type: str = "application/json",
        payload_format: str | None = None,
        source_identity: GarminSourceIdentity | None = None,
        stream_code: str | GarminStream | None = None,
        source_contract_version: str | None = None,
        source_filename: str | None = None,
        received_at: datetime | None = None,
        source_window_start_utc: datetime | None = None,
        source_window_end_utc: datetime | None = None,
        sync_run_id: str | None = None,
        ingest_event_id: str | None = None,
        create_ingest_event: bool = True,
    ) -> GarminPersistenceOutcome:
        if not isinstance(result, GarminNormalizationResult):
            raise TypeError("GarminPersistenceRepository expects a GarminNormalizationResult")
        source = result.source
        if source_identity is not None:
            if source is not None and source != source_identity:
                raise ValueError("supplied Garmin source identity conflicts with result identity")
            source = source_identity
        if source is None:
            raise ValueError("a source identity is required to persist a Garmin result")
        stream = result.stream
        if stream_code is not None:
            requested_stream = GarminStream(stream_code)
            if stream is not None and stream is not requested_stream:
                raise ValueError("supplied Garmin stream conflicts with result stream")
            stream = requested_stream
        if stream is None:
            raise ValueError("a stream is required to persist a Garmin result")
        for record in result.records:
            if record.source != source or record.stream is not stream:
                raise ValueError("Garmin result contains a record with conflicting provenance")

        stored = self._store_payload(
            payload,
            media_type=media_type,
            payload_format=payload_format,
        )
        source_row = self.sources.get_or_create(source)
        artifact = self.provenance.raw_artifacts.get_or_create(
            content_hash=stored.content_hash,
            kind="garmin_payload",
            media_type=_normalized_media_type(media_type),
            byte_size=stored.byte_size,
            relative_storage_path=stored.relative_storage_path,
            source_filename=source_filename,
        )
        existing_payload = self.raw_payloads.get_by_key(
            garmin_source_id=source_row.id,
            stream_code=stream,
            content_hash=stored.content_hash,
        )

        batch = None
        event = self.provenance.ingest_events.get(ingest_event_id) if ingest_event_id else None
        if ingest_event_id is not None and event is None:
            raise KeyError(f"unknown ingest event {ingest_event_id}")
        if event is not None and event.acquisition_source_id != source_row.acquisition_source_id:
            raise ValueError("Garmin ingest event does not belong to the source identity")
        if existing_payload is None and event is None and create_ingest_event:
            batch = self.provenance.ingest_batches.create(
                acquisition_source_id=source_row.acquisition_source_id,
                batch_kind="provider_sync",
                parser_name="garmin-normalization",
                parser_version=result.contract_version,
                status="received",
            )
            event = self.provenance.ingest_events.get_or_create(
                ingest_batch_id=batch.id,
                acquisition_source_id=source_row.acquisition_source_id,
                raw_artifact_id=artifact.id,
                provider_stream=stream.value,
                semantic_fingerprint=f"garmin-payload:{stored.content_hash}",
                event_type="insert",
                status="parsed",
            )

        event_id = (
            existing_payload.ingest_event_id
            if existing_payload is not None and existing_payload.ingest_event_id is not None
            else event.id
            if event is not None
            else ingest_event_id
        )
        raw_payload = existing_payload or self.raw_payloads.create(
            garmin_source_id=source_row.id,
            raw_artifact_id=artifact.id,
            content_hash=stored.content_hash,
            stream_code=stream,
            payload_format=payload_format or _payload_format_for_media_type(media_type),
            source_contract_version=source_contract_version or _source_contract_version(payload),
            normalization_contract_version=result.contract_version,
            parse_status=result.status.value,
            record_count=len(result.records),
            diagnostics=(item.as_dict() for item in result.diagnostics),
            unknown_fields=(item.as_dict() for item in result.unknown_fields),
            ingest_event_id=event_id,
            sync_run_id=sync_run_id,
            source_window_start_utc=source_window_start_utc,
            source_window_end_utc=source_window_end_utc,
            fixture_id=result.fixture_id,
            received_at=received_at,
        )

        seen_at = start_or_now(received_at)
        seen_records: dict[str, str] = {}
        records: list[GarminSourceRecord] = []
        inserted_count = 0
        updated_count = 0
        for record in result.records:
            signature = canonical_json(record.as_dict())
            previous_signature = seen_records.get(record.idempotency_key)
            if previous_signature is not None:
                if previous_signature != signature:
                    raise ValueError("one Garmin result contains conflicting duplicate identities")
                continue
            seen_records[record.idempotency_key] = signature
            stored_record, inserted, updated = self.records.upsert(
                garmin_source_id=source_row.id,
                raw_payload_id=raw_payload.id,
                record=record,
                ingest_event_id=event_id,
                seen_at=seen_at,
            )
            records.append(stored_record)
            inserted_count += int(inserted)
            updated_count += int(updated)

        if batch is not None and event is not None:
            final_status = "failed" if result.status.value == "invalid" else "committed"
            final_event_status = "failed" if result.status.value == "invalid" else "committed"
            self.provenance.ingest_events.set_status(
                event.id,
                final_event_status,
                diagnostic_code=(result.diagnostics[0].code if result.diagnostics else None),
                diagnostic_reason=(result.diagnostics[0].message if result.diagnostics else None),
            )
            self.provenance.ingest_batches.update(
                batch.id,
                status=final_status,
                received_count=1,
                parsed_count=1,
                committed_count=0 if result.status.value == "invalid" else 1,
                failed_count=1 if result.status.value == "invalid" else 0,
                diagnostic_reason=(result.diagnostics[0].message if result.diagnostics else None),
                completed=True,
            )

        return GarminPersistenceOutcome(
            source=source_row,
            raw_payload=raw_payload,
            records=tuple(records),
            inserted_count=inserted_count,
            updated_count=updated_count,
            replayed=existing_payload is not None and inserted_count == 0 and updated_count == 0,
            ingest_batch_id=batch.id if batch is not None else None,
            ingest_event_id=event_id,
        )

    persist = persist_result
    upsert_result = persist_result

    def _store_payload(
        self,
        payload: RawGarminPayload,
        *,
        media_type: str,
        payload_format: str | None,
    ) -> StoredGarminPayload:
        if self.payload_store is None:
            raise ValueError("a ContentAddressedGarminPayloadStore is required for raw storage")
        payload_bytes = serialize_garmin_payload(payload)
        return self.payload_store.put(
            payload_bytes,
            media_type=media_type,
            payload_format=payload_format,
        )


GarminPersistenceService = GarminPersistenceRepository


def garmin_persistence_for(
    session: Session,
    *,
    payload_store: ContentAddressedGarminPayloadStore | None = None,
) -> GarminPersistenceRepository:
    """Build the persistence facade for an existing transaction session."""

    return GarminPersistenceRepository(session, payload_store=payload_store)


def _record_values(
    *,
    garmin_source_id: str,
    raw_payload_id: str,
    record: GarminRecordDTO,
    ingest_event_id: str | None,
) -> dict[str, Any]:
    temporal = record.temporal
    return {
        "garmin_source_id": garmin_source_id,
        "raw_payload_id": raw_payload_id,
        "ingest_event_id": ingest_event_id,
        "stream_code": record.stream.value,
        "idempotency_key": record.idempotency_key,
        "external_record_id": record.record_id,
        "record_index": record.record_index,
        "activity_type": record.activity_type,
        "source_path": record.source_path,
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
        "normalization_contract_version": NORMALIZATION_CONTRACT_VERSION,
        "diagnostics_json": _json_list_or_none(item.as_dict() for item in record.diagnostics),
        "unknown_fields_json": _json_list_or_none(item.as_dict() for item in record.unknown_fields),
    }


def _metric_values(metric: GarminMetricDTO) -> tuple[float | None, str | None]:
    if metric.state is not GarminFieldState.VALUE:
        return None, None
    if isinstance(metric.value, bool):
        raise ValueError("boolean Garmin metric values are not persistable")
    if isinstance(metric.value, (int, float)):
        return float(metric.value), None
    if isinstance(metric.value, str):
        return None, metric.value
    if metric.value is None and metric.collection:
        return None, None
    if metric.value is None:
        return None, None
    raise ValueError("unsupported Garmin metric value type")


def _metric_collection_json(metric: GarminMetricDTO) -> str | None:
    if metric.state is not GarminFieldState.VALUE:
        return None
    if metric.metric_code == "sleep_stages":
        return canonical_json([item.as_dict() for item in metric.collection])
    if metric.collection:
        return canonical_json([item.as_dict() for item in metric.collection])
    return None


def _sleep_stage_values(
    *,
    sleep_record_id: str,
    ordinal: int,
    start: GarminTemporalDTO,
    end: GarminTemporalDTO,
    activity_level: str | None,
) -> dict[str, Any]:
    return {
        "sleep_record_id": sleep_record_id,
        "ordinal": ordinal,
        "start_precision": start.precision.value,
        "end_precision": end.precision.value,
        "start_at_utc": _as_utc(start.measured_at_utc),
        "end_at_utc": _as_utc(end.measured_at_utc),
        "start_local_date": start.local_date,
        "end_local_date": end.local_date,
        "start_local_wall_time": start.local_wall_time,
        "end_local_wall_time": end.local_wall_time,
        "start_source_timestamp": start.source_local_timestamp,
        "end_source_timestamp": end.source_local_timestamp,
        "start_source_timezone": start.source_timezone,
        "end_source_timezone": end.source_timezone,
        "start_utc_offset_minutes": start.source_utc_offset_minutes,
        "end_utc_offset_minutes": end.source_utc_offset_minutes,
        "start_source_field": start.source_field,
        "end_source_field": end.source_field,
        "activity_level": activity_level,
        "start_temporal_json": canonical_json(start.as_dict()),
        "end_temporal_json": canonical_json(end.as_dict()),
    }


def _source_contract_version(payload: RawGarminPayload) -> str | None:
    if isinstance(payload, GarminCapabilityFixture):
        return payload.contract_version
    if isinstance(payload, Mapping):
        value = payload.get("fixture_contract_version")
        return value if isinstance(value, str) and value.strip() else None
    return None


def _payload_format_for_media_type(media_type: str) -> str:
    normalized = _normalized_media_type(media_type)
    if "json" in normalized:
        return "json"
    if "fit" in normalized:
        return "fit"
    return "binary"


def _normalized_media_type(media_type: str) -> str:
    normalized = media_type.split(";", 1)[0].strip().lower()
    if not normalized:
        raise ValueError("Garmin payload media type is required")
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
        raise ValueError("Garmin UTC timestamps must be timezone-aware")
    return value.astimezone(UTC)


def _datetime_key(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    restored = restore_stored_utc(value)
    return restored.astimezone(UTC) if restored is not None else None


def _same_datetime(left: datetime | None, right: datetime | None) -> bool:
    return _datetime_key(left) == _datetime_key(right)


def _max_datetime(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def start_or_now(value: datetime | None) -> datetime:
    return _as_utc(value) or utc_now()


def _validate_optional_interval(start: datetime | None, end: datetime | None, label: str) -> None:
    if (start is None) != (end is None):
        raise ValueError(f"{label} requires both boundaries")
    if start is not None and end is not None and end <= start:
        raise ValueError(f"{label} end must be after start")


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


__all__ = [
    "GARMIN_COVERAGE_RULE_VERSION",
    "GARMIN_INPUT_METHOD",
    "GARMIN_SOURCE_APPLICATION",
    "GarminCoverageRepository",
    "GarminPersistenceOutcome",
    "GarminPersistenceRepository",
    "GarminPersistenceRepositories",
    "GarminPersistenceService",
    "GarminRawPayloadRepository",
    "GarminSourceRecordRepository",
    "GarminSourceRepository",
    "PERSISTENCE_CONTRACT_VERSION",
    "garmin_persistence_for",
]
