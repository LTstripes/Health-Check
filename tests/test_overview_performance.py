"""Synthetic #559 query budgets, indexed plans and unchanged analytic evidence."""

from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.engine import Engine

from healthcheck.config import Settings
from healthcheck.db.engine import _alembic_config, create_sqlite_engine
from healthcheck.db.models import GarminRecordMetric, GarminSourceRecord
from healthcheck.demo import seed_demo
from healthcheck.garmin.analytic_contract import (
    ANALYTIC_METRIC_REGISTRY,
    AnalyticInputAssemblyError,
    build_analytic_input_from_storage,
)
from healthcheck.garmin.analytic_storage import GarminAnalyticStorageBatch
from healthcheck.google.exercise_read import read_saved_exercise
from healthcheck.web.ui_app import create_ui_app
from test_garmin_analytic_contract import (
    _persist_fixture,
)
from test_garmin_analytic_contract import (
    analytic_persistence_database as analytic_persistence_database,
)


@contextmanager
def sql_statements():
    statements = []

    def collect(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))

    event.listen(Engine, "before_cursor_execute", collect)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", collect)


@pytest.fixture
def demo(tmp_path):
    settings = Settings(data_dir=tmp_path / "demo")
    # The local Owner-assigned pytest basetemp is inside the checkout. This
    # fixture creates only marked synthetic data, never a provider/runtime copy.
    with patch("healthcheck.demo._reject_source_workspace_target"):
        seed_demo(settings)
    return settings


@pytest.mark.parametrize("fixture", ["sleep", "daily_health", "activity"])
def test_batch_inputs_are_identical_including_manifest_hashes(
    analytic_persistence_database, fixture,
):
    _, session, store = analytic_persistence_database
    _persist_fixture(session, store, fixture)
    session.commit()
    rows = session.execute(select(GarminRecordMetric, GarminSourceRecord).join(
        GarminSourceRecord, GarminSourceRecord.id == GarminRecordMetric.record_id,
    )).all()
    batch = GarminAnalyticStorageBatch(session, rows)
    for metric, _ in rows:
        if metric.metric_code not in ANALYTIC_METRIC_REGISTRY:
            with pytest.raises(KeyError, match="unknown analytic metric code"):
                build_analytic_input_from_storage(session, metric_row_id=metric.id)
            with pytest.raises(KeyError, match="unknown analytic metric code"):
                build_analytic_input_from_storage(session, metric_row_id=metric.id, _batch=batch)
            continue
        single = build_analytic_input_from_storage(session, metric_row_id=metric.id)
        with sql_statements() as statements:
            batched = build_analytic_input_from_storage(
                session, metric_row_id=metric.id, _batch=batch,
            )
        assert statements == []
        assert batched.as_dict() == single.as_dict()


@pytest.mark.parametrize("failure", ["missing", "ambiguous", "artifact", "source"])
def test_batch_preserves_observation_errors(analytic_persistence_database, failure):
    _, session, store = analytic_persistence_database
    outcome = _persist_fixture(session, store, "daily_health")
    session.commit()
    rows = session.execute(select(GarminRecordMetric, GarminSourceRecord).join(
        GarminSourceRecord, GarminSourceRecord.id == GarminRecordMetric.record_id,
    )).all()
    metric, record = rows[0]
    batch = GarminAnalyticStorageBatch(session, rows)
    observations = batch.observations[outcome.raw_payload.id]
    if failure == "missing":
        observations.clear()
        expected = "no Garmin observation provenance"
    elif failure == "ambiguous":
        observations.append(observations[0])
        expected = "ambiguous Garmin observation provenance"
    elif failure == "artifact":
        observations[0].raw_artifact_id = "different-artifact"
        expected = "observation raw artifact mismatch"
    else:
        observations[0].garmin_source_id = "different-source"
        expected = "observation source mismatch"
    with pytest.raises(AnalyticInputAssemblyError, match=expected):
        build_analytic_input_from_storage(session, metric_row_id=metric.id, _batch=batch)
    session.rollback()


def test_exercise_discovery_uses_freshness_context_index(demo):
    from healthcheck.db.engine import session_scope
    from healthcheck.runtime import resolve_runtime_paths

    engine = create_sqlite_engine(resolve_runtime_paths(demo))
    try:
        with session_scope(engine) as session, sql_statements() as statements:
            packet = read_saved_exercise(session)
            assert packet["reason"] == "no_saved_exercise"
            sql, params = statements[0]
            plan = session.connection().exec_driver_sql("EXPLAIN QUERY PLAN " + sql, params)
            details = " ".join(row[3] for row in plan)
            assert "ix_google_source_records_freshness" in details
            assert "SCAN google_source_records" not in details
    finally:
        engine.dispose()


def test_chunked_batch_matches_single_inputs(demo, monkeypatch):
    from healthcheck.db.engine import session_scope
    from healthcheck.garmin import analytic_storage
    from healthcheck.runtime import resolve_runtime_paths

    monkeypatch.setattr(analytic_storage, "_CHUNK_SIZE", 3)
    engine = create_sqlite_engine(resolve_runtime_paths(demo))
    try:
        with session_scope(engine) as session:
            rows = session.execute(select(GarminRecordMetric, GarminSourceRecord).join(
                GarminSourceRecord, GarminSourceRecord.id == GarminRecordMetric.record_id,
            ).where(GarminRecordMetric.metric_code == "sleep_duration_seconds").order_by(
                GarminSourceRecord.source_local_date,
            )).all()
            assert len(rows) == 25
            batch = GarminAnalyticStorageBatch(session, rows)
            for metric, _ in rows:
                assert build_analytic_input_from_storage(
                    session, metric_row_id=metric.id, _batch=batch,
                ).as_dict() == build_analytic_input_from_storage(
                    session, metric_row_id=metric.id,
                ).as_dict()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "metric_code", ["sleep_duration_seconds", "sleep_score", "distance_meters"],
)
def test_complete_series_and_result_hash_match_single_reader(demo, metric_code):
    from healthcheck.analytics import garmin_baselines
    from healthcheck.db.engine import session_scope
    from healthcheck.db.models import GarminSource
    from healthcheck.runtime import resolve_runtime_paths

    engine = create_sqlite_engine(resolve_runtime_paths(demo))
    try:
        with session_scope(engine) as session:
            source_id = session.scalar(select(GarminSource.id))
            query = dict(metric_code=metric_code, start_date=date(2026, 9, 11),
                         end_date=date(2026, 10, 10), garmin_source_id=source_id)
            batched = garmin_baselines.compute_garmin_scalar_series(session, **query)
            # None selects the original per-row reader, with all validation and
            # frozen result assembly shared. Compare the entire exported body.
            with patch.object(garmin_baselines, "GarminAnalyticStorageBatch", return_value=None):
                single = garmin_baselines.compute_garmin_scalar_series(session, **query)
            assert batched.as_dict() == single.as_dict()
    finally:
        engine.dispose()


def test_observation_lookup_index_and_additive_migration(demo):
    from healthcheck.runtime import resolve_runtime_paths

    paths = resolve_runtime_paths(demo)
    config = _alembic_config(paths)
    command.downgrade(config, "0020_google_exercise")
    engine = create_sqlite_engine(paths)

    def snapshot():
        with engine.connect() as connection:
            tables = connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name!='alembic_version'"
            ).scalars().all()
            rows = {name: connection.exec_driver_sql(f'SELECT * FROM "{name}"').all()
                    for name in tables}
            triggers = connection.exec_driver_sql(
                "SELECT name, sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
            ).all()
            return rows, triggers

    try:
        before = snapshot()
        # Test the index-only revision independently of later body migrations.
        command.upgrade(config, "0021_garmin_observation_lookup")
        assert snapshot() == before
        # Reapplying this revision is harmless on an already migrated database.
        command.upgrade(config, "0021_garmin_observation_lookup")
        with engine.connect() as connection:
            plan = connection.execute(text(
                "EXPLAIN QUERY PLAN SELECT * FROM garmin_payload_observations "
                "WHERE garmin_raw_payload_id=:raw ORDER BY received_at, id"
            ), {"raw": "synthetic-raw"}).all()
            details = " ".join(row[3] for row in plan)
            assert "ix_garmin_payload_observations_raw_received" in details
            assert "TEMP B-TREE" not in details
            assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        engine.dispose()


@pytest.mark.parametrize("page", ["/brief", "/garmin"])
def test_page_sql_does_not_grow_per_sleep_record(demo, page, monkeypatch):
    from healthcheck import demo as demo_module
    from healthcheck.analytics import garmin_baselines
    from healthcheck.db.engine import session_scope
    from healthcheck.runtime import resolve_runtime_paths

    persist_sleep = demo_module._persist_garmin_sleep
    nights = demo_module._garmin_sleep_nights()
    with patch("healthcheck.demo._GARMIN_SLEEP_MISSING_OFFSETS", ()):
        all_nights = demo_module._garmin_sleep_nights()
    original_dates = {day for day, _ in nights}
    extra_nights = [night for night in all_nights if night[0] not in original_dates]
    # Hold the period, activities, Google, Weight and Context rows constant.
    # Grow only Garmin scalar inputs, using the very same seed-demo producer.
    # Full seed also keeps the separate recent-import queue at its 50-batch cap.
    app, _ = create_ui_app(demo)
    counts = []
    sizes = []
    selected = []

    def batch(session, rows, **kwargs):
        selected.append(len(rows))
        return GarminAnalyticStorageBatch(session, rows, **kwargs)

    monkeypatch.setattr(garmin_baselines, "GarminAnalyticStorageBatch", batch)
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        for grow in (False, True):
            if grow:
                paths = resolve_runtime_paths(demo)
                engine = create_sqlite_engine(paths)
                try:
                    with session_scope(engine) as session:
                        persist_sleep(session, paths, extra_nights)
                finally:
                    engine.dispose()
            selected.clear()
            params = {"start_date": "2026-09-11", "end_date": "2026-10-10"}
            if page == "/garmin":
                params["metric_code"] = "sleep_duration_seconds"
            with sql_statements() as statements:
                response = client.get(page, params=params)
            assert response.status_code == 200
            counts.append(len(statements))
            sizes.append(max(selected))
    assert sizes == [25, 30], sizes
    assert counts[1] <= counts[0], counts
