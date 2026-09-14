"""Synthetic persisted regressions for the R05 sleep metric projection."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from healthcheck.analytics.sleep_metrics import (
    EXCLUDED_SLEEP_METRIC_CODES,
    read_persisted_sleep_metric_projection,
)
from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
from healthcheck.db.models import (
    GarminRecordMetric,
    GoogleRecordMetric,
    GoogleSleepFieldState,
)
from healthcheck.garmin.normalization import normalize_garmin_payload
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.google.contracts import (
    GoogleQueryContext,
    GoogleQueryMode,
    GoogleSourceIdentity,
    GoogleSourceKind,
    GoogleStream,
)
from healthcheck.google.normalization import normalize_google_payload
from healthcheck.google.persistence import GooglePersistenceRepository
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from healthcheck.runtime import prepare_runtime

GARMIN_SLEEP_FIXTURE = Path(__file__).parent / "fixtures" / "garmin" / "sleep.json"
GARMIN_DAILY_FIXTURE = Path(__file__).parent / "fixtures" / "garmin" / "daily_health.json"
FITBIT_SOURCE = "users/me/dataSources/raw:com.google.sleep:com.fitbit.Fitbit:synthetic"


@pytest.fixture
def projection_database(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    try:
        with create_session_factory(engine)() as session:
            yield session, paths
    finally:
        engine.dispose()


def _persist_garmin(session, paths, fixture: Path = GARMIN_SLEEP_FIXTURE):
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    result = normalize_garmin_payload(payload)
    return GarminPersistenceRepository(
        session,
        payload_store=ContentAddressedGarminPayloadStore(paths.root / "garmin-artifacts"),
    ).persist_result(result, payload=fixture.read_bytes())


def _google_identity() -> GoogleSourceIdentity:
    return GoogleSourceIdentity(
        source_kind=GoogleSourceKind.DATA_SOURCE,
        source_instance_id=FITBIT_SOURCE,
        platform="fitbit",
        recording_method="automatic",
    )


def _google_sleep_payload(
    *,
    name: str = "fitbit-night-1",
    sleep_type: str = "STAGES",
    stages: list[dict[str, object]] | None = None,
    stages_status: str | None = None,
    summary_stages: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "main": True,
        "nap": False,
        "manuallyEdited": False,
        "externalId": name,
    }
    if stages_status is not None:
        metadata["stagesStatus"] = stages_status
    component: dict[str, object] = {
        "interval": {
            "startTime": "2099-01-01T22:00:00Z",
            "startUtcOffset": "10800s",
            "endTime": "2099-01-02T05:00:00Z",
            "endUtcOffset": "10800s",
            "civilStartTime": {"date": "2099-01-02", "time": "01:00:00", "zone": "Europe/Moscow"},
            "civilEndTime": {"date": "2099-01-02", "time": "08:00:00", "zone": "Europe/Moscow"},
        },
        "type": sleep_type,
        "stages": stages if stages is not None else [],
        "outOfBedSegments": [],
        "metadata": metadata,
        "summary": {
            "minutesInSleepPeriod": "420",
            "minutesAfterWakeUp": "0",
            "minutesToFallAsleep": "10",
            "minutesAsleep": "410",
            "minutesAwake": "10",
            "stagesSummary": summary_stages if summary_stages is not None else [],
        },
        "updateTime": "2099-01-02T08:04:00Z",
    }
    return {
        "dataPoints": [
            {
                "name": name,
                "sleep": component,
                "dataSource": {
                    "recordingMethod": "AUTOMATIC",
                    "platform": "fitbit",
                    "device": {
                        "formFactor": "WATCH",
                        "manufacturer": "Fitbit",
                        "displayName": "Fitbit Synthetic Watch",
                    },
                },
            }
        ]
    }


def _persist_google(
    session,
    paths,
    *,
    payload: dict[str, object],
    stream: GoogleStream = GoogleStream.SLEEP,
    name: str = "fitbit-night-1",
):
    if stream is not GoogleStream.SLEEP:
        component_name = {
            GoogleStream.DAILY_RESTING_HR: "dailyRestingHeartRate",
            GoogleStream.DAILY_SPO2: "dailyOxygenSaturation",
        }[stream]
        payload = {
            "dataPoints": [
                {
                    "name": name,
                    component_name: payload,
                    "dataSource": {
                        "recordingMethod": "AUTOMATIC",
                        "platform": "fitbit",
                        "device": {
                            "formFactor": "WATCH",
                            "manufacturer": "Fitbit",
                            "displayName": "Fitbit Synthetic Watch",
                        },
                    },
                }
            ]
        }
    result = normalize_google_payload(
        payload,
        stream=stream,
        query=GoogleQueryContext(query_mode=GoogleQueryMode.LIST),
        source_identity=_google_identity(),
    )
    return GooglePersistenceRepository(
        session,
        payload_store=ContentAddressedGooglePayloadStore(paths.root / "google-artifacts"),
    ).persist_result(
        result,
        payload=payload,
        received_at=datetime(2099, 1, 2, tzinfo=UTC),
    )


def _metric(result, code: str):
    rows = [item for item in result.projections if item.metric_code == code]
    assert len(rows) == 1
    return rows[0]


def _stage(
    start: str,
    end: str,
    stage_type: str,
) -> dict[str, object]:
    return {
        "startTime": start,
        "startUtcOffset": "10800s",
        "endTime": end,
        "endUtcOffset": "10800s",
        "type": stage_type,
    }


def test_projection_uses_common_units_and_keeps_metric_eligibility_independent(
    projection_database,
):
    session, paths = projection_database
    _persist_garmin(session, paths)
    _persist_google(session, paths, payload=_google_sleep_payload())
    session.commit()

    result = read_persisted_sleep_metric_projection(session)
    duration = _metric(result, "sleep_duration_asleep_seconds")
    stages = _metric(result, "sleep_stage_light_seconds")
    waso = _metric(result, "sleep_awake_waso_seconds")
    start = _metric(result, "sleep_start_at")
    end = _metric(result, "sleep_end_at")

    assert duration.status == "comparable"
    assert duration.garmin.value == 28800
    assert duration.google.value == 24600
    assert duration.difference == -4200  # google - garmin
    assert stages.status == "unavailable"
    assert stages.google.reason == "typed_stage_collection_required"
    assert waso.status == "unavailable"
    assert waso.google.reason == "typed_stage_collection_required"
    assert start.status == "unavailable"
    assert start.garmin.reason == "timing_precision_unavailable"
    assert end.status == "comparable"
    assert end.difference == -6300
    assert result.excluded_metric_codes == EXCLUDED_SLEEP_METRIC_CODES
    assert all(item.manifest_hash for item in result.frozen_inputs)

    replay = read_persisted_sleep_metric_projection(session)
    assert result.result_hash == replay.result_hash
    assert result.as_dict() == replay.as_dict()


def test_partial_garmin_stages_do_not_erase_duration_or_create_dependent_metrics(
    projection_database,
):
    session, paths = projection_database
    _persist_garmin(session, paths)
    _persist_google(session, paths, payload=_google_sleep_payload())
    session.commit()

    stage_row = session.scalar(
        select(GarminRecordMetric).where(GarminRecordMetric.metric_code == "sleep_stages")
    )
    assert stage_row is not None
    stage_row.reason = "partial_collection"
    session.commit()

    result = read_persisted_sleep_metric_projection(session)
    assert _metric(result, "sleep_duration_asleep_seconds").status == "comparable"
    assert _metric(result, "sleep_stage_deep_seconds").garmin.reason == "stage_collection_partial"
    assert _metric(result, "sleep_time_in_bed_seconds").garmin.reason == "stage_collection_partial"
    assert _metric(result, "sleep_end_at").garmin.reason == "stage_collection_partial"


def test_explicit_zero_stays_value_and_missing_stays_missing(projection_database):
    session, paths = projection_database
    _persist_garmin(session, paths)
    _persist_google(session, paths, payload=_google_sleep_payload())
    session.commit()

    garmin_duration = session.scalar(
        select(GarminRecordMetric).where(
            GarminRecordMetric.metric_code == "sleep_duration_seconds"
        )
    )
    google_duration = session.scalar(
        select(GoogleRecordMetric).where(
            GoogleRecordMetric.metric_code == "sleep_summary_minutes_asleep"
        )
    )
    assert garmin_duration is not None
    assert google_duration is not None
    garmin_duration.value_number = 0
    google_duration.value_number = 0
    session.commit()

    zero_result = read_persisted_sleep_metric_projection(session)
    zero = _metric(zero_result, "sleep_duration_asleep_seconds")
    assert zero.status == "comparable"
    assert zero.garmin.state == "value"
    assert zero.google.state == "value"
    assert zero.garmin.is_zero is True
    assert zero.google.is_zero is True
    assert zero.difference == 0

    google_duration.state = "missing"
    google_duration.value_number = None
    google_duration.value_text = None
    session.commit()

    missing_result = read_persisted_sleep_metric_projection(session)
    missing = _metric(missing_result, "sleep_duration_asleep_seconds")
    assert missing.status == "unavailable"
    assert missing.garmin.state == "value"
    assert missing.google.state == "missing"
    assert missing.google.value is None
    assert missing.google.is_zero is False


def test_overlapping_typed_intervals_fail_only_stage_dependent_metrics(projection_database):
    session, paths = projection_database
    _persist_garmin(session, paths)
    _persist_google(
        session,
        paths,
        payload=_google_sleep_payload(
            stages_status="SUCCEEDED",
            stages=[
                _stage("2099-01-01T22:00:00Z", "2099-01-01T23:00:00Z", "LIGHT"),
                _stage("2099-01-01T22:30:00Z", "2099-01-01T23:30:00Z", "DEEP"),
            ],
        ),
    )
    session.commit()

    result = read_persisted_sleep_metric_projection(session)
    assert _metric(result, "sleep_duration_asleep_seconds").status == "comparable"
    assert _metric(result, "sleep_time_in_bed_seconds").status == "comparable"
    light = _metric(result, "sleep_stage_light_seconds")
    assert light.status == "unavailable"
    assert light.google.reason == "stage_interval_overlap"


def test_summary_stage_evidence_fails_closed_and_classic_never_uses_stage_metrics(
    projection_database,
):
    session, paths = projection_database
    _persist_garmin(session, paths)
    _persist_google(
        session,
        paths,
        payload=_google_sleep_payload(
            summary_stages=[
                {"type": "LIGHT", "minutes": "60", "count": "1"},
                {"type": "DEEP", "minutes": "30", "count": "1"},
                {"type": "AWAKE", "minutes": "5", "count": "1"},
            ],
        ),
    )
    session.commit()

    summary_result = read_persisted_sleep_metric_projection(session)
    light = _metric(summary_result, "sleep_stage_light_seconds")
    assert light.status == "unavailable"
    assert light.google.value == 3600
    assert light.google.eligible is False
    assert light.google.reason == "typed_stage_collection_required"
    assert light.google.comparison_basis == "summary_only"
    assert light.google.evidence.metric_row_ids

    waso = _metric(summary_result, "sleep_awake_waso_seconds")
    assert waso.status == "unavailable"
    assert waso.google.value == 300
    assert waso.google.eligible is False
    assert waso.google.reason == "typed_stage_collection_required"

    sleep_type = session.scalar(
        select(GoogleRecordMetric).where(GoogleRecordMetric.metric_code == "sleep_type")
    )
    assert sleep_type is not None
    sleep_type.value_text = "CLASSIC"
    session.commit()

    classic_result = read_persisted_sleep_metric_projection(session)
    duration = _metric(classic_result, "sleep_duration_asleep_seconds")
    stage = _metric(classic_result, "sleep_stage_light_seconds")
    assert duration.status == "comparable"
    assert duration.variant == "CLASSIC"
    assert stage.status == "excluded"
    assert stage.reason == "classic_sleep_excludes_stage_metric"


def test_non_succeeded_google_stage_status_fails_closed_without_breaking_independent_metrics(
    projection_database,
):
    session, paths = projection_database
    _persist_garmin(session, paths)
    _persist_google(
        session,
        paths,
        payload=_google_sleep_payload(
            stages_status="PROCESSING",
            stages=[
                _stage("2099-01-01T22:00:00Z", "2099-01-01T23:00:00Z", "LIGHT"),
            ],
            summary_stages=[{"type": "LIGHT", "minutes": "60", "count": "1"}],
        ),
    )
    session.commit()

    result = read_persisted_sleep_metric_projection(session)
    light = _metric(result, "sleep_stage_light_seconds")
    assert light.status == "unavailable"
    assert light.google.value == 3600
    assert light.google.eligible is False
    assert light.google.reason == "stages_status_not_succeeded"
    assert light.google.comparison_basis == "summary_only"
    assert _metric(result, "sleep_duration_asleep_seconds").status == "comparable"
    assert _metric(result, "sleep_time_in_bed_seconds").status == "comparable"


def test_auxiliary_metrics_require_their_own_persisted_daily_rows(projection_database):
    session, paths = projection_database
    _persist_garmin(session, paths)
    _persist_garmin(session, paths, fixture=GARMIN_DAILY_FIXTURE)
    _persist_google(session, paths, payload=_google_sleep_payload())
    _persist_google(
        session,
        paths,
        stream=GoogleStream.DAILY_RESTING_HR,
        payload={
            "date": {"year": 2099, "month": 1, "day": 2},
            "dailyRestingHeartRateMetadata": {"calculationMethod": "WITH_SLEEP"},
            "beatsPerMinute": "55",
        },
    )
    _persist_google(
        session,
        paths,
        stream=GoogleStream.DAILY_SPO2,
        payload={
            "date": {"year": 2099, "month": 1, "day": 2},
            "averagePercentage": "96",
            "lowerBoundPercentage": "95",
            "upperBoundPercentage": "97",
            "standardDeviationPercentage": "1",
        },
    )
    session.commit()

    result = read_persisted_sleep_metric_projection(session)
    rhr = _metric(result, "resting_heart_rate_bpm")
    spo2 = _metric(result, "spo2_daily_average_pct")
    assert rhr.status == "comparable"
    assert rhr.garmin.value == 52
    assert rhr.google.value == 55
    assert spo2.status == "unavailable"
    assert spo2.garmin.value is None
    assert spo2.google.value == 96


def test_google_partial_stage_state_is_not_treated_as_empty_or_zero(projection_database):
    session, paths = projection_database
    _persist_garmin(session, paths)
    _persist_google(session, paths, payload=_google_sleep_payload())
    session.commit()

    field_state = session.scalar(select(GoogleSleepFieldState))
    assert field_state is not None
    field_state.sleep_stages_state = "invalid"
    session.commit()

    result = read_persisted_sleep_metric_projection(session)
    light = _metric(result, "sleep_stage_light_seconds")
    waso = _metric(result, "sleep_awake_waso_seconds")
    assert light.google.state == "invalid"
    assert light.google.reason == "stage_collection_invalid"
    assert waso.google.state == "invalid"
    assert waso.google.value is None


def test_manifest_contains_no_raw_payload_body_and_freezes_interval_ids(projection_database):
    session, paths = projection_database
    _persist_garmin(session, paths)
    _persist_google(
        session,
        paths,
        payload=_google_sleep_payload(
            stages_status="SUCCEEDED",
            stages=[_stage("2099-01-01T22:00:00Z", "2099-01-01T23:00:00Z", "LIGHT")],
        ),
    )
    session.commit()

    result = read_persisted_sleep_metric_projection(session)
    light = _metric(result, "sleep_stage_light_seconds")
    manifest = light.manifest.as_dict()
    text = json.dumps(manifest, sort_keys=True)
    assert '"dataPoints":' not in text
    assert "raw_payload_body" not in text
    assert light.google.evidence.interval_ids
    assert light.google.evidence.interval_snapshots
    assert light.google.evidence.interval_snapshots[0]["start_at_utc"]
    assert light.google.evidence.content_hash
    assert light.google.evidence.observation_key
