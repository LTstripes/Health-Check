"""Synthetic-only #340 RHR eligibility, no-fallback and collision regressions."""

from copy import deepcopy
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from healthcheck.db.engine import create_sqlite_engine, session_scope
from healthcheck.db.models import GarminRecordMetric, GarminSourceRecord
from healthcheck.garmin.normalization import garmin_source_identity, normalize_garmin_payload
from healthcheck.garmin.persistence import GarminCollectionScope, GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.web.overview_view import read_overview_values
from test_garmin_query_dashboard import _ui
from test_period_brief_ui import _stage3_result, _stub_brief_service, seed_overview_v2

RHR = "resting_heart_rate_bpm"
DAY = date(2099, 1, 2)
NEXT = date(2099, 1, 3)
EARLY = datetime(2099, 1, 2, 8, tzinfo=UTC)
LATE = datetime(2099, 1, 2, 18, tzinfo=UTC)


@pytest.fixture(scope="module")
def rhr_engine(tmp_path_factory):
    _, _, paths = _ui(tmp_path_factory.mktemp("rhr340"))
    seed_overview_v2(paths)
    engine = create_sqlite_engine(paths)
    # A different, unattributed synthetic source must never supplement the
    # selected provider-shaped source. Both contain fabricated values only.
    with session_scope(engine) as session:
        payload = {"calendarDate": NEXT.isoformat(), "restingHeartRate": 99}
        GarminPersistenceRepository(
            session, payload_store=ContentAddressedGarminPayloadStore(paths.root / "artifacts"),
        ).persist_result(
            normalize_garmin_payload(payload, stream="daily_health",
                                     source_identity=garmin_source_identity(source_kind="synthetic")),
            payload=payload, received_at=LATE,
        )
    yield engine, paths
    engine.dispose()


@pytest.fixture
def stored(rhr_engine):
    engine, _ = rhr_engine
    with Session(engine, autoflush=False) as session:
        record, metric = session.execute(
            select(GarminSourceRecord, GarminRecordMetric)
            .join(GarminRecordMetric, GarminRecordMetric.record_id == GarminSourceRecord.id)
            .where(GarminRecordMetric.metric_code == RHR,
                   GarminSourceRecord.source_local_date == DAY)
        ).one()
        yield session, record, metric
        session.rollback()


def _read(stored, *, start=DAY, end=NEXT, selected=True):
    session, record, _ = stored
    session.flush()
    # Read persisted SQLite timestamps, as the route's fresh read session does;
    # SQLite returns UTC columns without tzinfo rather than identity-map inputs.
    session.expire_all()
    return read_overview_values(
        session, start=start, end=end,
        selected_id=record.garmin_source_id if selected else None,
    )


def _copy(stored, *, record_changes=None, metric_changes=None):
    session, record, metric = stored
    values = {c.name: getattr(record, c.name) for c in record.__table__.columns
              if c.name not in {"id", "idempotency_key"}}
    values.update(record_changes or {})
    duplicate = GarminSourceRecord(**values, idempotency_key=f"synthetic340-{uuid4()}")
    session.add(duplicate)
    session.flush()
    values = {c.name: getattr(metric, c.name) for c in metric.__table__.columns
              if c.name not in {"id", "record_id"}}
    values.update(metric_changes or {})
    other_metric = GarminRecordMetric(**values, record_id=duplicate.id)
    session.add(other_metric)
    session.flush()
    return duplicate, other_metric


@pytest.mark.parametrize("surface", [None, "daily_summary", "resting_heart_rate"])
def test_rhr_allowed_surfaces_keep_original_provenance(stored, surface):
    _, record, metric = stored
    record.surface_code = surface
    before = (record.garmin_source_id, record.raw_payload_id, metric.id, metric.field_path,
              metric.source_device_attributed)
    result = _read(stored)
    cell = result["garmin"][RHR]
    assert cell == {"label": "Пульс в покое", "state": "partial", "value": 52,
                    "date": DAY.isoformat(), "note": None}
    evidence = [r for r in result["technical"]["garmin"] if r["metric_code"] == RHR]
    assert evidence == [{"metric_code": RHR, "record_id": record.id, "state": "value",
                         "value": 52, "unit": "bpm", "field_path": metric.field_path,
                         "source_local_date": DAY.isoformat(), "source_timestamp_utc": None}]
    assert before == (record.garmin_source_id, record.raw_payload_id, metric.id, metric.field_path,
                      metric.source_device_attributed)


@pytest.mark.parametrize("surface", [None, "daily_summary", "resting_heart_rate"])
@pytest.mark.parametrize("guard,wrong", [
    ("surface_code", "daily_health"), ("surface_code", "hrv_status"),
    ("surface_code", "sleep"), ("surface_code", "activities"),
    ("surface_code", "heart_rate"), ("surface_code", "unknown_surface"),
    ("stream_code", "sleep"), ("stream_code", "activity"),
    ("stream_code", "intraday"), ("stream_code", "original_fit"),
    ("capability_code", "hrv_status"), ("capability_code", "unknown_capability"),
    ("metric_code", "heart_rate_bpm"),
])
def test_rhr_rejects_newer_wrong_identity_without_hiding_eligible_snapshot(stored, surface,
                                                                        guard, wrong):
    _, record, _ = stored
    record.surface_code = surface
    record_changes = {"source_local_date": NEXT, "surface_code": surface}
    metric_changes = {"value_number": 99}
    changes = metric_changes if guard in {"capability_code", "metric_code"} else record_changes
    changes[guard] = wrong
    bad, _ = _copy(stored, record_changes=record_changes, metric_changes=metric_changes)
    result = _read(stored)
    assert result["garmin"][RHR]["value"] == 52
    assert result["garmin"][RHR]["date"] == DAY.isoformat()
    assert bad.id not in {r["record_id"] for r in result["technical"]["garmin"]
                          if r["metric_code"] == RHR}


@pytest.mark.parametrize("start,end,expected", [
    (DAY, DAY, 52), (date(2099, 1, 1), DAY, 52), (DAY, NEXT, 52),
    (date(2099, 1, 1), date(2099, 1, 1), None), (NEXT, NEXT, None),
])
def test_rhr_selected_source_and_inclusive_local_window(stored, start, end, expected):
    result = _read(stored, start=start, end=end)
    assert result["garmin"][RHR]["value"] == expected  # second source's 99 never wins
    assert not _read(stored, selected=False)["garmin"]
    assert not _read(stored, selected=False)["technical"]["garmin"]


def test_rhr_unknown_selected_source_does_not_fall_back_to_google_or_other_garmin(stored):
    session, _, _ = stored
    result = read_overview_values(session, start=DAY, end=NEXT, selected_id="unknown-synthetic-id")
    assert result["garmin"][RHR]["value"] is None
    assert result["garmin"][RHR]["state"] == "unknown"
    assert not result["technical"]["garmin"]


@pytest.mark.parametrize("state,number,unit,parent,expected,reason", [
    ("missing", None, "bpm", "partial", None, "не передал"),
    ("null", None, "bpm", "ok", None, "пустое"),
    ("invalid", None, "bpm", "ok", None, "непригодно"),
    ("value", 80, "ms", "ok", None, "единица"),
    ("value", 80, None, "ok", None, "единица"),
    ("value", None, "bpm", "ok", None, "число"),
    ("value", float("inf"), "bpm", "ok", None, "число"),
    ("value", float("-inf"), "bpm", "ok", None, "число"),
    ("value", float("nan"), "bpm", "ok", None, "число"),
    ("value", 80, "bpm", "invalid", None, "запись"),
    ("value", 80, "bpm", "empty", None, "число"),
    ("value", 80, "bpm", "partial", 80, None),
    ("value", 0, "bpm", "ok", 0, None),
])
def test_rhr_newest_snapshot_is_checked_without_older_value_fallback(
    stored, state, number, unit, parent, expected, reason,
):
    newest, _ = _copy(stored, record_changes={
        "source_local_date": NEXT, "surface_code": "daily_summary", "record_status": parent,
    }, metric_changes={"state": state, "value_number": number, "unit": unit})
    cell = _read(stored)["garmin"][RHR]
    assert cell["value"] == expected
    assert cell["date"] == NEXT.isoformat()
    assert cell["state"] == ("unavailable" if expected is None else
                             "partial" if parent == "partial" else "present")
    if reason:
        assert reason.lower() in cell["note"].lower()
    newest.projection_status, newest.retired_at, newest.retire_reason = "retired", LATE, "synthetic"
    assert _read(stored)["garmin"][RHR]["value"] == 52


def test_rhr_non_numeric_sqlite_value_is_unavailable(stored):
    session, _, _ = stored
    _, metric = _copy(stored, record_changes={"source_local_date": NEXT})
    # SQLite dynamic typing can expose corrupt text even in a Float column.
    session.execute(text("UPDATE garmin_record_metrics SET value_number=:bad WHERE id=:id"),
                    {"bad": "not-a-number", "id": metric.id})
    session.expire(metric)
    assert _read(stored)["garmin"][RHR]["state"] == "unavailable"
    assert _read(stored)["garmin"][RHR]["value"] is None


@pytest.mark.parametrize("surface_a,surface_b", [
    ("daily_summary", "resting_heart_rate"), ("resting_heart_rate", "daily_summary"),
    (None, "daily_summary"), ("daily_summary", None),
])
@pytest.mark.parametrize("stamp_a,stamp_b,expected", [
    (None, None, None), (EARLY, None, None), (None, LATE, None),
    (LATE, LATE, None), (EARLY, LATE, 80), (LATE, EARLY, 52),
])
def test_rhr_cross_surface_collisions_use_only_complete_source_instants(
    stored, surface_a, surface_b, stamp_a, stamp_b, expected,
):
    _, record, _ = stored
    record.surface_code, record.source_timestamp_utc = surface_a, stamp_a
    record.projection_observed_at = datetime(2099, 2, 1, tzinfo=UTC)
    _copy(stored, record_changes={"surface_code": surface_b, "source_timestamp_utc": stamp_b,
                                 "projection_observed_at": EARLY},
          metric_changes={"value_number": 80})
    cell = _read(stored)["garmin"][RHR]
    assert cell["value"] == expected
    assert cell["date"] == DAY.isoformat()
    if expected is None:
        assert "несколько снимков" in cell["note"]


@pytest.mark.parametrize("stamp", [None, LATE])
@pytest.mark.parametrize("state,value", [("value", 52), ("missing", None)])
def test_rhr_equal_number_or_missing_does_not_resolve_collision(stored, stamp, state, value):
    _, record, _ = stored
    record.source_timestamp_utc = stamp
    _copy(stored, record_changes={"surface_code": "daily_summary", "source_timestamp_utc": stamp},
          metric_changes={"state": state, "value_number": value})
    cell = _read(stored)["garmin"][RHR]
    assert cell["value"] is None and "несколько снимков" in cell["note"]


def test_rhr_later_source_instant_missing_blocks_older_same_day_value(stored):
    _, record, _ = stored
    record.source_timestamp_utc = EARLY
    _copy(stored, record_changes={"surface_code": "daily_summary", "source_timestamp_utc": LATE},
          metric_changes={"state": "missing", "value_number": None})
    cell = _read(stored)["garmin"][RHR]
    assert cell["state"] == "unavailable" and cell["value"] is None
    assert "не передал" in cell["note"]


@pytest.mark.parametrize("surface", ["daily_summary", "resting_heart_rate"])
def test_rhr_production_collection_scope_displays_only_rhr(stored, rhr_engine, surface):
    session, _, _ = stored
    _, paths = rhr_engine
    before = _read(stored)
    payload = {"calendarDate": NEXT.isoformat(), "restingHeartRate": 61,
               "hrvSummary": {"weeklyAvg": 77}}
    GarminPersistenceRepository(
        session, payload_store=ContentAddressedGarminPayloadStore(paths.root / "artifacts"),
    ).persist_result(
        normalize_garmin_payload(payload, stream="daily_health",
                                 source_identity=garmin_source_identity(source_kind="provider")),
        payload=payload, received_at=LATE,
        collection_scope=GarminCollectionScope(
            surface=surface, stream="daily_health", kind="day_singleton",
            window_start=NEXT, window_end=NEXT, complete=True,
        ),
    )
    session.flush()
    statements = []
    def listener(_c, _cur, sql, *_a):
        statements.append(sql)

    event.listen(session.bind, "before_cursor_execute", listener)
    try:
        after = _read(stored)
    finally:
        event.remove(session.bind, "before_cursor_execute", listener)
    assert after["garmin"][RHR]["value"] == 61
    assert after["garmin"][RHR]["state"] == "partial"
    assert after["google"] == before["google"]
    assert after["technical"]["google"] == before["technical"]["google"]
    assert {k: v for k, v in after["garmin"].items() if k != RHR} == {
        k: v for k, v in before["garmin"].items() if k != RHR
    }
    assert after["training"] == before["training"]
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                   for sql in statements)


@pytest.mark.parametrize("reason,state,notice", [
    ("reauth_required", "unavailable", "нужен повторный вход"),
    ("refresh_failed", "stale", "ошибка обновления"),
    ("refresh_overdue", "stale", "проверьте сбор данных"),
    ("expected_evidence_absent", "unknown", "проверьте сбор данных"),
])
def test_rhr_display_keeps_source_warning_packet_and_hash(
    tmp_path, monkeypatch, reason, state, notice,
):
    app, _, paths = _ui(tmp_path)
    seed_overview_v2(paths)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            record = session.scalar(select(GarminSourceRecord).where(
                GarminSourceRecord.stream_code == "daily_health"))
            record.surface_code = "daily_summary"
            source_id = record.garmin_source_id
    finally:
        engine.dispose()
    result = _stage3_result()
    actions = [{"code": "source_freshness_attention", "scope_key": "garmin:daily_summary",
                "reason_code": reason, "state": state}]
    for payload in (result["packet"], result["display"]):
        payload["owner_actions"] = deepcopy(actions)
    before = deepcopy(result)
    _stub_brief_service(monkeypatch, result, source_selection={
        "status": "selected", "selected_source_id": source_id, "sources": [],
    })
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        response = client.get("/brief?start_date=2099-01-01&end_date=2099-01-02")
    assert response.status_code == 200
    cell = response.context["overview"]["garmin"][RHR]
    assert cell["value"] == 52 and cell["state"] == "partial"
    secondary = response.text.split('class="overview-secondary"', 1)[1].split("</section>", 1)[0]
    assert "52 уд/мин" in secondary
    assert f"Garmin: {notice}" in response.text
    assert "Сохранённая история не подтверждает свежесть" in response.text
    assert result == before and response.context["packet"] == before["packet"]
    assert response.context["brief"]["source_result_hash"] == "synthetic-result-hash"
