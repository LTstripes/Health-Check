"""Offline R02 Garmin normalization and idempotency contract tests."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from healthcheck.garmin.contracts import load_synthetic_fixture
from healthcheck.garmin.normalization import (
    NORMALIZATION_CONTRACT_VERSION,
    GarminFieldState,
    GarminParseStatus,
    GarminTemporalPrecision,
    garmin_source_identity,
    normalize_garmin_payload,
    parse_garmin_time,
    stable_garmin_idempotency_key,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "garmin"


def fixture(name: str):
    return load_synthetic_fixture(FIXTURE_ROOT / f"{name}.json")


def raw_fixture(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / f"{name}.json").read_text(encoding="utf-8"))


def test_sleep_fixture_projects_typed_values_and_date_only_semantics() -> None:
    result = normalize_garmin_payload(fixture("sleep"))

    assert result.ok
    assert result.contract_version == NORMALIZATION_CONTRACT_VERSION
    assert result.source is not None
    assert result.source.device_attributed is True
    (record,) = result.records
    assert record.temporal.precision is GarminTemporalPrecision.DATE_ONLY
    assert record.temporal.local_date == date(2099, 1, 2)
    assert record.temporal.measured_at_utc is None
    assert record.metric("sleep_score").value == 82
    assert record.metric("sleep_duration_seconds").value == 28800
    stages = record.metric("sleep_stages").collection
    assert len(stages) == 2
    assert stages[0].start.measured_at_utc == datetime(2099, 1, 1, 21, 30, tzinfo=UTC)
    assert json.dumps(result.as_dict(), sort_keys=True)


def test_aware_and_naive_timestamps_keep_distinct_contracts() -> None:
    aware = parse_garmin_time("2099-01-02T08:00:00+03:00")
    naive = parse_garmin_time("2099-01-02T08:00:00")
    date_only = parse_garmin_time("2099-01-02")

    assert aware.precision is GarminTemporalPrecision.UTC_INSTANT
    assert aware.measured_at_utc == datetime(2099, 1, 2, 5, tzinfo=UTC)
    assert aware.local_date == date(2099, 1, 2)
    assert aware.local_wall_time == "2099-01-02T08:00:00"
    assert aware.source_local_timestamp == "2099-01-02T08:00:00+03:00"
    assert aware.source_utc_offset_minutes == 180
    assert aware.source_timezone is None
    assert naive.precision is GarminTemporalPrecision.LOCAL_WALL_TIME
    assert naive.measured_at_utc is None
    assert naive.local_wall_time == "2099-01-02T08:00:00"
    assert naive.local_date == date(2099, 1, 2)
    assert date_only.precision is GarminTemporalPrecision.DATE_ONLY
    assert date_only.local_date == date(2099, 1, 2)
    assert date_only.measured_at_utc is None


def test_paired_local_and_gmt_fields_preserve_both_temporal_semantics() -> None:
    result = normalize_garmin_payload(
        {
            "calendarDate": "2099-01-02",
            "startTimeLocal": "2099-01-02T11:00:00+03:00",
            "startTimeGMT": "2099-01-02T08:00:00",
            "timeZone": "Europe/Moscow",
            "restingHeartRate": 52,
            "hrvStatus": {"weeklyAverage": 55},
            "maxMetrics": {"vo2MaxRunning": 44.2},
            "trainingReadiness": 80,
            "trainingStatus": "productive",
        },
        stream="daily_health",
    )

    assert result.ok
    (record,) = result.records
    temporal = record.temporal
    assert temporal.precision is GarminTemporalPrecision.UTC_INSTANT
    assert temporal.measured_at_utc == datetime(2099, 1, 2, 8, tzinfo=UTC)
    assert temporal.local_wall_time == "2099-01-02T11:00:00"
    assert temporal.source_local_timestamp == "2099-01-02T11:00:00+03:00"
    assert temporal.source_utc_offset_minutes == 180
    assert temporal.source_timezone == "Europe/Moscow"
    assert temporal.source_local_field == "payload.startTimeLocal"
    assert temporal.source_utc_field == "payload.startTimeGMT"
    assert temporal.source_field == "payload.startTimeGMT"


def test_naive_gmt_field_is_utc_by_field_semantics() -> None:
    parsed = parse_garmin_time("2099-01-02T08:00:00", source_field="startTimeGMT")

    assert parsed.precision is GarminTemporalPrecision.UTC_INSTANT
    assert parsed.measured_at_utc == datetime(2099, 1, 2, 8, tzinfo=UTC)
    assert parsed.local_wall_time is None
    assert parsed.local_date == date(2099, 1, 2)
    assert parsed.source_local_timestamp is None
    assert parsed.source_utc_field == "startTimeGMT"


def test_naive_local_only_field_has_no_invented_timezone() -> None:
    parsed = parse_garmin_time("2099-01-02T08:00:00", source_field="startTimeLocal")

    assert parsed.precision is GarminTemporalPrecision.LOCAL_WALL_TIME
    assert parsed.measured_at_utc is None
    assert parsed.local_wall_time == "2099-01-02T08:00:00"
    assert parsed.local_date == date(2099, 1, 2)
    assert parsed.source_local_timestamp == "2099-01-02T08:00:00"
    assert parsed.source_utc_offset_minutes is None
    assert parsed.source_timezone is None
    assert parsed.source_local_field == "startTimeLocal"


def test_activity_fixture_normalizes_records_and_stable_record_key() -> None:
    first_payload = raw_fixture("activity")
    second_payload = raw_fixture("activity")
    second_payload["fixture_id"] = "synthetic-vivoactive-5-cycling-replayed"
    second_payload["payload"]["activities"][0]["durationSeconds"] = 9999

    first = normalize_garmin_payload(first_payload)
    second = normalize_garmin_payload(second_payload)

    assert first.ok and second.ok
    assert first.idempotency_keys == second.idempotency_keys
    (record,) = first.records
    assert record.record_id == "synthetic-activity-001"
    assert record.activity_type == "cycling"
    assert record.temporal.measured_at_utc == datetime(2099, 1, 2, 8, tzinfo=UTC)
    assert record.metric("duration_seconds").value == 3600
    assert record.metric("distance_meters").value == 21000
    assert record.metric("power_watts").state is GarminFieldState.NULL
    assert record.metric("training_effect").device_evidence is False


def test_unattributed_account_value_is_not_device_evidence() -> None:
    result = normalize_garmin_payload(fixture("unattributed_account_value"))

    assert result.source is not None
    assert result.source.device_attributed is False
    (record,) = result.records
    training_status = record.metric("training_status")
    assert training_status is not None
    assert training_status.value == "productive"
    assert training_status.device_evidence is False
    assert record.metric("training_status").source_device_attributed is False
    assert training_status.capability_status.value == "not_device_produced"


def test_missing_null_and_zero_are_three_distinct_states() -> None:
    present = raw_fixture("daily_health")
    zero = raw_fixture("daily_health")
    zero["payload"]["allMetrics"]["metricsMap"]["WELLNESS_RESTING_HEART_RATE"][0]["value"] = 0
    missing = raw_fixture("daily_health")
    del missing["payload"]["allMetrics"]["metricsMap"]["WELLNESS_RESTING_HEART_RATE"]
    explicit_null = raw_fixture("daily_health")
    explicit_null["payload"]["allMetrics"]["metricsMap"][
        "WELLNESS_RESTING_HEART_RATE"
    ][0]["value"] = None

    present_result = normalize_garmin_payload(present)
    zero_result = normalize_garmin_payload(zero)
    missing_result = normalize_garmin_payload(missing)
    null_result = normalize_garmin_payload(explicit_null)

    assert present_result.records[0].metric("resting_heart_rate").value == 52
    assert zero_result.records[0].metric("resting_heart_rate").state is GarminFieldState.VALUE
    assert zero_result.records[0].metric("resting_heart_rate").value == 0
    assert zero_result.records[0].metric("resting_heart_rate").is_zero
    assert missing_result.records[0].metric("resting_heart_rate").state is GarminFieldState.MISSING
    assert missing_result.records[0].metric("resting_heart_rate").device_evidence is False
    assert null_result.records[0].metric("resting_heart_rate").state is GarminFieldState.NULL
    assert zero_result.idempotency_keys != missing_result.idempotency_keys
    assert zero_result.idempotency_keys != null_result.idempotency_keys
    assert missing_result.partial


def test_partial_empty_and_shape_drift_results_are_deterministic() -> None:
    partial = raw_fixture("sleep")
    partial["payload"]["dailySleepDTO"]["sleepScores"].pop("overall")
    partial["payload"]["levels"] = "unexpected-shape"
    first = normalize_garmin_payload(partial)
    second = normalize_garmin_payload(json.loads(json.dumps(partial)))

    assert first.status is GarminParseStatus.PARTIAL
    assert first.as_dict() == second.as_dict()
    assert first.records[0].metric("sleep_score").state is GarminFieldState.MISSING
    assert first.records[0].metric("sleep_stages").state is GarminFieldState.INVALID
    assert any(item.code == "fixture_field_map_drift" for item in first.diagnostics)

    empty = normalize_garmin_payload({"activities": []}, stream="activity")
    assert empty.status is GarminParseStatus.EMPTY
    assert empty.records == ()
    assert any(item.code == "empty_activity_collection" for item in empty.diagnostics)

    drift = normalize_garmin_payload({"activities": {"not": "an array"}}, stream="activity")
    assert drift.status is GarminParseStatus.INVALID
    assert any(item.code == "activity_collection_shape_drift" for item in drift.diagnostics)


def test_mixed_activity_shape_drift_keeps_valid_record() -> None:
    payload = raw_fixture("activity")["payload"]
    mixed = {"activities": [payload["activities"][0], "broken-item"]}

    result = normalize_garmin_payload(mixed, stream="activity")

    assert result.status is GarminParseStatus.PARTIAL
    assert len(result.records) == 1
    assert result.records[0].record_id == "synthetic-activity-001"
    assert any(item.code == "activity_item_shape_drift" for item in result.diagnostics)


def test_semantic_key_ignores_unknown_order_but_tracks_present_values() -> None:
    source = garmin_source_identity(
        device_attributed=True,
        device_code="garmin_vivoactive_5",
        device_model="Vivoactive 5",
    )
    temporal = parse_garmin_time("2099-01-02")
    left = [
        ("sleep_score", 82, "points"),
        ("sleep_duration_seconds", 28800, "seconds"),
    ]
    right = list(reversed(left))

    first = stable_garmin_idempotency_key(source, "sleep", temporal=temporal, metrics=left)
    second = stable_garmin_idempotency_key(source, "sleep", temporal=temporal, metrics=right)
    changed = stable_garmin_idempotency_key(
        source,
        "sleep",
        temporal=temporal,
        metrics=[("sleep_score", 0, "points"), ("sleep_duration_seconds", 28800, "seconds")],
    )

    assert first == second
    assert first != changed


def test_invalid_or_raw_inputs_fail_closed_without_payload_dump() -> None:
    invalid = normalize_garmin_payload({"source_kind": "owner-live", "payload": {}})
    assert invalid.status is GarminParseStatus.INVALID
    text = json.dumps(invalid.as_dict(), sort_keys=True)
    assert "owner-live" not in text
    assert "payload" not in text.split("diagnostics", 1)[-1]

    with pytest.raises(ValueError, match="source provider"):
        garmin_source_identity(provider_code="other")
