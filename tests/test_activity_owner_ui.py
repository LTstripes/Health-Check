"""Stage 6 presentation checks against unchanged Garmin reads, using synthetic evidence."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from healthcheck.db.engine import create_sqlite_engine, session_scope
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


def client_for(app):
    return TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    )


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
