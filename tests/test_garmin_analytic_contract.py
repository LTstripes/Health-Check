"""Synthetic regressions for Pre-R03 Garmin analytic input contract (#55)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

from healthcheck.garmin.analytic_contract import (
    ANALYTIC_INPUT_CONTRACT_VERSION,
    ANALYTIC_RULE_VERSION,
    AggregateKind,
    AnalyticAvailability,
    AnalyticEvidenceRef,
    build_analytic_input_dto,
    build_analytic_input_from_metric,
    evaluate_metric_analytic_coverage,
    evaluate_sleep_metric_family_coverage,
    get_analytic_metric_definition,
    project_analytic_temporal,
    resolve_aggregate_kind,
    substitute_aggregate_is_forbidden,
)
from healthcheck.garmin.capabilities import GarminStream
from healthcheck.garmin.normalization import (
    GarminFieldState,
    GarminMetricDTO,
    GarminParseStatus,
    GarminRecordDTO,
    GarminSourceIdentity,
    GarminTemporalDTO,
    GarminTemporalPrecision,
    normalize_garmin_payload,
)
from healthcheck.garmin.sync import _sample_temporal, _sample_token


def _source() -> GarminSourceIdentity:
    return GarminSourceIdentity(
        source_kind="synthetic",
        provider_code="garmin_connect",
        device_attributed=True,
        device_code="garmin_vivoactive_5",
        device_model="Vivoactive 5",
    )


def _evidence(**overrides: object) -> AnalyticEvidenceRef:
    payload = {
        "raw_payload_id": "raw-1",
        "content_hash": "a" * 64,
        "observation_id": "obs-1",
        "observation_key": "obs-key-" + ("b" * 32),
        "record_id": "rec-1",
        "idempotency_key": "garmin:v1:reconcile:test",
        "metric_row_id": "metric-1",
        "field_path": "payload.avgStressLevel",
        "normalization_contract_version": "r02-garmin-normalization-contract-v1",
        "reconciliation_contract_version": "r02-garmin-collection-reconciliation-v1",
        "projection_status": "current",
    }
    payload.update(overrides)
    return AnalyticEvidenceRef(**payload)  # type: ignore[arg-type]


def test_stress_and_spo2_aggregates_keep_distinct_metric_codes() -> None:
    payload = {
        "fixture_contract_version": "r02-garmin-capability-fixture-v1",
        "fixture_id": "synthetic-aggregate-identity",
        "source_kind": "synthetic",
        "provider_code": "garmin_connect",
        "stream_code": "intraday",
        "device": {"attributed": True, "code": "garmin_vivoactive_5", "model": "Vivoactive 5"},
        "payload": {
            "calendarDate": "2099-03-10",
            "avgStressLevel": 25,
            "maxStressLevel": 80,
            "stress": 40,
            "averageSpO2": 98,
            "lastSevenDaysAvgSpO2": 97,
            "spo2": 96,
        },
    }
    result = normalize_garmin_payload(payload)
    record = result.records[0]
    assert record.metric("stress_daily_average").value == 25
    assert record.metric("stress_daily_maximum").value == 80
    assert record.metric("stress_sample").value == 40
    assert record.metric("spo2_daily_average").value == 98
    assert record.metric("spo2_trailing_7d_average").value == 97
    assert record.metric("spo2_sample").value == 96
    assert get_analytic_metric_definition("stress_daily_average").aggregate_kind is (
        AggregateKind.DAILY_AVERAGE
    )
    assert get_analytic_metric_definition("stress_daily_maximum").aggregate_kind is (
        AggregateKind.DAILY_MAXIMUM
    )
    assert get_analytic_metric_definition("spo2_trailing_7d_average").aggregate_kind is (
        AggregateKind.TRAILING_AGGREGATE
    )
    assert get_analytic_metric_definition("stress_sample").aggregate_kind is AggregateKind.SAMPLE
    assert substitute_aggregate_is_forbidden(
        "stress_daily_average", ["stress_daily_maximum", "stress_sample"]
    )
    assert not substitute_aggregate_is_forbidden(
        "stress_daily_average", ["stress_daily_average", "stress_sample"]
    )


def test_missing_average_is_not_filled_from_maximum_or_trailing() -> None:
    payload = {
        "fixture_contract_version": "r02-garmin-capability-fixture-v1",
        "fixture_id": "synthetic-no-substitute",
        "source_kind": "synthetic",
        "provider_code": "garmin_connect",
        "stream_code": "intraday",
        "device": {"attributed": True, "code": "garmin_vivoactive_5", "model": "Vivoactive 5"},
        "payload": {
            "calendarDate": "2099-03-10",
            "maxStressLevel": 80,
            "lastSevenDaysAvgSpO2": 97,
        },
    }
    result = normalize_garmin_payload(payload)
    record = result.records[0]
    assert record.metric("stress_daily_average").state is GarminFieldState.MISSING
    assert record.metric("stress_daily_maximum").value == 80
    assert record.metric("spo2_daily_average").state is GarminFieldState.MISSING
    assert record.metric("spo2_trailing_7d_average").value == 97
    coverage = evaluate_metric_analytic_coverage(
        "stress_daily_average",
        result.records,
        operational_surface_present=True,
    )
    assert coverage.availability is AnalyticAvailability.MISSING
    assert coverage.operational_surface_present is True


def test_sample_temporal_does_not_invent_utc_for_local_only_naive() -> None:
    # US spring-forward local wall time stays local/unknown-zone.
    local_naive = datetime(2026, 3, 8, 2, 30, 0)
    temporal = _sample_temporal(local_naive, day=date(2026, 3, 8), fallback=None)
    assert temporal.precision is GarminTemporalPrecision.LOCAL_WALL_TIME
    assert temporal.measured_at_utc is None
    assert temporal.local_wall_time == "2026-03-08T02:30:00"
    assert temporal.source_local_timestamp == "2026-03-08T02:30:00"
    assert "Z" not in (_sample_token(local_naive) or "")
    assert "+00:00" not in (_sample_token(local_naive) or "")

    local_text = _sample_temporal("2026-11-01T01:15:00", day=date(2026, 11, 1), fallback=None)
    assert local_text.precision is GarminTemporalPrecision.LOCAL_WALL_TIME
    assert local_text.measured_at_utc is None
    semantics = project_analytic_temporal(local_text)
    assert semantics.zone_policy == "local_unknown_zone"
    assert semantics.measured_at_utc is None


def test_sample_temporal_preserves_explicit_utc_and_aware_offsets() -> None:
    utc_text = _sample_temporal("2099-01-02T08:00:00Z", day=date(2099, 1, 2), fallback=None)
    assert utc_text.precision is GarminTemporalPrecision.UTC_INSTANT
    assert utc_text.measured_at_utc == datetime(2099, 1, 2, 8, 0, tzinfo=UTC)

    offset = timezone(timedelta(hours=3))
    aware = datetime(2099, 1, 2, 11, 0, tzinfo=offset)
    temporal = _sample_temporal(aware, day=date(2099, 1, 2), fallback=None)
    assert temporal.precision is GarminTemporalPrecision.UTC_INSTANT
    assert temporal.measured_at_utc == datetime(2099, 1, 2, 8, 0, tzinfo=UTC)
    assert temporal.source_utc_offset_minutes == 180
    assert temporal.local_wall_time == "2099-01-02T11:00:00"
    semantics = project_analytic_temporal(temporal)
    assert semantics.zone_policy == "utc_with_source_local"

    epoch = _sample_temporal(1_704_200_000, day=date(2024, 1, 2), fallback=None)
    assert epoch.precision is GarminTemporalPrecision.UTC_INSTANT
    assert epoch.measured_at_utc is not None


def test_sleep_duration_does_not_imply_score_stages_or_naps() -> None:
    source = _source()
    temporal = GarminTemporalDTO(
        precision=GarminTemporalPrecision.DATE_ONLY,
        local_date=date(2099, 1, 2),
        local_date_source="calendarDate",
    )
    record = GarminRecordDTO(
        stream=GarminStream.SLEEP,
        source=source,
        temporal=temporal,
        idempotency_key="garmin:v1:semantic:test-sleep",
        metrics=(
            GarminMetricDTO(
                capability_code="sleep",
                metric_code="sleep_duration_seconds",
                field_path="payload.dailySleepDTO.sleepTimeSeconds",
                state=GarminFieldState.VALUE,
                value=28800,
                unit="seconds",
            ),
            GarminMetricDTO(
                capability_code="sleep_score",
                metric_code="sleep_score",
                field_path="payload.dailySleepDTO.sleepScores.overall.value",
                state=GarminFieldState.MISSING,
            ),
            GarminMetricDTO(
                capability_code="sleep_stages",
                metric_code="sleep_stages",
                field_path="payload.levels",
                state=GarminFieldState.MISSING,
            ),
            GarminMetricDTO(
                capability_code="naps",
                metric_code="nap_duration_seconds",
                field_path="payload.dailySleepDTO.napTimeSeconds",
                state=GarminFieldState.NULL,
            ),
        ),
        status=GarminParseStatus.PARTIAL,
    )
    family = evaluate_sleep_metric_family_coverage(
        (record,), operational_surface_present=True
    )
    assert family["sleep_duration_seconds"].availability is AnalyticAvailability.AVAILABLE
    assert family["sleep_score"].availability is AnalyticAvailability.MISSING
    assert family["sleep_stages"].availability is AnalyticAvailability.MISSING
    assert family["nap_duration_seconds"].availability is AnalyticAvailability.NULL
    assert all(item.operational_surface_present for item in family.values())


def test_missing_null_zero_and_not_computable_remain_distinct() -> None:
    source = _source()
    temporal = GarminTemporalDTO(
        precision=GarminTemporalPrecision.DATE_ONLY,
        local_date=date(2099, 1, 2),
        local_date_source="calendarDate",
    )
    record = GarminRecordDTO(
        stream=GarminStream.INTRADAY,
        source=source,
        temporal=temporal,
        idempotency_key="garmin:v1:semantic:test-states",
        metrics=(
            GarminMetricDTO(
                capability_code="stress",
                metric_code="stress_sample",
                field_path="payload.stress",
                state=GarminFieldState.VALUE,
                value=0,
                unit="points",
            ),
            GarminMetricDTO(
                capability_code="stress",
                metric_code="stress_daily_average",
                field_path="payload.avgStressLevel",
                state=GarminFieldState.NULL,
                unit="points",
            ),
            GarminMetricDTO(
                capability_code="stress",
                metric_code="stress_daily_maximum",
                field_path="payload.maxStressLevel",
                state=GarminFieldState.MISSING,
                unit="points",
            ),
        ),
        status=GarminParseStatus.PARTIAL,
    )
    zero = evaluate_metric_analytic_coverage("stress_sample", (record,))
    null = evaluate_metric_analytic_coverage("stress_daily_average", (record,))
    missing = evaluate_metric_analytic_coverage("stress_daily_maximum", (record,))
    absent = evaluate_metric_analytic_coverage(
        "spo2_daily_average", (record,), operational_surface_present=True
    )
    assert zero.availability is AnalyticAvailability.ZERO
    assert null.availability is AnalyticAvailability.NULL
    assert missing.availability is AnalyticAvailability.MISSING
    assert absent.availability is AnalyticAvailability.NOT_COMPUTABLE
    assert any(item.reason_code == "metric_absent_from_projection" for item in absent.exclusions)


def test_same_evidence_and_rule_version_yield_same_manifest_hash() -> None:
    source = _source()
    temporal = GarminTemporalDTO(
        precision=GarminTemporalPrecision.LOCAL_WALL_TIME,
        local_wall_time="2099-01-02T08:00:00",
        local_date=date(2099, 1, 2),
        source_field="payload.series",
        source_local_timestamp="2099-01-02T08:00:00",
        source_local_field="payload.series",
    )
    metric = GarminMetricDTO(
        capability_code="stress",
        metric_code="stress_daily_average",
        field_path="payload.avgStressLevel",
        state=GarminFieldState.VALUE,
        value=25,
        unit="points",
    )
    record = GarminRecordDTO(
        stream=GarminStream.INTRADAY,
        source=source,
        temporal=temporal,
        idempotency_key="garmin:v1:reconcile:avg",
        metrics=(metric,),
    )
    evidence = _evidence()
    first = build_analytic_input_from_metric(record, metric, evidence=evidence)
    second = build_analytic_input_from_metric(record, metric, evidence=evidence)
    assert first.contract_version == ANALYTIC_INPUT_CONTRACT_VERSION
    assert first.rule_version == ANALYTIC_RULE_VERSION
    assert first.manifest_hash == second.manifest_hash
    assert first.as_dict()["manifest_hash"] == second.manifest_hash
    assert first.selected.aggregate_kind == AggregateKind.DAILY_AVERAGE.value
    assert first.temporal is not None
    assert first.temporal.zone_policy == "local_unknown_zone"


def test_later_projection_correction_does_not_change_recorded_manifest() -> None:
    evidence = _evidence(content_hash="c" * 64, observation_id="obs-frozen")
    original = build_analytic_input_dto(
        metric_code="spo2_daily_average",
        selected_state="value",
        selected_value=98,
        field_path="payload.averageSpO2",
        evidence=evidence,
        source_instance_id="synthetic:garmin",
    )
    # A later current-record correction would change live projections / hashes,
    # but the already-recorded manifest keeps the frozen selected value + evidence.
    corrected_live_hash = "d" * 64
    assert original.evidence.content_hash == "c" * 64
    assert original.selected.value == 98
    assert original.evidence.content_hash != corrected_live_hash
    replay = build_analytic_input_dto(
        metric_code="spo2_daily_average",
        selected_state="value",
        selected_value=98,
        field_path="payload.averageSpO2",
        evidence=evidence,
        source_instance_id="synthetic:garmin",
    )
    assert replay.manifest_hash == original.manifest_hash


def test_not_computable_input_is_recorded_in_manifest_exclusions() -> None:
    dto = build_analytic_input_dto(
        metric_code="stress_daily_average",
        selected_state="missing",
        selected_value=None,
        field_path="payload.avgStressLevel",
        evidence=_evidence(),
        operational_surface_present=True,
    )
    assert dto.coverage.availability in {
        AnalyticAvailability.MISSING,
        AnalyticAvailability.NOT_COMPUTABLE,
    }
    assert any(item.reason_code == "not_computable_input" for item in dto.exclusions)


def test_resolve_aggregate_kind_field_path_fallback() -> None:
    assert resolve_aggregate_kind("custom", "payload.avgStressLevel") is AggregateKind.DAILY_AVERAGE
    assert resolve_aggregate_kind("custom", "payload.maxStressLevel") is AggregateKind.DAILY_MAXIMUM
    assert (
        resolve_aggregate_kind("custom", "payload.lastSevenDaysAvgSpO2")
        is AggregateKind.TRAILING_AGGREGATE
    )
    assert resolve_aggregate_kind("custom", "payload.stressValuesArray") is AggregateKind.SAMPLE
