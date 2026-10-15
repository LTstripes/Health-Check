"""#357: one saved Garmin daily stress mean versus its preceding 28 dates.

R03 owns selection and statistics. This adapter only proves comparability and
completion for the referenced evidence, then subtracts the historical median.
No record-wide parse-status gate: unrelated sibling metrics may be partial.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from healthcheck.analytics.garmin_baselines import (
    R03_01_ALGORITHM,
    R03_01_QUANTILE_METHOD,
    R03_01_STRESS_RULE_VERSION,
    STRESS_APPLICABILITY_VERSION,
    GarminScalarAnalyticsError,
    GarminSeriesQuery,
    analyze_garmin_metric_series,
)
from healthcheck.db.models import (
    GarminPayloadObservation,
    GarminRawPayload,
    GarminRecordMetric,
    GarminSource,
    GarminSourceRecord,
    IngestBatch,
    IngestEvent,
    Provider,
    RawArtifact,
    SyncRun,
)
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.garmin.analytic_contract import (
    AnalyticInputAssemblyError,
    coerce_selected_number,
    stable_manifest_hash,
)
from healthcheck.garmin.normalization import (
    _COMMON_TIME_PATHS,
    _PAIRED_UTC_TIME_PATHS,
    _UTC_OFFSET_PATHS,
    _parse_source_offset,
    parse_garmin_time,
)
from healthcheck.garmin.persistence import build_garmin_observation_key
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.web.read_snapshot import ensure_read_snapshot

CONTRACT_VERSION = "garmin-daily-stress-personal-baseline-v2"
POLICY_CONTRACT_VERSION = "garmin-daily-stress-personal-baseline-v3"
MOSCOW_ANALYSIS_DAY_POLICY = "owner-selected-europe-moscow-analysis-day-v1"
_ANALYSIS_ZONE = "Europe/Moscow"
METRIC_CODE = "stress_daily_average"
MIN_HISTORY_DAYS = 21
MAX_ARTIFACT_BYTES = 1024 * 1024
# At most one current + 28 historical daily participants. No history/raw scan.
MAX_PARTICIPANTS = 29
_VALUE_STATES = {"usable", "zero"}
_PARTICIPATING_STATES = _VALUE_STATES | {"partial"}
_TIMEZONE_FIELDS = ("timeZone", "timezone", "timeZoneId", "timezoneId", "zone", "sourceTimezone")
# Exact stress equivalence inspected at #319 commit 4a7bc96d7940c2e5161a210de2c179641bfa2aa6:
# avgStressLevel/finite-number/points, local calendar day, coverage-v1 unchanged.
# _scalar_capability_status delegates to the unchanged helper for stress.
_NORMALIZATION_VERSIONS = {
    "r02-garmin-normalization-contract-v1",
    "r02-garmin-normalization-contract-v2",
}
_INPUT_RULES = {"r03-garmin-analytic-rules-v1", "r03-garmin-analytic-rules-v2"}
_RECONCILIATION_VERSION = "r02-garmin-collection-reconciliation-v1"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("non-JSON numeric constant")


def _day_end(day: date, zone: ZoneInfo) -> datetime | None:
    """Last valid next-midnight fold; a skipped midnight remains unproven."""
    wall = datetime.combine(day + timedelta(days=1), time())
    candidates = []
    for fold in (0, 1):
        instant = wall.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        if instant.astimezone(zone).replace(tzinfo=None) == wall:
            candidates.append(instant)
    return max(candidates) if candidates else None


def _source_clock_reason(record, original, zone):
    """Reconcile only supplied clock evidence, at its instant (including DST)."""
    offsets = [
        _parse_source_offset(key, original[key]) for key in _UTC_OFFSET_PATHS if key in original
    ]
    if any(offset is None for offset in offsets):
        return "source_timezone_offset_unproven"
    if record.source_utc_offset_minutes is not None:
        offsets.append(record.source_utc_offset_minutes)
    if len(set(offsets)) > 1:
        return "source_timezone_conflict"
    offset = offsets[0] if offsets else None
    instant = restore_stored_utc(record.source_timestamp_utc)
    if instant is not None and offset is not None:
        if instant.astimezone(zone).utcoffset() != timedelta(minutes=offset):
            return "source_timezone_conflict"
    if record.local_wall_time:
        try:
            wall = datetime.fromisoformat(record.local_wall_time)
        except ValueError:
            return "source_local_clock_unproven"
        if wall.tzinfo is not None:
            return "source_local_clock_unproven"
        if instant is not None:
            if instant.astimezone(zone).replace(tzinfo=None) != wall:
                return "source_timezone_conflict"
        else:
            candidates = [wall.replace(tzinfo=zone, fold=fold) for fold in (0, 1)]
            if not any(
                candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == wall
                and (offset is None or candidate.utcoffset() == timedelta(minutes=offset))
                for candidate in candidates
            ):
                return "source_timezone_conflict"
    elif instant is None and offset is not None:
        return "source_timezone_offset_unproven"
    return None


def _policy_clock_reason(record, original, day, zone):
    """Validate every supplied clock, including fields normalization did not select.

    The analysis zone checks compatibility only; it never attests a source zone
    or changes the source date, timestamps or daily mean.
    """
    if "date" in original and original["date"] != day.isoformat():
        return "source_calendar_date_conflict"
    instants = {restore_stored_utc(record.source_timestamp_utc)} - {None}
    walls = {record.local_wall_time} - {None, ""}
    if any(instant.astimezone(zone).date() != day for instant in instants) or any(
        datetime.fromisoformat(wall).date() != day for wall in walls
    ):
        return "source_calendar_date_conflict"
    for key in dict.fromkeys((*_COMMON_TIME_PATHS, *_PAIRED_UTC_TIME_PATHS)):
        if key not in original:
            continue
        temporal = parse_garmin_time(original[key], source_field=key)
        if temporal.precision.value == "unknown":
            return "source_local_clock_unproven"
        instant = temporal.measured_at_utc
        if instant is not None:
            if instant.astimezone(zone).date() != day:
                return "source_calendar_date_conflict"
            instants.add(instant)
        elif temporal.local_date != day:
            return "source_calendar_date_conflict"
        if temporal.local_wall_time:
            wall = datetime.fromisoformat(temporal.local_wall_time)
            if wall.date() != day:
                return "source_calendar_date_conflict"
            walls.add(wall.isoformat())
            offset = temporal.source_utc_offset_minutes
            if offset is not None and wall.replace(tzinfo=zone).utcoffset() != timedelta(
                minutes=offset
            ):
                return "source_timezone_conflict"
    if len(instants) > 1 or len(walls) > 1:
        return "source_timezone_conflict"
    if instants and walls:
        if next(iter(instants)).astimezone(zone).replace(tzinfo=None) != datetime.fromisoformat(
            next(iter(walls))
        ):
            return "source_timezone_conflict"
    return None


def _ordinary_acquisition(session, source, record, raw, obs, artifact, evaluated_at):
    """Only the selected observation's ordinary successful acquisition counts.

    Raw rows can be deduplicated across acquisitions. Neither raw.received_at nor
    projection_observed_at nor a later garmin_reprocess receipt proves completion.
    """
    run = session.get(SyncRun, obs.sync_run_id) if obs.sync_run_id else None
    event = session.get(IngestEvent, obs.ingest_event_id) if obs.ingest_event_id else None
    batch = session.get(IngestBatch, event.ingest_batch_id) if event else None
    provider = session.get(Provider, source.provider_id)
    if (
        source.source_kind != "provider"
        or provider is None
        or provider.code != "garmin_connect"
        or obs.garmin_source_id != source.id
        or raw.garmin_source_id != source.id
        or obs.garmin_raw_payload_id != raw.id
        or obs.raw_artifact_id != artifact.id
        or raw.raw_artifact_id != artifact.id
        or record.ingest_event_id != obs.ingest_event_id
        or raw.stream_code != "intraday"
        or obs.stream_code != "intraday"
        or raw.payload_format != "json"
        or obs.payload_format != "json"
        or obs.source_filename != "stress.json"
        or obs.fixture_id is not None
    ):
        return "acquisition_provenance_mismatch"
    if run is None or run.stream_code not in {"garmin_incremental", "garmin_historical"}:
        return "ordinary_acquisition_unproven"
    if (
        run.provider_id != source.provider_id
        or (
            run.acquisition_source_id is not None
            and run.acquisition_source_id != source.acquisition_source_id
        )
        or run.status != "succeeded"
        or run.completed_at is None
    ):
        return "successful_acquisition_unproven"
    received = restore_stored_utc(obs.received_at)
    completed = restore_stored_utc(run.completed_at)
    if not restore_stored_utc(run.started_at) <= received <= completed <= evaluated_at:
        return "acquisition_chronology_unproven"
    fields = {
        name: getattr(obs, name)
        for name in (
            "garmin_source_id",
            "stream_code",
            "payload_format",
            "source_contract_version",
            "normalization_contract_version",
            "fixture_id",
            "parse_status",
            "record_count",
            "diagnostics_json",
            "unknown_fields_json",
            "sync_run_id",
            "source_filename",
        )
    }
    try:
        for name in ("source_window_start_utc", "source_window_end_utc"):
            fields[name] = restore_stored_utc(getattr(obs, name))
        expected_key = build_garmin_observation_key(content_hash=raw.content_hash, **fields)
    except ValueError:
        return "acquisition_identity_mismatch"
    if obs.observation_key != expected_key:
        return "acquisition_identity_mismatch"
    if (
        event is None
        or batch is None
        or event.acquisition_source_id != source.acquisition_source_id
        or event.raw_artifact_id != artifact.id
        or event.provider_stream != "intraday"
        or event.semantic_fingerprint != f"garmin-observation:{expected_key}"
        or event.status != "committed"
        or batch.status != "committed"
        or batch.acquisition_source_id != source.acquisition_source_id
        or batch.batch_kind != "provider_sync"
        or batch.parser_name != "garmin-normalization"
        or batch.parser_version != obs.normalization_contract_version
    ):
        return "acquisition_event_unproven"
    return None


def _proof(session, source, point, frozen, store, evaluated_at, analysis_day_policy=None):
    evidence = frozen["evidence"]
    record = session.get(GarminSourceRecord, evidence["record_id"])
    metric = session.get(GarminRecordMetric, evidence["metric_row_id"])
    raw = session.get(GarminRawPayload, evidence["raw_payload_id"])
    obs = session.get(GarminPayloadObservation, evidence["observation_id"])
    artifact = session.get(RawArtifact, raw.raw_artifact_id) if raw else None
    proof: dict[str, Any] = {
        "input_manifest_hash": point["input_manifest_hash"],
        "analytic_date": point["analytic_date"],
        "stored_unit": metric.unit if metric else None,
        "metric_device_attributed": bool(metric.source_device_attributed) if metric else None,
        "normalization_contract_version": evidence["normalization_contract_version"],
        "observation_id": evidence["observation_id"],
        "reason": None,
    }
    if analysis_day_policy is not None:
        proof.update(
            analysis_day_policy=analysis_day_policy,
            analysis_timezone=_ANALYSIS_ZONE,
            source_timezone=None,
            source_timezone_status="unproven",
        )

    def failed(reason):
        return {**proof, "reason": reason}

    if point["status"] == "partial" or frozen["coverage"]["availability"] == "partial":
        return failed("participating_metric_partial")
    definition = frozen["metric_definition"]
    selected = frozen["selected"]
    if (
        frozen["contract_version"] != "r03-garmin-analytic-input-v1"
        or frozen["rule_version"] not in _INPUT_RULES
        or frozen["coverage"]["coverage_rule_version"] != "r03-garmin-analytic-coverage-v1"
        or frozen["algorithm_identity"] != "stress"
        or definition["metric_code"] != METRIC_CODE
        or definition["capability_code"] != "stress"
        or definition["unit"] != "points"
        or definition["aggregate_kind"] != "daily_average"
        or definition["window"] != "calendar_day"
        or definition["source_field_paths"] != ["avgStressLevel"]
        or selected["metric_code"] != METRIC_CODE
        or selected["unit"] != "points"
        or selected["aggregate_kind"] != "daily_average"
        or selected["window"] != "calendar_day"
        or evidence["normalization_contract_version"] not in _NORMALIZATION_VERSIONS
        or evidence["reconciliation_contract_version"] != _RECONCILIATION_VERSION
    ):
        return failed("stress_method_incompatible_or_unknown")
    if record is None or metric is None or raw is None or obs is None or artifact is None:
        return failed("referenced_evidence_missing")
    if (
        record.garmin_source_id != source.id
        or record.projection_status != "current"
        or record.raw_payload_id != raw.id
        or metric.record_id != record.id
        or record.stream_code != "intraday"
        or metric.metric_code != METRIC_CODE
        or metric.capability_code != "stress"
        or metric.unit != "points"
        or metric.field_path != selected["field_path"]
        or metric.field_path != evidence["field_path"]
        or metric.field_path.rsplit(".", 1)[-1] != "avgStressLevel"
        or metric.state != "value"
        or metric.collection_json is not None
        or frozen["provider_code"] != source.provider_code
        or frozen["source_instance_id"] != source.source_instance_id
        or bool(metric.source_device_attributed) != bool(source.device_attributed)
        or obs.normalization_contract_version != record.normalization_contract_version
        or obs.reconciliation_contract_version != record.reconciliation_contract_version
        or obs.observation_key != evidence["observation_key"]
        or raw.content_hash != evidence["content_hash"]
    ):
        return failed("stress_source_unit_or_attribution_mismatch")
    reason = _ordinary_acquisition(session, source, record, raw, obs, artifact, evaluated_at)
    if reason:
        return failed(reason)
    if artifact.byte_size > MAX_ARTIFACT_BYTES:
        return failed("referenced_artifact_exceeds_byte_bound")
    try:
        content = store.read(artifact.relative_storage_path, max_bytes=MAX_ARTIFACT_BYTES)
        if (
            len(content) != artifact.byte_size
            or artifact.content_hash != raw.content_hash
            or hashlib.sha256(content).hexdigest() != raw.content_hash
        ):
            return failed("referenced_artifact_integrity_mismatch")
        original = json.loads(
            content, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (OSError, ValueError, RecursionError):
        return failed("referenced_original_unreadable")
    if not isinstance(original, dict):
        return failed("original_stress_shape_unproven")
    if (
        original.get("calendarDate") != point["analytic_date"]
        or record.source_local_date is None
        or record.source_local_date.isoformat() != point["analytic_date"]
    ):
        return failed("original_source_local_date_unproven")
    value = coerce_selected_number(original.get("avgStressLevel"))
    if value is None or value != point["value"] or value != selected["value"]:
        return failed("original_stress_value_mismatch")
    zones = [original[key] for key in _TIMEZONE_FIELDS if key in original]
    if analysis_day_policy is None:
        if not zones or any(not isinstance(zone, str) or not zone for zone in zones):
            return failed("confirmed_source_timezone_missing")
        if len(set(zones)) != 1 or (record.source_timezone and record.source_timezone != zones[0]):
            return failed("source_timezone_conflict")
        try:
            zone = ZoneInfo(zones[0])
        except (ZoneInfoNotFoundError, ValueError):
            return failed("confirmed_source_timezone_invalid")
    else:
        if any(not isinstance(zone, str) or not zone for zone in zones):
            return failed("confirmed_source_timezone_invalid")
        if len(set(zones)) > 1:
            return failed("source_timezone_conflict")
        source_zone = zones[0] if zones else None
        if record.source_timezone is not None and record.source_timezone != source_zone:
            return failed("source_timezone_conflict")
        if source_zone is not None:
            try:
                ZoneInfo(source_zone)
            except (ZoneInfoNotFoundError, ValueError):
                return failed("confirmed_source_timezone_invalid")
            proof.update(source_timezone=source_zone, source_timezone_status="confirmed")
            if source_zone != _ANALYSIS_ZONE:
                return failed("source_timezone_incompatible_with_analysis_policy")
        zone = ZoneInfo(_ANALYSIS_ZONE)
    reason = _source_clock_reason(record, original, zone)
    if reason:
        return failed(reason)
    day = date.fromisoformat(point["analytic_date"])
    if analysis_day_policy is not None:
        reason = _policy_clock_reason(record, original, day, zone)
        if reason:
            return failed(reason)
    boundary = _day_end(day, zone)
    if boundary is None:
        return failed("source_day_end_unproven")
    received = restore_stored_utc(obs.received_at)
    proof.update(
        completion_boundary_utc=boundary.isoformat(),
        acquired_at=received.isoformat(),
        sync_run_id=obs.sync_run_id,
    )
    if analysis_day_policy is None:
        proof["source_timezone"] = zone.key
    if received < boundary or evaluated_at < boundary:
        return failed(
            "acquisition_before_analysis_day_end"
            if analysis_day_policy is not None
            else "acquisition_before_source_day_end"
        )
    return proof


def read_stress_baseline(
    session: Session,
    *,
    garmin_source_id: str | None,
    selected_date: date,
    evaluated_at: datetime,
    payload_store: ContentAddressedGarminPayloadStore,
    analysis_day_policy: str | None = None,
) -> dict[str, Any]:
    """Return a source-specific frozen comparison, or current value plus reasons.

    Caller supplies an aware evaluation instant; host date/timezone is never a
    source-calendar attestation. All selected R03 participants must be proven;
    excluding a failed participant and recomputing a smaller sample is forbidden.
    Only explicit versioned opt-in selects the Owner's Moscow completion policy;
    the default retains the strict v2 source-zone contract and serialization.
    """
    if analysis_day_policy is not None and analysis_day_policy != MOSCOW_ANALYSIS_DAY_POLICY:
        raise ValueError("unsupported analysis_day_policy")
    if type(selected_date) is not date or selected_date < date.min + timedelta(days=28):
        raise ValueError("selected_date must allow the preceding 28 civil dates")
    if not isinstance(evaluated_at, datetime) or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be an aware instant")
    if garmin_source_id is not None and (
        not isinstance(garmin_source_id, str) or not garmin_source_id.strip()
    ):
        raise ValueError("garmin_source_id must be an explicit nonempty identity")
    evaluated_at = evaluated_at.astimezone(UTC)
    start, end = selected_date - timedelta(days=28), selected_date - timedelta(days=1)
    ensure_read_snapshot(session)
    source = session.get(GarminSource, garmin_source_id) if garmin_source_id else None
    body: dict[str, Any] = {
        "contract_version": (
            POLICY_CONTRACT_VERSION if analysis_day_policy is not None else CONTRACT_VERSION
        ),
        "metric_code": METRIC_CODE,
        "selected_date": selected_date.isoformat(),
        "evaluated_at": evaluated_at.isoformat(),
        "source": None,
        "current": {
            "date": selected_date.isoformat(),
            "status": "unavailable",
            "value": None,
            "unit": None,
        },
        "history": {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "denominator": 28,
            "observed_nonpartial_days": 0,
            "eligible_days": 0,
            "effective_start_date": None,
            "effective_end_date": None,
        },
        "comparison": {
            "status": "unavailable",
            "reason": None,
            "median": None,
            "p25": None,
            "p75": None,
            "delta_points": None,
            "direction": None,
        },
        "evidence": {},
        "proofs": [],
        "coverage_semantics": "saved_daily_observations_not_intraday_or_acquisition_completeness",
    }
    if analysis_day_policy is not None:
        body["analysis_day_policy"] = {
            "version": analysis_day_policy,
            "analysis_timezone": _ANALYSIS_ZONE,
            "date_semantics": "original_garmin_calendarDate_not_rebucketed",
        }

    def finish(reason=None, status="unavailable"):
        body["comparison"].update(status=status, reason=reason)
        return {**body, "result_hash": stable_manifest_hash(body)}

    if garmin_source_id is None:
        return finish("source_selection_required")
    if source is None or source.provider_code != "garmin_connect":
        return finish("selected_garmin_source_not_found")
    body["source"] = {
        key: getattr(source, key)
        for key in (
            "id",
            "provider_code",
            "source_instance_id",
            "source_kind",
            "device_attributed",
            "device_code",
            "device_model",
        )
    }
    for name, first, last in (("current", selected_date, selected_date), ("history", start, end)):
        try:
            result = analyze_garmin_metric_series(
                session,
                GarminSeriesQuery(
                    METRIC_CODE, first, last, source.id,
                    selection_version=STRESS_APPLICABILITY_VERSION,
                ),
            ).as_dict()
        except (GarminScalarAnalyticsError, AnalyticInputAssemblyError, ValueError) as exc:
            return finish(getattr(exc, "reason_code", "r03_evidence_assembly_failed"))
        body["evidence"][name] = {
            key: result[key]
            for key in (
                "algorithm",
                "rule_version",
                "query",
                "metric_definition",
                "points",
                "availability",
                "applicability",
                "frozen_inputs",
                "result_hash",
            )
            if key in result
        }
        if name == "current":
            current = result
            points = result["points"]
            if len(points) == 1:
                point = points[0]
                metric = session.get(GarminRecordMetric, point["metric_row_id"])
                body["current"].update(
                    status=point["status"],
                    value=point["value"],
                    unit=metric.unit if metric else None,
                )
        else:
            history = result
    participants = [
        ("current", p) for p in current["points"] if p["status"] in _PARTICIPATING_STATES
    ]
    participants += [
        ("history", p) for p in history["points"] if p["status"] in _PARTICIPATING_STATES
    ]
    observed = {p["analytic_date"] for p in history["points"] if p["status"] in _VALUE_STATES}
    body["history"]["observed_nonpartial_days"] = len(observed)
    body["history"]["unobserved_dates"] = [
        (start + timedelta(days=i)).isoformat()
        for i in range(28)
        if (start + timedelta(days=i)).isoformat()
        not in {p["analytic_date"] for p in history["points"]}
    ]
    if len(current["points"]) != 1 or current["points"][0]["status"] not in _PARTICIPATING_STATES:
        return finish("selected_day_not_uniquely_usable")
    if any(
        r["algorithm"] != R03_01_ALGORITHM
        or r["rule_version"] != R03_01_STRESS_RULE_VERSION
        or r.get("applicability", {}).get("version") != STRESS_APPLICABILITY_VERSION
        or r["query"].get("selection_version") != STRESS_APPLICABILITY_VERSION
        or r["baseline"]["quantile_method"] != R03_01_QUANTILE_METHOD
        for r in (current, history)
    ):
        return finish("r03_method_incompatible", "method_dependent")
    if len(participants) > MAX_PARTICIPANTS:
        return finish("daily_participant_bound_exceeded", "method_dependent")
    eligible_dates = []
    for name, point in participants:
        frozen = {item["manifest_hash"]: item for item in body["evidence"][name]["frozen_inputs"]}
        item = frozen.get(point["input_manifest_hash"])
        if item is None:
            return finish("frozen_input_missing", "method_dependent")
        proof = _proof(
            session, source, point, item, payload_store, evaluated_at, analysis_day_policy
        )
        proof["scope"] = name
        body["proofs"].append(proof)
        if name == "history" and proof["reason"] is None:
            eligible_dates.append(point["analytic_date"])
    body["history"].update(
        eligible_days=len(set(eligible_dates)),
        effective_start_date=min(eligible_dates, default=None),
        effective_end_date=max(eligible_dates, default=None),
    )
    failures = [p for p in body["proofs"] if p["reason"] is not None]
    if failures:
        return finish(failures[0]["reason"], "method_dependent")
    if analysis_day_policy is None and len({p["source_timezone"] for p in body["proofs"]}) > 1:
        return finish("participating_source_timezone_changed", "method_dependent")
    if len(observed) < MIN_HISTORY_DAYS:
        return finish("insufficient_eligible_history")
    baseline = history["baseline"]
    if not baseline["available"] or baseline["count"] != len(observed):
        return finish("frozen_baseline_sample_mismatch", "method_dependent")
    delta = float(body["current"]["value"]) - baseline["median"]
    body["comparison"].update(
        median=baseline["median"],
        p25=baseline["p25"],
        p75=baseline["p75"],
        delta_points=delta,
        direction="above" if delta > 0 else "below" if delta < 0 else "equal",
    )
    return finish(status="available")
