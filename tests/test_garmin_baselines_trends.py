"""Synthetic regressions for R03-01 Garmin scalar baselines and trends (#67)."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from healthcheck.analytics.garmin_baselines import (
    MAX_SERIES_CALENDAR_DAYS,
    R03_01_ALGORITHM,
    R03_01_RULE_VERSION,
    GarminScalarAnalyticsError,
    GarminSeriesWindowError,
    compute_garmin_scalar_series,
    modified_robust_z,
    personal_midrank_percentile,
    theil_sen_slope_per_day,
    type7_quantile,
)
from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
from healthcheck.db.models import GarminSourceRecord
from healthcheck.db.repositories import repositories_for
from healthcheck.garmin.analytic_contract import (
    AggregateKind,
    AnalyticInputAssemblyError,
    build_analytic_input_from_storage,
)
from healthcheck.garmin.normalization import normalize_garmin_payload
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.runtime import prepare_runtime

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "garmin"


@pytest.fixture
def baselines_database(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            yield paths, session, ContentAddressedGarminPayloadStore(paths.root / "artifacts")
    finally:
        engine.dispose()


def _stress_payload(
    day: str,
    *,
    avg: int | float | None = 25,
    maximum: int | float | None = 80,
    sample: int | float | None = 40,
    spo2_avg: int | float | None = 98,
    spo2_trail: int | float | None = 97,
    spo2_sample: int | float | None = 96,
    fixture_suffix: str = "",
    extra_payload: dict | None = None,
) -> dict:
    payload: dict = {
        "calendarDate": day,
        "heartRate": 70,
        "bodyBattery": 50,
        "respiration": 14,
    }
    if avg is not None:
        payload["avgStressLevel"] = avg
    if maximum is not None:
        payload["maxStressLevel"] = maximum
    if sample is not None:
        payload["stress"] = sample
    if spo2_avg is not None:
        payload["averageSpO2"] = spo2_avg
    if spo2_trail is not None:
        payload["lastSevenDaysAvgSpO2"] = spo2_trail
    if spo2_sample is not None:
        payload["spo2"] = spo2_sample
    if extra_payload:
        payload.update(extra_payload)
    return {
        "fixture_contract_version": "r02-garmin-capability-fixture-v1",
        "fixture_id": f"synthetic-r03-01-{day}{fixture_suffix}",
        "source_kind": "synthetic",
        "provider_code": "garmin_connect",
        "stream_code": "intraday",
        "device": {
            "attributed": True,
            "code": "garmin_vivoactive_5",
            "model": "Vivoactive 5",
        },
        "payload": payload,
    }


def _persist(session, store, payload: dict, *, received_at: datetime | None = None):
    result = normalize_garmin_payload(payload)
    assert result.records, result.diagnostics
    outcome = GarminPersistenceRepository(session, payload_store=store).persist_result(
        result,
        payload=payload,
        received_at=received_at or datetime(2099, 1, 1, 12, tzinfo=UTC),
        source_contract_version=payload.get("fixture_contract_version"),
    )
    session.flush()
    return outcome


def _source_id(session) -> str:
    from sqlalchemy import select

    row = session.scalars(select(GarminSourceRecord)).first()
    assert row is not None
    return row.garmin_source_id


def test_type7_quantiles_and_midrank_percentile_with_ties() -> None:
    values = [1.0, 2.0, 2.0, 3.0, 10.0]
    assert type7_quantile(values, 0.10) == pytest.approx(1.4)
    assert type7_quantile(values, 0.25) == pytest.approx(2.0)
    assert type7_quantile(values, 0.50) == pytest.approx(2.0)
    assert type7_quantile(values, 0.75) == pytest.approx(3.0)
    assert type7_quantile(values, 0.90) == pytest.approx(7.2)
    # latest=2 with ties: less=1, equal=2, n=5 -> 100*(1+1)/5 = 40
    assert personal_midrank_percentile(values, 2.0) == pytest.approx(40.0)
    assert personal_midrank_percentile(values, 10.0) == pytest.approx(90.0)


def test_theil_sen_irregular_dates_ignores_zero_delta() -> None:
    points = [
        (date(2099, 1, 1), 10.0),
        (date(2099, 1, 1), 12.0),  # same date -> ignored in pairs with each other
        (date(2099, 1, 4), 16.0),
        (date(2099, 1, 10), 28.0),
    ]
    slope, pair_count = theil_sen_slope_per_day(points)
    # pairs with nonzero delta: (1,16)/3, (1,28)/9, (12,16)/3, (12,28)/9, (16,28)/6
    assert pair_count == 5
    assert slope == pytest.approx(2.0)


def test_mad_zero_gate_and_high_deviation_example() -> None:
    assert modified_robust_z([5.0, 5.0, 5.0, 5.0, 5.0], 5.0) is None
    sample = [10.0, 11.0, 12.0, 13.0, 14.0, 100.0]
    z_score, median, mad = modified_robust_z(sample, 100.0)
    assert median == pytest.approx(12.5)
    assert mad > 0
    assert abs(z_score) >= 3.5


def test_stable_hash_and_no_aggregate_substitution(baselines_database) -> None:
    _paths, session, store = baselines_database
    days = [
        ("2099-04-01", 10),
        ("2099-04-02", 20),
        ("2099-04-03", 30),
        ("2099-04-05", 40),
        ("2099-04-08", 50),
    ]
    for index, (day, avg) in enumerate(days):
        _persist(
            session,
            store,
            _stress_payload(day, avg=avg, maximum=avg + 40),
            received_at=datetime(2099, 4, 10, index, tzinfo=UTC),
        )
    session.commit()
    source_id = _source_id(session)

    first = compute_garmin_scalar_series(
        session,
        metric_code="stress_daily_average",
        start_date=date(2099, 4, 1),
        end_date=date(2099, 4, 10),
        garmin_source_id=source_id,
    )
    second = compute_garmin_scalar_series(
        session,
        metric_code="stress_daily_average",
        start_date=date(2099, 4, 1),
        end_date=date(2099, 4, 10),
        garmin_source_id=source_id,
    )
    assert first.result_hash == second.result_hash
    assert first.as_dict()["result_hash"] == first.result_hash
    assert first.algorithm == R03_01_ALGORITHM
    assert first.rule_version == R03_01_RULE_VERSION
    assert [point.value for point in first.points] == [10, 20, 30, 40, 50]
    assert [point.analytic_date for point in first.points] == [
        "2099-04-01",
        "2099-04-02",
        "2099-04-03",
        "2099-04-05",
        "2099-04-08",
    ]

    maximum_series = compute_garmin_scalar_series(
        session,
        metric_code="stress_daily_maximum",
        start_date=date(2099, 4, 1),
        end_date=date(2099, 4, 10),
        garmin_source_id=source_id,
    )
    assert maximum_series.metric_definition.aggregate_kind is AggregateKind.DAILY_MAXIMUM
    assert [point.value for point in maximum_series.points] == [50, 60, 70, 80, 90]
    assert maximum_series.result_hash != first.result_hash

    # Average series never silently becomes maximum values.
    assert first.points[0].value != maximum_series.points[0].value


def test_local_only_remains_local_without_invented_utc(baselines_database) -> None:
    _paths, session, store = baselines_database
    payload = _stress_payload(
        "2099-03-08",
        avg=22,
        extra_payload={"timestamp": "2099-03-08T02:30:00"},
    )
    # Force local-only sample path via normalize of a dedicated local sample fixture shape.
    outcome = _persist(session, store, payload)
    session.commit()
    source_id = outcome.records[0].garmin_source_id
    series = compute_garmin_scalar_series(
        session,
        metric_code="stress_daily_average",
        start_date=date(2099, 3, 1),
        end_date=date(2099, 3, 10),
        garmin_source_id=source_id,
    )
    assert len(series.points) == 1
    point = series.points[0]
    assert point.analytic_date == "2099-03-08"
    assert point.measured_at_utc is None
    assert point.zone_policy in {"local_date_only", "local_unknown_zone"}
    dumped = json.dumps(point.as_dict())
    assert "Z" not in dumped
    assert "+00:00" not in dumped
    frozen = series.frozen_inputs[0]
    assert frozen["temporal"]["measured_at_utc"] is None
    assert frozen["temporal"]["zone_policy"] in {"local_date_only", "local_unknown_zone"}


def test_missing_null_zero_invalid_not_computable_distinct(baselines_database) -> None:
    _paths, session, store = baselines_database
    # zero average
    _persist(
        session,
        store,
        _stress_payload("2099-05-01", avg=0, maximum=10, sample=0),
        received_at=datetime(2099, 5, 10, 1, tzinfo=UTC),
    )
    # null stress sample day still has average
    _persist(
        session,
        store,
        _stress_payload("2099-05-02", avg=15, sample=None, maximum=40),
        received_at=datetime(2099, 5, 10, 2, tzinfo=UTC),
    )
    # missing average, only maximum present
    _persist(
        session,
        store,
        _stress_payload("2099-05-03", avg=None, maximum=77, sample=12),
        received_at=datetime(2099, 5, 10, 3, tzinfo=UTC),
    )
    session.commit()
    source_id = _source_id(session)

    average = compute_garmin_scalar_series(
        session,
        metric_code="stress_daily_average",
        start_date=date(2099, 5, 1),
        end_date=date(2099, 5, 3),
        garmin_source_id=source_id,
    )
    by_date = {point.analytic_date: point for point in average.points}
    assert by_date["2099-05-01"].status == "zero"
    assert by_date["2099-05-01"].value == 0
    assert by_date["2099-05-01"].is_zero is True
    assert by_date["2099-05-02"].status == "usable"
    assert by_date["2099-05-02"].value == 15
    assert by_date["2099-05-03"].status == "missing"
    assert by_date["2099-05-03"].value is None
    # Zero participates numerically.
    assert average.availability.zero_count == 1
    assert average.availability.usable_count == 2
    assert average.baseline.available is True
    assert average.baseline.count == 2
    assert average.baseline.mean == pytest.approx(7.5)

    with pytest.raises(GarminScalarAnalyticsError, match="collection-valued"):
        compute_garmin_scalar_series(
            session,
            metric_code="sleep_stages",
            start_date=date(2099, 5, 1),
            end_date=date(2099, 5, 3),
            garmin_source_id=source_id,
        )


def test_insufficient_sample_gates(baselines_database) -> None:
    _paths, session, store = baselines_database
    _persist(session, store, _stress_payload("2099-06-01", avg=10))
    _persist(
        session,
        store,
        _stress_payload("2099-06-02", avg=20),
        received_at=datetime(2099, 6, 3, tzinfo=UTC),
    )
    session.commit()
    source_id = _source_id(session)
    series = compute_garmin_scalar_series(
        session,
        metric_code="stress_daily_average",
        start_date=date(2099, 6, 1),
        end_date=date(2099, 6, 10),
        garmin_source_id=source_id,
    )
    assert series.availability.usable_count == 2
    assert series.personal_percentile.available is False
    assert series.personal_percentile.reason == "insufficient_usable_values"
    assert series.personal_percentile.label == "personal_window_percentile"
    assert series.deviation.available is False
    assert series.deviation.reason == "insufficient_usable_values"
    assert series.trend.available is False
    assert series.trend.reason == "insufficient_temporal_sample"


def test_trend_deviation_and_baseline_on_irregular_window(baselines_database) -> None:
    _paths, session, store = baselines_database
    # Five usable + one extreme for deviation flag.
    series_days = [
        ("2099-07-01", 10),
        ("2099-07-02", 11),
        ("2099-07-04", 12),
        ("2099-07-07", 13),
        ("2099-07-10", 14),
        ("2099-07-11", 100),
    ]
    for index, (day, avg) in enumerate(series_days):
        _persist(
            session,
            store,
            _stress_payload(day, avg=avg),
            received_at=datetime(2099, 7, 15, index, tzinfo=UTC),
        )
    session.commit()
    source_id = _source_id(session)
    series = compute_garmin_scalar_series(
        session,
        metric_code="stress_daily_average",
        start_date=date(2099, 7, 1),
        end_date=date(2099, 7, 15),
        garmin_source_id=source_id,
    )
    assert series.trend.available is True
    assert series.trend.slope_per_day is not None
    assert series.trend.distinct_analytic_dates == 6
    assert "improving" not in json.dumps(series.trend.as_dict())
    assert "worsening" not in json.dumps(series.trend.as_dict())
    assert series.personal_percentile.available is True
    assert series.deviation.available is True
    assert series.deviation.personal_baseline_deviation is True
    assert abs(series.deviation.robust_z or 0) >= 3.5
    assert series.deviation.label == "personal_baseline_deviation"
    assert series.baseline.p50 == series.baseline.median


def test_duplicate_daily_rows_are_not_silently_averaged(baselines_database) -> None:
    _paths, session, store = baselines_database
    _persist(
        session,
        store,
        _stress_payload("2099-08-01", avg=10, fixture_suffix="-a", extra_payload={"note": "a"}),
        received_at=datetime(2099, 8, 2, 1, tzinfo=UTC),
    )
    _persist(
        session,
        store,
        _stress_payload("2099-08-01", avg=90, fixture_suffix="-b", extra_payload={"note": "b"}),
        received_at=datetime(2099, 8, 2, 2, tzinfo=UTC),
    )
    _persist(
        session,
        store,
        _stress_payload("2099-08-02", avg=20, fixture_suffix="-c"),
        received_at=datetime(2099, 8, 2, 3, tzinfo=UTC),
    )
    session.commit()
    source_id = _source_id(session)
    series = compute_garmin_scalar_series(
        session,
        metric_code="stress_daily_average",
        start_date=date(2099, 8, 1),
        end_date=date(2099, 8, 3),
        garmin_source_id=source_id,
    )
    day_one = [point for point in series.points if point.analytic_date == "2099-08-01"]
    assert len(day_one) == 2
    assert all(point.status == "excluded" for point in day_one)
    assert all(point.exclusion_reason == "ambiguous_daily_aggregate" for point in day_one)
    assert all(point.value is None for point in day_one)
    # Surviving unambiguous day remains usable; no averaged 50.
    usable_values = [point.value for point in series.points if point.status == "usable"]
    assert usable_values == [20]
    assert 50 not in usable_values
    assert any(
        item.reason_code == "ambiguous_daily_aggregate" for item in series.availability.exclusions
    )


def test_correction_keeps_old_result_immutable_and_changes_rebuild(
    baselines_database,
) -> None:
    _paths, session, store = baselines_database
    first_payload = json.loads((FIXTURE_ROOT / "sleep.json").read_text(encoding="utf-8"))
    first_payload["payload"]["id"] = "sleep-session-r03-01"
    first = _persist(
        session,
        store,
        first_payload,
        received_at=datetime(2099, 9, 2, tzinfo=UTC),
    )
    session.commit()
    source_id = first.records[0].garmin_source_id
    original = compute_garmin_scalar_series(
        session,
        metric_code="sleep_duration_seconds",
        start_date=date(2099, 1, 1),
        end_date=date(2099, 1, 3),
        garmin_source_id=source_id,
    )
    frozen = copy.deepcopy(original.as_dict())
    assert frozen["points"][0]["value"] == 28800
    original_hash = frozen["result_hash"]
    original_manifest = frozen["frozen_inputs"][0]["manifest_hash"]
    original_content = frozen["frozen_inputs"][0]["evidence"]["content_hash"]

    corrected = json.loads((FIXTURE_ROOT / "sleep.json").read_text(encoding="utf-8"))
    corrected["payload"]["id"] = "sleep-session-r03-01"
    corrected["fixture_id"] = "synthetic-vivoactive-5-sleep-001-corrected"
    corrected["payload"]["dailySleepDTO"]["sleepTimeSeconds"] = 30000
    second = _persist(
        session,
        store,
        corrected,
        received_at=datetime(2099, 9, 3, tzinfo=UTC),
    )
    session.commit()
    assert second.updated_count == 1
    assert second.records[0].id == first.records[0].id
    rebuilt = compute_garmin_scalar_series(
        session,
        metric_code="sleep_duration_seconds",
        start_date=date(2099, 1, 1),
        end_date=date(2099, 1, 3),
        garmin_source_id=source_id,
    )
    assert rebuilt.points[0].value == 30000
    assert rebuilt.result_hash != original_hash
    assert rebuilt.frozen_inputs[0]["manifest_hash"] != original_manifest
    assert rebuilt.frozen_inputs[0]["evidence"]["content_hash"] != original_content

    # Already serialized old result stays unchanged.
    assert frozen["result_hash"] == original_hash
    assert frozen["points"][0]["value"] == 28800
    assert frozen["frozen_inputs"][0]["selected"]["value"] == 28800
    assert frozen["frozen_inputs"][0]["evidence"]["content_hash"] == original_content


def test_provenance_fail_closed_through_storage_assembler(baselines_database) -> None:
    _paths, session, store = baselines_database
    fixture_value = json.loads((FIXTURE_ROOT / "sleep.json").read_text(encoding="utf-8"))
    payload_bytes = (FIXTURE_ROOT / "sleep.json").read_bytes()
    result_v1 = normalize_garmin_payload(fixture_value)
    repository = GarminPersistenceRepository(session, payload_store=store)
    source = repository.sources.get_or_create(result_v1.source)
    provenance = repositories_for(session)
    first_run = provenance.sync.create_run(
        provider_id=source.provider_id,
        acquisition_source_id=source.acquisition_source_id,
        stream_code="sleep",
        requested_start=datetime(2099, 1, 1, tzinfo=UTC),
        requested_end=datetime(2099, 1, 3, tzinfo=UTC),
    )
    second_run = provenance.sync.create_run(
        provider_id=source.provider_id,
        acquisition_source_id=source.acquisition_source_id,
        stream_code="sleep",
        requested_start=datetime(2099, 1, 2, tzinfo=UTC),
        requested_end=datetime(2099, 1, 4, tzinfo=UTC),
    )
    first = repository.persist_result(
        result_v1,
        payload=payload_bytes,
        source_filename="sleep-window-1.json",
        received_at=datetime(2099, 1, 3, 12, tzinfo=UTC),
        source_window_start_utc=datetime(2099, 1, 1, tzinfo=UTC),
        source_window_end_utc=datetime(2099, 1, 3, tzinfo=UTC),
        sync_run_id=first_run.id,
        source_contract_version=fixture_value["fixture_contract_version"],
    )
    session.commit()
    observation_a = first.observation.id
    result_v2 = replace(result_v1, contract_version="r02-garmin-normalization-contract-v2")
    second = repository.persist_result(
        result_v2,
        payload=payload_bytes,
        source_filename="sleep-window-2.json",
        received_at=datetime(2099, 1, 4, 12, tzinfo=UTC),
        source_window_start_utc=datetime(2099, 1, 2, tzinfo=UTC),
        source_window_end_utc=datetime(2099, 1, 4, tzinfo=UTC),
        sync_run_id=second_run.id,
        source_contract_version=fixture_value["fixture_contract_version"],
    )
    session.commit()
    record = session.get(GarminSourceRecord, first.records[0].id)
    assert record is not None
    assert record.ingest_event_id == second.ingest_event_id

    with pytest.raises(AnalyticInputAssemblyError, match="ingest event"):
        build_analytic_input_from_storage(
            session,
            record_id=record.id,
            metric_code="sleep_duration_seconds",
            observation_id=observation_a,
            operational_surface_present=True,
        )

    # Series path still uses the fail-closed assembler for current rows.
    series = compute_garmin_scalar_series(
        session,
        metric_code="sleep_duration_seconds",
        start_date=date(2099, 1, 1),
        end_date=date(2099, 1, 3),
        garmin_source_id=record.garmin_source_id,
    )
    assert series.availability.usable_count >= 1
    assert all(item.get("manifest_hash") for item in series.frozen_inputs)


def test_oversized_window_is_rejected(baselines_database) -> None:
    _paths, session, store = baselines_database
    outcome = _persist(session, store, _stress_payload("2099-01-01", avg=10))
    session.commit()
    source_id = outcome.records[0].garmin_source_id
    start = date(2099, 1, 1)
    end = start + timedelta(days=MAX_SERIES_CALENDAR_DAYS)  # 401 inclusive days
    assert (end - start).days + 1 == MAX_SERIES_CALENDAR_DAYS + 1
    with pytest.raises(GarminSeriesWindowError, match="max allowed"):
        compute_garmin_scalar_series(
            session,
            metric_code="stress_daily_average",
            start_date=start,
            end_date=end,
            garmin_source_id=source_id,
        )


def test_no_missing_calendar_day_without_coverage_evidence(baselines_database) -> None:
    _paths, session, store = baselines_database
    _persist(session, store, _stress_payload("2099-10-01", avg=12))
    _persist(
        session,
        store,
        _stress_payload("2099-10-03", avg=18),
        received_at=datetime(2099, 10, 4, tzinfo=UTC),
    )
    session.commit()
    source_id = _source_id(session)
    series = compute_garmin_scalar_series(
        session,
        metric_code="stress_daily_average",
        start_date=date(2099, 10, 1),
        end_date=date(2099, 10, 5),
        garmin_source_id=source_id,
    )
    dates = [point.analytic_date for point in series.points]
    assert dates == ["2099-10-01", "2099-10-03"]
    assert "2099-10-02" not in dates
    assert series.availability.missing_count == 0


def test_trailing_spo2_not_substituted_for_daily(baselines_database) -> None:
    _paths, session, store = baselines_database
    payload = _stress_payload("2099-11-01", avg=10, spo2_avg=None, spo2_trail=97, spo2_sample=96)
    _persist(session, store, payload)
    session.commit()
    source_id = _source_id(session)
    daily = compute_garmin_scalar_series(
        session,
        metric_code="spo2_daily_average",
        start_date=date(2099, 11, 1),
        end_date=date(2099, 11, 1),
        garmin_source_id=source_id,
    )
    trailing = compute_garmin_scalar_series(
        session,
        metric_code="spo2_trailing_7d_average",
        start_date=date(2099, 11, 1),
        end_date=date(2099, 11, 1),
        garmin_source_id=source_id,
    )
    assert daily.points[0].status == "missing"
    assert daily.points[0].value is None
    assert trailing.points[0].status == "usable"
    assert trailing.points[0].value == 97
