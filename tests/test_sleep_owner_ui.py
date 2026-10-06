"""Stage-5 presentation regressions with disposable synthetic persisted evidence."""

import copy
import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from healthcheck.db.engine import create_sqlite_engine, session_scope
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.web.garmin_query import GarminQueryService
from healthcheck.web.sleep_view import metric_value, night_metric, point_state
from test_garmin_query_dashboard import _persist, _ui
from test_sleep_agreement_report import _rows, _run, _service


def seed_sleep(paths):
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            payload = json.loads((Path(__file__).parent / "fixtures/garmin/sleep.json").read_text())
            outcome = _persist(
                session, ContentAddressedGarminPayloadStore(paths.root / "artifacts"), payload
            )
            return outcome.records[0].garmin_source_id
    finally:
        engine.dispose()


def agreement_fixture():
    run = _run()
    pairs, metrics = _rows(cohort="family_pair", count=14)
    return _service(run, pairs, metrics).report(run_id=run.id)


def client_for(app):
    return TestClient(app, base_url="http://127.0.0.1:8120")


@pytest.mark.parametrize(
    ("point", "state"),
    [
        (None, "unavailable"),
        ({"status": "missing", "value": None}, "unavailable"),
        ({"status": "null", "value": None}, "unavailable"),
        ({"status": "zero", "value": 0}, "present"),
        ({"status": "partial", "value": 120}, "partial"),
        ({"status": "usable", "value": 28800}, "present"),
        ({"status": "usable", "value": None}, "unknown"),
        ({"status": "usable", "value": float("nan")}, "unknown"),
        ({"status": "usable", "value": False}, "unknown"),
        ({"status": "future", "value": 12}, "unknown"),
        ({"status": "excluded", "value": 12}, "unavailable"),
    ],
)
def test_sleep_point_states_keep_unknown_missing_partial_and_zero(point, state):
    assert point_state(point) == state


def test_selected_night_never_borrows_or_pools():
    point = {"status": "usable", "value": 28800, "analytic_date": "2099-01-02"}
    assert night_metric({"points": [point]}, date(2099, 1, 3))["value"] is None
    assert night_metric({"points": [point]}, date(2099, 1, 2))["value"] == 28800
    ambiguous = night_metric({"points": [point, point]}, date(2099, 1, 2))
    assert ambiguous == {"state": "unknown", "value": None, "ambiguous": True}


def test_sleep_duration_formatting_preserves_seconds_and_zero():
    assert metric_value("sleep_duration_seconds", 28800) == "8 ч 0 мин"
    assert metric_value("sleep_duration_seconds", 3661) == "1 ч 1 мин 1 с"
    assert metric_value("sleep_duration_seconds", 0) == "0 ч 0 мин"
    assert metric_value("sleep_duration_seconds", 1.25) == "1.25 с"


def test_sleep_page_reads_existing_results_without_mutation(tmp_path):
    app, settings, paths = _ui(tmp_path)
    source = seed_sleep(paths)
    engine = create_sqlite_engine(paths)
    direct = {}
    try:
        with session_scope(engine) as session:
            for code in ("sleep_duration_seconds", "sleep_score"):
                direct[code] = GarminQueryService(session, settings).scalar_series(
                    garmin_source_id=source,
                    metric_code=code,
                    start_date=date(2098, 12, 4),
                    end_date=date(2099, 1, 2),
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
        page = client.get("/sleep?wake_date=2099-01-02")
        assert page.status_code == 200
        primary, technical = page.text.split(
            '<details class="card owner-details sleep-technical"', 1
        )
        assert "<th>Состояние</th>" not in primary
        assert "status-chip owner-state present" not in primary
        assert '<select name="garmin_source_id"' not in primary
        assert "2 января 2099" in primary
        assert "8 ч 0 мин" in primary
        assert "82.0 баллы" in primary or "82 баллы" in primary
        assert "История сна" in primary and "Точность устройств" in primary
        assert 'href="/imports"' in primary
        assert "r03-01" not in primary and "result_hash" not in primary
        assert all(body["result_hash"] in technical for body in direct.values())
        assert 'lang="en"' not in page.text
        assert 'class="card owner-details" open' not in page.text
        for code, body in direct.items():
            result = client.get(
                "/api/garmin/series",
                params={
                    "garmin_source_id": source,
                    "metric_code": code,
                    "start_date": "2098-12-04",
                    "end_date": "2099-01-02",
                },
            ).json()
            assert result == body
        missing = client.get("/sleep?wake_date=2099-01-03")
        hero = missing.text.split("<summary>История сна</summary>", 1)[0]
        assert "нет пригодного значения" in hero
        assert "28800" not in hero and "82.0" not in hero
    assert "BEGIN" in statements
    assert not any(
        sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements
    )


def test_sleep_ambiguous_source_fails_closed_and_escapes_labels(tmp_path, monkeypatch):
    app, _settings, _paths = _ui(tmp_path)
    selection = {
        "status": "require_selection",
        "sources": [
            {"id": "a", "device_attributed": True, "device_model": "<script>alert(1)</script>"},
            {"id": "b", "device_attributed": False},
        ],
    }
    monkeypatch.setattr(GarminQueryService, "resolve_source", lambda *args: selection)
    monkeypatch.setattr(
        GarminQueryService,
        "scalar_series",
        lambda *args, **kwargs: pytest.fail("ambiguous source must not read series"),
    )
    with client_for(app) as client:
        page = client.get("/sleep")
        assert page.status_code == 200
        assert "Найдено несколько источников" in page.text
        assert 'data-owner-state="unknown"' in page.text
        assert "<script>alert" not in page.text
        assert "&lt;script&gt;" in page.text
        assert client.get("/sleep?wake_date=0001-01-01").status_code == 400
        invalid = client.get("/sleep?wake_date=invalid")
        assert invalid.status_code == 400
        assert "Укажите дату пробуждения" in invalid.text


def test_sleep_empty_and_unavailable_stay_honest(tmp_path):
    app, _settings, _paths = _ui(tmp_path)
    with client_for(app) as client:
        page = client.get("/sleep")
        primary = page.text.split('<details class="card owner-details', 1)[0]
        assert "Нет доступного источника Garmin" in primary
        assert 'data-owner-state="unavailable"' in primary
        assert "0 с" not in primary and "0 баллы" not in primary
        assert client.get("/sleep?garmin_source_id=unknown").status_code == 200
    app.state.engine.dispose()
    app.state.runtime_paths.database.unlink()
    with client_for(app) as client:
        page = client.get("/sleep")
        assert page.status_code == 200
        assert "Локальное хранилище данных не готово" in page.text


def test_agreement_secondary_keeps_frozen_packet_and_discloses_statistics(tmp_path, monkeypatch):
    from healthcheck.analytics.sleep_agreement_report import SleepAgreementReportService

    app, _settings, _paths = _ui(tmp_path)
    packet = agreement_fixture()
    # Interpretation-changing uncertainty is visible; exact source text is technical.
    packet["groups"][0]["uncertainty_notice"] = "synthetic-internal-uncertainty"
    packet["groups"][0]["exclusions"] = {"synthetic-exclusion": 2}
    before = copy.deepcopy(packet)
    monkeypatch.setattr(SleepAgreementReportService, "report", lambda *a, **kw: packet)
    with client_for(app) as client:
        page = client.get("/agreement")
        assert page.status_code == 200
        primary, technical = page.text.split('<details class="card owner-details', 1)
        assert "Исследовательское сравнение" in primary
        assert "Длительность сна" in primary and "Семейство устройств Google" in primary
        assert "Принадлежность устройству" in primary and "Часть данных исключена" in primary
        assert "sleep_duration_asleep_seconds" not in primary
        assert "synthetic-internal-uncertainty" not in primary
        assert "synthetic-exclusion" not in primary
        assert "bias" not in primary and "rmse" not in primary
        assert "bias" in technical and "rmse" in technical
        assert "synthetic-exclusion" in technical
        assert 'href="/sleep"' in primary and 'lang="en"' not in page.text
        assert "Сохранённый период: 1 января 2099 → 14 января 2099" in primary
        assert " open>" not in page.text
        assert client.get("/api/agreement/report").json() == packet
    assert packet == before


def test_agreement_accumulation_does_not_fabricate_statistics(tmp_path, monkeypatch):
    from healthcheck.analytics.sleep_agreement_report import SleepAgreementReportService

    app, _settings, _paths = _ui(tmp_path)
    run = _run()
    pairs, metrics = _rows(count=1)
    packet = _service(run, pairs, metrics).report(run_id=run.id)
    monkeypatch.setattr(SleepAgreementReportService, "report", lambda *a, **kw: packet)
    with client_for(app) as client:
        page = client.get("/agreement")
        assert page.status_code == 200
        assert 'data-owner-state="insufficient"' in page.text
        assert "Принятая статистика пока недоступна" in page.text
        assert "осталось пригодных пар: 13" in page.text
        assert "Принятая исследовательская статистика" not in page.text
