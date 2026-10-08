"""Synthetic production-persistence negatives for the #317 source-only read."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import event, select

from healthcheck.analytics.sleep_metrics import read_persisted_sleep_metric_projection
from healthcheck.analytics.sleep_pairing import read_persisted_sleep_pairing
from healthcheck.analytics.sleep_source_view import read_source_sleep_night
from healthcheck.db.engine import create_sqlite_engine, session_scope
from healthcheck.db.models import (
    GarminRecordMetric,
    GarminSourceRecord,
    GoogleRecordMetric,
    GoogleSleepFieldState,
    GoogleSleepInterval,
    GoogleSourceRecord,
)
from healthcheck.google.contracts import (
    FAMILY_GOOGLE_WEARABLES,
    GoogleQueryContext,
    GoogleQueryMode,
    GoogleSourceIdentity,
    GoogleSourceKind,
    GoogleStream,
)
from healthcheck.google.normalization import normalize_google_payload
from healthcheck.google.persistence import GooglePersistenceRepository
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from test_garmin_query_dashboard import _ui
from test_google_daily_vitals import seed_google_daily_vitals
from test_sleep_metrics import (
    _google_sleep_payload,
    _persist_garmin,
    _persist_google,
    _stage,
)
from test_sleep_metrics import projection_database as projection_database
from test_sleep_owner_ui import client_for

WAKE_DATE = date(2099, 1, 2)


def _read(session, provider="google", wake_date=WAKE_DATE, **kwargs):
    return read_source_sleep_night(session, provider=provider, wake_date=wake_date, **kwargs)


def _single(session, provider="google"):
    result = _read(session, provider)
    assert len(result["sources"]) == 1
    assert result["sources"][0]["ambiguous"] is False
    return result["sources"][0]["summary"]


def _persist_identity(session, paths, payload, identity, family=None):
    normalized = normalize_google_payload(
        payload, stream=GoogleStream.SLEEP, source_identity=identity,
        query=GoogleQueryContext(query_mode=GoogleQueryMode.LIST, data_source_family=family),
    )
    return GooglePersistenceRepository(
        session, payload_store=ContentAddressedGooglePayloadStore(paths.root / "google-artifacts")
    ).persist_result(normalized, payload=payload, received_at=datetime(2099, 1, 2, tzinfo=UTC))


def test_unpaired_garmin_has_native_naps_and_independent_timing_and_stages(projection_database):
    session, paths = projection_database
    _persist_garmin(session, paths)
    session.commit()
    assert read_persisted_sleep_pairing(session).pairs == ()
    night = _single(session, "garmin")
    cells = night["metrics"]
    assert cells["sleep_duration_asleep_seconds"]["value"] == 28800
    assert cells["sleep_score"]["value"] == 82
    assert cells["nap_duration_seconds"]["value"] == 900
    assert cells["sleep_stage_deep_seconds"]["value"] == 5400
    assert cells["sleep_stage_light_seconds"]["value"] == 4500
    assert cells["sleep_start_at"]["eligible"] is False  # parent is date-only
    assert cells["sleep_start_at"]["reason"] == "timing_precision_unavailable"
    assert cells["sleep_end_at"]["value"] == "2099-01-02T06:45:00Z"
    assert night["temporal_evidence"]["source_local_date"] == "2099-01-02"
    assert _read(session, "garmin", date(2099, 1, 3))["sources"] == []


def test_unpaired_google_uses_own_boundaries_without_creating_score_or_pair(projection_database):
    session, paths = projection_database
    _persist_google(session, paths, payload=_google_sleep_payload(
        stages_status="SUCCEEDED", stages=[
            _stage("2099-01-01T22:00:00Z", "2099-01-01T23:00:00Z", "LIGHT"),
            _stage("2099-01-01T23:00:00Z", "2099-01-02T00:00:00Z", "DEEP"),
        ],
    ))
    session.commit()
    night = _single(session)
    assert read_persisted_sleep_pairing(session).pairs == ()
    assert night["metrics"]["sleep_duration_asleep_seconds"]["value"] == 24600
    assert night["metrics"]["sleep_time_in_bed_seconds"]["value"] == 25200
    assert night["metrics"]["sleep_start_at"]["value"] == "2099-01-01T22:00:00Z"
    assert night["metrics"]["sleep_end_at"]["value"] == "2099-01-02T05:00:00Z"
    assert night["metrics"]["sleep_stage_light_seconds"]["value"] == 3600
    assert "sleep_score" not in night["metrics"]
    assert "nap_duration_seconds" not in night["metrics"]


@pytest.mark.parametrize("state,value,unit,eligible,reason", [
    ("value", 0, "min", True, None),
    ("missing", None, "min", False, "metric_missing"),
    ("null", None, "min", False, "metric_null"),
    ("invalid", None, "min", False, "metric_invalid"),
    ("value", 12, "seconds", False, "metric_unit_mismatch"),
])
def test_zero_missing_null_invalid_and_unit_mismatch_remain_independent(
    projection_database, state, value, unit, eligible, reason,
):
    session, paths = projection_database
    _persist_google(session, paths, payload=_google_sleep_payload())
    row = session.scalar(select(GoogleRecordMetric).where(
        GoogleRecordMetric.metric_code == "sleep_summary_minutes_asleep"
    ))
    row.state, row.value_number, row.unit = state, value, unit
    row.value_text = None
    session.commit()
    cells = _single(session)["metrics"]
    cell = cells["sleep_duration_asleep_seconds"]
    assert cell["state"] == state
    assert cell["eligible"] is eligible
    assert cell["reason"] == reason
    assert cell["is_zero"] is eligible
    assert cells["sleep_start_at"]["eligible"] is True


@pytest.mark.parametrize("sleep_type,status,stages,reason", [
    ("CLASSIC", "SUCCEEDED", ["LIGHT"], "classic_sleep_excludes_stage_metric"),
    ("CLASSIC", "SUCCEEDED", ["ASLEEP"], "classic_sleep_excludes_stage_metric"),
    ("STAGES", "PROCESSING", ["LIGHT"], "stages_status_not_succeeded"),
    ("STAGES", "SUCCEEDED", [], "typed_stage_collection_required"),
    ("STAGES", "SUCCEEDED", ["RESTLESS"], "stage_type_unmapped"),
])
def test_classic_summary_only_unmapped_and_processing_stages_fail_closed(
    projection_database, sleep_type, status, stages, reason,
):
    session, paths = projection_database
    _persist_google(session, paths, payload=_google_sleep_payload(
        sleep_type=sleep_type, stages_status=status,
        stages=[_stage("2099-01-01T22:00:00Z", "2099-01-01T23:00:00Z", t) for t in stages],
        summary_stages=[{"type": "LIGHT", "minutes": "60", "count": "1"}],
    ))
    session.commit()
    cells = _single(session)["metrics"]
    assert cells["sleep_stage_light_seconds"]["eligible"] is False
    assert cells["sleep_stage_light_seconds"]["reason"] == reason
    assert cells["sleep_duration_asleep_seconds"]["eligible"] is True
    assert cells["sleep_time_in_bed_seconds"]["eligible"] is True
    if not stages:
        assert cells["sleep_stage_light_seconds"]["value"] == 3600  # retained, ineligible


@pytest.mark.parametrize("provider", ["google", "garmin"])
def test_partial_or_invalid_stage_evidence_does_not_erase_duration(projection_database, provider):
    session, paths = projection_database
    if provider == "garmin":
        _persist_garmin(session, paths)
        row = session.scalar(select(GarminRecordMetric).where(
            GarminRecordMetric.metric_code == "sleep_stages"
        ))
        row.reason = "partial_collection"
    else:
        _persist_google(session, paths, payload=_google_sleep_payload(stages_status="SUCCEEDED"))
        state = session.scalar(select(GoogleSleepFieldState))
        state.sleep_stages_state = "invalid"
    session.commit()
    cells = _single(session, provider)["metrics"]
    assert cells["sleep_stage_light_seconds"]["eligible"] is False
    assert cells["sleep_duration_asleep_seconds"]["eligible"] is True


@pytest.mark.parametrize("main,nap,reason,selection", [
    (True, True, "google_nap_only", None),
    (False, False, "google_non_main", ""),
    (True, None, "google_nap_state_unknown", None),
    (None, False, None, "fallback_main"),
])
def test_role_uncertainty_is_not_promoted_to_confirmed_main(
    projection_database, main, nap, reason, selection,
):
    session, paths = projection_database
    payload = _google_sleep_payload()
    metadata = payload["dataPoints"][0]["sleep"]["metadata"]
    for key, value in (("main", main), ("nap", nap)):
        if value is None:
            metadata.pop(key)
        else:
            metadata[key] = value
    _persist_google(session, paths, payload=payload)
    session.commit()
    night = _single(session)
    assert night["role"]["reason"] == reason
    assert night["role"]["selection"] == selection
    assert night["metrics"]["sleep_duration_asleep_seconds"]["eligible"] is (reason is None)
    assert night["role"]["main_value"] is main


def test_competing_google_sessions_have_no_night_winner_or_pool(projection_database):
    session, paths = projection_database
    for name in ("first", "second"):
        _persist_google(session, paths, payload=_google_sleep_payload(name=name))
    session.commit()
    source = _read(session)["sources"][0]
    assert source["ambiguous"] is True
    assert source["summary"] is None
    assert len(source["sessions"]) == 2
    assert len({s["record_id"] for s in source["sessions"]}) == 2
    assert all(s["metrics"]["sleep_duration_asleep_seconds"]["value"] == 24600
               for s in source["sessions"])


def test_device_family_and_unattributed_sources_stay_separate(projection_database):
    session, paths = projection_database
    _persist_google(session, paths, payload=_google_sleep_payload())
    for instance, kind, family in (
        (FAMILY_GOOGLE_WEARABLES, GoogleSourceKind.FAMILY_AGGREGATE, FAMILY_GOOGLE_WEARABLES),
        ("unattributed", GoogleSourceKind.DATA_SOURCE, None),
    ):
        payload = _google_sleep_payload(name=instance)
        payload["dataPoints"][0].pop("dataSource")
        _persist_identity(session, paths, payload, GoogleSourceIdentity(
            source_kind=kind, source_instance_id=instance,
        ), family)
    session.commit()
    sources = _read(session)["sources"]
    assert len(sources) == 3
    assert len({s["source"]["source_id"] for s in sources}) == 3
    by_instance = {s["source"]["source_instance_id"]: s for s in sources}
    unattributed = by_instance["unattributed"]["summary"]
    assert unattributed["source_eligibility"]["eligible"] is False
    assert unattributed["metrics"]["sleep_duration_asleep_seconds"]["eligible"] is False
    assert by_instance[FAMILY_GOOGLE_WEARABLES]["summary"]["source_eligibility"]["eligible"]


def test_local_precision_and_dst_offsets_are_not_replaced_by_host_offset(projection_database):
    session, paths = projection_database
    payload = _google_sleep_payload()
    payload["dataPoints"][0]["sleep"]["interval"] = {
        "startTime": "2026-10-24T20:00:00Z", "startUtcOffset": "7200s",
        "endTime": "2026-10-25T06:00:00Z", "endUtcOffset": "3600s",
        "civilStartTime": {"date": "2026-10-24", "time": {"hours": 22}},
        "civilEndTime": {"date": "2026-10-25", "time": {"hours": 7}},
    }
    _persist_google(session, paths, payload=payload)
    interval = session.scalar(select(GoogleSleepInterval).where(
        GoogleSleepInterval.interval_kind == "sleep_session"
    ))
    interval.start_precision = "local"
    session.commit()
    cells = _read(session, wake_date=date(2026, 10, 25))["sources"][0]["summary"]["metrics"]
    assert cells["sleep_start_at"]["eligible"] is False
    assert cells["sleep_time_in_bed_seconds"]["eligible"] is False
    interval.start_precision = "instant"
    session.commit()
    cells = _read(session, wake_date=date(2026, 10, 25))["sources"][0]["summary"]["metrics"]
    assert cells["sleep_start_at"]["value"] == "2026-10-24T20:00:00Z"
    assert cells["sleep_end_at"]["value"] == "2026-10-25T06:00:00Z"
    assert interval.start_utc_offset_minutes == 120
    assert interval.end_utc_offset_minutes == 60
    snapshot = cells["sleep_start_at"]["evidence"]["interval_snapshots"][0]
    assert snapshot["start_temporal"]["source_utc_offset_minutes"] == 120
    assert snapshot["end_temporal"]["source_utc_offset_minutes"] == 60
    assert snapshot["start_temporal"]["source_local_timestamp"] == "2026-10-24T22:00:00"
    assert snapshot["end_temporal"]["source_local_timestamp"] == "2026-10-25T07:00:00"


def test_read_is_bounded_current_exact_date_and_does_not_change_comparison(
    projection_database, monkeypatch,
):
    session, paths = projection_database
    _persist_garmin(session, paths)
    _persist_google(session, paths, payload=_google_sleep_payload())
    session.commit()
    before = read_persisted_sleep_metric_projection(session).as_dict()
    statements = []
    event.listen(session.get_bind(), "before_cursor_execute",
                 lambda _c, _cur, sql, *_a: statements.append(sql))
    for provider in ("garmin", "google"):
        view = _single(session, provider)
        for projected in before["projections"]:
            code = projected["metric_code"]
            if code not in view["metrics"]:
                continue
            cell = view["metrics"][code]
            expected = projected[provider]
            assert (cell["value"], cell["state"], cell["eligible"], cell["reason"]) == (
                expected["value"], expected["state"], expected["eligible"], expected["reason"]
            )
    assert read_persisted_sleep_metric_projection(session).as_dict() == before
    assert not any(sql.lstrip().upper().startswith(("UPDATE", "DELETE", "INSERT", "CREATE"))
                   for sql in statements)
    assert '"dataPoints":' not in json.dumps(_read(session))  # field-path locators are permitted
    assert _read(session, source_id="not-a-source")["sources"] == []
    assert _read(session, wake_date=date(2099, 1, 3))["sources"] == []
    monkeypatch.setattr("healthcheck.analytics.sleep_source_view.MAX_SOURCE_SLEEP_RECORDS", 0)
    assert _read(session)["state"] == "read_limit_exceeded"
    assert _read(session)["sources"] == []
    google = session.scalar(select(GoogleSourceRecord))
    google.projection_status = "retired"
    google.retired_at = datetime(2099, 1, 3, tzinfo=UTC)
    session.commit()
    assert _read(session)["state"] == "no_records"


def test_provenance_failure_keeps_value_ineligible(projection_database):
    session, paths = projection_database
    _persist_garmin(session, paths)
    session.commit()
    record = session.scalar(select(GarminSourceRecord))
    record.raw_payload_id = "missing-synthetic-payload"
    # Loaded evidence can become unavailable; never persist an invalid FK.
    with session.no_autoflush:
        night = _single(session, "garmin")
    duration = night["metrics"]["sleep_duration_asleep_seconds"]
    assert duration["value"] == 28800
    assert duration["eligible"] is False
    assert duration["reason"] == "raw_payload_missing"


def test_google_source_page_has_unpaired_sleep_and_separate_dated_vitals(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    seed_google_daily_vitals(paths)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            _persist_google(session, paths, payload=_google_sleep_payload())
    finally:
        engine.dispose()
    with client_for(app) as client:
        response = client.get("/sleep?view=google&wake_date=2099-01-02")
        missing = client.get("/sleep?view=google&wake_date=2099-01-03")
    assert response.status_code == missing.status_code == 200
    primary, technical = response.text.split('<details class="card owner-details sleep-technical"')
    sleep, vitals = primary.split('<section class="card brief-controls" data-google-vitals>')
    assert "6 ч 50 мин" in sleep
    assert "2099-01-01T22:00:00Z" in sleep
    assert "42.5" not in sleep
    assert "42.5" in vitals and "2 января 2099" in vitals
    assert "summary_only" in technical
    assert "Совместимой оценки сна Google нет" in sleep
    assert "За эту дату нет сохранённых сессий Google" in missing.text
    assert "6 ч 50 мин" not in missing.text.split('data-google-vitals>')[0]
