"""Authenticated openScale-sync webhook ingestion and durable persistence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from healthcheck.canonical import CanonicalSelectionService
from healthcheck.config import Settings
from healthcheck.db.models import (
    IngestBatch,
    IngestStatus,
    MeasurementSession,
)
from healthcheck.db.repositories import (
    ProvenanceRepositories,
    canonical_json,
    repositories_for,
    restore_stored_utc,
)
from healthcheck.ingestion.openscale.auth import require_matching_bearer
from healthcheck.ingestion.openscale.contract import (
    OPENSCALE_CONTRACT_VERSION,
    EnvelopeResult,
    InvalidBatchItem,
    NormalizedMeasurement,
    normalize_envelope,
)
from healthcheck.ingestion.openscale.errors import OpenScaleIngestError
from healthcheck.ingestion.openscale.provenance import (
    algorithm_for_metric,
    ensure_openscale_acquisition_source,
    require_source_instance_id,
)
from healthcheck.ingestion.openscale.store import ContentAddressedPayloadStore
from healthcheck.logging import log_event
from healthcheck.runtime import RuntimePaths


@dataclass(frozen=True, slots=True)
class ItemOutcome:
    status: str
    event_id: str | None
    session_id: str | None = None
    reason_code: str | None = None
    duplicate_of_event_id: str | None = None
    batch_index: int | None = None


@dataclass(frozen=True, slots=True)
class WebhookIngestResult:
    batch_id: str | None
    event: str
    status: str
    items: tuple[ItemOutcome, ...] = ()
    acknowledged: bool = False


class OpenScaleWebhookService:
    """Persist one authenticated openScale-sync envelope through repositories."""

    def __init__(self, session: Session, paths: RuntimePaths, settings: Settings):
        self.session = session
        self.paths = paths
        self.settings = settings
        self.repos = repositories_for(session)
        self.store = ContentAddressedPayloadStore(paths.payloads.parent)
        self.source_instance_id = require_source_instance_id(settings.openscale_source_instance_id)
        self.algorithm_identity = settings.openscale_algorithm_identity or "openscale-default"
        self.config_identity = settings.openscale_config_identity or "unknown"

    def ingest(
        self,
        *,
        body: bytes,
        authorization_header: str | None,
        media_type: str | None = "application/json",
    ) -> WebhookIngestResult:
        require_matching_bearer(authorization_header, self.settings.openscale_ingest_token)
        payload = _parse_json_object(body)
        envelope = normalize_envelope(
            payload,
            source_instance_id=self.source_instance_id,
            algorithm_identity=self.algorithm_identity,
            config_identity=self.config_identity,
        )
        if _is_invalid_top_level(envelope):
            log_event(
                "openscale_ingest_rejected",
                operation="openscale_ingest",
                status="error",
                reason=_primary_reason(envelope),
            )
            raise OpenScaleIngestError(
                "invalid_envelope",
                "webhook envelope is invalid",
                status_code=400,
            )

        stored = self.store.put(body, media_type=media_type or "application/json")
        source = ensure_openscale_acquisition_source(
            self.repos,
            source_instance_id=self.source_instance_id,
            configuration_fingerprint=self.config_identity,
        )
        artifact = self.repos.raw_artifacts.get_or_create(
            content_hash=stored.content_hash,
            kind="openscale_webhook",
            media_type=(media_type or "application/json").split(";")[0].strip()
            or "application/json",
            byte_size=stored.byte_size,
            relative_storage_path=stored.relative_storage_path,
        )
        batch = self.repos.ingest_batches.create(
            acquisition_source_id=source.id,
            batch_kind="webhook",
            parser_name="openscale-sync-generic-webhook",
            parser_version=OPENSCALE_CONTRACT_VERSION,
            status=IngestStatus.RECEIVED.value,
        )

        outcomes: list[ItemOutcome] = []
        if envelope.is_control:
            outcomes.append(
                self._process_control(
                    batch=batch,
                    envelope=envelope,
                    acquisition_source_id=source.id,
                    raw_artifact_id=artifact.id,
                    payload=payload,
                )
            )
        else:
            for warning in envelope.item_warnings:
                # Non-fatal metric conflicts are retained as durable diagnostics
                # attached to the surviving measurement when present.
                del warning
            for invalid in envelope.invalid_items:
                outcomes.append(
                    self._quarantine_invalid(
                        batch=batch,
                        acquisition_source_id=source.id,
                        raw_artifact_id=artifact.id,
                        invalid=invalid,
                        event_type=envelope.event,
                    )
                )
            for measurement in envelope.measurements:
                outcomes.append(
                    self._process_measurement(
                        batch=batch,
                        acquisition_source_id=source.id,
                        raw_artifact_id=artifact.id,
                        measurement=measurement,
                        event_type=envelope.event,
                    )
                )

        committed = sum(1 for item in outcomes if item.status in {"committed", "duplicate"})
        failed = sum(1 for item in outcomes if item.status == "failed")
        final_status = IngestStatus.COMMITTED.value
        if failed and not committed:
            final_status = IngestStatus.FAILED.value
        elif failed:
            final_status = IngestStatus.COMMITTED.value
        self.repos.ingest_batches.update(
            batch.id,
            status=final_status,
            received_count=max(len(outcomes), 1),
            parsed_count=len(outcomes),
            committed_count=committed,
            failed_count=failed,
            completed=True,
        )
        if any(
            item.status in {"committed", "rejected"} and item.session_id is not None
            for item in outcomes
        ):
            CanonicalSelectionService(self.session).recompute_dashboard()
        log_event(
            "openscale_ingest",
            operation="openscale_ingest",
            status=final_status,
            count=len(outcomes),
        )
        return WebhookIngestResult(
            batch_id=batch.id,
            event=envelope.event,
            status=final_status,
            items=tuple(outcomes),
            acknowledged=True,
        )

    def _process_control(
        self,
        *,
        batch: IngestBatch,
        envelope: EnvelopeResult,
        acquisition_source_id: str,
        raw_artifact_id: str,
        payload: dict[str, Any],
    ) -> ItemOutcome:
        if envelope.event == "test":
            event = self.repos.ingest_events.get_or_create(
                ingest_batch_id=batch.id,
                acquisition_source_id=acquisition_source_id,
                raw_artifact_id=raw_artifact_id,
                event_type="test",
                semantic_fingerprint=f"test:{stored_hash(raw_artifact_id)}",
                status=IngestStatus.COMMITTED.value,
            )
            if event.status != IngestStatus.COMMITTED.value:
                self.repos.ingest_events.set_status(event.id, IngestStatus.COMMITTED.value)
            return ItemOutcome(status="committed", event_id=event.id)

        if envelope.event == "clear":
            user_id = payload.get("userId")
            external_user_id = (
                user_id.strip() if isinstance(user_id, str) and user_id.strip() else None
            )
            event = self.repos.ingest_events.get_or_create(
                ingest_batch_id=batch.id,
                acquisition_source_id=acquisition_source_id,
                raw_artifact_id=raw_artifact_id,
                external_user_id=external_user_id,
                event_type="clear",
                semantic_fingerprint=(
                    f"clear:{acquisition_source_id}:{external_user_id or '*'}:{raw_artifact_id}"
                ),
                status=IngestStatus.RECEIVED.value,
            )
            if event.status == IngestStatus.COMMITTED.value:
                return ItemOutcome(
                    status="duplicate",
                    event_id=event.id,
                    duplicate_of_event_id=event.id,
                )
            nested = self.session.begin_nested()
            try:
                heads = self._current_heads_for_user(acquisition_source_id, external_user_id)
                last_session_id = None
                for head in heads:
                    tombstone = self.repos.measurement_sessions.create_tombstone(
                        head.id,
                        ingest_event_id=event.id,
                        raw_artifact_id=raw_artifact_id,
                    )
                    last_session_id = tombstone.id
                self.repos.ingest_events.set_status(event.id, IngestStatus.COMMITTED.value)
                nested.commit()
                return ItemOutcome(
                    status="committed",
                    event_id=event.id,
                    session_id=last_session_id,
                )
            except Exception:
                nested.rollback()
                self.repos.ingest_events.set_status(
                    event.id,
                    IngestStatus.FAILED.value,
                    diagnostic_code="clear_failed",
                    diagnostic_reason="clear tombstone persistence failed",
                )
                return ItemOutcome(
                    status="failed",
                    event_id=event.id,
                    reason_code="clear_failed",
                )

        raise OpenScaleIngestError("invalid_event", "unsupported control event", status_code=400)

    def _quarantine_invalid(
        self,
        *,
        batch: IngestBatch,
        acquisition_source_id: str,
        raw_artifact_id: str,
        invalid: InvalidBatchItem,
        event_type: str,
    ) -> ItemOutcome:
        reason = invalid.failures[0].reason_code if invalid.failures else "invalid_measurement"
        fingerprint = (
            f"invalid:{event_type}:{invalid.batch_index}:"
            f"{raw_artifact_id}:{reason}:{','.join(f.reason_code for f in invalid.failures)}"
        )
        nested = self.session.begin_nested()
        try:
            event = self.repos.ingest_events.get_or_create(
                ingest_batch_id=batch.id,
                acquisition_source_id=acquisition_source_id,
                raw_artifact_id=raw_artifact_id,
                event_type=event_type,
                semantic_fingerprint=fingerprint,
                status=IngestStatus.FAILED.value,
                diagnostic_code=reason,
                diagnostic_reason=_sanitize_failures(invalid.failures),
            )
            if event.status != IngestStatus.FAILED.value:
                self.repos.ingest_events.set_status(
                    event.id,
                    IngestStatus.FAILED.value,
                    diagnostic_code=reason,
                    diagnostic_reason=_sanitize_failures(invalid.failures),
                )
            nested.commit()
            return ItemOutcome(
                status="failed",
                event_id=event.id,
                reason_code=reason,
                batch_index=invalid.batch_index,
            )
        except Exception:
            nested.rollback()
            raise

    def _process_measurement(
        self,
        *,
        batch: IngestBatch,
        acquisition_source_id: str,
        raw_artifact_id: str,
        measurement: NormalizedMeasurement,
        event_type: str,
    ) -> ItemOutcome:
        identity = measurement.identity or f"missing-identity:{raw_artifact_id}"
        evidence = _event_evidence(measurement, event_type)
        source_timestamp = measurement.measured_at_utc
        nested = self.session.begin_nested()
        try:
            if event_type == "delete":
                outcome = self._apply_delete(
                    batch=batch,
                    acquisition_source_id=acquisition_source_id,
                    raw_artifact_id=raw_artifact_id,
                    measurement=measurement,
                    fingerprint=identity,
                )
            else:
                outcome = self._apply_upsert(
                    batch=batch,
                    acquisition_source_id=acquisition_source_id,
                    raw_artifact_id=raw_artifact_id,
                    measurement=measurement,
                    event_type=event_type,
                    identity=identity,
                    evidence=evidence,
                    source_timestamp=source_timestamp,
                )
            nested.commit()
            return outcome
        except OpenScaleIngestError as exc:
            nested.rollback()
            event = self.repos.ingest_events.get_or_create(
                ingest_batch_id=batch.id,
                acquisition_source_id=acquisition_source_id,
                raw_artifact_id=raw_artifact_id,
                external_user_id=measurement.user_id,
                external_record_id=measurement.record_id,
                event_type=event_type,
                semantic_fingerprint=f"failed:{identity}:{exc.code}",
                source_timestamp=source_timestamp,
                status=IngestStatus.FAILED.value,
                diagnostic_code=exc.code,
                diagnostic_reason=exc.message,
            )
            return ItemOutcome(
                status="failed",
                event_id=event.id,
                reason_code=exc.code,
                batch_index=measurement.batch_index,
            )
        except Exception:
            nested.rollback()
            event = self.repos.ingest_events.get_or_create(
                ingest_batch_id=batch.id,
                acquisition_source_id=acquisition_source_id,
                raw_artifact_id=raw_artifact_id,
                external_user_id=measurement.user_id,
                external_record_id=measurement.record_id,
                event_type=event_type,
                semantic_fingerprint=f"failed:{identity}:persistence_error",
                source_timestamp=source_timestamp,
                status=IngestStatus.FAILED.value,
                diagnostic_code="persistence_error",
                diagnostic_reason="measurement persistence failed",
            )
            return ItemOutcome(
                status="failed",
                event_id=event.id,
                reason_code="persistence_error",
                batch_index=measurement.batch_index,
            )

    def _apply_upsert(
        self,
        *,
        batch: IngestBatch,
        acquisition_source_id: str,
        raw_artifact_id: str,
        measurement: NormalizedMeasurement,
        event_type: str,
        identity: str,
        evidence: str,
        source_timestamp: datetime | None,
    ) -> ItemOutcome:
        existing_event = self.repos.ingest_events.find_existing(
            acquisition_source_id=acquisition_source_id,
            external_user_id=measurement.user_id,
            external_record_id=measurement.record_id,
            semantic_fingerprint=evidence,
            event_type=event_type,
            source_timestamp=source_timestamp,
        )
        if existing_event is not None and existing_event.status == IngestStatus.COMMITTED.value:
            session = self.repos.measurement_sessions.find_by_source_identity(
                acquisition_source_id=acquisition_source_id,
                source_record_id=_source_record_id(measurement),
                source_fingerprint=identity,
                semantic_key=identity,
            )
            if session is None or session.confirmation_status != "rejected":
                return ItemOutcome(
                    status="duplicate",
                    event_id=existing_event.id,
                    session_id=session.id if session is not None else None,
                    duplicate_of_event_id=existing_event.id,
                    batch_index=measurement.batch_index,
                )

        event = self.repos.ingest_events.get_or_create(
            ingest_batch_id=batch.id,
            acquisition_source_id=acquisition_source_id,
            raw_artifact_id=raw_artifact_id,
            external_user_id=measurement.user_id,
            external_record_id=measurement.record_id,
            semantic_fingerprint=evidence,
            event_type=event_type,
            source_timestamp=source_timestamp,
            status=IngestStatus.PARSED.value,
        )
        if event.status == IngestStatus.COMMITTED.value:
            session = self.repos.measurement_sessions.find_by_source_identity(
                acquisition_source_id=acquisition_source_id,
                source_record_id=_source_record_id(measurement),
                source_fingerprint=identity,
                semantic_key=identity,
            )
            if session is None or session.confirmation_status != "rejected":
                return ItemOutcome(
                    status="duplicate",
                    event_id=event.id,
                    session_id=session.id if session is not None else None,
                    duplicate_of_event_id=event.id,
                    batch_index=measurement.batch_index,
                )
            # Tombstone recovery needs a fresh ingest event identity.
            event = self.repos.ingest_events.get_or_create(
                ingest_batch_id=batch.id,
                acquisition_source_id=acquisition_source_id,
                raw_artifact_id=raw_artifact_id,
                external_user_id=measurement.user_id,
                external_record_id=measurement.record_id,
                semantic_fingerprint=f"revive:{evidence}",
                event_type=event_type,
                source_timestamp=source_timestamp,
                status=IngestStatus.PARSED.value,
            )

        usable = measurement.usable_metrics()
        if not usable and event_type in {"insert", "update"}:
            # Structurally valid but no usable metrics — durable quarantine.
            self.repos.ingest_events.set_status(
                event.id,
                IngestStatus.FAILED.value,
                diagnostic_code="no_usable_metrics",
                diagnostic_reason="measurement carried no usable canonical metrics",
            )
            return ItemOutcome(
                status="failed",
                event_id=event.id,
                reason_code="no_usable_metrics",
                batch_index=measurement.batch_index,
            )

        precision, local_date, timestamp_utc, local_timestamp = _session_time(measurement)
        source_record_id = _source_record_id(measurement)
        head = self.repos.measurement_sessions.find_by_source_identity(
            acquisition_source_id=acquisition_source_id,
            source_record_id=source_record_id,
            source_fingerprint=identity,
            semantic_key=identity,
        )
        if head is not None and self.repos.measurement_sessions.is_current_head(head.id):
            if _session_matches_measurement(
                head, measurement, precision, local_date, timestamp_utc
            ):
                if _scalars_match(self.repos, head, usable):
                    self.repos.ingest_events.set_status(event.id, IngestStatus.COMMITTED.value)
                    return ItemOutcome(
                        status="duplicate",
                        event_id=event.id,
                        session_id=head.id,
                        duplicate_of_event_id=event.id,
                        batch_index=measurement.batch_index,
                    )
            session_record = self.repos.measurement_sessions.create_revision(
                head.id,
                source_local_date=local_date,
                temporal_precision=precision,
                source_timestamp_utc=timestamp_utc,
                source_local_timestamp=local_timestamp,
                ingest_event_id=event.id,
                raw_artifact_id=raw_artifact_id,
                source_record_id=source_record_id,
                source_fingerprint=identity,
                semantic_key=identity,
            )
        elif head is not None and not self.repos.measurement_sessions.is_current_head(head.id):
            # Walk to current head (may be tombstone); if rejected, create a new
            # confirmed revision chain from the latest row sharing identity.
            current = _latest_identity_session(
                self.repos, acquisition_source_id, source_record_id, identity
            )
            if current is not None and current.confirmation_status == "confirmed":
                session_record = self.repos.measurement_sessions.create_revision(
                    current.id,
                    source_local_date=local_date,
                    temporal_precision=precision,
                    source_timestamp_utc=timestamp_utc,
                    source_local_timestamp=local_timestamp,
                    ingest_event_id=event.id,
                    raw_artifact_id=raw_artifact_id,
                    source_record_id=source_record_id,
                    source_fingerprint=identity,
                    semantic_key=identity,
                )
            elif current is not None and current.confirmation_status == "rejected":
                # Revive after tombstone with a new confirmed revision (insert-only).
                session_record = self.repos.measurement_sessions.create_revision(
                    current.id,
                    source_local_date=local_date,
                    temporal_precision=precision,
                    source_timestamp_utc=timestamp_utc,
                    source_local_timestamp=local_timestamp,
                    ingest_event_id=event.id,
                    raw_artifact_id=raw_artifact_id,
                    source_record_id=source_record_id,
                    source_fingerprint=identity,
                    semantic_key=identity,
                )
            else:
                session_record = self.repos.measurement_sessions.create_confirmed(
                    acquisition_source_id=acquisition_source_id,
                    ingest_event_id=event.id,
                    raw_artifact_id=raw_artifact_id,
                    source_record_id=source_record_id,
                    source_fingerprint=identity,
                    semantic_key=identity,
                    source_local_date=local_date,
                    temporal_precision=precision,
                    source_timestamp_utc=timestamp_utc,
                    source_local_timestamp=local_timestamp,
                )
        else:
            session_record = self.repos.measurement_sessions.create_confirmed(
                acquisition_source_id=acquisition_source_id,
                ingest_event_id=event.id,
                raw_artifact_id=raw_artifact_id,
                source_record_id=source_record_id,
                source_fingerprint=identity,
                semantic_key=identity,
                source_local_date=local_date,
                temporal_precision=precision,
                source_timestamp_utc=timestamp_utc,
                source_local_timestamp=local_timestamp,
            )

        for metric in usable:
            assert metric.value is not None
            algorithm = algorithm_for_metric(
                self.repos,
                metric_code=metric.metric_code,
                algorithm_identity=self.algorithm_identity,
                config_identity=self.config_identity,
            )
            previous = self.repos.scalar_measurements.active_for_source_metric(
                acquisition_source_id=acquisition_source_id,
                metric_code=metric.metric_code,
                semantic_key=session_record.semantic_key,
                source_record_id=session_record.source_record_id,
            )
            if previous is not None and previous.measurement_session_id != session_record.id:
                self.repos.scalar_measurements.create_revision(
                    previous.id,
                    measurement_session_id=session_record.id,
                    normalized_value=float(metric.value),
                    normalized_unit=metric.unit or "",
                    measurement_algorithm_id=algorithm.id,
                    original_value=str(metric.value),
                    original_unit=metric.source_unit,
                    source_text=metric.source_key,
                )
            else:
                self.repos.scalar_measurements.create(
                    measurement_session_id=session_record.id,
                    metric_code=metric.metric_code,
                    normalized_value=float(metric.value),
                    normalized_unit=metric.unit or "",
                    measurement_algorithm_id=algorithm.id,
                    original_value=str(metric.value),
                    original_unit=metric.source_unit,
                    source_text=metric.source_key,
                )

        self.repos.ingest_events.set_status(event.id, IngestStatus.COMMITTED.value)
        return ItemOutcome(
            status="committed",
            event_id=event.id,
            session_id=session_record.id,
            batch_index=measurement.batch_index,
        )

    def _apply_delete(
        self,
        *,
        batch: IngestBatch,
        acquisition_source_id: str,
        raw_artifact_id: str,
        measurement: NormalizedMeasurement,
        fingerprint: str,
    ) -> ItemOutcome:
        event = self.repos.ingest_events.get_or_create(
            ingest_batch_id=batch.id,
            acquisition_source_id=acquisition_source_id,
            raw_artifact_id=raw_artifact_id,
            external_user_id=measurement.user_id,
            external_record_id=measurement.record_id,
            semantic_fingerprint=fingerprint,
            event_type="delete",
            source_timestamp=measurement.measured_at_utc,
            status=IngestStatus.PARSED.value,
        )
        if event.status == IngestStatus.COMMITTED.value:
            return ItemOutcome(
                status="duplicate",
                event_id=event.id,
                duplicate_of_event_id=event.id,
                batch_index=measurement.batch_index,
            )

        targets = self._sessions_for_delete(acquisition_source_id, measurement, fingerprint)
        last_session_id = None
        for head in targets:
            if not self.repos.measurement_sessions.is_current_head(head.id):
                continue
            if head.confirmation_status != "confirmed":
                continue
            tombstone = self.repos.measurement_sessions.create_tombstone(
                head.id,
                ingest_event_id=event.id,
                raw_artifact_id=raw_artifact_id,
            )
            last_session_id = tombstone.id
        self.repos.ingest_events.set_status(event.id, IngestStatus.COMMITTED.value)
        return ItemOutcome(
            status="committed",
            event_id=event.id,
            session_id=last_session_id,
            batch_index=measurement.batch_index,
        )

    def _sessions_for_delete(
        self,
        acquisition_source_id: str,
        measurement: NormalizedMeasurement,
        fingerprint: str,
    ) -> list[MeasurementSession]:
        if measurement.record_id is not None:
            found = self.repos.measurement_sessions.find_by_source_identity(
                acquisition_source_id=acquisition_source_id,
                source_record_id=_source_record_id(measurement),
            )
            return [found] if found is not None else []
        # Time fallback: match confirmed heads for this source/user at the sender time.
        candidates = self.repos.measurement_sessions.current_heads(
            acquisition_source_id=acquisition_source_id
        )
        matched: list[MeasurementSession] = []
        for session in candidates:
            event = (
                self.repos.ingest_events.get(session.ingest_event_id)
                if session.ingest_event_id is not None
                else None
            )
            if event is not None and event.external_user_id != measurement.user_id:
                continue
            if _time_matches_session(session, measurement):
                matched.append(session)
            elif session.source_fingerprint == fingerprint.lower():
                matched.append(session)
        return matched

    def _current_heads_for_user(
        self, acquisition_source_id: str, external_user_id: str | None
    ) -> list[MeasurementSession]:
        heads = self.repos.measurement_sessions.current_heads(
            acquisition_source_id=acquisition_source_id
        )
        if external_user_id is None:
            return heads
        matched: list[MeasurementSession] = []
        for head in heads:
            if head.ingest_event_id is None:
                continue
            event = self.repos.ingest_events.get(head.ingest_event_id)
            if event is not None and event.external_user_id == external_user_id:
                matched.append(head)
        return matched


def stored_hash(raw_artifact_id: str) -> str:
    return raw_artifact_id


def _parse_json_object(body: bytes) -> dict[str, Any]:
    if not body:
        raise OpenScaleIngestError("invalid_json", "request body must be JSON", status_code=400)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenScaleIngestError(
            "invalid_json", "request body must be JSON", status_code=400
        ) from exc
    if not isinstance(payload, dict):
        raise OpenScaleIngestError(
            "invalid_envelope", "top-level payload must be an object", status_code=400
        )
    return payload


def _is_invalid_top_level(envelope: EnvelopeResult) -> bool:
    if envelope.is_control:
        return bool(envelope.failures)
    # A batch/single payload is processable when at least one measurement or
    # quarantined item exists.  Single-mode fatal failures leave both empty and
    # place reason codes on envelope.failures — that is an invalid top level.
    if envelope.measurements or envelope.invalid_items:
        return False
    return True


def _primary_reason(envelope: EnvelopeResult) -> str:
    if envelope.failures:
        return envelope.failures[0].reason_code
    if envelope.invalid_items and envelope.invalid_items[0].failures:
        return envelope.invalid_items[0].failures[0].reason_code
    return "invalid_envelope"


def _sanitize_failures(failures: tuple[Any, ...]) -> str:
    codes = [getattr(item, "reason_code", "invalid") for item in failures]
    return ",".join(codes) if codes else "invalid_measurement"


def _event_evidence(measurement: NormalizedMeasurement, event_type: str) -> str:
    """Content-aware event identity so successive updates do not collapse."""

    payload = {
        "identity": measurement.identity,
        "event_type": event_type,
        "user_id": measurement.user_id,
        "record_id": measurement.record_id,
        "precision": measurement.precision,
        "measured_at_utc": (
            measurement.measured_at_utc.isoformat() if measurement.measured_at_utc else None
        ),
        "local_wall_time": measurement.local_wall_time,
        "local_date": measurement.local_date.isoformat() if measurement.local_date else None,
        "metrics": [
            {
                "metric_code": item.metric_code,
                "value": item.value,
                "unit": item.unit,
                "status": item.status,
            }
            for item in measurement.metrics
        ],
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _source_record_id(measurement: NormalizedMeasurement) -> str | None:
    if measurement.record_id is not None:
        return f"{measurement.user_id}:{measurement.record_id}"
    return None


def _session_time(
    measurement: NormalizedMeasurement,
) -> tuple[str, date, datetime | None, datetime | None]:
    if measurement.local_date is None:
        raise OpenScaleIngestError(
            "missing_datetime", "measurement requires a sender date", status_code=400
        )
    if measurement.measured_at_utc is not None:
        return (
            measurement.precision,
            measurement.local_date,
            measurement.measured_at_utc,
            _parse_local_wall(measurement.local_wall_time),
        )
    if measurement.local_wall_time is not None:
        # Schema requires UTC for minute/instant precision.  When the sender
        # supplied a naive wall clock, store that wall time labeled UTC without
        # inventing a different zone offset — zone remains unknown.
        wall = _parse_local_wall(measurement.local_wall_time)
        assert wall is not None
        labeled = wall if wall.tzinfo is not None else wall.replace(tzinfo=UTC)
        precision = "minute"
        if labeled.second != 0 or labeled.microsecond != 0:
            precision = "instant"
        return precision, measurement.local_date, labeled, wall.replace(tzinfo=UTC)
    return "date", measurement.local_date, None, None


def _parse_local_wall(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed


def _session_matches_measurement(
    session: MeasurementSession,
    measurement: NormalizedMeasurement,
    precision: str,
    local_date: date,
    timestamp_utc: datetime | None,
) -> bool:
    if session.source_local_date != local_date:
        return False
    if session.temporal_precision != precision:
        return False
    return restore_stored_utc(session.source_timestamp_utc) == restore_stored_utc(timestamp_utc)


def _scalars_match(
    repos: ProvenanceRepositories,
    session: MeasurementSession,
    usable: tuple[Any, ...],
) -> bool:
    existing = {
        item.metric_code: item for item in repos.scalar_measurements.list_for_session(session.id)
    }
    if len(existing) != len(usable):
        return False
    for metric in usable:
        row = existing.get(metric.metric_code)
        if row is None:
            return False
        if row.normalized_value != float(metric.value) or row.normalized_unit != (
            metric.unit or ""
        ):
            return False
    return True


def _latest_identity_session(
    repos: ProvenanceRepositories,
    acquisition_source_id: str,
    source_record_id: str | None,
    fingerprint: str,
) -> MeasurementSession | None:
    return repos.measurement_sessions.find_by_source_identity(
        acquisition_source_id=acquisition_source_id,
        source_record_id=source_record_id,
        source_fingerprint=fingerprint,
        semantic_key=fingerprint,
    )


def _time_matches_session(session: MeasurementSession, measurement: NormalizedMeasurement) -> bool:
    if measurement.measured_at_utc is not None:
        return restore_stored_utc(session.source_timestamp_utc) == restore_stored_utc(
            measurement.measured_at_utc
        )
    if measurement.local_date is not None and session.source_local_date == measurement.local_date:
        if measurement.local_wall_time is None:
            return session.temporal_precision == "date"
        wall = _parse_local_wall(measurement.local_wall_time)
        if wall is None or session.source_local_timestamp is None:
            return False
        left = session.source_local_timestamp.replace(tzinfo=None)
        return left == wall.replace(tzinfo=None)
    return False


__all__ = ["ItemOutcome", "OpenScaleWebhookService", "WebhookIngestResult"]
