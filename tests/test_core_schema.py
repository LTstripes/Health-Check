from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from alembic import command
from sqlalchemy import func, inspect, select, text

from healthcheck.config import Settings
from healthcheck.db.engine import (
    _alembic_config,
    create_session_factory,
    create_sqlite_engine,
    database_readiness,
    migrate_database,
)
from healthcheck.db.models import (
    ImportCandidateEdit,
    IngestEvent,
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
        "migration_revision": "0004_naive_minute_wall_clock",
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

    edit_count = session.scalar(
        select(func.count(ImportCandidateEdit.id)).where(
            ImportCandidateEdit.candidate_id == candidate.id
        )
    )
    assert (
        repositories.import_candidates.decide(
            candidate.id,
            "confirmed",
            edited_value=72.3,
            edited_unit="kg",
        ).id
        == candidate.id
    )
    assert (
        session.scalar(
            select(func.count(ImportCandidateEdit.id)).where(
                ImportCandidateEdit.candidate_id == candidate.id
            )
        )
        == edit_count
    )
    with pytest.raises(ValueError, match="terminal candidate decision"):
        repositories.import_candidates.decide(candidate.id, "rejected")
    with pytest.raises(ValueError, match="measurement revision"):
        repositories.import_candidates.decide(candidate.id, "confirmed", edited_value=72.2)

    audit_edit = session.scalar(
        select(ImportCandidateEdit).where(ImportCandidateEdit.candidate_id == candidate.id)
    )
    assert audit_edit is not None
    with pytest.raises(Exception):
        with session.begin_nested():
            audit_edit.actor = "tampered"
            session.flush()
    session.refresh(audit_edit)
    assert audit_edit.actor == "owner"
    with pytest.raises(Exception):
        with session.begin_nested():
            session.delete(audit_edit)
            session.flush()
    assert session.get(ImportCandidateEdit, audit_edit.id) is not None

    with pytest.raises(Exception):
        with session.begin_nested():
            candidate.decision_reason = "tampered"
            session.flush()
    session.refresh(candidate)
    assert candidate.user_decision == "confirmed"


def test_photo_reprocessing_requires_a_session_revision(e2e_database):
    repositories, _session = e2e_database
    provider = repositories.providers.get_or_create("xiaomi-photo", "Xiaomi", "scale")
    source = repositories.acquisition_sources.get_or_create(
        provider_id=provider.id,
        input_method="photo_import",
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
        raw_artifact_id=None,
        semantic_fingerprint="photo-envelope",
        event_type="photo",
    )
    first_candidate = repositories.import_candidates.create_pending(
        ingest_event_id=event.id,
        candidate_set_key="extractor@1",
        measurement_group_key="weigh-in-1",
        metric_code="weight",
        proposed_value=72.4,
        proposed_unit="kg",
        proposed_source_local_date=date(2026, 1, 2),
        temporal_precision="date",
    )
    repositories.import_candidates.decide(first_candidate.id, "confirmed")
    first_session = repositories.measurement_sessions.create_confirmed(
        acquisition_source_id=source.id,
        ingest_event_id=event.id,
        confirmation_candidate_id=first_candidate.id,
        source_record_id="photo-record-1",
        source_local_date=date(2026, 1, 2),
        temporal_precision="date",
    )

    reprocessed_candidate = repositories.import_candidates.create_pending(
        ingest_event_id=event.id,
        candidate_set_key="extractor@2",
        measurement_group_key="weigh-in-1",
        metric_code="weight",
        proposed_value=72.1,
        proposed_unit="kg",
        proposed_source_local_date=date(2026, 1, 2),
        temporal_precision="date",
    )
    repositories.import_candidates.decide(reprocessed_candidate.id, "confirmed")
    with pytest.raises(ValueError, match="call create_revision"):
        repositories.measurement_sessions.create_confirmed(
            acquisition_source_id=source.id,
            ingest_event_id=event.id,
            confirmation_candidate_id=reprocessed_candidate.id,
            source_record_id="photo-record-1",
            source_local_date=date(2026, 1, 2),
            temporal_precision="date",
        )

    revision = repositories.measurement_sessions.create_revision(
        first_session.id,
        confirmation_candidate_id=reprocessed_candidate.id,
        source_local_date=date(2026, 1, 2),
        temporal_precision="date",
    )
    assert revision.supersedes_session_id == first_session.id
    assert revision.revision_number == 2
    replayed_revision = repositories.measurement_sessions.create_revision(
        first_session.id,
        confirmation_candidate_id=reprocessed_candidate.id,
        source_local_date=date(2026, 1, 2),
        temporal_precision="date",
    )
    assert replayed_revision.id == revision.id
    assert (
        repositories.measurement_sessions.create_confirmed(
            acquisition_source_id=source.id,
            ingest_event_id=event.id,
            confirmation_candidate_id=first_candidate.id,
            source_record_id="photo-record-1",
            source_local_date=date(2026, 1, 2),
            temporal_precision="date",
        ).id
        == first_session.id
    )


def test_ingest_retry_identity_excludes_stream_and_allows_updates(e2e_database):
    repositories, session = e2e_database
    provider = repositories.providers.get_or_create("openscale-sync", "openScale", "webhook")
    source = repositories.acquisition_sources.get_or_create(
        provider_id=provider.id,
        input_method="webhook",
        source_instance_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )
    batch = repositories.ingest_batches.create(
        acquisition_source_id=source.id,
        batch_kind="webhook",
    )
    insert = repositories.ingest_events.get_or_create(
        ingest_batch_id=batch.id,
        acquisition_source_id=source.id,
        external_user_id="synthetic-user",
        provider_stream=None,
        external_record_id="source-record-1",
        semantic_fingerprint="payload-insert",
        event_type="insert",
    )
    exact_retry = repositories.ingest_events.get_or_create(
        ingest_batch_id=batch.id,
        acquisition_source_id=source.id,
        external_user_id="synthetic-user",
        provider_stream="measurements",
        external_record_id="source-record-1",
        semantic_fingerprint="PAYLOAD-INSERT",
        event_type="insert",
        status="failed",
    )
    assert exact_retry.id == insert.id

    update = repositories.ingest_events.get_or_create(
        ingest_batch_id=batch.id,
        acquisition_source_id=source.id,
        external_user_id="synthetic-user",
        provider_stream="measurements",
        external_record_id="source-record-1",
        semantic_fingerprint="payload-update",
        event_type="update",
    )
    update_retry = repositories.ingest_events.get_or_create(
        ingest_batch_id=batch.id,
        acquisition_source_id=source.id,
        external_user_id="synthetic-user",
        provider_stream=None,
        external_record_id="source-record-1",
        semantic_fingerprint="PAYLOAD-UPDATE",
        event_type="update",
    )
    assert update.id != insert.id
    assert update_retry.id == update.id

    null_user = repositories.ingest_events.get_or_create(
        ingest_batch_id=batch.id,
        acquisition_source_id=source.id,
        external_user_id=None,
        provider_stream=None,
        external_record_id="record-without-user",
        semantic_fingerprint="payload-null-user",
        event_type="insert",
    )
    assert (
        repositories.ingest_events.get_or_create(
            ingest_batch_id=batch.id,
            acquisition_source_id=source.id,
            external_user_id=None,
            provider_stream="weight",
            external_record_id="record-without-user",
            semantic_fingerprint="PAYLOAD-NULL-USER",
            event_type="insert",
        ).id
        == null_user.id
    )
    null_record = repositories.ingest_events.get_or_create(
        ingest_batch_id=batch.id,
        acquisition_source_id=source.id,
        external_user_id="synthetic-user",
        provider_stream=None,
        external_record_id=None,
        semantic_fingerprint="fallback-payload",
        event_type="insert",
    )
    assert (
        repositories.ingest_events.get_or_create(
            ingest_batch_id=batch.id,
            acquisition_source_id=source.id,
            external_user_id="synthetic-user",
            provider_stream="fallback",
            external_record_id=None,
            semantic_fingerprint="FALLBACK-PAYLOAD",
            event_type="insert",
        ).id
        == null_record.id
    )
    assert session.scalar(select(func.count(IngestEvent.id))) == 4


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
    naive_wall = repositories.measurement_sessions.create_confirmed(
        acquisition_source_id=source.id,
        semantic_key="naive-wall-minute",
        source_local_date=date(2026, 1, 2),
        temporal_precision="minute",
        source_timestamp_utc=None,
        source_local_timestamp=datetime(2026, 1, 2, 8, 15),
    )
    assert naive_wall.source_timestamp_utc is None
    assert naive_wall.source_local_timestamp is not None
    assert naive_wall.source_local_timestamp.replace(tzinfo=None).hour == 8
    assert naive_wall.source_local_timestamp.replace(tzinfo=None).minute == 15

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
    assert (
        repositories.measurement_sessions.create_revision(
            first_session.id,
            source_local_date=date(2026, 1, 2),
            temporal_precision="instant",
            source_timestamp_utc=datetime(2026, 1, 2, 8, 30, tzinfo=UTC),
        ).id
        == revision_session.id
    )
    with pytest.raises(ValueError, match="different successor"):
        repositories.measurement_sessions.create_revision(
            first_session.id,
            source_local_date=date(2026, 1, 2),
            temporal_precision="instant",
            source_timestamp_utc=datetime(2026, 1, 2, 8, 31, tzinfo=UTC),
        )
    assert (
        repositories.scalar_measurements.create_revision(
            first.id,
            measurement_session_id=revision_session.id,
            normalized_value=72.4,
            normalized_unit="kg",
            measurement_algorithm_id=algorithm.id,
        ).id
        == revision.id
    )
    with pytest.raises(ValueError, match="different successor"):
        repositories.scalar_measurements.create_revision(
            first.id,
            measurement_session_id=revision_session.id,
            normalized_value=72.3,
            normalized_unit="kg",
            measurement_algorithm_id=algorithm.id,
        )
    session.expire_all()
    assert (
        repositories.measurement_sessions.create_revision(
            first_session.id,
            source_local_date=date(2026, 1, 2),
            temporal_precision="instant",
            source_timestamp_utc=datetime(2026, 1, 2, 8, 30, tzinfo=UTC),
        ).id
        == revision_session.id
    )
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
        parameters={"formula": "unknown", "unit": "kg"},
    )
    assert (
        repositories.measurement_algorithms.get_or_create(
            code="xiaomi-home",
            version="unknown",
            metric_family="body_composition",
            producer="xiaomi",
            compatibility_group="xiaomi-home-unknown",
            parameters={"unit": "kg", "formula": "unknown"},
        ).id
        == xiaomi_algorithm.id
    )
    for contradictory_metadata in (
        {"metric_family": "weight"},
        {"producer": "other-provider"},
        {"compatibility_group": "other-group"},
        {"parameters": {"formula": "different", "unit": "kg"}},
    ):
        algorithm_metadata = {
            "metric_family": "body_composition",
            "producer": "xiaomi",
            "compatibility_group": "xiaomi-home-unknown",
            "parameters": {"formula": "unknown", "unit": "kg"},
        }
        algorithm_metadata.update(contradictory_metadata)
        with pytest.raises(ValueError, match="immutable metadata"):
            repositories.measurement_algorithms.get_or_create(
                code="xiaomi-home",
                version="unknown",
                **algorithm_metadata,
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
    completed_at = successful_run.completed_at
    assert (
        repositories.canonical_selection_runs.finish(
            successful_run.id,
            status="succeeded",
            selection_count=1,
        ).id
        == successful_run.id
    )
    assert successful_run.completed_at == completed_at
    with pytest.raises(ValueError, match="immutable"):
        repositories.canonical_selection_runs.finish(
            successful_run.id,
            status="succeeded",
            selection_count=2,
        )
    with pytest.raises(Exception):
        with session.begin_nested():
            successful_run.selection_count = 2
            session.flush()
    session.refresh(successful_run)
    assert successful_run.selection_count == 1
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


def test_linear_alembic_chain_canonical_then_photo(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    config = _alembic_config(paths)
    command.upgrade(config, "head")
    assert database_readiness(paths)["migration_revision"] == "0004_naive_minute_wall_clock"
    command.upgrade(config, "head")
    assert database_readiness(paths)["migration_revision"] == "0004_naive_minute_wall_clock"

    engine = create_sqlite_engine(paths)
    try:
        with engine.connect() as connection:
            columns = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(import_candidates)")
            }
            assert {
                "algorithm_code",
                "algorithm_version",
                "provider_code",
                "source_timezone",
                "source_utc_offset_minutes",
            } <= columns
            triggers = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='trigger'"
                )
            }
            assert "immutable_canonical_selections_update" in triggers
            assert "immutable_canonical_selections_delete" in triggers
            assert "immutable_terminal_import_candidates_update" in triggers
    finally:
        engine.dispose()


def test_existing_canonical_database_upgrades_to_photo_and_roundtrips(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    config = _alembic_config(paths)
    command.upgrade(config, "0002_canonical_selection_metric_identity")
    assert (
        database_readiness(paths)["migration_revision"]
        == "0002_canonical_selection_metric_identity"
    )

    engine = create_sqlite_engine(paths)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO providers (id, code, display_name, provider_kind) "
                    "VALUES ('prov-1', 'synthetic', 'Synthetic', 'test')"
                )
            )
            before_providers = connection.execute(text("SELECT COUNT(*) FROM providers")).scalar()
        command.upgrade(config, "0003_photo_candidate_provenance")
        assert database_readiness(paths)["migration_revision"] == "0003_photo_candidate_provenance"
        with engine.connect() as connection:
            after_providers = connection.execute(text("SELECT COUNT(*) FROM providers")).scalar()
            assert after_providers == before_providers
            columns = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(import_candidates)")
            }
            assert "algorithm_code" in columns
            triggers = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='trigger'"
                )
            }
            assert "immutable_canonical_selections_update" in triggers
        command.downgrade(config, "0002_canonical_selection_metric_identity")
        assert (
            database_readiness(paths)["migration_revision"]
            == "0002_canonical_selection_metric_identity"
        )
        with engine.connect() as connection:
            columns = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(import_candidates)")
            }
            assert "algorithm_code" not in columns
            assert connection.execute(text("SELECT COUNT(*) FROM providers")).scalar() == 1
            triggers = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type='trigger'"
                )
            }
            assert "immutable_canonical_selections_update" in triggers
        command.upgrade(config, "0003_photo_candidate_provenance")
        assert database_readiness(paths)["migration_revision"] == "0003_photo_candidate_provenance"
        command.upgrade(config, "head")
        assert database_readiness(paths)["migration_revision"] == "0004_naive_minute_wall_clock"
    finally:
        engine.dispose()
