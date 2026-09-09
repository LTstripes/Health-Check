"""Synthetic regressions for R03-02 Garmin activity session comparison (#69)."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from healthcheck.analytics.garmin_activity_comparison import (
    ACTIVITY_COMPARISON_METRIC_CODES,
    MAX_SELECTED_ACTIVITIES,
    MIN_SELECTED_ACTIVITIES,
    R03_02_ALGORITHM,
    R03_02_RULE_VERSION,
    GarminActivityComparisonError,
    cadence_source_field_is_unambiguous,
    compute_garmin_activity_comparison,
)
from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
from healthcheck.db.models import GarminSourceRecord
from healthcheck.db.repositories import repositories_for
from healthcheck.garmin.analytic_contract import (
    AggregateKind,
    AnalyticInputAssemblyError,
    build_analytic_input_from_storage,
    get_analytic_metric_definition,
)
from healthcheck.garmin.normalization import normalize_garmin_payload
from healthcheck.garmin.persistence import PROJECTION_RETIRED, GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.runtime import prepare_runtime

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "garmin"


@pytest.fixture
def comparison_database(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            yield paths, session, ContentAddressedGarminPayloadStore(paths.root / "artifacts")
    finally:
        engine.dispose()


def _activity_payload(
    *,
    activity_id: str,
    activity_type: str = "cycling",
    day: str = "2099-01-02",
    duration: int | float | None = 3600,
    distance: int | float | None = 21000,
    average_speed: int | float | None = 5.83,
    average_hr: int | float | None = 128,
    avg_power: int | float | None = None,
    cadence: int | float | None = 82,
    cadence_field: str = "averageRunningCadenceInStepsPerMinute",
    training_effect: int | float | None = 2.3,
    training_load: int | float | None = 42,
    fixture_suffix: str = "",
    include_speed: bool = True,
    title: str | None = None,
    gps: dict | None = None,
) -> dict:
    activity: dict = {
        "activityId": activity_id,
        "activityType": {"typeKey": activity_type},
        "startTimeGMT": f"{day}T08:00:00Z",
    }
    if duration is not None:
        activity["duration"] = duration
    if distance is not None:
        activity["distance"] = distance
    if include_speed and average_speed is not None:
        activity["averageSpeed"] = average_speed
    if average_hr is not None:
        activity["averageHR"] = average_hr
    if avg_power is not None or avg_power is None:
        # Explicit null remains a persisted null metric when key present.
        activity["avgPower"] = avg_power
    if cadence is not None:
        if cadence_field == "metrics.cadenceRpm":
            activity.setdefault("metrics", {})["cadenceRpm"] = cadence
        else:
            activity[cadence_field] = cadence
    if training_effect is not None:
        activity["aerobicTrainingEffect"] = training_effect
    if training_load is not None:
        activity["activityTrainingLoad"] = training_load
    if title is not None:
        activity["activityName"] = title
    if gps is not None:
        activity["gps"] = gps
    return {
        "fixture_contract_version": "r02-garmin-capability-fixture-v1",
        "fixture_id": f"synthetic-r03-02-{activity_id}{fixture_suffix}",
        "source_kind": "synthetic",
        "provider_code": "garmin_connect",
        "stream_code": "activity",
        "device": {
            "attributed": True,
            "code": "garmin_vivoactive_5",
            "model": "Vivoactive 5",
        },
        "client_methods": ["get_activities_by_date", "download_activity"],
        "payload_fields": {
            "activities": "activities",
            "cycling_metrics": "activities.0.averageSpeed",
            "training_effect": "activities.0.aerobicTrainingEffect",
            "acute_training_load": "activities.0.activityTrainingLoad",
        },
        "payload": {"activities": [activity]},
    }


def _persist(session, store, payload: dict, *, received_at: datetime | None = None):
    result = normalize_garmin_payload(payload)
    outcome = GarminPersistenceRepository(session, payload_store=store).persist_result(
        result,
        payload=json.dumps(payload, sort_keys=True).encode("utf-8"),
        source_filename=f"{payload['fixture_id']}.json",
        received_at=received_at or datetime(2099, 1, 3, tzinfo=UTC),
        source_contract_version=payload.get("fixture_contract_version"),
    )
    return outcome


def _persist_pair(session, store, left: dict, right: dict):
    first = _persist(session, store, left, received_at=datetime(2099, 1, 3, 1, tzinfo=UTC))
    second = _persist(session, store, right, received_at=datetime(2099, 1, 3, 2, tzinfo=UTC))
    session.commit()
    assert first.records[0].garmin_source_id == second.records[0].garmin_source_id
    return first.records[0], second.records[0]


def _metric_map(session_block):
    return {item.metric_code: item for item in session_block.metric_coverage}


def _delta_map(block):
    return {item.metric_code: item for item in block.metrics}


def test_registry_activity_identities_are_distinct() -> None:
    assert get_analytic_metric_definition("duration_seconds").aggregate_kind is (
        AggregateKind.SESSION_TOTAL
    )
    assert get_analytic_metric_definition("speed_mps").aggregate_kind is (
        AggregateKind.SESSION_AVERAGE
    )
    assert get_analytic_metric_definition("heart_rate_bpm").aggregate_kind is (
        AggregateKind.SESSION_AVERAGE
    )
    assert get_analytic_metric_definition("training_effect").capability_code == "training_effect"
    assert (
        get_analytic_metric_definition("acute_training_load").capability_code
        == "acute_training_load"
    )
    assert not cadence_source_field_is_unambiguous(
        "payload.activities.averageRunningCadenceInStepsPerMinute"
    )
    assert cadence_source_field_is_unambiguous("payload.activities.metrics.cadenceRpm")


def test_selection_bounds_and_rejects(comparison_database) -> None:
    _paths, session, store = comparison_database
    records = []
    for index in range(3):
        outcome = _persist(
            session,
            store,
            _activity_payload(activity_id=f"bound-{index}", duration=1000 + index),
            received_at=datetime(2099, 1, 3, index + 1, tzinfo=UTC),
        )
        records.append(outcome.records[0])
    session.commit()
    source_id = records[0].garmin_source_id

    with pytest.raises(GarminActivityComparisonError) as below:
        compute_garmin_activity_comparison(
            session,
            garmin_source_id=source_id,
            activity_record_ids=[records[0].id],
            reference_activity_id=records[0].id,
        )
    assert below.value.reason_code == "selection_bounds_violated"

    too_many = [records[0].id, records[1].id] + [f"missing-{i}" for i in range(19)]
    with pytest.raises(GarminActivityComparisonError) as above:
        compute_garmin_activity_comparison(
            session,
            garmin_source_id=source_id,
            activity_record_ids=too_many,
            reference_activity_id=records[0].id,
        )
    assert above.value.reason_code == "selection_bounds_violated"
    assert MIN_SELECTED_ACTIVITIES == 2
    assert MAX_SELECTED_ACTIVITIES == 20

    with pytest.raises(GarminActivityComparisonError) as dup:
        compute_garmin_activity_comparison(
            session,
            garmin_source_id=source_id,
            activity_record_ids=[records[0].id, records[0].id],
            reference_activity_id=records[0].id,
        )
    assert dup.value.reason_code == "duplicate_activity_record_ids"

    with pytest.raises(GarminActivityComparisonError) as unknown:
        compute_garmin_activity_comparison(
            session,
            garmin_source_id=source_id,
            activity_record_ids=[records[0].id, "does-not-exist"],
            reference_activity_id=records[0].id,
        )
    assert unknown.value.reason_code == "unknown_activity_record_id"

    other_payload = _activity_payload(activity_id="other-source")
    other_payload["device"] = {"attributed": False}
    other_payload["fixture_id"] = "synthetic-r03-02-other-source"
    other = _persist(
        session,
        store,
        other_payload,
        received_at=datetime(2099, 1, 4, tzinfo=UTC),
    )
    session.commit()
    with pytest.raises(GarminActivityComparisonError) as wrong_source:
        compute_garmin_activity_comparison(
            session,
            garmin_source_id=source_id,
            activity_record_ids=[records[0].id, other.records[0].id],
            reference_activity_id=records[0].id,
        )
    assert wrong_source.value.reason_code == "wrong_source_activity_record"

    # Non-current reject.
    retired = session.get(GarminSourceRecord, records[2].id)
    assert retired is not None
    retired.projection_status = PROJECTION_RETIRED
    retired.retired_at = datetime(2099, 1, 5, tzinfo=UTC)
    retired.retire_reason = "test_retire"
    session.commit()
    with pytest.raises(GarminActivityComparisonError) as non_current:
        compute_garmin_activity_comparison(
            session,
            garmin_source_id=source_id,
            activity_record_ids=[records[0].id, records[2].id],
            reference_activity_id=records[0].id,
        )
    assert non_current.value.reason_code == "non_current_activity_record"

    # Non-activity reject via sleep fixture.
    sleep_payload = json.loads((FIXTURE_ROOT / "sleep.json").read_text(encoding="utf-8"))
    sleep_payload["payload"]["id"] = "sleep-for-non-activity-reject"
    sleep = _persist(session, store, sleep_payload, received_at=datetime(2099, 1, 6, tzinfo=UTC))
    session.commit()
    # Force same source id if possible; otherwise wrong-source still fail-closes.
    sleep_record = sleep.records[0]
    if sleep_record.garmin_source_id != source_id:
        sleep_record.garmin_source_id = source_id
        session.commit()
    with pytest.raises(GarminActivityComparisonError) as non_activity:
        compute_garmin_activity_comparison(
            session,
            garmin_source_id=source_id,
            activity_record_ids=[records[0].id, sleep_record.id],
            reference_activity_id=records[0].id,
        )
    assert non_activity.value.reason_code == "non_activity_record"


def test_stable_ordering_and_result_hash(comparison_database) -> None:
    _paths, session, store = comparison_database
    left, right = _persist_pair(
        session,
        store,
        _activity_payload(activity_id="hash-a", duration=3000, average_speed=5.0),
        _activity_payload(activity_id="hash-b", duration=3600, average_speed=6.0),
    )
    first = compute_garmin_activity_comparison(
        session,
        garmin_source_id=left.garmin_source_id,
        activity_record_ids=[left.id, right.id],
        reference_activity_id=left.id,
    )
    second = compute_garmin_activity_comparison(
        session,
        garmin_source_id=left.garmin_source_id,
        activity_record_ids=[left.id, right.id],
        reference_activity_id=left.id,
    )
    assert first.result_hash == second.result_hash
    assert first.as_dict() == second.as_dict()
    assert first.algorithm == R03_02_ALGORITHM
    assert first.rule_version == R03_02_RULE_VERSION
    assert [item.record_id for item in first.sessions] == [left.id, right.id]
    assert first.sessions[0].external_record_id == "hash-a"
    assert first.sessions[1].external_record_id == "hash-b"
    # Hash excludes itself: body without hash matches.
    body = first.as_dict()
    digest = body.pop("result_hash")
    from healthcheck.garmin.analytic_contract import stable_manifest_hash

    assert stable_manifest_hash(body) == digest


def test_no_aggregation_substitution_or_speed_from_distance_duration(
    comparison_database,
) -> None:
    _paths, session, store = comparison_database
    # Reference has provider speed; compared omits averageSpeed entirely.
    left, right = _persist_pair(
        session,
        store,
        _activity_payload(
            activity_id="speed-ref",
            duration=3600,
            distance=21600,
            average_speed=6.0,
        ),
        _activity_payload(
            activity_id="speed-cmp",
            duration=3600,
            distance=21600,
            include_speed=False,
            average_speed=None,
        ),
    )
    result = compute_garmin_activity_comparison(
        session,
        garmin_source_id=left.garmin_source_id,
        activity_record_ids=[left.id, right.id],
        reference_activity_id=left.id,
    )
    ref_cov = _metric_map(result.sessions[0])
    cmp_cov = _metric_map(result.sessions[1])
    assert ref_cov["speed_mps"].status == "usable"
    assert ref_cov["speed_mps"].value == 6.0
    assert cmp_cov["speed_mps"].status == "missing"
    assert cmp_cov["speed_mps"].value is None
    # Duration/distance still usable independently — no substitution into speed.
    assert cmp_cov["duration_seconds"].status == "usable"
    assert cmp_cov["distance_meters"].status == "usable"
    speed_delta = _delta_map(result.comparisons[0])["speed_mps"]
    assert speed_delta.status == "not_computable"
    assert speed_delta.absolute_delta is None
    # Explicit identities remain distinct.
    assert ref_cov["duration_seconds"].aggregate_kind == AggregateKind.SESSION_TOTAL.value
    assert ref_cov["speed_mps"].aggregate_kind == AggregateKind.SESSION_AVERAGE.value


def test_distinct_availability_states(comparison_database) -> None:
    _paths, session, store = comparison_database
    left, right = _persist_pair(
        session,
        store,
        _activity_payload(
            activity_id="avail-ref",
            duration=0,
            distance=100,
            average_speed=5.0,
            average_hr=120,
            avg_power=None,
            cadence=90,
            cadence_field="metrics.cadenceRpm",
        ),
        _activity_payload(
            activity_id="avail-cmp",
            duration=3600,
            distance=0,
            average_speed=None,
            include_speed=False,
            average_hr=None,
            avg_power=180,
            cadence=None,
            training_effect=None,
            training_load=50,
        ),
    )
    result = compute_garmin_activity_comparison(
        session,
        garmin_source_id=left.garmin_source_id,
        activity_record_ids=[left.id, right.id],
        reference_activity_id=left.id,
    )
    ref = _metric_map(result.sessions[0])
    cmp = _metric_map(result.sessions[1])
    assert ref["duration_seconds"].status == "zero"
    assert ref["duration_seconds"].is_zero is True
    assert cmp["distance_meters"].status == "zero"
    assert ref["power_watts"].status == "null"
    assert cmp["power_watts"].status == "usable"
    assert cmp["speed_mps"].status == "missing"
    assert cmp["heart_rate_bpm"].status == "missing"
    assert cmp["training_effect"].status == "missing"
    # Cadence on ref is unambiguous RPM and usable; compared missing.
    assert ref["cadence_rpm"].status == "usable"
    assert cmp["cadence_rpm"].status == "missing"
    assert result.coverage.zero_count >= 2
    assert result.coverage.null_count >= 1
    assert result.coverage.missing_count >= 1


def test_absolute_and_percent_deltas_with_signs(comparison_database) -> None:
    _paths, session, store = comparison_database
    left, right = _persist_pair(
        session,
        store,
        _activity_payload(
            activity_id="delta-ref",
            duration=3000,
            distance=10000,
            average_speed=5.0,
            average_hr=120,
            avg_power=150,
            cadence=80,
            cadence_field="metrics.cadenceRpm",
            training_effect=2.0,
            training_load=40,
        ),
        _activity_payload(
            activity_id="delta-cmp",
            duration=3600,
            distance=10000,
            average_speed=4.0,
            average_hr=120,
            avg_power=180,
            cadence=90,
            cadence_field="metrics.cadenceRpm",
            training_effect=3.0,
            training_load=40,
        ),
    )
    result = compute_garmin_activity_comparison(
        session,
        garmin_source_id=left.garmin_source_id,
        activity_record_ids=[left.id, right.id],
        reference_activity_id=left.id,
    )
    deltas = _delta_map(result.comparisons[0])
    assert deltas["duration_seconds"].status == "compared"
    assert deltas["duration_seconds"].absolute_delta == 600
    assert deltas["duration_seconds"].percent_delta == 20.0
    assert deltas["duration_seconds"].percent_status == "computed"
    assert deltas["distance_meters"].absolute_delta == 0
    assert deltas["distance_meters"].percent_delta == 0.0
    assert deltas["speed_mps"].absolute_delta == -1.0
    assert deltas["speed_mps"].percent_delta == -20.0
    assert deltas["heart_rate_bpm"].absolute_delta == 0
    assert deltas["power_watts"].absolute_delta == 30
    assert deltas["training_effect"].absolute_delta == 1.0
    assert deltas["acute_training_load"].absolute_delta == 0


def test_zero_reference_percent_not_computable(comparison_database) -> None:
    _paths, session, store = comparison_database
    left, right = _persist_pair(
        session,
        store,
        _activity_payload(activity_id="zero-ref", duration=0, distance=0, average_speed=0.0),
        _activity_payload(activity_id="zero-cmp", duration=100, distance=50, average_speed=1.0),
    )
    result = compute_garmin_activity_comparison(
        session,
        garmin_source_id=left.garmin_source_id,
        activity_record_ids=[left.id, right.id],
        reference_activity_id=left.id,
    )
    deltas = _delta_map(result.comparisons[0])
    for code in ("duration_seconds", "distance_meters", "speed_mps"):
        assert deltas[code].status == "compared"
        assert deltas[code].absolute_delta is not None
        assert deltas[code].percent_status == "not_computable"
        assert deltas[code].percent_reason == "zero_reference_percent"
        assert deltas[code].percent_delta is None


def test_missing_power_only_affects_power(comparison_database) -> None:
    _paths, session, store = comparison_database
    left, right = _persist_pair(
        session,
        store,
        _activity_payload(activity_id="pwr-ref", avg_power=200, duration=3600),
        _activity_payload(activity_id="pwr-cmp", avg_power=None, duration=4000),
    )
    result = compute_garmin_activity_comparison(
        session,
        garmin_source_id=left.garmin_source_id,
        activity_record_ids=[left.id, right.id],
        reference_activity_id=left.id,
    )
    assert len(result.sessions) == 2
    deltas = _delta_map(result.comparisons[0])
    assert deltas["power_watts"].status == "not_computable"
    assert deltas["duration_seconds"].status == "compared"
    assert deltas["duration_seconds"].absolute_delta == 400
    assert _metric_map(result.sessions[1])["power_watts"].status == "null"


def test_different_activity_type_surfaced_not_normalized(comparison_database) -> None:
    _paths, session, store = comparison_database
    left, right = _persist_pair(
        session,
        store,
        _activity_payload(activity_id="type-cycle", activity_type="cycling"),
        _activity_payload(activity_id="type-run", activity_type="running"),
    )
    result = compute_garmin_activity_comparison(
        session,
        garmin_source_id=left.garmin_source_id,
        activity_record_ids=[left.id, right.id],
        reference_activity_id=left.id,
    )
    assert result.sessions[0].activity_type == "cycling"
    assert result.sessions[1].activity_type == "running"
    assert result.comparisons[0].same_activity_type is False
    assert result.comparisons[0].metrics[0].same_activity_type is False
    # Still comparable on shared metrics; flag only, no sport-family invention.
    assert _delta_map(result.comparisons[0])["duration_seconds"].status == "compared"


def test_aggregation_mismatch_not_comparable(comparison_database) -> None:
    from healthcheck.analytics.garmin_activity_comparison import (
        SessionMetricCoverage,
        _compare_metric,
    )

    _paths, session, store = comparison_database
    left, right = _persist_pair(
        session,
        store,
        _activity_payload(activity_id="agg-ref", duration=3000),
        _activity_payload(activity_id="agg-cmp", duration=3600),
    )
    result = compute_garmin_activity_comparison(
        session,
        garmin_source_id=left.garmin_source_id,
        activity_record_ids=[left.id, right.id],
        reference_activity_id=left.id,
        metric_codes=("duration_seconds", "speed_mps"),
    )
    duration = _delta_map(result.comparisons[0])["duration_seconds"]
    speed = _delta_map(result.comparisons[0])["speed_mps"]
    assert duration.aggregate_kind == AggregateKind.SESSION_TOTAL.value
    assert speed.aggregate_kind == AggregateKind.SESSION_AVERAGE.value
    assert duration.unit == "seconds"
    assert speed.unit == "m/s"

    # Even with matching numeric magnitude/units-looking values, mismatched
    # aggregation/window identities are not comparable.
    reference = SessionMetricCoverage(
        metric_code="duration_seconds",
        status="usable",
        value=3000,
        is_zero=False,
        unit="seconds",
        aggregate_kind=AggregateKind.SESSION_TOTAL.value,
        window="activity_session",
        field_path="payload.activities.duration",
        reason=None,
        input_manifest_hash="a" * 64,
        metric_row_id="m1",
        comparable=True,
    )
    compared_mismatched = SessionMetricCoverage(
        metric_code="duration_seconds",
        status="usable",
        value=3000,
        is_zero=False,
        unit="seconds",
        aggregate_kind=AggregateKind.SESSION_AVERAGE.value,
        window="activity_session",
        field_path="payload.activities.duration",
        reason="aggregation_mismatch",
        input_manifest_hash="b" * 64,
        metric_row_id="m2",
        comparable=False,
    )
    mismatched = _compare_metric(
        metric_code="duration_seconds",
        reference=reference,
        compared=compared_mismatched,
        reference_activity_type="cycling",
        compared_activity_type="cycling",
    )
    assert mismatched.status == "not_computable"
    assert "aggregation_mismatch" in (mismatched.reason or "")


def test_provider_native_scores_not_merged(comparison_database) -> None:
    _paths, session, store = comparison_database
    left, right = _persist_pair(
        session,
        store,
        _activity_payload(activity_id="score-ref", training_effect=2.0, training_load=40),
        _activity_payload(activity_id="score-cmp", training_effect=3.0, training_load=55),
    )
    result = compute_garmin_activity_comparison(
        session,
        garmin_source_id=left.garmin_source_id,
        activity_record_ids=[left.id, right.id],
        reference_activity_id=left.id,
    )
    te = _delta_map(result.comparisons[0])["training_effect"]
    atl = _delta_map(result.comparisons[0])["acute_training_load"]
    assert te.status == "compared"
    assert atl.status == "compared"
    assert te.reference_value == 2.0
    assert te.compared_value == 3.0
    assert atl.absolute_delta == 15
    # No combined custom score field in result.
    payload = result.as_dict()
    blob = json.dumps(payload)
    assert "readiness" not in blob.lower()
    assert "custom_score" not in blob.lower()
    assert "fitness" not in blob.lower()
    assert te.metric_code != atl.metric_code


def test_correction_freezes_old_serialized_result(comparison_database) -> None:
    _paths, session, store = comparison_database
    first_payload = _activity_payload(activity_id="freeze-1", duration=3000, average_speed=5.0)
    first = _persist(session, store, first_payload, received_at=datetime(2099, 1, 3, tzinfo=UTC))
    second_payload = _activity_payload(activity_id="freeze-2", duration=3600, average_speed=6.0)
    second = _persist(
        session, store, second_payload, received_at=datetime(2099, 1, 3, 1, tzinfo=UTC)
    )
    session.commit()
    original = compute_garmin_activity_comparison(
        session,
        garmin_source_id=first.records[0].garmin_source_id,
        activity_record_ids=[first.records[0].id, second.records[0].id],
        reference_activity_id=first.records[0].id,
    )
    frozen = copy.deepcopy(original.as_dict())
    original_hash = frozen["result_hash"]
    original_manifest = next(
        item["manifest_hash"]
        for item in frozen["frozen_inputs"]
        if item["selected"]["metric_code"] == "duration_seconds"
        and item["evidence"]["record_id"] == first.records[0].id
    )
    original_content = next(
        item["evidence"]["content_hash"]
        for item in frozen["frozen_inputs"]
        if item["evidence"]["record_id"] == first.records[0].id
    )

    corrected = _activity_payload(
        activity_id="freeze-1",
        duration=3300,
        average_speed=5.5,
        fixture_suffix="-corrected",
    )
    updated = _persist(session, store, corrected, received_at=datetime(2099, 1, 4, tzinfo=UTC))
    session.commit()
    assert updated.records[0].id == first.records[0].id
    rebuilt = compute_garmin_activity_comparison(
        session,
        garmin_source_id=first.records[0].garmin_source_id,
        activity_record_ids=[first.records[0].id, second.records[0].id],
        reference_activity_id=first.records[0].id,
    )
    assert rebuilt.result_hash != original_hash
    new_duration = _metric_map(rebuilt.sessions[0])["duration_seconds"].value
    assert new_duration == 3300
    assert frozen["result_hash"] == original_hash
    assert (
        next(
            item["selected"]["value"]
            for item in frozen["frozen_inputs"]
            if item["selected"]["metric_code"] == "duration_seconds"
            and item["evidence"]["record_id"] == first.records[0].id
        )
        == 3000
    )
    assert (
        next(
            item["manifest_hash"]
            for item in frozen["frozen_inputs"]
            if item["selected"]["metric_code"] == "duration_seconds"
            and item["evidence"]["record_id"] == first.records[0].id
        )
        == original_manifest
    )
    assert (
        next(
            item["evidence"]["content_hash"]
            for item in frozen["frozen_inputs"]
            if item["evidence"]["record_id"] == first.records[0].id
        )
        == original_content
    )


def test_provenance_fail_closed(comparison_database) -> None:
    _paths, session, store = comparison_database
    payload = _activity_payload(activity_id="prov-1", duration=3000)
    payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    result_v1 = normalize_garmin_payload(payload)
    repository = GarminPersistenceRepository(session, payload_store=store)
    source = repository.sources.get_or_create(result_v1.source)
    provenance = repositories_for(session)
    first_run = provenance.sync.create_run(
        provider_id=source.provider_id,
        acquisition_source_id=source.acquisition_source_id,
        stream_code="activity",
        requested_start=datetime(2099, 1, 1, tzinfo=UTC),
        requested_end=datetime(2099, 1, 3, tzinfo=UTC),
    )
    second_run = provenance.sync.create_run(
        provider_id=source.provider_id,
        acquisition_source_id=source.acquisition_source_id,
        stream_code="activity",
        requested_start=datetime(2099, 1, 2, tzinfo=UTC),
        requested_end=datetime(2099, 1, 4, tzinfo=UTC),
    )
    first = repository.persist_result(
        result_v1,
        payload=payload_bytes,
        source_filename="activity-window-1.json",
        received_at=datetime(2099, 1, 3, 12, tzinfo=UTC),
        source_window_start_utc=datetime(2099, 1, 1, tzinfo=UTC),
        source_window_end_utc=datetime(2099, 1, 3, tzinfo=UTC),
        sync_run_id=first_run.id,
        source_contract_version=payload["fixture_contract_version"],
    )
    session.commit()
    observation_a = first.observation.id
    companion = _persist(
        session,
        store,
        _activity_payload(activity_id="prov-2", duration=3600),
        received_at=datetime(2099, 1, 3, 13, tzinfo=UTC),
    )
    session.commit()
    result_v2 = replace(result_v1, contract_version="r02-garmin-normalization-contract-v2")
    second = repository.persist_result(
        result_v2,
        payload=payload_bytes,
        source_filename="activity-window-2.json",
        received_at=datetime(2099, 1, 4, 12, tzinfo=UTC),
        source_window_start_utc=datetime(2099, 1, 2, tzinfo=UTC),
        source_window_end_utc=datetime(2099, 1, 4, tzinfo=UTC),
        sync_run_id=second_run.id,
        source_contract_version=payload["fixture_contract_version"],
    )
    session.commit()
    record = session.get(GarminSourceRecord, first.records[0].id)
    assert record is not None
    assert record.ingest_event_id == second.ingest_event_id

    with pytest.raises(AnalyticInputAssemblyError, match="ingest event"):
        build_analytic_input_from_storage(
            session,
            record_id=record.id,
            metric_code="duration_seconds",
            observation_id=observation_a,
            operational_surface_present=True,
        )

    # Comparison path uses fail-closed assembler for current rows without stale obs.
    result = compute_garmin_activity_comparison(
        session,
        garmin_source_id=record.garmin_source_id,
        activity_record_ids=[record.id, companion.records[0].id],
        reference_activity_id=record.id,
    )
    assert result.coverage.usable_count >= 1
    assert all(item.get("manifest_hash") for item in result.frozen_inputs)


def test_no_gps_name_private_in_result_fixtures(comparison_database) -> None:
    _paths, session, store = comparison_database
    left, right = _persist_pair(
        session,
        store,
        _activity_payload(
            activity_id="priv-ref",
            title="Secret Morning Ride near Home",
            gps={"lat": 55.75, "lon": 37.61, "route": "private-polyline"},
        ),
        _activity_payload(
            activity_id="priv-cmp",
            title="Another Private Loop",
            gps={"lat": 55.76, "lon": 37.62},
        ),
    )
    result = compute_garmin_activity_comparison(
        session,
        garmin_source_id=left.garmin_source_id,
        activity_record_ids=[left.id, right.id],
        reference_activity_id=left.id,
    )
    blob = json.dumps(result.as_dict())
    assert "Secret Morning Ride" not in blob
    assert "private-polyline" not in blob
    assert "55.75" not in blob
    assert "37.61" not in blob
    assert "activityName" not in blob
    assert "gps" not in blob.lower() or '"gps"' not in blob
    # Comparability must not depend on titles.
    assert result.comparisons[0].same_activity_type is True


def test_ambiguous_running_cadence_is_unsupported(comparison_database) -> None:
    _paths, session, store = comparison_database
    left, right = _persist_pair(
        session,
        store,
        _activity_payload(
            activity_id="cad-ref",
            cadence=90,
            cadence_field="averageRunningCadenceInStepsPerMinute",
        ),
        _activity_payload(
            activity_id="cad-cmp",
            cadence=95,
            cadence_field="averageRunningCadenceInStepsPerMinute",
        ),
    )
    result = compute_garmin_activity_comparison(
        session,
        garmin_source_id=left.garmin_source_id,
        activity_record_ids=[left.id, right.id],
        reference_activity_id=left.id,
    )
    ref_cad = _metric_map(result.sessions[0])["cadence_rpm"]
    assert ref_cad.status == "unsupported"
    assert ref_cad.reason == "ambiguous_cadence_source_field"
    assert ref_cad.comparable is False
    assert _delta_map(result.comparisons[0])["cadence_rpm"].status == "not_computable"


def test_all_reviewed_metric_codes_listed() -> None:
    assert ACTIVITY_COMPARISON_METRIC_CODES == (
        "duration_seconds",
        "distance_meters",
        "speed_mps",
        "heart_rate_bpm",
        "power_watts",
        "cadence_rpm",
        "training_effect",
        "acute_training_load",
    )
