"""Stage 6 presentation checks against unchanged Garmin reads, using synthetic evidence."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from healthcheck.db.engine import create_sqlite_engine, session_scope
from healthcheck.db.models import GarminSourceRecord
from healthcheck.garmin.normalization import garmin_source_identity, normalize_garmin_payload
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.web.garmin_query import GarminQueryService
from test_garmin_training_owner_view import _seed_training, _ui


def seed_activity(paths):
    """Shared disposable seed for focused tests and the narrow browser smoke."""
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            source = _seed_training(session, store)
            for index in range(8):
                day = date(2099, 1, 1) + timedelta(days=index)
                payload = {
                    "calendarDate": day.isoformat(),
                    "avgStressLevel": None if index == 3 else index * 4,
                    "averageSpO2": 95 + index % 3,
                }
                result = normalize_garmin_payload(
                    payload,
                    stream="intraday",
                    source_identity=garmin_source_identity(source_kind="provider"),
                )
                GarminPersistenceRepository(session, payload_store=store).persist_result(
                    result, payload=payload, received_at=datetime(2099, 1, 9, tzinfo=UTC)
                )
            session.commit()
            return source
    finally:
        engine.dispose()


def seed_activity_comparison_tennis(paths):
    """Two synthetic tennis sessions with exact seconds and zero/missing coverage."""
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            payload = {
                "activities": [
                    {
                        "activityId": f"synthetic-tennis-{index}",
                        "activityType": {"typeKey": "tennis_v2"},
                        "calendarDate": f"2099-01-0{index + 1}",
                        "duration": duration,
                        "distance": distance,
                        "averageHR": heart_rate,
                        "averageSpeed": 3.5,
                        "averageBikeCadence": None,
                        "activityTrainingLoad": load,
                        "aerobicTrainingEffect": 2.5,
                    }
                    for index, (duration, distance, heart_rate, load) in enumerate(
                        ((3901.25, None, 110, 10), (3600, 0, 100, 0))
                    )
                ]
            }
            result = normalize_garmin_payload(
                payload,
                stream="activity",
                source_identity=garmin_source_identity(source_kind="provider"),
            )
            GarminPersistenceRepository(
                session, payload_store=ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            ).persist_result(result, payload=payload, received_at=datetime(2099, 1, 9, tzinfo=UTC))
    finally:
        engine.dispose()


def client_for(app):
    return TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    )


def seed_second_activity_source(paths):
    """Independent synthetic recorder for source-switch checks."""
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            payload = {
                "activities": [
                    {
                        "activityId": f"second-{index}",
                        "calendarDate": f"2099-01-0{index + 1}",
                        "activityType": {"typeKey": "walking"},
                        "duration": duration,
                    }
                    for index, duration in enumerate((600, None))
                ]
            }
            result = normalize_garmin_payload(
                payload,
                stream="activity",
                source_identity=garmin_source_identity(
                    source_kind="provider",
                    device_attributed=True,
                    device_code="synthetic-second",
                    device_model="Synthetic recorder",
                ),
            )
            GarminPersistenceRepository(
                session, payload_store=ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            ).persist_result(result, payload=payload, received_at=datetime(2099, 1, 9, tzinfo=UTC))
    finally:
        engine.dispose()


def test_activity_multiple_sources_require_explicit_selection(tmp_path):
    app, _, paths = _ui(tmp_path)
    source = seed_activity(paths)
    seed_second_activity_source(paths)
    with client_for(app) as client:
        page = client.get("/garmin")
        assert 'id="source-form"' in page.text
        assert "Выбери источник Garmin. Данные разных источников не объединяются." in page.text
        embedded = re.search(
            r'<script id="garmin-dashboard-data"[^>]*>(.*?)</script>', page.text, re.S
        )
        payload = json.loads(embedded.group(1))
        assert len(payload["source_selection"]["sources"]) == 2
        assert payload["activities"] == []
        selected = client.get("/garmin", params={"garmin_source_id": source})
        assert 'id="source-form"' in selected.text
        assert "Велотренировка" in selected.text
        assert "Ходьба" not in selected.text


def test_activity_owner_surface_disclosure_and_read_parity(tmp_path):
    app, settings, paths = _ui(tmp_path)
    source = seed_activity(paths)
    engine = create_sqlite_engine(paths)
    params = {
        "garmin_source_id": source,
        "metric_code": "stress_daily_average",
        "start_date": "2099-01-01",
        "end_date": "2099-01-08",
    }
    try:
        with session_scope(engine) as session:
            direct = GarminQueryService(session, settings).dashboard(
                **{**params, "start_date": date(2099, 1, 1), "end_date": date(2099, 1, 8)}
            )
    finally:
        engine.dispose()
    statements = []
    app.state.engine = create_sqlite_engine(paths)
    with client_for(app) as client:
        event.listen(
            app.state.engine,
            "before_cursor_execute",
            lambda _c, _cur, sql, *_a: statements.append(sql),
        )
        page = client.get("/garmin", params=params)
        assert page.status_code == 200
        primary, technical = page.text.split(
            '<details class="card owner-details activity-technical', 1
        )
        assert 'lang="en"' not in page.text
        assert "Последние сессии" in primary and "Сравнить сессии" in primary
        assert 'id="source-form"' not in primary
        assert 'id="garmin-source-id"' not in primary
        assert "Сессии Google пока не загружаются" in primary
        assert 'id="activity-a"' in primary and 'id="activity-b"' in primary
        assert 'id="activity-ids"' not in primary and " multiple " not in primary
        assert "B минус A" in primary and "относительно A" in primary
        assert page.text.count('activity-technical"') == 1
        assert "Тренировки и восстановление" in primary and "Острая нагрузка Garmin" in primary
        assert "3 января 2099" in primary and "2 января 2099, 12:00 UTC" in primary
        assert "2099-01-02T12:00:00+00:00" in technical
        assert "Единица времени восстановления не предоставлена" in primary
        assert "Дата запроса не подставляется" in primary
        assert "Производитель каждой метрики не подтверждён" in primary
        assert 'href="/imports"' in primary
        assert 'data-owner-state="present">0.0</span>' in primary
        assert 'data-owner-state="unavailable">Не предоставлено' in primary
        for internal in (
            "result_hash",
            "dailyTrainingLoadAcute",
            "synthetic feedback",
            "synthetic status",
            "activity recorder",
            source,
        ):
            assert internal not in re.sub(r'<option value="[^"]+"', "<option", primary)
            assert internal in technical
        assert 'activity-technical" open' not in page.text
        # Embedded data and APIs are exact service results, not UI recomputations.
        embedded = re.search(
            r'<script id="garmin-dashboard-data"[^>]*>(.*?)</script>', page.text, re.S
        )
        assert json.loads(embedded.group(1)) == direct
        assert client.get("/api/garmin/dashboard", params=params).json() == direct
        assert client.get("/api/garmin/series", params=params).json() == direct["series"]
        assert (
            client.get("/api/garmin/training-overview", params={"garmin_source_id": source}).json()
            == direct["training_overview"]
        )
        activity_ids = [a["record_id"] for a in direct["activities"]]
        with session_scope(app.state.engine) as session:
            expected = GarminQueryService(session, settings).activity_comparison(
                garmin_source_id=source,
                activity_record_ids=activity_ids,
                reference_activity_id=activity_ids[0],
                metric_codes=None,
            )
        assert (
            client.get(
                "/api/garmin/activity-comparison",
                params={
                    "garmin_source_id": source,
                    "activity_record_ids": ",".join(activity_ids),
                    "reference_activity_id": activity_ids[0],
                },
            ).json()
            == expected
        )
    assert not any(
        sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements
    )
    app.state.engine.dispose()


def test_tennis_v2_labels_cover_journal_summary_and_comparison(tmp_path):
    app, _, paths = _ui(tmp_path)
    source = seed_activity(paths)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            records = session.scalars(
                select(GarminSourceRecord).where(GarminSourceRecord.stream_code == "activity")
            ).all()
            assert len(records) == 2
            for record in records:
                record.activity_type = "tennis_v2"
            session.commit()
    finally:
        engine.dispose()

    with client_for(app) as client:
        page = client.get("/garmin", params={"garmin_source_id": source})
        assert page.status_code == 200
        primary = page.text.split('<details class="card owner-details activity-technical', 1)[0]
        embedded = re.search(
            r'<script id="garmin-dashboard-data"[^>]*>(.*?)</script>', page.text, re.S
        )
        payload = json.loads(embedded.group(1))
        assert {activity["activity_type"] for activity in payload["activities"]} == {"tennis_v2"}
        summary_types = {
            activity["activity_type"]
            for activity in payload["training_overview"]["recent_activities"]
        }
        assert summary_types == {"tennis_v2"}
        assert primary.count("Теннис") >= 2, (
            f"labels missing; journal={len(payload['activities'])}, "
            f"summary={len(payload['training_overview']['recent_activities'])}"
        )
        assert "Другой вид активности" not in primary
        script = client.get("/static/garmin_dashboard.js")
        assert script.status_code == 200
        assert 'tennis_v2: "Теннис"' in script.text
        assert "activityNames[activity.activity_type]" in script.text
    app.state.engine.dispose()


def test_tennis_comparison_keeps_exact_seconds_and_coverage(tmp_path):
    app, _, paths = _ui(tmp_path)
    seed_activity_comparison_tennis(paths)
    with client_for(app) as client:
        page = client.get("/garmin")
        assert "/static/activity_comparison.css" in page.text
        embedded = re.search(
            r'<script id="garmin-dashboard-data"[^>]*>(.*?)</script>', page.text, re.S
        )
        activities = json.loads(embedded.group(1))["activities"]
        assert [item["activity_type"] for item in activities] == ["tennis_v2", "tennis_v2"]
        ids = [item["record_id"] for item in activities]
        source = json.loads(embedded.group(1))["source_selection"]["selected_source_id"]
        response = client.get(
            "/api/garmin/activity-comparison",
            params={
                "garmin_source_id": source,
                "activity_record_ids": ",".join(ids),
                "reference_activity_id": ids[0],
            },
        )
        assert response.status_code == 200
        body = response.json()
        metrics = {m["metric_code"]: m for m in body["comparisons"][0]["metrics"]}
        duration = metrics["duration_seconds"]
        assert duration["reference_value"] == 3600
        assert duration["compared_value"] == 3901.25
        assert duration["absolute_delta"] == 301.25
        assert duration["percent_delta"] == pytest.approx(301.25 / 3600 * 100)
        assert metrics["acute_training_load"]["percent_reason"] == "zero_reference_percent"
        coverage = {s["record_id"]: s["metric_coverage"] for s in body["sessions"]}
        a_distance = next(m for m in coverage[ids[0]] if m["metric_code"] == "distance_meters")
        b_distance = next(m for m in coverage[ids[1]] if m["metric_code"] == "distance_meters")
        assert a_distance["status"] == "zero" and a_distance["value"] == 0
        assert b_distance["status"] == "null" and b_distance["value"] is None
        assert {"power_watts", "cadence_rpm"}.issubset(metrics)
    app.state.engine.dispose()


@pytest.mark.parametrize("field_state", ["missing", "null", "invalid"])
def test_activity_field_does_not_invent_zero_or_units(tmp_path, monkeypatch, field_state):
    app, settings, paths = _ui(tmp_path)
    source = seed_activity(paths)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            payload = GarminQueryService(session, settings).dashboard(garmin_source_id=source)
    finally:
        engine.dispose()
    for block in (
        payload["training_overview"]["readiness"],
        payload["training_overview"]["training_status"],
    ):
        for field in block["fields"].values():
            field.update(state=field_state, value=None)
    monkeypatch.setattr(GarminQueryService, "dashboard", lambda *a, **kw: payload)
    with client_for(app) as client:
        primary = client.get("/garmin").text.split(
            '<details class="card owner-details activity-technical', 1
        )[0]
    recovery = primary.split("<h3>Готовность и восстановление</h3>", 1)[1].split("</section>", 1)[0]
    assert ">0</span>" not in recovery
    state = "unknown" if field_state == "invalid" else "unavailable"
    assert f'data-owner-state="{state}"' in recovery
    assert "часы или минуты" in recovery


def test_activity_empty_is_unavailable_and_no_fabricated_sessions(tmp_path):
    app, _, _ = _ui(tmp_path)
    with client_for(app) as client:
        primary = client.get("/garmin").text.split(
            '<details class="card owner-details activity-technical', 1
        )[0]
    assert "Источник Garmin пока не найден" in primary
    assert 'id="source-form"' not in primary
    assert "Это не означает отсутствие тренировок" in primary
    assert "Нагрузка не считается нулевой" in primary
    assert 'data-owner-state="confirmed_empty"' not in primary
    assert ">0</span>" not in primary


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2099-01-02", "2 января 2099"),
        ("2099-01-02T12:34:56Z", "2 января 2099, 12:34 UTC"),
        ("2099-01-02T00:30:00+03:00", "2 января 2099, 00:30 UTC+0300"),
        ("2099-01-02T12:34:56", "2 января 2099, 12:34"),
        (None, "Дата не указана"),
        ("bad-date", "Дата не указана"),
    ],
)
def test_owner_dates_preserve_source_day_precision_and_zone(value, expected):
    from healthcheck.web.owner_presentation import owner_date

    assert owner_date(value) == expected


def test_activity_rounds_display_only_and_preserves_raw_precision(tmp_path, monkeypatch):
    app, settings, paths = _ui(tmp_path)
    source = seed_activity(paths)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            payload = GarminQueryService(session, settings).dashboard(garmin_source_id=source)
    finally:
        engine.dispose()
    field = payload["training_overview"]["training_status"]["fields"]["dailyTrainingLoadAcute"]
    field.update(state="value", value=123.456789)
    monkeypatch.setattr(GarminQueryService, "dashboard", lambda *a, **kw: payload)
    with client_for(app) as client:
        page = client.get("/garmin")
    primary, technical = page.text.split('<details class="card owner-details activity-technical', 1)
    assert ">123.5</span>" in primary and "123.456789" not in primary
    assert "123.456789" in technical
    assert field["value"] == 123.456789
