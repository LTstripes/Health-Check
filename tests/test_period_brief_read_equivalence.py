"""Persisted-edge equivalence against #283's frozen pre-change query bodies."""

from __future__ import annotations

import random
import runpy
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from healthcheck import source_freshness_read as freshness
from healthcheck.analytics import garmin_baselines as baselines
from healthcheck.analytics.sleep_agreement_report import SleepAgreementReportService
from healthcheck.db.models import (
    Base,
    CoverageInterval,
    GarminRecordMetric,
    GarminSource,
    GarminSourceRecord,
    Provider,
    SyncRun,
    SyncStreamState,
)
from healthcheck.source_freshness import SCOPE_BY_KEY, evaluate_scope
from test_garmin_baselines_trends import _persist, _stress_payload
from test_garmin_baselines_trends import baselines_database as baselines_database

REFERENCE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts" / "period_brief_read_reference.py")
)
DAY = date(2099, 1, 15)
STAMP = datetime(2099, 1, 15, 12)
SURFACES = ("heart_rate", "stress", "body_battery", "spo2", "respiration")


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                Provider(
                    id="p",
                    code="garmin_connect",
                    display_name="Synthetic",
                    provider_kind="wearable",
                ),
                Provider(id="q", code="other", display_name="Other", provider_kind="other"),
                Provider(id="empty", code="empty", display_name="Empty", provider_kind="other"),
            ]
        )
        session.add_all(
            [
                GarminSource(
                    id=source,
                    provider_id=provider,
                    acquisition_source_id="synthetic",
                    source_kind="synthetic",
                    provider_code="garmin_connect",
                    source_instance_id=source,
                )
                for source, provider in (("s1", "p"), ("s2", "p"), ("foreign", "q"))
            ]
        )
        session.commit()
        yield session
    engine.dispose()


def record(
    session,
    rid,
    *,
    source="s1",
    day=DAY,
    precision="date",
    status="ok",
    projection="current",
    surface="heart_rate",
    stream="intraday",
    stamp=None,
):
    row = GarminSourceRecord(
        id=rid,
        garmin_source_id=source,
        raw_payload_id="synthetic-unused",
        stream_code=stream,
        surface_code=surface,
        idempotency_key=rid,
        temporal_precision=precision,
        source_local_date=day,
        source_timestamp_utc=stamp,
        local_wall_time="synthetic-unresolved" if precision == "local" else None,
        record_status=status,
        projection_status=projection,
        retired_at=STAMP if projection == "retired" else None,
        normalization_contract_version="synthetic-283",
    )
    session.add(row)
    return row


def assert_freshness_equal(session, provider, surface):
    expected = REFERENCE["_garmin_series_evidence_query"](session, provider, surface)
    actual = freshness._garmin_series_evidence_query(session, provider, surface)
    assert actual == expected
    scope = SCOPE_BY_KEY[f"garmin:{surface}"]
    with patch.object(
        freshness, "_garmin_series_evidence_query", REFERENCE["_garmin_series_evidence_query"]
    ):
        old_facts = freshness.read_facts(session, scope, evaluation_local_date=DAY)
    new_facts = freshness.read_facts(session, scope, evaluation_local_date=DAY)
    assert new_facts == old_facts
    kwargs = dict(evaluated_at_utc=STAMP.replace(tzinfo=UTC), evaluation_local_date=DAY)
    assert evaluate_scope(scope, new_facts, **kwargs) == evaluate_scope(scope, old_facts, **kwargs)
    return actual


@pytest.mark.parametrize(
    "kind",
    [
        "none",
        "only_undated",
        "dated_and_undated",
        "multiple_latest_sources",
        "older_other_source",
        "invalid_latest",
        "timestamp_and_date",
        "excluded_future",
    ],
)
@pytest.mark.parametrize("surface", SURFACES)
def test_freshness_latest_slice_and_reason_actionability(session, kind, surface):
    if kind == "only_undated":
        record(session, "undated", day=None, precision="unknown", surface=surface)
    elif kind != "none":
        record(session, "accepted", surface=surface)
        if kind == "dated_and_undated":
            record(session, "undated", day=None, precision="unknown", surface=surface)
        elif kind == "multiple_latest_sources":
            record(session, "second", source="s2", surface=surface)
        elif kind == "older_other_source":
            record(session, "older", source="s2", day=DAY - timedelta(days=1), surface=surface)
        elif kind == "invalid_latest":
            record(session, "local", precision="local", surface=surface)
        elif kind == "timestamp_and_date":
            record(session, "instant", precision="instant", stamp=STAMP, surface=surface)
        elif kind == "excluded_future":
            for suffix, kwargs in (
                ("invalid", dict(status="invalid")),
                ("empty", dict(status="empty")),
                ("retired", dict(projection="retired")),
                ("stream", dict(stream="daily_health")),
                ("provider", dict(source="foreign")),
            ):
                record(session, suffix, day=DAY + timedelta(days=1), surface=surface, **kwargs)
    session.commit()
    value = assert_freshness_equal(session, "p", surface)
    if kind == "none":
        assert value == (None, None, None, True, False)
    elif kind == "only_undated":
        assert value == (None, None, "invalid_chronology", True, True)
    elif kind == "multiple_latest_sources":
        assert value[3] is False
    elif kind == "invalid_latest":
        assert value[2] == "invalid_chronology"
    elif kind == "timestamp_and_date":
        assert value[:3] == (STAMP.replace(tzinfo=UTC), None, None)
    else:
        assert value == (None, DAY, None, True, True)


def test_randomized_persisted_freshness_provider_surface_statuses(session):
    rng = random.Random(283)
    for i in range(300):
        precision = rng.choice(("date", "instant", "unknown", "local"))
        record(
            session,
            str(i),
            source=rng.choice(("s1", "s2", "foreign")),
            day=rng.choice((None, DAY, DAY - timedelta(days=1), DAY + timedelta(days=2))),
            precision=precision,
            status=rng.choice(("ok", "partial", "invalid", "empty")),
            projection=rng.choice(("current", "retired")),
            surface=rng.choice(SURFACES),
            stamp=STAMP if precision == "instant" else None,
        )
    session.commit()
    for provider in ("p", "q", "absent"):
        for surface in SURFACES:
            assert_freshness_equal(session, provider, surface)


def test_freshness_decodes_only_global_latest_date_like_baseline(session):
    record(session, "unselected", source="s1", day=DAY - timedelta(days=1))
    record(session, "latest", source="s2")
    session.commit()
    session.execute(
        text(
            "UPDATE garmin_source_records SET source_local_date='2000-invalid' "
            "WHERE id='unselected'"
        )
    )
    session.commit()
    session.expire_all()
    assert assert_freshness_equal(session, "p", "heart_rate") == (None, DAY, None, True, True)


@pytest.mark.parametrize(
    "window",
    [
        (DAY, DAY),
        (DAY - timedelta(days=1), DAY),
        (None, None),
        (None, DAY),
        (DAY, None),
        (date.max, date.max),
    ],
)
@pytest.mark.parametrize("pending", [False, True])
def test_quality_all_clocks_tie_breaks_and_inclusive_coverage(session, window, pending):
    session.add_all(
        [
            SyncRun(
                id=rid,
                provider_id=provider,
                stream_code="any",
                status=status,
                started_at=start,
                completed_at=end,
            )
            for rid, provider, status, start, end in (
                (
                    "old-success",
                    "p",
                    "succeeded",
                    STAMP - timedelta(days=2),
                    STAMP - timedelta(days=1),
                ),
                ("a", "p", "failed", STAMP - timedelta(hours=1), STAMP),
                ("z", "p", "partial", STAMP - timedelta(hours=1), STAMP),
                ("q-failed", "q", "failed", STAMP, STAMP),
            )
        ]
    )
    if pending:
        session.add(
            SyncRun(
                id="pending",
                provider_id="p",
                stream_code="any",
                status="running",
                started_at=STAMP + timedelta(hours=1),
                completed_at=None,
            )
        )
    session.add(
        SyncStreamState(
            provider_id="p",
            stream_code="any",
            last_attempt_at=STAMP,
            last_success_at=STAMP + timedelta(hours=2),
        )
    )
    edges = (
        (datetime.combine(DAY - timedelta(days=1), time.min), datetime.combine(DAY, time.min)),
        (datetime.combine(DAY, time.max), datetime.combine(DAY + timedelta(days=1), time.min)),
        (
            datetime.combine(DAY + timedelta(days=1), time.min),
            datetime.combine(DAY + timedelta(days=2), time.min),
        ),
        (
            datetime.combine(DAY - timedelta(days=2), time.min),
            datetime.combine(DAY - timedelta(days=1), time.max),
        ),
        (datetime.combine(date.max, time.min), datetime.combine(date.max, time.max)),
    )
    for i, (left, right) in enumerate(edges):
        session.add(
            CoverageInterval(
                id=f"coverage-{i}",
                provider_id="p",
                stream_code="any",
                metric_code="metric",
                interval_start=left,
                interval_end=right,
                resolution="day",
                status=("present", "unavailable", "confirmed_empty", "failed", "unknown")[i],
                observed_count=0 if i == 2 else None,
                expected_count=None,
                calculation_rule_version="synthetic",
                diagnostic_reason="synthetic-reason",
            )
        )
    session.commit()
    pairs = [(SimpleNamespace(), SimpleNamespace(wake_date=DAY))]
    service = SleepAgreementReportService(session)
    expected = REFERENCE["_source_data_quality"](service, pairs, *window)
    actual = service._source_data_quality(pairs, *window)
    assert actual == expected
    garmin = next(row for row in actual if row["provider_code"] == "garmin_connect")
    assert garmin["last_sync_status"] == ("running" if pending else "partial")
    assert garmin["last_attempt"] == STAMP.isoformat()
    assert garmin["last_successful_sync"] == (STAMP + timedelta(hours=2)).isoformat()
    if window == (DAY, DAY):
        assert len(garmin["coverage_facts"]) == 2


@pytest.mark.parametrize(
    "status, coverage, state",
    [
        (None, "unknown", "unknown"),
        (None, "confirmed_empty", "confirmed_empty"),
        (None, "present", "usable"),
        (None, "unavailable", "unavailable"),
        ("succeeded", "unknown", "usable"),
        ("partial", "present", "unavailable"),
        ("failed", "present", "failed"),
        ("running", "failed", "unknown"),
    ],
)
def test_quality_status_precedence_and_empty_providers(session, status, coverage, state):
    if status:
        session.add(
            SyncRun(
                provider_id="p",
                stream_code="any",
                status=status,
                started_at=STAMP,
                completed_at=None,
            )
        )
    session.add(
        CoverageInterval(
            provider_id="p",
            stream_code="any",
            metric_code="metric",
            interval_start=STAMP,
            interval_end=STAMP + timedelta(hours=1),
            resolution="day",
            status=coverage,
            calculation_rule_version="synthetic",
        )
    )
    session.commit()
    service = SleepAgreementReportService(session)
    result = service._source_data_quality([], DAY, DAY)
    assert result == REFERENCE["_source_data_quality"](service, [], DAY, DAY)
    assert next(row for row in result if row["provider_code"] == "garmin_connect")["state"] == state
    empty = next(row for row in result if row["provider_code"] == "empty")
    assert empty["state"] == "unknown"
    assert empty["coverage_facts"] == []
    assert empty["last_attempt"] is None


def test_baseline_candidates_preserve_every_state_date_fallback_order_and_cap(session):
    for i, (day, stamp, precision, projection, source) in enumerate(
        (
            (DAY, None, "date", "current", "s1"),
            (None, STAMP, "instant", "current", "s1"),
            (DAY, STAMP - timedelta(days=4), "instant", "current", "s1"),
            (DAY - timedelta(days=1), STAMP, "instant", "current", "s1"),
            (None, STAMP - timedelta(days=1), "instant", "current", "s1"),
            (None, None, "unknown", "current", "s1"),
            (DAY, None, "date", "retired", "s1"),
            (DAY, None, "date", "current", "s2"),
        )
    ):
        row = record(
            session,
            f"r-{i}",
            day=day,
            stamp=stamp,
            precision=precision,
            projection=projection,
            source=source,
        )
        for j, state in enumerate(("value", "null", "missing", "invalid")):
            # Different records let one registered metric cover every state.
            other = record(
                session,
                f"r-{i}-{j}",
                day=day,
                stamp=stamp,
                precision=precision,
                projection=projection,
                source=source,
            )
            session.add(
                GarminRecordMetric(
                    id=f"m-{i}-{j}",
                    record_id=other.id,
                    capability_code="stress",
                    metric_code="stress_daily_average",
                    field_path="synthetic",
                    state=state,
                    value_number=0 if state == "value" else None,
                )
            )
        session.add(
            GarminRecordMetric(
                id=f"noise-{i}",
                record_id=row.id,
                capability_code="stress",
                metric_code="stress_sample",
                field_path="synthetic",
                state="value",
                value_number=0,
            )
        )
    session.commit()
    query = baselines.GarminSeriesQuery(" stress_daily_average ", DAY, DAY, " s1 ")
    for cap in (None, 1, 2, baselines.MAX_SERIES_SELECTED_POINTS + 1):
        before = REFERENCE["_candidate_statement"](query)
        after = baselines._candidate_statement(query)
        if cap:
            before, after = before.limit(cap), after.limit(cap)

        def ids(rows):
            return [(metric.id, record.id, metric.state) for metric, record in rows]

        assert ids(session.execute(after)) == ids(session.execute(before))
    assert len(session.execute(baselines._candidate_statement(query)).all()) == 12


def test_optimized_reads_are_select_only(session):
    statements = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.lstrip().split()[0])

    event.listen(session.bind, "before_cursor_execute", capture)
    try:
        freshness._garmin_series_evidence_query(session, "p", "heart_rate")
        SleepAgreementReportService(session)._source_data_quality([], DAY, DAY)
        session.execute(
            baselines._candidate_statement(
                baselines.GarminSeriesQuery("stress_daily_average", DAY, DAY, "s1")
            )
        ).all()
    finally:
        event.remove(session.bind, "before_cursor_execute", capture)
    assert statements and set(statements) == {"SELECT"}


@pytest.mark.parametrize("value", [0, 25, None, "invalid-synthetic"])
def test_baseline_production_assembly_results_and_hash_are_unchanged(baselines_database, value):
    _paths, session, store = baselines_database
    for offset in range(5):
        payload = _stress_payload((DAY + timedelta(days=offset)).isoformat(), avg=value)
        outcome = _persist(session, store, payload)
    session.commit()
    kwargs = dict(
        metric_code="stress_daily_average",
        start_date=DAY,
        end_date=DAY + timedelta(days=4),
        garmin_source_id=outcome.records[0].garmin_source_id,
    )
    with patch.object(baselines, "_candidate_statement", REFERENCE["_candidate_statement"]):
        before = baselines.compute_garmin_scalar_series(session, **kwargs)
    after = baselines.compute_garmin_scalar_series(session, **kwargs)
    assert after.as_dict() == before.as_dict()
    assert after.result_hash == before.result_hash


def test_baseline_over_cap_fails_in_both_arms_before_assembly(session):
    for i in range(4):
        row = record(session, f"cap-{i}")
        session.add(
            GarminRecordMetric(
                id=f"metric-{i}",
                record_id=row.id,
                capability_code="stress",
                metric_code="stress_daily_average",
                field_path="synthetic",
                state="value",
                value_number=0,
            )
        )
    session.commit()
    kwargs = dict(
        metric_code="stress_daily_average", start_date=DAY, end_date=DAY, garmin_source_id="s1"
    )
    with patch.object(baselines, "MAX_SERIES_SELECTED_POINTS", 2):
        for query in (REFERENCE["_candidate_statement"], baselines._candidate_statement):
            with patch.object(baselines, "_candidate_statement", query):
                with pytest.raises(
                    baselines.GarminSeriesPointCapError, match="selected at least 3"
                ):
                    baselines.compute_garmin_scalar_series(session, **kwargs)


@pytest.mark.parametrize(
    "start, end",
    [
        ("2099-01-14 23:00:00", "2099-01-15 00:00:00"),
        ("2099-01-15T23:59:59", "2099-01-16T00:00:00"),
        ("2099-01-15T00:30:00+03:00", "2099-01-15T01:00:00+03:00"),
        ("20990115T000000", "20990115T010000"),
        ("2099-01-14T23:00:00-03:00", "2099-01-15T00:00:00-03:00"),
    ],
)
def test_quality_preserves_civil_date_for_valid_sqlite_datetime_encodings(session, start, end):
    # SQLAlchemy can read these valid SQLite datetime encodings too. Filtering
    # must reproduce Python .date(), without assuming six fractional digits,
    # a space separator, or converting civil dates to UTC.
    session.add(
        CoverageInterval(
            id="encoded",
            provider_id="p",
            stream_code="any",
            metric_code="metric",
            interval_start=STAMP,
            interval_end=STAMP + timedelta(hours=1),
            resolution="day",
            status="unknown",
            calculation_rule_version="synthetic",
        )
    )
    session.commit()
    session.execute(
        text(
            "UPDATE coverage_intervals SET interval_start=:start, interval_end=:end "
            "WHERE id='encoded'"
        ),
        dict(start=start, end=end),
    )
    session.commit()
    session.expire_all()
    service = SleepAgreementReportService(session)
    before = REFERENCE["_source_data_quality"](service, [], DAY, DAY)
    after = service._source_data_quality([], DAY, DAY)
    assert after == before
    assert (
        len(
            next(row for row in after if row["provider_code"] == "garmin_connect")["coverage_facts"]
        )
        == 1
    )


@pytest.mark.parametrize(
    "start, end",
    [
        ("2099-01-01Tinvalid", "2099-01-01Tinvalid2"),
        ("2099-02-30 00:00:00", "2099-02-30 01:00:00"),
    ],
)
def test_quality_malformed_datetime_outside_window_still_fails_closed(session, start, end):
    session.add(
        CoverageInterval(
            id="malformed",
            provider_id="p",
            stream_code="any",
            metric_code="metric",
            interval_start=STAMP,
            interval_end=STAMP + timedelta(hours=1),
            resolution="day",
            status="present",
            calculation_rule_version="synthetic",
        )
    )
    session.commit()
    session.execute(
        text(
            "UPDATE coverage_intervals SET interval_start=:start, interval_end=:end "
            "WHERE id='malformed'"
        ),
        dict(start=start, end=end),
    )
    session.commit()
    session.expire_all()
    service = SleepAgreementReportService(session)
    for function in (
        REFERENCE["_source_data_quality"],
        SleepAgreementReportService._source_data_quality,
    ):
        with pytest.raises(ValueError):
            function(service, [], DAY, DAY)
