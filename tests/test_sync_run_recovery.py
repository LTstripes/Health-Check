"""Synthetic coverage for race-free stale SyncRun recovery."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from healthcheck import cli
from healthcheck.config import Settings
from healthcheck.db.engine import (
    create_session_factory,
    create_sqlite_engine,
    migrate_database,
)
from healthcheck.db.models import (
    AcquisitionSource,
    CoverageInterval,
    RawArtifact,
    SyncRun,
    SyncStreamState,
)
from healthcheck.db.repositories import (
    SYNC_RUN_RECOVERY_DIAGNOSTIC_REASON,
    SYNC_RUN_RECOVERY_ERROR_CATEGORY,
    repositories_for,
    restore_stored_utc,
)
from healthcheck.external_runtime_lock import (
    ExternalRuntimeOperationBusyError,
    ExternalRuntimeOperationLock,
)
from healthcheck.garmin.auth import GarminAuthResult, GarminAuthStatus
from healthcheck.garmin.sync import GarminIncrementalSync
from healthcheck.google.auth import GoogleAuthResult, GoogleAuthStatus
from healthcheck.google.sync import GoogleHealthSync, GoogleRunKind
from healthcheck.owner_refresh import OwnerRefreshLock
from healthcheck.runtime import prepare_runtime
from healthcheck.sync_run_recovery import recover_stale_sync_runs

STALE_GARMIN_ID = "synthetic-private-garmin-run"
STALE_GOOGLE_ID = "synthetic-private-google-run"
RECENT_RUN_ID = "synthetic-private-recent-run"


def _runtime(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    return settings, paths


def _seed_running_rows(settings: Settings) -> dict[str, object]:
    paths = prepare_runtime(settings)
    engine = create_sqlite_engine(paths)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            repositories = repositories_for(session)
            garmin = repositories.providers.get_or_create("garmin", "Garmin", "wearable")
            google = repositories.providers.get_or_create("google", "Google", "health_api")
            source = repositories.acquisition_sources.get_or_create(
                provider_id=garmin.id,
                input_method="provider_api",
                source_application="synthetic-test",
            )
            stale_garmin = repositories.sync.create_run(
                provider_id=garmin.id,
                acquisition_source_id=source.id,
                stream_code="garmin_incremental",
                requested_start=datetime(2025, 12, 1, tzinfo=UTC),
                requested_end=datetime(2025, 12, 2, tzinfo=UTC),
            )
            stale_garmin.id = STALE_GARMIN_ID
            stale_garmin.started_at = datetime(2026, 1, 1, tzinfo=UTC)
            stale_garmin.actual_start = datetime(2025, 12, 1, 1, tzinfo=UTC)
            stale_garmin.actual_end = datetime(2025, 12, 1, 2, tzinfo=UTC)
            stale_garmin.item_count = 9
            stale_garmin.received_count = 8
            stale_garmin.accepted_count = 7
            stale_garmin.failed_count = 1

            stale_google = repositories.sync.create_run(
                provider_id=google.id,
                stream_code="google_historical",
                requested_start=datetime(2025, 11, 1, tzinfo=UTC),
                requested_end=datetime(2025, 11, 3, tzinfo=UTC),
            )
            stale_google.id = STALE_GOOGLE_ID
            stale_google.started_at = datetime(2026, 1, 2, tzinfo=UTC)
            stale_google.item_count = 4
            stale_google.received_count = 3
            stale_google.accepted_count = 2
            stale_google.failed_count = 1

            recent = repositories.sync.create_run(
                provider_id=garmin.id,
                stream_code="garmin_incremental",
            )
            recent.id = RECENT_RUN_ID
            recent.started_at = datetime(2026, 2, 1, tzinfo=UTC)

            repositories.sync.get_or_create_state(
                provider_id=garmin.id,
                acquisition_source_id=source.id,
                stream_code="garmin:daily",
                cursor="synthetic-cursor",
                watermark=datetime(2025, 12, 1, tzinfo=UTC),
                trailing_window_days=7,
                diagnostic_status="present",
                last_success_at=datetime(2025, 12, 2, tzinfo=UTC),
                last_attempt_at=datetime(2025, 12, 3, tzinfo=UTC),
            )
            session.add(
                CoverageInterval(
                    provider_id=garmin.id,
                    acquisition_source_id=source.id,
                    stream_code="daily",
                    metric_code="coverage",
                    interval_start=datetime(2025, 12, 1, tzinfo=UTC),
                    interval_end=datetime(2025, 12, 2, tzinfo=UTC),
                    resolution="day",
                    status="present",
                    observed_count=7,
                    expected_count=7,
                    calculation_rule_version="synthetic-v1",
                    diagnostic_reason="synthetic",
                )
            )
            session.add(
                RawArtifact(
                    content_hash="a" * 64,
                    kind="provider_payload",
                    media_type="application/json",
                    byte_size=17,
                    relative_storage_path="payloads/synthetic.json",
                    source_filename="synthetic.json",
                )
            )
            session.commit()
            return {
                "provider_ids": (garmin.id, google.id),
                "source_id": source.id,
            }
    finally:
        engine.dispose()


def _run_snapshot(settings: Settings, run_id: str) -> dict[str, object]:
    paths = prepare_runtime(settings)
    engine = create_sqlite_engine(paths)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            run = session.get(SyncRun, run_id)
            assert run is not None
            return {
                "provider_id": run.provider_id,
                "acquisition_source_id": run.acquisition_source_id,
                "stream_code": run.stream_code,
                "requested_start": restore_stored_utc(run.requested_start),
                "requested_end": restore_stored_utc(run.requested_end),
                "actual_start": restore_stored_utc(run.actual_start),
                "actual_end": restore_stored_utc(run.actual_end),
                "item_count": run.item_count,
                "received_count": run.received_count,
                "accepted_count": run.accepted_count,
                "failed_count": run.failed_count,
                "started_at": restore_stored_utc(run.started_at),
                "status": run.status,
                "completed_at": restore_stored_utc(run.completed_at),
                "error_category": run.error_category,
                "diagnostic_reason": run.diagnostic_reason,
            }
    finally:
        engine.dispose()


def _evidence_snapshot(settings: Settings) -> dict[str, object]:
    paths = prepare_runtime(settings)
    engine = create_sqlite_engine(paths)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            state = session.scalar(select(SyncStreamState))
            coverage = session.scalar(select(CoverageInterval))
            assert state is not None
            assert coverage is not None
            return {
                "source_count": session.scalar(select(func.count(AcquisitionSource.id))),
                "artifact_count": session.scalar(select(func.count(RawArtifact.id))),
                "coverage_count": session.scalar(select(func.count(CoverageInterval.id))),
                "state_count": session.scalar(select(func.count(SyncStreamState.id))),
                "state": (
                    state.provider_id,
                    state.acquisition_source_id,
                    state.stream_code,
                    state.cursor,
                    restore_stored_utc(state.watermark),
                    restore_stored_utc(state.last_success_at),
                    restore_stored_utc(state.last_attempt_at),
                    state.trailing_window_days,
                    state.diagnostic_status,
                ),
                "coverage": (
                    coverage.provider_id,
                    coverage.acquisition_source_id,
                    coverage.stream_code,
                    coverage.metric_code,
                    coverage.status,
                    coverage.observed_count,
                    coverage.expected_count,
                    coverage.calculation_rule_version,
                    coverage.diagnostic_reason,
                ),
            }
    finally:
        engine.dispose()


def test_recovery_is_dry_run_first_terminal_failed_and_idempotent(tmp_path: Path) -> None:
    settings, _paths = _runtime(tmp_path)
    _seed_running_rows(settings)
    before_garmin = _run_snapshot(settings, STALE_GARMIN_ID)
    before_google = _run_snapshot(settings, STALE_GOOGLE_ID)
    before_recent = _run_snapshot(settings, RECENT_RUN_ID)
    before_evidence = _evidence_snapshot(settings)
    cutoff = datetime(2026, 1, 15, tzinfo=UTC)
    completed_at = datetime(2026, 3, 1, tzinfo=UTC)

    dry_run = recover_stale_sync_runs(settings, cutoff=cutoff, apply=False)
    assert dry_run.running_count == 3
    assert dry_run.eligible_stale_count == 2
    assert dry_run.recovered_count == 0
    assert dry_run.remaining_running_count == 3
    assert _run_snapshot(settings, STALE_GARMIN_ID) == before_garmin
    assert _run_snapshot(settings, STALE_GOOGLE_ID) == before_google

    applied = recover_stale_sync_runs(
        settings,
        cutoff=cutoff,
        apply=True,
        clock=lambda: completed_at,
    )
    assert applied.eligible_stale_count == 2
    assert applied.recovered_count == 2
    assert applied.remaining_running_count == 1

    for run_id, before in (
        (STALE_GARMIN_ID, before_garmin),
        (STALE_GOOGLE_ID, before_google),
    ):
        after = _run_snapshot(settings, run_id)
        for field in (
            "provider_id",
            "acquisition_source_id",
            "stream_code",
            "requested_start",
            "requested_end",
            "actual_start",
            "actual_end",
            "item_count",
            "received_count",
            "accepted_count",
            "failed_count",
            "started_at",
        ):
            assert after[field] == before[field]
        assert after["status"] == "failed"
        assert after["status"] != "succeeded"
        assert after["completed_at"] == completed_at
        assert after["error_category"] == SYNC_RUN_RECOVERY_ERROR_CATEGORY
        assert after["diagnostic_reason"] == SYNC_RUN_RECOVERY_DIAGNOSTIC_REASON

    assert _run_snapshot(settings, RECENT_RUN_ID) == before_recent
    assert _evidence_snapshot(settings) == before_evidence

    repeated = recover_stale_sync_runs(
        settings,
        cutoff=cutoff,
        apply=True,
        clock=lambda: datetime(2026, 3, 2, tzinfo=UTC),
    )
    assert repeated.eligible_stale_count == 0
    assert repeated.recovered_count == 0
    assert _run_snapshot(settings, STALE_GARMIN_ID)["completed_at"] == completed_at
    assert _run_snapshot(settings, STALE_GOOGLE_ID)["completed_at"] == completed_at


def test_lock_contention_blocks_recovery_without_mutation(tmp_path: Path) -> None:
    settings, paths = _runtime(tmp_path)
    _seed_running_rows(settings)
    acquired = threading.Event()
    release = threading.Event()

    def hold_lock() -> None:
        with ExternalRuntimeOperationLock(paths):
            acquired.set()
            assert release.wait(timeout=10)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert acquired.wait(timeout=10)
    try:
        with pytest.raises(ExternalRuntimeOperationBusyError):
            recover_stale_sync_runs(
                settings,
                cutoff=datetime(2026, 1, 15, tzinfo=UTC),
                apply=True,
            )
        assert _run_snapshot(settings, STALE_GARMIN_ID)["status"] == "running"
        assert _run_snapshot(settings, STALE_GOOGLE_ID)["status"] == "running"
    finally:
        release.set()
        holder.join(timeout=10)
    assert not holder.is_alive()


def test_garmin_and_google_sync_paths_exclude_recovery(tmp_path: Path, monkeypatch) -> None:
    settings, _paths = _runtime(tmp_path)
    _seed_running_rows(settings)

    operations = (
        GarminIncrementalSync(
            settings,
            client=object(),
            auth_result=GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED),
        ),
        GoogleHealthSync(
            settings,
            transport=object(),
            auth_result=GoogleAuthResult(status=GoogleAuthStatus.AUTHENTICATED),
            access_token="synthetic-token-not-emitted",
            run_kind=GoogleRunKind.INCREMENTAL,
        ),
    )
    for operation in operations:
        acquired = threading.Event()
        release = threading.Event()
        failures: list[BaseException] = []

        def hold_provider_operation(*_args, **_kwargs):
            acquired.set()
            assert release.wait(timeout=10)
            return object()

        monkeypatch.setattr(operation, "_run", hold_provider_operation)

        def run_provider_operation() -> None:
            try:
                operation.run(as_of="2026-01-20")
            except BaseException as exc:  # pragma: no cover - surfaced below
                failures.append(exc)

        holder = threading.Thread(target=run_provider_operation)
        holder.start()
        assert acquired.wait(timeout=10)
        try:
            with pytest.raises(ExternalRuntimeOperationBusyError):
                recover_stale_sync_runs(
                    settings,
                    cutoff=datetime(2026, 1, 15, tzinfo=UTC),
                    apply=True,
                )
        finally:
            release.set()
            holder.join(timeout=10)
        assert not holder.is_alive()
        assert failures == []
        assert _run_snapshot(settings, STALE_GARMIN_ID)["status"] == "running"
        assert _run_snapshot(settings, STALE_GOOGLE_ID)["status"] == "running"


def test_owner_refresh_lock_allows_nested_provider_lock_but_rejects_overlap(tmp_path: Path) -> None:
    _settings, paths = _runtime(tmp_path)
    with OwnerRefreshLock(paths):
        with ExternalRuntimeOperationLock(paths):
            pass
        with pytest.raises(ExternalRuntimeOperationBusyError):
            with OwnerRefreshLock(paths):
                pass


def test_cli_output_is_aggregate_and_privacy_safe(tmp_path: Path, capsys) -> None:
    settings, _paths = _runtime(tmp_path)
    seeded = _seed_running_rows(settings)

    exit_code = cli.main(
        [
            "sync-run-recovery",
            "--data-dir",
            str(settings.data_dir),
            "--cutoff",
            "2026-01-15T00:00:00Z",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["mode"] == "dry_run"
    assert payload["eligible_stale_count"] == 2
    assert payload["recovered_count"] == 0
    assert payload["privacy"] == {
        "health_timestamps_emitted": False,
        "private_identifiers_emitted": False,
        "raw_values_emitted": False,
        "tokens_emitted": False,
    }
    for private_value in (
        STALE_GARMIN_ID,
        STALE_GOOGLE_ID,
        RECENT_RUN_ID,
        *seeded["provider_ids"],
        seeded["source_id"],
        "synthetic-cursor",
        "2026-01-15",
    ):
        assert str(private_value) not in output


def test_cli_requires_explicit_cutoff_and_mode(tmp_path: Path, capsys) -> None:
    settings, _paths = _runtime(tmp_path)

    assert cli.main(["sync-run-recovery", "--data-dir", str(settings.data_dir)]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"
    assert payload["error"]["error_code"] == "invalid_recovery_request"


def test_normal_successful_sync_repository_lifecycle_is_unchanged(tmp_path: Path) -> None:
    settings, paths = _runtime(tmp_path)
    engine = create_sqlite_engine(paths)
    try:
        factory = create_session_factory(engine)
        with ExternalRuntimeOperationLock(paths):
            with factory() as session:
                repositories = repositories_for(session)
                provider = repositories.providers.get_or_create(
                    "synthetic-normal", "Synthetic", "test"
                )
                run = repositories.sync.create_run(
                    provider_id=provider.id,
                    stream_code="synthetic_success",
                )
                repositories.sync.finish_run(
                    run.id,
                    status="succeeded",
                    item_count=1,
                    received_count=1,
                    accepted_count=1,
                    failed_count=0,
                )
                session.commit()
                run_id = run.id
        with factory() as session:
            finished = session.get(SyncRun, run_id)
            assert finished is not None
            assert finished.status == "succeeded"
            assert finished.completed_at is not None
            assert finished.item_count == 1
            assert finished.received_count == 1
            assert finished.accepted_count == 1
            assert finished.failed_count == 0
    finally:
        engine.dispose()
