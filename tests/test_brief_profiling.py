"""Synthetic timing isolation, read-only harness and before/after render evidence."""

import json
import marshal
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from scripts.profile_brief import (
    normalize_sql,
    parse_timing,
    profile,
    readonly_engine,
    validate_output,
)
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import OperationalError

from healthcheck.analytics import garmin_activity_comparison as comparison
from healthcheck.db.engine import create_sqlite_engine, session_scope
from healthcheck.db.models import GarminSourceRecord
from healthcheck.garmin.normalization import garmin_source_identity, normalize_garmin_payload
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.logging import JsonFormatter
from healthcheck.web import pages, period_brief_query
from healthcheck.web.brief_timing import BriefTiming
from test_garmin_activity_comparison import _activity_payload
from test_garmin_query_dashboard import _ui
from test_period_brief_ui import seed_overview_v2


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2099, 1, 10, 12, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(pages, "datetime", Clock)
    monkeypatch.setattr(period_brief_query, "datetime", Clock)
    app, settings, paths = _ui(tmp_path)
    seed_overview_v2(paths)
    engine = create_sqlite_engine(paths)
    with session_scope(engine) as session:
        repo = GarminPersistenceRepository(
            session, payload_store=ContentAddressedGarminPayloadStore(paths.root / "artifacts"),
        )
        for i in range(3):
            payload = _activity_payload(
                activity_id=f"profile-{i}", distance=0 if i == 0 else 1000,
            )["payload"]
            outcome = repo.persist_result(
                normalize_garmin_payload(
                    payload, stream="activity",
                    source_identity=garmin_source_identity(source_kind="provider")),
                payload=payload, received_at=datetime(2099, 1, 3, tzinfo=UTC),
            )
            source = outcome.records[0].garmin_source_id
            if i == 2:
                outcome.records[0].record_status = "partial"
    engine.dispose()
    return app, settings, paths, source


@pytest.mark.parametrize("empty", [False, True])
def test_normalized_entire_brief_html_and_packets_match_single_reader(synthetic, empty):
    app, _, _, source = synthetic
    params = {"start_date": "2000-01-01" if empty else "2099-01-01",
              "end_date": "2000-01-02" if empty else "2099-01-02",
              "garmin_source_id": source}
    # This fallback is the original per-metric production assembly, sharing the
    # same projection, validation, quality, manifests and result hashing code.
    client = TestClient(app, base_url="http://127.0.0.1:8120")
    try:
        with patch.object(comparison, "GarminAnalyticStorageBatch", return_value=None):
            before = client.get("/brief", params=params)
        after = client.get("/brief", params=params)
    finally:
        client.close()
    assert before.status_code == after.status_code == 200
    assert " ".join(after.text.split()) == " ".join(before.text.split())
    assert after.context["packet"] == before.context["packet"]
    assert after.context["overview"] == before.context["overview"]
    if empty:
        assert after.context["overview"]["garmin"]["stress_daily_average"]["value"] is None
        assert not after.context["overview"]["google"]["sources"]
    else:
        overview = after.context["overview"]
        assert overview["garmin"]["stress_daily_average"]["value"] == 0
        assert overview["google"]["sources"]  # Separate Google source series are retained.
        packet = after.context["packet"]
        # The selected activities exercise the optimized path and real zero.
        # Sparse saved-day coverage is retained separately from completeness.
        serialized = json.dumps(packet)
        assert '"zero"' in serialized
        rhr = overview["rhr"]["items"][0]["dto"]
        assert rhr["eligible_day_count"] == 1 and rhr["requested_day_count"] == 2
        assert rhr["acquisition_coverage_state"] == "unknown"
        assert parse_timing(after.headers["Server-Timing"])["brief_queries"] < (
            parse_timing(before.headers["Server-Timing"])["brief_queries"])


def test_header_counts_match_actual_sql_and_logging_is_opt_in(synthetic, caplog):
    app, settings, paths, source = synthetic
    engine = create_sqlite_engine(paths)
    app.state.engine = engine
    statements = []

    def collect(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", collect)
    client = TestClient(app, base_url="http://127.0.0.1:8120")
    try:
        params = {"start_date": "2099-01-01", "end_date": "2099-01-02",
                  "garmin_source_id": source}
        with caplog.at_level("INFO", logger="healthcheck"):
            first = client.get("/brief", params=params)
            assert not any(r.getMessage() == "brief_timing" for r in caplog.records)
            # BEGIN belongs to snapshot setup, outside the six content blocks.
            timing = parse_timing(first.headers["Server-Timing"])
            assert sum(v for k, v in timing.items() if k.endswith("_queries")) == (
                len(statements) - statements.count("BEGIN"))
            for block in ("brief", "overview", "rhr", "charts", "completed", "steps", "render"):
                assert timing[block] >= timing[f"{block}_sql"] >= 0
            settings.brief_timing_log = True
            second = client.get("/brief", params=params)
        logged = [r for r in caplog.records if r.getMessage() == "brief_timing"]
        assert len(logged) == 1
        payload = json.loads(JsonFormatter().format(logged[0]))
        assert payload["reason"] == second.headers["Server-Timing"]
        assert source not in payload["reason"] and "2099" not in payload["reason"]
        assert len(second.headers["Server-Timing"]) < 2000
        assert "Server-Timing" not in client.get("/healthz").headers
        invalid = client.get("/brief?preset=invalid")
        assert invalid.status_code == 400
        assert parse_timing(invalid.headers["Server-Timing"])["render"] > 0
    finally:
        client.close()
        engine.dispose()


def test_sql_listeners_are_connection_local_and_removed_on_failure():
    engine = create_engine("sqlite://")

    def measure(count):
        timing = BriefTiming()
        with engine.connect() as connection:
            with pytest.raises(RuntimeError), timing.sql(connection), timing.block("brief"):
                for _ in range(count):
                    connection.exec_driver_sql("SELECT 1")
                raise RuntimeError("synthetic")
            connection.exec_driver_sql("SELECT 1")
        return timing.blocks["brief"].sql_count

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            assert list(executor.map(measure, (3, 7))) == [3, 7]
    finally:
        engine.dispose()


def test_profiler_never_starts_runtime_or_writes_database(synthetic, tmp_path, monkeypatch):
    _, _, paths, source = synthetic
    engine = readonly_engine(paths.database)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA query_only").scalar() == 1
            with pytest.raises(OperationalError, match="readonly"):
                connection.exec_driver_sql("CREATE TABLE forbidden (id INTEGER)")
    finally:
        engine.dispose()
    original = paths.database.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("profiling must not start/migrate/prepare runtime")

    monkeypatch.setattr("healthcheck.app.prepare_runtime", forbidden)
    monkeypatch.setattr("healthcheck.db.engine.migrate_database", forbidden)
    stats = tmp_path / "brief.pstats"
    result = profile(paths.root, source=source, end=datetime(2099, 1, 2).date(),
                     period=7, repeats=2, cprofile=stats)
    assert len(result["samples"]) == 3
    assert result["warm_repeats"] == 2
    assert result["sql"][0]["plan"]
    assert paths.database.read_bytes() == original
    assert source not in json.dumps(result)
    cpu = marshal.loads(stats.read_bytes())
    assert any(key[2] == "period_brief_page" for key in cpu)


def test_sql_normalization_removes_literals_and_parameter_values():
    assert normalize_sql("SELECT * FROM t WHERE value='private''value' AND n=77 -- comment") == (
        "SELECT * FROM t WHERE value=? AND n=?")
    assert normalize_sql("SELECT 'private--value', 'private/*value*/', 55") == (
        "SELECT ?, ...")


def test_profiler_outputs_cannot_overwrite_input_profile(tmp_path):
    with pytest.raises(ValueError, match="outside the input profile"):
        validate_output(tmp_path, tmp_path / "healthcheck.db")


def test_activity_batch_query_budget_and_complete_hash_equivalence(synthetic):
    _, _, paths, source = synthetic
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            ids = list(session.scalars(select(GarminSourceRecord.id).where(
                GarminSourceRecord.garmin_source_id == source,
                GarminSourceRecord.stream_code == "activity",
            ).order_by(GarminSourceRecord.id)))
            counts = []
            for size in (2, 3):
                statements = []

                def collect(conn, cursor, statement, *args):
                    statements.append(statement)

                kwargs = dict(garmin_source_id=source, activity_record_ids=ids[:size],
                              reference_activity_id=ids[0])
                with patch.object(comparison, "GarminAnalyticStorageBatch", return_value=None):
                    before = comparison.compute_garmin_activity_comparison(session, **kwargs)
                event.listen(engine, "before_cursor_execute", collect)
                try:
                    after = comparison.compute_garmin_activity_comparison(session, **kwargs)
                finally:
                    event.remove(engine, "before_cursor_execute", collect)
                assert after.as_dict() == before.as_dict()
                counts.append(len(statements))
            assert counts[0] == counts[1] <= 8
    finally:
        engine.dispose()
