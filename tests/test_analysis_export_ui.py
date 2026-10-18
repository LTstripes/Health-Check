"""Synthetic UI adapter regressions; reader semantics remain in their own tests."""

import json

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


def test_overview_contains_form_downloads_and_semantic_disclosures(client):
    response = client.get("/brief")
    assert response.status_code == 200
    for text in ("Выгрузка для анализа", 'id="analysis-export-form"',
                 'id="analysis-export-text"', 'id="analysis-export-json"',
                 '/static/analysis_export.js', "2 MiB", "не являются завершёнными",
                 "недельные снимки", "Полнота сбора неизвестна"):
        assert text in response.text


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
