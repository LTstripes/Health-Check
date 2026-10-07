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


def agreement_service_fixture():
    run = _run()
    pairs, metrics = _rows(cohort="family_pair", count=14)
    for index, metric in enumerate(metrics):
        metric.variant = "STAGES"
        manifest = json.loads(metric.manifest_json)
        for provider in ("garmin", "google"):
            manifest[provider]["evidence"]["source_id"] = provider + "-synthetic-source"
            manifest[provider]["comparison_basis"] = "persisted_metric"
            manifest[provider]["value"] = 28800 + (120 + index * 60 if provider == "google" else 0)
        metric.difference_number = 120.0 + index * 60
        metric.manifest_json = json.dumps(manifest)
    return _service(run, pairs, metrics)


def agreement_fixture():
    return agreement_service_fixture().report(run_id="run-1")


def agreement_detail_fixture():
    return agreement_service_fixture().night_detail("run-1")


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
    assert metric_value("sleep_duration_seconds", 1.25) == "1.2 с"


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
        assert "История сна" in primary and "Точность устройств" not in primary
        assert "Точность устройств" in technical
        assert page.text.count("<summary>Технические детали</summary>") == 1
        assert primary.count("data-night-row") == 1
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
    detail = agreement_detail_fixture()
    monkeypatch.setattr(SleepAgreementReportService, "report", lambda *a, **kw: packet)
    monkeypatch.setattr(SleepAgreementReportService, "night_detail", lambda *a, **kw: detail)
    with client_for(app) as client:
        page = client.get("/agreement")
        assert page.status_code == 200
        primary, technical = page.text.split('<details class="card owner-details', 1)
        assert "Сравнение сна" in primary
        assert "Исследовательское сравнение" not in primary
        assert "Длительность сна" in primary and "Семейство устройств Google" in primary
        assert "Принадлежность устройству" in primary and "Часть данных исключена" in primary
        assert "sleep_duration_asleep_seconds" not in primary
        assert "synthetic-internal-uncertainty" not in primary
        assert "synthetic-exclusion" not in primary
        assert "bias" not in primary and "rmse" not in primary
        assert "Средняя разность" in primary and "+8 мин 30 с" in primary
        assert page.text.count("<summary>Технические детали</summary>") == 1
        assert "data-sleep-comparison" in primary
        assert "bias" in technical and "rmse" in technical
        assert "synthetic-exclusion" in technical
        assert 'href="/sleep?view=garmin' in primary and 'lang="en"' not in page.text
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
    detail = agreement_detail_fixture()
    monkeypatch.setattr(SleepAgreementReportService, "report", lambda *a, **kw: packet)
    monkeypatch.setattr(SleepAgreementReportService, "night_detail", lambda *a, **kw: detail)
    with client_for(app) as client:
        page = client.get("/agreement")
        assert page.status_code == 200
        assert 'data-owner-state="insufficient"' in page.text
        assert "Статистика пока недоступна" in page.text
        assert "осталось пригодных пар: 13" in page.text
        assert "Принятая исследовательская статистика" not in page.text


def test_nightly_history_aligns_fields_without_pooling_or_duplicate_dates():
    from healthcheck.web.sleep_view import nightly_rows

    def point(day, value, status="usable"):
        return {"analytic_date": day, "value": value, "status": status}

    rows = nightly_rows({
        "sleep_duration_seconds": {"points": [
            point("2099-01-02", 28800), point("2099-01-01", 0),
            point("2098-12-31", 60), point("2098-12-31", 120),
        ]},
        "sleep_score": {"points": [point("2099-01-02", 82, "partial")]},
    })
    assert [row["wake_date"] for row in rows] == ["2099-01-02", "2099-01-01", "2098-12-31"]
    assert rows[0]["metrics"]["sleep_score"]["state"] == "partial"
    assert rows[1]["metrics"]["sleep_duration_seconds"]["value"] == 0
    assert rows[1]["metrics"]["sleep_score"]["value"] is None
    assert rows[2]["metrics"]["sleep_duration_seconds"]["ambiguous"]


def test_comparison_source_switch_keeps_date_and_independent_panels(tmp_path):
    from test_google_daily_vitals import seed_google_daily_vitals

    app, _settings, paths = _ui(tmp_path)
    seed_sleep(paths)
    seed_google_daily_vitals(paths)
    with client_for(app) as client:
        garmin = client.get("/sleep?wake_date=2099-01-02&vitals_window=7").text
        google = client.get("/sleep?view=google&wake_date=2099-01-02&vitals_window=7").text
        compare = client.get("/sleep?view=compare&wake_date=2099-01-02").text
        assert "data-google-vitals" not in garmin
        assert "sleep-night-table" not in google
        assert 'view=google&amp;wake_date=2099-01-02&amp;vitals_window=7' in garmin
        assert "42.5 мс" in google
        assert "Нет доступного сохранённого сравнения" in compare
        assert "общий график недоступен" in compare
        assert 'data-sleep-comparison="' not in compare
        assert compare.count("<summary>Технические детали</summary>") == 1
        assert client.get("/sleep?view=invalid").status_code == 200
        assert client.get("/sleep?wake_date=0001-02-01&vitals_window=90").status_code == 400


@pytest.mark.parametrize("failure", [
    "unit", "eligible", "immutable", "unknown_source", "unknown_variant", "unknown_metric",
    "different_date", "different_cohort", "unaccepted_difference", "not_comparable",
    "daily_vs_sleep", "nonfinite", "duplicate_date", "account_cohort",
])
def test_comparison_overlay_fails_closed_for_incompatible_evidence(failure):
    from healthcheck.web.sleep_comparison import comparison_charts

    group = agreement_fixture()["groups"][0]
    detail = agreement_detail_fixture()
    detail["nights"] = detail["nights"][:1]
    before = copy.deepcopy(detail)
    assert len(comparison_charts(group, detail)) == 1
    side = detail["nights"][0]["metrics"][0]["google"]
    metric = detail["nights"][0]["metrics"][0]
    if failure == "unit":
        side["unit"] = "min"
    elif failure in {"eligible", "immutable"}:
        (side if failure == "eligible" else side["evidence"])[failure] = False
    elif failure == "unknown_source":
        side["evidence"]["source_id"] = None
    elif failure == "unknown_variant":
        group["variant"] = None
    elif failure == "unknown_metric":
        group["metric_code"] = "sleep_score"
    elif failure == "different_date":
        detail["nights"][0]["wake_date"] = "2098-01-01"
    elif failure == "different_cohort":
        detail["nights"][0]["cohort"] = "device_pair"
    elif failure == "unaccepted_difference":
        metric["difference"] = 999
    elif failure == "not_comparable":
        metric["status"] = "unavailable"
    elif failure == "daily_vs_sleep":
        metric["variant"] = "DAILY"
    elif failure == "nonfinite":
        side["value"] = float("inf")
    elif failure == "duplicate_date":
        detail["nights"].append(copy.deepcopy(detail["nights"][0]))
    elif failure == "account_cohort":
        group["cohort"] = "account_wearables_sleep_observations"
    assert comparison_charts(group, detail) == []
    # No display adapter ever edits accepted side values.
    assert before["nights"][0]["metrics"][0]["google"]["value"] == 28920


def test_comparison_charts_keep_sources_bases_variants_and_missing_dates_separate():
    from healthcheck.web.sleep_comparison import comparison_charts

    group = agreement_fixture()["groups"][0]
    detail = agreement_detail_fixture()
    before = copy.deepcopy(detail)
    charts = comparison_charts(group, detail)
    assert len(charts) == 1 and len(charts[0]["points"]) == 14
    assert charts[0]["points"][0]["garmin"] == 28800
    assert charts[0]["points"][0]["google_text"] == "8 ч 2 мин"
    assert detail == before
    detail["nights"][0]["metrics"][0]["google"]["evidence"]["source_id"] = "other-device"
    detail["nights"][1]["metrics"][0]["google"]["comparison_basis"] = "summary_only"
    detail["nights"][2]["metrics"][0]["variant"] = "CLASSIC"
    charts = comparison_charts(group, detail)
    assert sorted(len(chart["points"]) for chart in charts) == [1, 1, 11]
    assert all("2099-01-03" not in [p["wake_date"] for p in c["points"]] for c in charts)


def test_comparison_read_preserves_window_packet_and_performs_no_writes(tmp_path, monkeypatch):
    from healthcheck.analytics.sleep_agreement_report import SleepAgreementReportService

    app, _settings, paths = _ui(tmp_path)
    app.state.engine = create_sqlite_engine(paths)
    frozen = agreement_service_fixture()
    seen = []
    packet = frozen.report(
        run_id="run-1", start_date=date(2098, 12, 6), end_date=date(2099, 1, 4)
    )
    before = copy.deepcopy(packet)
    detail = frozen.night_detail("run-1")
    detail_before = copy.deepcopy(detail)

    def report(*args, **kwargs):
        seen.append(kwargs)
        return packet

    monkeypatch.setattr(SleepAgreementReportService, "report", report)
    monkeypatch.setattr(SleepAgreementReportService, "night_detail", lambda *a, **kw: detail)
    statements = []
    with client_for(app) as client:
        event.listen(app.state.engine, "before_cursor_execute",
                     lambda _c, _cur, sql, *_a: statements.append(sql))
        page = client.get("/sleep?view=compare&wake_date=2099-01-04")
        assert page.status_code == 200
        assert seen == [{"start_date": date(2098, 12, 6), "end_date": date(2099, 1, 4)}]
        primary = page.text.split('<details class="card owner-details sleep-technical"')[0]
        assert "2099-01-05" not in primary
        assert "Статистика пока недоступна" in primary
        assert client.get("/api/agreement/report").json() == packet
    assert packet == before and detail == detail_before
    assert "BEGIN" in statements
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                   for sql in statements)


@pytest.mark.parametrize("code,unit", [("resting_heart_rate_bpm", "bpm"),
                                      ("spo2_daily_average_pct", "%")])
def test_daily_comparisons_require_their_own_same_date_record_basis(code, unit):
    from healthcheck.web.sleep_comparison import comparison_charts

    group = agreement_fixture()["groups"][0]
    detail = agreement_detail_fixture()
    detail["nights"] = detail["nights"][:1]
    group.update(metric_code=code, variant="DAILY")
    metric = detail["nights"][0]["metrics"][0]
    metric.update(metric_code=code, variant="DAILY",
                  difference_unit="bpm" if unit == "bpm" else "percentage_points")
    for provider in ("garmin", "google"):
        metric[provider].update(unit=unit, value=0, comparison_basis="own_daily_record")
    charts = comparison_charts(group, detail)
    assert len(charts) == 1
    assert charts[0]["points"][0]["google"] == 0
    metric["google"]["comparison_basis"] = "sleep_summary"
    assert comparison_charts(group, detail) == []


def test_owner_comparison_formatting_rounds_display_only():
    from healthcheck.web.sleep_comparison import comparison_value

    assert comparison_value(-3661.125, "seconds", signed=True) == "−1 ч 1 мин 1 с"
    assert comparison_value(0, "seconds") == "0 с"
    assert comparison_value(1.23456, "bpm") == "1.2 уд/мин"
    assert comparison_value(0.23456, "percentage_points") == "0.2 п.п."
    assert comparison_value(1, None) == "—"
