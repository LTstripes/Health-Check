"""#572: cached validation must reject mutations and freshness stays equivalent."""

from __future__ import annotations

import runpy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from healthcheck import source_freshness_read as reader
from healthcheck.analytics.sleep_agreement import PersistedSleepAgreementService
from healthcheck.analytics.sleep_agreement_report import SleepAgreementReportService
from healthcheck.analytics.sleep_metrics import read_persisted_sleep_metric_projection
from healthcheck.db.engine import _alembic_config, create_sqlite_engine
from healthcheck.db.models import (
    AgreementCoverage,
    AgreementMetricResult,
    AgreementRun,
    AgreementRunPair,
    GarminSource,
    GarminSourceRecord,
    GoogleSource,
    GoogleSourceRecord,
)
from healthcheck.db.repositories import AgreementRunRepository
from test_google_freshness_read_equivalence import record
from test_google_freshness_read_equivalence import session as session
from test_sleep_metrics import (
    _google_sleep_payload,
    _persist_garmin,
    _persist_google,
)
from test_sleep_metrics import (
    projection_database as projection_database,
)

REFERENCE = runpy.run_path(str(
    Path(__file__).resolve().parents[1] / "scripts/google_freshness_read_reference.py"
))["_evidence_query"]


@pytest.fixture
def published(projection_database):
    session, paths = projection_database
    _persist_garmin(session, paths)
    _persist_google(session, paths, payload=_google_sleep_payload())
    session.commit()
    projection = read_persisted_sleep_metric_projection(session)
    result = PersistedSleepAgreementService(session).persist(projection, scope_key="synthetic:572")
    session.commit()
    # Simulate storage tampering past the ordinary immutability guards, in
    # this disposable synthetic fixture only. Production triggers stay intact.
    with session.bind.begin() as connection:
        triggers = connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name LIKE 'agreement_%'"
        ).scalars().all()
        for name in triggers:
            connection.exec_driver_sql(f'DROP TRIGGER "{name}"')
    return session, result.id


def test_validation_reused_across_repository_instances_and_committed_reads(published):
    session, run_id = published
    with patch.object(AgreementRunRepository, "_validate_integrity", autospec=True,
                      wraps=None) as validate:
        # Use the real implementation while counting calls.
        validate.side_effect = _REAL_VALIDATE
        first = SleepAgreementReportService(session).report(run_id=run_id)
        session.commit()
        second = SleepAgreementReportService(session).report(run_id=run_id)
        assert second == first
        assert validate.call_count == 1


_REAL_VALIDATE = AgreementRunRepository._validate_integrity


@pytest.mark.parametrize("model,values", [
    (AgreementMetricResult, {"manifest_json": "{}"}),
    (AgreementRunPair, {"pair_json": "{}"}),
    (AgreementCoverage, {"coverage_json": "{}"}),
    (AgreementRun, {"input_snapshot_json": "{}"}),
])
@pytest.mark.parametrize("external", [False, True])
def test_cached_validation_detects_in_place_updates(published, model, values, external):
    session, run_id = published
    repository = AgreementRunRepository(session)
    repository.validate_published(run_id)
    session.commit()
    # Deliberately leave ORM rows in the identity map (expire_on_commit=False).
    keep = list(session.scalars(select(model)))
    assert keep
    session.commit()
    if external:
        reader_connection = session.connection()
        with session.bind.begin() as writer:
            assert (writer.connection.driver_connection is not
                    reader_connection.connection.driver_connection)
            writer.execute(update(model).values(**values))
    else:
        session.execute(update(model).values(**values).execution_options(synchronize_session=False))
        session.commit()
    with pytest.raises(ValueError):
        repository.validate_published(run_id)


def test_cached_validation_rejects_partial_published_run_with_original_reason(published):
    session, run_id = published
    repository = AgreementRunRepository(session)
    repository.validate_published(run_id)
    session.execute(delete(AgreementMetricResult).where(AgreementMetricResult.run_id == run_id))
    session.commit()
    for _ in range(2):  # Failed validation must never become a cached success.
        with pytest.raises(ValueError, match="metric_count does not match its child rows"):
            repository.validate_published(run_id)


@pytest.mark.parametrize("savepoint", [False, True])
def test_rolled_back_validation_does_not_authorize_a_different_stored_state(published, savepoint):
    session, run_id = published
    repository = AgreementRunRepository(session)
    repository.validate_published(run_id)
    session.commit()
    # Persist corruption, then temporarily repair and validate it, then roll
    # that repair back. SQLite total_changes alone cannot distinguish this.
    row = session.scalar(select(AgreementMetricResult))
    metric_id, original = row.id, row.manifest_json
    row.manifest_json = "{}"
    session.commit()
    transaction = session.begin_nested() if savepoint else session.begin()
    session.execute(update(AgreementMetricResult).where(
        AgreementMetricResult.id == metric_id,
    ).values(manifest_json=original))
    repository.validate_published(run_id)
    transaction.rollback()
    with pytest.raises(ValueError):
        repository.validate_published(run_id)


def test_new_connection_validates_independently(published):
    session, run_id = published
    AgreementRunRepository(session).validate_published(run_id)
    # A new connection to the same database still performs its first validation.
    with session.bind.connect() as other, Session(other) as second:
        with patch.object(AgreementRunRepository, "_validate_integrity", autospec=True) as validate:
            validate.side_effect = _REAL_VALIDATE
            AgreementRunRepository(second).validate_published(run_id)
            assert validate.call_count == 1


def test_cached_validation_keeps_one_snapshot_then_detects_external_commit(published):
    session, run_id = published
    repository = AgreementRunRepository(session)
    repository.validate_published(run_id)
    session.commit()
    repository.validate_published(run_id)  # Pins the current WAL snapshot.
    with session.bind.begin() as writer:
        writer.execute(update(AgreementMetricResult).values(manifest_json="{}"))
    # A concurrent commit must not mix newer rows into the old coherent read.
    repository.validate_published(run_id)
    session.commit()
    with pytest.raises(ValueError, match="metric manifest hash is inconsistent"):
        repository.validate_published(run_id)


def test_freshness_migration_is_additive_and_uses_both_indexes(projection_database):
    session, paths = projection_database
    _persist_garmin(session, paths)
    _persist_google(session, paths, payload=_google_sleep_payload())
    session.commit()
    session.close()
    config = _alembic_config(paths)
    command.downgrade(config, "0021_garmin_observation_lookup")
    engine = create_sqlite_engine(paths)

    def snapshot():
        with engine.connect() as connection:
            tables = connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name!='alembic_version'"
            ).scalars().all()
            return (
                {table: connection.exec_driver_sql(f'SELECT * FROM "{table}"').all()
                 for table in tables},
                connection.exec_driver_sql(
                    "SELECT name, sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
                ).all(),
            )

    try:
        before = snapshot()
        command.upgrade(config, "head")
        assert snapshot() == before
        with engine.connect() as connection:
            for table, clauses in (
                ("google_source_records", "google_source_id='s' AND stream_code='heart_rate' "
                 "AND query_mode='list' AND data_source_family IS NULL "
                 "AND projection_status='current' AND record_status='ok'"),
                ("garmin_source_records", "stream_code='sleep' AND surface_code='sleep' "
                 "AND projection_status='current' AND record_status IN ('ok','partial')"),
            ):
                plan = connection.exec_driver_sql(
                    f"EXPLAIN QUERY PLAN SELECT source_local_date FROM {table} "
                    f"WHERE {clauses} ORDER BY source_local_date DESC LIMIT 1"
                ).all()
                assert any(f"ix_{table}_freshness" in row[3] for row in plan)
                assert all("TEMP B-TREE" not in row[3] for row in plan)
        command.downgrade(config, "0021_garmin_observation_lookup")
        assert snapshot() == before
        command.upgrade(config, "head")
    finally:
        engine.dispose()


@pytest.mark.parametrize("kind", ["empty", "dated", "undated", "invalid", "mixed", "foreign"])
@pytest.mark.parametrize("latest_slice", [False, True])
def test_generic_freshness_matches_old_aggregate(session, kind, latest_slice):
    if kind != "empty":
        record(session, "a", day=None if kind in {"undated", "invalid"} else date(2099, 1, 1),
               precision="unknown" if kind == "invalid" else "instant",
               stamp=None if kind == "invalid" else datetime(2099, 1, 1, tzinfo=UTC),
               source="other" if kind == "foreign" else "s1")
    if kind == "mixed":
        record(session, "b", source="s2", day=date(2099, 1, 1))
        record(session, "c", day=None, precision="unknown")
    session.commit()
    kwargs = dict(
        joins=((GoogleSource, GoogleSource.id == GoogleSourceRecord.google_source_id),),
        conditions=(GoogleSource.provider_id == "p", GoogleSourceRecord.stream_code == "sleep"),
        source_identity=GoogleSourceRecord.google_source_id, latest_slice=latest_slice,
    )
    assert reader._evidence_query(session, GoogleSourceRecord, **kwargs) == REFERENCE(
        session, GoogleSourceRecord, **kwargs,
    )


def test_large_generic_freshness_equivalence_and_bounded_work(session):
    session.add(GarminSource(
        id="garmin", provider_id="p", acquisition_source_id="synthetic",
        source_kind="synthetic", provider_code="garmin_connect", source_instance_id="synthetic",
    ))
    for start in range(0, 100_000, 2000):
        session.execute(insert(GarminSourceRecord), [
            dict(id=f"g-{i}", garmin_source_id="garmin", raw_payload_id="synthetic",
                 stream_code="sleep", surface_code="sleep", idempotency_key=f"g-{i}",
                 temporal_precision="date", source_local_date=date(2099, 1, 1) - timedelta(days=i),
                 record_status="ok", projection_status="current",
                 normalization_contract_version="synthetic-572")
            for i in range(start, start + 2000)
        ])
    session.commit()
    kwargs = dict(
        joins=((GarminSource, GarminSource.id == GarminSourceRecord.garmin_source_id),),
        conditions=(GarminSource.provider_id == "p", GarminSourceRecord.stream_code == "sleep",
                    GarminSourceRecord.surface_code == "sleep",
                    GarminSourceRecord.projection_status == "current",
                    GarminSourceRecord.record_status.in_(("ok", "partial"))),
        source_identity=GarminSourceRecord.garmin_source_id,
    )
    driver = session.connection().connection.driver_connection

    def measure(callback):
        ticks = 0

        def progress():
            nonlocal ticks
            ticks += 1
            return 0

        driver.set_progress_handler(progress, 100)
        try:
            result = callback(session, GarminSourceRecord, **kwargs)
        finally:
            driver.set_progress_handler(None, 0)
        return result, ticks * 100

    old, old_steps = measure(REFERENCE)
    current, steps = measure(reader._evidence_query)
    assert current == old
    assert steps < old_steps / 100  # VM work, independent of host scheduling.
    print(f"generic freshness 100000 rows: old={old_steps} new<={steps + 100} VM steps")
