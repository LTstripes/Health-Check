"""Bounded read-only normalization preview, distinct from reprocess --dry-run.

Call with an existing read-only Session and explicit saved observation IDs.
Nothing here prepares a runtime, migrates, persists, or contacts providers.
Candidates describe production-prepared DTOs, not stored v6-eligible nights.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    GarminPayloadObservation,
    GarminRawPayload,
    GarminSource,
    GarminSourceRecord,
    RawArtifact,
)
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.garmin.normalization import GarminSourceIdentity, normalize_garmin_payload
from healthcheck.garmin.persistence import PROJECTION_CURRENT
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.garmin.sync import (
    PRODUCTION_SYNC_SURFACES,
    _normalize_provider_payload,
    _prepare_normalization_result,
)
from healthcheck.web.read_snapshot import ensure_read_snapshot

PREVIEW_VERSION = "saved-garmin-sleep-normalization-preview-v1"
MAX_PREVIEW_OBSERVATIONS = 30
MAX_PREVIEW_BYTES = 1024 * 1024
SLEEP_SURFACE = next(s for s in PRODUCTION_SYNC_SURFACES if s.code == "sleep")


def preview_saved_garmin_sleep(
    session: Session, *, payload_store: ContentAddressedGarminPayloadStore,
    source_id: str, observation_ids: Sequence[str], start_date: date, end_date: date,
) -> dict:
    """Inspect explicit originals under one snapshot; never apply a replacement.

    Bounds: 30 selected observations, 30 inclusive dates, one MiB per original,
    one production sleep record per original, two current identity matches.
    An excess or ambiguous input fails closed instead of returning a prefix.
    """
    if (type(start_date) is not date or type(end_date) is not date
            or not 1 <= (end_date - start_date).days + 1 <= 30):
        raise ValueError("preview_date_range_out_of_bounds")
    if (isinstance(observation_ids, (str, bytes)) or not observation_ids
            or len(observation_ids) > MAX_PREVIEW_OBSERVATIONS
            or any(not isinstance(i, str) or not i for i in observation_ids)
            or len(set(observation_ids)) != len(observation_ids)):
        raise ValueError("preview_observation_selection_out_of_bounds")
    ensure_read_snapshot(session)
    source = session.get(GarminSource, source_id)
    if source is None:
        raise ValueError("preview_source_unavailable")
    identity = GarminSourceIdentity(
        source_kind=source.source_kind, provider_code=source.provider_code,
        device_attributed=source.device_attributed, device_code=source.device_code,
        device_model=source.device_model, source_instance_id=source.source_instance_id,
    )
    rows = []
    for observation_id in observation_ids:
        observation = session.get(GarminPayloadObservation, observation_id)
        if (observation is None or observation.garmin_source_id != source_id
                or observation.stream_code != "sleep"
                or observation.source_filename != f"{SLEEP_SURFACE.code}.json"):
            raise ValueError("preview_observation_not_selected_sleep_source")
        window_start = restore_stored_utc(observation.source_window_start_utc)
        window_end = restore_stored_utc(observation.source_window_end_utc)
        if (window_start is None or window_end is None or window_end <= window_start
                or window_start.date() < start_date or window_start.date() > end_date
                or (window_end - window_start).total_seconds() != 86400):
            raise ValueError("preview_requires_selected_single_day_window")
        raw = session.get(GarminRawPayload, observation.garmin_raw_payload_id)
        artifact = session.get(RawArtifact, observation.raw_artifact_id)
        if (raw is None or artifact is None or raw.garmin_source_id != source_id
                or raw.raw_artifact_id != artifact.id or raw.stream_code != "sleep"
                or raw.payload_format != "json" or observation.payload_format != "json"
                or not 0 <= artifact.byte_size <= MAX_PREVIEW_BYTES):
            raise ValueError("preview_original_evidence_unavailable")
        content = payload_store.read(artifact.relative_storage_path, max_bytes=MAX_PREVIEW_BYTES)
        digest = hashlib.sha256(content).hexdigest()
        if (len(content) != artifact.byte_size
                or digest != raw.content_hash or digest != artifact.content_hash):
            raise ValueError("preview_original_hash_mismatch")
        payload = json.loads(content)
        normalized_payload = _normalize_provider_payload(SLEEP_SURFACE, payload,
            day=window_start.date())
        result = normalize_garmin_payload(normalized_payload, stream="sleep",
            source_identity=identity)
        result = _prepare_normalization_result(SLEEP_SURFACE, payload, result,
            day=window_start.date())
        if len(result.records) > 1:
            raise ValueError("preview_sleep_record_cap_exceeded")
        latest = session.scalar(select(GarminPayloadObservation.id).where(
            GarminPayloadObservation.garmin_source_id == source_id,
            GarminPayloadObservation.source_filename == observation.source_filename,
            GarminPayloadObservation.source_window_start_utc == observation.source_window_start_utc,
            GarminPayloadObservation.source_window_end_utc == observation.source_window_end_utc,
        ).order_by(GarminPayloadObservation.received_at.desc(),
                   GarminPayloadObservation.id.desc()).limit(1))
        candidates = []
        for record in result.records:
            current = list(session.scalars(select(GarminSourceRecord).where(
                GarminSourceRecord.garmin_source_id == source_id,
                GarminSourceRecord.surface_code == "sleep",
                GarminSourceRecord.idempotency_key == record.idempotency_key,
                GarminSourceRecord.projection_status == PROJECTION_CURRENT,
            ).limit(2)))
            if len(current) > 1:
                raise ValueError("preview_current_identity_ambiguous")
            existing = current[0] if current else None
            projected = (restore_stored_utc(existing.projection_observed_at)
                         or restore_stored_utc(existing.last_seen_at)) if existing else None
            received = restore_stored_utc(observation.received_at)
            stale = bool(projected and received and received < projected)
            stages = record.metric("sleep_stages")
            complete = bool(stages and stages.state == "value" and stages.reason is None
                            and stages.collection)
            in_range = (record.temporal.local_date is not None
                        and start_date <= record.temporal.local_date <= end_date)
            blockers = []
            if not in_range:
                blockers.append("explicit_date_unavailable_or_out_of_range")
            if stale:
                blockers.append("older_than_current_projection")
            if latest != observation.id:
                blockers.append("not_newest_window_observation")
            if existing is None:
                blockers.append("current_identity_unresolved")
            if result.status == "invalid" or record.status == "invalid":
                blockers.append("invalid_normalization")
            candidates.append({
                "production_prepared_identity": record.idempotency_key,
                "current_record_id": existing.id if existing else None,
                "identity_transition": "preserved" if existing else "new_or_unresolved",
                "current_normalization_version": existing.normalization_contract_version
                    if existing else None,
                "start_instant_available": record.temporal.measured_at_utc is not None,
                "start_fixed_offset_available": (
                    record.temporal.source_utc_offset_minutes is not None
                ),
                "end_method": "complete_stage_boundary",
                "complete_stage_boundary_available": complete,
                "end_fixed_offset_available": bool(complete and
                    stages.collection[-1].end.source_utc_offset_minutes is not None),
                "explicit_date_in_range": in_range,
                "older_than_current_projection": stale,
                "newest_selected_window_observation": latest == observation.id,
                "replacement_candidate": not blockers,
                "replacement_blockers": blockers,
                "stored_v6_eligibility": "unchanged_not_recomputed",
            })
        rows.append({"observation_id": observation.id, "raw_payload_id": raw.id,
            "raw_artifact_id": artifact.id, "original_hash_verified": True,
            "normalization_version": result.contract_version,
            "diagnostic_codes": sorted({d.code for d in result.diagnostics}),
            "candidates": candidates})
    return {"version": PREVIEW_VERSION, "snapshot": "one_sqlite_read_transaction",
        "mode": "hypothetical_normalization_only", "writes_performed": False,
        "source_id": source_id, "observations": rows}
