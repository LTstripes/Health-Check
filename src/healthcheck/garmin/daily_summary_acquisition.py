"""One complete provider daily-summary fetch; no historic proof reconstruction."""

from datetime import UTC, date, datetime, time, timedelta
from hashlib import sha256

from sqlalchemy.orm import Session

from healthcheck.db.models import (
    GarminDailySummaryAcquisitionReceipt,
    IngestBatch,
    IngestEvent,
    Provider,
    RawArtifact,
    SyncRun,
)
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.garmin.observed_steps import _calendar_date, _decode
from healthcheck.garmin.persistence import GarminPersistenceOutcome, build_garmin_observation_key

RECEIPT_VERSION = "garmin-daily-summary-acquisition-v1"
ACQUISITION_RUN_KINDS = frozenset({"garmin_incremental", "garmin_historical"})


def acquisition_spine_reason(observation, source, raw, artifact, run, provider, event, batch):
    """Validate the existing immutable spine without assuming a terminal run."""
    if (
        source is None
        or source.provider_code != "garmin_connect"
        or source.source_kind != "provider"
        or provider is None
        or provider.code != "garmin_connect"
        or provider.id != source.provider_id
        or raw is None
        or raw.garmin_source_id != source.id
        or observation.garmin_source_id != source.id
        or raw.stream_code != "daily_health"
        or raw.payload_format != "json"
        or observation.stream_code != "daily_health"
        or observation.payload_format != "json"
        or observation.source_filename != "daily_summary.json"
        or artifact is None
        or raw.raw_artifact_id != artifact.id
        or observation.raw_artifact_id != artifact.id
        or raw.content_hash != artifact.content_hash
    ):
        return "provenance_mismatch"
    if run is None or run.stream_code not in ACQUISITION_RUN_KINDS:
        return "acquisition_run_not_evidenced"
    if run.provider_id != source.provider_id or (
        run.acquisition_source_id is not None
        and run.acquisition_source_id != source.acquisition_source_id
    ):
        return "acquisition_run_mismatch"
    fields = {
        name: getattr(observation, name)
        for name in (
            "garmin_source_id",
            "stream_code",
            "payload_format",
            "source_contract_version",
            "normalization_contract_version",
            "fixture_id",
            "parse_status",
            "record_count",
            "diagnostics_json",
            "unknown_fields_json",
            "source_window_start_utc",
            "source_window_end_utc",
            "sync_run_id",
            "source_filename",
        )
    }
    try:
        for name in ("source_window_start_utc", "source_window_end_utc"):
            fields[name] = restore_stored_utc(fields[name])
        expected_key = build_garmin_observation_key(content_hash=raw.content_hash, **fields)
    except (ValueError, TypeError, OverflowError):
        return "acquisition_identity_mismatch"
    if observation.observation_key != expected_key:
        return "acquisition_identity_mismatch"
    if (
        event is None
        or batch is None
        or event.acquisition_source_id != source.acquisition_source_id
        or event.raw_artifact_id != artifact.id
        or event.provider_stream != "daily_health"
        or event.semantic_fingerprint != f"garmin-observation:{expected_key}"
        or batch.acquisition_source_id != source.acquisition_source_id
        or batch.batch_kind != "provider_sync"
        or batch.parser_name != "garmin-normalization"
        or batch.parser_version != observation.normalization_contract_version
        or event.status != "committed"
        or batch.status != "committed"
        or observation.fixture_id is not None
    ):
        return "acquisition_event_unproven"
    return None


def receipt_reason(receipt, observation, run, original_day):
    """Validate receipt v1 against the already verified immutable observation."""
    if (
        receipt.observation_id != observation.id
        or receipt.contract_version != RECEIPT_VERSION
        or receipt.surface != "daily_summary"
        or receipt.method != "get_user_summary"
        or type(receipt.requested_date) is not date
        or type(receipt.original_calendar_date) is not date
        or receipt.requested_date != receipt.original_calendar_date
        or receipt.original_calendar_date != original_day
    ):
        return "acquisition_receipt_mismatch"
    try:
        start = datetime.combine(receipt.requested_date, time(), UTC)
        end = start + timedelta(days=1)
        observed_start = restore_stored_utc(observation.source_window_start_utc)
        observed_end = restore_stored_utc(observation.source_window_end_utc)
        requested_start = restore_stored_utc(run.requested_start)
        requested_end = restore_stored_utc(run.requested_end)
        if (
            observed_start != start
            or observed_end != end
            or requested_start is None
            or requested_end is None
            or not requested_start <= start < end <= requested_end
        ):
            return "acquisition_receipt_window_mismatch"
    except (ValueError, TypeError, OverflowError):
        return "acquisition_receipt_window_mismatch"
    return None


def record_daily_summary_acquisition(
    session: Session,
    outcome: GarminPersistenceOutcome,
    *,
    original_bytes: bytes,
    requested_date: date | None,
    surface: str,
    method: str,
    fetch_complete: bool,
    request_count: int,
) -> GarminDailySummaryAcquisitionReceipt | None:
    """Mint only inside the real complete-fetch transaction; never commit here.

    Generic persistence/reprocess/projectors do not call this function. A replay
    may validate an existing receipt, but cannot attach proof to an old observation.
    """
    if (
        surface != "daily_summary"
        or method != "get_user_summary"
        or fetch_complete is not True
        or type(request_count) is not int
        or request_count <= 0
        or type(requested_date) is not date
    ):
        return None
    original, _ = _decode(original_bytes)
    original_day = _calendar_date(original) if original is not None else None
    if original_day != requested_date:
        return None
    observation, raw, source = outcome.observation, outcome.raw_payload, outcome.source
    artifact = session.get(RawArtifact, observation.raw_artifact_id)
    run = session.get(SyncRun, observation.sync_run_id) if observation.sync_run_id else None
    provider = session.get(Provider, source.provider_id)
    event = (
        session.get(IngestEvent, observation.ingest_event_id)
        if observation.ingest_event_id
        else None
    )
    batch = session.get(IngestBatch, event.ingest_batch_id) if event else None
    reason = acquisition_spine_reason(
        observation, source, raw, artifact, run, provider, event, batch
    )
    if reason or run.status != "running" or run.completed_at is not None:
        raise ValueError("daily-summary acquisition provenance is not valid")
    if (
        len(original_bytes) != artifact.byte_size
        or sha256(original_bytes).hexdigest() != raw.content_hash
    ):
        raise ValueError("daily-summary original integrity is not valid")
    existing = session.get(GarminDailySummaryAcquisitionReceipt, observation.id)
    if outcome.replayed is not False:
        if outcome.replayed is not True:
            raise ValueError("daily-summary observation insertion is not proven")
        if existing is not None and receipt_reason(existing, observation, run, original_day):
            raise ValueError("daily-summary replay receipt conflicts")
        return existing
    if existing is not None:
        raise ValueError("daily-summary receipt already exists for a new observation")
    receipt = GarminDailySummaryAcquisitionReceipt(
        observation_id=observation.id,
        contract_version=RECEIPT_VERSION,
        surface=surface,
        method=method,
        requested_date=requested_date,
        original_calendar_date=original_day,
    )
    if receipt_reason(receipt, observation, run, original_day):
        raise ValueError("daily-summary acquisition window is not valid")
    session.add(receipt)
    session.flush()
    return receipt
