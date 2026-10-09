"""Synthetic production-persistence negatives for the #317 source-only read."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import event, select

from healthcheck.analytics.sleep_metrics import read_persisted_sleep_metric_projection
from healthcheck.analytics.sleep_pairing import (
    ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS,
    SleepPairingQuery,
    read_persisted_sleep_pairing,
)
from healthcheck.analytics.sleep_source_view import (
    read_source_sleep_night,
    read_source_sleep_range,
    resolve_source_sleep_point,
)
from healthcheck.db.engine import create_sqlite_engine, session_scope
from healthcheck.db.models import (
    GarminPayloadObservation,
    GarminRecordMetric,
    GarminSleepRecord,
    GarminSource,
    GarminSourceRecord,
    GoogleRecordMetric,
    GoogleRecordSourceEvidence,
    GoogleSleepFieldState,
    GoogleSleepInterval,
    GoogleSleepRecord,
    GoogleSourceRecord,
)
from healthcheck.garmin.normalization import normalize_garmin_payload
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.google.contracts import (
    FAMILY_ALL_SOURCES,
    FAMILY_GOOGLE_SOURCES,
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
    GARMIN_SLEEP_FIXTURE,
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


def _persist_account_garmin(session, paths):
    payload = json.loads(GARMIN_SLEEP_FIXTURE.read_text(encoding="utf-8"))
    payload["device"] = {"attributed": False}
    return GarminPersistenceRepository(
        session, payload_store=ContentAddressedGarminPayloadStore(paths.root / "garmin-artifacts")
    ).persist_result(normalize_garmin_payload(payload), payload=json.dumps(payload).encode())


def test_garmin_account_without_device_keeps_own_fields_and_legacy_exclusion(projection_database):
    session, paths = projection_database
    _persist_account_garmin(session, paths)
    session.commit()
    result = _read(session, "garmin")
    source = result["sources"][0]["source"]
    assert source["device_attributed"] is False
    assert source["device_code"] is source["device_model"] is None
    night = result["sources"][0]["summary"]
    assert night["source_eligibility"]["cohort"] == ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS
    assert night["source_eligibility"]["source_class"] == "garmin_account"
    for code, value in (
        ("sleep_duration_asleep_seconds", 28800), ("sleep_score", 82),
        ("nap_duration_seconds", 900), ("sleep_stage_deep_seconds", 5400),
        ("sleep_end_at", "2099-01-02T06:45:00Z"),
    ):
        assert night["metrics"][code]["eligible"] is True
        assert night["metrics"][code]["value"] == value
    legacy = read_persisted_sleep_pairing(session)
    assert legacy.pairs == ()
    assert "garmin_not_target_device" in {e.reason for e in legacy.exclusions}


def test_identified_non_fitbit_account_does_not_create_device_agreement(projection_database):
    session, paths = projection_database
    _persist_account_garmin(session, paths)
    payload = _google_sleep_payload(stages_status="SUCCEEDED", stages=[
        _stage("2099-01-01T22:00:00Z", "2099-01-01T23:00:00Z", "LIGHT"),
    ])
    payload["dataPoints"][0]["dataSource"]["platform"] = "health_connect"
    payload["dataPoints"][0]["dataSource"]["device"]["manufacturer"] = "Synthetic"
    payload["dataPoints"][0]["dataSource"]["device"]["displayName"] = "Synthetic Watch"
    identity = GoogleSourceIdentity(
        source_kind=GoogleSourceKind.DATA_SOURCE,
        source_instance_id="users/me/dataSources/synthetic-account-watch",
        platform="health_connect",
    )
    _persist_identity(session, paths, payload, identity)
    session.commit()
    # Reading source views must not change any accepted comparison/cohort packet.
    before = {
        cohort: read_persisted_sleep_metric_projection(
            session, SleepPairingQuery(cohort=cohort)
        ).as_dict()
        for cohort in ("all", "device_pair", "family_pair", ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS)
    }
    night = _single(session)
    source = _read(session)["sources"][0]["source"]
    assert source["source_instance_id"] == identity.source_instance_id
    assert source["platform"] == "health_connect"
    decision = night["source_eligibility"]
    assert decision["eligible"] is True
    assert decision["cohort"] == ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS
    assert decision["basis"]["device_agreement_eligibility"]["eligible"] is False
    for code in ("sleep_duration_asleep_seconds", "sleep_start_at", "sleep_stage_light_seconds"):
        assert night["metrics"][code]["eligible"] is True
    assert "sleep_score" not in night["metrics"]
    assert read_persisted_sleep_pairing(session).pairs == ()
    assert len(read_persisted_sleep_pairing(
        session, SleepPairingQuery(cohort=ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS)
    ).pairs) == 1
    for cohort, packet in before.items():
        assert read_persisted_sleep_metric_projection(
            session, SleepPairingQuery(cohort=cohort)
        ).as_dict() == packet


@pytest.mark.parametrize("case,reason", [
    ("all_family", "google_all_sources_excluded"),
    ("google_family", "google_sources_excluded"),
    ("unattributed", "google_source_unattributed"),
    ("conflict", "google_source_device_conflict"),
    ("invalid_evidence", "google_record_source_evidence_invalid"),
    ("invalid_record", "google_record_invalid"),
])
def test_account_google_exclusions_do_not_disappear(projection_database, case, reason):
    session, paths = projection_database
    payload = _google_sleep_payload()
    family = {"all_family": FAMILY_ALL_SOURCES, "google_family": FAMILY_GOOGLE_SOURCES}.get(case)
    if family or case == "unattributed":
        payload["dataPoints"][0].pop("dataSource")
        _persist_identity(session, paths, payload, GoogleSourceIdentity(
            source_kind=(
                GoogleSourceKind.FAMILY_AGGREGATE if family else GoogleSourceKind.DATA_SOURCE
            ),
            source_instance_id=family or "unattributed",
        ), family)
    else:
        if case == "conflict":
            payload["dataPoints"][0]["dataSource"]["device"]["manufacturer"] = "Synthetic Other"
        _persist_google(session, paths, payload=payload)
        if case == "invalid_evidence":
            row = session.scalar(select(GoogleRecordSourceEvidence))
            row.evidence_json = '{"state":"invalid"}'
        elif case == "invalid_record":
            session.scalar(select(GoogleSourceRecord)).record_status = "invalid"
    session.commit()
    night = _single(session)
    assert night["reason"] == reason
    assert all(not c["eligible"] for c in night["metrics"].values())
    assert night["metrics"]["sleep_duration_asleep_seconds"]["value"] == 24600


@pytest.mark.parametrize("rejection", ["provider", "source_kind", "invalid_record"])
def test_native_garmin_fields_share_account_record_gate(projection_database, rejection):
    session, paths = projection_database
    _persist_account_garmin(session, paths)
    session.commit()
    source = session.scalar(select(GarminSource))
    if rejection == "provider":
        source.provider_code = "synthetic_other_provider"
    elif rejection == "source_kind":
        source.source_kind = "unattributed"
    else:
        session.scalar(select(GarminSourceRecord)).record_status = "invalid"
    # Source identities are append-only. Model rejected loaded evidence without
    # weakening persistence guards or writing a mutated source identity.
    with session.no_autoflush:
        night = _single(session, "garmin")
    expected = "garmin_record_invalid" if rejection == "invalid_record" else (
        "garmin_account_source_ineligible"
    )
    for code, value in (("sleep_score", 82), ("nap_duration_seconds", 900),
                        ("sleep_duration_asleep_seconds", 28800)):
        cell = night["metrics"][code]
        assert cell["eligible"] is False
        assert cell["reason"] == expected
        assert cell["value"] == value


@pytest.mark.parametrize("code", ["sleep_score", "nap_duration_seconds"])
@pytest.mark.parametrize("state", ["value", "missing", "null", "invalid"])
def test_native_garmin_zero_and_absence_are_independent(projection_database, code, state):
    session, paths = projection_database
    _persist_account_garmin(session, paths)
    row = session.scalar(select(GarminRecordMetric).where(GarminRecordMetric.metric_code == code))
    row.state, row.value_number = state, 0 if state == "value" else None
    session.commit()
    cells = _single(session, "garmin")["metrics"]
    assert cells[code]["state"] == state
    assert cells[code]["eligible"] is (state == "value")
    assert cells[code]["is_zero"] is (state == "value")
    assert cells[code]["value"] == (0 if state == "value" else None)
    other = "nap_duration_seconds" if code == "sleep_score" else "sleep_score"
    assert cells[other]["eligible"] is True


@pytest.mark.parametrize("failure,reason", [
    ("missing", "raw_payload_missing"), ("mismatch", "observation_provenance_mismatch"),
])
def test_native_garmin_provenance_failure_is_not_promoted(projection_database, failure, reason):
    session, paths = projection_database
    _persist_account_garmin(session, paths)
    session.commit()
    if failure == "missing":
        session.scalar(select(GarminSourceRecord)).raw_payload_id = "missing-synthetic-payload"
    else:
        session.scalar(select(GarminPayloadObservation)).garmin_source_id = "other-synthetic-source"
    # Model unavailable/mismatched loaded evidence without writing invalid foreign keys.
    with session.no_autoflush:
        cells = _single(session, "garmin")["metrics"]
    for code, value in (("sleep_score", 82), ("nap_duration_seconds", 900)):
        assert cells[code]["eligible"] is False
        assert cells[code]["reason"] == reason
        assert cells[code]["value"] == value


@pytest.mark.parametrize("failure", ["source", "record", "provenance"])
def test_garmin_primary_table_respects_source_view_gate(tmp_path, monkeypatch, failure):
    app, _settings, paths = _ui(tmp_path)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            _persist_account_garmin(session, paths)
    finally:
        engine.dispose()

    def read_rejected_evidence(session, **kwargs):
        # The legacy scalar read has valid values. Only the subsequent source
        # adapter observes this modeled eligibility/provenance failure.
        if failure == "source":
            row, attr, value = session.scalar(select(GarminSource)), "source_kind", "unattributed"
        else:
            row = session.scalar(select(GarminSourceRecord))
            attr, value = ("record_status", "invalid") if failure == "record" else (
                "raw_payload_id", "missing-synthetic-payload"
            )
        original = getattr(row, attr)
        try:
            setattr(row, attr, value)
            with session.no_autoflush:
                return read_source_sleep_night(session, **kwargs)
        finally:
            setattr(row, attr, original)

    monkeypatch.setattr("healthcheck.web.pages.read_source_sleep_night", read_rejected_evidence)
    with client_for(app) as client:
        response = client.get("/sleep?wake_date=2099-01-02")
    assert response.status_code == 200
    primary = response.text.split('<details class="card owner-details sleep-technical"')[0]
    assert "data-night-row" in primary
    assert "8 ч 0 мин" not in primary
    assert "82 баллы" not in primary
    assert "0 ч 15 мин" not in primary
    assert primary.count('data-owner-state="unavailable"') >= 3


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


@pytest.mark.parametrize("main", ["missing", "null", "invalid", "false", "true"])
@pytest.mark.parametrize("nap", ["missing", "null", "invalid", "false", "true"])
def test_role_uncertainty_is_not_promoted_to_confirmed_main(
    projection_database, main, nap,
):
    session, paths = projection_database
    payload = _google_sleep_payload()
    metadata = payload["dataPoints"][0]["sleep"]["metadata"]
    values = {"null": None, "invalid": "unknown", "false": False, "true": True}
    for key, state in (("main", main), ("nap", nap)):
        if state == "missing":
            metadata.pop(key)
        else:
            metadata[key] = values[state]
    _persist_google(session, paths, payload=payload)
    session.commit()
    night = _single(session)
    explicit_nap = nap == "true"
    explicit_main = main == "true" and nap == "false"
    assert night["role"]["reason"] == ("google_nap_only" if explicit_nap else None)
    assert night["role"]["selection"] == (
        "" if explicit_nap else "explicit_main" if explicit_main else "single_uncertain_session"
    )
    for key, state in (("main", main), ("nap", nap)):
        assert night["role"][key + "_state"] == (
            "value" if state in {"true", "false"} else state
        )
        assert night["role"][key + "_value"] is (
            values[state] if state in {"true", "false"} else None
        )
    for code in ("sleep_duration_asleep_seconds", "sleep_start_at", "sleep_end_at"):
        assert night["metrics"][code]["eligible"] is not explicit_nap


def test_competing_google_sessions_have_no_night_winner_or_pool(projection_database):
    session, paths = projection_database
    for name in ("first", "second", "nap"):
        payload = _google_sleep_payload(name=name)
        if name == "first":
            payload["dataPoints"][0]["sleep"]["metadata"]["main"] = False
            payload["dataPoints"][0]["sleep"]["metadata"].pop("nap")
        elif name == "nap":
            payload["dataPoints"][0]["sleep"]["metadata"]["nap"] = True
        _persist_google(session, paths, payload=payload)
    session.commit()
    source = _read(session)["sources"][0]
    assert source["ambiguous"] is True
    assert source["summary"] is None
    assert len(source["sessions"]) == 3
    assert len({s["record_id"] for s in source["sessions"]}) == 3
    assert all(s["metrics"]["sleep_duration_asleep_seconds"]["value"] == 24600
               for s in source["sessions"])
    assert {s["role"]["selection"] for s in source["sessions"]} == {
        "explicit_main", "single_uncertain_session", "",
    }
    assert sum(s["metrics"]["sleep_duration_asleep_seconds"]["eligible"]
               for s in source["sessions"]) == 2


def test_device_family_and_unattributed_sources_stay_separate(projection_database):
    session, paths = projection_database
    _persist_google(session, paths, payload=_google_sleep_payload())
    for instance, kind, family in (
        (FAMILY_GOOGLE_WEARABLES, GoogleSourceKind.FAMILY_AGGREGATE, FAMILY_GOOGLE_WEARABLES),
        ("unattributed", GoogleSourceKind.DATA_SOURCE, None),
        ("users/me/dataSources/synthetic-account", GoogleSourceKind.DATA_SOURCE, None),
    ):
        payload = _google_sleep_payload(name=instance)
        payload["dataPoints"][0].pop("dataSource")
        _persist_identity(session, paths, payload, GoogleSourceIdentity(
            source_kind=kind, source_instance_id=instance,
        ), family)
    session.commit()
    sources = _read(session)["sources"]
    assert len(sources) == 4
    assert len({s["source"]["source_id"] for s in sources}) == 4
    by_instance = {s["source"]["source_instance_id"]: s for s in sources}
    unattributed = by_instance["unattributed"]["summary"]
    assert unattributed["source_eligibility"]["eligible"] is False
    assert unattributed["metrics"]["sleep_duration_asleep_seconds"]["eligible"] is False
    assert by_instance[FAMILY_GOOGLE_WEARABLES]["summary"]["source_eligibility"]["eligible"]
    account = by_instance["users/me/dataSources/synthetic-account"]["summary"]
    assert account["source_eligibility"]["eligible"] is True
    assert account["metrics"]["sleep_duration_asleep_seconds"]["eligible"] is True
    assert all(not s["ambiguous"] for s in sources)  # separate source summaries, no pooling


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


def _range(session, provider="google", wake_date=WAKE_DATE, days=7, **kwargs):
    return read_source_sleep_range(
        session, provider=provider, wake_date=wake_date, days=days, **kwargs
    )


def _point(packet, index=-1):
    assert len(packet["series"]) == 1
    return packet["series"][0]["points"][index]


@pytest.mark.parametrize("provider", ["garmin", "google"])
@pytest.mark.parametrize("days", [7, 30])
def test_range_preserves_every_night_packet_and_empty_dates(projection_database, provider, days):
    session, paths = projection_database
    _persist_garmin(session, paths)
    _persist_google(session, paths, payload=_google_sleep_payload())
    session.commit()
    before = read_persisted_sleep_metric_projection(session).as_dict()
    packet = _range(session, provider, days=days)
    assert packet["start_date"] == (WAKE_DATE - timedelta(days=days - 1)).isoformat()
    assert packet["end_date"] == WAKE_DATE.isoformat()
    assert len(packet["days"]) == days
    for night in packet["days"]:
        assert night == _read(session, provider, date.fromisoformat(night["wake_date"]))
    assert packet["observed_dates"] == [WAKE_DATE.isoformat()]
    assert packet["missing_dates"] == [n["wake_date"] for n in packet["days"][:-1]]
    assert _point(packet)["value"] == (28800 if provider == "garmin" else 24600)
    assert all(p["state"] == "no_records" and p["value"] is None
               for p in packet["series"][0]["points"][:-1])
    assert read_persisted_sleep_metric_projection(session).as_dict() == before
    missing = _range(session, provider, WAKE_DATE + timedelta(days=days), days=days)
    assert missing["state"] == "no_records" and missing["series"] == []
    assert missing["observed_dates"] == []
    assert len(missing["missing_dates"]) == days
    unknown = _range(session, provider, source_id="unknown-source")
    assert unknown["state"] == "no_records" and unknown["series"] == []


@pytest.mark.parametrize("roles,state,uncertain", [
    (["main", "fallback", "nap"], "value", False),
    (["main", "main", "nap"], "ambiguous", False),
    (["fallback", "fallback", "nap"], "ambiguous", False),
    (["fallback", "nap"], "value", True),
    (["nap"], "unavailable", False),
])
def test_range_google_role_selection_before_values(projection_database, roles, state, uncertain):
    session, paths = projection_database
    for i, role in enumerate(roles):
        payload = _google_sleep_payload(name=f"session-{i}")
        metadata = payload["dataPoints"][0]["sleep"]["metadata"]
        if role == "fallback":
            metadata.pop("main")
            # An attractive value cannot override an explicit-main missing cell.
            payload["dataPoints"][0]["sleep"]["summary"]["minutesAsleep"] = "600"
        elif role == "nap":
            metadata["nap"] = True
        _persist_google(session, paths, payload=payload)
    session.commit()
    packet = _range(session)
    source = packet["days"][-1]["sources"][0]
    saved = deepcopy(source)
    point = resolve_source_sleep_point(source, provider="google")
    assert point == {k: v for k, v in _point(packet).items() if k != "wake_date"}
    assert source == saved  # The pure resolver never edits disclosure/eligibility.
    assert point["state"] == state and point["role_uncertain"] is uncertain
    if state == "ambiguous":
        assert point["value"] is None and point["record_id"] is None
        assert point["reason"] == "ambiguous_google_main"
    if roles == ["main", "fallback", "nap"]:
        assert point["value"] == 24600
        assert {e["reason"] for e in point["exclusions"]} == {
            "google_explicit_main_preferred", "google_nap_only"
        }
    if roles == ["nap"]:
        assert point["reason"] == "google_nap_only"
        assert packet["observed_dates"] == [WAKE_DATE.isoformat()]


@pytest.mark.parametrize("state,value,unit,expected", [
    ("value", 0, "min", "value"),
    ("missing", None, "min", "missing"),
    ("null", None, "min", "null"),
    ("invalid", None, "min", "invalid"),
    ("value", 12, "seconds", "unavailable"),
])
def test_range_duration_state_and_partial_disclosure(
    projection_database, state, value, unit, expected,
):
    session, paths = projection_database
    _persist_google(session, paths, payload=_google_sleep_payload())
    row = session.scalar(select(GoogleRecordMetric).where(
        GoogleRecordMetric.metric_code == "sleep_summary_minutes_asleep"
    ))
    row.state, row.value_number, row.unit, row.value_text = state, value, unit, None
    session.scalar(select(GoogleSourceRecord)).record_status = "partial"
    session.commit()
    packet = _range(session)
    point = _point(packet)
    assert point["state"] == expected and point["partial"] is True
    assert point["is_zero"] is (expected == "value")
    assert point["value"] == (0 if expected == "value" else None)
    assert packet["days"][-1] == _read(session)


@pytest.mark.parametrize("provider", ["garmin", "google"])
def test_range_invalid_record_retains_scalar_without_plotting(projection_database, provider):
    session, paths = projection_database
    if provider == "google":
        _persist_google(session, paths, payload=_google_sleep_payload())
        model = GoogleSourceRecord
    else:
        _persist_garmin(session, paths)
        model = GarminSourceRecord
    session.scalar(select(model)).record_status = "invalid"
    session.commit()
    packet = _range(session, provider)
    assert _point(packet)["value"] is None
    assert _point(packet)["reason"] == f"{provider}_record_invalid"
    assert packet["days"][-1]["sources"][0]["summary"]["metrics"][
        "sleep_duration_asleep_seconds"
    ]["value"] > 0


def test_range_keeps_actual_google_identities_and_excluded_sources(projection_database):
    session, paths = projection_database
    for identity in ("users/me/dataSources/first", "users/me/dataSources/second", "unattributed"):
        payload = _google_sleep_payload(name=identity)
        payload["dataPoints"][0].pop("dataSource")
        _persist_identity(session, paths, payload, GoogleSourceIdentity(
            source_kind=GoogleSourceKind.DATA_SOURCE, source_instance_id=identity
        ))
    session.commit()
    packet = _range(session)
    assert len(packet["series"]) == 3
    assert len({s["source"]["source_id"] for s in packet["series"]}) == 3
    for series in packet["series"]:
        point = series["points"][-1]
        excluded = series["source"]["source_instance_id"] == "unattributed"
        assert point["value"] == (None if excluded else 24600)
        assert point["state"] == ("unavailable" if excluded else "value")
        selected = _range(session, source_id=series["source"]["source_id"])
        assert selected["series"] == [series]
    assert _range(session, "garmin")["state"] == "no_records"


def test_range_garmin_collisions_never_choose_a_duration(projection_database):
    session, paths = projection_database
    _persist_garmin(session, paths)
    payload = json.loads(GARMIN_SLEEP_FIXTURE.read_text(encoding="utf-8"))
    payload["payload"]["dailySleepDTO"]["calendarDate"] = "2099-01-03"
    payload["payload"]["dailySleepDTO"]["sleepTimeSeconds"] = 36000
    GarminPersistenceRepository(
        session, payload_store=ContentAddressedGarminPayloadStore(paths.root / "garmin-artifacts")
    ).persist_result(normalize_garmin_payload(payload), payload=payload)
    session.flush()
    for row in session.scalars(select(GarminSleepRecord)):
        row.wake_date = WAKE_DATE
    session.commit()
    packet = _range(session, "garmin")
    assert len(packet["days"][-1]["sources"][0]["sessions"]) == 2
    point = _point(packet)
    assert point["state"] == "ambiguous" and point["value"] is None
    assert point["reason"] == "ambiguous_garmin_main"


@pytest.mark.parametrize("provider", ["garmin", "google"])
@pytest.mark.parametrize("offset,expected", [(0, 1), (-6, 1), (-7, 0), (1, 0), (None, 0)])
def test_range_null_wake_date_uses_only_bounded_source_local_date(
    projection_database, provider, offset, expected
):
    session, paths = projection_database
    if provider == "garmin":
        _persist_garmin(session, paths)
        model, typed = GarminSourceRecord, GarminSleepRecord
    else:
        _persist_google(session, paths, payload=_google_sleep_payload())
        model, typed = GoogleSourceRecord, GoogleSleepRecord
    record = session.scalar(select(model))
    identity = record.garmin_source_id if provider == "garmin" else record.google_source_id
    record.source_local_date = WAKE_DATE + timedelta(days=offset) if offset is not None else None
    session.scalar(select(typed)).wake_date = None
    session.commit()
    packet = _range(session, provider)
    assert packet["wake_date_missing_count"] == expected
    assert packet["wake_date_missing_by_source"] == ({identity: 1} if expected else {})
    assert packet["observed_dates"] == [] and len(packet["missing_dates"]) == 7
    assert all(n["sources"] == [] for n in packet["days"])
    assert all(p["value"] is None for s in packet["series"] for p in s["points"])


@pytest.mark.parametrize("provider", ["garmin", "google"])
def test_range_cap_fail_closed_before_load_and_preserves_night_cap(
    projection_database, monkeypatch, provider
):
    session, paths = projection_database
    if provider == "garmin":
        _persist_garmin(session, paths)
    else:
        _persist_google(session, paths, payload=_google_sleep_payload())
    session.commit()
    module = "healthcheck.analytics.sleep_source_view"
    monkeypatch.setattr(f"{module}.MAX_SOURCE_SLEEP_RANGE_RECORDS", 1)
    assert _range(session, provider)["state"] == "records"  # inclusive cap
    monkeypatch.setattr(f"{module}.MAX_SOURCE_SLEEP_RANGE_RECORDS", 0)
    def forbidden(*args, **kwargs):
        pytest.fail("overflow must fail before any typed loader")
    monkeypatch.setattr(f"{module}._load_{provider}_sleep_record_side", forbidden)
    packet = _range(session, provider)
    assert packet["state"] == "read_limit_exceeded"
    assert packet["days"] == packet["series"] == []
    assert packet["observed_dates"] is packet["missing_dates"] is None
    assert packet["wake_date_missing_count"] is None
    monkeypatch.setattr(f"{module}.MAX_SOURCE_SLEEP_RANGE_RECORDS", 400)
    monkeypatch.setattr(f"{module}.MAX_SOURCE_SLEEP_RECORDS", 0)
    assert _range(session, provider)["state"] == "read_limit_exceeded"


def test_range_null_dates_count_toward_cap_and_retired_rows_do_not(
    projection_database, monkeypatch,
):
    session, paths = projection_database
    _persist_google(session, paths, payload=_google_sleep_payload())
    session.scalar(select(GoogleSleepRecord)).wake_date = None
    session.commit()
    monkeypatch.setattr("healthcheck.analytics.sleep_source_view.MAX_SOURCE_SLEEP_RANGE_RECORDS", 0)
    assert _range(session)["state"] == "read_limit_exceeded"
    session.rollback()
    row = session.scalar(select(GoogleSourceRecord))
    row.projection_status, row.retired_at = "retired", datetime(2099, 1, 3, tzinfo=UTC)
    session.commit()
    assert _range(session)["state"] == "no_records"


def test_range_presence_uses_wake_date_not_parent_or_utc_date(projection_database):
    session, paths = projection_database
    _persist_google(session, paths, payload=_google_sleep_payload())
    session.scalar(select(GoogleSourceRecord)).source_local_date = date(2000, 1, 1)
    session.commit()
    assert _range(session)["observed_dates"] == [WAKE_DATE.isoformat()]
    session.rollback()
    session.scalar(select(GoogleSleepRecord)).wake_date = WAKE_DATE + timedelta(days=1)
    session.scalar(select(GoogleSourceRecord)).source_local_date = WAKE_DATE
    session.commit()
    assert _range(session)["state"] == "no_records"


@pytest.mark.parametrize("kwargs", [
    {"days": 1}, {"days": 31}, {"days": 7.0}, {"days": True},
    {"provider": "other"}, {"wake_date": "2099-01-02"},
    {"wake_date": datetime(2099, 1, 2, tzinfo=UTC)},
])
def test_range_rejects_unsupported_window_before_queries(projection_database, kwargs):
    session, _paths = projection_database
    with pytest.raises(ValueError):
        _range(session, **kwargs)


def test_range_snapshot_is_coherent_across_separate_writer(projection_database, monkeypatch):
    import healthcheck.analytics.sleep_source_view as module
    session, paths = projection_database
    _persist_google(session, paths, payload=_google_sleep_payload())
    session.commit()
    # Cache old evidence; new snapshot must expire it before the presence scan.
    cached = session.scalar(select(GoogleRecordMetric).where(
        GoogleRecordMetric.metric_code == "sleep_summary_minutes_asleep"
    ))
    session.rollback()
    engine = session.get_bind()
    original = module._load_google_sleep_record_side
    commits = []
    def load_after_writer(reader, record_id, **kwargs):
        if not commits:
            with session_scope(engine) as writer:
                metric = writer.get(GoogleRecordMetric, cached.id)
                metric.value_number = 500
            commits.append(True)
        return original(reader, record_id, **kwargs)
    monkeypatch.setattr(module, "_load_google_sleep_record_side", load_after_writer)
    assert _point(_range(session))["value"] == 24600
    assert commits == [True]
    assert session.connection().connection.driver_connection.in_transaction
    session.rollback()
    assert _point(_range(session))["value"] == 30000


def test_range_is_bounded_read_only_and_never_opens_payloads(projection_database, monkeypatch):
    from sqlalchemy.exc import InvalidRequestError
    session, paths = projection_database
    _persist_google(session, paths, payload=_google_sleep_payload())
    session.commit()
    def forbidden(*args, **kwargs):
        pytest.fail("range must not open raw payload bodies")
    monkeypatch.setattr(ContentAddressedGooglePayloadStore, "read", forbidden)
    monkeypatch.setattr(ContentAddressedGarminPayloadStore, "read", forbidden)
    statements = []
    event.listen(session.get_bind(), "before_cursor_execute",
                 lambda _c, _cur, sql, params, *_a: statements.append((sql, params)))
    packet = _range(session)
    scans = [(sql, params) for sql, params in statements
             if "google_sleep_records.wake_date BETWEEN" in sql]
    assert len(scans) == 1 and "LIMIT" in scans[0][0] and 401 in scans[0][1]
    assert not any(sql.lstrip().upper().startswith(("UPDATE", "DELETE", "INSERT", "CREATE"))
                   for sql, _params in statements)
    assert '"dataPoints":' not in json.dumps(packet)
    record = session.scalar(select(GoogleSourceRecord))
    record.record_status = "invalid"
    with pytest.raises(InvalidRequestError):
        _range(session)
    assert record.record_status == "invalid"  # No implicit flush/discard of caller writes.


def test_range_explicit_main_missing_scalar_never_falls_back_to_better_value(projection_database):
    session, paths = projection_database
    for name in ("main", "fallback"):
        payload = _google_sleep_payload(name=name)
        if name == "main":
            payload["dataPoints"][0]["sleep"]["summary"].pop("minutesAsleep")
        else:
            payload["dataPoints"][0]["sleep"]["metadata"].pop("main")
        _persist_google(session, paths, payload=payload)
    session.commit()
    point = _point(_range(session))
    assert point["state"] == "missing" and point["value"] is None
    assert len(point["candidate_record_ids"]) == 1
    assert point["exclusions"][0]["reason"] == "google_explicit_main_preferred"


def test_range_cap_counts_all_sources_and_each_provider_independently(
    projection_database, monkeypatch,
):
    session, paths = projection_database
    _persist_garmin(session, paths)
    for name in ("one", "two"):
        payload = _google_sleep_payload(name=name)
        payload["dataPoints"][0].pop("dataSource")
        _persist_identity(session, paths, payload, GoogleSourceIdentity(
            source_kind=GoogleSourceKind.DATA_SOURCE,
            source_instance_id=f"users/me/dataSources/{name}",
        ))
    session.commit()
    monkeypatch.setattr("healthcheck.analytics.sleep_source_view.MAX_SOURCE_SLEEP_RANGE_RECORDS", 1)
    assert _range(session, "google")["state"] == "read_limit_exceeded"
    assert _range(session, "garmin")["state"] == "records"
    source_id = session.scalar(select(GoogleSourceRecord)).google_source_id
    assert _range(session, source_id=source_id)["state"] == "records"


def test_range_multiple_dates_are_inclusive_and_never_bridge_gaps(projection_database):
    session, paths = projection_database
    start = WAKE_DATE - timedelta(days=6)
    dates = [start - timedelta(days=1), start, start + timedelta(days=2), WAKE_DATE]
    for local_date in dates:
        payload = _google_sleep_payload(name=local_date.isoformat())
        interval = payload["dataPoints"][0]["sleep"]["interval"]
        interval["civilStartTime"]["date"] = local_date.isoformat()
        interval["civilEndTime"]["date"] = local_date.isoformat()
        interval["startTime"] = f"{local_date.isoformat()}T01:00:00Z"
        interval["endTime"] = f"{local_date.isoformat()}T08:00:00Z"
        _persist_google(session, paths, payload=payload)
    session.commit()
    packet = _range(session)
    assert packet["observed_dates"] == [d.isoformat() for d in dates[1:]]
    assert [p["state"] for p in packet["series"][0]["points"]] == [
        "value", "no_records", "value", "no_records", "no_records", "no_records", "value"
    ]
    for night in packet["days"]:
        assert night == _read(session, wake_date=date.fromisoformat(night["wake_date"]))
