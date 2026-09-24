"""Synthetic-only Garmin Training Phase B chronology and persistence contracts."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select

from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
from healthcheck.db.models import (
    GarminPayloadObservation,
    GarminRawPayload,
    GarminSource,
    GarminSourceRecord,
    GarminTrainingAcquisition,
    GarminTrainingSnapshot,
    RawArtifact,
    SyncRun,
)
from healthcheck.garmin.auth import GarminAuthResult, GarminAuthStatus
from healthcheck.garmin.normalization import garmin_source_identity, normalize_garmin_payload
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.garmin.training import (
    GarminTrainingSync,
    persist_training_payload,
    read_training_acquisitions,
    read_training_evidence,
    validate_training_window,
)
from healthcheck.runtime import prepare_runtime


@pytest.fixture
def training_database(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            yield session, ContentAddressedGarminPayloadStore(paths.root / "artifacts")
    finally:
        engine.dispose()


def _status(source_day: str = "2099-01-02") -> dict:
    return {
        "mostRecentTrainingStatus": {
            "latestTrainingStatusData": {
                "dynamic-provider-device": {
                    "calendarDate": source_day,
                    "deviceId": 811,
                    "trainingStatus": 0,
                    "trainingStatusFeedbackPhrase": "synthetic feedback",
                    "acuteTrainingLoadDTO": {
                        "dailyTrainingLoadAcute": 0,
                        "dailyTrainingLoadChronic": None,
                        "acwrPercent": 88,
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
            "recoveryTime": recovery,
            "primaryActivityTracker": False,
        }
        for stamp, score, recovery in (
            ("2099-01-02T06:00:00", 0, None),
            ("2099-01-02T12:00:00", 76, 0),
        )
    ]


def test_status_uses_provider_date_and_keeps_undated_balance(training_database):
    session, store = training_database
    new, changed, status = persist_training_payload(
        session,
        store,
        surface="training_status",
        requested_date=date(2099, 1, 7),
        payload=_status(),
        received_at=datetime(2099, 1, 7, 8, tzinfo=UTC),
    )
    session.commit()
    assert (new, changed, status) == (2, 0, "ok")
    source = session.scalar(select(GarminSource))
    assert source.device_attributed is False
    records = read_training_evidence(session, garmin_source_id=source.id)
    status_row = next(row for row in records if row["kind"] == "status")
    balance_row = next(row for row in records if row["kind"] == "load_balance")
    assert status_row["source_date"] == "2099-01-02"
    assert balance_row["source_date"] is None
    assert status_row["requested_dates"] == ("2099-01-07",)
    assert status_row["fields"]["dailyTrainingLoadAcute"] == {"state": "value", "value": 0.0}
    assert status_row["fields"]["dailyTrainingLoadChronic"] == {"state": "null", "value": None}
    assert status_row["fields"]["dailyAcuteChronicWorkloadRatio"] == {
        "state": "missing",
        "value": None,
    }
    assert status_row["attribution"] == "associated_device"
    assert status_row["metric_producer"] == "unverified"
    assert status_row["provider_device_key"] == "dynamic-provider-device"


def test_readiness_multiple_snapshots_and_exact_replay(training_database):
    session, store = training_database
    for _ in range(2):
        counts = persist_training_payload(
            session,
            store,
            surface="training_readiness",
            requested_date=date(2099, 1, 4),
            payload=_readiness(),
            received_at=datetime(2099, 1, 4, 13, tzinfo=UTC),
        )
        session.commit()
    assert counts == (0, 0, "ok")
    assert session.scalar(select(func.count()).select_from(GarminTrainingSnapshot)) == 2
    assert session.scalar(select(func.count()).select_from(GarminTrainingAcquisition)) == 1
    source = session.scalar(select(GarminSource))
    rows = read_training_evidence(session, garmin_source_id=source.id)
    assert [row["source_timestamp_utc"] for row in rows] == [
        "2099-01-02T06:00:00+00:00",
        "2099-01-02T12:00:00+00:00",
    ]
    assert rows[0]["fields"]["score"]["value"] == 0
    assert rows[0]["fields"]["recoveryTime"]["state"] == "null"
    assert rows[1]["fields"]["recoveryTime"]["value"] == 0
    assert rows[0]["fields"]["primaryActivityTracker"] == {"state": "value", "value": "false"}
    assert rows[0]["source_local_timestamp"].startswith("2099-01-02T09:00:00")
    assert all(row["requested_dates"] == ("2099-01-04",) for row in rows)


def test_status_request_variation_does_not_backfill_or_duplicate(training_database):
    session, store = training_database
    for requested in (date(2099, 1, 7), date(2099, 1, 8)):
        persist_training_payload(
            session,
            store,
            surface="training_status",
            requested_date=requested,
            payload=_status("2099-01-02"),
            received_at=datetime(2099, 1, 8, tzinfo=UTC),
        )
        session.commit()
    assert session.scalar(select(func.count()).select_from(GarminTrainingSnapshot)) == 2
    assert session.scalar(select(func.count()).select_from(GarminTrainingAcquisition)) == 2
    assert session.scalar(select(func.count()).select_from(GarminPayloadObservation)) == 2
    assert session.scalar(select(func.count()).select_from(GarminSourceRecord)) == 2
    source = session.scalar(select(GarminSource))
    rows = read_training_evidence(session, garmin_source_id=source.id)
    assert all(row["requested_dates"] == ("2099-01-07", "2099-01-08") for row in rows)


def test_changed_status_refresh_preserves_old_raw_evidence(training_database):
    session, store = training_database
    original = _status()
    changed = _status()
    changed["mostRecentTrainingStatus"]["latestTrainingStatusData"]["dynamic-provider-device"][
        "trainingStatus"
    ] = 2
    for requested, payload in ((date(2099, 1, 7), original), (date(2099, 1, 8), changed)):
        persist_training_payload(
            session,
            store,
            surface="training_status",
            requested_date=requested,
            payload=payload,
            received_at=datetime(2099, 1, requested.day, tzinfo=UTC),
        )
        session.commit()
    assert session.scalar(select(func.count()).select_from(GarminRawPayload)) == 2
    assert session.scalar(select(func.count()).select_from(GarminTrainingSnapshot)) == 2
    source = session.scalar(select(GarminSource))
    row = next(
        item
        for item in read_training_evidence(session, garmin_source_id=source.id)
        if item["kind"] == "status"
    )
    assert row["requested_dates"] == ("2099-01-07", "2099-01-08")
    assert row["fields"]["trainingStatus"]["value"] == 2
    artifacts = list(session.scalars(select(RawArtifact)))
    assert any(
        b'"trainingStatus":0' in store.read(item.relative_storage_path) for item in artifacts
    )


def test_empty_invalid_and_private_shape(training_database):
    session, store = training_database
    for payload, expected in (
        (None, "partial"),
        ([], "empty"),
        ({"unsupported": True}, "invalid"),
    ):
        _, _, status = persist_training_payload(
            session,
            store,
            surface="training_readiness",
            requested_date=date(2099, 1, 2),
            payload=payload,
            received_at=datetime(2099, 1, 2, tzinfo=UTC),
        )
        assert status == expected
        session.commit()
    assert session.scalar(select(func.count()).select_from(GarminTrainingSnapshot)) == 0
    source = session.scalar(select(GarminSource))
    states = {
        item["response_state"]
        for item in read_training_acquisitions(session, garmin_source_id=source.id)
    }
    assert states == {"null", "empty", "shape_drift"}
    with pytest.raises(ValueError, match="private or credential-shaped"):
        persist_training_payload(
            session,
            store,
            surface="training_status",
            requested_date=date(2099, 1, 2),
            payload={"accessToken": "synthetic-secret"},
            received_at=datetime(2099, 1, 2, tzinfo=UTC),
        )


def test_activity_listing_fields_keep_recorder_without_producer_claim():
    payload = {
        "activities": [
            {
                "activityId": 7001,
                "calendarDate": "2099-01-02",
                "deviceId": 811,
                "activityTrainingLoad": 0,
                "aerobicTrainingEffect": 2.5,
                "anaerobicTrainingEffect": None,
                "trainingEffectLabel": "synthetic label",
            }
        ]
    }
    result = normalize_garmin_payload(
        payload, stream="activity", source_identity=garmin_source_identity(source_kind="provider")
    )
    assert len(result.records) == 1
    metrics = {metric.metric_code: metric for metric in result.records[0].metrics}
    assert metrics["activityTrainingLoad"].value == 0
    assert metrics["anaerobicTrainingEffect"].state == "null"
    assert metrics["activityRecorderDeviceId"].value == "811"
    assert metrics["activityRecorderDeviceId"].device_evidence is False
    assert metrics["trainingEffectLabel"].value == "synthetic label"


def test_activity_listing_fields_are_readable_with_recorder_attribution(training_database):
    session, store = training_database
    payload = {
        "activities": [
            {
                "activityId": 7001,
                "calendarDate": "2099-01-02",
                "deviceId": 811,
                "activityTrainingLoad": 0,
                "aerobicTrainingEffect": 2.5,
                "trainingEffectLabel": "synthetic label",
            }
        ]
    }
    identity = garmin_source_identity(source_kind="provider")
    normalized = normalize_garmin_payload(payload, stream="activity", source_identity=identity)
    outcome = GarminPersistenceRepository(session, payload_store=store).persist_result(
        normalized, payload=payload, received_at=datetime(2099, 1, 3, tzinfo=UTC)
    )
    session.commit()
    records = read_training_evidence(session, garmin_source_id=outcome.source.id)
    assert len(records) == 1
    assert records[0]["kind"] == "activity"
    assert records[0]["attribution"] == "activity_recorder"
    assert records[0]["provider_device_id"] == "811"
    assert records[0]["metric_producer"] == "unverified"
    assert records[0]["fields"]["activityTrainingLoad"] == {"state": "value", "value": 0.0}


class _Client:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.retry_attempts = 3

    def get_training_status(self, day: str):
        self.calls.append(("status", day))
        return _status("2099-01-02")

    def get_training_readiness(self, day: str):
        self.calls.append(("readiness", day))
        return _readiness()

    def get_activity(self, _activity_id: str):
        raise AssertionError("unproven detail path must not be called")


def test_explicit_training_acquisition_is_bounded_sanitized_and_no_detail(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    client = _Client()
    report = GarminTrainingSync(
        settings,
        client=client,
        auth_result=GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED),
    ).run(start="2099-01-07", end="2099-01-08")
    assert report["status"] == "succeeded"
    assert report["request_count"] == 3
    assert report["status_historical_backfill"] is False
    assert report["inserted_count"] == 4
    assert client.calls == [
        ("status", "2099-01-08"),
        ("readiness", "2099-01-07"),
        ("readiness", "2099-01-08"),
    ]
    public = json.dumps(report)
    assert "2099-" not in public
    assert "dynamic-provider-device" not in public
    assert "synthetic feedback" not in public
    paths = prepare_runtime(settings)
    engine = create_sqlite_engine(paths)
    try:
        with create_session_factory(engine)() as session:
            run = session.scalar(select(SyncRun))
            assert run.stream_code == "garmin_training"
            assert run.status == "succeeded"
            observations = list(session.scalars(select(GarminPayloadObservation)))
            assert len(observations) == 3
            assert all(row.sync_run_id == run.id for row in observations)
    finally:
        engine.dispose()
    with pytest.raises(ValueError, match="fourteen days"):
        validate_training_window("2099-01-01", "2099-01-15")


def test_unavailable_status_method_is_a_failed_surface_not_empty(tmp_path):
    class ReadinessOnly:
        retry_attempts = 2

        def get_training_readiness(self, _day: str):
            return []

    report = GarminTrainingSync(
        Settings(data_dir=tmp_path / "runtime"),
        client=ReadinessOnly(),
        auth_result=GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED),
    ).run(start="2099-01-07", end="2099-01-07")
    assert report["status"] == "partial"
    assert report["request_count"] == 1
    assert report["inserted_count"] == 0
