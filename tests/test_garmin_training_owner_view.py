"""Synthetic owner Training & recovery presentation over #180 evidence (#187)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.models import GarminSource, GarminTrainingSnapshot
from healthcheck.garmin.normalization import garmin_source_identity, normalize_garmin_payload
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.garmin.training import persist_training_payload, read_training_evidence
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.runtime import prepare_runtime
from healthcheck.web.garmin_training_overview import (
    TRAINING_OVERVIEW_CONTRACT,
    build_training_overview,
)
from healthcheck.web.ui_app import create_ui_app


def _ui(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())
    return app, settings, paths


def _status(source_day: str = "2099-01-02", *, training_status: int | float = 0) -> dict:
    return {
        "mostRecentTrainingStatus": {
            "latestTrainingStatusData": {
                "dynamic-provider-device": {
                    "calendarDate": source_day,
                    "deviceId": 811,
                    "trainingStatus": training_status,
                    "trainingStatusFeedbackPhrase": "synthetic feedback",
                    "acuteTrainingLoadDTO": {
                        "dailyTrainingLoadAcute": 0,
                        "dailyTrainingLoadChronic": None,
                        "acwrPercent": 88,
                        "dailyAcuteChronicWorkloadRatio": 0.88,
                        "acwrStatus": "synthetic status",
                    },
                }
            }
        },
        "mostRecentTrainingLoadBalance": {
            "metricsTrainingLoadBalanceDTOMap": {
                "dynamic-provider-device": {
                    "monthlyLoadAerobicLow": 0,
                    "monthlyLoadAerobicHigh": None,
                    "monthlyLoadAnaerobic": 12,
                    "monthlyLoadAnaerobicTargetMax": 200,
                }
            }
        },
    }


def _readiness() -> list[dict]:
    return [
        {
            "calendarDate": "2099-01-02",
            "timestamp": stamp,
            "timestampLocal": stamp.replace("T06", "T09").replace("T12", "T15"),
            "deviceId": 811,
            "score": score,
            "level": level,
            "recoveryTime": recovery,
            "acuteLoad": acute,
            "acwrFactorFeedback": feedback,
            "inputContext": "synthetic context",
            "primaryActivityTracker": False,
        }
        for stamp, score, level, recovery, acute, feedback in (
            ("2099-01-02T06:00:00", 0, "poor", None, 10, "earlier"),
            ("2099-01-02T12:00:00", 76, "productive", 0, 20, "later"),
        )
    ]


def _persist_activity(session, store, *, activity_id: str, day: str, load: float | None):
    payload = {
        "activities": [
            {
                "activityId": activity_id,
                "activityType": {"typeKey": "cycling"},
                "calendarDate": day,
                "startTimeGMT": f"{day}T08:00:00Z",
                "deviceId": 811,
                "activityTrainingLoad": load,
                "aerobicTrainingEffect": 2.5 if load is not None else None,
                "anaerobicTrainingEffect": None,
                "trainingEffectLabel": "synthetic label",
            }
        ]
    }
    identity = garmin_source_identity(source_kind="provider")
    normalized = normalize_garmin_payload(payload, stream="activity", source_identity=identity)
    return GarminPersistenceRepository(session, payload_store=store).persist_result(
        normalized, payload=payload, received_at=datetime(2099, 1, 3, tzinfo=UTC)
    )


def _seed_training(session, store):
    persist_training_payload(
        session,
        store,
        surface="training_status",
        requested_date=date(2099, 1, 7),
        payload=_status("2099-01-02", training_status=0),
        received_at=datetime(2099, 1, 7, 8, tzinfo=UTC),
    )
    persist_training_payload(
        session,
        store,
        surface="training_readiness",
        requested_date=date(2099, 1, 4),
        payload=_readiness(),
        received_at=datetime(2099, 1, 4, 13, tzinfo=UTC),
    )
    _persist_activity(session, store, activity_id="act-older", day="2099-01-01", load=10)
    _persist_activity(session, store, activity_id="act-newer", day="2099-01-03", load=0)
    session.commit()
    source = session.scalar(select(GarminSource))
    assert source is not None
    return source.id


def _assert_no_training_leaks(payload) -> None:
    blob = json.dumps(payload, default=str)
    lowered = blob.lower()
    for banned in (
        "provider_device_id",
        "provider_device_key",
        "dynamic-provider-device",
        '"record_id"',
        "requested_dates",
        "activityrecorderdeviceid",
        "access_token",
        "refresh_token",
        "payload_body",
        "raw_payload",
    ):
        assert banned not in lowered
    assert "811" not in blob


def test_training_overview_chronology_zero_missing_and_units(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            source_id = _seed_training(session, store)
            # Later acquisition of the same source day must not change chronology.
            persist_training_payload(
                session,
                store,
                surface="training_status",
                requested_date=date(2099, 1, 9),
                payload=_status("2099-01-02", training_status=0),
                received_at=datetime(2099, 1, 9, tzinfo=UTC),
            )
            session.commit()
            snapshots_before = session.scalar(
                select(func.count()).select_from(GarminTrainingSnapshot)
            )
            overview = build_training_overview(session, garmin_source_id=source_id)
            evidence = read_training_evidence(session, garmin_source_id=source_id)
    finally:
        engine.dispose()

    assert overview["contract_version"] == TRAINING_OVERVIEW_CONTRACT
    assert overview["status"] == "available"
    assert overview["metric_producer"] == "unverified"
    status = overview["training_status"]
    assert status["source_date"] == "2099-01-02"
    assert "2099-01-07" not in json.dumps(status)
    assert "2099-01-09" not in json.dumps(status)
    assert status["fields"]["trainingStatus"] == {"state": "zero", "value": 0}
    assert status["fields"]["dailyTrainingLoadAcute"]["state"] == "zero"
    assert status["fields"]["dailyTrainingLoadChronic"]["state"] == "null"
    assert status["fields"]["dailyTrainingLoadChronic"]["value"] is None
    assert status["attribution_label"] == "associated device"

    focus = overview["load_focus"]
    assert focus["dated"] is False
    assert focus["source_date"] is None
    assert focus["fields"]["monthlyLoadAerobicLow"]["state"] == "zero"
    assert focus["fields"]["monthlyLoadAerobicHigh"]["state"] == "null"
    assert focus["fields"]["monthlyLoadAnaerobic"]["state"] == "value"

    readiness = overview["readiness"]
    assert readiness["snapshot_count"] == 2
    assert readiness["source_timestamp_utc"] == "2099-01-02T12:00:00+00:00"
    assert readiness["fields"]["score"]["value"] == 76
    assert readiness["fields"]["recoveryTime"]["state"] == "zero"
    assert readiness["fields"]["recoveryTime"]["value"] == 0
    assert readiness["fields"]["recoveryTime"]["unit_status"] == "unavailable"
    assert readiness["fields"]["recoveryTime"]["unit"] is None
    assert "hour" not in json.dumps(readiness["fields"]["recoveryTime"]).lower()
    assert "minute" not in json.dumps(readiness["fields"]["recoveryTime"]).lower()

    readiness_rows = [row for row in evidence if row["kind"] == "readiness"]
    assert len(readiness_rows) == 2
    assert snapshots_before >= 4  # status + load_balance + 2 readiness

    activities = overview["recent_activities"]
    assert len(activities) == 2
    assert activities[0]["source_date"] == "2099-01-03"
    assert activities[0]["activity_type"] == "cycling"
    assert activities[0]["fields"]["activityTrainingLoad"]["state"] == "zero"
    assert activities[0]["fields"]["aerobicTrainingEffect"]["state"] == "value"
    assert activities[0]["fields"]["anaerobicTrainingEffect"]["state"] == "null"
    assert activities[0]["fields"]["trainingEffectLabel"]["value"] == "synthetic label"
    assert activities[0]["attribution_label"] == "activity recorder"
    _assert_no_training_leaks(overview)

    with TestClient(app) as client:
        api = client.get(
            "/api/garmin/training-overview",
            params={"garmin_source_id": source_id, "activity_limit": 5},
        )
        assert api.status_code == 200, api.text
        body = api.json()
        assert body["training_status"]["source_date"] == "2099-01-02"
        assert body["readiness"]["snapshot_count"] == 2
        assert body["load_focus"]["dated"] is False
        _assert_no_training_leaks(body)

        page = client.get(f"/garmin?garmin_source_id={source_id}")
        assert page.status_code == 200
        assert "Training &amp; recovery" in page.text or "Training & recovery" in page.text
        assert "2099-01-02" in page.text
        assert "Undated (request date not attached)" in page.text
        assert "unit unavailable" in page.text
        assert "metric producer unverified" in page.text
        assert "associated device" in page.text
        assert "activity recorder" in page.text
        assert "synthetic feedback" in page.text
        assert "dynamic-provider-device" not in page.text
        assert "VO2Max" not in page.text
        assert "coaching" not in page.text.lower() or "no coaching" in page.text.lower()
        # R03 cards remain present.
        assert "Scalar series / baseline / trend (R03-01)" in page.text
        assert "Activity comparison (R03-02)" in page.text
        assert "Lagged association (R03-03)" in page.text

        dashboard = client.get(
            "/api/garmin/dashboard", params={"garmin_source_id": source_id}
        ).json()
        assert "training_overview" in dashboard
        assert dashboard["training_overview"]["status"] == "available"
        assert dashboard["series"] is not None or dashboard["unavailable_reason"] is not None


def test_training_overview_source_selection_and_partial_evidence(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    with TestClient(app) as client:
        empty = client.get("/api/garmin/training-overview").json()
        assert empty["status"] == "no_data"
        page = client.get("/garmin")
        assert "No Garmin source" in page.text
        assert "Training &amp; recovery" in page.text or "Training & recovery" in page.text

    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            # Two device-attributed sources force explicit selection.
            for fixture_id, code, model, stress in (
                ("synthetic-training-source-a", "garmin_vivoactive_5", "Vivoactive 5", 20),
                ("synthetic-training-source-b", "garmin_fenix", "Fenix", 22),
            ):
                result = normalize_garmin_payload(
                    {
                        "fixture_contract_version": "r02-garmin-capability-fixture-v1",
                        "fixture_id": fixture_id,
                        "source_kind": "synthetic",
                        "provider_code": "garmin_connect",
                        "stream_code": "intraday",
                        "device": {"attributed": True, "code": code, "model": model},
                        "payload": {"calendarDate": "2099-05-01", "avgStressLevel": stress},
                    }
                )
                GarminPersistenceRepository(session, payload_store=store).persist_result(
                    result,
                    payload={"fixture_id": fixture_id},
                    received_at=datetime(2099, 5, 1, tzinfo=UTC),
                )
            session.commit()
            device_sources = list(
                session.scalars(select(GarminSource.id).order_by(GarminSource.id))
            )
            assert len(device_sources) == 2

            # Status-only training evidence (no readiness, no load focus).
            persist_training_payload(
                session,
                store,
                surface="training_status",
                requested_date=date(2099, 5, 2),
                payload={
                    "mostRecentTrainingStatus": {
                        "latestTrainingStatusData": {
                            "only-status": {
                                "calendarDate": "2099-05-01",
                                "trainingStatus": 1,
                                "trainingStatusFeedbackPhrase": "status only",
                                "acuteTrainingLoadDTO": {"dailyTrainingLoadAcute": 5},
                            }
                        }
                    }
                },
                received_at=datetime(2099, 5, 2, tzinfo=UTC),
            )
            session.commit()
            # Training rows attach to the provider identity source created by #180.
            training_source_id = None
            for source_id in session.scalars(select(GarminSource.id)):
                overview = build_training_overview(session, garmin_source_id=source_id)
                if overview["status"] == "available" and overview["availability"]["has_status"]:
                    training_source_id = source_id
                    break
            assert training_source_id is not None
            sources_total = session.scalar(select(func.count()).select_from(GarminSource))
            assert sources_total >= 3
    finally:
        engine.dispose()

    with TestClient(app) as client:
        require = client.get("/api/garmin/training-overview").json()
        assert require["status"] == "require_selection"
        page = client.get("/garmin")
        assert "Select a Garmin source" in page.text or "select a source" in page.text.lower()

        overview = client.get(
            "/api/garmin/training-overview",
            params={"garmin_source_id": training_source_id},
        ).json()
        assert overview["status"] == "available"
        assert overview["availability"]["has_status"] is True
        assert overview["availability"]["has_readiness"] is False
        assert overview["readiness"] is None
        assert overview["load_focus"] is None
        page = client.get(f"/garmin?garmin_source_id={training_source_id}")
        assert "Readiness not provided" in page.text
        assert "Load focus not provided" in page.text

        # A device source without training evidence stays honest.
        bare = client.get(
            "/api/garmin/training-overview",
            params={"garmin_source_id": device_sources[0]},
        ).json()
        assert bare["status"] == "no_training_evidence"
        bare_page = client.get(f"/garmin?garmin_source_id={device_sources[0]}")
        assert "No Training evidence yet" in bare_page.text


def test_training_overview_no_network_and_no_activity_detail(tmp_path, monkeypatch):
    app, _settings, paths = _ui(tmp_path)
    calls: list[str] = []

    def _blocked(*_args, **_kwargs):
        calls.append("network")
        raise AssertionError("network must not be used")

    monkeypatch.setattr("urllib.request.urlopen", _blocked)
    try:
        import http.client

        monkeypatch.setattr(http.client.HTTPConnection, "request", _blocked)
    except Exception:
        pass

    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            source_id = _seed_training(session, store)
    finally:
        engine.dispose()

    with TestClient(app) as client:
        assert client.get(f"/garmin?garmin_source_id={source_id}").status_code == 200
        assert (
            client.get(
                "/api/garmin/training-overview", params={"garmin_source_id": source_id}
            ).status_code
            == 200
        )
        assert (
            client.get("/api/garmin/dashboard", params={"garmin_source_id": source_id}).status_code
            == 200
        )
    assert calls == []
