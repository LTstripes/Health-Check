"""Synthetic UI adapter regressions; reader semantics remain in their own tests."""

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from healthcheck.chat_evidence import EvidenceError
from healthcheck.combined_evidence import encode_combined_evidence, render_combined_evidence
from healthcheck.config import Settings
from healthcheck.db.engine import session_scope
from healthcheck.db.models import GarminSource
from healthcheck.web import analysis_export as ui
from healthcheck.web.ui_app import create_ui_app
from test_combined_evidence import profile as _combined_profile
from test_combined_evidence import sleep_profile as _sleep_profile

profile = _combined_profile
sleep_profile = _sleep_profile


@pytest.fixture
def client(profile):
    app, _ = create_ui_app(Settings(data_dir=profile[0].root, ui_port=8120))
    with TestClient(app, base_url="http://127.0.0.1:8120",
                    headers={"Origin": "http://127.0.0.1:8120"}) as result:
        yield result


def selection(fixture, **overrides):
    return {"days": 7, "end_date": str(fixture[2].end_date),
            "garmin_source_id": fixture[2].sleep_garmin_source_id,
            "google_hrv_source_id": fixture[2].sleep_google_source_id, **overrides}


@pytest.mark.parametrize("days", [7, 30])
def test_full_adapter_serializes_one_snapshot_and_both_downloads(
        client, profile, monkeypatch, days):
    packets = []
    requests = []
    original = ui.read_combined_evidence

    def capture(**kwargs):
        requests.append(kwargs["request"])
        packet = original(**kwargs)
        packets.append(packet)
        return packet

    monkeypatch.setattr(ui, "read_combined_evidence", capture)
    response = client.post("/api/analysis-export", json=selection(profile, days=days))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert len(packets) == 1
    packet = packets[0]
    assert data["json"] == encode_combined_evidence(packet)
    assert data["text"] == render_combined_evidence(packet)
    assert set(packet["sections"]) == {
        "sleep", "activity", "context", "stress", "body_battery", "hrv", "rhr", "steps", "weight"}
    assert json.loads(data["json"])["snapshot"] == "one_sqlite_read_transaction"
    assert packet["request"]["range_truncated"] is False
    assert requests[0].projection == "compact"
    assert requests[0].include_weight and requests[0].sleep_google_auto_select
    assert requests[0].rhr_google_auto_select
    assert packet["envelope_hash"][:12] in data["filename"]
    assert data["disclosures"]["stress"]["missing_day_count"] == days
    assert data["disclosures"]["body_battery"]["state"] == "no_eligible_in_period"
    assert data["disclosures"]["weight"]["measured_facts"]["returned_count"] == 0
    assert "rows" not in data["disclosures"]["context"]


def test_sources_are_explicit_bounded_and_no_store(client, profile):
    response = client.get("/api/analysis-export/sources")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    rows = response.json()["sources"]
    assert profile[2].sleep_garmin_source_id in {row["id"] for row in rows}
    assert {row["provider"] for row in rows} == {"garmin_connect", "google_health"}
    with session_scope(profile[1]) as session:
        original_source = session.get(GarminSource, profile[2].sleep_garmin_source_id)
        for index in range(33):
            session.add(GarminSource(provider_code="garmin_connect",
                                     provider_id=original_source.provider_id,
                                     acquisition_source_id=original_source.acquisition_source_id,
                                     source_kind=original_source.source_kind,
                                     source_instance_id=f"synthetic-extra-{index}"))
    response = client.get("/api/analysis-export/sources")
    assert response.status_code == 400
    assert response.json() == {"code": "source_inventory_exceeds_limit"}


@pytest.mark.parametrize("overrides", [
    {"days": 90}, {"days": True}, {"days": "7"}, {"days": 7.0},
    {"end_date": "invalid-private-input"}, {"end_date": "0001-01-01"},
    {"end_date": "9999-12-31"}, {"garmin_source_id": "missing"},
    {"google_hrv_source_id": "missing"}, {"profile": "private-path"},
])
def test_invalid_request_has_no_payload_or_supplied_values(client, profile, overrides):
    response = client.post("/api/analysis-export", json=selection(profile, **overrides))
    assert response.status_code in {400, 422}
    assert set(response.json()) <= {"code", "message"}
    assert "invalid-private-input" not in response.text
    assert "private-path" not in response.text


@pytest.mark.parametrize("serializer", ["encode_combined_evidence", "render_combined_evidence"])
def test_either_serializer_limit_fails_whole_response(client, profile, monkeypatch, serializer):
    def fail(_packet):
        raise EvidenceError("output_exceeds_byte_limit")

    monkeypatch.setattr(ui, serializer, fail)
    response = client.post("/api/analysis-export", json=selection(profile))
    assert response.status_code == 400
    assert response.json() == {"code": "output_exceeds_byte_limit"}
    assert response.headers["cache-control"] == "no-store"


def test_repeated_generation_failure_and_recovery_never_reuses_payload(
        client, profile, monkeypatch):
    original = ui.read_combined_evidence
    first = client.post("/api/analysis-export", json=selection(profile))
    assert first.status_code == 200

    def fail(**_kwargs):
        raise RuntimeError("private database path / secret / SQL")

    monkeypatch.setattr(ui, "read_combined_evidence", fail)
    failed = client.post("/api/analysis-export", json=selection(profile))
    assert failed.status_code == 503
    assert failed.json() == {"code": "export_unavailable"}
    monkeypatch.setattr(ui, "read_combined_evidence", original)
    next_result = client.post("/api/analysis-export", json=selection(profile, days=30))
    assert next_result.status_code == 200
    assert next_result.json()["filename"] != first.json()["filename"]
    assert json.loads(next_result.json()["json"])["request"]["days"] == 30


def test_optional_google_hrv_does_not_infer_source(client, profile):
    response = client.post(
        "/api/analysis-export", json=selection(profile, google_hrv_source_id=None))
    assert response.status_code == 200
    assert set(json.loads(response.json()["json"])["sections"]["hrv"]["providers"]) == {"garmin"}


def test_origin_guard_precedes_generation(client, profile, monkeypatch):
    def unexpected(**_kwargs):
        pytest.fail("foreign request reached reader")

    monkeypatch.setattr(ui, "read_combined_evidence", unexpected)
    response = client.post("/api/analysis-export", json=selection(profile),
                           headers={"Origin": "https://external.example"})
    assert response.status_code == 403


def test_overview_is_primary_entry_and_data_owns_simple_export(client):
    home = client.get("/", follow_redirects=False)
    assert home.status_code == 307 and home.headers["location"] == "/brief"
    legacy = client.get("/?source=synthetic&view=history", follow_redirects=False)
    assert legacy.headers["location"] == "/weight?source=synthetic&view=history"
    assert client.get("/weight").status_code == 200
    overview = client.get("/brief")
    assert overview.status_code == 200
    assert 'id="analysis-export-form"' not in overview.text
    assert '/static/analysis_export.js' not in overview.text
    assert '/imports#analysis-export' in overview.text
    assert '<h3><a href="/weight">Вес</a></h3>' in overview.text
    data = client.get("/imports")
    assert data.status_code == 200
    for text in ('Скачать данные', 'id="analysis-export-form"',
                 'id="analysis-export-text"', 'id="analysis-export-json"',
                 '/static/analysis_export.js', '2 MiB', 'ваши комментарии',
                 'name="days"', 'name="end_date"', '>Скачать</button>'):
        assert text in data.text
    assert 'Сформировать</button>' not in data.text
    assert 'id="analysis-export-options"' in data.text


def test_disclosures_preserve_unknown_conflicts_and_pagination():
    value = {"providers": {"google": {"state": "conflict", "missing_day_count": None,
             "source_selection": {"search_complete": False}}},
             "rows": [{"text": "private comment"}], "has_more": True,
             "warnings": ["missing_is_not_zero"]}
    assert ui._disclosures(value) == {
        "providers": {"google": {"state": "conflict", "missing_day_count": None,
                       "source_selection": {"search_complete": False}}},
        "has_more": True, "warnings": ["missing_is_not_zero"]}


def test_disclosures_reduce_cells_to_state_counts_only():
    value = {"cells": [
        {"state": "value", "value": 42, "evidence": {"private": "comment"}},
        {"state": "ambiguous", "value": None, "evidence": {"private": "comment"}},
        {"state": "unavailable", "evidence": {"private": "comment"}},
        {"state": "value", "value": 7, "evidence": {}},
    ]}
    assert ui._disclosures(value) == {"cell_state_counts": {
        "value": 2, "ambiguous": 1, "unavailable": 1}}



def test_completed_export_api_mode_and_legacy_default(client, profile, monkeypatch):
    from types import SimpleNamespace

    from test_combined_evidence import _seed_completed_steps
    from test_sleep_evidence import CLOCK

    identity = _seed_completed_steps(profile, 0)
    monkeypatch.setattr(ui, "datetime", SimpleNamespace(now=lambda _zone: CLOCK))
    response = client.post(
        "/api/analysis-export",
        json=selection(
            profile, garmin_source_id=identity, google_hrv_source_id=None, steps_view="completed"
        ),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    packet = json.loads(data["json"])
    assert packet["version"] == "health-chat-combined-compact-evidence-v5"
    assert packet["request"]["steps_view"] == "completed"
    assert data["disclosures"]["steps"]["display_zone"] == "Europe/Moscow"
    assert data["disclosures"]["steps"]["completed_day_count"] == 7
    assert "effective_completed_range" in data["disclosures"]["steps"]
    assert data["disclosures"]["steps"]["cell_state_counts"]["value"] == 1
    legacy = client.post("/api/analysis-export", json=selection(profile))
    assert (
        json.loads(legacy.json()["json"])["version"] == "health-chat-combined-compact-evidence-v4"
    )
    bad = client.post(
        "/api/analysis-export", json=selection(profile, steps_view="private-invalid-mode")
    )
    assert bad.status_code == 400 and bad.json() == {"code": "invalid_steps_view"}


def test_completed_export_ui_declares_mode_and_effective_days(client):
    response = client.get("/imports")
    assert 'name="steps_view"' in response.text
    assert '<option value="completed" selected>' in response.text
    assert '<option value="observed">' in response.text
    script = client.get("/static/analysis_export.js").text
    assert 'steps_view: values.get("steps_view")' in script
    assert "effective_completed_range" in script and "completed_day_count" in script


@pytest.mark.parametrize("end,days", [
    ("2024-03-01", 7), ("2024-03-01", 30), ("2025-01-05", 7), ("2025-01-05", 30),
])
def test_sleep_period_handoff_prefills_only_then_exports_exact_range(
        client, profile, monkeypatch, end, days):
    from html import unescape
    from re import search

    calls = []
    original = ui.read_combined_evidence

    def capture(**kwargs):
        calls.append(kwargs["request"])
        return original(**kwargs)

    monkeypatch.setattr(ui, "read_combined_evidence", capture)
    sleep = client.get(f"/sleep?wake_date={end}&days={days}")
    link = search(r'href="([^"]+)" data-sleep-export', sleep.text)
    assert link
    target = unescape(link.group(1))
    assert target == f"/imports?export_end_date={end}&export_days={days}#analysis-export"
    page = client.get(target)
    assert page.status_code == 200
    assert calls == []  # GET never generates an export.
    start = str(date.fromisoformat(end) - timedelta(days=days - 1))
    assert f'<option value="{days}" selected>' in page.text
    assert f'name="end_date" value="{end}"' in page.text
    assert f'Период: {start} — {end} (включительно).' in page.text
    assert "Скачайте и приложите в личный чат" in page.text
    response = client.post("/api/analysis-export", json=selection(profile, days=days, end_date=end))
    assert response.status_code == 200
    assert len(calls) == 1 and calls[0].days == days and str(calls[0].end_date) == end
    data = response.json()
    assert data["range"] == {"start_date": start, "end_date": end,
                             "precision": "inclusive_local_date"}
    assert json.loads(data["json"])["request"]["effective_range"] == data["range"]
    assert f"{end}-{days}d" in data["filename"]


def test_export_prefill_defaults_still_today_and_30(client):
    response = client.get("/imports")
    end = date.today()
    assert f'name="end_date" value="{end}"' in response.text
    assert '<option value="30" selected>' in response.text
    assert f'Период: {end - timedelta(days=29)} — {end} (включительно).' in response.text


@pytest.mark.parametrize("query", [
    "export_days=14", "export_days=07", "export_days=", "export_days=7&export_days=30",
    "export_end_date=invalid-private-date", "export_end_date=2025-02-29",
    "export_end_date=20240301", "export_end_date=2024-W09-5", "export_end_date=",
    "export_end_date=0001-01-01&export_days=7",
    "export_end_date=0001-01-29&export_days=30", "export_end_date=9999-12-31",
    "export_end_date=2024-03-01&export_end_date=2025-03-01",
    "export_end_date=%22%3E%3Cscript%3Ealert(1)%3C/script%3E",
])
def test_invalid_export_prefill_rejects_without_range_or_generation(client, monkeypatch, query):
    def unexpected(**_kwargs):
        pytest.fail("invalid GET reached export reader")

    monkeypatch.setattr(ui, "read_combined_evidence", unexpected)
    response = client.get("/imports?" + query)
    assert response.status_code == 400
    assert 'invalid_export_period' in response.text
    assert 'id="analysis-export-form"' not in response.text
    assert 'invalid-private-date' not in response.text
    assert '<script>alert(1)</script>' not in response.text


@pytest.mark.parametrize("end,days", [("0001-01-07", 7), ("0001-01-30", 30)])
def test_export_prefill_accepts_first_complete_range(client, end, days):
    response = client.get(f"/imports?export_end_date={end}&export_days={days}")
    assert response.status_code == 200
    assert f'Период: 0001-01-01 — {end} (включительно).' in response.text
