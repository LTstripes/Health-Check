"""Synthetic route/template coverage for the #127 Period Brief page."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from healthcheck.config import Settings
from healthcheck.db.engine import (
    create_session_factory,
    create_sqlite_engine,
    migrate_database,
)
from healthcheck.db.models import GarminSource
from healthcheck.garmin.normalization import normalize_garmin_payload
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.runtime import prepare_runtime
from healthcheck.web.ui_app import create_ui_app
from test_garmin_query_dashboard import _activity_payload


class _VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)


def _visible_text(html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html)
    return " ".join(parser.parts)


def _ui(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ui_app(settings)
    return app


def _ui_with_garmin_source(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    try:
        with create_session_factory(engine)() as session:
            payload = _activity_payload(activity_id="brief-ui-activity")
            outcome = GarminPersistenceRepository(
                session,
                payload_store=ContentAddressedGarminPayloadStore(paths.root / "artifacts"),
            ).persist_result(
                normalize_garmin_payload(payload),
                payload=payload,
                received_at=datetime(2099, 1, 1, 12, tzinfo=UTC),
                source_contract_version=payload["fixture_contract_version"],
            )
            session.commit()
            source_id = outcome.records[0].garmin_source_id
            source_instance_id = session.get(GarminSource, source_id).source_instance_id
    finally:
        engine.dispose()
    app, _ = create_ui_app(settings)
    return app, source_id, source_instance_id


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


def test_period_brief_rendered_source_hides_identity_until_technical_details(tmp_path):
    app, source_id, source_instance_id = _ui_with_garmin_source(tmp_path)
    with TestClient(app) as client:
        page = client.get(
            "/brief",
            params={
                "start_date": "2099-01-01",
                "end_date": "2099-01-02",
                "garmin_source_id": source_id,
            },
        )

    assert page.status_code == 200
    primary = _visible_text(page.text.split("Технические детали", 1)[0])
    technical = _visible_text(page.text.split("Технические детали", 1)[1])
    assert "Garmin Connect · Vivoactive 5" in primary
    assert source_id not in primary
    assert source_instance_id not in primary
    assert source_id in technical
    assert source_instance_id in technical


def test_period_brief_rendered_summary_deduplicates_warning_and_notables(
    tmp_path, monkeypatch
):
    class FakeGarmin:
        @staticmethod
        def resolve_source(_source_id):
            return {
                "status": "no_data",
                "reason": "no_garmin_sources",
                "selected_source_id": None,
                "sources": [],
            }

    sections = {
        "weight": {
            "state": "present",
            "summary_facts": [],
            "display_points": [],
        },
        "sleep": {
            "state": "present",
            "groups": [
                {
                    "cohort_label": (
                        "Uncertain Garmin account / Google source or family observations"
                    ),
                    "exploratory_label_required": True,
                    "n": 3,
                    "paired_nights": 3,
                    "statistics_available": False,
                },
                {
                    "cohort_label": (
                        "Uncertain Garmin account / Google source or family observations"
                    ),
                    "exploratory_label_required": True,
                    "n": 3,
                    "paired_nights": 3,
                    "statistics_available": False,
                },
            ],
            "summary_facts": [],
            "coverage": {"source_data_quality": []},
        },
        "activity": {
            "state": "confirmed_empty",
            "summary_facts": [],
            "sessions": [],
        },
        "data_quality": {
            "state": "present",
            "summary_facts": [],
            "coverage": {
                "provider_states": [{"state": "unavailable"}],
                "weight_sparse_note": None,
            },
        },
    }
    display = {
        "period": {
            "start_date": "2099-01-01",
            "end_date": "2099-01-02",
            "calendar_days": 2,
        },
        "sections": sections,
        "notable_changes": [
            {"section": "sleep", "code": "uncertain_account_cohort"},
            {"section": "sleep", "code": "uncertain_account_cohort"},
            {"section": "baselines", "code": "personal_baseline_deviation"},
        ],
        "owner_actions": [],
        "source_result_hash": "synthetic-display-hash",
    }
    packet = {
        **display,
        "contract_version": "period-brief-v1",
        "algorithm": "period_brief_assemble_v1",
        "result_hash": "synthetic-result-hash",
        "contracts_referenced": {},
    }

    class FakeService:
        def __init__(self, *_args):
            self.garmin = FakeGarmin()

        def build_with_render(self, **_kwargs):
            return {"packet": packet, "display": display, "rendered_text": ""}

    monkeypatch.setattr("healthcheck.web.pages.PeriodBriefService", FakeService)
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ui_app(settings)
    with TestClient(app) as client:
        page = client.get("/brief", params={"start_date": "2099-01-01", "end_date": "2099-01-02"})

    assert page.status_code == 200
    assert page.text.count("исследовательская когорта с неопределённой атрибуцией") == 1
    assert page.text.count("Обнаружено отклонение от личной базовой линии Garmin.") == 1
    assert page.text.count("Есть исследовательские данные сна с неопределённой атрибуцией.") == 1
    assert page.text.index("Обнаружено отклонение") < page.text.index(
        "Есть исследовательские данные"
    )
    assert "Источник: Источник данных недоступен" in page.text


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
