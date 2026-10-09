"""Synthetic persisted evidence for #347; no providers, raw reads or writes in service."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import InvalidRequestError

from healthcheck.analytics.period_summary import SLEEP_CODE, PeriodSummaryService
from healthcheck.db.models import (
    GarminRecordMetric,
    GarminSleepRecord,
    GarminSource,
    GarminSourceRecord,
    GoogleRecordMetric,
    GoogleSleepRecord,
    GoogleSource,
    GoogleSourceRecord,
)
from healthcheck.db.repositories import repositories_for
from healthcheck.garmin.normalization import normalize_garmin_payload
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from test_sleep_account_cohort import _garmin, _google
from test_sleep_metrics import projection_database as projection_database

END = date(2099, 1, 8)
START = END - timedelta(days=6)
ACTIVITY = Path(__file__).parent / "fixtures" / "garmin" / "activity.json"


def _activity(
    session,
    paths,
    *,
    count=1,
    kind="cycling",
    day=START,
    distance=21000,
    duration=3600,
    suffix="",
    attributed=True,
):
    payload = json.loads(ACTIVITY.read_text(encoding="utf-8"))
    if not attributed:
        payload["device"] = {"attributed": False}
    template = payload["payload"]["activities"][0]
    payload["payload"]["activities"] = [
        dict(
            template,
            activityId=f"synthetic-{kind}-{suffix}-{i}",
            activityType={"typeKey": kind},
            startTimeGMT=f"{day}T08:00:00Z",
            distance=distance,
            duration=duration,
        )
        for i in range(count)
    ]
    return GarminPersistenceRepository(
        session, payload_store=ContentAddressedGarminPayloadStore(paths.root / "garmin-artifacts")
    ).persist_result(normalize_garmin_payload(payload), payload=json.dumps(payload).encode())


def _packet(session, **kwargs):
    return PeriodSummaryService(session).build(end_date=END, days=7, **kwargs)


def _metric(packet, code=SLEEP_CODE, side=0):
    return packet["sides"][side]["metrics"][code]


def _reasons(metric):
    return {e["reason_code"]: e["count"] for e in metric["exclusions"]}


def _coverage(session, source, *, surface="activities", status="present", scoped=True):
    return repositories_for(session).coverage.record(
        provider_id=source.provider_id,
        acquisition_source_id=source.acquisition_source_id if scoped else None,
        stream_code="google:synthetic:sleep:list:none"
        if isinstance(source, GoogleSource)
        else surface,
        metric_code="google_coverage" if isinstance(source, GoogleSource) else surface,
        interval_start=datetime.combine(START, datetime.min.time(), tzinfo=UTC),
        interval_end=datetime.combine(END + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
        resolution="day",
        status=status,
        calculation_rule_version="synthetic-coverage-v1",
    )


def test_empty_packet_has_two_null_sides_and_blocked_streams(projection_database):
    session, _ = projection_database
    packet = _packet(session)
    assert packet["contract_version"] == "source-period-summary-v1"
    assert packet["requested_window"]["start_date"] == str(START)
    assert [s["provider_code"] for s in packet["sides"]] == ["garmin_connect", "google_health"]
    for side in packet["sides"]:
        for cell in side["metrics"].values():
            assert cell["aggregation"]["value"] is None
            assert cell["missing_day_count"] == 7
    assert _metric(packet, "activity_session_count", 1)["state"] == "not_collected"
    assert set(packet["blocked_metrics"]) == {"steps", "calories"}
    assert all(d["value"] is None for d in packet["deltas"].values())


@pytest.mark.parametrize("days", [7, 30])
def test_inclusive_boundaries_and_uncapped_inventory(projection_database, days):
    session, paths = projection_database
    start = END - timedelta(days=days - 1)
    _activity(session, paths, count=105, day=start, distance=2)
    _activity(session, paths, day=END, suffix="end", distance=3)
    _activity(session, paths, day=start - timedelta(days=1), suffix="before")
    _activity(session, paths, day=END + timedelta(days=1), suffix="after")
    session.commit()
    packet = PeriodSummaryService(session).build(end_date=END, days=days)
    count = _metric(packet, "activity_session_count")
    assert count["aggregation"]["value"] == 106
    assert count["effective_dates"] == {"min_observed": str(start), "max_observed": str(END)}
    assert count["missing_day_count"] == days - 2
    assert count["coverage"]["complete"] is False
    assert _metric(packet, "cycling_distance_meters")["aggregation"]["value"] == 213


@pytest.mark.parametrize("kind", ["tennis", "tennis_v2", "cycling", "road_biking"])
def test_frozen_type_sets_and_explicit_zero(projection_database, kind):
    session, paths = projection_database
    _activity(session, paths, kind=kind, distance=0, duration=0)
    session.commit()
    packet = _packet(session)
    assert _metric(packet, "activity_type_counts")["aggregation"]["value"] == {kind: 1}
    tennis = kind in {"tennis", "tennis_v2"}
    assert _metric(packet, "tennis_session_count")["aggregation"]["value"] == (
        1 if tennis else None
    )
    for code, supported in (
        ("cycling_distance_meters", kind == "cycling"),
        ("tennis_duration_seconds", tennis),
    ):
        cell = _metric(packet, code)
        assert cell["aggregation"]["value"] == (0 if supported else None)
        assert cell["availability_counts"]["zero"] == int(supported)


@pytest.mark.parametrize(
    "state,unit,number,reason",
    [
        ("missing", "meters", None, "metric_missing"),
        ("null", "meters", None, "metric_null"),
        ("invalid", "meters", None, "metric_invalid"),
        ("value", "km", 2, "metric_unit_mismatch"),
        ("value", "meters", -2, "metric_invalid"),
    ],
)
def test_activity_field_exclusions_keep_session_count(
    projection_database, state, unit, number, reason
):
    session, paths = projection_database
    _activity(session, paths)
    row = session.scalar(
        select(GarminRecordMetric).where(GarminRecordMetric.metric_code == "distance_meters")
    )
    row.state, row.unit, row.value_number = state, unit, number
    session.commit()
    packet = _packet(session)
    assert _metric(packet, "activity_session_count")["aggregation"]["value"] == 1
    cell = _metric(packet, "cycling_distance_meters")
    assert cell["aggregation"]["value"] is None
    assert _reasons(cell)[reason] == 1


def test_duplicate_current_and_retired_activity_snapshots_are_not_summed(projection_database):
    session, paths = projection_database
    _activity(session, paths, distance=10)
    _activity(session, paths, distance=20, suffix="competing")
    rows = list(session.scalars(select(GarminSourceRecord)))
    assert len(rows) == 2
    rows[1].external_record_id = rows[0].external_record_id
    session.commit()
    cell = _metric(_packet(session), "cycling_distance_meters")
    assert cell["aggregation"]["value"] is None
    assert _reasons(cell)["duplicate_current_identity"] == 2
    rows[0].projection_status = "retired"
    rows[0].retired_at = datetime(2099, 1, 9, tzinfo=UTC)
    rows[0].retire_reason = "authoritative_collection_replacement"
    session.commit()
    cell = _metric(_packet(session), "cycling_distance_meters")
    assert cell["aggregation"]["value"] == 20
    assert cell["availability_counts"]["retired"] == 1
    assert cell["aggregation"]["excluded_count"] == 1


def test_repeated_identical_payload_is_one_session(projection_database):
    session, paths = projection_database
    _activity(session, paths)
    _activity(session, paths)
    session.commit()
    cell = _metric(_packet(session), "activity_session_count")
    assert cell["aggregation"]["value"] == cell["observed_count"] == 1
    assert cell["snapshot_evidence"]["duplicate_payload_observation_count"] >= 0


def test_sleep_sources_are_independent_sparse_and_zero_is_preserved(projection_database):
    session, paths = projection_database
    _garmin(session, paths, START, seconds=0)
    _garmin(session, paths, END, seconds=3600)
    _google(session, paths, START, minutes="0")
    session.commit()
    packet = _packet(session)
    garmin, google = (_metric(packet, side=i) for i in (0, 1))
    assert garmin["aggregation"]["value"] == 1800
    assert garmin["aggregation"]["eligible_count"] == 2
    assert garmin["aggregation"]["denominator"] == "eligible_saved_nights"
    assert google["aggregation"]["value"] == 0
    assert google["aggregation"]["eligible_count"] == 1
    assert google["availability_counts"]["uncertain"] == 1
    assert google["source_unit"] == "min" and google["unit"] == "seconds"
    assert google["coverage"]["state"] == "unestablished"
    assert packet["deltas"][SLEEP_CODE]["value"] is None


def test_google_only_does_not_require_garmin_or_agreement(projection_database):
    session, paths = projection_database
    _google(session, paths, START)
    session.commit()
    packet = _packet(session)
    assert _metric(packet)["aggregation"]["value"] is None
    assert _metric(packet, side=1)["aggregation"]["value"] == 24600


def test_sleep_full_observation_period_does_not_prove_acquisition(projection_database):
    session, paths = projection_database
    for i in range(7):
        _google(session, paths, START + timedelta(days=i), main="true", nap="false", minutes="60")
    session.commit()
    cell = _metric(_packet(session), side=1)
    assert cell["aggregation"]["value"] == 3600
    assert cell["aggregation"]["eligible_count"] == 7
    assert cell["missing_day_count"] == 0
    assert cell["coverage"]["complete"] is False


@pytest.mark.parametrize(
    "case,reason,eligible",
    [
        ("nap", "google_nap_only", 1),
        ("uncertain", "google_explicit_main_preferred", 1),
        ("two_main", "ambiguous_google_main", 0),
        ("two_uncertain", "ambiguous_google_main", 0),
    ],
)
def test_r05_roles_and_uniqueness_before_scalar_availability(
    projection_database, case, reason, eligible
):
    session, paths = projection_database
    explicit = case != "two_uncertain"
    _google(session, paths, START, name="one", main="true" if explicit else "missing", nap="false")
    _google(
        session,
        paths,
        START,
        name="two",
        main="true" if case == "two_main" else "missing",
        nap="true" if case == "nap" else "false" if case == "two_main" else "missing",
    )
    session.commit()
    cell = _metric(_packet(session), side=1)
    assert cell["observed_count"] == 2
    assert cell["aggregation"]["eligible_count"] == eligible
    assert _reasons(cell)[reason] == (2 if not eligible else 1)


@pytest.mark.parametrize("provider", ["garmin", "google"])
@pytest.mark.parametrize("state", ["missing", "null", "invalid", "wrong_unit"])
def test_sleep_scalar_absence_and_units(projection_database, provider, state):
    session, paths = projection_database
    if provider == "garmin":
        _garmin(session, paths, START)
        model, code = GarminRecordMetric, "sleep_duration_seconds"
    else:
        _google(session, paths, START)
        model, code = GoogleRecordMetric, "sleep_summary_minutes_asleep"
    row = session.scalar(select(model).where(model.metric_code == code))
    if state == "wrong_unit":
        row.unit = "wrong"
    else:
        row.state, row.value_number = state, None
        row.value_text, row.collection_json = None, None
    session.commit()
    cell = _metric(_packet(session), side=int(provider == "google"))
    assert cell["aggregation"]["value"] is None
    assert (
        _reasons(cell)["metric_unit_mismatch" if state == "wrong_unit" else f"metric_{state}"] == 1
    )


def test_google_correction_retired_snapshot_and_wake_date_not_source_date(projection_database):
    session, paths = projection_database
    _google(session, paths, START, name="same", minutes="60")
    _google(session, paths, START, name="corrected", minutes="120")
    rows = list(session.scalars(select(GoogleSourceRecord)))
    assert len(rows) == 2
    rows[0].projection_status = "retired"
    rows[0].retired_at = datetime(2099, 1, 9, tzinfo=UTC)
    rows[0].retire_reason = "superseded_logical_session"
    # Typed wake date controls eligibility, regardless of source record's UTC/local start date.
    for row in rows:
        row.source_local_date = START - timedelta(days=1)
    assert session.scalar(select(GoogleSleepRecord)).wake_date == START
    session.commit()
    cell = _metric(_packet(session), side=1)
    assert cell["aggregation"]["value"] == 7200
    assert cell["availability_counts"]["retired"] == 1
    assert cell["effective_dates"]["min_observed"] == str(START)


def test_multiple_actual_sources_require_selection_and_never_pool(projection_database):
    session, paths = projection_database
    _garmin(session, paths, START)
    _activity(session, paths, attributed=True)
    session.commit()
    packet = _packet(session)
    assert packet["sides"][0]["state"] == "selection_required"
    assert _metric(packet)["aggregation"]["value"] is None
    source = session.scalar(select(GarminSource).where(GarminSource.device_attributed.is_(False)))
    selected = _packet(session, garmin_source_id=source.id)
    assert _metric(selected)["aggregation"]["value"] == 28800
    assert _metric(selected, "activity_session_count")["aggregation"]["value"] is None
    with pytest.raises(ValueError, match="unknown selected"):
        _packet(session, google_source_id=source.id)


@pytest.mark.parametrize(
    "status", ["present", "confirmed_empty", "failed", "unavailable", "unknown"]
)
def test_acquisition_statuses_are_distinct_from_saved_values(projection_database, status):
    session, paths = projection_database
    _activity(session, paths)
    source = session.scalar(select(GarminSource))
    _coverage(session, source, status=status)
    session.commit()
    cell = _metric(_packet(session), "activity_session_count")
    assert cell["aggregation"]["value"] == 1
    assert cell["coverage"]["status_counts"][status] == 7
    assert cell["coverage"]["complete"] is (status == "present")
    if status == "confirmed_empty":
        assert cell["coverage"]["state"] == "contradictory"


def test_provider_wide_google_coverage_is_not_source_completeness(projection_database):
    session, paths = projection_database
    _google(session, paths, START)
    _coverage(session, session.scalar(select(GoogleSource)), scoped=False)
    session.commit()
    assert _metric(_packet(session), side=1)["coverage"]["state"] == "unestablished"


def test_read_only_snapshot_rejects_pending_writes_and_never_opens_payloads(projection_database):
    session, paths = projection_database
    _garmin(session, paths, START)
    session.commit()
    source = session.scalar(select(GarminSource))
    source.device_attributed = False
    with pytest.raises(InvalidRequestError, match="no pending"):
        _packet(session)
    session.rollback()
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        packet = _packet(session)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert _metric(packet)["aggregation"]["value"] == 28800
    assert all(s.lstrip().upper().startswith(("SELECT", "BEGIN")) for s in statements)
    assert not session.new and not session.dirty and not session.deleted


@pytest.mark.parametrize("days", [0, 1, 6, 8, 29, 31, True, 7.0])
def test_unsupported_windows_fail_before_reads(projection_database, days):
    session, _ = projection_database
    with pytest.raises(ValueError, match="7 or 30"):
        PeriodSummaryService(session).build(end_date=END, days=days)


@pytest.mark.parametrize("provider", ["garmin", "google"])
def test_missing_wake_date_is_disclosed_not_silently_lost(projection_database, provider):
    session, paths = projection_database
    if provider == "garmin":
        _garmin(session, paths, START)
        model = GarminSleepRecord
    else:
        _google(session, paths, START)
        model = GoogleSleepRecord
    session.scalar(select(model)).wake_date = None
    session.commit()
    cell = _metric(_packet(session), side=int(provider == "google"))
    assert cell["observed_count"] == 1
    assert cell["aggregation"]["value"] is None
    assert _reasons(cell)["wake_date_missing"] == 1


def test_sleep_read_limit_never_selects_a_prefix(projection_database, monkeypatch):
    session, paths = projection_database
    _google(session, paths, START, name="one")
    _google(session, paths, START, name="two")
    session.commit()
    monkeypatch.setattr("healthcheck.analytics.sleep_source_view.MAX_SOURCE_SLEEP_RECORDS", 1)
    cell = _metric(_packet(session), side=1)
    assert cell["aggregation"]["value"] is None
    assert _reasons(cell)["read_limit_exceeded"] == 2


def test_proven_empty_activity_count_is_distinct_from_unknown(projection_database):
    session, paths = projection_database
    _garmin(session, paths, START)
    source = session.scalar(select(GarminSource))
    session.commit()
    assert _metric(_packet(session), "activity_session_count")["aggregation"]["value"] is None
    _coverage(session, source, status="confirmed_empty")
    session.commit()
    cell = _metric(_packet(session), "activity_session_count")
    assert cell["aggregation"]["value"] == 0
    assert cell["aggregation"]["eligible_count"] == 0
    assert cell["coverage"]["complete"] is True


@pytest.mark.parametrize("kind", [None, "", " ", "\t\r\n"])
def test_unknown_activity_type_never_proves_empty_tennis(projection_database, kind):
    session, paths = projection_database
    _activity(session, paths, kind=kind)
    _coverage(session, session.scalar(select(GarminSource)))
    session.commit()
    packet = _packet(session)
    assert _metric(packet, "activity_session_count")["aggregation"]["value"] == 1
    assert _metric(packet, "activity_type_counts")["aggregation"]["value"] == {"unknown": 1}
    for code in ("tennis_session_count", "tennis_duration_seconds", "cycling_distance_meters"):
        cell = _metric(packet, code)
        assert cell["coverage"]["complete"] is True
        assert cell["aggregation"]["value"] is None
        assert cell["observed_count"] == 1
        assert _reasons(cell)["activity_type_missing"] == 1


@pytest.mark.parametrize("provider", ["garmin", "google"])
@pytest.mark.parametrize("days", [7, 30])
def test_missing_dates_distinguish_absence_from_ineligible_observations(
    projection_database, provider, days
):
    session, paths = projection_database
    start = END - timedelta(days=days - 1)
    excluded_day = start + timedelta(days=2)
    persist = _garmin if provider == "garmin" else _google
    persist(session, paths, start)
    persist(session, paths, excluded_day)
    persist(session, paths, END)
    model = GarminSourceRecord if provider == "garmin" else GoogleSourceRecord
    typed = GarminSleepRecord if provider == "garmin" else GoogleSleepRecord
    session.scalar(
        select(model)
        .join(typed, typed.record_id == model.id)
        .where(typed.wake_date == excluded_day)
    ).record_status = "invalid"
    session.commit()
    packet = PeriodSummaryService(session).build(end_date=END, days=days)
    cell = _metric(packet, side=int(provider == "google"))
    assert cell["observed_calendar_dates"] == [str(start), str(excluded_day), str(END)]
    assert cell["eligible_dates"] == [str(start), str(END)]
    assert cell["missing_dates"] == [
        str(start + timedelta(days=i))
        for i in range(days)
        if start + timedelta(days=i) not in {start, excluded_day, END}
    ]
    assert cell["missing_day_count"] == days - 3
    assert str(excluded_day) not in cell["missing_dates"]


def test_multiple_google_sources_remain_separate_even_with_same_wake_date(projection_database):
    session, paths = projection_database
    _google(session, paths, START, source="synthetic-source-one", minutes="60")
    _google(session, paths, START, source="synthetic-source-two", minutes="120")
    session.commit()
    packet = _packet(session)
    assert packet["sides"][1]["state"] == "selection_required"
    assert _metric(packet, side=1)["aggregation"]["value"] is None
    sources = list(session.scalars(select(GoogleSource).order_by(GoogleSource.source_instance_id)))
    values = [
        _metric(_packet(session, google_source_id=s.id), side=1)["aggregation"]["value"]
        for s in sources
    ]
    assert values == [3600, 7200]


def test_invalid_record_and_partial_observation_are_disclosed(projection_database):
    session, paths = projection_database
    _activity(session, paths, count=2, distance=10)
    records = list(
        session.scalars(select(GarminSourceRecord).order_by(GarminSourceRecord.external_record_id))
    )
    records[0].record_status = "invalid"
    records[1].record_status = "partial"
    session.commit()
    cell = _metric(_packet(session), "cycling_distance_meters")
    assert cell["observed_count"] == 2
    assert cell["aggregation"]["value"] == 10
    assert cell["aggregation"]["eligible_count"] == 1
    assert cell["availability_counts"]["partial"] == 1
    assert _reasons(cell)["record_invalid"] == 1


@pytest.mark.parametrize(
    "case,reason",
    [
        ("dates", "different_observed_windows_or_denominators"),
        ("denominator", "different_observed_windows_or_denominators"),
        ("count", "different_observed_windows_or_denominators"),
        ("unit", "incompatible_units"),
        ("meaning", "incompatible_metric_meaning"),
        ("coverage", "acquisition_coverage_not_established"),
        ("partial", "partial_uncertain_or_excluded_inputs"),
        ("uncertain", "partial_uncertain_or_excluded_inputs"),
    ],
)
def test_delta_requires_compatible_source_inputs(projection_database, case, reason):
    session, paths = projection_database
    _garmin(session, paths, START, seconds=3600)
    _google(session, paths, START, main="true", nap="false", minutes="120")
    session.commit()
    packet = _packet(session)
    left, right = (_metric(packet, side=i) for i in (0, 1))
    # Isolate compatibility decisions with synthetic complete coverage. Real
    # provider-wide Google coverage remains unestablished in the service tests.
    for cell in (left, right):
        cell["coverage"]["complete"] = True
        cell["availability_counts"]["partial"] = 0
    assert PeriodSummaryService._delta(left, right)["value"] == 3600
    if case == "dates":
        right["eligible_dates"] = [str(END)]
    elif case == "denominator":
        right["aggregation"]["denominator"] = "calendar_days"
    elif case == "count":
        right["aggregation"]["eligible_count"] = 2
    elif case == "unit":
        right["unit"] = "min"
    elif case == "meaning":
        right["canonical_metric_code"] = "time_in_bed"
    elif case == "coverage":
        right["coverage"]["complete"] = False
    else:
        right["availability_counts"][case] = 1
    result = PeriodSummaryService._delta(left, right)
    assert result["value"] is None and result["reason"] == reason
