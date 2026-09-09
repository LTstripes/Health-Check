"""Synthetic regressions for R03-03 lagged cross-metric associations (#71)."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from healthcheck.analytics.garmin_baselines import GarminSeriesWindowError
from healthcheck.analytics.garmin_lagged_associations import (
    MAX_LAG_COUNT,
    MAX_LAG_DAYS,
    R03_03_ALGORITHM,
    R03_03_RULE_VERSION,
    GarminLaggedAssociationError,
    GarminLaggedAssociationQuery,
    analyze_garmin_lagged_associations,
    compute_garmin_lagged_associations,
    metric_eligible_for_lagged_association,
    spearman_midranks,
    spearman_rho,
)
from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
from healthcheck.db.models import GarminSourceRecord
from healthcheck.db.repositories import repositories_for
from healthcheck.garmin.analytic_contract import (
    AnalyticInputAssemblyError,
    build_analytic_input_from_storage,
)
from healthcheck.garmin.normalization import normalize_garmin_payload
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.runtime import prepare_runtime

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "garmin"


@pytest.fixture
def assoc_database(tmp_path):
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
        "fixture_id": f"synthetic-r03-03-{day}{fixture_suffix}",
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
    row = session.scalars(select(GarminSourceRecord)).first()
    assert row is not None
    return row.garmin_source_id


def _persist_days(session, store, rows: list[tuple[str, int | float, int | float]]) -> str:
    """Persist stress avg + spo2 avg pairs: (day, stress_avg, spo2_avg)."""

    source_id = None
    for index, (day, stress_avg, spo2_avg) in enumerate(rows):
        outcome = _persist(
            session,
            store,
            _stress_payload(
                day,
                avg=stress_avg,
                spo2_avg=spo2_avg,
                fixture_suffix=f"-row-{index}",
            ),
            received_at=datetime(2099, 6, 1, index % 24, tzinfo=UTC),
        )
        source_id = outcome.records[0].garmin_source_id
    session.commit()
    assert source_id is not None
    return source_id


def test_spearman_midranks_and_ties_unit() -> None:
    ranks = spearman_midranks([1.0, 2.0, 2.0, 4.0])
    assert ranks == [1.0, 2.5, 2.5, 4.0]
    # Perfect positive association
    assert spearman_rho([1, 2, 3, 4, 5], [2, 4, 6, 8, 10]) == pytest.approx(1.0)
    # Perfect negative
    assert spearman_rho([1, 2, 3, 4, 5], [10, 8, 6, 4, 2]) == pytest.approx(-1.0)
    # Constant -> not computable
    assert spearman_rho([3, 3, 3, 3, 3], [1, 2, 3, 4, 5]) is None
    assert spearman_rho([1, 2, 3, 4, 5], [7, 7, 7, 7, 7]) is None


def test_lag_direction_k0_k1_k2(assoc_database) -> None:
    _paths, session, store = assoc_database
    # X stress: 10,20,30,40,50,60,70 on consecutive days
    # Y spo2: same days 90..96 so lag0 positive; shift pattern for lag checks
    rows = [
        ("2099-07-01", 10, 90),
        ("2099-07-02", 20, 91),
        ("2099-07-03", 30, 92),
        ("2099-07-04", 40, 93),
        ("2099-07-05", 50, 94),
        ("2099-07-06", 60, 95),
        ("2099-07-07", 70, 96),
    ]
    source_id = _persist_days(session, store, rows)
    result = compute_garmin_lagged_associations(
        session,
        garmin_source_id=source_id,
        x_metric_code="stress_daily_average",
        y_metric_code="spo2_daily_average",
        start_date=date(2099, 7, 1),
        end_date=date(2099, 7, 7),
        lag_days=[0, 1, 2],
    )
    assert [item.lag_days for item in result.lags] == [0, 1, 2]
    lag0 = result.lags[0]
    assert lag0.status == "association_available"
    assert lag0.n == 7
    assert [(p.x_analytic_date, p.y_analytic_date) for p in lag0.pairing_map] == [
        ("2099-07-01", "2099-07-01"),
        ("2099-07-02", "2099-07-02"),
        ("2099-07-03", "2099-07-03"),
        ("2099-07-04", "2099-07-04"),
        ("2099-07-05", "2099-07-05"),
        ("2099-07-06", "2099-07-06"),
        ("2099-07-07", "2099-07-07"),
    ]
    lag1 = result.lags[1]
    assert [(p.x_analytic_date, p.y_analytic_date) for p in lag1.pairing_map] == [
        ("2099-07-01", "2099-07-02"),
        ("2099-07-02", "2099-07-03"),
        ("2099-07-03", "2099-07-04"),
        ("2099-07-04", "2099-07-05"),
        ("2099-07-05", "2099-07-06"),
        ("2099-07-06", "2099-07-07"),
    ]
    assert lag1.n == 6
    lag2 = result.lags[2]
    assert [(p.x_analytic_date, p.y_analytic_date) for p in lag2.pairing_map] == [
        ("2099-07-01", "2099-07-03"),
        ("2099-07-02", "2099-07-04"),
        ("2099-07-03", "2099-07-05"),
        ("2099-07-04", "2099-07-06"),
        ("2099-07-05", "2099-07-07"),
    ]
    assert lag2.n == 5
    # k>0 means X precedes Y
    assert all(
        date.fromisoformat(p.y_analytic_date) - date.fromisoformat(p.x_analytic_date)
        == timedelta(days=1)
        for p in lag1.pairing_map
    )


def test_lag_bounds_duplicate_empty_rejects(assoc_database) -> None:
    _paths, session, store = assoc_database
    source_id = _persist_days(
        session,
        store,
        [(f"2099-08-{day:02d}", 10 + day, 90 + day) for day in range(1, 8)],
    )
    with pytest.raises(GarminLaggedAssociationError) as empty:
        compute_garmin_lagged_associations(
            session,
            garmin_source_id=source_id,
            x_metric_code="stress_daily_average",
            y_metric_code="spo2_daily_average",
            start_date=date(2099, 8, 1),
            end_date=date(2099, 8, 7),
            lag_days=[],
        )
    assert empty.value.reason_code == "empty_lag_days"

    with pytest.raises(GarminLaggedAssociationError) as dup:
        compute_garmin_lagged_associations(
            session,
            garmin_source_id=source_id,
            x_metric_code="stress_daily_average",
            y_metric_code="spo2_daily_average",
            start_date=date(2099, 8, 1),
            end_date=date(2099, 8, 7),
            lag_days=[0, 1, 1],
        )
    assert dup.value.reason_code == "duplicate_lag_days"

    with pytest.raises(GarminLaggedAssociationError) as out:
        compute_garmin_lagged_associations(
            session,
            garmin_source_id=source_id,
            x_metric_code="stress_daily_average",
            y_metric_code="spo2_daily_average",
            start_date=date(2099, 8, 1),
            end_date=date(2099, 8, 7),
            lag_days=[15],
        )
    assert out.value.reason_code == "lag_out_of_range"

    with pytest.raises(GarminLaggedAssociationError) as neg:
        compute_garmin_lagged_associations(
            session,
            garmin_source_id=source_id,
            x_metric_code="stress_daily_average",
            y_metric_code="spo2_daily_average",
            start_date=date(2099, 8, 1),
            end_date=date(2099, 8, 7),
            lag_days=[-1],
        )
    assert neg.value.reason_code == "lag_out_of_range"

    with pytest.raises(GarminLaggedAssociationError) as many:
        compute_garmin_lagged_associations(
            session,
            garmin_source_id=source_id,
            x_metric_code="stress_daily_average",
            y_metric_code="spo2_daily_average",
            start_date=date(2099, 8, 1),
            end_date=date(2099, 8, 7),
            lag_days=list(range(MAX_LAG_COUNT + 1)),
        )
    assert many.value.reason_code == "too_many_lag_days"
    assert MAX_LAG_DAYS == 14


def test_distinct_and_unknown_metric_rejects(assoc_database) -> None:
    _paths, session, store = assoc_database
    source_id = _persist_days(
        session,
        store,
        [(f"2099-08-{day:02d}", 10 + day, 90) for day in range(1, 8)],
    )
    with pytest.raises(GarminLaggedAssociationError) as same:
        compute_garmin_lagged_associations(
            session,
            garmin_source_id=source_id,
            x_metric_code="stress_daily_average",
            y_metric_code="stress_daily_average",
            start_date=date(2099, 8, 1),
            end_date=date(2099, 8, 7),
            lag_days=[0],
        )
    assert same.value.reason_code == "metrics_must_be_distinct"

    with pytest.raises(GarminLaggedAssociationError) as unknown:
        compute_garmin_lagged_associations(
            session,
            garmin_source_id=source_id,
            x_metric_code="hrv_rmssd",
            y_metric_code="spo2_daily_average",
            start_date=date(2099, 8, 1),
            end_date=date(2099, 8, 7),
            lag_days=[0],
        )
    assert unknown.value.reason_code == "unknown_metric_code"
    ok, reason = metric_eligible_for_lagged_association("resting_heart_rate")
    assert ok is False
    assert reason == "unknown_metric_code"


def test_sample_collection_activity_rejects(assoc_database) -> None:
    _paths, session, store = assoc_database
    source_id = _persist_days(
        session,
        store,
        [(f"2099-08-{day:02d}", 10 + day, 90) for day in range(1, 8)],
    )
    with pytest.raises(GarminLaggedAssociationError) as sample:
        compute_garmin_lagged_associations(
            session,
            garmin_source_id=source_id,
            x_metric_code="stress_sample",
            y_metric_code="spo2_daily_average",
            start_date=date(2099, 8, 1),
            end_date=date(2099, 8, 7),
            lag_days=[0],
        )
    assert sample.value.reason_code == "sample_metric_not_supported"

    with pytest.raises(GarminLaggedAssociationError) as collection:
        compute_garmin_lagged_associations(
            session,
            garmin_source_id=source_id,
            x_metric_code="sleep_stages",
            y_metric_code="spo2_daily_average",
            start_date=date(2099, 8, 1),
            end_date=date(2099, 8, 7),
            lag_days=[0],
        )
    assert collection.value.reason_code == "collection_valued_not_scalar"

    with pytest.raises(GarminLaggedAssociationError) as activity:
        compute_garmin_lagged_associations(
            session,
            garmin_source_id=source_id,
            x_metric_code="stress_daily_average",
            y_metric_code="distance_meters",
            start_date=date(2099, 8, 1),
            end_date=date(2099, 8, 7),
            lag_days=[0],
        )
    assert activity.value.reason_code == "activity_session_metric_not_supported"


def test_spearman_ties_stable_hash_and_association_signs(assoc_database) -> None:
    _paths, session, store = assoc_database
    # Positive monotone with a tie in X
    pos_rows = [
        ("2099-09-01", 10, 90),
        ("2099-09-02", 20, 91),
        ("2099-09-03", 20, 92),  # tie in X
        ("2099-09-04", 40, 93),
        ("2099-09-05", 50, 94),
        ("2099-09-06", 60, 95),
    ]
    source_id = _persist_days(session, store, pos_rows)
    first = compute_garmin_lagged_associations(
        session,
        garmin_source_id=source_id,
        x_metric_code="stress_daily_average",
        y_metric_code="spo2_daily_average",
        start_date=date(2099, 9, 1),
        end_date=date(2099, 9, 6),
        lag_days=[0],
    )
    second = compute_garmin_lagged_associations(
        session,
        garmin_source_id=source_id,
        x_metric_code="stress_daily_average",
        y_metric_code="spo2_daily_average",
        start_date=date(2099, 9, 1),
        end_date=date(2099, 9, 6),
        lag_days=[0],
    )
    assert first.result_hash == second.result_hash
    assert first.algorithm == R03_03_ALGORITHM
    assert first.rule_version == R03_03_RULE_VERSION
    assert first.lags[0].status == "association_available"
    assert first.lags[0].rho is not None
    assert first.lags[0].rho > 0.9

    # Negative association on a fresh source window via spo2 decreasing
    neg_rows = [
        ("2099-10-01", 10, 96),
        ("2099-10-02", 20, 95),
        ("2099-10-03", 30, 94),
        ("2099-10-04", 40, 93),
        ("2099-10-05", 50, 92),
        ("2099-10-06", 60, 91),
    ]
    for index, (day, stress_avg, spo2_avg) in enumerate(neg_rows):
        _persist(
            session,
            store,
            _stress_payload(day, avg=stress_avg, spo2_avg=spo2_avg, fixture_suffix=f"-neg-{index}"),
            received_at=datetime(2099, 10, 10, index, tzinfo=UTC),
        )
    session.commit()
    neg = compute_garmin_lagged_associations(
        session,
        garmin_source_id=source_id,
        x_metric_code="stress_daily_average",
        y_metric_code="spo2_daily_average",
        start_date=date(2099, 10, 1),
        end_date=date(2099, 10, 6),
        lag_days=[0],
    )
    assert neg.lags[0].status == "association_available"
    assert neg.lags[0].rho is not None
    assert neg.lags[0].rho < -0.9

    # Near-zero / tied association: Y constant ranks after midrank still constant
    # Use shuffled Y that yields rho near 0
    zero_rows = [
        ("2099-11-01", 10, 93),
        ("2099-11-02", 20, 91),
        ("2099-11-03", 30, 95),
        ("2099-11-04", 40, 90),
        ("2099-11-05", 50, 94),
        ("2099-11-06", 60, 92),
    ]
    for index, (day, stress_avg, spo2_avg) in enumerate(zero_rows):
        _persist(
            session,
            store,
            _stress_payload(day, avg=stress_avg, spo2_avg=spo2_avg, fixture_suffix=f"-z-{index}"),
            received_at=datetime(2099, 11, 10, index, tzinfo=UTC),
        )
    session.commit()
    zeroish = compute_garmin_lagged_associations(
        session,
        garmin_source_id=source_id,
        x_metric_code="stress_daily_average",
        y_metric_code="spo2_daily_average",
        start_date=date(2099, 11, 1),
        end_date=date(2099, 11, 6),
        lag_days=[0],
    )
    assert zeroish.lags[0].status == "association_available"
    assert zeroish.lags[0].rho is not None
    assert abs(zeroish.lags[0].rho) < 0.3


def test_n_less_than_five_not_computable(assoc_database) -> None:
    _paths, session, store = assoc_database
    source_id = _persist_days(
        session,
        store,
        [
            ("2099-07-01", 10, 90),
            ("2099-07-02", 20, 91),
            ("2099-07-03", 30, 92),
            ("2099-07-04", 40, 93),
        ],
    )
    result = compute_garmin_lagged_associations(
        session,
        garmin_source_id=source_id,
        x_metric_code="stress_daily_average",
        y_metric_code="spo2_daily_average",
        start_date=date(2099, 7, 1),
        end_date=date(2099, 7, 4),
        lag_days=[0],
    )
    assert result.lags[0].status == "not_computable"
    assert result.lags[0].reason == "insufficient_paired_n"
    assert result.lags[0].rho is None
    assert result.lags[0].n == 4


def test_constant_series_not_computable_no_nan(assoc_database) -> None:
    _paths, session, store = assoc_database
    source_id = _persist_days(
        session,
        store,
        [(f"2099-07-{day:02d}", 42, 90 + day) for day in range(1, 8)],
    )
    result = compute_garmin_lagged_associations(
        session,
        garmin_source_id=source_id,
        x_metric_code="stress_daily_average",
        y_metric_code="spo2_daily_average",
        start_date=date(2099, 7, 1),
        end_date=date(2099, 7, 7),
        lag_days=[0],
    )
    lag = result.lags[0]
    assert lag.status == "not_computable"
    assert lag.reason == "constant_or_degenerate_input"
    assert lag.rho is None
    dumped = json.dumps(result.as_dict())
    assert "NaN" not in dumped
    assert "Infinity" not in dumped
    assert "null" in dumped  # rho null


def test_availability_distinct_and_zero_participates(assoc_database) -> None:
    _paths, session, store = assoc_database
    # zero avg on day 1; usable otherwise; one missing avg day
    _persist(
        session,
        store,
        _stress_payload("2099-05-01", avg=0, spo2_avg=90, fixture_suffix="-z"),
        received_at=datetime(2099, 5, 10, 1, tzinfo=UTC),
    )
    for index, (day, avg, spo2) in enumerate(
        [
            ("2099-05-02", 10, 91),
            ("2099-05-03", 20, 92),
            ("2099-05-04", 30, 93),
            ("2099-05-05", 40, 94),
            ("2099-05-06", 50, 95),
        ],
        start=2,
    ):
        _persist(
            session,
            store,
            _stress_payload(day, avg=avg, spo2_avg=spo2, fixture_suffix=f"-u{index}"),
            received_at=datetime(2099, 5, 10, index, tzinfo=UTC),
        )
    # missing average (only maximum) — spo2 still present
    _persist(
        session,
        store,
        _stress_payload(
            "2099-05-07",
            avg=None,
            maximum=77,
            spo2_avg=96,
            fixture_suffix="-missing-avg",
        ),
        received_at=datetime(2099, 5, 10, 7, tzinfo=UTC),
    )
    session.commit()
    source_id = _source_id(session)
    result = compute_garmin_lagged_associations(
        session,
        garmin_source_id=source_id,
        x_metric_code="stress_daily_average",
        y_metric_code="spo2_daily_average",
        start_date=date(2099, 5, 1),
        end_date=date(2099, 5, 7),
        lag_days=[0],
    )
    lag = result.lags[0]
    assert lag.coverage.zero_x_participation_count == 1
    assert any(p.x_is_zero and p.x_value == 0.0 for p in lag.pairing_map)
    assert lag.coverage.exclusion_counts.get("x_missing", 0) == 1
    assert lag.n == 6
    assert lag.status == "association_available"


def test_ambiguous_same_metric_date_excluded(assoc_database) -> None:
    _paths, session, store = assoc_database
    # Two current rows for same analytic date for stress avg
    _persist(
        session,
        store,
        _stress_payload(
            "2099-08-01",
            avg=10,
            spo2_avg=90,
            fixture_suffix="-a",
            extra_payload={"note": "a"},
        ),
        received_at=datetime(2099, 8, 10, 1, tzinfo=UTC),
    )
    _persist(
        session,
        store,
        _stress_payload(
            "2099-08-01",
            avg=90,
            spo2_avg=91,
            fixture_suffix="-b",
            extra_payload={"note": "b"},
        ),
        received_at=datetime(2099, 8, 10, 2, tzinfo=UTC),
    )
    days = ["2099-08-02", "2099-08-03", "2099-08-04", "2099-08-05", "2099-08-06"]
    for index, day in enumerate(days, start=3):
        _persist(
            session,
            store,
            _stress_payload(
                day,
                avg=10 * index,
                spo2_avg=90 + index,
                fixture_suffix=f"-d{index}",
            ),
            received_at=datetime(2099, 8, 10, index, tzinfo=UTC),
        )
    session.commit()
    source_id = _source_id(session)
    result = compute_garmin_lagged_associations(
        session,
        garmin_source_id=source_id,
        x_metric_code="stress_daily_average",
        y_metric_code="spo2_daily_average",
        start_date=date(2099, 8, 1),
        end_date=date(2099, 8, 6),
        lag_days=[0],
    )
    lag = result.lags[0]
    assert lag.coverage.exclusion_counts.get("x_ambiguous_metric_date", 0) == 1
    # Never silently averaged the ambiguous day's 10/90 into the series.
    assert "2099-08-01" not in {p.x_analytic_date for p in lag.pairing_map}


def test_low_overlap_lag_surfaced(assoc_database) -> None:
    _paths, session, store = assoc_database
    # X all week; Y only first two days -> lag 5 has very low overlap
    rows = [
        ("2099-07-01", 10, 90),
        ("2099-07-02", 20, 91),
        ("2099-07-03", 30, None),
        ("2099-07-04", 40, None),
        ("2099-07-05", 50, None),
        ("2099-07-06", 60, None),
        ("2099-07-07", 70, None),
    ]
    source_id = None
    for index, (day, stress_avg, spo2_avg) in enumerate(rows):
        outcome = _persist(
            session,
            store,
            _stress_payload(
                day,
                avg=stress_avg,
                spo2_avg=spo2_avg,
                spo2_trail=None if spo2_avg is None else 97,
                spo2_sample=None if spo2_avg is None else 96,
                fixture_suffix=f"-low-{index}",
            ),
            received_at=datetime(2099, 7, 10, index, tzinfo=UTC),
        )
        source_id = outcome.records[0].garmin_source_id
    session.commit()
    assert source_id is not None
    result = compute_garmin_lagged_associations(
        session,
        garmin_source_id=source_id,
        x_metric_code="stress_daily_average",
        y_metric_code="spo2_daily_average",
        start_date=date(2099, 7, 1),
        end_date=date(2099, 7, 7),
        lag_days=[0, 5],
    )
    assert len(result.lags) == 2
    low = result.lags[1]
    assert low.lag_days == 5
    assert low.status == "not_computable"
    assert low.reason == "insufficient_paired_n"
    assert low.n < 5
    assert low.coverage.paired_usable_count == low.n
    assert low.coverage.exclusion_counts.get("y_absent_at_lag", 0) >= 1


def test_local_only_pairs_without_invented_utc(assoc_database) -> None:
    _paths, session, store = assoc_database
    for index, (day, avg, spo2) in enumerate(
        [
            ("2099-03-01", 10, 90),
            ("2099-03-02", 20, 91),
            ("2099-03-03", 30, 92),
            ("2099-03-04", 40, 93),
            ("2099-03-05", 50, 94),
            ("2099-03-06", 60, 95),
        ]
    ):
        payload = _stress_payload(
            day,
            avg=avg,
            spo2_avg=spo2,
            fixture_suffix=f"-local-{index}",
            extra_payload={"timestamp": f"{day}T02:30:00"},
        )
        _persist(session, store, payload, received_at=datetime(2099, 3, 10, index, tzinfo=UTC))
    session.commit()
    source_id = _source_id(session)
    result = compute_garmin_lagged_associations(
        session,
        garmin_source_id=source_id,
        x_metric_code="stress_daily_average",
        y_metric_code="spo2_daily_average",
        start_date=date(2099, 3, 1),
        end_date=date(2099, 3, 6),
        lag_days=[0, 1],
    )
    assert result.lags[0].status == "association_available"
    # Pairing uses analytic_date only; frozen temporal must not invent UTC Z.
    for frozen in result.frozen_inputs:
        temporal = frozen.get("temporal") or {}
        if temporal.get("zone_policy") in {"local_date_only", "local_unknown_zone"}:
            assert temporal.get("measured_at_utc") is None
    assert result.lags[1].pairing_map[0].x_analytic_date == "2099-03-01"
    assert result.lags[1].pairing_map[0].y_analytic_date == "2099-03-02"


def test_correction_a_to_b_freezes_old_changes_new(assoc_database) -> None:
    _paths, session, store = assoc_database
    rows = [
        ("2099-04-01", 10, 90),
        ("2099-04-02", 20, 91),
        ("2099-04-03", 30, 92),
        ("2099-04-04", 40, 93),
        ("2099-04-05", 50, 94),
        ("2099-04-06", 60, 95),
    ]
    source_id = _persist_days(session, store, rows)
    original = compute_garmin_lagged_associations(
        session,
        garmin_source_id=source_id,
        x_metric_code="stress_daily_average",
        y_metric_code="spo2_daily_average",
        start_date=date(2099, 4, 1),
        end_date=date(2099, 4, 6),
        lag_days=[0],
    )
    frozen = copy.deepcopy(original.as_dict())
    original_hash = frozen["result_hash"]
    original_rho = frozen["lags"][0]["rho"]
    original_n = frozen["lags"][0]["n"]
    assert original_n == 6

    rebuilt_same = compute_garmin_lagged_associations(
        session,
        garmin_source_id=source_id,
        x_metric_code="stress_daily_average",
        y_metric_code="spo2_daily_average",
        start_date=date(2099, 4, 1),
        end_date=date(2099, 4, 6),
        lag_days=[0],
    )
    assert rebuilt_same.result_hash == original_hash

    # Persistence-backed correction A -> B: second current row for same metric/date
    # changes selected pairing evidence (ambiguous exclusion) and therefore the hash.
    _persist(
        session,
        store,
        _stress_payload(
            "2099-04-03",
            avg=99,
            spo2_avg=99,
            fixture_suffix="-corrected",
            extra_payload={"note": "corrected-b"},
        ),
        received_at=datetime(2099, 4, 20, tzinfo=UTC),
    )
    session.commit()
    rebuilt = compute_garmin_lagged_associations(
        session,
        garmin_source_id=source_id,
        x_metric_code="stress_daily_average",
        y_metric_code="spo2_daily_average",
        start_date=date(2099, 4, 1),
        end_date=date(2099, 4, 6),
        lag_days=[0],
    )
    assert rebuilt.result_hash != original_hash
    assert frozen["result_hash"] == original_hash
    assert frozen["lags"][0]["rho"] == original_rho
    assert frozen["lags"][0]["n"] == original_n
    assert rebuilt.lags[0].n < original_n


def test_provenance_fail_closed(assoc_database) -> None:
    _paths, session, store = assoc_database
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

    # Seed Y scalars and confirm association still routes through #55 assembler
    # (frozen manifests present) for current rows.
    sleep_day = date(2099, 1, 2)
    for offset in range(6):
        day = (sleep_day + timedelta(days=offset)).isoformat()
        _persist(
            session,
            store,
            _stress_payload(
                day,
                avg=10 + offset,
                spo2_avg=90 + offset,
                fixture_suffix=f"-prov-{offset}",
            ),
            received_at=datetime(2099, 1, 5, offset, tzinfo=UTC),
        )
    session.commit()
    result = compute_garmin_lagged_associations(
        session,
        garmin_source_id=record.garmin_source_id,
        x_metric_code="stress_daily_average",
        y_metric_code="spo2_daily_average",
        start_date=sleep_day,
        end_date=sleep_day + timedelta(days=5),
        lag_days=[0],
    )
    assert result.frozen_inputs
    assert all(item.get("manifest_hash") for item in result.frozen_inputs)


def test_no_pvalue_best_lag_or_causal_labels(assoc_database) -> None:
    _paths, session, store = assoc_database
    source_id = _persist_days(
        session,
        store,
        [(f"2099-07-{day:02d}", 10 * day, 90 + day) for day in range(1, 8)],
    )
    result = analyze_garmin_lagged_associations(
        session,
        GarminLaggedAssociationQuery(
            garmin_source_id=source_id,
            x_metric_code="stress_daily_average",
            y_metric_code="spo2_daily_average",
            start_date=date(2099, 7, 1),
            end_date=date(2099, 7, 7),
            lag_days=(0, 1),
        ),
    )
    dumped = json.dumps(result.as_dict()).lower()
    forbidden = [
        "p_value",
        "pvalue",
        "p-value",
        "significance",
        "best_lag",
        "best-lag",
        "causal",
        "predictive",
        "prediction",
        "medical",
        "readiness",
        "training_advice",
        "diagnosis",
        "confidence_interval",
        "pearson",
    ]
    for token in forbidden:
        assert token not in dumped, token
    assert "association_available" in dumped
    assert result.lags[0].status in {"association_available", "not_computable"}


def test_window_bound_reuses_r03_01_cap(assoc_database) -> None:
    _paths, session, store = assoc_database
    source_id = _persist_days(
        session,
        store,
        [("2099-01-01", 10, 90), ("2099-01-02", 20, 91)],
    )
    with pytest.raises(GarminSeriesWindowError):
        compute_garmin_lagged_associations(
            session,
            garmin_source_id=source_id,
            x_metric_code="stress_daily_average",
            y_metric_code="spo2_daily_average",
            start_date=date(2099, 1, 1),
            end_date=date(2099, 1, 1) + timedelta(days=400),
            lag_days=[0],
        )
