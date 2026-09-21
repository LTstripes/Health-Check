"""Bounded offline Garmin reprocessing from stored raw evidence.

This command recalculates current collections after normalization/reconciliation
rule changes.  It does not call Garmin, download FIT/GPS, or write incremental
or historical checkpoints.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
from healthcheck.db.models import (
    CoverageInterval,
    GarminPayloadObservation,
    GarminSource,
    GarminSourceRecord,
    RawArtifact,
    SyncStreamState,
)
from healthcheck.db.repositories import repositories_for, restore_stored_utc
from healthcheck.external_runtime_lock import ExternalRuntimeOperationLock
from healthcheck.garmin.capabilities import GARMIN_PROVIDER_CODE
from healthcheck.garmin.normalization import (
    NORMALIZATION_CONTRACT_VERSION,
    GarminSourceIdentity,
    normalize_garmin_payload,
)
from healthcheck.garmin.persistence import (
    PROJECTION_CURRENT,
    RECONCILIATION_CONTRACT_VERSION,
    GarminPersistenceRepository,
)
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.garmin.sync import (
    ACTIVITY_PAGE_SIZE,
    DEFAULT_TRAILING_WINDOW_DAYS,
    PRODUCTION_SYNC_SURFACES,
    GarminSyncSurface,
    _calendar_days,
    _collection_scope,
    _coverage_status_for,
    _day_bounds,
    _normalize_provider_payload,
    _prepare_normalization_result,
    validate_sync_date,
)
from healthcheck.logging import log_event
from healthcheck.runtime import prepare_runtime

REPROCESS_CONTRACT_VERSION = "r02-garmin-collection-reprocess-v1"
REPROCESS_RUN_STREAM = "garmin_reprocess"
MAX_REPROCESS_OBSERVATIONS = 140
MAX_REPROCESS_SPAN_DAYS = 3660
_SURFACE_BY_CODE = {item.code: item for item in PRODUCTION_SYNC_SURFACES}
_SURFACE_BY_FILENAME = {f"{item.code}.json": item for item in PRODUCTION_SYNC_SURFACES}


@dataclass(frozen=True, slots=True)
class GarminHistoryGap:
    """One local day/surface without complete coverage, especially outside the trailing window."""

    surface: str
    stream: str
    day: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "surface": self.surface,
            "stream": self.stream,
            "day": self.day,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class GarminReprocessReport:
    """Sanitized machine-readable reprocess summary."""

    status: str
    start: str
    end: str
    streams: tuple[str, ...]
    dry_run: bool
    observation_count: int
    processed_count: int
    skipped_current_version_count: int
    inserted_count: int
    updated_count: int
    retired_count: int
    remaining_observation_count: int
    abort_reason: str | None = None
    sync_run_id: str | None = None
    history_gaps: tuple[GarminHistoryGap, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": REPROCESS_CONTRACT_VERSION,
            "reconciliation_contract_version": RECONCILIATION_CONTRACT_VERSION,
            "normalization_contract_version": NORMALIZATION_CONTRACT_VERSION,
            "reprocess": {
                "status": self.status,
                "start": self.start,
                "end": self.end,
                "streams": list(self.streams),
                "dry_run": self.dry_run,
                "observation_count": self.observation_count,
                "processed_count": self.processed_count,
                "skipped_current_version_count": self.skipped_current_version_count,
                "inserted_count": self.inserted_count,
                "updated_count": self.updated_count,
                "retired_count": self.retired_count,
                "remaining_observation_count": self.remaining_observation_count,
                "max_observations": MAX_REPROCESS_OBSERVATIONS,
                "sync_run_id": self.sync_run_id,
                "abort_reason": self.abort_reason,
                "provider_requests": 0,
                "historical_checkpoint_namespace_unchanged": True,
                "incremental_checkpoint_namespace_unchanged": True,
                "gps_or_fit_downloaded": False,
            },
            "privacy": {
                "raw_values_emitted": False,
                "private_identifiers_emitted": False,
                "tokens_emitted": False,
                "health_timestamps_emitted": False,
            },
            "history_gaps": [item.as_dict() for item in self.history_gaps],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def validate_reprocess_range(start: date | str | None, end: date | str | None) -> tuple[date, date]:
    if start is None or end is None:
        raise ValueError("garmin-reprocess requires explicit --start and --end")
    start_date = validate_sync_date(start)
    end_date = validate_sync_date(end)
    if end_date < start_date:
        raise ValueError("garmin-reprocess end must not precede start")
    span_days = (end_date - start_date).days + 1
    if span_days > MAX_REPROCESS_SPAN_DAYS:
        raise ValueError(
            f"garmin-reprocess span must be at most {MAX_REPROCESS_SPAN_DAYS} days"
        )
    return start_date, end_date


def validate_reprocess_streams(values: Sequence[str] | None) -> tuple[GarminSyncSurface, ...]:
    if not values:
        return PRODUCTION_SYNC_SURFACES
    selected: list[GarminSyncSurface] = []
    seen: set[str] = set()
    for raw in values:
        code = raw.strip()
        if not code:
            raise ValueError("garmin-reprocess stream must be a non-empty code")
        surface = _SURFACE_BY_CODE.get(code)
        if surface is None:
            raise ValueError("garmin-reprocess stream is not an accepted production surface")
        if code not in seen:
            selected.append(surface)
            seen.add(code)
    if not selected:
        raise ValueError("garmin-reprocess requires at least one stream")
    return tuple(selected)


def validate_reprocess_max_observations(value: int | None) -> int:
    cap = MAX_REPROCESS_OBSERVATIONS if value is None else value
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        raise ValueError("max_observations must be a positive integer")
    if cap > MAX_REPROCESS_OBSERVATIONS:
        raise ValueError("max_observations exceeds the hard reprocess cap")
    return cap


class GarminCollectionReprocessor:
    """Re-normalize stored Garmin payloads for an explicit bounded window."""

    def __init__(
        self,
        settings: Settings,
        *,
        clock: Callable[[], datetime] | None = None,
        max_observations: int = MAX_REPROCESS_OBSERVATIONS,
    ) -> None:
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(UTC))
        self.max_observations = validate_reprocess_max_observations(max_observations)

    def run(
        self,
        *,
        start: date | str | None,
        end: date | str | None,
        streams: Sequence[str] | None = None,
        dry_run: bool = False,
        max_observations: int | None = None,
    ) -> GarminReprocessReport:
        start_date, end_date = validate_reprocess_range(start, end)
        surfaces = validate_reprocess_streams(streams)
        cap = validate_reprocess_max_observations(
            self.max_observations if max_observations is None else max_observations
        )
        paths = prepare_runtime(self.settings)
        with ExternalRuntimeOperationLock(paths):
            migrate_database(paths)
            engine = create_sqlite_engine(paths)
            store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            factory = create_session_factory(engine)
            try:
                return self._run(
                    factory,
                    store,
                    start=start_date,
                    end=end_date,
                    surfaces=surfaces,
                    dry_run=dry_run,
                    cap=cap,
                )
            finally:
                engine.dispose()

    def _run(
        self,
        factory,
        store: ContentAddressedGarminPayloadStore,
        *,
        start: date,
        end: date,
        surfaces: tuple[GarminSyncSurface, ...],
        dry_run: bool,
        cap: int,
    ) -> GarminReprocessReport:
        window_start_utc, _ = _day_bounds(start)
        _, window_end_utc = _day_bounds(end)
        stream_codes = {item.stream.value for item in surfaces}
        filenames = {f"{item.code}.json" for item in surfaces}
        with factory() as session:
            observations = list(
                session.scalars(
                    select(GarminPayloadObservation)
                    .where(
                        GarminPayloadObservation.stream_code.in_(stream_codes),
                        GarminPayloadObservation.source_window_start_utc.is_not(None),
                        GarminPayloadObservation.source_window_end_utc.is_not(None),
                        GarminPayloadObservation.source_window_start_utc < window_end_utc,
                        GarminPayloadObservation.source_window_end_utc > window_start_utc,
                    )
                    .order_by(
                        GarminPayloadObservation.received_at,
                        GarminPayloadObservation.id,
                    )
                )
            )
            selected: list[GarminPayloadObservation] = []
            for observation in observations:
                if observation.source_filename not in filenames:
                    continue
                selected.append(observation)
            candidates, superseded = _latest_observations_per_window(selected)
            history_gaps = tuple(
                _history_gaps(session, start=start, end=end, surfaces=surfaces)
            )

        eligible: list[GarminPayloadObservation] = []
        skipped_current = 0
        for observation in candidates:
            if _window_already_current(
                factory, observation, request_start=start, request_end=end
            ):
                skipped_current += 1
            else:
                eligible.append(observation)
        eligible.sort(key=_observation_sort_key)
        remaining = max(0, len(eligible) - cap)
        bounded = eligible[:cap]
        if dry_run:
            skipped = superseded + skipped_current
            return GarminReprocessReport(
                status="planned",
                start=start.isoformat(),
                end=end.isoformat(),
                streams=tuple(item.code for item in surfaces),
                dry_run=True,
                observation_count=len(selected),
                processed_count=0,
                skipped_current_version_count=skipped,
                inserted_count=0,
                updated_count=0,
                retired_count=0,
                remaining_observation_count=remaining,
                abort_reason="observation_budget_exhausted" if remaining else None,
                history_gaps=history_gaps,
            )

        with factory() as session:
            provider = repositories_for(session).providers.get_or_create(
                GARMIN_PROVIDER_CODE,
                "Garmin Connect",
                "wearable",
            )
            run = repositories_for(session).sync.create_run(
                provider_id=provider.id,
                stream_code=REPROCESS_RUN_STREAM,
                requested_start=window_start_utc,
                requested_end=window_end_utc,
            )
            session.commit()
            sync_run_id = run.id

        processed = 0
        skipped = superseded + skipped_current
        inserted = 0
        updated = 0
        retired = 0
        abort_reason = "observation_budget_exhausted" if remaining else None
        for observation in bounded:
            outcome = self._reprocess_observation(
                factory,
                store,
                observation,
                sync_run_id=sync_run_id,
                request_start=start,
                request_end=end,
            )
            if outcome is None:
                continue
            processed += 1
            inserted += outcome.inserted_count
            updated += outcome.updated_count
            retired += outcome.retired_count

        with factory() as session:
            repositories_for(session).sync.finish_run(
                sync_run_id,
                status="partial" if abort_reason else "succeeded",
                item_count=processed,
                received_count=processed,
                accepted_count=processed,
                failed_count=0,
                error_category=abort_reason,
                diagnostic_reason=abort_reason,
                actual_start=window_start_utc,
                actual_end=window_end_utc,
            )
            session.commit()

        log_event(
            "garmin_collection_reprocess",
            operation="garmin-reprocess",
            status="partial" if abort_reason else "succeeded",
            count=processed,
            reason=abort_reason or "succeeded",
        )
        return GarminReprocessReport(
            status="partial" if abort_reason else "succeeded",
            start=start.isoformat(),
            end=end.isoformat(),
            streams=tuple(item.code for item in surfaces),
            dry_run=False,
            observation_count=len(selected),
            processed_count=processed,
            skipped_current_version_count=skipped,
            inserted_count=inserted,
            updated_count=updated,
            retired_count=retired,
            remaining_observation_count=remaining,
            abort_reason=abort_reason,
            sync_run_id=sync_run_id,
            history_gaps=history_gaps,
        )

    def _reprocess_observation(
        self,
        factory,
        store: ContentAddressedGarminPayloadStore,
        observation: GarminPayloadObservation,
        *,
        sync_run_id: str,
        request_start: date,
        request_end: date,
    ) -> Any:
        surface = _SURFACE_BY_FILENAME.get(observation.source_filename or "")
        if surface is None:
            return None
        window_start = restore_stored_utc(observation.source_window_start_utc)
        window_end = restore_stored_utc(observation.source_window_end_utc)
        if window_start is None or window_end is None:
            return None
        received_at = restore_stored_utc(observation.received_at) or self.clock()
        with factory() as session:
            artifact = session.get(RawArtifact, observation.raw_artifact_id)
            source = session.get(GarminSource, observation.garmin_source_id)
            if artifact is None:
                raise RuntimeError("Garmin observation references a missing raw artifact")
            if source is None:
                raise RuntimeError("Garmin observation references a missing source")
            raw_bytes = store.read(artifact.relative_storage_path)
            identity = GarminSourceIdentity(
                source_kind=source.source_kind,
                provider_code=source.provider_code,
                device_attributed=source.device_attributed,
                device_code=source.device_code,
                device_model=source.device_model,
                source_instance_id=source.source_instance_id,
            )
        payload = json.loads(raw_bytes.decode("utf-8"))
        obs_start = window_start.date()
        obs_end = (window_end - timedelta(microseconds=1)).date()
        scope_start = max(obs_start, request_start)
        scope_end = min(obs_end, request_end)
        if scope_start > scope_end:
            return None
        clipped = (scope_start, scope_end) != (obs_start, obs_end)
        day = None if not surface.per_day else scope_start
        normalized_payload = _normalize_provider_payload(surface, payload, day=day)
        result = normalize_garmin_payload(
            normalized_payload,
            stream=surface.stream,
            source_identity=identity,
        )
        result = _prepare_normalization_result(surface, payload, result, day=day)
        result = _filter_result_to_range(result, scope_start, scope_end, clipped=clipped)
        coverage_status = _coverage_status_for(surface, result, payload, day=day)
        fetch_complete = _reconstruct_fetch_complete(surface, payload) and not clipped
        with factory() as session:
            persistence = GarminPersistenceRepository(session, payload_store=store)
            outcome = persistence.persist_result(
                result,
                payload=raw_bytes,
                stream_code=surface.stream,
                source_identity=identity,
                received_at=received_at,
                source_window_start_utc=window_start,
                source_window_end_utc=window_end,
                sync_run_id=sync_run_id,
                source_filename=observation.source_filename,
                collection_scope=_collection_scope(
                    surface,
                    day=day,
                    window_start=scope_start,
                    window_end=scope_end,
                    fetch_complete=fetch_complete,
                    coverage_status=coverage_status,
                ),
                allow_per_row_stale_reconciliation=True,
            )
            session.commit()
            return outcome


def _observation_window_key(observation: GarminPayloadObservation) -> tuple[str, str, str, str]:
    start = restore_stored_utc(observation.source_window_start_utc)
    end = restore_stored_utc(observation.source_window_end_utc)
    start_text = start.isoformat() if start is not None else ""
    end_text = end.isoformat() if end is not None else ""
    return (
        observation.garmin_source_id,
        observation.source_filename or "",
        start_text,
        end_text,
    )


def _latest_observations_per_window(
    observations: Sequence[GarminPayloadObservation],
) -> tuple[list[GarminPayloadObservation], int]:
    """Keep only the newest observation in each source/surface/window.

    Older observations in the same window are provenance, not reprocess inputs.
    Applying them first would stamp current versions and skip a later correction.
    """

    latest: dict[tuple[str, str, str, str], GarminPayloadObservation] = {}
    for observation in observations:
        key = _observation_window_key(observation)
        current = latest.get(key)
        if current is None or _observation_is_newer(observation, current):
            latest[key] = observation
    candidates = sorted(latest.values(), key=_observation_sort_key, reverse=True)
    return candidates, max(0, len(observations) - len(candidates))


def _observation_sort_key(observation: GarminPayloadObservation) -> tuple[datetime, str]:
    return (
        restore_stored_utc(observation.received_at) or datetime.min.replace(tzinfo=UTC),
        observation.id,
    )


def _observation_is_newer(
    candidate: GarminPayloadObservation, current: GarminPayloadObservation
) -> bool:
    candidate_at = restore_stored_utc(candidate.received_at)
    current_at = restore_stored_utc(current.received_at)
    if candidate_at != current_at:
        if candidate_at is None:
            return False
        if current_at is None:
            return True
        return candidate_at > current_at
    return candidate.id > current.id


def _reconstruct_fetch_complete(surface: GarminSyncSurface, payload: Any) -> bool:
    """Rebuild original collection completeness, fail-closed when unprovable.

    Per-day surfaces are single-request fetches. Activity lists are complete only
    when the reconstructed last page is short or the collection is empty. A full
    last page may be truncated pagination or a budget stop, so it is not
    authoritative enough to retire absent members.
    """

    if surface.code != "activities":
        return True
    items = _activity_items(payload)
    if items is None:
        return False
    if not items:
        return True
    return len(items) % ACTIVITY_PAGE_SIZE != 0


def _filter_result_to_range(result: Any, start: date, end: date, *, clipped: bool) -> Any:
    """Keep only current-projection members inside the requested local-date span."""

    kept = []
    for record in result.records:
        local = record.temporal.local_date
        if local is None and record.temporal.measured_at_utc is not None:
            local = record.temporal.measured_at_utc.date()
        if local is None:
            if clipped:
                continue
            kept.append(record)
            continue
        if start <= local <= end:
            kept.append(record)
    if len(kept) == len(result.records):
        return result
    return replace(result, records=tuple(kept))


def _activity_items(payload: Any) -> list[Any] | None:
    if isinstance(payload, Sequence) and not isinstance(
        payload, (str, bytes, bytearray, Mapping)
    ):
        return list(payload)
    if isinstance(payload, Mapping):
        raw = payload.get("activities")
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray, Mapping)):
            return list(raw)
        return None
    return None


def _window_already_current(
    factory,
    observation: GarminPayloadObservation,
    *,
    request_start: date,
    request_end: date,
) -> bool:
    window_start = restore_stored_utc(observation.source_window_start_utc)
    window_end = restore_stored_utc(observation.source_window_end_utc)
    if window_start is None or window_end is None:
        return False
    local_start = max(window_start.date(), request_start)
    local_end = min((window_end - timedelta(microseconds=1)).date(), request_end)
    if local_start > local_end:
        return True
    surface = _SURFACE_BY_FILENAME.get(observation.source_filename or "")
    if surface is None:
        return False
    with factory() as session:
        rows = list(
            session.scalars(
                select(GarminSourceRecord).where(
                    GarminSourceRecord.garmin_source_id == observation.garmin_source_id,
                    GarminSourceRecord.surface_code == surface.code,
                    GarminSourceRecord.projection_status == PROJECTION_CURRENT,
                    GarminSourceRecord.source_local_date >= local_start,
                    GarminSourceRecord.source_local_date <= local_end,
                )
            )
        )
        if rows:
            observed_at = restore_stored_utc(observation.received_at)
            for row in rows:
                projected = restore_stored_utc(row.projection_observed_at) or restore_stored_utc(
                    row.last_seen_at
                )
                if (
                    observed_at is not None
                    and projected is not None
                    and observed_at < projected
                ):
                    continue
                version_current = (
                    row.reconciliation_contract_version == RECONCILIATION_CONTRACT_VERSION
                    and row.normalization_contract_version == NORMALIZATION_CONTRACT_VERSION
                )
                if not version_current:
                    return False
                if observed_at is not None and (projected is None or observed_at > projected):
                    return False
            return True
        siblings = [
            item
            for item in session.scalars(
                select(GarminPayloadObservation).where(
                    GarminPayloadObservation.garmin_source_id == observation.garmin_source_id,
                    GarminPayloadObservation.source_filename == observation.source_filename,
                )
            )
            if _observation_window_key(item) == _observation_window_key(observation)
        ]
        if not siblings:
            return False
        latest = siblings[0]
        for item in siblings[1:]:
            if _observation_is_newer(item, latest):
                latest = item
        return (
            latest.reconciliation_contract_version == RECONCILIATION_CONTRACT_VERSION
            and latest.normalization_contract_version == NORMALIZATION_CONTRACT_VERSION
        )


def _history_gaps(
    session,
    *,
    start: date,
    end: date,
    surfaces: Sequence[GarminSyncSurface],
) -> list[GarminHistoryGap]:
    days = _calendar_days(start, end)
    trailing_start = end - timedelta(days=DEFAULT_TRAILING_WINDOW_DAYS - 1)
    gaps: list[GarminHistoryGap] = []
    coverage_rows = list(session.scalars(select(CoverageInterval)))
    covered: set[tuple[str, str]] = set()
    for row in coverage_rows:
        if row.status not in {"present", "confirmed_empty"} or row.resolution != "day":
            continue
        interval_start = restore_stored_utc(row.interval_start)
        interval_end = restore_stored_utc(row.interval_end)
        if interval_start is None or interval_end is None:
            continue
        if interval_end <= interval_start + timedelta(days=1):
            covered.add((row.metric_code, interval_start.date().isoformat()))
    watermark_end: date | None = None
    incremental_states = list(
        session.scalars(
            select(SyncStreamState).where(~SyncStreamState.stream_code.like("garmin_historical:%"))
        )
    )
    for state in incremental_states:
        stamp = restore_stored_utc(state.watermark) or restore_stored_utc(state.last_success_at)
        if stamp is None:
            continue
        stamp_day = stamp.date()
        if watermark_end is None or stamp_day > watermark_end:
            watermark_end = stamp_day
    trailing_end = watermark_end or end
    trailing_start = trailing_end - timedelta(days=DEFAULT_TRAILING_WINDOW_DAYS - 1)
    for surface in surfaces:
        for day in days:
            key = (surface.code, day.isoformat())
            if key in covered:
                continue
            if trailing_start <= day <= trailing_end:
                reason = "inside_trailing_window_no_coverage"
            else:
                reason = "outside_trailing_window_no_coverage"
            gaps.append(
                GarminHistoryGap(
                    surface=surface.code,
                    stream=surface.stream.value,
                    day=day.isoformat(),
                    reason=reason,
                )
            )
    return gaps


def run_garmin_reprocess(
    settings: Settings,
    *,
    start: date | str | None = None,
    end: date | str | None = None,
    streams: Sequence[str] | None = None,
    dry_run: bool = False,
    max_observations: int | None = None,
    clock: Callable[[], datetime] | None = None,
) -> GarminReprocessReport:
    """Re-normalize stored Garmin payloads for one explicit bounded range."""

    return GarminCollectionReprocessor(
        settings,
        clock=clock,
        max_observations=max_observations or MAX_REPROCESS_OBSERVATIONS,
    ).run(
        start=start,
        end=end,
        streams=streams,
        dry_run=dry_run,
        max_observations=max_observations,
    )


__all__ = [
    "MAX_REPROCESS_OBSERVATIONS",
    "MAX_REPROCESS_SPAN_DAYS",
    "REPROCESS_CONTRACT_VERSION",
    "REPROCESS_RUN_STREAM",
    "GarminCollectionReprocessor",
    "GarminHistoryGap",
    "GarminReprocessReport",
    "run_garmin_reprocess",
    "validate_reprocess_max_observations",
    "validate_reprocess_range",
    "validate_reprocess_streams",
]
