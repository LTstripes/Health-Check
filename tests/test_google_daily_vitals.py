"""Focused regressions for the frozen #297 Google daily-vitals read contract."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.models import GoogleSourceRecord
from healthcheck.google.contracts import (
    FAMILY_GOOGLE_SOURCES,
    FAMILY_GOOGLE_WEARABLES,
    GoogleMetricDTO,
    GoogleMetricState,
    GooglePayloadStatus,
    GoogleQueryContext,
    GoogleQueryMode,
    GoogleRecordDTO,
    GoogleSourceIdentity,
    GoogleSourceKind,
    GoogleStream,
    GoogleTemporalDTO,
    GoogleTemporalPrecision,
)
from healthcheck.google.daily_vitals import (
    GOOGLE_DAILY_VITALS,
    GOOGLE_DAILY_VITALS_CONTRACT_VERSION,
    MAX_GOOGLE_DAILY_VITALS_CALENDAR_DAYS,
    get_google_daily_vital,
    read_google_daily_vitals,
    validate_google_daily_vitals_window,
)
from healthcheck.google.persistence import GooglePersistenceRepository
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from healthcheck.runtime import prepare_runtime

HRV = "daily_hrv_average_ms"
RHR = "daily_resting_heart_rate_bpm"
SPO2 = "daily_oxygen_saturation_average_percentage"
RR = "daily_respiratory_rate_breaths_per_minute"

METRIC_FIELDS = {
    HRV: (GoogleStream.DAILY_HRV, "ms"),
    RHR: (GoogleStream.DAILY_RESTING_HR, "bpm"),
    SPO2: (GoogleStream.DAILY_SPO2, "%"),
    RR: (GoogleStream.DAILY_RESPIRATORY_RATE, "breaths_per_minute"),
}

FITBIT_DATASOURCE = (
    "users/me/dataSources/raw:com.google.heart_rate.bpm:com.fitbit.Fitbit:ABC123"
)


@pytest.fixture
def google_database(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            yield paths, session, ContentAddressedGooglePayloadStore(paths.root / "artifacts")
    finally:
        engine.dispose()


def _fitbit_identity(**overrides) -> GoogleSourceIdentity:
    values = {
        "source_kind": GoogleSourceKind.DATA_SOURCE,
        "source_instance_id": FITBIT_DATASOURCE,
        "data_source_name": FITBIT_DATASOURCE,
        "data_source_id": "raw:com.google.heart_rate.bpm:com.fitbit.Fitbit:ABC123",
        "platform": "fitbit",
        "recording_method": "automatic",
        "device_attributed": True,
        "device_code": "fitbit_air",
        "device_manufacturer": "Fitbit",
        "device_model": "Fitbit Air",
        "device_uid": "ABC123",
    }
    values.update(overrides)
    return GoogleSourceIdentity(**values)


def _family_identity(family: str = FAMILY_GOOGLE_WEARABLES) -> GoogleSourceIdentity:
    return GoogleSourceIdentity(
        source_kind=GoogleSourceKind.FAMILY_AGGREGATE,
        source_instance_id=family,
    )


def _query(mode, family=None) -> GoogleQueryContext:
    return GoogleQueryContext(query_mode=mode, data_source_family=family)


def _daily_record(
    *,
    metric_code: str,
    local_date: date | None,
    value: float | None,
    state: GoogleMetricState = GoogleMetricState.VALUE,
    unit: str | None = None,
    precision: GoogleTemporalPrecision = GoogleTemporalPrecision.DATE,
    local_wall_time: str | None = None,
    external_record_id: str = "synthetic-daily",
    status: GooglePayloadStatus = GooglePayloadStatus.OK,
    idempotency_key: str | None = None,
) -> GoogleRecordDTO:
    stream, default_unit = METRIC_FIELDS[metric_code]
    return GoogleRecordDTO(
        stream=stream,
        idempotency_key=(
            idempotency_key
            or f"{stream.value}:{external_record_id}:{local_date or 'no-date'}"
        ),
        external_record_id=external_record_id,
        temporal=GoogleTemporalDTO(
            precision=precision,
            local_date=local_date,
            local_wall_time=local_wall_time,
        ),
        metrics=(
            GoogleMetricDTO(
                metric_code=metric_code,
                field_path=f"$.dataPoints[0].{stream.value}",
                state=state,
                value_number=value if state is GoogleMetricState.VALUE else None,
                unit=unit if unit is not None else default_unit,
            ),
        ),
        status=status,
    )


def _persist(session, store, record: GoogleRecordDTO, *, identity=None, query=None):
    outcome = GooglePersistenceRepository(session, payload_store=store).persist_observation(
        identity=identity or _fitbit_identity(),
        query=query or _query(GoogleQueryMode.LIST),
        stream=record.stream,
        payload={"synthetic": record.idempotency_key},
        records=(record,),
        received_at=datetime(2099, 1, 3, 12, tzinfo=UTC),
    )
    session.flush()
    return outcome


def seed_google_daily_vitals(paths) -> None:
    """Deterministic synthetic Owner fixture: two explicit sources, mixed states.

    Source A (attributed Fitbit Air): HRV 42.5 on 2099-01-02, RHR 57 on
    2099-01-01 and 55 on 2099-01-02, SpO2 97 on 2099-01-02, RR 13.5 on
    2099-01-02, and an ambiguous HRV pair on 2099-01-01 (list + reconcile).

    Source B (google-wearables family): explicit NULL HRV, SpO2 96, explicit
    zero RR on 2099-01-02; no resting-HR record at all.
    """

    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            store = ContentAddressedGooglePayloadStore(paths.root / "artifacts")
            identity_a = _fitbit_identity()
            _persist(
                session,
                store,
                _daily_record(metric_code=HRV, local_date=date(2099, 1, 2), value=42.5),
                identity=identity_a,
            )
            _persist(
                session,
                store,
                _daily_record(
                    metric_code=RHR, local_date=date(2099, 1, 1), value=57,
                    external_record_id="rhr-0101",
                ),
                identity=identity_a,
            )
            _persist(
                session,
                store,
                _daily_record(
                    metric_code=RHR, local_date=date(2099, 1, 2), value=55,
                    external_record_id="rhr-0102",
                ),
                identity=identity_a,
            )
            _persist(
                session,
                store,
                _daily_record(metric_code=SPO2, local_date=date(2099, 1, 2), value=97),
                identity=identity_a,
            )
            _persist(
                session,
                store,
                _daily_record(metric_code=RR, local_date=date(2099, 1, 2), value=13.5),
                identity=identity_a,
            )
            _persist(
                session,
                store,
                _daily_record(
                    metric_code=HRV, local_date=date(2099, 1, 1), value=40,
                    external_record_id="hrv-0101",
                ),
                identity=identity_a,
            )
            _persist(
                session,
                store,
                _daily_record(
                    metric_code=HRV, local_date=date(2099, 1, 1), value=41,
                    external_record_id="hrv-0101",
                ),
                identity=identity_a,
                query=_query(GoogleQueryMode.RECONCILE),
            )
            identity_b = _family_identity()
            _persist(
                session,
                store,
                _daily_record(
                    metric_code=HRV, local_date=date(2099, 1, 2), value=None,
                    state=GoogleMetricState.NULL,
                ),
                identity=identity_b,
                query=_query(GoogleQueryMode.LIST, FAMILY_GOOGLE_WEARABLES),
            )
            _persist(
                session,
                store,
                _daily_record(metric_code=SPO2, local_date=date(2099, 1, 2), value=96),
                identity=identity_b,
                query=_query(GoogleQueryMode.LIST, FAMILY_GOOGLE_WEARABLES),
            )
            _persist(
                session,
                store,
                _daily_record(metric_code=RR, local_date=date(2099, 1, 2), value=0),
                identity=identity_b,
                query=_query(GoogleQueryMode.LIST, FAMILY_GOOGLE_WEARABLES),
            )
    finally:
        engine.dispose()


def test_registry_freezes_exactly_four_typed_metrics():
    assert [item.metric_code for item in GOOGLE_DAILY_VITALS] == [HRV, RHR, SPO2, RR]
    assert {item.metric_code: item.unit for item in GOOGLE_DAILY_VITALS} == {
        HRV: "ms",
        RHR: "bpm",
        SPO2: "%",
        RR: "breaths_per_minute",
    }
    assert {item.metric_code: item.stream_code for item in GOOGLE_DAILY_VITALS} == {
        HRV: "daily_hrv",
        RHR: "daily_resting_hr",
        SPO2: "daily_spo2",
        RR: "daily_respiratory_rate",
    }
    assert GOOGLE_DAILY_VITALS_CONTRACT_VERSION == "r297-google-daily-vitals-read-v1"
    assert MAX_GOOGLE_DAILY_VITALS_CALENDAR_DAYS == 400
    with pytest.raises(ValueError):
        get_google_daily_vital("heart_rate_bpm")


def test_window_validation_rejects_reversed_and_overlong_bounds():
    with pytest.raises(ValueError):
        validate_google_daily_vitals_window(date(2099, 1, 2), date(2099, 1, 1))
    assert validate_google_daily_vitals_window(date(2099, 1, 1), date(2099, 1, 1)) == 1
    with pytest.raises(ValueError):
        validate_google_daily_vitals_window(date(2099, 1, 1), date(2100, 3, 1))


def test_single_current_record_yields_value_and_latest(google_database):
    _paths, session, store = google_database
    _persist(
        session, store,
        _daily_record(metric_code=HRV, local_date=date(2099, 1, 2), value=42.5),
    )
    result = read_google_daily_vitals(
        session, metric_code=HRV, start_date=date(2099, 1, 1), end_date=date(2099, 1, 2)
    )
    assert result.window_state == "records_in_window"
    assert result.unit == "ms"
    assert len(result.sources) == 1
    source = result.sources[0]
    assert source.latest is not None
    assert source.latest.source_local_date == date(2099, 1, 2)
    assert source.latest.value == 42.5
    assert source.latest.eligible is True
    assert source.latest.is_zero is False
    assert source.latest.record_status == "ok"


def test_list_and_reconcile_same_date_is_ambiguous(google_database):
    _paths, session, store = google_database
    identity = _fitbit_identity()
    _persist(
        session, store,
        _daily_record(metric_code=HRV, local_date=date(2099, 1, 2), value=40),
        identity=identity, query=_query(GoogleQueryMode.LIST),
    )
    _persist(
        session, store,
        _daily_record(metric_code=HRV, local_date=date(2099, 1, 2), value=41),
        identity=identity, query=_query(GoogleQueryMode.RECONCILE),
    )
    result = read_google_daily_vitals(
        session, metric_code=HRV, start_date=date(2099, 1, 2), end_date=date(2099, 1, 2)
    )
    point = result.sources[0].points[0]
    assert point.state == "ambiguous"
    assert point.eligible is False
    assert point.value is None
    assert point.exclusion_basis == "ambiguous_same_date_records"
    assert len(point.candidates) == 2
    assert {item.query_mode for item in point.candidates} == {"list", "reconcile"}
    assert result.sources[0].latest is None
    assert result.sources[0].latest_reason == "no_eligible_value_in_window"


def test_two_family_contexts_same_date_is_ambiguous(google_database):
    _paths, session, store = google_database
    identity = _fitbit_identity()
    for family in (FAMILY_GOOGLE_WEARABLES, FAMILY_GOOGLE_SOURCES):
        _persist(
            session, store,
            _daily_record(metric_code=RHR, local_date=date(2099, 1, 2), value=55),
            identity=identity,
            query=_query(GoogleQueryMode.RECONCILE, family),
        )
    result = read_google_daily_vitals(
        session, metric_code=RHR, start_date=date(2099, 1, 2), end_date=date(2099, 1, 2)
    )
    assert result.sources[0].points[0].state == "ambiguous"


def test_two_provider_point_names_same_date_is_ambiguous(google_database):
    _paths, session, store = google_database
    identity = _fitbit_identity()
    for name in ("point-a", "point-b"):
        _persist(
            session, store,
            _daily_record(
                metric_code=SPO2, local_date=date(2099, 1, 2), value=97,
                external_record_id=name,
            ),
            identity=identity,
        )
    result = read_google_daily_vitals(
        session, metric_code=SPO2, start_date=date(2099, 1, 2), end_date=date(2099, 1, 2)
    )
    assert result.sources[0].points[0].state == "ambiguous"


def test_two_sources_remain_separate_series(google_database):
    _paths, session, store = google_database
    _persist(
        session, store,
        _daily_record(metric_code=SPO2, local_date=date(2099, 1, 2), value=97),
        identity=_fitbit_identity(),
    )
    _persist(
        session, store,
        _daily_record(metric_code=SPO2, local_date=date(2099, 1, 2), value=96),
        identity=_family_identity(),
        query=_query(GoogleQueryMode.LIST, FAMILY_GOOGLE_WEARABLES),
    )
    result = read_google_daily_vitals(
        session, metric_code=SPO2, start_date=date(2099, 1, 2), end_date=date(2099, 1, 2)
    )
    assert len(result.sources) == 2
    assert {source.latest.value for source in result.sources} == {97, 96}
    assert {source.source_kind for source in result.sources} == {
        "data_source", "family_aggregate"
    }


def test_missing_row_and_missing_null_invalid_states_stay_distinct(google_database):
    _paths, session, store = google_database
    identity = _fitbit_identity()
    _persist(
        session, store,
        _daily_record(metric_code=RHR, local_date=date(2099, 1, 1), value=57),
        identity=identity,
    )
    _persist(
        session, store,
        _daily_record(
            metric_code=RHR, local_date=date(2099, 1, 2), value=None,
            state=GoogleMetricState.MISSING,
        ),
        identity=identity,
    )
    _persist(
        session, store,
        _daily_record(
            metric_code=RHR, local_date=date(2099, 1, 3), value=None,
            state=GoogleMetricState.NULL,
        ),
        identity=identity,
    )
    _persist(
        session, store,
        _daily_record(
            metric_code=RHR, local_date=date(2099, 1, 4), value=None,
            state=GoogleMetricState.INVALID,
        ),
        identity=identity,
    )
    result = read_google_daily_vitals(
        session, metric_code=RHR, start_date=date(2099, 1, 1), end_date=date(2099, 1, 4)
    )
    states = {point.source_local_date: point.state for point in result.sources[0].points}
    assert states == {
        date(2099, 1, 1): "value",
        date(2099, 1, 2): "missing",
        date(2099, 1, 3): "null",
        date(2099, 1, 4): "invalid",
    }
    assert all(
        point.eligible is False
        for point in result.sources[0].points
        if point.state != "value"
    )
    assert result.sources[0].latest.source_local_date == date(2099, 1, 1)


def test_value_state_without_finite_number_is_invalid(google_database):
    _paths, session, store = google_database
    _persist(
        session, store,
        _daily_record(metric_code=HRV, local_date=date(2099, 1, 2), value=None),
    )
    result = read_google_daily_vitals(
        session, metric_code=HRV, start_date=date(2099, 1, 2), end_date=date(2099, 1, 2)
    )
    point = result.sources[0].points[0]
    assert point.state == "invalid"
    assert point.exclusion_basis == "metric_value_invalid"
    assert point.eligible is False


def test_unit_mismatch_is_ineligible_without_value(google_database):
    _paths, session, store = google_database
    _persist(
        session, store,
        _daily_record(metric_code=RHR, local_date=date(2099, 1, 2), value=55, unit="seconds"),
    )
    result = read_google_daily_vitals(
        session, metric_code=RHR, start_date=date(2099, 1, 2), end_date=date(2099, 1, 2)
    )
    point = result.sources[0].points[0]
    assert point.state == "value"
    assert point.exclusion_basis == "metric_unit_mismatch"
    assert point.value is None
    assert point.eligible is False
    assert result.sources[0].latest is None


def test_explicit_zero_is_eligible_and_flagged(google_database):
    _paths, session, store = google_database
    _persist(
        session, store,
        _daily_record(metric_code=RR, local_date=date(2099, 1, 2), value=0),
    )
    result = read_google_daily_vitals(
        session, metric_code=RR, start_date=date(2099, 1, 2), end_date=date(2099, 1, 2)
    )
    point = result.sources[0].latest
    assert point is not None
    assert point.eligible is True
    assert point.is_zero is True
    assert point.value == 0
    assert point.state == "value"


def test_invalid_record_status_does_not_erase_sibling_value(google_database):
    _paths, session, store = google_database
    _persist(
        session, store,
        _daily_record(
            metric_code=SPO2, local_date=date(2099, 1, 2), value=95,
            status=GooglePayloadStatus.INVALID,
        ),
    )
    result = read_google_daily_vitals(
        session, metric_code=SPO2, start_date=date(2099, 1, 2), end_date=date(2099, 1, 2)
    )
    point = result.sources[0].latest
    assert point is not None and point.eligible is True
    assert point.record_status == "invalid"
    assert point.value == 95


def test_window_bounds_are_inclusive(google_database):
    _paths, session, store = google_database
    for day in (date(2099, 1, 1), date(2099, 1, 3)):
        _persist(
            session, store,
            _daily_record(
                metric_code=RHR, local_date=day, value=55,
                external_record_id=f"rhr-{day.isoformat()}",
            ),
        )
    result = read_google_daily_vitals(
        session, metric_code=RHR, start_date=date(2099, 1, 1), end_date=date(2099, 1, 3)
    )
    assert [point.source_local_date for point in result.sources[0].points] == [
        date(2099, 1, 1), date(2099, 1, 3)
    ]
    narrower = read_google_daily_vitals(
        session, metric_code=RHR, start_date=date(2099, 1, 2), end_date=date(2099, 1, 3)
    )
    assert [point.source_local_date for point in narrower.sources[0].points] == [
        date(2099, 1, 3)
    ]


def test_latest_skips_ambiguous_newer_date_but_keeps_actual_date(google_database):
    _paths, session, store = google_database
    identity = _fitbit_identity()
    _persist(
        session, store,
        _daily_record(metric_code=HRV, local_date=date(2099, 1, 1), value=40),
        identity=identity,
    )
    for value in (40, 41):
        _persist(
            session, store,
            _daily_record(metric_code=HRV, local_date=date(2099, 1, 2), value=value),
            identity=identity,
            query=_query(
                GoogleQueryMode.LIST if value == 40 else GoogleQueryMode.RECONCILE
            ),
        )
    result = read_google_daily_vitals(
        session, metric_code=HRV, start_date=date(2099, 1, 1), end_date=date(2099, 1, 2)
    )
    assert result.sources[0].latest.source_local_date == date(2099, 1, 1)
    assert result.sources[0].latest.value == 40
    assert result.sources[0].points[-1].state == "ambiguous"


def test_no_current_record_in_window_is_not_global_absence(google_database):
    _paths, session, _store = google_database
    result = read_google_daily_vitals(
        session, metric_code=HRV, start_date=date(2099, 1, 1), end_date=date(2099, 1, 2)
    )
    assert result.window_state == "no_current_record_in_window"
    assert result.sources == ()


def test_null_date_and_non_date_precision_are_not_window_eligible(google_database):
    _paths, session, store = google_database
    _persist(
        session, store,
        _daily_record(metric_code=HRV, local_date=None, value=40),
    )
    _persist(
        session, store,
        _daily_record(
            metric_code=HRV,
            local_date=date(2099, 1, 2),
            value=41,
            precision=GoogleTemporalPrecision.LOCAL,
            local_wall_time="2099-01-02T08:00:00",
            external_record_id="local-precision",
        ),
    )
    result = read_google_daily_vitals(
        session, metric_code=HRV, start_date=date(2099, 1, 1), end_date=date(2099, 1, 2)
    )
    assert result.window_state == "no_current_record_in_window"
    assert result.sources == ()


def test_retired_projection_is_excluded(google_database):
    _paths, session, store = google_database
    outcome = _persist(
        session, store,
        _daily_record(metric_code=HRV, local_date=date(2099, 1, 2), value=40),
    )
    record = session.get(GoogleSourceRecord, outcome.records[0].id)
    record.projection_status = "retired"
    record.retired_at = datetime(2099, 1, 4, tzinfo=UTC)
    record.retire_reason = "synthetic"
    session.flush()
    result = read_google_daily_vitals(
        session, metric_code=HRV, start_date=date(2099, 1, 2), end_date=date(2099, 1, 2)
    )
    assert result.window_state == "no_current_record_in_window"


def test_metric_read_does_not_leak_other_streams(google_database):
    _paths, session, store = google_database
    _persist(
        session, store,
        _daily_record(metric_code=HRV, local_date=date(2099, 1, 2), value=40),
    )
    result = read_google_daily_vitals(
        session, metric_code=RHR, start_date=date(2099, 1, 2), end_date=date(2099, 1, 2)
    )
    assert result.sources == ()


@pytest.mark.parametrize("metric_code", [HRV, RHR, SPO2, RR])
@pytest.mark.parametrize("bounds", [(1, 5), (2, 2), (3, 4), (8, 9)])
def test_295_source_seeks_match_frozen_reader_for_mixed_evidence(
    google_database,
    metric_code,
    bounds,
):
    """Compare complete ordered DTOs, including candidates and source metadata."""
    import random

    from scripts.google_daily_vitals_read_reference import read_google_daily_vitals_reference

    from healthcheck.web.read_snapshot import ensure_read_snapshot

    _paths, session, store = google_database
    rng = random.Random(295)
    identities = [_fitbit_identity(platform="synthetic-other-platform"), _family_identity()]
    # Deliberately unordered dates and source/query identities. The accepted
    # reader does not prefer list/reconcile, family, platform or record status.
    for index in range(36):
        precision = rng.choice(
            (
                GoogleTemporalPrecision.DATE,
                GoogleTemporalPrecision.LOCAL,
                GoogleTemporalPrecision.UNKNOWN,
            )
        )
        day = date(2099, 1, rng.randint(1, 5)) if index % 11 else None
        state = rng.choice(tuple(GoogleMetricState))
        outcome = _persist(
            session,
            store,
            _daily_record(
                metric_code=metric_code,
                local_date=day,
                value=0 if index % 3 else 41,
                state=state,
                unit="wrong" if index % 7 == 0 else None,
                precision=precision,
                local_wall_time=f"2099-01-01T08:{index:02d}:00"
                if precision is GoogleTemporalPrecision.LOCAL
                else None,
                external_record_id=f"mixed-{index}",
                status=rng.choice(tuple(GooglePayloadStatus)),
            ),
            identity=identities[index % 2],
            query=_query(
                rng.choice((GoogleQueryMode.LIST, GoogleQueryMode.RECONCILE)),
                rng.choice((None, FAMILY_GOOGLE_WEARABLES, FAMILY_GOOGLE_SOURCES))
                if index % 2 == 0
                else FAMILY_GOOGLE_WEARABLES,
            ),
        )
        if index % 9 == 0:
            record = session.get(GoogleSourceRecord, outcome.records[0].id)
            record.projection_status = "retired"
            record.retired_at = datetime(2099, 1, 6, tzinfo=UTC)
            record.retire_reason = "synthetic correction"
    # Retain a real eligible zero and a same-day list/reconcile ambiguity.
    for index, day in enumerate((1, 3, 3)):
        _persist(
            session,
            store,
            _daily_record(
                metric_code=metric_code,
                local_date=date(2099, 1, day),
                value=0,
                external_record_id=f"eligible-{index}",
            ),
            query=_query(GoogleQueryMode.RECONCILE if index == 2 else GoogleQueryMode.LIST),
        )
    session.commit()
    ensure_read_snapshot(session)
    kwargs = dict(
        metric_code=metric_code,
        start_date=date(2099, 1, bounds[0]),
        end_date=date(2099, 1, bounds[1]),
    )
    assert read_google_daily_vitals(session, **kwargs).as_dict() == (
        read_google_daily_vitals_reference(session, **kwargs).as_dict()
    )


def test_295_source_seeks_do_not_cap_inventory_and_observe_correction(google_database):
    from scripts.google_daily_vitals_read_reference import read_google_daily_vitals_reference
    from sqlalchemy import select

    from healthcheck.db.models import GoogleRecordMetric, GoogleSource

    _paths, session, store = google_database
    first = _persist(
        session,
        store,
        _daily_record(
            metric_code=HRV,
            local_date=date(2098, 12, 1),
            value=40,
        ),
    )
    source = session.scalar(select(GoogleSource))
    # All inventory IDs participate; no new discovery/work cap may exclude a
    # source after 400 identities (the calendar bound is not a source bound).
    template = {
        column.name: getattr(source, column.name) for column in GoogleSource.__table__.columns
    }
    for index in range(405):
        row = dict(
            template,
            id=f"synthetic-inventory-{index:04d}",
            source_instance_id=f"synthetic-inventory-{index:04d}",
        )
        session.add(GoogleSource(**row))
    session.flush()
    first = _persist(
        session,
        store,
        _daily_record(
            metric_code=HRV,
            local_date=date(2099, 1, 2),
            value=40,
        ),
        identity=_fitbit_identity(source_instance_id="synthetic-inventory-0404"),
    )
    first_record = session.get(GoogleSourceRecord, first.records[0].id)
    session.commit()
    kwargs = dict(metric_code=HRV, start_date=date(2099, 1, 2), end_date=date(2099, 1, 2))
    before = read_google_daily_vitals(session, **kwargs)
    assert before.as_dict() == read_google_daily_vitals_reference(session, **kwargs).as_dict()
    assert [item.source_id for item in before.sources] == ["synthetic-inventory-0404"]
    # Same connection, next read must observe current/retired evidence, with no
    # request/global cache. Missing metric rows retain their accepted state.
    first_record.projection_status = "retired"
    first_record.retired_at = datetime(2099, 1, 4, tzinfo=UTC)
    first_record.retire_reason = "synthetic correction"
    _persist(
        session,
        store,
        _daily_record(
            metric_code=HRV,
            local_date=date(2099, 1, 2),
            value=42,
            external_record_id="replacement",
        ),
    )
    session.commit()
    corrected = read_google_daily_vitals(session, **kwargs)
    assert corrected.as_dict() == read_google_daily_vitals_reference(session, **kwargs).as_dict()
    assert corrected.sources[0].latest.value == 42
    replacement = session.scalar(
        select(GoogleSourceRecord).where(
            GoogleSourceRecord.projection_status == "current",
            GoogleSourceRecord.source_local_date == date(2099, 1, 2),
        )
    )
    session.query(GoogleRecordMetric).filter(
        GoogleRecordMetric.record_id == replacement.id,
    ).delete()
    session.commit()
    missing = read_google_daily_vitals(session, **kwargs)
    assert missing.as_dict() == read_google_daily_vitals_reference(session, **kwargs).as_dict()
    assert missing.sources[0].latest is None


def test_295_source_seeks_match_window_validation(google_database):
    from scripts.google_daily_vitals_read_reference import read_google_daily_vitals_reference

    _paths, session, _store = google_database
    for reader in (read_google_daily_vitals, read_google_daily_vitals_reference):
        for metric, start, end in (
            (HRV, date(2099, 1, 3), date(2099, 1, 2)),
            (HRV, date(2099, 1, 1), date(2100, 3, 1)),
            ("unsupported", date(2099, 1, 1), date(2099, 1, 2)),
        ):
            with pytest.raises(ValueError):
                reader(session, metric_code=metric, start_date=start, end_date=end)


@pytest.mark.parametrize("route", ["brief", "sleep"])
@pytest.mark.parametrize("days", [7, 30])
def test_295_source_seeks_preserve_consumer_html_packet_and_evidence(
    tmp_path, monkeypatch, route, days
):
    from datetime import timedelta
    from unittest.mock import patch

    from fastapi.testclient import TestClient
    from scripts.google_daily_vitals_read_reference import read_google_daily_vitals_reference

    from healthcheck.web import overview_view, pages, period_brief_query
    from test_garmin_query_dashboard import _ui
    from test_period_brief_ui import seed_overview_v2

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2099, 1, 3, 12, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(pages, "datetime", FixedClock)
    monkeypatch.setattr(period_brief_query, "datetime", FixedClock)
    app, _settings, paths = _ui(tmp_path)
    seed_overview_v2(paths)
    params = (
        {
            "start_date": (date(2099, 1, 2) - timedelta(days=days - 1)).isoformat(),
            "end_date": "2099-01-02",
        }
        if route == "brief"
        else {"wake_date": "2099-01-02", "vitals_window": str(days), "view": "google"}
    )
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        actual = client.get(f"/{route}", params=params)
        with (
            patch.object(
                overview_view, "read_google_daily_vitals", read_google_daily_vitals_reference
            ),
            patch.object(pages, "read_google_daily_vitals", read_google_daily_vitals_reference),
        ):
            reference = client.get(f"/{route}", params=params)
    assert actual.status_code == reference.status_code == 200
    assert actual.text == reference.text
    keys = (
        ("packet", "brief", "charts", "overview", "source_selection")
        if route == "brief"
        else (
            "google_vitals",
            "google_vitals_technical",
        )
    )
    for key in keys:
        assert actual.context[key] == reference.context[key]
