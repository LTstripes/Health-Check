"""Synthetic route/template coverage for the #127 Period Brief page."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from healthcheck.config import Settings
from healthcheck.db.engine import migrate_database
from healthcheck.runtime import prepare_runtime
from healthcheck.web.ui_app import create_ui_app


def _ui(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ui_app(settings)
    return app


def test_period_brief_page_defaults_to_bounded_local_period_and_exposes_nav(tmp_path):
    app = _ui(tmp_path)
    end = date.today()
    start = end - timedelta(days=29)

    with TestClient(app) as client:
        page = client.get("/brief")
        home = client.get("/")

    assert page.status_code == 200
    assert "Сводка за период" in page.text
    assert f"{start.isoformat()} → {end.isoformat()}" in page.text
    assert 'href="/brief"' in home.text
    assert "Источник Garmin" in page.text
    assert "За выбранный период нет доступных данных" in page.text
    assert "Данных за период для сводки пока нет" in page.text
    assert 'name="garmin_source_id" value=""' in page.text
    primary = page.text.split("Технические детали", 1)[0]
    assert "weight_rate_kg_per_week" not in primary
    assert "sleep_agreement_mode" not in primary
    assert "activity_comparison_state" not in primary
    assert "weight_rate_kg_per_week" in page.text
    assert "period-brief-v1" in page.text
    assert "Traceback" not in page.text
    assert "SELECT " not in page.text
    assert "password" not in page.text.lower()


@pytest.mark.parametrize(
    ("state", "label"),
    [
        ("present", "Данные доступны"),
        ("confirmed_empty", "За период записей нет"),
        ("unknown", "Состояние данных не определено"),
        ("unavailable", "Источник данных недоступен"),
        ("insufficient", "Недостаточно данных"),
        ("not_requested", "Не запрашивалось"),
    ],
)
def test_period_brief_owner_state_labels_remain_distinct(state, label):
    from healthcheck.web.pages import _brief_owner_state

    assert _brief_owner_state(state) == label


def test_period_brief_page_supports_presets_and_custom_period(tmp_path):
    app = _ui(tmp_path)
    with TestClient(app) as client:
        for days in (7, 30, 90):
            end = date.today()
            start = end - timedelta(days=days - 1)
            response = client.get("/brief", params={"preset": str(days)})
            assert response.status_code == 200
            assert f"{start.isoformat()} → {end.isoformat()}" in response.text
            assert f'name="start_date" value="{start.isoformat()}"' in response.text
            assert f'name="end_date" value="{end.isoformat()}"' in response.text

        custom = client.get(
            "/brief",
            params={"start_date": "2099-02-03", "end_date": "2099-02-17"},
        )

    assert custom.status_code == 200
    assert "2099-02-03 → 2099-02-17" in custom.text
    assert "15 days" in custom.text


def test_period_brief_page_rejects_invalid_period_controls(tmp_path):
    app = _ui(tmp_path)
    with TestClient(app) as client:
        bad_preset = client.get("/brief", params={"preset": "14"})
        bad_date = client.get(
            "/brief", params={"start_date": "not-a-date", "end_date": "2099-01-01"}
        )
        reversed_period = client.get(
            "/brief", params={"start_date": "2099-02-01", "end_date": "2099-01-01"}
        )

    for response in (bad_preset, bad_date, reversed_period):
        assert response.status_code == 400
        assert "invalid_period" in response.text
        assert "request failed" not in response.text


def test_period_brief_source_label_is_human_and_identity_free():
    from healthcheck.web.pages import _brief_source_label

    source = {
        "id": "source-uuid-1234",
        "provider_code": "garmin_connect",
        "source_instance_id": "account-instance-uuid",
        "device_attributed": True,
        "device_model": "Vivoactive 5",
    }
    label = _brief_source_label(source)
    assert label == "Garmin Connect · Vivoactive 5"
    assert "source-uuid-1234" not in label
    assert "account-instance-uuid" not in label
    assert _brief_source_label({"provider_code": "garmin_connect"}) == "Garmin Connect"


def test_period_brief_sleep_warning_is_collapsed_to_one_notice():
    from healthcheck.web.pages import _brief_sleep_uncertainty

    groups = [
        {"exploratory_label_required": True, "metric_code": "duration"},
        {"exploratory_label_required": True, "metric_code": "score"},
    ]
    notice = _brief_sleep_uncertainty(groups)
    assert notice is not None
    assert "не сравнение Garmin и Fitbit/устройств" in notice
    assert _brief_sleep_uncertainty([{"exploratory_label_required": False}]) is None


def test_period_brief_notable_changes_are_deduplicated_and_prioritized():
    from healthcheck.web.pages import _brief_notable_changes

    notes = [
        {"section": "sleep", "code": "uncertain_account_cohort", "cohort": "account"},
        {"section": "sleep", "code": "uncertain_account_cohort", "cohort": "account"},
        {"section": "weight", "code": "weight_rate"},
        {"section": "baselines", "code": "personal_baseline_deviation", "fact_code": "sleep"},
    ]
    result = _brief_notable_changes(notes)
    assert [item["code"] for item in result] == [
        "personal_baseline_deviation",
        "weight_rate",
        "uncertain_account_cohort",
    ]
