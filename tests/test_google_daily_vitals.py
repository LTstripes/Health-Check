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
