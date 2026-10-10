"""Focused synthetic checks for the source-bound saved Activity detail (#345)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.analytics.garmin_activity_comparison import (
    ACTIVITY_COMPARISON_METRIC_CODES,
    GarminActivityComparisonError,
    assemble_garmin_activity_session,
    compute_garmin_activity_comparison,
)
from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.models import GarminSourceRecord
from healthcheck.garmin.normalization import garmin_source_identity, normalize_garmin_payload
from healthcheck.garmin.persistence import (
    PROJECTION_RETIRED,
    RETIRE_REASON_AUTHORITATIVE,
    GarminPersistenceRepository,
)
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.runtime import prepare_runtime
from healthcheck.web.garmin_query import GarminQueryError, GarminQueryService
from healthcheck.web.ui_app import create_ui_app
from test_garmin_training_owner_view import _ui


def client_for(app):
    return TestClient(
        app, base_url="http://127.0.0.1:8120", headers={"Origin": "http://127.0.0.1:8120"}
    )


def _persist(
    paths,
    payload,
    *,
    stream,
    device_model="Synthetic detail",
    device_code="synthetic-detail",
):
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            result = normalize_garmin_payload(
                payload,
                stream=stream,
                source_identity=garmin_source_identity(
                    source_kind="provider",
                    device_attributed=True,
                    device_code=device_code,
                    device_model=device_model,
                ),
            )
            outcome = GarminPersistenceRepository(
                session,
                payload_store=ContentAddressedGarminPayloadStore(paths.root / "artifacts"),
            ).persist_result(result, payload=payload, received_at=datetime(2099, 4, 1, tzinfo=UTC))
            return outcome.source.id
    finally:
        engine.dispose()


def _detail_activities():
    return [
        {
            "activityId": "detail-tennis-1",
            "activityType": {"typeKey": "tennis_v2"},
            "calendarDate": "2099-03-02",
            "startTimeGMT": "2099-03-02T08:30:00Z",
            "duration": 3901.5,
            "distance": None,
            "averageHR": 110,
            "averageSpeed": 3.5,
            "activityTrainingLoad": 10,
            "aerobicTrainingEffect": 2.5,
            "maxHR": 165,
            "anaerobicTrainingEffect": 1.8,
        },
        {
            "activityId": "detail-tennis-2",
            "activityType": {"typeKey": "tennis"},
            "calendarDate": "2099-03-03",
            "startTimeGMT": "2099-03-03T08:30:00Z",
            "duration": 3600,
            "distance": 0,
            "averageHR": 100,
            "activityTrainingLoad": 0,
            "aerobicTrainingEffect": 2.0,
        },
    ]


def _seed_detail(paths):
    return _persist(paths, {"activities": _detail_activities()}, stream="activity")


def _records(paths, source_id, *, stream_code="activity"):
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            return list(
                session.scalars(
                    select(GarminSourceRecord)
                    .where(
                        GarminSourceRecord.garmin_source_id == source_id,
                        GarminSourceRecord.stream_code == stream_code,
                    )
                    .order_by(GarminSourceRecord.id.asc())
                )
            )
    finally:
        engine.dispose()


def _activity_ids(paths, source_id):
    return {row.external_record_id: row.id for row in _records(paths, source_id)}


def _card(text, metric_code):
    match = re.search(
        r'<article class="activity-metric-card" data-metric="' + metric_code + r'">(.*?)</article>',
        text,
        re.S,
    )
    assert match, f"card missing: {metric_code}"
    return match.group(1)


def _pre(text, element_id):
    match = re.search(r'<pre id="' + element_id + r'">(.*?)</pre>', text, re.S)
    assert match, f"pre missing: {element_id}"
    return match.group(1)


def test_detail_route_binds_source_cards_and_exact_evidence(tmp_path):
    app, _, paths = _ui(tmp_path)
    source = _seed_detail(paths)
    ids = _activity_ids(paths, source)
    first = ids["detail-tennis-1"]

    with client_for(app) as client:
        page = client.get(
            "/garmin/session", params={"garmin_source_id": source, "record_id": first}
        )
        assert page.status_code == 200
        assert 'lang="en"' not in page.text
        assert "Теннис" in page.text
        assert f'href="/garmin?garmin_source_id={source}#activity-journal"' in page.text

        duration = _card(page.text, "duration_seconds")
        assert 'data-owner-state="present">3901.5</span>' in duration
        assert 'activity-metric-unit">с</span>' in duration
        assert "1 ч 5 мин 1.5 с" in duration
        average = _card(page.text, "heart_rate_bpm")
        assert 'data-owner-state="present">110.0</span>' in average
        assert 'activity-metric-unit">уд/мин</span>' in average
        maximum = _card(page.text, "max_heart_rate_bpm")
        assert 'data-owner-state="present">165.0</span>' in maximum
        anaerobic = _card(page.text, "anaerobic_training_effect")
        assert 'data-owner-state="present">1.8</span>' in anaerobic
        assert 'activity-metric-unit">баллы</span>' in anaerobic
        load = _card(page.text, "acute_training_load")
        assert 'data-owner-state="present">10.0</span>' in load
        # Provider did not save a distance value; null stays unavailable, never zero.
        assert (
            'data-owner-state="unavailable">Не предоставлено</span>'
            in _card(page.text, "distance_meters")
        )

        # Exact read result is embedded once in the technical disclosure.
        evidence = json.loads(_pre(page.text, "activity-session-evidence"))
        assert evidence["record_id"] == first
        assert evidence["projection_status"] == "current"
        assert evidence["stream_code"] == "activity"
        assert evidence["result_hash"] and len(evidence["result_hash"]) == 64
        assert {item["metric_code"] for item in evidence["metric_coverage"]} == set(
            ACTIVITY_COMPARISON_METRIC_CODES
        )
        assert evidence["frozen_inputs"]

        # Raw identifiers stay out of the visible primary text (hrefs excluded).
        primary = page.text.split(
            '<details class="card owner-details activity-session-technical', 1
        )[0]
        visible = re.sub(r'href="[^"]*"', 'href=""', primary)
        assert first not in visible
        assert "idempotency_key" not in visible
        assert "idempotency_key" in page.text


def test_detail_route_omits_typed_extras_without_saved_evidence(tmp_path):
    app, _, paths = _ui(tmp_path)
    source = _seed_detail(paths)
    ids = _activity_ids(paths, source)
    second = ids["detail-tennis-2"]

    with client_for(app) as client:
        page = client.get(
            "/garmin/session", params={"garmin_source_id": source, "record_id": second}
        )
        assert page.status_code == 200
        # Zero distance and zero load are present zeros, not missing.
        assert (
            'data-owner-state="present">0.0</span>' in _card(page.text, "distance_meters")
        )
        assert (
            'data-owner-state="present">0.0</span>' in _card(page.text, "acute_training_load")
        )
        # #319 typed max-HR/anaerobic cards need saved values; absent evidence hides them.
        assert "Максимальный пульс Garmin" not in page.text
        assert "Анаэробный эффект Garmin" not in page.text
        evidence = json.loads(_pre(page.text, "activity-session-evidence"))
        coverage = {item["metric_code"]: item for item in evidence["metric_coverage"]}
        assert coverage["max_heart_rate_bpm"]["status"] == "missing"
        assert coverage["max_heart_rate_bpm"]["value"] is None
        assert coverage["anaerobic_training_effect"]["status"] == "missing"
        assert coverage["distance_meters"]["status"] == "zero"


def test_detail_route_rejects_wrong_source_unknown_retired_and_non_activity(tmp_path):
    app, _, paths = _ui(tmp_path)
    source_a = _seed_detail(paths)
    ids = _activity_ids(paths, source_a)
    first, second = ids["detail-tennis-1"], ids["detail-tennis-2"]
    source_b = _persist(
        paths,
        {
            "activities": [
                {
                    "activityId": "detail-other",
                    "activityType": {"typeKey": "walking"},
                    "calendarDate": "2099-03-04",
                    "duration": 600,
                    "averageHR": 90,
                }
            ]
        },
        stream="activity",
        device_model="Synthetic other",
        device_code="synthetic-other",
    )
    other = _activity_ids(paths, source_b)["detail-other"]
    _persist(
        paths,
        {"calendarDate": "2099-03-02", "avgStressLevel": 21, "averageSpO2": 95},
        stream="intraday",
    )
    intraday = _records(paths, source_a, stream_code="intraday")[0].id

    with client_for(app) as client:
        cross = client.get(
            "/garmin/session", params={"garmin_source_id": source_a, "record_id": other}
        )
        assert cross.status_code == 404
        assert "Сохранённая сессия не найдена" in cross.text
        assert "600.0" not in cross.text

        wrong_source = client.get(
            "/garmin/session", params={"garmin_source_id": source_b, "record_id": first}
        )
        assert wrong_source.status_code == 404
        assert "3901.5" not in wrong_source.text

        unknown = client.get(
            "/garmin/session",
            params={
                "garmin_source_id": source_a,
                "record_id": "00000000-0000-4000-8000-000000000000",
            },
        )
        assert unknown.status_code == 404

        non_activity = client.get(
            "/garmin/session", params={"garmin_source_id": source_a, "record_id": intraday}
        )
        assert non_activity.status_code == 404

        missing_record = client.get("/garmin/session", params={"garmin_source_id": source_a})
        assert missing_record.status_code == 400
        assert "Сохранённая сессия не выбрана" in missing_record.text

        missing_source = client.get("/garmin/session", params={"record_id": second})
        assert missing_source.status_code == 400
        assert "Источник не указан" in missing_source.text

        unknown_source = client.get(
            "/garmin/session",
            params={"garmin_source_id": "no-such-source", "record_id": second},
        )
        assert unknown_source.status_code == 400
        assert "Источник Garmin не найден" in unknown_source.text

        engine = create_sqlite_engine(paths)
        try:
            with session_scope(engine) as session:
                record = session.get(GarminSourceRecord, first)
                observed = datetime(2099, 5, 1, tzinfo=UTC)
                record.projection_status = PROJECTION_RETIRED
                record.retired_at = observed
                record.retire_reason = RETIRE_REASON_AUTHORITATIVE
                record.projection_observed_at = observed
                session.commit()
        finally:
            engine.dispose()

        retired = client.get(
            "/garmin/session", params={"garmin_source_id": source_a, "record_id": first}
        )
        assert retired.status_code == 404
        assert "3901.5" not in retired.text
        journal = client.get("/garmin", params={"garmin_source_id": source_a})
        assert f"record_id={first}" not in journal.text
        assert f"record_id={second}" in journal.text


def test_detail_read_matches_comparison_coverage_and_is_deterministic(tmp_path):
    app, settings, paths = _ui(tmp_path)
    source = _seed_detail(paths)
    ids = _activity_ids(paths, source)
    first, second = ids["detail-tennis-1"], ids["detail-tennis-2"]

    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            service = GarminQueryService(session, settings)
            detail = service.activity_session_detail(
                garmin_source_id=source, activity_record_id=first
            )
            repeat = service.activity_session_detail(
                garmin_source_id=source, activity_record_id=first
            )
            assert detail == repeat
            assert detail["contract_version"] == "garmin-activity-session-owner-view-v1"
            assert detail["source"]["id"] == source
            body = detail["session"]
            coverage = {item["metric_code"]: item for item in body["metric_coverage"]}
            assert coverage["duration_seconds"]["value"] == 3901.5
            assert coverage["duration_seconds"]["unit"] == "seconds"
            assert coverage["max_heart_rate_bpm"]["status"] == "usable"
            assert coverage["max_heart_rate_bpm"]["value"] == 165
            assert coverage["max_heart_rate_bpm"]["unit"] == "bpm"
            assert coverage["anaerobic_training_effect"]["value"] == 1.8
            assert coverage["distance_meters"]["status"] == "null"
            assert coverage["distance_meters"]["value"] is None
            cards = {card["metric_code"]: card for card in detail["cards"]}
            assert cards["duration_seconds"]["value"] == 3901.5
            assert cards["distance_meters"]["state"] == "null"
            assert cards["max_heart_rate_bpm"]["state"] == "value"

            # The detail coverage is the same per-record read used by A/B comparison.
            comparison = compute_garmin_activity_comparison(
                session,
                garmin_source_id=source,
                activity_record_ids=[first, second],
                reference_activity_id=first,
            )
            reference_block = next(
                block for block in comparison.sessions if block.record_id == first
            )
            assert [item.as_dict() for item in reference_block.metric_coverage] == body[
                "metric_coverage"
            ]
            raw = assemble_garmin_activity_session(
                session, garmin_source_id=source, activity_record_id=first
            )
            assert raw.result_hash == body["result_hash"]

            with pytest.raises(GarminActivityComparisonError) as missing_source:
                assemble_garmin_activity_session(
                    session, garmin_source_id="", activity_record_id=first
                )
            assert missing_source.value.reason_code == "missing_garmin_source_id"
            with pytest.raises(GarminActivityComparisonError) as missing_record:
                assemble_garmin_activity_session(
                    session, garmin_source_id=source, activity_record_id="  "
                )
            assert missing_record.value.reason_code == "missing_activity_record_id"
            with pytest.raises(GarminQueryError) as unknown_source:
                service.activity_session_detail(
                    garmin_source_id="00000000-0000-4000-8000-000000000000",
                    activity_record_id=first,
                )
            assert unknown_source.value.code == "unknown_garmin_source_id"
    finally:
        engine.dispose()


def test_journal_detail_link_preserves_period_and_source(tmp_path):
    app, _, paths = _ui(tmp_path)
    source = _seed_detail(paths)
    ids = _activity_ids(paths, source)
    first = ids["detail-tennis-1"]
    params = {
        "garmin_source_id": source,
        "metric_code": "stress_daily_average",
        "start_date": "2099-03-01",
        "end_date": "2099-03-05",
    }
    with client_for(app) as client:
        page = client.get("/garmin", params=params)
        assert page.status_code == 200
        journal_link = (
            f'href="/garmin/session?garmin_source_id={source}&amp;record_id={first}'
            f'&amp;metric_code=stress_daily_average&amp;start_date=2099-03-01'
            f'&amp;end_date=2099-03-05"'
        )
        assert journal_link in page.text

        detail = client.get("/garmin/session", params={**params, "record_id": first})
        assert detail.status_code == 200
        back_link = (
            f'href="/garmin?garmin_source_id={source}&amp;metric_code=stress_daily_average'
            f'&amp;start_date=2099-03-01&amp;end_date=2099-03-05#activity-journal"'
        )
        assert back_link in detail.text

        # A/B comparison endpoint still returns every accepted metric code.
        response = client.get(
            "/api/garmin/activity-comparison",
            params={
                "garmin_source_id": source,
                "activity_record_ids": f"{first},{ids['detail-tennis-2']}",
                "reference_activity_id": first,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert {m["metric_code"] for m in body["comparisons"][0]["metrics"]} == set(
            ACTIVITY_COMPARISON_METRIC_CODES
        )


def test_detail_uninitialized_store_keeps_503_document(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())
    with client_for(app) as client:
        # A bounded request first creates the app request engine (as #347 does).
        assert client.get(
            "/garmin/session", params={"garmin_source_id": "any", "record_id": "any"}
        ).status_code == 400
    app.state.engine.dispose()
    paths.database.unlink()

    with client_for(app) as client:
        response = client.get(
            "/garmin/session", params={"garmin_source_id": "any", "record_id": "any"}
        )
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("text/html")
    primary, technical = response.text.split('<details class="card owner-details', 1)
    assert 'role="alert"' in primary
    assert 'data-owner-state="error"' in primary
    assert "Локальное хранилище данных не готово." in primary
    assert "database_unavailable" in technical
    assert "no such table" not in response.text.lower()
    assert "OperationalError" not in response.text


def test_detail_read_failure_is_russian_alert_without_raw_internals(tmp_path, monkeypatch):
    app, _, paths = _ui(tmp_path)
    source = _seed_detail(paths)

    def failing_assemble(*args, **kwargs):
        raise SQLAlchemyError("synthetic detail read failure")

    monkeypatch.setattr(
        "healthcheck.web.garmin_query.assemble_garmin_activity_session", failing_assemble
    )
    with client_for(app) as client:
        response = client.get(
            "/garmin/session", params={"garmin_source_id": source, "record_id": "any"}
        )
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("text/html")
    primary, technical = response.text.split('<details class="card owner-details', 1)
    assert 'role="alert"' in primary
    assert "Не удалось выполнить запрос. Попробуй повторить его." in primary
    assert "synthetic detail read failure" not in response.text
    assert "persistence_error" in technical
