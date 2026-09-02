from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import inspect, select

from healthcheck.config import Settings
from healthcheck.db.engine import (
    create_session_factory,
    create_sqlite_engine,
    database_readiness,
    migrate_database,
)
from healthcheck.db.models import (
    ImportCandidateEdit,
    ScalarMeasurement,
)
from healthcheck.db.repositories import (
    build_input_snapshot_hash,
    repositories_for,
)
from healthcheck.runtime import prepare_runtime


@pytest.fixture
def migrated_database(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    try:
        yield paths, engine
    finally:
        engine.dispose()


def test_empty_migration_is_idempotent_and_has_only_r01_tables(migrated_database):
    paths, engine = migrated_database
    migrate_database(paths)

    expected = {
        "providers",
        "physical_devices",
        "acquisition_sources",
        "measurement_algorithms",
        "raw_artifacts",
        "ingest_batches",
        "ingest_events",
        "import_candidates",
        "import_candidate_edits",
        "measurement_sessions",
        "scalar_measurements",
        "derived_measurements",
        "canonical_rule_sets",
        "canonical_selection_runs",
        "canonical_selections",
        "sync_runs",
        "sync_stream_state",
        "coverage_intervals",
        "alembic_version",
    }
    table_names = set(inspect(engine).get_table_names())
    assert table_names == expected
    assert not {"sleep_sessions", "activities", "series_streams", "context_events"} & table_names
    assert database_readiness(paths) == {
        "journal_mode": "wal",
        "foreign_keys": 1,
        "migration_revision": "0001_r01_core_schema",
        "ready": True,
    }


def test_repositories_retain_provenance_and_deduplicate_raw_and_ingest(e2e_database):
    repositories, session = e2e_database
    provider = repositories.providers.get_or_create("xiaomi_home", "Xiaomi Home", "scale_app")
    device = repositories.physical_devices.get_or_create(
        "xiaomi_s400", manufacturer="Xiaomi", model="S400"
    )
    source = repositories.acquisition_sources.get_or_create(
        provider_id=provider.id,
        physical_device_id=device.id,
        input_method="photo_import",
        source_application="Xiaomi Home",
    )
    algorithm = repositories.measurement_algorithms.get_or_create(
        code="xiaomi_home_s400_unknown_version",
        version="unknown",
        metric_family="body_composition",
        producer="xiaomi",
        compatibility_group="xiaomi_home_s400_unknown_version",
    )
    artifact = repositories.raw_artifacts.get_or_create(
        content_hash="a" * 64,
        kind="photo",
        media_type="image/jpeg",
        byte_size=128,
        relative_storage_path="photos/aa/" + "a" * 64 + ".jpg",
        source_filename="scale.jpg",
    )
    duplicate_artifact = repositories.raw_artifacts.get_or_create(
        content_hash="A" * 64,
        kind="photo",
        media_type="image/jpeg",
        byte_size=999,
        relative_storage_path="photos/other.jpg",
    )
    assert duplicate_artifact.id == artifact.id
    with pytest.raises(ValueError):
        repositories.raw_artifacts.get_or_create(
            content_hash="b" * 64,
            kind="photo",
            media_type="image/jpeg",
            byte_size=1,
            relative_storage_path="C:/private/photo.jpg",
        )

    batch = repositories.ingest_batches.create(
        acquisition_source_id=source.id,
        batch_kind="photo",
        extractor_name="synthetic-extractor",
        extractor_version="1",
    )
    event = repositories.ingest_events.get_or_create(
        ingest_batch_id=batch.id,
        acquisition_source_id=source.id,
        raw_artifact_id=artifact.id,
        external_user_id="synthetic-user",
        provider_stream="photo",
        external_record_id="synthetic-record-1",
        event_type="photo",
        status="pending-confirmation",
    )
    duplicate_event = repositories.ingest_events.get_or_create(
        ingest_batch_id=batch.id,
        acquisition_source_id=source.id,
        external_user_id="synthetic-user",
        provider_stream="photo",
        external_record_id="synthetic-record-1",
        status="failed",
    )
    assert duplicate_event.id == event.id

    candidate = repositories.import_candidates.create_pending(
        ingest_event_id=event.id,
        candidate_set_key="synthetic-extractor@1/schema-1",
        measurement_group_key="weigh-in-1",
        metric_code="weight",
        proposed_value=72.4,
        proposed_unit="kg",
        proposed_source_local_date=date(2026, 1, 2),
        temporal_precision="date",
        confidence=None,
    )
    assert candidate.confidence is None
    repositories.import_candidates.decide(
        candidate.id,
        "confirmed",
        edited_value=72.3,
        edited_unit="kg",
    )
    assert (
        session.scalar(
            select(ImportCandidateEdit).where(ImportCandidateEdit.candidate_id == candidate.id)
        )
        is not None
    )

    session_record = repositories.measurement_sessions.create_confirmed(
        acquisition_source_id=source.id,
        ingest_event_id=event.id,
        raw_artifact_id=artifact.id,
        confirmation_candidate_id=candidate.id,
        source_record_id="synthetic-record-1",
        source_local_date=date(2026, 1, 2),
        temporal_precision="date",
    )
    measurement = repositories.scalar_measurements.create(
        measurement_session_id=session_record.id,
        import_candidate_id=candidate.id,
        metric_code="weight",
        normalized_value=72.3,
        normalized_unit="kg",
        original_value="72.3",
        original_unit="kg",
        measurement_algorithm_id=algorithm.id,
    )
    assert measurement.measurement_session_id == session_record.id
    assert measurement.normalized_value == pytest.approx(72.3)
    assert session_record.source_timestamp_utc is None
    assert session_record.source_local_date == date(2026, 1, 2)
    repeated_session = repositories.measurement_sessions.create_confirmed(
        acquisition_source_id=source.id,
        ingest_event_id=event.id,
        raw_artifact_id=artifact.id,
        confirmation_candidate_id=candidate.id,
        source_record_id="different-transport-id",
        source_local_date=date(2026, 1, 2),
        temporal_precision="date",
    )
    assert repeated_session.id == session_record.id


def test_date_precision_rejects_invented_timestamp_and_revisions_are_append_only(e2e_database):
    repositories, session = e2e_database
    provider = repositories.providers.get_or_create("synthetic", "Synthetic", "test")
    source = repositories.acquisition_sources.get_or_create(
        provider_id=provider.id, input_method="manual_import"
    )
    algorithm = repositories.measurement_algorithms.get_or_create(
        code="synthetic-weight",
        version="1",
        metric_family="weight",
        producer="healthcheck",
        compatibility_group="synthetic-weight-v1",
    )
    with pytest.raises(ValueError):
        repositories.measurement_sessions.create_confirmed(
            acquisition_source_id=source.id,
            source_local_date=date(2026, 1, 2),
            temporal_precision="date",
            source_timestamp_utc=datetime(2026, 1, 2, tzinfo=UTC),
        )
    with pytest.raises(ValueError):
        repositories.measurement_sessions.create_confirmed(
            acquisition_source_id=source.id,
            source_local_date=date(2026, 1, 2),
            temporal_precision="minute",
            source_timestamp_utc=datetime(2026, 1, 2, 8, 30, 1, tzinfo=UTC),
        )

    first_session = repositories.measurement_sessions.create_confirmed(
        acquisition_source_id=source.id,
        semantic_key="weigh-in-1",
        source_local_date=date(2026, 1, 2),
        temporal_precision="instant",
        source_timestamp_utc=datetime(2026, 1, 2, 8, 30, tzinfo=UTC),
    )
    first = repositories.scalar_measurements.create(
        measurement_session_id=first_session.id,
        metric_code="weight",
        normalized_value=72.5,
        normalized_unit="kg",
        measurement_algorithm_id=algorithm.id,
    )
    revision_session = repositories.measurement_sessions.create_revision(
        first_session.id,
        source_local_date=date(2026, 1, 2),
        temporal_precision="instant",
        source_timestamp_utc=datetime(2026, 1, 2, 8, 30, tzinfo=UTC),
    )
    revision = repositories.scalar_measurements.create_revision(
        first.id,
        measurement_session_id=revision_session.id,
        normalized_value=72.4,
        normalized_unit="kg",
        measurement_algorithm_id=algorithm.id,
    )
    session.expire_all()
    assert session.get(ScalarMeasurement, first.id).normalized_value == pytest.approx(72.5)
    assert revision.supersedes_measurement_id == first.id
    assert repositories.scalar_measurements.active_for_metric("weight") == [revision]
    with pytest.raises(Exception):
        session.delete(first)
        session.flush()
    session.rollback()


def test_algorithms_canonical_runs_and_coverage_are_versioned(e2e_database):
    repositories, session = e2e_database
    provider = repositories.providers.get_or_create("xiaomi", "Xiaomi", "scale")
    source = repositories.acquisition_sources.get_or_create(
        provider_id=provider.id,
        input_method="webhook",
        source_instance_id="12345678-1234-5678-1234-567812345678",
    )
    xiaomi_algorithm = repositories.measurement_algorithms.get_or_create(
        code="xiaomi-home",
        version="unknown",
        metric_family="body_composition",
        producer="xiaomi",
        compatibility_group="xiaomi-home-unknown",
    )
    openscale_algorithm = repositories.measurement_algorithms.get_or_create(
        code="openscale",
        version="2.0",
        metric_family="body_composition",
        producer="openscale",
        compatibility_group="openscale-2.0",
    )
    assert xiaomi_algorithm.compatibility_group != openscale_algorithm.compatibility_group
    assert source.source_instance_id == "12345678-1234-5678-1234-567812345678"
    measurement_session = repositories.measurement_sessions.create_confirmed(
        acquisition_source_id=source.id,
        semantic_key="2026-01-02",
        source_local_date=date(2026, 1, 2),
        temporal_precision="date",
    )
    source_measurement = repositories.scalar_measurements.create(
        measurement_session_id=measurement_session.id,
        metric_code="weight",
        normalized_value=72.4,
        normalized_unit="kg",
        measurement_algorithm_id=xiaomi_algorithm.id,
    )

    rule = repositories.canonical_rule_sets.get_or_create(
        rule_name="weight-v1",
        rule_version=1,
        rule_definition={"eligible": ["confirmed", "not_superseded"]},
        creation_reason="synthetic acceptance test",
    )
    records = [("b", "revision-2"), ("a", "revision-1")]
    snapshot = build_input_snapshot_hash(records)
    reordered_snapshot = build_input_snapshot_hash(reversed(records))
    assert snapshot == reordered_snapshot
    run, created = repositories.canonical_selection_runs.start_or_get(
        scope_key="weight:2026-01",
        rule_set=rule,
        input_snapshot_hash=snapshot,
        requested_start_date=date(2026, 1, 1),
        requested_end_date=date(2026, 1, 31),
    )
    assert created is True
    repositories.canonical_selection_runs.finish(
        run.id, status="failed", failure_reason="synthetic failure"
    )
    with pytest.raises(ValueError):
        repositories.canonical_selections.add(
            selection_run_id=run.id,
            metric_code="weight",
            semantic_key="2026-01-02",
            selection_reason="must not activate failed run",
            source_measurement_id="missing",
        )

    successful_run, successful_created = repositories.canonical_selection_runs.start_or_get(
        scope_key="weight:2026-01",
        rule_set=rule,
        input_snapshot_hash=snapshot,
    )
    assert successful_created is True
    selection = repositories.canonical_selections.add(
        selection_run_id=successful_run.id,
        metric_code="weight",
        semantic_key="2026-01-02",
        selection_reason="latest confirmed synthetic value",
        source_measurement_id=source_measurement.id,
    )
    repositories.canonical_selection_runs.finish(
        successful_run.id, status="succeeded", selection_count=1
    )
    existing_run, existing_created = repositories.canonical_selection_runs.start_or_get(
        scope_key="weight:2026-01",
        rule_set=rule,
        input_snapshot_hash=snapshot,
    )
    assert existing_run.id == successful_run.id
    assert existing_created is False
    assert repositories.canonical_selections.for_run(successful_run.id) == [selection]
    assert session.get(ScalarMeasurement, source_measurement.id).normalized_value == pytest.approx(
        72.4
    )
    interval = repositories.coverage.record(
        provider_id=provider.id,
        acquisition_source_id=source.id,
        stream_code="weight",
        metric_code="weight",
        interval_start=datetime(2026, 1, 1, tzinfo=UTC),
        interval_end=datetime(2026, 1, 8, tzinfo=UTC),
        resolution="day",
        status="unknown",
        calculation_rule_version="coverage-v1",
        observed_count=None,
        expected_count=None,
    )
    assert interval.observed_count is None
    assert interval.expected_count is None


@pytest.fixture
def e2e_database(migrated_database):
    _paths, engine = migrated_database
    factory = create_session_factory(engine)
    with factory() as session:
        yield repositories_for(session), session
