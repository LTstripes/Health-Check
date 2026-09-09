"""Synthetic regressions for R03-04 Garmin query service and owner dashboard (#73)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from healthcheck.analytics.garmin_activity_comparison import (
    R03_02_ALGORITHM,
    compute_garmin_activity_comparison,
)
from healthcheck.analytics.garmin_baselines import (
    R03_01_ALGORITHM,
    R03_01_RULE_VERSION,
    compute_garmin_scalar_series,
)
from healthcheck.analytics.garmin_lagged_associations import (
    R03_03_ALGORITHM,
    compute_garmin_lagged_associations,
)
from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.models import GarminSource, GarminSourceRecord
from healthcheck.garmin.normalization import normalize_garmin_payload
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.runtime import prepare_runtime
from healthcheck.web.garmin_query import PROVIDER_NATIVE_SCORE_LABELS, GarminQueryService
from healthcheck.web.ui_app import create_ui_app


def _ui(tmp_path, **settings_values):
    settings = Settings(data_dir=tmp_path / "runtime", **settings_values)
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())
    return app, settings, paths


def _stress_payload(
    day: str,
    *,
    avg: int | float | None = 25,
    maximum: int | float | None = 80,
    sample: int | float | None = 40,
    spo2_avg: int | float | None = 98,
    spo2_trail: int | float | None = 97,
    spo2_sample: int | float | None = 96,
    fixture_suffix: str = "",
    device: dict | None = None,
    extra_payload: dict | None = None,
) -> dict:
    payload: dict = {
        "calendarDate": day,
        "heartRate": 70,
        "bodyBattery": 50,
        "respiration": 14,
    }
    if avg is not None:
        payload["avgStressLevel"] = avg
    if maximum is not None:
        payload["maxStressLevel"] = maximum
    if sample is not None:
        payload["stress"] = sample
    if spo2_avg is not None:
        payload["averageSpO2"] = spo2_avg
    if spo2_trail is not None:
        payload["lastSevenDaysAvgSpO2"] = spo2_trail
    if spo2_sample is not None:
        payload["spo2"] = spo2_sample
    if extra_payload:
        payload.update(extra_payload)
    return {
        "fixture_contract_version": "r02-garmin-capability-fixture-v1",
        "fixture_id": f"synthetic-r03-04-{day}{fixture_suffix}",
        "source_kind": "synthetic",
        "provider_code": "garmin_connect",
        "stream_code": "intraday",
        "device": device
        or {
            "attributed": True,
            "code": "garmin_vivoactive_5",
            "model": "Vivoactive 5",
        },
        "payload": payload,
    }


def _activity_payload(
    *,
    activity_id: str,
    activity_type: str = "cycling",
    day: str = "2099-01-02",
    duration: int | float | None = 3600,
    training_effect: int | float | None = 2.3,
    training_load: int | float | None = 42,
    device: dict | None = None,
) -> dict:
    activity: dict = {
        "activityId": activity_id,
        "activityType": {"typeKey": activity_type},
        "startTimeGMT": f"{day}T08:00:00Z",
        "duration": duration,
        "distance": 21000,
        "averageSpeed": 5.83,
        "averageHR": 128,
        "aerobicTrainingEffect": training_effect,
        "activityTrainingLoad": training_load,
    }
    return {
        "fixture_contract_version": "r02-garmin-capability-fixture-v1",
        "fixture_id": f"synthetic-r03-04-activity-{activity_id}",
        "source_kind": "synthetic",
        "provider_code": "garmin_connect",
        "stream_code": "activity",
        "device": device
        or {
            "attributed": True,
            "code": "garmin_vivoactive_5",
            "model": "Vivoactive 5",
        },
        "client_methods": ["get_activities_by_date"],
        "payload_fields": {
            "activities": "activities",
            "training_effect": "activities.0.aerobicTrainingEffect",
            "acute_training_load": "activities.0.activityTrainingLoad",
        },
        "payload": {"activities": [activity]},
    }


def _persist(session, store, payload: dict, *, received_at: datetime | None = None):
    result = normalize_garmin_payload(payload)
    outcome = GarminPersistenceRepository(session, payload_store=store).persist_result(
        result,
        payload=payload,
        received_at=received_at or datetime(2099, 1, 1, 12, tzinfo=UTC),
        source_contract_version=payload.get("fixture_contract_version"),
    )
    session.flush()
    return outcome


def _seed_scalar_days(session, store, *, days: int = 8, start: date = date(2099, 1, 1)):
    source_id = None
    for index in range(days):
        day = (start + timedelta(days=index)).isoformat()
        outcome = _persist(
            session,
            store,
            _stress_payload(day, avg=20 + index, spo2_avg=95 + (index % 3)),
            received_at=datetime(2099, 1, 1, 12, index, tzinfo=UTC),
        )
        source_id = outcome.records[0].garmin_source_id
    session.commit()
    assert source_id is not None
    return source_id


def _assert_no_secrets(payload) -> None:
    blob = json.dumps(payload, default=str).lower()
    for banned in (
        '"authorization"',
        "refresh_token",
        "access_token",
        "session_token",
        "private_key",
        '"password"',
        '"gps"',
        "payload_body",
        '"raw_payload"',
        "payload_bytes",
    ):
        assert banned not in blob
    # Evidence may cite raw_payload_id + content_hash; never a payload body.


def test_empty_garmin_dashboard_honest_no_data(tmp_path):
    app, _settings, _paths = _ui(tmp_path)
    with TestClient(app) as client:
        page = client.get("/garmin")
        assert page.status_code == 200
        assert "no data" in page.text.lower() or "no_garmin_sources" in page.text
        assert "0 kg" not in page.text
        assert "Readiness" not in page.text
        assert "Recovery Score" not in page.text
        sources = client.get("/api/garmin/sources").json()
        assert sources["sources"] == []
        dashboard = client.get("/api/garmin/dashboard").json()
        assert dashboard["source_selection"]["status"] == "no_data"
        assert dashboard["series"] is None
        assert dashboard["activities"] == []
        assert "Garmin dashboard" in page.text
        weight = client.get("/")
        assert weight.status_code == 200
        assert "Weight and body composition" in weight.text


def test_single_source_scalar_delegates_r03_01_and_preserves_hash(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            source_id = _seed_scalar_days(session, store, days=8)
            direct = compute_garmin_scalar_series(
                session,
                metric_code="stress_daily_average",
                start_date=date(2099, 1, 1),
                end_date=date(2099, 1, 8),
                garmin_source_id=source_id,
            )
            service = GarminQueryService(session)
            via_service = service.scalar_series(
                garmin_source_id=source_id,
                metric_code="stress_daily_average",
                start_date=date(2099, 1, 1),
                end_date=date(2099, 1, 8),
            )
            assert via_service["algorithm"] == R03_01_ALGORITHM
            assert via_service["rule_version"] == R03_01_RULE_VERSION
            assert via_service["result_hash"] == direct.result_hash
            assert via_service["metric_definition"]["metric_code"] == "stress_daily_average"
            assert via_service["garmin_source_id"] == source_id
            assert via_service["availability"]["zero_count"] == direct.availability.zero_count
    finally:
        engine.dispose()

    with TestClient(app) as client:
        first = client.get(
            "/api/garmin/series",
            params={
                "garmin_source_id": source_id,
                "metric_code": "stress_daily_average",
                "start_date": "2099-01-01",
                "end_date": "2099-01-08",
            },
        )
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["result_hash"] == direct.result_hash
        second = client.get(
            "/api/garmin/series",
            params={
                "garmin_source_id": source_id,
                "metric_code": "stress_daily_average",
                "start_date": "2099-01-01",
                "end_date": "2099-01-08",
            },
        )
        assert second.status_code == 200
        assert second.json()["result_hash"] == body["result_hash"]
        _assert_no_secrets(body)

        # GET idempotent: no mutation of source/record counts.
        engine = create_sqlite_engine(paths)
        try:
            with session_scope(engine) as session:
                sources = session.scalar(select(func.count(GarminSource.id)))
                records = session.scalar(select(func.count(GarminSourceRecord.id)))
                assert sources == 1
                assert records >= 8
        finally:
            engine.dispose()

        page = client.get("/garmin")
        assert page.status_code == 200
        assert source_id[:8] in page.text
        assert "provider-native" in page.text.lower() or "Provider sleep score" in page.text


def test_invalid_queries_fail_sanitized(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            source_id = _seed_scalar_days(session, store, days=3)
    finally:
        engine.dispose()

    with TestClient(app) as client:
        unknown = client.get(
            "/api/garmin/series",
            params={
                "garmin_source_id": source_id,
                "metric_code": "not_a_reviewed_metric",
                "start_date": "2099-01-01",
                "end_date": "2099-01-03",
            },
        )
        assert unknown.status_code == 400
        assert unknown.json()["code"] == "unknown_metric_code"
        assert "Traceback" not in unknown.text

        bad_window = client.get(
            "/api/garmin/series",
            params={
                "garmin_source_id": source_id,
                "metric_code": "stress_daily_average",
                "start_date": "2099-01-10",
                "end_date": "2099-01-01",
            },
        )
        assert bad_window.status_code == 400
        assert bad_window.json()["code"] == "invalid_date_window"

        bad_lag = client.get(
            "/api/garmin/lagged-association",
            params={
                "garmin_source_id": source_id,
                "x_metric_code": "stress_daily_average",
                "y_metric_code": "spo2_daily_average",
                "start_date": "2099-01-01",
                "end_date": "2099-01-03",
                "lag_days": "0,99",
            },
        )
        assert bad_lag.status_code == 400
        assert bad_lag.json()["code"] in {"lag_out_of_range", "invalid_lag_days"}

        missing_source = client.get(
            "/api/garmin/series",
            params={
                "garmin_source_id": "does-not-exist",
                "metric_code": "stress_daily_average",
                "start_date": "2099-01-01",
                "end_date": "2099-01-03",
            },
        )
        assert missing_source.status_code == 400
        assert missing_source.json()["code"] == "unknown_garmin_source_id"


def test_multiple_sources_require_explicit_selection(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            first = _persist(
                session,
                store,
                _stress_payload("2099-02-01", fixture_suffix="-a"),
            )
            second_payload = _stress_payload(
                "2099-02-01",
                fixture_suffix="-b",
                device={"attributed": False},
            )
            second = _persist(
                session,
                store,
                second_payload,
                received_at=datetime(2099, 2, 1, 13, tzinfo=UTC),
            )
            session.commit()
            first_id = first.records[0].garmin_source_id
            second_id = second.records[0].garmin_source_id
            assert first_id != second_id
    finally:
        engine.dispose()

    with TestClient(app) as client:
        dashboard = client.get("/api/garmin/dashboard").json()
        assert dashboard["source_selection"]["status"] == "require_selection"
        assert dashboard["series"] is None
        assert len(dashboard["source_selection"]["sources"]) == 2
        page = client.get("/garmin")
        assert "select a source" in page.text.lower()
        chosen = client.get(
            "/api/garmin/dashboard",
            params={"garmin_source_id": first_id, "metric_code": "stress_daily_average"},
        )
        assert chosen.status_code == 200
        body = chosen.json()
        assert body["source_selection"]["selected_source_id"] == first_id
        assert body["series"] is not None
        assert body["series"]["garmin_source_id"] == first_id


def test_activity_comparison_and_native_score_labels(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            left = _persist(
                session,
                store,
                _activity_payload(activity_id="cmp-a", training_effect=2.0, training_load=40),
            )
            right = _persist(
                session,
                store,
                _activity_payload(
                    activity_id="cmp-b",
                    training_effect=3.0,
                    training_load=55,
                    activity_type="running",
                ),
                received_at=datetime(2099, 1, 2, tzinfo=UTC),
            )
            session.commit()
            source_id = left.records[0].garmin_source_id
            left_id = left.records[0].id
            right_id = right.records[0].id
            direct = compute_garmin_activity_comparison(
                session,
                garmin_source_id=source_id,
                activity_record_ids=[left_id, right_id],
                reference_activity_id=left_id,
            )
    finally:
        engine.dispose()

    with TestClient(app) as client:
        response = client.get(
            "/api/garmin/activity-comparison",
            params={
                "garmin_source_id": source_id,
                "activity_record_ids": f"{left_id},{right_id}",
                "reference_activity_id": left_id,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["algorithm"] == R03_02_ALGORITHM
        assert body["result_hash"] == direct.result_hash
        assert body["coverage"]["not_comparable_pair_count"] >= 0
        assert "training_effect" in body["native_score_labels"]
        assert "acute_training_load" in body["native_score_labels"]
        wording = body.get("wording", "").lower()
        assert "not daily readiness" in json.dumps(body["native_score_labels"]).lower()
        assert "better/worse" in wording or "not better" in wording or "coaching labels" in wording
        assert body["native_score_labels"]["training_effect"]["display_name"] != "Readiness"
        assert "p_value" not in body
        assert any(
            block["same_activity_type"] is False for block in body["comparisons"]
        )
        metrics = client.get("/api/garmin/metrics").json()
        for code in ("sleep_score", "training_effect", "acute_training_load"):
            assert code in metrics["native_score_labels"]
            assert metrics["native_score_labels"][code]["kind"] == "provider_native"
            assert code in PROVIDER_NATIVE_SCORE_LABELS
        page = client.get(f"/garmin?garmin_source_id={source_id}")
        assert "Provider training effect" in page.text
        assert "Provider acute training load" in page.text
        assert "Provider sleep score" in page.text
        assert "Training Readiness" not in page.text
        assert "VO2Max" not in page.text
        _assert_no_secrets(body)

        bad_activity = client.get(
            "/api/garmin/activity-comparison",
            params={
                "garmin_source_id": source_id,
                "activity_record_ids": left_id,
                "reference_activity_id": left_id,
            },
        )
        assert bad_activity.status_code == 400
        assert bad_activity.json()["code"] in {
            "selection_bounds_violated",
            "selection_below_minimum",
        }


def test_lagged_association_delegates_without_significance_language(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            source_id = _seed_scalar_days(session, store, days=10)
            direct = compute_garmin_lagged_associations(
                session,
                garmin_source_id=source_id,
                x_metric_code="stress_daily_average",
                y_metric_code="spo2_daily_average",
                start_date=date(2099, 1, 1),
                end_date=date(2099, 1, 10),
                lag_days=(0, 1, 2),
            )
    finally:
        engine.dispose()

    with TestClient(app) as client:
        response = client.get(
            "/api/garmin/lagged-association",
            params={
                "garmin_source_id": source_id,
                "x_metric_code": "stress_daily_average",
                "y_metric_code": "spo2_daily_average",
                "start_date": "2099-01-01",
                "end_date": "2099-01-10",
                "lag_days": "0,1,2",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["algorithm"] == R03_03_ALGORITHM
        assert body["result_hash"] == direct.result_hash
        assert "p_value" not in body
        assert "best_lag" not in body
        assert all("p_value" not in lag for lag in body["lags"])
        assert "exploratory association only" in body["wording"].lower()
        assert "no p-values, significance" in body["wording"].lower()
        _assert_no_secrets(body)


def test_local_only_timestamps_not_invented_as_utc(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            payload = _stress_payload(
                "2099-03-01",
                fixture_suffix="-local",
                extra_payload={"startTimeLocal": "2099-03-01T06:30:00"},
            )
            # Remove any GMT stamp so temporal stays local-only when present.
            payload["payload"].pop("startTimeGMT", None)
            outcome = _persist(session, store, payload)
            session.commit()
            source_id = outcome.records[0].garmin_source_id
    finally:
        engine.dispose()

    with TestClient(app) as client:
        response = client.get(
            "/api/garmin/series",
            params={
                "garmin_source_id": source_id,
                "metric_code": "stress_daily_average",
                "start_date": "2099-03-01",
                "end_date": "2099-03-01",
            },
        )
        assert response.status_code == 200, response.text
        points = response.json()["points"]
        assert points
        for point in points:
            if point.get("zone_policy") in {"local_unknown_zone", "local_date_only"}:
                assert point.get("measured_at_utc") in (None, "")
            # Never coerce missing UTC into a fabricated Z timestamp in presentation.
            if point.get("measured_at_utc") in (None, ""):
                assert "Z" not in json.dumps(point.get("local_wall_time"))


def test_unavailable_distinct_from_zero_and_weight_unaffected(tmp_path):
    app, _settings, paths = _ui(tmp_path)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            # Explicit zero stress average.
            _persist(
                session,
                store,
                _stress_payload("2099-04-01", avg=0, fixture_suffix="-zero"),
            )
            # Missing average (key absent) on another day.
            _persist(
                session,
                store,
                _stress_payload("2099-04-02", avg=None, fixture_suffix="-missing"),
                received_at=datetime(2099, 4, 2, tzinfo=UTC),
            )
            session.commit()
            source_id = session.scalars(select(GarminSource)).one().id
    finally:
        engine.dispose()

    with TestClient(app) as client:
        body = client.get(
            "/api/garmin/series",
            params={
                "garmin_source_id": source_id,
                "metric_code": "stress_daily_average",
                "start_date": "2099-04-01",
                "end_date": "2099-04-02",
            },
        ).json()
        statuses = {point["analytic_date"]: point for point in body["points"]}
        assert statuses["2099-04-01"]["status"] == "zero"
        assert statuses["2099-04-01"]["value"] == 0
        assert statuses["2099-04-01"]["is_zero"] is True
        assert statuses["2099-04-02"]["status"] in {"missing", "not_computable", "null"}
        assert statuses["2099-04-02"]["value"] is None
        assert body["availability"]["zero_count"] >= 1
        assert body["availability"]["missing_count"] + body["availability"][
            "not_computable_count"
        ] + body["availability"]["null_count"] >= 1

        weight_series = client.get("/api/weight/series")
        assert weight_series.status_code == 200
        assert weight_series.json()["raw_points"] == []
        weight_page = client.get("/")
        assert weight_page.status_code == 200
        assert "Garmin dashboard" in weight_page.text
        assert "Weight dashboard" in weight_page.text


def test_nav_and_no_network_side_effects(tmp_path, monkeypatch):
    app, _settings, paths = _ui(tmp_path)
    calls: list[str] = []

    def _blocked(*_args, **_kwargs):
        calls.append("network")
        raise AssertionError("network must not be used by Garmin dashboard/API")

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
            _seed_scalar_days(session, store, days=5)
    finally:
        engine.dispose()

    with TestClient(app) as client:
        assert client.get("/garmin").status_code == 200
        assert client.get("/api/garmin/sources").status_code == 200
        assert client.get("/api/garmin/metrics").status_code == 200
        assert client.get("/api/garmin/dashboard").status_code == 200
        assert client.get("/").status_code == 200
    assert calls == []
