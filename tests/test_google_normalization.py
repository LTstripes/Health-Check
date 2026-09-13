"""Synthetic offline coverage for R04-03b Google Health normalization."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select

from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
from healthcheck.db.models import (
    CanonicalSelection,
    CanonicalSelectionRun,
    DerivedMeasurement,
    GarminRawPayload,
    GarminSource,
    GarminSourceRecord,
    GoogleNormalizationAttempt,
    GooglePayloadObservation,
    GoogleRawPayload,
    GoogleRecordInterval,
    GoogleRecordMetric,
    GoogleRecordSourceEvidence,
    GoogleSleepFieldState,
    GoogleSleepInterval,
    GoogleSleepRecord,
    GoogleSourceKind,
    GoogleSourceRecord,
    ScalarMeasurement,
)
from healthcheck.google.contracts import (
    FAMILY_ALL_SOURCES,
    FAMILY_GOOGLE_SOURCES,
    FAMILY_GOOGLE_WEARABLES,
    GoogleMetricState,
    GooglePayloadStatus,
    GoogleQueryContext,
    GoogleQueryMode,
    GoogleSourceIdentity,
    GoogleStream,
)
from healthcheck.google.normalization import (
    NORMALIZATION_CONTRACT_VERSION,
    GoogleNormalizationResult,
    normalize_google_payload,
)
from healthcheck.google.persistence import GooglePersistenceRepository
from healthcheck.google.replay import replay_google_observations
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from healthcheck.runtime import prepare_runtime


def _civil(day: int = 2, hour: int = 8, minute: int = 0) -> dict[str, object]:
    return {
        "date": {"year": 2099, "month": 1, "day": day},
        "time": {"hours": hour, "minutes": minute, "seconds": 0, "nanos": 0},
    }


def _sample_time() -> dict[str, object]:
    return {
        "physicalTime": "2099-01-02T05:00:00Z",
        "utcOffset": "10800s",
        "civilTime": _civil(hour=8),
    }


def _interval(
    *, start: str = "2099-01-01T22:00:00Z", end: str = "2099-01-02T05:00:00Z"
) -> dict[str, object]:
    return {
        "startTime": start,
        "startUtcOffset": "10800s",
        "endTime": end,
        "endUtcOffset": "10800s",
        "civilStartTime": _civil(day=2, hour=1),
        "civilEndTime": _civil(day=2, hour=8),
    }


def _data_source(*, platform: str = "GOOGLE_WEB_API") -> dict[str, object]:
    return {
        "recordingMethod": "PASSIVELY_MEASURED",
        "device": {
            "formFactor": "WATCH",
            "manufacturer": "Synthetic Devices",
            "displayName": "Synthetic Watch",
        },
        "application": {"packageName": "org.synthetic.health"},
        "platform": platform,
    }


def _sleep_component() -> dict[str, object]:
    return {
        "interval": _interval(),
        "type": "STAGES",
        "stages": [
            {
                "startTime": "2099-01-01T22:00:00Z",
                "startUtcOffset": "10800s",
                "endTime": "2099-01-01T23:00:00Z",
                "endUtcOffset": "10800s",
                "type": "LIGHT",
                "createTime": "2099-01-02T08:01:00Z",
                "updateTime": "2099-01-02T08:02:00Z",
            }
        ],
        "outOfBedSegments": [
            {
                "startTime": "2099-01-02T01:00:00Z",
                "startUtcOffset": "10800s",
                "endTime": "2099-01-02T01:05:00Z",
                "endUtcOffset": "10800s",
            }
        ],
        "metadata": {
            "stagesStatus": "SUCCEEDED",
            "processed": True,
            "nap": False,
            "manuallyEdited": False,
            "externalId": "synthetic-sleep-01",
        },
        "summary": {
            "minutesInSleepPeriod": "420",
            "minutesAfterWakeUp": "0",
            "minutesToFallAsleep": "10",
            "minutesAsleep": "410",
            "minutesAwake": "10",
            "stagesSummary": [{"type": "LIGHT", "minutes": "60", "count": "1"}],
        },
        "createTime": "2099-01-02T08:03:00Z",
        "updateTime": "2099-01-02T08:04:00Z",
    }


def _component(stream: GoogleStream) -> dict[str, object]:
    if stream is GoogleStream.SLEEP:
        return _sleep_component()
    if stream is GoogleStream.HEART_RATE:
        return {"sampleTime": _sample_time(), "beatsPerMinute": "72"}
    if stream is GoogleStream.HRV:
        return {
            "sampleTime": _sample_time(),
            "rootMeanSquareOfSuccessiveDifferencesMilliseconds": 42.5,
            "standardDeviationMilliseconds": "55.0",
        }
    if stream is GoogleStream.DAILY_HRV:
        return {
            "date": _civil()["date"],
            "averageHeartRateVariabilityMilliseconds": "42.5",
            "nonRemHeartRateBeatsPerMinute": "60",
            "entropy": 0,
            "deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds": 0,
        }
    if stream is GoogleStream.DAILY_RESTING_HR:
        return {
            "date": _civil()["date"],
            "dailyRestingHeartRateMetadata": {"calculationMethod": "WITH_SLEEP"},
            "beatsPerMinute": "55",
        }
    if stream is GoogleStream.SPO2:
        return {"sampleTime": _sample_time(), "percentage": 0}
    if stream is GoogleStream.DAILY_SPO2:
        return {
            "date": _civil()["date"],
            "averagePercentage": 0,
            "lowerBoundPercentage": "0",
            "upperBoundPercentage": "0",
            "standardDeviationPercentage": 0,
        }
    if stream is GoogleStream.RESPIRATORY_RATE_SLEEP:
        return {
            "sampleTime": _sample_time(),
            "fullSleepStats": {
                "breathsPerMinute": "12.5",
                "standardDeviation": 0,
                "signalToNoise": "1.0",
            },
        }
    return {"date": _civil()["date"], "breathsPerMinute": "12.5"}


def stream_field(stream: GoogleStream) -> str:
    return {
        GoogleStream.SLEEP: "sleep",
        GoogleStream.HEART_RATE: "heartRate",
        GoogleStream.HRV: "heartRateVariability",
        GoogleStream.DAILY_HRV: "dailyHeartRateVariability",
        GoogleStream.DAILY_RESTING_HR: "dailyRestingHeartRate",
        GoogleStream.SPO2: "oxygenSaturation",
        GoogleStream.DAILY_SPO2: "dailyOxygenSaturation",
        GoogleStream.RESPIRATORY_RATE_SLEEP: "respiratoryRateSleepSummary",
        GoogleStream.DAILY_RESPIRATORY_RATE: "dailyRespiratoryRate",
    }[stream]


def _payload(
    stream: GoogleStream,
    *,
    data_source: dict[str, object] | None = None,
    component: object | None = None,
    name: str = "synthetic-record-01",
) -> dict[str, object]:
    point: dict[str, object] = {
        "name": name,
        stream_field(stream): component if component is not None else _component(stream),
    }
    if data_source is not None:
        point["dataSource"] = data_source
    return {"dataPoints": [point]}


def _identity(*, attributed: bool = False, suffix: str = "") -> GoogleSourceIdentity:
    values: dict[str, object] = {
        "source_kind": GoogleSourceKind.DATA_SOURCE,
        "source_instance_id": f"users/me/dataSources/synthetic-google-source{suffix}",
        "platform": "GOOGLE_WEB_API",
        "recording_method": "PASSIVELY_MEASURED",
    }
    if attributed:
        values.update(
            {
                "device_attributed": True,
                "device_code": "synthetic_fitbit_device",
                "device_manufacturer": "Synthetic Fitbit",
                "device_model": "Synthetic Band",
                "device_uid": "synthetic-device-01",
            }
        )
    return GoogleSourceIdentity(**values)


@pytest.mark.parametrize("stream", tuple(GoogleStream))
def test_every_accepted_type_has_a_successful_typed_projection(stream):
    result = normalize_google_payload(
        _payload(stream, data_source=_data_source()),
        stream=stream,
        query=GoogleQueryContext(GoogleQueryMode.LIST),
    )
    assert result.status.value == "ok"
    assert len(result.records) == 1
    assert result.records[0].stream is stream
    assert result.records[0].data_source is not None
    assert result.records[0].unknown_fields == ()


@pytest.mark.parametrize("stream", tuple(GoogleStream))
def test_empty_collection_is_explicit(stream):
    result = normalize_google_payload(
        {"dataPoints": []}, stream=stream, query=GoogleQueryContext(GoogleQueryMode.LIST)
    )
    assert result.status.value == "empty"
    assert result.records == ()


def test_sleep_session_stages_and_wake_date_are_typed():
    result = normalize_google_payload(
        _payload(GoogleStream.SLEEP, data_source=_data_source()),
        stream=GoogleStream.SLEEP,
        query=GoogleQueryContext(GoogleQueryMode.LIST),
    )
    record = result.records[0]
    assert record.sleep_interval is not None
    assert record.sleep_interval.interval_kind.value == "sleep_session"
    assert record.sleep_interval.state is GoogleMetricState.VALUE
    assert len(record.sleep_stages) == 1
    assert record.sleep_stages[0].stage_type == "LIGHT"
    assert record.sleep_stages[0].start.source_utc_field.endswith("startTime")
    assert len(record.out_of_bed_segments) == 1
    assert record.temporal.local_date == date(2099, 1, 2)
    assert record.wake_date == date(2099, 1, 2)
    assert record.external_record_id == "synthetic-record-01"
    assert not any(metric.metric_code == "sleep_stages" for metric in record.metrics)


def test_sleep_logical_identity_ignores_mutable_interval_revision_content():
    original = _payload(GoogleStream.SLEEP)
    corrected = json.loads(json.dumps(original))
    interval = corrected["dataPoints"][0]["sleep"]["interval"]
    interval["endTime"] = "2099-01-02T05:30:00Z"
    interval["civilEndTime"] = _civil(hour=8, minute=30)
    corrected["dataPoints"][0]["sleep"]["updateTime"] = "2099-01-02T08:05:00Z"

    first = normalize_google_payload(original, stream=GoogleStream.SLEEP)
    second = normalize_google_payload(corrected, stream=GoogleStream.SLEEP)

    assert first.records[0].external_record_id == second.records[0].external_record_id
    assert first.records[0].idempotency_key == second.records[0].idempotency_key
    assert first.records[0].sleep_interval.end.local_date == date(2099, 1, 2)
    assert second.records[0].sleep_interval.end.local_wall_time.endswith("08:30:00")


def test_unidentified_equal_sleep_records_remain_explicit():
    component = _sleep_component()
    del component["metadata"]["externalId"]
    payload = {
        "dataPoints": [
            {"sleep": json.loads(json.dumps(component))},
            {"sleep": json.loads(json.dumps(component))},
        ]
    }

    result = normalize_google_payload(payload, stream=GoogleStream.SLEEP)

    assert result.status.value == "ok"
    assert len(result.records) == 2
    assert all(record.external_record_id is None for record in result.records)
    assert len({record.idempotency_key for record in result.records}) == 2


def test_sleep_correction_keeps_one_current_session_and_preserves_observations(
    normalization_database,
):
    _paths, session, store = normalization_database
    original = _payload(GoogleStream.SLEEP)
    corrected = json.loads(json.dumps(original))
    corrected_point = corrected["dataPoints"][0]
    corrected_point["dataPointName"] = corrected_point.pop("name")
    corrected_point.pop("dataSource", None)
    interval = corrected_point["sleep"]["interval"]
    interval["endTime"] = "2099-01-03T00:30:00Z"
    interval["civilEndTime"] = _civil(day=3, hour=3, minute=30)
    corrected_point["sleep"]["updateTime"] = "2099-01-03T08:05:00Z"

    first_result, first = _persist_result(
        session,
        store,
        original,
        stream=GoogleStream.SLEEP,
        received_at=datetime(2099, 1, 4, tzinfo=UTC),
    )
    session.commit()
    first.records[0].record_identity_key = "google-record-v1:legacy-synthetic-sleep"
    session.commit()
    second_result, second = _persist_result(
        session,
        store,
        corrected,
        stream=GoogleStream.SLEEP,
        query=GoogleQueryContext(GoogleQueryMode.RECONCILE, FAMILY_GOOGLE_WEARABLES),
        received_at=datetime(2099, 1, 3, tzinfo=UTC),
    )
    session.commit()

    assert first_result.records[0].idempotency_key == second_result.records[0].idempotency_key
    assert second.records[0].id == first.records[0].id
    assert second.updated_count == 1
    current_rows = list(
        session.scalars(
            select(GoogleSourceRecord).where(
                GoogleSourceRecord.google_source_id == first.source.id,
                GoogleSourceRecord.stream_code == GoogleStream.SLEEP.value,
                GoogleSourceRecord.external_record_id == "synthetic-record-01",
                GoogleSourceRecord.projection_status == "current",
            )
        )
    )
    assert len(current_rows) == 1
    typed = session.get(GoogleSleepRecord, first.records[0].id)
    assert typed is not None
    assert typed.wake_date == date(2099, 1, 3)
    assert session.scalar(select(func.count(GoogleRawPayload.id))) == 2
    assert session.scalar(select(func.count(GooglePayloadObservation.id))) == 2


def test_older_sleep_revision_arriving_later_cannot_displace_current(
    normalization_database,
):
    _paths, session, store = normalization_database
    latest = _payload(GoogleStream.SLEEP)
    latest["dataPoints"][0]["sleep"]["updateTime"] = "2099-01-02T08:10:00Z"
    older = json.loads(json.dumps(latest))
    older["dataPoints"][0]["sleep"]["interval"]["endTime"] = "2099-01-02T05:15:00Z"
    older["dataPoints"][0]["sleep"]["interval"]["civilEndTime"] = _civil(hour=8, minute=15)
    older["dataPoints"][0]["sleep"]["updateTime"] = "2099-01-02T08:05:00Z"

    _latest_result, latest_outcome = _persist_result(
        session,
        store,
        latest,
        stream=GoogleStream.SLEEP,
        received_at=datetime(2099, 1, 3, tzinfo=UTC),
    )
    session.commit()
    _older_result, older_outcome = _persist_result(
        session,
        store,
        older,
        stream=GoogleStream.SLEEP,
        received_at=datetime(2099, 1, 5, tzinfo=UTC),
    )
    session.commit()

    assert older_outcome.records[0].id == latest_outcome.records[0].id
    assert older_outcome.updated_count == 0
    interval = session.scalar(
        select(GoogleSleepInterval).where(
            GoogleSleepInterval.sleep_record_id == latest_outcome.records[0].id,
            GoogleSleepInterval.interval_kind == "sleep_session",
        )
    )
    assert interval is not None
    assert interval.end_at_utc == datetime(2099, 1, 2, 5, 0)


def test_equal_or_unusable_sleep_revision_cannot_replace_changed_interval(
    normalization_database,
):
    _paths, session, store = normalization_database
    original = _payload(GoogleStream.SLEEP)
    original["dataPoints"][0]["sleep"]["updateTime"] = "2099-01-02T08:10:00Z"
    equal = json.loads(json.dumps(original))
    equal["dataPoints"][0]["sleep"]["interval"]["endTime"] = "2099-01-02T05:20:00Z"
    equal["dataPoints"][0]["sleep"]["interval"]["civilEndTime"] = _civil(hour=8, minute=20)
    unusable = json.loads(json.dumps(equal))
    unusable["dataPoints"][0]["sleep"]["updateTime"] = "not-a-timestamp"
    unusable["dataPoints"][0]["sleep"]["interval"]["endTime"] = "2099-01-02T05:30:00Z"
    unusable["dataPoints"][0]["sleep"]["interval"]["civilEndTime"] = _civil(hour=8, minute=30)

    _result, first = _persist_result(
        session,
        store,
        original,
        stream=GoogleStream.SLEEP,
        received_at=datetime(2099, 1, 3, tzinfo=UTC),
    )
    session.commit()
    _equal_result, equal_outcome = _persist_result(
        session,
        store,
        equal,
        stream=GoogleStream.SLEEP,
        received_at=datetime(2099, 1, 4, tzinfo=UTC),
    )
    session.commit()
    _unusable_result, unusable_outcome = _persist_result(
        session,
        store,
        unusable,
        stream=GoogleStream.SLEEP,
        received_at=datetime(2099, 1, 5, tzinfo=UTC),
    )
    session.commit()

    assert equal_outcome.updated_count == 0
    assert unusable_outcome.updated_count == 0
    assert equal_outcome.records[0].id == first.records[0].id
    interval = session.scalar(
        select(GoogleSleepInterval).where(
            GoogleSleepInterval.sleep_record_id == first.records[0].id,
            GoogleSleepInterval.interval_kind == "sleep_session",
        )
    )
    assert interval is not None
    assert interval.end_at_utc == datetime(2099, 1, 2, 5, 0)


@pytest.mark.parametrize("revision", ("missing", "invalid"))
@pytest.mark.parametrize(
    "interval_state",
    (GoogleMetricState.NULL, GoogleMetricState.MISSING, GoogleMetricState.INVALID),
)
def test_unusable_sleep_revision_cannot_replace_accepted_projection_field_state(
    normalization_database, revision, interval_state
):
    _paths, session, store = normalization_database
    original = _payload(GoogleStream.SLEEP)
    original["dataPoints"][0]["sleep"]["updateTime"] = "2099-01-02T08:10:00Z"
    _result, first = _persist_result(
        session,
        store,
        original,
        stream=GoogleStream.SLEEP,
        received_at=datetime(2099, 1, 3, tzinfo=UTC),
    )
    session.commit()

    record_id = first.records[0].id
    parent = session.get(GoogleSourceRecord, record_id)
    typed = session.get(GoogleSleepRecord, record_id)
    field_state = session.get(GoogleSleepFieldState, record_id)
    assert parent is not None
    assert typed is not None
    assert field_state is not None
    parent_before = tuple(
        getattr(parent, column.name) for column in GoogleSourceRecord.__table__.columns
    )
    typed_before = tuple(
        getattr(typed, column.name) for column in GoogleSleepRecord.__table__.columns
    )
    field_state_before = tuple(
        getattr(field_state, column.name) for column in GoogleSleepFieldState.__table__.columns
    )
    metrics_before = tuple(
        tuple(getattr(row, column.name) for column in GoogleRecordMetric.__table__.columns)
        for row in session.scalars(
            select(GoogleRecordMetric)
            .where(GoogleRecordMetric.record_id == record_id)
            .order_by(GoogleRecordMetric.metric_code, GoogleRecordMetric.id)
        )
    )
    intervals_before = _sleep_row_snapshot(session, record_id)
    raw_count_before = session.scalar(select(func.count(GoogleRawPayload.id)))
    observation_count_before = session.scalar(select(func.count(GooglePayloadObservation.id)))
    attempt_count_before = session.scalar(select(func.count(GoogleNormalizationAttempt.id)))

    incoming = json.loads(json.dumps(original))
    sleep = incoming["dataPoints"][0]["sleep"]
    if revision == "missing":
        del sleep["updateTime"]
    else:
        sleep["updateTime"] = "not-a-timestamp"
    if interval_state is GoogleMetricState.NULL:
        sleep["interval"] = None
    elif interval_state is GoogleMetricState.MISSING:
        del sleep["interval"]
    else:
        sleep["interval"] = []

    incoming_result = normalize_google_payload(
        incoming,
        stream=GoogleStream.SLEEP,
        source_identity=_identity(),
        normalization_contract_version=NORMALIZATION_CONTRACT_VERSION,
    )
    assert incoming_result.records
    # Exercise the record-level typed field states at the persistence boundary;
    # raw/observation/attempt evidence remains auditable for this input.
    incoming_result = replace(incoming_result, status=GooglePayloadStatus.OK)
    outcome = GooglePersistenceRepository(session, payload_store=store).persist_result(
        incoming_result,
        payload=incoming,
        received_at=datetime(2099, 1, 5, tzinfo=UTC),
    )
    session.commit()

    assert outcome.updated_count == 0
    assert outcome.inserted_count == 0
    assert outcome.records[0].id == record_id
    assert outcome.normalization_attempt is not None
    assert session.scalar(select(func.count(GoogleRawPayload.id))) == raw_count_before + 1
    assert (
        session.scalar(select(func.count(GooglePayloadObservation.id)))
        == observation_count_before + 1
    )
    assert (
        session.scalar(select(func.count(GoogleNormalizationAttempt.id)))
        == attempt_count_before + 1
    )

    parent_after = session.get(GoogleSourceRecord, record_id)
    typed_after = session.get(GoogleSleepRecord, record_id)
    field_state_after = session.get(GoogleSleepFieldState, record_id)
    assert parent_after is not None
    assert typed_after is not None
    assert field_state_after is not None
    assert parent_before == tuple(
        getattr(parent_after, column.name) for column in GoogleSourceRecord.__table__.columns
    )
    assert typed_before == tuple(
        getattr(typed_after, column.name) for column in GoogleSleepRecord.__table__.columns
    )
    assert field_state_before == tuple(
        getattr(field_state_after, column.name)
        for column in GoogleSleepFieldState.__table__.columns
    )
    metrics_after = tuple(
        tuple(getattr(row, column.name) for column in GoogleRecordMetric.__table__.columns)
        for row in session.scalars(
            select(GoogleRecordMetric)
            .where(GoogleRecordMetric.record_id == record_id)
            .order_by(GoogleRecordMetric.metric_code, GoogleRecordMetric.id)
        )
    )
    assert metrics_before == metrics_after
    assert intervals_before == _sleep_row_snapshot(session, record_id)


def test_missing_null_zero_invalid_nonfinite_and_string_numeric_states():
    missing = _payload(GoogleStream.HEART_RATE)
    del missing["dataPoints"][0]["heartRate"]["beatsPerMinute"]
    missing_result = normalize_google_payload(missing, stream=GoogleStream.HEART_RATE)
    assert missing_result.status.value == "invalid"
    assert missing_result.records[0].metrics[0].state is GoogleMetricState.MISSING

    null_payload = _payload(
        GoogleStream.HEART_RATE,
        component={"sampleTime": _sample_time(), "beatsPerMinute": None},
    )
    null_result = normalize_google_payload(null_payload, stream=GoogleStream.HEART_RATE)
    assert null_result.records[0].metrics[0].state is GoogleMetricState.NULL

    zero_result = normalize_google_payload(_payload(GoogleStream.SPO2), stream=GoogleStream.SPO2)
    zero_metric = zero_result.records[0].metrics[0]
    assert zero_metric.state is GoogleMetricState.VALUE
    assert zero_metric.value_number == 0

    invalid_result = normalize_google_payload(
        _payload(
            GoogleStream.SPO2,
            component={"sampleTime": _sample_time(), "percentage": "not-a-number"},
        ),
        stream=GoogleStream.SPO2,
    )
    assert invalid_result.status.value == "invalid"
    assert invalid_result.records[0].metrics[0].state is GoogleMetricState.INVALID

    nonfinite = normalize_google_payload(
        _payload(
            GoogleStream.SPO2,
            component={"sampleTime": _sample_time(), "percentage": float("nan")},
        ),
        stream=GoogleStream.SPO2,
    )
    assert nonfinite.records[0].metrics[0].state is GoogleMetricState.INVALID

    string_numeric = normalize_google_payload(
        _payload(GoogleStream.DAILY_RESTING_HR), stream=GoogleStream.DAILY_RESTING_HR
    )
    metric = string_numeric.records[0].metrics[0]
    assert metric.value_number == 55
    assert metric.value_text == "55"


def test_temporal_precision_preserves_utc_local_date_offset_and_source_paths():
    result = normalize_google_payload(
        _payload(GoogleStream.HEART_RATE), stream=GoogleStream.HEART_RATE
    )
    temporal = result.records[0].temporal
    assert temporal.precision.value == "instant"
    assert temporal.measured_at_utc == datetime(2099, 1, 2, 5, tzinfo=UTC)
    assert temporal.local_date == date(2099, 1, 2)
    assert temporal.source_utc_offset_minutes == 180
    assert temporal.source_utc_field.endswith("sampleTime.physicalTime")
    assert temporal.source_local_field.endswith("sampleTime.civilTime")

    daily = normalize_google_payload(
        _payload(GoogleStream.DAILY_HRV), stream=GoogleStream.DAILY_HRV
    )
    daily_temporal = daily.records[0].temporal
    assert daily_temporal.precision.value == "date"
    assert daily_temporal.measured_at_utc is None
    assert daily_temporal.local_date == date(2099, 1, 2)


def test_optional_sibling_states_keep_missing_distinct_from_explicit_null():
    component = _component(GoogleStream.HRV)
    del component["rootMeanSquareOfSuccessiveDifferencesMilliseconds"]
    component["standardDeviationMilliseconds"] = None
    result = normalize_google_payload(
        _payload(GoogleStream.HRV, component=component), stream=GoogleStream.HRV
    )
    by_code = {metric.metric_code: metric for metric in result.records[0].metrics}
    assert by_code["hrv_rmssd_ms"].state is GoogleMetricState.MISSING
    assert by_code["hrv_sdnn_ms"].state is GoogleMetricState.NULL
    assert result.status.value == "ok"


def test_unknown_fields_are_bounded_sanitized_evidence():
    component = {**_component(GoogleStream.HEART_RATE), "futureField": {"private": "discarded"}}
    result = normalize_google_payload(
        _payload(GoogleStream.HEART_RATE, component=component), stream=GoogleStream.HEART_RATE
    )
    assert result.status.value == "ok"
    assert result.records[0].unknown_fields == (
        {
            "path": "$.dataPoints[0].heartRate.futureField",
            "field": "futureField",
            "kind": "provider_field",
        },
    )
    assert "discarded" not in json.dumps(result.as_dict())


def test_unknown_top_level_data_union_fails_closed():
    point = _payload(GoogleStream.HEART_RATE)["dataPoints"][0]
    point["futureDataType"] = {"value": "not accepted in R04"}
    result = normalize_google_payload({"dataPoints": [point]}, stream="heart-rate")
    assert result.status.value == "invalid"
    assert result.records[0].status.value == "invalid"
    assert any(
        item["field"] == "futureDataType" and item["kind"] == "unsupported_data_type"
        for item in result.unknown_fields
    )


def test_required_respiratory_parent_omission_fails_closed():
    component = _component(GoogleStream.RESPIRATORY_RATE_SLEEP)
    del component["fullSleepStats"]
    result = normalize_google_payload(
        _payload(GoogleStream.RESPIRATORY_RATE_SLEEP, component=component),
        stream=GoogleStream.RESPIRATORY_RATE_SLEEP,
    )
    assert result.status.value == "invalid"
    assert any(
        item.code == "required_field_missing"
        and item.path.endswith("respiratoryRateSleepSummary.fullSleepStats")
        for item in result.diagnostics
    )


def test_invalid_interval_state_and_provider_paths_are_retained():
    payload = {
        "rollupDataPoints": [
            {
                "startTime": None,
                "endTime": "2099-01-02T06:00:00Z",
                "heartRate": {"beatsPerMinuteAvg": "72"},
            }
        ]
    }
    result = normalize_google_payload(
        payload,
        stream=GoogleStream.HEART_RATE,
        query=GoogleQueryContext(GoogleQueryMode.ROLL_UP),
    )
    record = result.records[0]
    assert result.status.value == "invalid"
    assert record.interval is not None
    assert record.interval.state is GoogleMetricState.INVALID
    assert record.interval.start.state is GoogleMetricState.NULL
    assert record.interval.start.source_field.endswith(".startTime")
    assert record.interval.start.source_utc_field == record.interval.start.source_field


@pytest.mark.parametrize("mode", (GoogleQueryMode.ROLL_UP, GoogleQueryMode.DAILY_ROLL_UP))
def test_heart_rate_rollup_modes_preserve_their_documented_interval_precision(mode):
    if mode is GoogleQueryMode.ROLL_UP:
        payload = {
            "rollupDataPoints": [
                {
                    "startTime": "2099-01-02T05:00:00Z",
                    "endTime": "2099-01-02T06:00:00Z",
                    "heartRate": {
                        "beatsPerMinuteAvg": "72.5",
                        "beatsPerMinuteMax": 80,
                        "beatsPerMinuteMin": 65,
                    },
                }
            ]
        }
    else:
        payload = {
            "rollupDataPoints": [
                {
                    "civilStartTime": _civil(hour=0),
                    "civilEndTime": _civil(day=3, hour=0),
                    "heartRate": {
                        "beatsPerMinuteAvg": 72.5,
                        "beatsPerMinuteMax": "80",
                        "beatsPerMinuteMin": "65",
                    },
                }
            ]
        }
    result = normalize_google_payload(
        payload,
        stream=GoogleStream.HEART_RATE,
        query=GoogleQueryContext(mode, FAMILY_GOOGLE_WEARABLES),
    )
    assert result.status.value == "ok"
    record = result.records[0]
    assert record.interval is not None
    assert record.interval.interval_kind.value == (
        "roll_up" if mode is GoogleQueryMode.ROLL_UP else "daily_roll_up"
    )
    assert record.temporal.precision.value == (
        "instant" if mode is GoogleQueryMode.ROLL_UP else "local"
    )
    assert record.metrics[0].value_number == 72.5


def test_rollup_unsupported_union_member_fails_closed():
    result = normalize_google_payload(
        {
            "rollupDataPoints": [
                {
                    "startTime": "2099-01-02T05:00:00Z",
                    "endTime": "2099-01-02T06:00:00Z",
                    "steps": {"countSum": "1"},
                }
            ]
        },
        stream="heart-rate",
        query=GoogleQueryContext(GoogleQueryMode.ROLL_UP),
    )
    assert result.status.value == "invalid"
    assert result.records[0].status.value == "invalid"
    assert any(item.code == "data_type_union_unsupported" for item in result.diagnostics)


def test_rollup_missing_value_is_not_treated_as_zero_or_shape_drift():
    result = normalize_google_payload(
        {
            "rollupDataPoints": [
                {
                    "startTime": "2099-01-02T05:00:00Z",
                    "endTime": "2099-01-02T06:00:00Z",
                }
            ]
        },
        stream="heart-rate",
        query=GoogleQueryContext(GoogleQueryMode.ROLL_UP),
    )
    assert result.status.value == "ok"
    assert all(metric.state is GoogleMetricState.MISSING for metric in result.records[0].metrics)


def test_rollup_unknown_union_shape_fails_closed():
    result = normalize_google_payload(
        {
            "rollupDataPoints": [
                {
                    "startTime": "2099-01-02T05:00:00Z",
                    "endTime": "2099-01-02T06:00:00Z",
                    "futureRollupValue": {"value": "not accepted in R04"},
                }
            ]
        },
        stream="heart-rate",
        query=GoogleQueryContext(GoogleQueryMode.ROLL_UP),
    )
    assert result.status.value == "invalid"
    assert any(item.code == "data_type_union_unsupported" for item in result.diagnostics)


@pytest.mark.parametrize(
    "mode,family",
    (
        (GoogleQueryMode.LIST, None),
        (GoogleQueryMode.RECONCILE, FAMILY_ALL_SOURCES),
        (GoogleQueryMode.RECONCILE, FAMILY_GOOGLE_SOURCES),
        (GoogleQueryMode.RECONCILE, FAMILY_GOOGLE_WEARABLES),
    ),
)
def test_query_and_family_context_are_retained_without_source_relabeling(mode, family):
    identity = _identity()
    payload = _payload(GoogleStream.HEART_RATE, data_source=_data_source())
    if mode is GoogleQueryMode.RECONCILE:
        point = payload["dataPoints"][0]
        point["dataPointName"] = point.pop("name")
        point.pop("dataSource")
    result = normalize_google_payload(
        payload,
        stream=GoogleStream.HEART_RATE,
        query=GoogleQueryContext(mode, family),
        source_identity=identity,
    )
    assert result.query.query_mode is mode
    assert result.query.data_source_family == family
    assert result.source_identity == identity
    if mode is GoogleQueryMode.LIST:
        assert result.records[0].data_source.platform.value_text == "GOOGLE_WEB_API"
    else:
        assert result.records[0].data_source.state is GoogleMetricState.MISSING
        assert result.records[0].data_source.platform is None
    assert identity.source_kind is GoogleSourceKind.DATA_SOURCE
    assert identity.device_attributed is False


@pytest.mark.parametrize(
    "payload,query",
    (
        (_payload(GoogleStream.HEART_RATE), GoogleQueryContext(GoogleQueryMode.LIST)),
        (
            {
                "dataPoints": [
                    {
                        "dataPointName": "synthetic-reconciled-record",
                        "heartRate": _component(GoogleStream.HEART_RATE),
                    }
                ]
            },
            GoogleQueryContext(GoogleQueryMode.RECONCILE),
        ),
    ),
)
def test_attributed_identity_requires_accepted_fitbit_provider_evidence(payload, query):
    result = normalize_google_payload(
        payload,
        stream=GoogleStream.HEART_RATE,
        query=query,
        source_identity=_identity(attributed=True),
    )
    assert result.status.value == "invalid"
    assert any(item.code == "source_attribution_invalid" for item in result.diagnostics)


def test_health_connect_or_pixel_evidence_cannot_support_fitbit_attribution():
    result = normalize_google_payload(
        _payload(
            GoogleStream.HEART_RATE,
            data_source={
                **_data_source(platform="HEALTH_CONNECT"),
                "device": {
                    "formFactor": "WATCH",
                    "manufacturer": "Google",
                    "displayName": "Pixel Watch",
                },
            },
        ),
        stream=GoogleStream.HEART_RATE,
        source_identity=_identity(attributed=True),
    )
    assert result.status.value == "invalid"
    assert any(item.code == "source_attribution_invalid" for item in result.diagnostics)


def test_family_aggregate_identity_cannot_absorb_source_specific_list_evidence():
    result = normalize_google_payload(
        _payload(GoogleStream.HEART_RATE, data_source=_data_source()),
        stream=GoogleStream.HEART_RATE,
        query=GoogleQueryContext(GoogleQueryMode.LIST, FAMILY_GOOGLE_WEARABLES),
        source_identity=GoogleSourceIdentity(
            source_kind=GoogleSourceKind.FAMILY_AGGREGATE,
            source_instance_id=FAMILY_GOOGLE_WEARABLES,
        ),
    )
    assert result.status.value == "invalid"
    assert any(item.code == "source_identity_conflict" for item in result.diagnostics)


def test_pixel_like_wearable_evidence_is_not_fitbit_and_explicit_fitbit_is_separate():
    pixel = normalize_google_payload(
        _payload(
            GoogleStream.HEART_RATE,
            data_source={
                **_data_source(platform="HEALTH_CONNECT"),
                "device": {
                    "formFactor": "WATCH",
                    "manufacturer": "Google",
                    "displayName": "Pixel Watch",
                },
            },
        ),
        stream=GoogleStream.HEART_RATE,
        source_identity=_identity(),
    )
    source = pixel.records[0].data_source
    assert source is not None
    assert source.platform.value_text == "HEALTH_CONNECT"
    assert source.device_manufacturer.value_text == "Google"
    assert source.device_display_name.value_text == "Pixel Watch"

    fitbit = normalize_google_payload(
        _payload(GoogleStream.HEART_RATE, data_source=_data_source(platform="FITBIT")),
        stream=GoogleStream.HEART_RATE,
        source_identity=_identity(attributed=True, suffix="-fitbit"),
    )
    assert fitbit.source_identity is not None
    assert fitbit.source_identity.device_attributed is True
    assert fitbit.source_identity.device_manufacturer == "Synthetic Fitbit"


@pytest.fixture
def normalization_database(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    try:
        with create_session_factory(engine)() as session:
            yield paths, session, ContentAddressedGooglePayloadStore(paths.root / "artifacts")
    finally:
        engine.dispose()


def _persist_result(
    session,
    store,
    payload,
    *,
    stream=GoogleStream.HEART_RATE,
    query=None,
    version=NORMALIZATION_CONTRACT_VERSION,
    identity=None,
    received_at=None,
):
    identity = identity or _identity()
    result = normalize_google_payload(
        payload,
        stream=stream,
        query=query or GoogleQueryContext(GoogleQueryMode.LIST),
        source_identity=identity,
        normalization_contract_version=version,
    )
    outcome = GooglePersistenceRepository(session, payload_store=store).persist_result(
        result,
        payload=payload,
        received_at=received_at or datetime(2099, 1, 3, tzinfo=UTC),
    )
    return result, outcome


@pytest.mark.parametrize("mode", (GoogleQueryMode.ROLL_UP, GoogleQueryMode.DAILY_ROLL_UP))
def test_rollup_projection_persists_typed_interval_and_query_context(normalization_database, mode):
    _paths, session, store = normalization_database
    if mode is GoogleQueryMode.ROLL_UP:
        payload = {
            "rollupDataPoints": [
                {
                    "startTime": "2099-01-02T05:00:00Z",
                    "endTime": "2099-01-02T06:00:00Z",
                    "heartRate": {"beatsPerMinuteAvg": "72"},
                }
            ]
        }
    else:
        payload = {
            "rollupDataPoints": [
                {
                    "civilStartTime": _civil(hour=0),
                    "civilEndTime": _civil(day=3, hour=0),
                    "heartRate": {"beatsPerMinuteAvg": "72"},
                }
            ]
        }
    query = GoogleQueryContext(mode, FAMILY_GOOGLE_WEARABLES)
    _result, outcome = _persist_result(
        session,
        store,
        payload,
        stream=GoogleStream.HEART_RATE,
        query=query,
    )
    session.commit()
    record = outcome.records[0]
    interval = session.scalar(
        select(GoogleRecordInterval).where(GoogleRecordInterval.record_id == record.id)
    )
    assert interval is not None
    assert interval.interval_kind == (
        "roll_up" if mode is GoogleQueryMode.ROLL_UP else "daily_roll_up"
    )
    assert interval.interval_state == GoogleMetricState.VALUE.value
    assert interval.start_state == GoogleMetricState.VALUE.value
    assert interval.start_temporal_json
    assert record.query_mode == mode.value
    assert record.data_source_family == FAMILY_GOOGLE_WEARABLES


def test_partial_sibling_fragment_does_not_erase_accepted_metric(normalization_database):
    _paths, session, store = normalization_database
    first_payload = _payload(
        GoogleStream.HRV,
        component={
            "sampleTime": _sample_time(),
            "rootMeanSquareOfSuccessiveDifferencesMilliseconds": 42.5,
            "standardDeviationMilliseconds": 55.0,
        },
    )
    _persist_result(session, store, first_payload, stream=GoogleStream.HRV)
    second_payload = _payload(
        GoogleStream.HRV,
        component={
            "sampleTime": _sample_time(),
            "rootMeanSquareOfSuccessiveDifferencesMilliseconds": 42.5,
        },
        name="synthetic-record-01",
    )
    _result, second = _persist_result(
        session,
        store,
        second_payload,
        stream=GoogleStream.HRV,
        received_at=datetime(2099, 1, 4, tzinfo=UTC),
    )
    session.commit()
    metric = session.scalar(
        select(GoogleRecordMetric).where(
            GoogleRecordMetric.record_id == second.records[0].id,
            GoogleRecordMetric.metric_code == "hrv_sdnn_ms",
        )
    )
    assert metric is not None
    assert metric.state == "value"
    assert metric.value_number == 55


def _sleep_row_snapshot(session, sleep_record_id):
    return tuple(
        (
            row.id,
            row.interval_kind,
            row.ordinal,
            row.interval_state,
            row.stage_type,
            row.create_time,
            row.update_time,
            row.start_at_utc,
            row.end_at_utc,
            row.start_local_date,
            row.end_local_date,
            row.start_source_field,
            row.end_source_field,
            row.start_temporal_json,
            row.end_temporal_json,
        )
        for row in session.scalars(
            select(GoogleSleepInterval)
            .where(GoogleSleepInterval.sleep_record_id == sleep_record_id)
            .order_by(GoogleSleepInterval.interval_kind, GoogleSleepInterval.ordinal)
        )
    )


def _assert_sleep_projection_consistent(session, sleep_record_id):
    field_state = session.get(GoogleSleepFieldState, sleep_record_id)
    assert field_state is not None
    rows = list(
        session.scalars(
            select(GoogleSleepInterval).where(
                GoogleSleepInterval.sleep_record_id == sleep_record_id
            )
        )
    )
    by_kind = {
        kind: [row for row in rows if row.interval_kind == kind]
        for kind in ("sleep_session", "sleep_stage", "sleep_out_of_bed")
    }
    for field_name, interval_kind in (
        ("sleep_interval_state", "sleep_session"),
        ("sleep_stages_state", "sleep_stage"),
        ("out_of_bed_state", "sleep_out_of_bed"),
    ):
        state = getattr(field_state, field_name)
        kind_rows = by_kind[interval_kind]
        if state == GoogleMetricState.VALUE.value:
            if interval_kind == "sleep_session":
                assert len(kind_rows) == 1
                assert kind_rows[0].interval_state == GoogleMetricState.VALUE.value
            else:
                assert all(row.interval_state == GoogleMetricState.VALUE.value for row in kind_rows)
        else:
            assert kind_rows == []


def test_sleep_typed_children_merge_missing_siblings_and_clear_empty_values(
    normalization_database,
):
    _paths, session, store = normalization_database
    full_result, first = _persist_result(
        session,
        store,
        _payload(GoogleStream.SLEEP),
        stream=GoogleStream.SLEEP,
        received_at=datetime(2099, 1, 3, tzinfo=UTC),
    )
    session.commit()
    record_id = first.records[0].id
    assert full_result.records[0].sleep_stages
    assert full_result.records[0].out_of_bed_segments
    field_state = session.get(GoogleSleepFieldState, record_id)
    assert field_state is not None
    assert field_state.sleep_stages_state == GoogleMetricState.VALUE.value
    assert field_state.out_of_bed_state == GoogleMetricState.VALUE.value
    initial_rows = _sleep_row_snapshot(session, record_id)
    _assert_sleep_projection_consistent(session, record_id)

    omitted = _sleep_component()
    omitted.pop("stages")
    omitted.pop("outOfBedSegments")
    partial_result, partial = _persist_result(
        session,
        store,
        _payload(GoogleStream.SLEEP, component=omitted),
        stream=GoogleStream.SLEEP,
        received_at=datetime(2099, 1, 4, tzinfo=UTC),
    )
    session.commit()
    assert partial_result.status.value == "ok"
    assert partial_result.records[0].sleep_stages_state is GoogleMetricState.MISSING
    assert partial_result.records[0].out_of_bed_state is GoogleMetricState.MISSING
    assert partial.records[0].id == record_id
    field_state = session.get(GoogleSleepFieldState, record_id)
    assert field_state is not None
    assert field_state.sleep_interval_state == GoogleMetricState.VALUE.value
    assert field_state.sleep_stages_state == GoogleMetricState.VALUE.value
    assert field_state.out_of_bed_state == GoogleMetricState.VALUE.value
    assert _sleep_row_snapshot(session, record_id) == initial_rows
    _assert_sleep_projection_consistent(session, record_id)

    empty_stages = _sleep_component()
    empty_stages["stages"] = []
    empty_stages.pop("outOfBedSegments")
    _persist_result(
        session,
        store,
        _payload(GoogleStream.SLEEP, component=empty_stages),
        stream=GoogleStream.SLEEP,
        received_at=datetime(2099, 1, 5, tzinfo=UTC),
    )
    session.commit()
    field_state = session.get(GoogleSleepFieldState, record_id)
    assert field_state is not None
    assert field_state.sleep_stages_state == GoogleMetricState.VALUE.value
    assert field_state.out_of_bed_state == GoogleMetricState.VALUE.value
    rows_after_empty_stages = _sleep_row_snapshot(session, record_id)
    assert not any(row[1] == "sleep_stage" for row in rows_after_empty_stages)
    assert [row for row in rows_after_empty_stages if row[1] == "sleep_out_of_bed"] == [
        row for row in initial_rows if row[1] == "sleep_out_of_bed"
    ]
    _assert_sleep_projection_consistent(session, record_id)

    empty_out_of_bed = _sleep_component()
    empty_out_of_bed["outOfBedSegments"] = []
    empty_out_of_bed.pop("stages")
    _persist_result(
        session,
        store,
        _payload(GoogleStream.SLEEP, component=empty_out_of_bed),
        stream=GoogleStream.SLEEP,
        received_at=datetime(2099, 1, 6, tzinfo=UTC),
    )
    session.commit()
    field_state = session.get(GoogleSleepFieldState, record_id)
    assert field_state is not None
    assert field_state.sleep_stages_state == GoogleMetricState.VALUE.value
    assert field_state.out_of_bed_state == GoogleMetricState.VALUE.value
    final_rows = _sleep_row_snapshot(session, record_id)
    assert not any(row[1] == "sleep_stage" for row in final_rows)
    assert not any(row[1] == "sleep_out_of_bed" for row in final_rows)
    _assert_sleep_projection_consistent(session, record_id)


def test_sleep_primary_interval_missing_and_null_are_non_destructive_and_consistent(
    normalization_database,
):
    _paths, session, store = normalization_database
    full_result, first = _persist_result(
        session,
        store,
        _payload(GoogleStream.SLEEP),
        stream=GoogleStream.SLEEP,
        received_at=datetime(2099, 1, 3, tzinfo=UTC),
    )
    session.commit()
    record_id = first.records[0].id
    full_record = full_result.records[0]
    assert full_record.sleep_interval is not None
    initial_rows = _sleep_row_snapshot(session, record_id)

    def persist_partial(record, payload_name, received_at):
        return GooglePersistenceRepository(session, payload_store=store).persist_observation(
            identity=_identity(),
            query=GoogleQueryContext(GoogleQueryMode.LIST),
            stream=GoogleStream.SLEEP,
            payload={"synthetic": payload_name},
            records=(record,),
            parse_status="partial",
            normalization_contract_version=NORMALIZATION_CONTRACT_VERSION,
            received_at=received_at,
            create_ingest_event=False,
        )

    missing_interval = replace(
        full_record,
        sleep_interval=replace(full_record.sleep_interval, state=GoogleMetricState.MISSING),
        sleep_stages_state=GoogleMetricState.MISSING,
        out_of_bed_state=GoogleMetricState.MISSING,
    )
    missing_outcome = persist_partial(
        missing_interval,
        "sleep-missing-interval",
        datetime(2099, 1, 4, tzinfo=UTC),
    )
    session.commit()
    assert missing_outcome.records[0].id == record_id
    field_state = session.get(GoogleSleepFieldState, record_id)
    assert field_state is not None
    assert field_state.sleep_interval_state == GoogleMetricState.VALUE.value
    assert field_state.sleep_stages_state == GoogleMetricState.VALUE.value
    assert field_state.out_of_bed_state == GoogleMetricState.VALUE.value
    assert _sleep_row_snapshot(session, record_id) == initial_rows
    _assert_sleep_projection_consistent(session, record_id)

    null_interval = replace(
        full_record,
        sleep_interval=replace(full_record.sleep_interval, state=GoogleMetricState.NULL),
        sleep_stages_state=GoogleMetricState.MISSING,
        out_of_bed_state=GoogleMetricState.MISSING,
    )
    persist_partial(
        null_interval,
        "sleep-null-interval",
        datetime(2099, 1, 5, tzinfo=UTC),
    )
    session.commit()
    field_state = session.get(GoogleSleepFieldState, record_id)
    assert field_state is not None
    assert field_state.sleep_interval_state == GoogleMetricState.NULL.value
    assert field_state.sleep_stages_state == GoogleMetricState.VALUE.value
    assert field_state.out_of_bed_state == GoogleMetricState.VALUE.value
    assert not any(row[1] == "sleep_session" for row in _sleep_row_snapshot(session, record_id))
    _assert_sleep_projection_consistent(session, record_id)

    null_stages = replace(
        full_record,
        sleep_interval=replace(full_record.sleep_interval, state=GoogleMetricState.MISSING),
        sleep_stages=(),
        sleep_stages_state=GoogleMetricState.NULL,
        out_of_bed_segments=(),
        out_of_bed_state=GoogleMetricState.MISSING,
    )
    persist_partial(
        null_stages,
        "sleep-null-stages",
        datetime(2099, 1, 6, tzinfo=UTC),
    )
    session.commit()
    field_state = session.get(GoogleSleepFieldState, record_id)
    assert field_state is not None
    assert field_state.sleep_interval_state == GoogleMetricState.NULL.value
    assert field_state.sleep_stages_state == GoogleMetricState.NULL.value
    assert field_state.out_of_bed_state == GoogleMetricState.VALUE.value
    rows = _sleep_row_snapshot(session, record_id)
    assert not any(row[1] in {"sleep_session", "sleep_stage"} for row in rows)
    assert any(row[1] == "sleep_out_of_bed" for row in rows)
    _assert_sleep_projection_consistent(session, record_id)


def test_shape_drift_is_invalid_and_does_not_replace_current(normalization_database):
    _paths, session, store = normalization_database
    good_payload = _payload(GoogleStream.HEART_RATE)
    _good, first = _persist_result(session, store, good_payload)
    bad_payload = _payload(GoogleStream.HEART_RATE, component=[])
    bad_result = normalize_google_payload(
        bad_payload,
        stream=GoogleStream.HEART_RATE,
        source_identity=_identity(),
        normalization_contract_version="r04-google-normalization-contract-v2",
    )
    failed = GooglePersistenceRepository(session, payload_store=store).persist_result(
        bad_result,
        payload=bad_payload,
        received_at=datetime(2099, 1, 5, tzinfo=UTC),
    )
    session.commit()
    current = session.scalar(
        select(GoogleSourceRecord).where(GoogleSourceRecord.id == first.records[0].id)
    )
    assert failed.records == ()
    assert bad_result.status.value == "invalid"
    assert current is not None
    assert current.normalization_contract_version == NORMALIZATION_CONTRACT_VERSION
    assert session.scalar(select(func.count(GoogleNormalizationAttempt.id))) == 2


def test_versioned_offline_replay_is_deterministic_and_keeps_raw_immutable(normalization_database):
    _paths, session, store = normalization_database
    payload = _payload(GoogleStream.HEART_RATE, data_source=_data_source())
    first_result, first = _persist_result(session, store, payload)
    raw_before = first.raw_payload.normalization_contract_version
    replayed = replay_google_observations(
        session,
        payload_store=store,
        observation_ids=[first.observation.id],
        normalization_contract_version="r04-google-normalization-contract-v2",
    )
    assert len(replayed) == 1
    assert replayed[0].normalization_attempt is not None
    assert replayed[0].normalization_attempt.normalization_contract_version.endswith("v2")
    current = session.scalar(
        select(GoogleSourceRecord).where(GoogleSourceRecord.id == first.records[0].id)
    )
    assert current is not None
    assert current.normalization_contract_version.endswith("v2")
    assert first.raw_payload.normalization_contract_version == raw_before
    second = replay_google_observations(
        session,
        payload_store=store,
        observation_ids=[first.observation.id],
        normalization_contract_version="r04-google-normalization-contract-v2",
    )[0]
    session.commit()
    assert second.replayed is True
    assert (
        second.normalization_attempt.projection_fingerprint
        == replayed[0].normalization_attempt.projection_fingerprint
    )
    assert session.scalar(select(func.count(GoogleNormalizationAttempt.id))) == 2
    assert session.scalar(select(func.count(GooglePayloadObservation.id))) == 2
    assert session.scalar(select(func.count(GoogleRawPayload.id))) == 1


def test_failed_new_version_attempt_keeps_accepted_current(normalization_database):
    _paths, session, store = normalization_database
    payload = _payload(GoogleStream.HEART_RATE)
    good_result, first = _persist_result(session, store, payload)
    invalid_result = GoogleNormalizationResult(
        stream=good_result.stream,
        query=good_result.query,
        status="invalid",
        records=(),
        source_identity=good_result.source_identity,
        normalization_contract_version="r04-google-normalization-contract-v2",
    )
    failed = GooglePersistenceRepository(session, payload_store=store).persist_result(
        invalid_result,
        payload=payload,
        received_at=datetime(2099, 1, 6, tzinfo=UTC),
    )
    session.commit()
    current = session.scalar(
        select(GoogleSourceRecord).where(GoogleSourceRecord.id == first.records[0].id)
    )
    assert failed.records == ()
    assert current is not None
    assert current.normalization_contract_version == NORMALIZATION_CONTRACT_VERSION
    assert session.scalar(select(func.count(GoogleNormalizationAttempt.id))) == 2


def test_google_normalization_never_writes_garmin_or_r03_tables(normalization_database):
    _paths, session, store = normalization_database
    _result, outcome = _persist_result(
        session, store, _payload(GoogleStream.SLEEP), stream=GoogleStream.SLEEP
    )
    session.commit()
    assert session.scalar(select(func.count(GarminSource.id))) == 0
    assert session.scalar(select(func.count(GarminRawPayload.id))) == 0
    assert session.scalar(select(func.count(GarminSourceRecord.id))) == 0
    assert session.scalar(select(func.count(ScalarMeasurement.id))) == 0
    assert session.scalar(select(func.count(DerivedMeasurement.id))) == 0
    assert session.scalar(select(func.count(CanonicalSelectionRun.id))) == 0
    assert session.scalar(select(func.count(CanonicalSelection.id))) == 0
    assert session.scalar(select(func.count(GoogleRecordSourceEvidence.record_id))) == 1
    field_state = session.get(GoogleSleepFieldState, outcome.records[0].id)
    assert field_state is not None
    assert field_state.sleep_interval_state == GoogleMetricState.VALUE.value
    assert field_state.sleep_stages_state == GoogleMetricState.VALUE.value
    assert field_state.out_of_bed_state == GoogleMetricState.VALUE.value
    assert session.scalar(select(func.count(GoogleSleepInterval.id))) == 3
