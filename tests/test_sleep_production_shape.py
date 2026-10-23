"""Invented production-shaped sleep evidence; no provider or Owner data."""
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from healthcheck.analytics.sleep_pairing import _google_observation_role
from healthcheck.analytics.sleep_source_view import read_source_sleep_night, read_source_sleep_range
from healthcheck.db.models import GoogleRecordMetric, GoogleSourceRecord
from healthcheck.garmin.normalization import (
    SLEEP_TIMING_CONTRACT_VERSION,
    GarminSourceIdentity,
    _parse_record_temporal,
    normalize_garmin_payload,
)
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.garmin.sync import (
    PRODUCTION_SYNC_SURFACES,
    _prepare_normalization_result,
    _reconcile_record,
)
from healthcheck.google.contracts import GoogleStream
from healthcheck.google.normalization import SLEEP_MAIN_CONTRACT_VERSION, normalize_google_payload
from healthcheck.saved_sleep_analysis import analyze_saved_sleep
from test_saved_sleep_analysis import event, request
from test_sleep_metrics import _google_identity, _google_sleep_payload, _persist_google
from test_sleep_metrics import projection_database as projection_database

DAY = date(2099, 1, 2)
START = datetime(2099, 1, 1, 22, tzinfo=UTC)
END = START + timedelta(hours=8)
SOURCE = GarminSourceIdentity(source_kind="provider", provider_code="garmin_connect",
    source_instance_id="invented-sleep-source", device_attributed=False)
SURFACE = next(s for s in PRODUCTION_SYNC_SURFACES if s.code == "sleep")


def milliseconds(value):
    return int((value - datetime(1970, 1, 1, tzinfo=UTC)).total_seconds() * 1000)


def production_sleep(*, offset=60, end_offset=None):
    end_offset = offset if end_offset is None else end_offset
    return {"dailySleepDTO": {"calendarDate": DAY.isoformat(),
        "sleepStartTimestampGMT": milliseconds(START),
        "sleepStartTimestampLocal": milliseconds(START + timedelta(minutes=offset)),
        "sleepEndTimestampGMT": milliseconds(END),
        "sleepEndTimestampLocal": milliseconds(END + timedelta(minutes=end_offset)),
        "sleepTimeSeconds": 8 * 3600},
        "sleepLevels": [{
            "startGMT": (START + timedelta(hours=i * 2)).replace(tzinfo=None).isoformat(),
            "endGMT": (START + timedelta(hours=(i + 1) * 2)).replace(tzinfo=None).isoformat(),
            "activityLevel": float(i)} for i in range(4)]}


@pytest.mark.parametrize("seconds,reason", [(-1, "duration_negative"),
    (28801, "duration_exceeds_confirmed_session"), (28800, None), (25200, None)])
@pytest.mark.parametrize("phases", ["complete", "partial", "missing"])
def test_production_duration_quality_in_current_and_legacy_readers(
    projection_database, seconds, reason, phases,
):
    from healthcheck.analytics.garmin_baselines import (
        GarminSeriesQuery,
        analyze_garmin_metric_series,
    )
    from healthcheck.db.models import GarminRecordMetric, GarminSourceRecord
    from healthcheck.garmin.analytic_contract import build_analytic_input_from_storage

    session, paths = projection_database
    payload = production_sleep()
    payload["dailySleepDTO"]["sleepTimeSeconds"] = seconds
    if phases == "partial":
        payload["sleepLevels"].pop()
    elif phases == "missing":
        payload.pop("sleepLevels")
    GarminPersistenceRepository(session, payload_store=ContentAddressedGarminPayloadStore(
        paths.root / "garmin-artifacts")).persist_result(normalized(payload), payload=payload)
    session.commit()
    night = read_source_sleep_night(session, provider="garmin", wake_date=DAY)
    cells = night["sources"][0]["summary"]["metrics"]
    cell = cells["sleep_duration_asleep_seconds"]
    assert cell["eligible"] is (reason is None)
    assert cell["reason"] == reason
    boundary = cell["evidence"]["quality_inputs"]["summary_boundary"]
    assert boundary["start"]["measured_at_utc"] == START.isoformat()
    assert boundary["end"]["measured_at_utc"] == END.isoformat()
    assert boundary["end"]["source_local_field"] == (
        "payload.dailySleepDTO.sleepEndTimestampLocal")
    assert cell["evidence"]["quality_inputs"]["session_bound_validation"] == {
        "state": "checked", "reason": reason, "upper_bound_seconds": 28800,
    }
    if phases != "complete":
        for code in ("sleep_stage_rem_seconds", "sleep_time_in_bed_seconds", "sleep_end_at"):
            assert not cells[code]["eligible"]
    row = session.scalar(select(GarminRecordMetric).where(
        GarminRecordMetric.metric_code == "sleep_duration_seconds",
    ))
    dto = build_analytic_input_from_storage(session, metric_row_id=row.id)
    assert dto.selected.state == ("invalid" if reason else "value")
    assert dto.selected.value == seconds
    assert dto.evidence.sleep_quality_inputs["confirmed_end_at_utc"] == END.isoformat()
    assert dto.evidence.sleep_quality_inputs["summary_boundary"] == boundary
    assert dto.rule_version == "r03-garmin-sleep-duration-quality-v2"
    source_id = session.scalar(select(GarminSourceRecord.garmin_source_id))
    series = analyze_garmin_metric_series(session, GarminSeriesQuery(
        garmin_source_id=source_id, metric_code="sleep_duration_seconds",
        start_date=DAY, end_date=DAY,
    ))
    assert series.points[0].value == (seconds if reason is None else None)
    assert series.points[0].exclusion_reason == reason
    assert session.get(GarminRecordMetric, row.id).value_number == seconds


def test_production_complete_coverage_can_prove_rem_zero(projection_database):
    session, paths = projection_database
    payload = production_sleep()
    payload["sleepLevels"][2]["activityLevel"] = 1
    GarminPersistenceRepository(session, payload_store=ContentAddressedGarminPayloadStore(
        paths.root / "garmin-artifacts")).persist_result(normalized(payload), payload=payload)
    session.commit()
    cells = read_source_sleep_night(session, provider="garmin", wake_date=DAY)[
        "sources"][0]["summary"]["metrics"]
    assert cells["sleep_stage_rem_seconds"]["eligible"]
    assert cells["sleep_stage_rem_seconds"]["value"] == 0
    assert cells["sleep_time_in_bed_seconds"]["value"] == 28800


@pytest.mark.parametrize("version,phases", [("v4", "missing"), ("v4", "empty"),
                                          ("v3", "complete")])
@pytest.mark.parametrize("fields", ["all", "local"])
@pytest.mark.parametrize("seconds", [28801, 25200])
def test_integral_float_summary_bounds_keep_original_provenance(
    projection_database, version, phases, fields, seconds,
):
    from healthcheck.db.models import GarminRecordMetric
    from healthcheck.garmin.analytic_contract import build_analytic_input_from_storage

    session, paths = projection_database
    payload = production_sleep()
    summary = payload["dailySleepDTO"]
    summary["sleepTimeSeconds"] = seconds
    for key in tuple(summary):
        if "Timestamp" in key and (fields == "all" or key.endswith("Local")):
            summary[key] = float(summary[key])
    if phases == "missing":
        payload.pop("sleepLevels")
    elif phases == "empty":
        payload["sleepLevels"] = []
    result = normalized(payload)
    if version == "v3":
        result = replace(result, contract_version="r02-garmin-sleep-normalization-v3", records=(
            replace(result.records[0], metrics=tuple(m for m in result.records[0].metrics
                if m.metric_code != "sleep_summary_session_bounds")),))
    GarminPersistenceRepository(session, payload_store=ContentAddressedGarminPayloadStore(
        paths.root / "garmin-artifacts")).persist_result(result, payload=payload)
    session.commit()
    cell = read_source_sleep_night(session, provider="garmin", wake_date=DAY)[
        "sources"][0]["summary"]["metrics"]["sleep_duration_asleep_seconds"]
    row = session.scalar(select(GarminRecordMetric).where(
        GarminRecordMetric.metric_code == "sleep_duration_seconds"))
    dto = build_analytic_input_from_storage(session, metric_row_id=row.id)
    reason = "duration_exceeds_confirmed_session" if seconds > 28800 else None
    assert cell["eligible"] is (reason is None)
    assert cell["reason"] == reason
    assert dto.selected.state == ("invalid" if reason else "value")
    assert dto.selected.value == seconds
    assert cell["evidence"]["quality_inputs"]["session_bound_validation"] == {
        "state": "checked", "reason": reason, "upper_bound_seconds": 28800,
    }
    assert dto.evidence.sleep_quality_inputs["confirmed_end_at_utc"] == END.isoformat()
    if version == "v4":
        boundary = cell["evidence"]["quality_inputs"]["summary_boundary"]
        for endpoint in ("start", "end"):
            assert boundary[endpoint]["source_local_timestamp"] == str(
                summary[f"sleep{endpoint.title()}TimestampLocal"])
    assert session.get(GarminRecordMetric, row.id).value_number == seconds


@pytest.mark.parametrize("text,expected", [
    ("4070901600000", 4070901600000), ("4070901600000.0", 4070901600000),
    ("4.0709016e12", 4070901600000), ("0.0", 0), ("-1.0", -1),
    ("253402300799999.0", 253402300799999), ("-62135596800000.0", -62135596800000),
    ("4070901600000.5", None), ("1e-9999", None), ("NaN", None),
    ("Infinity", None), ("-Infinity", None), ("True", None), (True, None), (False, None),
    (None, None), ("1e9999", None), ("253402300800000", None),
    ("-62135596800001", None), ("999999999999999999999", None),
    ("4_070901600000", None), (" 4070901600000", None),
])
def test_retained_sleep_milliseconds_decode_exact_integral_values_only(text, expected):
    from healthcheck.sleep_quality import _stored_milliseconds

    assert _stored_milliseconds(text) == expected


@pytest.mark.parametrize("phases", ["complete", "partial", "missing"])
def test_legacy_v3_summary_bound_check_is_explicit_without_raw_recovery(
    projection_database, phases,
):
    from healthcheck.db.models import GarminRecordMetric
    from healthcheck.garmin.analytic_contract import build_analytic_input_from_storage

    session, paths = projection_database
    payload = production_sleep()
    payload["dailySleepDTO"]["sleepTimeSeconds"] = 28801
    if phases == "partial":
        payload["sleepLevels"].pop()
    elif phases == "missing":
        payload.pop("sleepLevels")
    result = normalized(payload)
    legacy = replace(result, contract_version="r02-garmin-sleep-normalization-v3", records=(
        replace(result.records[0], metrics=tuple(m for m in result.records[0].metrics
            if m.metric_code != "sleep_summary_session_bounds")),))
    GarminPersistenceRepository(session, payload_store=ContentAddressedGarminPayloadStore(
        paths.root / "garmin-artifacts")).persist_result(legacy, payload=payload)
    session.commit()
    cell = read_source_sleep_night(session, provider="garmin", wake_date=DAY)[
        "sources"][0]["summary"]["metrics"]["sleep_duration_asleep_seconds"]
    row = session.scalar(select(GarminRecordMetric).where(
        GarminRecordMetric.metric_code == "sleep_duration_seconds"))
    dto = build_analytic_input_from_storage(session, metric_row_id=row.id)
    status = cell["evidence"]["quality_inputs"]["session_bound_validation"]
    assert dto.evidence.sleep_quality_inputs["session_bound_validation"] == status
    if phases == "complete":
        assert not cell["eligible"]
        assert status == {"state": "checked", "reason": "duration_exceeds_confirmed_session",
                          "upper_bound_seconds": 28800}
    else:
        # Native scalar usability is retained; agreement with the lost End is unverified.
        assert cell["eligible"] and cell["value"] == 28801
        assert status == {"state": "unverified", "reason": "summary_session_boundary_unavailable",
                          "upper_bound_seconds": None}
    assert session.get(GarminRecordMetric, row.id).value_number == 28801


@pytest.mark.parametrize("mutation", ["none", "offset_bool", "local", "path", "naive", "private"])
def test_independent_summary_boundary_metadata_requires_typed_provenance(mutation):
    import json
    from types import SimpleNamespace

    from healthcheck.sleep_quality import garmin_summary_boundary_evidence

    row = normalized(production_sleep()).records[0]
    metric = row.metric("sleep_summary_session_bounds")
    value = json.loads(metric.value)
    if mutation == "offset_bool":
        value["end"]["source_utc_offset_minutes"] = True
    elif mutation == "local":
        value["end"]["source_local_timestamp"] = str(milliseconds(END))
    elif mutation == "path":
        value["end"]["source_utc_field"] = "payload.sleepLevels[0].endGMT"
    elif mutation == "naive":
        value["end"]["measured_at_utc"] = END.replace(tzinfo=None).isoformat()
    elif mutation == "private":
        value["end"]["source_timezone"] = {"raw_payload": "do-not-export"}
    record = SimpleNamespace(normalization_contract_version=SLEEP_TIMING_CONTRACT_VERSION,
        temporal_precision="instant", source_timestamp_utc=START, source_path="payload")
    saved = SimpleNamespace(metric_code=metric.metric_code, state="value", unit=None,
        value_text=json.dumps(value), field_path=metric.field_path, id="invented-bound-row")
    evidence = garmin_summary_boundary_evidence(record, (saved,))
    assert (evidence is not None) is (mutation == "none")


@pytest.mark.parametrize("phases", ["partial", "missing"])
def test_offline_reprocess_retains_independent_summary_boundaries(projection_database, phases):
    from healthcheck.config import Settings
    from healthcheck.db.models import GarminRecordMetric, GarminSourceRecord
    from healthcheck.garmin.reprocess import run_garmin_reprocess
    from healthcheck.garmin.sync import _collection_scope, _day_bounds

    session, paths = projection_database
    payload = production_sleep()
    payload["dailySleepDTO"]["sleepTimeSeconds"] = 28801
    if phases == "partial":
        payload["sleepLevels"].pop()
    else:
        payload.pop("sleepLevels")
    result = normalized(payload)
    legacy = replace(result, contract_version="r02-garmin-sleep-normalization-v3", records=(
        replace(result.records[0], metrics=tuple(m for m in result.records[0].metrics
            if m.metric_code != "sleep_summary_session_bounds")),))
    bounds = _day_bounds(DAY)
    store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
    original = GarminPersistenceRepository(session, payload_store=store).persist_result(
        legacy, payload=payload, source_identity=SOURCE, source_filename="sleep.json",
        source_window_start_utc=bounds[0], source_window_end_utc=bounds[1],
        received_at=END + timedelta(days=1), collection_scope=_collection_scope(SURFACE,
            day=DAY, window_start=DAY, window_end=DAY, fetch_complete=True,
            coverage_status="present"))
    session.commit()
    report = run_garmin_reprocess(Settings(data_dir=paths.root), start=DAY, end=DAY,
        streams=["sleep"])
    assert report.status == "succeeded" and report.processed_count == 1
    session.expire_all()
    current = session.get(GarminSourceRecord, original.records[0].id)
    assert current.normalization_contract_version == SLEEP_TIMING_CONTRACT_VERSION
    boundary = session.scalar(select(GarminRecordMetric).where(
        GarminRecordMetric.record_id == current.id,
        GarminRecordMetric.metric_code == "sleep_summary_session_bounds"))
    assert boundary is not None
    cell = read_source_sleep_night(session, provider="garmin", wake_date=DAY)[
        "sources"][0]["summary"]["metrics"]["sleep_duration_asleep_seconds"]
    assert not cell["eligible"] and cell["reason"] == "duration_exceeds_confirmed_session"
    saved = cell["evidence"]["quality_inputs"]["summary_boundary"]
    assert saved["start"]["measured_at_utc"] == START.isoformat()
    assert saved["end"]["measured_at_utc"] == END.isoformat()
    assert saved["end"]["source_local_timestamp"] == str(
        payload["dailySleepDTO"]["sleepEndTimestampLocal"])


def normalized(payload):
    result = normalize_garmin_payload(payload, stream="sleep", source_identity=SOURCE)
    return _prepare_normalization_result(SURFACE, payload, result, day=DAY)


@pytest.mark.parametrize("phases", ["partial", "missing"])
@pytest.mark.parametrize("seconds", [28801, 25200])
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("timestamps_as_float", [False, True])
def test_independent_summary_bounds_reach_statistics_and_exports(
    tmp_path, phases, seconds, legacy, timestamps_as_float,
):
    import json
    import re

    from healthcheck.analytics.period_summary import SLEEP_CODE, PeriodSummaryService
    from healthcheck.db.engine import create_sqlite_engine, session_scope
    from healthcheck.db.models import GarminSource
    from healthcheck.sleep_evidence import (
        SleepEvidenceRequest,
        encode_sleep_evidence,
        read_sleep_evidence,
        render_sleep_evidence,
    )
    from healthcheck.web.sleep_view import source_sleep_note
    from healthcheck.web.statistics import format_statistics_value
    from test_garmin_query_dashboard import _ui
    from test_sleep_owner_ui import client_for
    from test_statistics_ui import MetricParser

    app, _settings, paths = _ui(tmp_path)
    engine = create_sqlite_engine(paths)
    payload = production_sleep()
    payload["dailySleepDTO"]["sleepTimeSeconds"] = seconds
    if timestamps_as_float:
        for key in tuple(payload["dailySleepDTO"]):
            if "Timestamp" in key:
                payload["dailySleepDTO"][key] = float(payload["dailySleepDTO"][key])
    if phases == "partial":
        payload["sleepLevels"].pop()
    else:
        payload.pop("sleepLevels")
    expected = None if seconds > 28800 and not legacy else seconds
    actual = {}
    try:
        with session_scope(engine) as session:
            store = ContentAddressedGarminPayloadStore(paths.root / "garmin-artifacts")
            result = normalized(payload)
            if legacy:
                result = replace(result, contract_version="r02-garmin-sleep-normalization-v3",
                    records=(replace(result.records[0], metrics=tuple(
                        m for m in result.records[0].metrics
                        if m.metric_code != "sleep_summary_session_bounds")),))
            GarminPersistenceRepository(session, payload_store=store).persist_result(
                result, payload=payload)
            source_id = session.scalar(select(GarminSource.id))
        for days in (7, 30):
            with session_scope(engine) as session:
                packet = PeriodSummaryService(session).build(end_date=DAY, days=days,
                    garmin_sleep_source_id=source_id, sleep_source_selection=True)
                cell = packet["sides"][0]["metrics"][SLEEP_CODE]
                actual[f"period{days}"] = cell["aggregation"]["value"]
                assert cell["session_bound_validation"]["unverified_count"] == int(legacy)
            package = read_sleep_evidence(profile=paths.root, profile_kind="synthetic",
                request=SleepEvidenceRequest(DAY, days, garmin_source_id=source_id),
                evaluated_at_utc=END + timedelta(days=1), evaluation_local_date=DAY)
            section = package["sections"]["garmin"]
            point = section["source_range"]["series"][0]["points"][-1]
            actual[f"export{days}"] = point["value"]
            encoded = encode_sleep_evidence(package)
            assert json.loads(encoded)["sections"]["garmin"] == section
            text = render_sleep_evidence(package)
            native_cell = section["source_range"]["days"][-1]["sources"][0]["summary"][
                "metrics"][SLEEP_CODE]
            quality = native_cell["evidence"]["quality_inputs"]
            if legacy:
                assert quality["session_bound_validation"]["state"] == "unverified"
                assert "не проверена по границам" in source_sleep_note(native_cell)
                assert "summary_session_boundary_unavailable" in text
            else:
                boundary = quality["summary_boundary"]
                assert boundary["start"]["measured_at_utc"] == START.isoformat()
                assert boundary["end"]["measured_at_utc"] == END.isoformat()
                assert boundary["end"]["source_utc_field"].endswith(".sleepEndTimestampGMT")
                assert boundary["end"]["source_utc_offset_minutes"] == 60
                assert boundary["end"]["source_local_timestamp"] == str(
                    payload["dailySleepDTO"]["sleepEndTimestampLocal"])
            with client_for(app) as client:
                response = client.get("/statistics", params={"days": days,
                    "end_date": str(DAY), "garmin_sleep_source_id": source_id})
                assert response.status_code == 200
                parser = MetricParser(response.text)
                html = parser.values[SLEEP_CODE, "left"].strip()
                if legacy:
                    qualifier = r"Границы не проверены:\s*1\b"
                    assert re.search(qualifier, parser.cells[SLEEP_CODE, "left"])
                    # Owner moved the retained legacy-A qualifier into the closed
                    # heading info; numerical/boundary evidence stays unchanged.
                    details = parser.details[SLEEP_CODE, "left"]
                    assert re.search(qualifier, details)
                    primary = parser.cells[SLEEP_CODE, "left"].replace(details, "", 1)
                    assert not re.search(qualifier, primary)
                else:
                    assert "Границы не проверены" not in parser.cells[SLEEP_CODE, "left"]
            actual[f"html{days}"] = html
            if expected is None:
                actual[f"reason{days}"] = (
                    "duration_exceeds_confirmed_session" in encoded
                    and "duration_exceeds_confirmed_session" in text
                )
                actual[f"invalid{days}"] = cell["availability_counts"]["invalid"]
            else:
                assert cell["aggregation"]["eligible_count"] == 1
                assert str(seconds) in encoded and str(seconds) in text
        assert all(actual[f"period{days}"] == expected and actual[f"export{days}"] == expected
                   and actual[f"html{days}"] == format_statistics_value(SLEEP_CODE, expected)
                   for days in (7, 30)), actual
        if expected is None:
            assert all(actual[f"reason{days}"] and actual[f"invalid{days}"] == 1
                       for days in (7, 30)), actual
    finally:
        engine.dispose()


def test_production_milliseconds_stage_codes_and_endpoint_provenance():
    payload = production_sleep()
    result = normalized(payload)
    assert result.contract_version == SLEEP_TIMING_CONTRACT_VERSION
    row = result.records[0]
    assert row.temporal.measured_at_utc == START
    assert row.temporal.local_date == DAY
    assert row.temporal.source_utc_offset_minutes == 60
    assert row.temporal.source_timezone is None
    assert row.temporal.source_local_timestamp == str(
        payload["dailySleepDTO"]["sleepStartTimestampLocal"]
    )
    assert row.temporal.source_utc_field == "payload.dailySleepDTO.sleepStartTimestampGMT"
    stages = row.metric("sleep_stages")
    assert stages.reason is None
    assert [s.activity_level for s in stages.collection] == ["DEEP", "LIGHT", "REM", "AWAKE"]
    assert stages.collection[-1].end.source_utc_offset_minutes == 60
    assert stages.collection[-1].end.source_utc_field == "payload.sleepLevels[3].endGMT"
    assert stages.collection[1].start.source_utc_offset_minutes is None


@pytest.mark.parametrize("field", ["sleepStartTimestampGMT", "sleepStartTimestampLocal",
                                  "sleepEndTimestampGMT", "sleepEndTimestampLocal"])
@pytest.mark.parametrize("bad", [None, True, "123", 1.25, float("nan"), 10**30])
def test_invalid_summary_boundaries_never_yield_complete_stages(field, bad):
    payload = production_sleep()
    payload["dailySleepDTO"][field] = bad
    result = normalized(payload)
    assert result.records[0].metric("sleep_stages").reason == "partial_collection"
    if "Start" in field:
        assert result.records[0].temporal.measured_at_utc is None


@pytest.mark.parametrize("bad", [None, True, -1, 4, 1.25, "1", float("nan")])
def test_unknown_stage_codes_are_partial_not_complete_prefix(bad):
    payload = production_sleep()
    payload["sleepLevels"][1]["activityLevel"] = bad
    assert normalized(payload).records[0].metric("sleep_stages").reason == "partial_collection"


@pytest.mark.parametrize("problem", ["gap", "overlap", "reorder", "boundary", "alias", "offset",
                                     "calendar", "root", "missing_end"])
def test_conflicting_or_incomplete_production_evidence_fails_closed(problem):
    payload = production_sleep()
    if problem in {"gap", "overlap"}:
        delta = timedelta(minutes=1 if problem == "gap" else -1)
        payload["sleepLevels"][1]["startGMT"] = (START + timedelta(hours=2) + delta).isoformat()
    elif problem == "reorder":
        payload["sleepLevels"].reverse()
    elif problem == "boundary":
        payload["dailySleepDTO"]["sleepEndTimestampGMT"] += 1000
    elif problem == "alias":
        payload["levels"] = []
    elif problem == "offset":
        payload["dailySleepDTO"]["sleepStartTimestampLocal"] += 1000
    elif problem == "calendar":
        payload["calendarDate"] = "2099-01-03"
    elif problem == "root":
        payload["startTimeGMT"] = (START + timedelta(hours=1)).isoformat()
    elif problem == "missing_end":
        del payload["dailySleepDTO"]["sleepEndTimestampGMT"]
    assert normalized(payload).records[0].metric("sleep_stages").reason == "partial_collection"


def test_absent_production_fields_keep_date_only_and_missing_stages():
    row = normalized({"dailySleepDTO": {"calendarDate": DAY.isoformat()}}).records[0]
    assert row.temporal.precision == "date" and row.temporal.measured_at_utc is None
    assert row.metric("sleep_stages").state == "missing"


@pytest.mark.parametrize("legacy_root", [False, True])
@pytest.mark.parametrize("record_id", [None, "invented-record"])
def test_sleep_enrichment_preserves_exact_v2_production_keys(legacy_root, record_id):
    payload = production_sleep()
    if legacy_root:
        payload["startTimeGMT"] = START.isoformat()
    if record_id:
        payload["recordId"] = record_id
    result = normalized(payload)
    row = result.records[0]
    legacy = _parse_record_temporal(payload, "payload")[0]
    expected = _reconcile_record(SURFACE, replace(row, temporal=legacy, sample_token=None))
    assert row.idempotency_key == expected.idempotency_key
    assert row.sample_token == expected.sample_token
    other = _reconcile_record(SURFACE, replace(row, source=replace(SOURCE,
        source_instance_id="another-source")), identity_temporal=legacy)
    assert other.idempotency_key != row.idempotency_key
    if not legacy_root:
        corrected = deepcopy(payload)
        corrected["dailySleepDTO"]["sleepStartTimestampGMT"] += 1000
        corrected["dailySleepDTO"]["sleepStartTimestampLocal"] += 1000
        assert normalized(corrected).records[0].idempotency_key == row.idempotency_key


@pytest.mark.parametrize("end_offset", [60, 120])
def test_production_persisted_analysis_preserves_methods_and_offset_partitions(
    projection_database, end_offset,
):
    session, paths = projection_database
    payload = production_sleep(end_offset=end_offset)
    GarminPersistenceRepository(session, payload_store=ContentAddressedGarminPayloadStore(
        paths.root / "garmin-artifacts")).persist_result(normalized(payload), payload=payload)
    session.commit()
    source_range = read_source_sleep_range(session, provider="garmin", wake_date=DAY, days=7)
    source = read_source_sleep_night(session, provider="garmin", wake_date=DAY)["sources"][0]
    night = source["sessions"][0]
    assert night["role"] is None
    assert night["metrics"]["sleep_start_at"]["comparison_basis"] == "explicit_record_boundary"
    assert night["metrics"]["sleep_end_at"]["comparison_basis"] == "complete_stage_boundary"
    data = {"sleep": {"providers": {"garmin": {"selected_source_id": "invented",
        "acquisition_coverage": {"state": "unknown"},
        "source_range": source_range}}}, "context": {"rows": [event(START.isoformat())]}}
    analyze_saved_sleep(data, request())
    if end_offset == 60:
        assert len(data["sleep_analysis_inputs"]["nights"]) == 1
        assert len(data["context_recovery"]["pairs"]) == 1
    else:
        assert data["sleep_analysis_inputs"]["nights"] == []
        assert data["sleep_analysis_inputs"]["night_exclusions"][0]["reason"] == (
            "within_night_timezone_change"
        )


@pytest.mark.parametrize("main", [True, False, None, "invalid"])
@pytest.mark.parametrize("nap", ["missing", None, True, False, "invalid"])
def test_documented_google_main_sleep_scoped_role_policy(projection_database, main, nap):
    session, paths = projection_database
    payload = _google_sleep_payload()
    metadata = payload["dataPoints"][0]["sleep"]["metadata"]
    metadata.pop("main", None)
    metadata["mainSleep"] = main
    if nap == "missing":
        metadata.pop("nap", None)
    else:
        metadata["nap"] = nap
    metadata.pop("processed", None)
    metadata.pop("stagesStatus", None)
    _persist_google(session, paths, payload=payload)
    session.commit()
    row = session.scalar(select(GoogleSourceRecord))
    assert row.normalization_contract_version == SLEEP_MAIN_CONTRACT_VERSION
    metrics = list(session.scalars(select(GoogleRecordMetric)))
    canonical = next(m for m in metrics if m.metric_code == "sleep_metadata_main_sleep")
    assert canonical.field_path.endswith(".metadata.mainSleep")
    assert _google_observation_role(metrics)[6] != "explicit_main"
    source = read_source_sleep_night(session, provider="google", wake_date=DAY)["sources"][0]
    night = source["sessions"][0]
    explicit = main is True and nap not in (True, "invalid")
    assert (night["role"]["selection"] == "explicit_main") is explicit
    assert night["role"]["nap_value"] is (nap if type(nap) is bool else None)
    source_range = read_source_sleep_range(session, provider="google", wake_date=DAY, days=7)
    data = {"sleep": {"providers": {"google": {"selected_source_id": "invented",
        "acquisition_coverage": {"state": "unknown"},
        "source_range": source_range}}}, "context": {"rows": [event(START.isoformat())]}}
    analyze_saved_sleep(data, request())
    assert bool(data["sleep_analysis_inputs"]["nights"]) is explicit
    assert bool(data["context_recovery"]["pairs"]) is explicit


@pytest.mark.parametrize("legacy,modern", [(True, False), (False, True)])
def test_google_contradictory_aliases_excluded(projection_database, legacy, modern):
    session, paths = projection_database
    payload = _google_sleep_payload()
    payload["dataPoints"][0]["sleep"]["metadata"].update(main=legacy, mainSleep=modern)
    _persist_google(session, paths, payload=payload)
    session.commit()
    source = read_source_sleep_night(session, provider="google", wake_date=DAY)["sources"][0]
    night = source["sessions"][0]
    assert night["reason"] == "google_main_alias_conflict"


def test_google_main_sleep_multiple_main_and_missing_endpoint_stay_excluded(projection_database):
    session, paths = projection_database
    for name in ("one", "two"):
        payload = _google_sleep_payload(name=name)
        payload["dataPoints"][0]["sleep"]["metadata"] = {"mainSleep": True}
        _persist_google(session, paths, payload=payload)
    session.commit()
    source_range = read_source_sleep_range(session, provider="google", wake_date=DAY, days=7)
    data = {"sleep": {"providers": {"google": {"selected_source_id": "invented",
        "acquisition_coverage": {"state": "unknown"},
        "source_range": source_range}}}, "context": {"rows": []}}
    analyze_saved_sleep(data, request())
    assert data["sleep_analysis_inputs"]["night_exclusions"][0]["reason"] == "ambiguous_google_main"


def test_google_main_sleep_normalization_keeps_missing_null_invalid_distinct():
    for present, value, state in ((False, None, "missing"), (True, None, "null"),
                                  (True, "true", "invalid"), (True, True, "value")):
        payload = _google_sleep_payload()
        if present:
            payload["dataPoints"][0]["sleep"]["metadata"]["mainSleep"] = value
        result = normalize_google_payload(payload, stream=GoogleStream.SLEEP,
            source_identity=_google_identity())
        metric = next(m for m in result.records[0].metrics
                      if m.metric_code == "sleep_metadata_main_sleep")
        assert metric.state == state


@pytest.mark.parametrize("revision", ["valid", "missing", "invalid"])
def test_google_actual_v2_original_replay_adds_role_without_changing_identity(
    projection_database, revision,
):
    from healthcheck.google.persistence import GooglePersistenceRepository
    from healthcheck.google.replay import replay_google_observations
    from healthcheck.google.storage import ContentAddressedGooglePayloadStore

    session, paths = projection_database
    payload = _google_sleep_payload()
    component = payload["dataPoints"][0]["sleep"]
    component["metadata"] = {"mainSleep": True}
    if revision == "missing":
        component.pop("updateTime")
    elif revision == "invalid":
        component["updateTime"] = "invalid"
    result = normalize_google_payload(payload, stream=GoogleStream.SLEEP,
        source_identity=_google_identity(),
        normalization_contract_version="r04-google-normalization-contract-v2")
    # Explicit v2 dispatch reproduces the actual old metric/unknown-field shape.
    assert all(m.metric_code != "sleep_metadata_main_sleep" for m in result.records[0].metrics)
    old = result
    store = ContentAddressedGooglePayloadStore(paths.root / "google-artifacts")
    original = GooglePersistenceRepository(session, payload_store=store).persist_result(
        old, payload=payload, received_at=datetime(2099, 1, 3, tzinfo=UTC))
    session.commit()
    record_id, raw_id = original.records[0].id, original.records[0].raw_payload_id
    observation_id = original.records[0].observation_id
    legacy_retry = replay_google_observations(session, payload_store=store,
        observation_ids=[observation_id],
        normalization_contract_version="r04-google-normalization-contract-v2")
    assert legacy_retry[0].updated_count == 0
    replay_google_observations(session, payload_store=store, observation_ids=[observation_id])
    session.commit()
    session.expire_all()
    current = session.get(GoogleSourceRecord, record_id)
    assert current.raw_payload_id == raw_id
    metric = session.scalar(select(GoogleRecordMetric).where(
        GoogleRecordMetric.record_id == record_id,
        GoogleRecordMetric.metric_code == "sleep_metadata_main_sleep"))
    assert (metric is not None) is (revision == "valid")
    assert current.normalization_contract_version == (
        SLEEP_MAIN_CONTRACT_VERSION if revision == "valid"
        else "r04-google-normalization-contract-v2")
    again = replay_google_observations(session, payload_store=store,
        observation_ids=[observation_id])
    assert again[0].inserted_count == 0 and again[0].updated_count == 0


@pytest.mark.parametrize("problem", ["none", "hash", "byte_cap", "foreign", "stale", "invalid"])
def test_preview_uses_verified_read_only_snapshot_and_discloses_currentness(
    projection_database, problem, monkeypatch,
):
    from healthcheck.chat_evidence import _read_session
    from healthcheck.db.models import GarminPayloadObservation, RawArtifact
    from healthcheck.garmin.sleep_preview import preview_saved_garmin_sleep
    from healthcheck.garmin.sync import _collection_scope, _day_bounds

    session, paths = projection_database
    store = ContentAddressedGarminPayloadStore(paths.root / "garmin-artifacts")
    payload = production_sleep()
    bounds = _day_bounds(DAY)
    repository = GarminPersistenceRepository(session, payload_store=store)
    if problem == "invalid":
        payload["dailySleepDTO"]["sleepTimeSeconds"] = "bad"
        payload["sleepLevels"] = "bad"
    result = normalized(payload)
    scope = _collection_scope(SURFACE, day=DAY, window_start=DAY, window_end=DAY,
        fetch_complete=True, coverage_status="present")
    original = repository.persist_result(result, payload=payload,
        source_identity=SOURCE, source_filename="sleep.json",
        source_window_start_utc=bounds[0], source_window_end_utc=bounds[1],
        received_at=datetime(2099, 1, 3, tzinfo=UTC), collection_scope=scope)
    session.commit()
    observation = session.scalar(select(GarminPayloadObservation))
    observation_id, source_id = observation.id, observation.garmin_source_id
    if problem in {"hash", "byte_cap"}:
        artifact = session.get(RawArtifact, observation.raw_artifact_id)
        if problem == "hash":
            monkeypatch.setattr(store, "read", lambda *args, **kwargs: b"0" * artifact.byte_size)
        else:
            from healthcheck.garmin import sleep_preview
            monkeypatch.setattr(sleep_preview, "MAX_PREVIEW_BYTES", 1)
    elif problem == "stale":
        newer = deepcopy(payload)
        newer["dailySleepDTO"]["sleepStartTimestampGMT"] += 60000
        newer["dailySleepDTO"]["sleepStartTimestampLocal"] += 60000
        newer["sleepLevels"][0]["startGMT"] = (START + timedelta(minutes=1)).isoformat()
        repository.persist_result(normalized(newer), payload=newer,
            source_identity=SOURCE, source_filename="sleep.json",
            source_window_start_utc=bounds[0], source_window_end_utc=bounds[1],
            received_at=datetime(2099, 1, 4, tzinfo=UTC), collection_scope=scope)
    session.commit()
    before = (paths.root / "healthcheck.db").read_bytes()
    with _read_session(paths.root) as readonly:
        kwargs = dict(payload_store=store,
            source_id="foreign" if problem == "foreign" else source_id,
            observation_ids=[observation_id], start_date=DAY, end_date=DAY)
        if problem in {"hash", "byte_cap", "foreign"}:
            with pytest.raises(ValueError):
                preview_saved_garmin_sleep(readonly, **kwargs)
        else:
            preview = preview_saved_garmin_sleep(readonly, **kwargs)
            candidate = preview["observations"][0]["candidates"][0]
            assert preview["writes_performed"] is False
            assert candidate["current_record_id"] == original.records[0].id
            assert candidate["identity_transition"] == "preserved"
            assert candidate["complete_stage_boundary_available"] is (problem != "invalid")
            assert candidate["replacement_candidate"] is (problem not in {"stale", "invalid"})
            assert candidate["older_than_current_projection"] is (problem == "stale")
            assert candidate["stored_v6_eligibility"] == "unchanged_not_recomputed"
    assert (paths.root / "healthcheck.db").read_bytes() == before


@pytest.mark.parametrize("ids,days", [([], 1), (["one"] * 2, 1),
                                      ([str(i) for i in range(31)], 1), (["one"], 31)])
def test_preview_caps_fail_before_database_or_artifact_access(ids, days):
    from healthcheck.garmin.sleep_preview import preview_saved_garmin_sleep
    with pytest.raises(ValueError, match="out_of_bounds"):
        preview_saved_garmin_sleep(None, payload_store=None, source_id="invented",
            observation_ids=ids, start_date=DAY, end_date=DAY + timedelta(days=days - 1))


@pytest.mark.parametrize("missing", ["start", "end"])
def test_google_documented_main_does_not_bypass_endpoint_gate(projection_database, missing):
    session, paths = projection_database
    payload = _google_sleep_payload()
    component = payload["dataPoints"][0]["sleep"]
    component["metadata"] = {"mainSleep": True}
    component["interval"].pop(missing + "Time")
    _persist_google(session, paths, payload=payload)
    session.commit()
    source_range = read_source_sleep_range(session, provider="google", wake_date=DAY, days=7)
    data = {"sleep": {"providers": {"google": {"selected_source_id": "invented",
        "acquisition_coverage": {"state": "unknown"}, "source_range": source_range}}},
        "context": {"rows": []}}
    analyze_saved_sleep(data, request())
    assert data["sleep_analysis_inputs"]["nights"] == []


@pytest.mark.parametrize("field,value", [("utcOffsetMinutes", 120),
    ("utcOffsetMinutes", "bad"), ("timeZone", "Europe/Paris"),
    ("timeZone", "invented/Unknown")])
def test_production_conflicting_or_invalid_explicit_zone_offset_is_excluded(field, value):
    payload = production_sleep(offset=0)
    payload[field] = value
    row = normalized(payload).records[0]
    assert row.temporal.measured_at_utc is None
    assert row.metric("sleep_stages").reason == "partial_collection"


def test_local_only_numeric_sleep_preserves_clock_without_inventing_instant():
    payload = production_sleep()
    del payload["dailySleepDTO"]["sleepStartTimestampGMT"]
    temporal = normalized(payload).records[0].temporal
    assert temporal.precision == "local"
    assert temporal.measured_at_utc is None and temporal.source_utc_offset_minutes is None
    assert temporal.local_wall_time == "2099-01-01T23:00:00"
    assert temporal.source_local_timestamp == str(
        payload["dailySleepDTO"]["sleepStartTimestampLocal"])


@pytest.mark.parametrize("empty", [False, True])
def test_sleep_version_currentness_and_stale_replay_preserve_current_identity(
    projection_database, empty,
):
    from sqlalchemy.orm import Session

    from healthcheck.db.models import GarminPayloadObservation, GarminSourceRecord
    from healthcheck.garmin.reprocess import _window_already_current
    from healthcheck.garmin.sync import _collection_scope, _day_bounds

    session, paths = projection_database
    store = ContentAddressedGarminPayloadStore(paths.root / "garmin-artifacts")
    repository = GarminPersistenceRepository(session, payload_store=store)
    payload = {} if empty else production_sleep()
    result = normalized(payload)
    legacy = replace(result, contract_version="r02-garmin-normalization-contract-v2",
        records=tuple(replace(r, temporal=_parse_record_temporal(payload, "payload")[0])
                      for r in result.records))
    bounds = _day_bounds(DAY)
    scope = _collection_scope(SURFACE, day=DAY, window_start=DAY, window_end=DAY,
        fetch_complete=True, coverage_status="confirmed_empty" if empty else "present")
    kwargs = dict(payload=payload, source_identity=SOURCE, source_filename="sleep.json",
        source_window_start_utc=bounds[0], source_window_end_utc=bounds[1],
        received_at=datetime(2099, 1, 3, tzinfo=UTC), collection_scope=scope)
    first = repository.persist_result(legacy, **kwargs)
    session.commit()
    old = session.scalar(select(GarminPayloadObservation))
    def factory():
        return Session(session.bind)
    assert not _window_already_current(factory, old, store=store,
        request_start=DAY, request_end=DAY)
    if empty:
        repository.persist_result(replace(result, status="invalid"), **kwargs)
        session.commit()
        assert not _window_already_current(factory, old, store=store,
            request_start=DAY, request_end=DAY)
    newer = repository.persist_result(result, **kwargs)
    session.commit()
    assert _window_already_current(factory, old, store=store,
        request_start=DAY, request_end=DAY)
    if not empty:
        assert first.records[0].id == newer.records[0].id
        assert newer.records[0].temporal_precision == "instant"
        # An older receive epoch cannot roll back the enriched current projection.
        kwargs["received_at"] = datetime(2099, 1, 2, tzinfo=UTC)
        repository.persist_result(legacy, **kwargs)
        session.commit()
        session.expire_all()
        current = session.get(GarminSourceRecord, first.records[0].id)
        assert current.normalization_contract_version == SLEEP_TIMING_CONTRACT_VERSION
        assert current.temporal_precision == "instant"

    else:
        # A later different immutable original cannot borrow the old v3 proof.
        kwargs["payload"] = b"{} "
        kwargs["received_at"] = datetime(2099, 1, 4, tzinfo=UTC)
        repository.persist_result(legacy, **kwargs)
        session.commit()
        assert not _window_already_current(factory, old, store=store,
            request_start=DAY, request_end=DAY)


@pytest.mark.parametrize("problem", ["invalid_root_gmt", "conflicting_root_pair"])
def test_production_nested_timing_retains_material_legacy_alias_diagnostics(problem):
    payload = production_sleep()
    if problem == "invalid_root_gmt":
        payload["startTimeGMT"] = "invalid"
    else:
        payload["startTimeGMT"] = START.isoformat()
        # Same nominal offset as the nested pair, but a different UTC instant.
        payload["startTimeLocal"] = "2099-01-02T00:00:00+01:00"
    result = normalized(payload)
    assert result.records[0].temporal.measured_at_utc is None
    assert result.records[0].metric("sleep_stages").reason == "partial_collection"
    assert {d.code for d in result.diagnostics} & {"invalid_datetime", "paired_time_mismatch"}
