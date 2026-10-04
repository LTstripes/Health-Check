"""Stage 4 Weight Owner-first surface: frozen Russian presentation, semantics unchanged."""

from __future__ import annotations

from fastapi.testclient import TestClient

from healthcheck.config import Settings
from healthcheck.db.engine import migrate_database
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.ingestion.photo.synthetic import six_month_synthetic_batch
from healthcheck.runtime import prepare_runtime
from healthcheck.web.ui_app import create_ui_app


def _ui(tmp_path, **settings_values):
    settings = Settings(data_dir=tmp_path / "runtime", **settings_values)
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())
    return app


def _upload_batch(client, batch=None):
    items = batch if batch is not None else six_month_synthetic_batch()
    return client.post(
        "/api/imports/photos",
        files=[("files", (name, content, "image/png")) for name, content, _payload in items],
    )


def _confirm_all_pending(client, batch_id):
    detail = client.get(f"/api/imports/{batch_id}")
    assert detail.status_code == 200
    pending = [
        item["id"]
        for item in detail.json()["candidates"]
        if item["user_decision"] == "pending"
    ]
    if not pending:
        return []
    confirmed = client.post("/api/import-candidates/confirm", json={"candidate_ids": pending})
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()["confirmed"]


def test_weight_owner_state_mapping_keeps_missing_and_insufficient_distinct():
    from healthcheck.web.pages import _weight_owner_state

    assert _weight_owner_state(True, None) == "present"
    assert _weight_owner_state(False, "insufficient_observations") == "insufficient"
    assert _weight_owner_state(False, "insufficient_span") == "insufficient"
    assert _weight_owner_state(False, "insufficient_gap") == "insufficient"
    assert _weight_owner_state(False, "no_data") == "unavailable"
    assert _weight_owner_state(False, "missing_session") == "unavailable"
    assert _weight_owner_state(False, "database_unavailable") == "unavailable"
    assert _weight_owner_state(False, "future_reason") == "unavailable"
    assert _weight_owner_state(False, None) == "unknown"
    assert _weight_owner_state(False, "") == "unknown"


def test_weight_owner_reason_is_russian_and_keeps_exact_codes_behind():
    from healthcheck.web.pages import _weight_owner_reason

    assert "Нет подтверждённых измерений" in _weight_owner_reason("no_data")
    assert "Недостаточно измерений" in _weight_owner_reason("insufficient_observations")
    assert "Нет принятого расчёта" in _weight_owner_reason("no_canonical_run")
    assert "Локальное хранилище" in _weight_owner_reason("database_unavailable")
    expected_fallback = "Подробности доступны в технических данных."
    assert _weight_owner_reason("future_unknown_reason") == expected_fallback
    # Exact codes are not translated away: caller keeps them for technical disclosure.
    assert _weight_owner_reason("no_data") != "no_data"


def test_weight_page_is_russian_owner_first_with_technical_disclosure(tmp_path):
    app = _ui(tmp_path, weight_goal_kg=76.0)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        _confirm_all_pending(client, _upload_batch(client).json()["id"])
        page = client.get("/")
        assert page.status_code == 200
        html = page.text
        # Owner-first Russian primary surface.
        for snippet in (
            "Текущий подтверждённый вес",
            "Текущий вес и цель",
            "Ряд веса",
            "Подтверждённый вес (источник)",
            "Тренд 21 день (расчёт Health-Check)",
            "Настроенная цель",
            "Изменение за последнее время",
            "Покрытие и свежесть",
            "Последний состав тела",
            "Изменения при похожем весе",
            "Состав тела по группам алгоритмов",
            "Происхождение точек",
            "Выбери точку на графике",
            "Проверить состояние источников",
            "Технические детали",
        ):
            assert snippet in html
        # Interpretation-changing limitations stay visible in Russian.
        assert "Потребительский биоимпеданс" in html
        assert "не ставит диагнозы" in html
        # Exact mechanics/reasons stay behind closed disclosure, not primary.
        assert '<details class="card owner-details' in html
        assert 'class="card owner-details" open' not in html
        primary, technical = html.split("Технические детали", 1)
        assert "weight_trend_taewma_v1" not in primary
        assert "weight_rate_theil_sen_90d_v1" not in primary
        assert "no_data" not in primary or 'data-owner-state' in primary  # only via chip metadata
        assert "weight_trend_taewma_v1" in technical
        assert "canonical" in technical.lower() or "Канонический" in technical
        # Import needs link toward Data, not duplicated source-status UX.
        assert 'href="/imports' in primary
        assert "на проверке" in primary or "Открыть данные" in primary
        # Missing is never zero in primary (exact zero, not goal substring like 76.0).
        assert " 0 кг" not in primary
        assert ">0 кг" not in primary
        # API semantics unchanged.
        series = client.get("/api/weight/series").json()
        assert series["trend_algorithm"] == "weight_trend_taewma_v1"
        assert series["metric_labels"]["raw_weight"] == "Raw confirmed weight (source)"
        assert series["bia_uncertainty"].startswith("Consumer bioimpedance")


def test_weight_empty_states_use_frozen_chips_and_no_zero(tmp_path):
    app = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        html = client.get("/").text
        primary = html.split("Технические детали", 1)[0]
        assert 'data-owner-state="unavailable"' in primary
        assert "Это не означает ноль" in primary
        assert "Нет подтверждённых измерений" in primary
        assert "Не настроена" in primary
        assert "Нет кандидатов на проверке" in primary
        assert "0 кг" not in primary
        assert "<dd>0</dd>" not in primary


def test_weight_browser_contract_uses_frozen_surfaces(tmp_path):
    app = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        html = client.get("/").text
        js = client.get("/static/dashboard.js").text
        css = client.get("/static/dashboard.css").text
        # Viewport, skip link, focus, chart scroller present.
        assert 'name="viewport"' in html
        assert 'href="#owner-main"' in html
        assert 'id="weight-chart" class="chart"' in html
        assert 'aria-label="График веса"' in html
        assert 'id="trend-status"' in html
        # Legend uses frozen 8px squares (CSS) and Russian labels (HTML).
        assert "Подтверждённый вес (источник)" in html
        assert ".swatch" in css and "width: 8px" in css
        # Tables keep real layout inside dedicated scroller (JS creates wrapper).
        assert "table-scroll" in js
        assert 'aria-label", "Состав тела' in js or "Состав тела, прокрутка таблицы" in js
        assert 'createElement("table")' in js
        assert "display: block" not in js
        # Frozen series colors reused, no page-local palette.
        assert "#1d4e89" in js
        assert "#9a4f1a" in js
        assert "#5c4d86" in js
        assert "#c45c26" not in js
        assert "#6b4ea2" not in js
        # Owner-facing JS copy is Russian; exact reason codes stay in JSON only.
        assert "Тренд доступен" in js or "Тренд недоступен" in js
        assert "кг/нед." in js
        assert "Покрытие" not in js or "Даты наблюдений" in js
        assert "Trend algorithm" not in js
        assert "kg/week" not in js
        # No new visual tokens introduced by Stage 4.
        assert "border-radius: 999px" not in css
        assert "font-weight: 700" not in css
