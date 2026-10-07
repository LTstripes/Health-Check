"""Synthetic route/template coverage for the #127 Period Brief page."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from tempfile import TemporaryDirectory

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
from healthcheck.web.owner_presentation import owner_date
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
        # Keep the artifact root short: the verification helper deliberately
        # nests pytest temp paths, and Windows path limits are not product scope.
        with TemporaryDirectory(prefix="issue133-artifacts-", dir=".") as artifact_dir:
            with create_session_factory(engine)() as session:
                payload = _activity_payload(activity_id="brief-ui-activity")
                outcome = GarminPersistenceRepository(
                    session,
                    payload_store=ContentAddressedGarminPayloadStore(artifact_dir),
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

    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        page = client.get("/brief")
        home = client.get("/")

    assert page.status_code == 200
    assert "Обзор за период" in page.text
    assert f"{owner_date(start)} → {owner_date(end)}" in page.text
    assert 'href="/brief"' in home.text
    assert "Источник Garmin не сохранён" in page.text
    assert '<select name="garmin_source_id">' not in page.text
    assert 'id="brief-notable-heading"' not in page.text
    assert 'class="owner-page-mode"' not in page.text
    assert "За выбранный период нет доступных данных" in page.text
    assert "Данных за период для сводки пока нет" in page.text
    assert 'name="garmin_source_id" value=""' in page.text
    primary = page.text.split("Технические детали", 1)[0]
    assert "weight_rate_kg_per_week" not in primary
    assert "sleep_agreement_mode" not in primary
    assert "activity_comparison_state" not in primary
    assert "weight_rate_kg_per_week" in page.text
    assert "period-brief-v2" in page.text
    assert "Traceback" not in page.text
    assert "SELECT " not in page.text
    assert "password" not in page.text.lower()


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
    assert (
        _brief_source_label({"provider_code": "garmin_connect", "device_model": "Vivoactive 5"})
        == "Garmin Connect"
    )
    assert (
        _brief_source_label(
            {
                "provider_code": "garmin_connect",
                "device_attributed": False,
                "device_model": "Vivoactive 5",
            }
        )
        == "Garmin Connect"
    )


def test_period_brief_rendered_source_hides_identity_until_technical_details(tmp_path):
    app, source_id, source_instance_id = _ui_with_garmin_source(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        page = client.get(
            "/brief",
            params={
                "start_date": "2099-01-01",
                "end_date": "2099-01-02",
                "garmin_source_id": source_id,
            },
        )

    assert page.status_code == 200
    assert '<select name="garmin_source_id">' not in page.text
    primary = _visible_text(page.text.split("Технические детали", 1)[0])
    technical = _visible_text(page.text.split("Технические детали", 1)[1])
    assert "Garmin Connect · Vivoactive 5" in primary
    assert source_id not in primary
    assert source_instance_id not in primary
    assert source_id in technical
    assert source_instance_id in technical


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
        {"section": "weight", "code": "weight_rate", "value": 0},
        {"section": "weight", "code": "weight_trend"},
        {"section": "activity", "code": "activity_comparison"},
        {"section": "baselines", "code": "personal_baseline_deviation", "fact_code": "sleep"},
    ]
    result = _brief_notable_changes(notes)
    assert [item["code"] for item in result] == [
        "personal_baseline_deviation",
        "weight_rate",
    ]


def test_period_brief_rendered_summary_deduplicates_warning_and_notables(tmp_path, monkeypatch):
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
        "weight": {"state": "present", "summary_facts": [], "display_points": []},
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
        "activity": {"state": "confirmed_empty", "summary_facts": [], "sessions": []},
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
        "period": {"start_date": "2099-01-01", "end_date": "2099-01-02", "calendar_days": 2},
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
        "contract_version": "period-brief-v2",
        "algorithm": "period_brief_assemble_v2",
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
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        page = client.get("/brief", params={"start_date": "2099-01-01", "end_date": "2099-01-02"})

    assert page.status_code == 200
    assert page.text.count("Принадлежность устройству и роль записи сна могут быть неизвестны") == 1
    assert page.text.count("Обнаружено отклонение от личной базовой линии Garmin.") == 1
    assert "Есть исследовательские данные сна с неопределённой атрибуцией." not in page.text
    assert "Источник: Источник данных недоступен" in page.text


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
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
        for days in (7, 30, 90):
            end = date.today()
            start = end - timedelta(days=days - 1)
            response = client.get("/brief", params={"preset": str(days)})
            assert response.status_code == 200
            assert f"{owner_date(start)} → {owner_date(end)}" in response.text
            assert f'name="start_date" value="{start.isoformat()}"' in response.text
            assert f'name="end_date" value="{end.isoformat()}"' in response.text

        custom = client.get(
            "/brief",
            params={"start_date": "2099-02-03", "end_date": "2099-02-17"},
        )

    assert custom.status_code == 200
    assert "3 февраля 2099 → 17 февраля 2099" in custom.text
    assert "15 дней" in custom.text


def test_period_brief_page_rejects_invalid_period_controls(tmp_path):
    app = _ui(tmp_path)
    with TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    ) as client:
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


def _stage3_result():
    """Private-safe presentation fixture; all rows remain separate packet observations."""
    from copy import deepcopy

    uncertain = "Uncertain Garmin account / Google source or family observations"
    groups = []
    for code, variant, bias, mae, n in [
        ("sleep_duration_asleep_seconds", "STAGES", -120, 180, 7),
        ("sleep_duration_asleep_seconds", "CLASSIC", 0, 90, 8),
        ("sleep_stage_deep_seconds", "STAGES", 30, 50, 9),
        ("resting_heart_rate_bpm", "DAILY", -2, 3, 10),
        ("spo2_daily_average_pct", "DAILY", 0.5, 1.5, 11),
        ("future_metric", "NEW", 999, 999, None),
    ]:
        groups.append(
            {
                "run_id": f"synthetic-run-{len(groups)}",
                "cohort_label": uncertain,
                "cohort": "account_wearables_sleep_observations_v1",
                "metric_code": code,
                "variant": variant,
                "exploratory_label_required": True,
                "n": n,
                "paired_nights": 12,
                "statistics_available": True,
                "bias": bias,
                "mae": mae,
                "accepted_statistics_n": n,
                "progress": {"gate": {"reason_codes": ["uncertain_attribution"]}},
            }
        )
    groups.append(
        {
            **groups[0],
            "run_id": "synthetic-missing",
            "n": 3,
            "statistics_available": False,
            "bias": None,
            "mae": None,
            "accepted_statistics_n": None,
        }
    )
    actions = [{"code": "confirm_pending_imports", "pending_candidate_count": 2}]
    for scope, reason, state in [
        ("garmin:sleep", "refresh_overdue", "stale"),
        ("garmin:heart_rate", "expected_evidence_absent", "unknown"),
        ("garmin:sleep", "refresh_overdue", "stale"),
        ("garmin:daily_summary", "reauth_required", "unavailable"),
        ("google:sleep", "refresh_overdue", "stale"),
    ]:
        actions.append(
            {
                "code": "source_freshness_attention",
                "scope_key": scope,
                "reason_code": reason,
                "state": state,
            }
        )
    sections = {
        "weight": {
            "state": "insufficient",
            "summary_facts": [
                {
                    "code": "weight_observation_count",
                    "value": 2,
                    "unit": "count",
                    "availability": "present",
                },
                {
                    "code": "weight_rate_kg_per_week",
                    "value": None,
                    "unit": "kg/week",
                    "availability": "insufficient",
                },
                {
                    "code": "weight_last_daily_median_kg",
                    "value": 65,
                    "unit": "kg",
                    "availability": "present",
                },
            ],
            "display_points": [{"observed_date": "2099-01-01", "median_kg": 65}],
        },
        "sleep": {
            "state": "present",
            "groups": groups,
            "summary_facts": [
                {"code": "sleep_agreement_mode", "value": "published", "availability": "present"},
            ],
        },
        "activity": {
            "state": "confirmed_empty",
            "summary_facts": [
                {
                    "code": "activity_session_count",
                    "value": 0,
                    "unit": "count",
                    "availability": "confirmed_empty",
                },
            ],
            "sessions": [],
        },
        "data_quality": {
            "state": "present",
            "summary_facts": [],
            "coverage": {
                "provider_states": [{"provider_code": "google", "state": "unknown"}],
                "weight_sparse_note": "Synthetic technical sparse sampling note",
            },
        },
    }
    packet = {
        "period": {"start_date": "2099-01-01", "end_date": "2099-01-07", "calendar_days": 7},
        "sections": sections,
        "notable_changes": [],
        "owner_actions": actions,
        "contract_version": "period-brief-v2",
        "algorithm": "period_brief_assemble_v2",
        "result_hash": "synthetic-result-hash",
        "contracts_referenced": {},
    }
    display = deepcopy(packet)
    display["source_result_hash"] = display.pop("result_hash")
    return {"packet": packet, "display": display, "rendered_text": ""}


def _stub_brief_service(monkeypatch, result, source_selection=None):
    class FakeGarmin:
        @staticmethod
        def resolve_source(_source_id):
            return source_selection or {
                "status": "no_data",
                "selected_source_id": None,
                "sources": [],
            }

    class FakeService:
        def __init__(self, *_args):
            self.garmin = FakeGarmin()

        def build_with_render(self, **_kwargs):
            return result

    monkeypatch.setattr("healthcheck.web.pages.PeriodBriefService", FakeService)


def test_stage3_owner_presentation_keeps_packet_and_all_distinct_sleep_rows(tmp_path, monkeypatch):
    from copy import deepcopy

    result = _stage3_result()
    before = deepcopy(result)
    _stub_brief_service(monkeypatch, result)
    with TestClient(_ui(tmp_path), base_url="http://127.0.0.1:8120") as client:
        page = client.get("/brief?start_date=2099-01-01&end_date=2099-01-07")
    assert page.status_code == 200
    assert result == before
    primary, technical = page.text.split("Технические детали", 1)
    text = _visible_text(primary)
    assert "Уверенность и покрытие" not in text
    assert "Полнота данных" not in text
    assert "sleep_agreement_mode" not in primary
    assert "Synthetic technical sparse" not in primary
    for label in [
        "Длительность и время",
        "Стадии сна",
        "Сопутствующие показатели за день",
        "Со стадиями сна",
        "Без стадий сна",
        "Google минус Garmin",
        "п.п.",
        "уд/мин",
    ]:
        assert label in text
    assert primary.count('class="brief-comparison"') == 7
    assert "-120 с" in text and "0 с" in text and "180 с" in text
    assert "999" not in text  # unknown units are not guessed
    assert "Пригодных наблюдений: —" in text
    assert "Принятое сравнение недоступно" in text
    assert "не оценка точности" in text
    assert "0 шт." in text  # explicit confirmed-empty count survives
    assert "Недостаточно данных" in text
    assert "Свежесть неизвестна" in text and "Данные недоступны" in text
    assert "Полнота данных и происхождение" in technical
    assert "synthetic-run-0" not in primary and "synthetic-run-0" in technical
    assert "future_metric" in technical and "999" in technical
    assert "synthetic-result-hash" in technical
    assert "source_freshness_attention" not in primary
    assert technical.count('"source_freshness_attention"') == 5
    assert 'class="card owner-details brief-provenance" open' not in page.text


def test_stage3_actions_group_same_work_but_keep_provider_and_distinct_remediation():
    from copy import deepcopy

    from healthcheck.web.pages import _brief_owner_actions

    actions = _stage3_result()["packet"]["owner_actions"]
    before = deepcopy(actions)
    rows = _brief_owner_actions(actions)
    assert actions == before
    assert len(rows) == 4  # confirmation, Garmin collection, Garmin login, Google collection
    assert rows[1]["contexts"] == ["Данные устарели", "Свежесть неизвестна"]
    assert "Garmin" in rows[1]["text"] and "Garmin" in rows[2]["text"]
    assert "Повторите вход" in rows[2]["text"]
    assert "Google" in rows[3]["text"]
    assert rows[0]["link"] == "/imports"
    assert all(row["link"].startswith("/imports") for row in rows)


def test_stage3_sleep_units_match_frozen_definitions_and_no_pooling():
    from healthcheck.analytics.sleep_metrics import get_sleep_metric_definition
    from healthcheck.web.pages import _brief_sleep_groups

    groups = _stage3_result()["packet"]["sections"]["sleep"]["groups"]
    rows = [row for bucket in _brief_sleep_groups(groups) for row in bucket["rows"]]
    assert len(rows) == len(groups)
    for group in groups:
        assert sum(row["group"] is group for row in rows) == 1
    for row in rows:
        code = row["group"]["metric_code"]
        assert row["unit"] == (
            None if code == "future_metric" else get_sleep_metric_definition(code).difference_unit
        )


def test_stage3_source_choice_opens_only_when_needed_and_escapes_untrusted_text(
    tmp_path, monkeypatch
):
    result = _stage3_result()
    result["packet"]["sections"]["sleep"]["groups"][0]["run_id"] = "<img src=x onerror=alert(1)>"
    selection = {
        "status": "require_selection",
        "selected_source_id": None,
        "sources": [
            {
                "id": "synthetic-one",
                "provider_code": "garmin_connect",
                "device_attributed": True,
                "device_model": "<script>alert(1)</script>",
            },
            {"id": "synthetic-two", "provider_code": "garmin_connect"},
        ],
    }
    _stub_brief_service(monkeypatch, result, selection)
    with TestClient(_ui(tmp_path), base_url="http://127.0.0.1:8120") as client:
        page = client.get("/brief")
    assert 'class="owner-details brief-source" open' in page.text
    assert "данные не объединяются молча" in page.text
    assert "<script>alert(1)</script>" not in page.text
    assert "<img src=x" not in page.text
    assert "&lt;script&gt;" in page.text
    assert 'name="start_date" value="2099-01-01"' in page.text
    assert 'name="end_date" value="2099-01-07"' in page.text


def test_stage3_notable_comparisons_identify_metric_and_use_exact_fact_unit():
    from healthcheck.web.pages import _brief_note_value, _brief_owner_note

    note = {
        "code": "personal_baseline_deviation",
        "fact_code": "garmin_sleep_baseline_sleep_duration_seconds",
        "value": 18000,
    }
    brief = {
        "sections": {
            "sleep": {
                "summary_facts": [
                    {"code": note["fact_code"], "unit": "seconds", "value": 18000},
                ]
            }
        }
    }
    assert _brief_owner_note(note) == "Длительность сна: отклонение от личной базовой линии."
    assert _brief_note_value(note, brief) == "18000 с"
    assert "единицы доступны" in _brief_note_value(note, {"sections": {}})
    assert _brief_owner_note(
        {"code": "sleep_exploratory_agreement", "metric_code": "sleep_stage_deep_seconds"}
    ).startswith("Глубокий сон:")
    assert _brief_note_value({"value": None}, brief) == ""


def test_stage3_all_frozen_states_and_unknown_activity_copy_are_preserved():
    from healthcheck.web.pages import _brief_owner_activity, _brief_owner_state, templates

    for state, label in templates.get_template("owner_ui.html").module.state_labels.items():
        assert _brief_owner_state(state) == label
    assert _brief_owner_state("future_state") == "Состояние данных не определено"
    assert _brief_owner_activity("future_provider_activity") == "Другая активность"


def test_brief_usable_evidence_inspects_section_evidence_not_only_state():
    from healthcheck.web.pages import _brief_has_usable_evidence

    # Real weight points remain usable even if a conservative state says unknown.
    assert _brief_has_usable_evidence(
        {
            "sections": {
                "weight": {
                    "state": "unknown",
                    "display_points": [{"observed_date": "2099-01-01", "median_kg": 70.0}],
                },
                "sleep": {"state": "insufficient"},
                "activity": {"state": "unknown"},
            }
        }
    )
    # Primary persisted sleep nights count as usable section evidence.
    assert _brief_has_usable_evidence(
        {
            "sections": {
                "weight": {"state": "unknown"},
                "sleep": {
                    "state": "insufficient",
                    "coverage": {"primary": {"metrics": [{"usable_count": 2}]}},
                },
                "activity": {"state": "unknown"},
            }
        }
    )
    # No section evidence anywhere stays empty.
    assert not _brief_has_usable_evidence(
        {
            "sections": {
                "weight": {"state": "unknown"},
                "sleep": {"state": "insufficient", "coverage": {"primary": {"metrics": []}}},
                "activity": {"state": "unknown"},
            }
        }
    )
    # Confirmed-empty inventory remains an explicit usable answer.
    assert _brief_has_usable_evidence(
        {"sections": {"weight": {"state": "unknown"}, "activity": {"state": "confirmed_empty"}}}
    )


def test_brief_source_status_is_source_explicit():
    from healthcheck.web.pages import _brief_source_status

    brief = {
        "sections": {
            "data_quality": {
                "coverage": {
                    "freshness": {
                        "providers": {
                            "garmin": {"state": "fresh"},
                            "google": {"state": "unknown"},
                        }
                    }
                }
            }
        }
    }
    assert _brief_source_status(brief) == (
        "Garmin: Данные доступны · Google: Состояние данных не определено"
    )
    assert _brief_source_status({"sections": {}}) is None
    assert _brief_source_status({"sections": {"data_quality": {"coverage": {}}}}) is None


def test_brief_activity_tennis_label_and_unknown_fallback():
    from healthcheck.web.pages import _brief_owner_activity

    assert _brief_owner_activity("tennis") == "Теннис"
    assert _brief_owner_activity("future_provider_activity") == "Другая активность"


def test_overview_sleep_summarizes_primary_evidence_and_source_status(tmp_path, monkeypatch):
    from copy import deepcopy

    result = _stage3_result()
    display = result["display"]
    sleep = display["sections"]["sleep"]
    sleep["state"] = "present"
    sleep["summary_facts"] = [
        {
            "code": "sleep_primary_duration_seconds",
            "value": 27000,
            "unit": "seconds",
            "availability": "present",
            "observed_date": "2099-01-02",
            "reason": "insufficient_baseline",
        },
        {
            "code": "sleep_primary_nights_with_duration",
            "value": 14,
            "unit": "count",
            "availability": "present",
        },
        {
            "code": "sleep_primary_score",
            "value": 75,
            "unit": "points",
            "availability": "present",
        },
    ]
    display["sections"]["data_quality"]["coverage"]["freshness"] = {
        "providers": {"garmin": {"state": "fresh"}, "google": {"state": "stale"}}
    }
    packet = deepcopy(result["packet"])
    packet["sections"]["sleep"] = deepcopy(display["sections"]["sleep"])
    packet["sections"]["data_quality"] = deepcopy(display["sections"]["data_quality"])
    result["packet"] = packet
    _stub_brief_service(monkeypatch, result)

    with TestClient(_ui(tmp_path), base_url="http://127.0.0.1:8120") as client:
        page = client.get("/brief?start_date=2099-01-01&end_date=2099-01-07")

    assert page.status_code == 200
    primary, _technical = page.text.split("Технические детали", 1)
    assert 'href="/sleep"' in primary
    assert "Последняя длительность сна" in primary
    assert "7 ч 30 мин" in primary
    assert "Ночей с длительностью" in primary
    assert "Последняя оценка сна Garmin" in primary
    assert "Источники: Garmin: Данные доступны · Google: Данные доступны частично" in primary
    assert "За выбранный период нет доступных данных" not in primary
    assert 'class="card owner-details brief-sleep"' in primary
    assert 'class="card owner-details brief-sleep" open' not in primary
    assert "status-chip owner-state present" not in primary
    overview = primary.split('class="brief-overview-list"', 1)[1]
    sleep_card = overview.split('href="/sleep"', 1)[1].split("</li>", 1)[0]
    assert "2 января 2099" in sleep_card
    assert "Подробности доступны в технических данных" not in sleep_card


def seed_overview_v2(paths):
    """Source-explicit synthetic snapshots for route and browser checks."""
    from healthcheck.db.engine import session_scope
    from healthcheck.garmin.normalization import garmin_source_identity
    from test_google_daily_vitals import seed_google_daily_vitals

    seed_google_daily_vitals(paths)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            repository = GarminPersistenceRepository(session, payload_store=store)
            for stream, payload in [
                ("daily_health", {
                    "calendarDate": "2099-01-02", "restingHeartRate": 52,
                    "hrvSummary": {"weeklyAvg": 60.123456},
                }),
                ("intraday", {
                    "calendarDate": "2099-01-02", "averageSpO2": 98,
                    "avgStressLevel": 0, "bodyBattery": 65, "respirationRate": 14.123456,
                }),
                ("activity", {
                    "activityId": "overview-v2-activity", "calendarDate": "2099-01-02",
                    "activityType": {"typeKey": "cycling"}, "duration": 1200, "distance": 5000,
                }),
            ]:
                normalized = normalize_garmin_payload(
                    payload, stream=stream,
                    source_identity=garmin_source_identity(source_kind="provider"),
                )
                repository.persist_result(
                    normalized, payload=payload, received_at=datetime(2099, 1, 3, tzinfo=UTC),
                )
    finally:
        engine.dispose()


def test_overview_v2_real_read_is_source_explicit_bounded_and_read_only(tmp_path):
    from sqlalchemy import event

    from test_garmin_query_dashboard import _ui as create_fixture

    app, _settings, paths = create_fixture(tmp_path)
    seed_overview_v2(paths)
    statements = []
    app.state.engine = create_sqlite_engine(paths)
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        event.listen(
            app.state.engine, "before_cursor_execute",
            lambda _c, _cur, sql, *_a: statements.append(sql),
        )
        response = client.get("/brief?start_date=2099-01-01&end_date=2099-01-02")
        assert response.status_code == 200
        primary, technical = response.text.split('class="card owner-details brief-provenance"', 1)
        assert 'data-overview-vitals' in primary
        assert "52 уд/мин" in primary and "55 уд/мин" in primary
        assert "60.12 мс" in primary and "42.5 мс" in primary
        assert "98 %" in primary and "97 %" in primary and "96 %" in primary
        assert "14.12 вдохов/мин" in primary and "13.5 вдохов/мин" in primary
        assert "Google: явный ноль" in primary and "0 баллы" in primary
        assert "среднее за неделю" in primary and "за день" in primary
        assert "Снимок; суточное среднее не подтверждено" in primary
        assert "Google · Пульс в покое: нет текущих записей" in primary
        assert "Источник передал пустое значение" in primary
        assert "За выбранный период нет доступных данных" not in primary
        assert "r297-google-daily-vitals-read-v1" in technical
        assert "60.123456" in technical  # source precision retained
        outside = client.get("/brief?start_date=2099-01-04&end_date=2099-01-05")
        visible = outside.text.split('class="card owner-details brief-provenance"', 1)[0]
        assert "52 уд/мин" not in visible and "42.5 мс" not in visible
        assert "Garmin: нет записи этого показателя в выбранном периоде" in visible
        assert "Google · HRV: нет текущих записей в выбранном периоде" in visible
    assert "BEGIN" in statements
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                   for sql in statements)


def test_overview_v2_google_only_does_not_look_globally_empty(tmp_path):
    from test_garmin_query_dashboard import _ui as create_fixture
    from test_google_daily_vitals import seed_google_daily_vitals

    app, _settings, paths = create_fixture(tmp_path)
    seed_google_daily_vitals(paths)
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        page = client.get("/brief?start_date=2099-01-01&end_date=2099-01-02")
    assert page.status_code == 200
    primary = page.text.split('class="card owner-details brief-provenance"', 1)[0]
    assert "42.5 мс" in primary
    assert "Garmin: источник не сохранён" in primary
    assert "За выбранный период нет доступных данных" not in primary


def test_overview_v2_garmin_collisions_null_units_and_retirement_stay_honest(tmp_path):
    from sqlalchemy import select

    from healthcheck.db.engine import session_scope
    from healthcheck.db.models import GarminRecordMetric, GarminSourceRecord
    from healthcheck.web.overview_view import read_overview_values
    from test_garmin_query_dashboard import _ui as create_fixture

    _app, _settings, paths = create_fixture(tmp_path)
    seed_overview_v2(paths)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            source_id = session.scalar(select(GarminSource.id))
            rhr = session.scalar(select(GarminRecordMetric).where(
                GarminRecordMetric.metric_code == "resting_heart_rate_bpm"))
            record = session.get(GarminSourceRecord, rhr.record_id)
            rhr.state, rhr.value_number = "null", None
            hrv = session.scalar(select(GarminRecordMetric).where(
                GarminRecordMetric.metric_code == "hrv_weekly_average_ms"))
            hrv.unit = "seconds"
            result = read_overview_values(session, start=date(2099, 1, 1),
                                          end=date(2099, 1, 2), selected_id=source_id)
            assert result["garmin"]["resting_heart_rate_bpm"]["value"] is None
            assert "пустое" in result["garmin"]["resting_heart_rate_bpm"]["note"]
            assert result["garmin"]["hrv_weekly_average_ms"]["value"] is None
            rhr.state, rhr.value_number = "value", 52
            record.record_status = "invalid"
            session.flush()
            invalid = read_overview_values(session, start=date(2099, 1, 1),
                                           end=date(2099, 1, 2), selected_id=source_id)
            assert invalid["garmin"]["resting_heart_rate_bpm"]["state"] == "unavailable"
            assert invalid["garmin"]["resting_heart_rate_bpm"]["value"] is None
            assert "непригодна" in invalid["garmin"]["resting_heart_rate_bpm"]["note"]
            record.record_status = "partial"
            duplicate = GarminSourceRecord(**{
                column.name: getattr(record, column.name)
                for column in GarminSourceRecord.__table__.columns
                if column.name not in {"id", "idempotency_key"}
            }, idempotency_key=record.idempotency_key + "-collision")
            session.add(duplicate)
            session.flush()
            session.add(GarminRecordMetric(**{
                column.name: getattr(rhr, column.name)
                for column in GarminRecordMetric.__table__.columns
                if column.name not in {"id", "record_id", "state", "value_number"}
            }, record_id=duplicate.id, state="value", value_number=99))
            session.flush()
            collision = read_overview_values(session, start=date(2099, 1, 1),
                                             end=date(2099, 1, 2), selected_id=source_id)
            assert collision["garmin"]["resting_heart_rate_bpm"]["value"] is None
            assert "несколько снимков" in collision["garmin"]["resting_heart_rate_bpm"]["note"]
            duplicate.projection_status = "retired"
            duplicate.retired_at = datetime(2099, 1, 3, tzinfo=UTC)
            duplicate.retire_reason = "synthetic"
            record.projection_status = "retired"
            record.retired_at = datetime(2099, 1, 3, tzinfo=UTC)
            record.retire_reason = "synthetic"
            session.flush()
            result = read_overview_values(session, start=date(2099, 1, 1),
                                          end=date(2099, 1, 2), selected_id=source_id)
            assert result["garmin"]["resting_heart_rate_bpm"]["state"] == "unknown"
    finally:
        engine.dispose()


@pytest.mark.parametrize("value, expected", [(0, "0"), (0.126789, "0.13"), (-0.126789, "-0.13")])
def test_overview_v2_weight_rate_precision_only_changes_display(value, expected):
    from healthcheck.web.pages import _brief_note_value, _brief_owner_value

    assert _brief_owner_value(value, "kg/week", "present") == f"{expected} кг/нед."
    note = {"code": "weight_rate", "value": value, "unit": "kg/week"}
    assert _brief_note_value(note, {}) == f"{expected} кг/нед."
    assert note["value"] == value
