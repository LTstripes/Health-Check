"""Frozen Steps evaluators from d889acee9b48471817984db3a4e8a139a9dafce0.

Synthetic regression oracle only. Old function bodies copied verbatim;
unchanged constants, DTOs and provenance helpers use their existing modules.
Never imported by product code.
"""
from __future__ import annotations

import hashlib
import json
from collections import (
    defaultdict,
)
from datetime import (
    UTC,
    date,
    datetime,
    timedelta,
)
from time import (
    monotonic,
)
from typing import Any
from zoneinfo import (
    ZoneInfo,
)

from sqlalchemy import (
    LargeBinary,
    func,
    select,
)
from sqlalchemy.orm import (
    Load,
    Session,
    load_only,
)

from healthcheck.db.models import (
    GarminDailySummaryAcquisitionReceipt,
    GarminPayloadObservation,
    GarminRawPayload,
    GarminSource,
    GooglePayloadObservation,
    GoogleRawPayload,
    GoogleRecordInterval,
    GoogleRecordMetric,
    GoogleSource,
    GoogleSourceRecord,
    IngestBatch,
    IngestEvent,
    Provider,
    RawArtifact,
    SyncRun,
)
from healthcheck.db.repositories import (
    canonical_json,
    restore_stored_utc,
)
from healthcheck.garmin.completed_steps_read import (
    DISPLAY_ZONE,
    MAX_ALL_TIME_ARTIFACTS,
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACTS,
    MAX_CANDIDATES,
    MAX_PROVENANCE,
    MAX_READ_SECONDS,
    MAX_TOTAL_BYTES,
    CompletedStepsDay,
    CompletedStepsEvidence,
    CompletedStepsHistory,
    CompletedStepsWindow,
    acquisition_reason,
    completion_boundary,
)
from healthcheck.garmin.observed_steps import (
    _calendar_date,
    _decode,
    _metric,
)
from healthcheck.garmin.observed_steps_read import (
    MAX_WINDOW_DAYS,
    StepsSourceIdentity,
)
from healthcheck.garmin.storage import (
    ContentAddressedGarminPayloadStore,
)
from healthcheck.google.contracts import (
    GOOGLE_PROVIDER_CODE,
    KNOWN_DATA_SOURCE_FAMILIES,
    decode_count_sum_metric,
)
from healthcheck.google.identity import (
    _value,
    parse_steps_civil_endpoint,
)
from healthcheck.google.persistence import (
    build_google_record_identity_key,
)
from healthcheck.google.steps_read import (
    CONTRACT,
    COOPERATIVE_SECONDS,
    MAX_CHILDREN,
    MAX_RECORDS,
    MAX_SOURCES,
    MAX_TEXT_BYTES,
)
from healthcheck.web.read_snapshot import (
    ensure_read_snapshot,
)


def read_saved_steps_window_reference(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    source_id: str | None = None,
) -> dict:
    """Read an exact 7/30-day window from current typed projections in one snapshot."""
    if type(start_date) is not date or type(end_date) is not date:
        raise ValueError("explicit civil dates required")
    span = (end_date - start_date).days + 1
    if span not in {7, 30} or end_date == date.max:
        raise ValueError("Google saved Steps supports inclusive 7/30 days only")
    ensure_read_snapshot(session)
    began = monotonic()
    result = {
        "contract_version": CONTRACT,
        "start_date": start_date,
        "end_date": end_date,
        "source_id": source_id,
        "source_identity": None,
        "source_choices": [],
        "cells": [],
        "search_complete": True,
        "reason": None,
        "coverage": "unknown",
        "pagination": "unknown",
        "timezone": "unknown",
        "finality": "unknown",
        "records_examined": 0,
    }

    def incomplete(reason):
        result.update(search_complete=False, reason=reason, cells=[])
        return result

    sources = list(
        session.scalars(
            select(GoogleSource)
            .where(
                select(GoogleSourceRecord.id)
                .where(
                    GoogleSourceRecord.google_source_id == GoogleSource.id,
                    GoogleSourceRecord.stream_code == "steps",
                )
                .exists()
            )
            .order_by(GoogleSource.id)
            .limit(MAX_SOURCES + 1)
        )
    )
    if len(sources) > MAX_SOURCES:
        return incomplete("source_search_incomplete")
    result["source_choices"] = [
        {
            "source_id": s.id,
            "family": s.source_instance_id,
            "family_label": s.source_instance_id.rsplit("/", 1)[-1],
        }
        for s in sources
    ]
    if source_id is None:
        if len(sources) != 1:
            result["reason"] = "source_selection_required" if sources else "no_saved_source"
            return result
        source = sources[0]
    else:
        source = next((s for s in sources if s.id == source_id), None)
        if source is None:
            result["reason"] = "source_not_evidenced"
            return result
    result["source_id"] = source.id
    result["source_identity"] = {
        "source_id": source.id,
        "provider_code": source.provider_code,
        "source_kind": source.source_kind,
        "family": source.source_instance_id,
    }
    if (
        source.provider_code != GOOGLE_PROVIDER_CODE
        or source.source_kind != "family_aggregate"
        or source.source_instance_id not in KNOWN_DATA_SOURCE_FAMILIES
        or source.device_attributed
    ):
        result["reason"] = "invalid_source_identity"
        return result

    rows = list(
        session.scalars(
            select(GoogleSourceRecord)
            .options(
                load_only(
                    GoogleSourceRecord.id,
                    GoogleSourceRecord.google_source_id,
                    GoogleSourceRecord.stream_code,
                    GoogleSourceRecord.query_mode,
                    GoogleSourceRecord.data_source_family,
                    GoogleSourceRecord.idempotency_key,
                    GoogleSourceRecord.record_identity_key,
                    GoogleSourceRecord.record_status,
                    GoogleSourceRecord.observation_id,
                    GoogleSourceRecord.raw_payload_id,
                    GoogleSourceRecord.projection_observed_at,
                )
            )
            .where(
                GoogleSourceRecord.google_source_id == source.id,
                GoogleSourceRecord.stream_code == "steps",
                GoogleSourceRecord.projection_status == "current",
            )
            .order_by(GoogleSourceRecord.id)
            .limit(MAX_RECORDS + 1)
        )
    )
    result["records_examined"] = len(rows)
    if len(rows) > MAX_RECORDS:
        return incomplete("record_search_incomplete")
    # Each child collection is bounded independently; never read an arbitrary prefix
    # as if it were the complete current revision group.
    intervals, metrics = defaultdict(list), defaultdict(list)
    child_bytes = 0
    for model, grouped in ((GoogleRecordInterval, intervals), (GoogleRecordMetric, metrics)):
        text_columns = (
            (model.start_temporal_json, model.end_temporal_json)
            if model is GoogleRecordInterval
            else (model.value_text, model.collection_json)
        )
        lengths = list(
            session.execute(
                select(
                    model.id, *(func.length(column.cast(LargeBinary)) for column in text_columns)
                )
                .join(GoogleSourceRecord, model.record_id == GoogleSourceRecord.id)
                .where(
                    GoogleSourceRecord.google_source_id == source.id,
                    GoogleSourceRecord.stream_code == "steps",
                    GoogleSourceRecord.projection_status == "current",
                )
                .order_by(model.record_id, model.id)
                .limit(MAX_CHILDREN + 1)
            )
        )
        if len(lengths) > MAX_CHILDREN:
            return incomplete("child_search_incomplete")
        for _, *sizes in lengths:
            if any((size or 0) > 4096 for size in sizes):
                return incomplete("text_budget_exceeded")
            child_bytes += sum(size or 0 for size in sizes)
        if child_bytes > MAX_TEXT_BYTES:
            return incomplete("text_budget_exceeded")
        children = list(
            session.scalars(
                select(model)
                .join(GoogleSourceRecord, model.record_id == GoogleSourceRecord.id)
                .where(
                    GoogleSourceRecord.google_source_id == source.id,
                    GoogleSourceRecord.stream_code == "steps",
                    GoogleSourceRecord.projection_status == "current",
                )
                .order_by(model.record_id, model.id)
                .limit(MAX_CHILDREN + 1)
            )
        )
        if len(children) > MAX_CHILDREN:
            return incomplete("child_search_incomplete")
        for child in children:
            grouped[child.record_id].append(child)

    provenance = {
        record_id: (observation, raw)
        for record_id, observation, raw in session.execute(
            select(GoogleSourceRecord.id, GooglePayloadObservation, GoogleRawPayload)
            .options(
                Load(GooglePayloadObservation).load_only(
                    GooglePayloadObservation.id,
                    GooglePayloadObservation.google_source_id,
                    GooglePayloadObservation.google_raw_payload_id,
                    GooglePayloadObservation.stream_code,
                    GooglePayloadObservation.query_mode,
                    GooglePayloadObservation.data_source_family,
                ),
                Load(GoogleRawPayload).load_only(
                    GoogleRawPayload.id,
                    GoogleRawPayload.google_source_id,
                    GoogleRawPayload.stream_code,
                ),
            )
            .outerjoin(
                GooglePayloadObservation,
                GooglePayloadObservation.id == GoogleSourceRecord.observation_id,
            )
            .outerjoin(GoogleRawPayload, GoogleRawPayload.id == GoogleSourceRecord.raw_payload_id)
            .where(
                GoogleSourceRecord.google_source_id == source.id,
                GoogleSourceRecord.stream_code == "steps",
                GoogleSourceRecord.projection_status == "current",
            )
            .limit(MAX_RECORDS + 1)
        )
    }

    days = [start_date + timedelta(days=i) for i in range(span)]
    groups = defaultdict(list)
    used_bytes = 0
    for row in rows:
        if monotonic() - began > COOPERATIVE_SECONDS:
            return incomplete("work_budget_exceeded")
        parts = intervals[row.id]
        if len(parts) != 1:
            return incomplete("unlocatable_interval")
        interval = parts[0]
        if not isinstance(interval.start_temporal_json, str) or not isinstance(
            interval.end_temporal_json, str
        ):
            return incomplete("unlocatable_interval")
        used_bytes += len(interval.start_temporal_json.encode()) + len(
            interval.end_temporal_json.encode()
        )
        if (
            used_bytes > MAX_TEXT_BYTES
            or len(interval.start_temporal_json) > 4096
            or len(interval.end_temporal_json) > 4096
        ):
            return incomplete("text_budget_exceeded")
        try:
            endpoints = []
            for text in (interval.start_temporal_json, interval.end_temporal_json):
                outer = json.loads(text)
                if not isinstance(outer, dict) or not isinstance(outer.get("raw_civil_json"), str):
                    raise ValueError("invalid temporal evidence object")
                raw_endpoint = json.loads(outer["raw_civil_json"])
                if not isinstance(raw_endpoint, dict):
                    raise ValueError("invalid raw civil endpoint object")
                endpoints.append(raw_endpoint)
            # Accepted identity validator checks raw/typed fields, no zone/UTC
            # invention, nanoseconds and omitted raw components.
            if google_steps_interval_key_reference(interval) != row.idempotency_key:
                raise ValueError("civil identity mismatch")
            if (
                build_google_record_identity_key(
                    stream_code="steps",
                    query_mode=row.query_mode,
                    data_source_family=row.data_source_family,
                    idempotency_key=row.idempotency_key,
                    interval=interval,
                )
                != row.record_identity_key
            ):
                raise ValueError("record identity mismatch")
            start_raw, end_raw = endpoints
            first, _, start_key = parse_steps_civil_endpoint(start_raw)
            last, _, end_key = parse_steps_civil_endpoint(end_raw)
        except (ValueError, KeyError, TypeError, OverflowError, RecursionError):
            return incomplete("unlocatable_interval")
        full_day = (
            start_key[3:] == (0, 0, 0, 0)
            and end_key[3:] == (0, 0, 0, 0)
            and first < date.max
            and last == first + timedelta(days=1)
        )
        # A non-day interval may overlap multiple requested days. Never split or
        # sum its count; retain it as an exclusion on every affected civil date.
        for day in days:
            if first <= day <= last and not (day == last and end_key[3:] == (0, 0, 0, 0)):
                groups[day].append((row, interval, full_day))

    for day in days:
        candidates = groups[day]
        cell = {
            "calendar_date": day,
            "state": "no_observation",
            "value": None,
            "reason": "no_saved_interval",
            "evidence": [],
        }
        for row, interval, _ in candidates:
            cell["evidence"].append(
                {
                    "record_id": row.id,
                    "observation_id": row.observation_id,
                    "raw_payload_id": row.raw_payload_id,
                    "as_of": restore_stored_utc(row.projection_observed_at),
                    "start": interval.start_local_wall_time,
                    "end": interval.end_local_wall_time,
                }
            )
        if len(candidates) > 1:
            cell.update(state="ambiguous", reason="overlapping_current_intervals")
        elif candidates:
            row, _, full_day = candidates[0]
            observation, raw = provenance.get(row.id, (None, None))
            provenance_valid = (
                observation is not None
                and raw is not None
                and observation.google_source_id == raw.google_source_id == source.id
                and observation.google_raw_payload_id == raw.id == row.raw_payload_id
                and observation.stream_code == raw.stream_code == "steps"
                and observation.query_mode == row.query_mode == "dailyRollUp"
                and observation.data_source_family
                == row.data_source_family
                == source.source_instance_id
            )
            if not full_day:
                cell.update(state="unavailable", reason="not_one_civil_day")
            elif (
                not provenance_valid
                or row.query_mode != "dailyRollUp"
                or row.data_source_family != source.source_instance_id
                or row.record_status not in {"ok", "partial"}
            ):
                cell.update(state="invalid", reason="current_record_unavailable")
            elif len(metrics[row.id]) != 1:
                cell.update(state="invalid", reason="invalid_metric_group")
            else:
                metric = metrics[row.id][0]
                if metric.value_text is not None and len(metric.value_text) > 32:
                    cell.update(state="invalid", reason="invalid_count_sum")
                else:
                    try:
                        count = decode_count_sum_metric(metric)
                        cell.update(
                            state=count.state.value,
                            value=count.value,
                            reason=None
                            if count.value is not None
                            else "metric_" + count.state.value,
                        )
                    except (ValueError, TypeError, OverflowError):
                        cell.update(state="invalid", reason="invalid_count_sum")
        result["cells"].append(cell)
    if monotonic() - began > COOPERATIVE_SECONDS:
        return incomplete("work_budget_exceeded")
    return result


def read_completed_steps_window_reference(
    session: Session,
    *,
    payload_store: ContentAddressedGarminPayloadStore,
    source_id: str | None,
    start_date: date,
    end_date: date,
    evaluated_at: datetime,
    _all_time: bool = False,
    _started: float | None = None,
    _requested_end_date: date | None = None,
) -> CompletedStepsWindow:
    """Bound metadata, then scan relevant originals once in one snapshot.

    Requested civil bounds are retained. Current/future Moscow days are omitted.
    A fully validated immutable receipt can index an original outside the window.
    Otherwise unknown original day/integrity or any exhausted bound fails closed
    because its day/latest rank cannot be proved. Exact source selection
    is preserved; automatic choice requires one sole source in the verified range.
    """
    if type(end_date) is not date or (not _all_time and type(start_date) is not date):
        raise ValueError("completed Steps requires civil dates")
    if not _all_time and not 1 <= (end_date - start_date).days + 1 <= MAX_WINDOW_DAYS:
        raise ValueError("completed Steps window must contain 1 to 366 days")
    if source_id is not None and (not isinstance(source_id, str) or not source_id.strip()):
        raise ValueError("invalid exact source")
    if not isinstance(evaluated_at, datetime) or evaluated_at.utcoffset() is None:
        raise ValueError("completed Steps requires an aware evaluation instant")
    evaluated_at = evaluated_at.astimezone(UTC)
    today = evaluated_at.astimezone(ZoneInfo(DISPLAY_ZONE)).date()
    dates = () if _all_time else tuple(
        start_date + timedelta(days=i)
        for i in range((end_date - start_date).days + 1)
        if start_date + timedelta(days=i) < today
    )
    ensure_read_snapshot(session)
    started = monotonic() if _started is None else _started
    history_days = set()
    source = session.get(GarminSource, source_id) if source_id else None
    identity = None
    choices = ()
    candidates = provenance = artifacts = byte_count = 0

    def result(cells=(), reason=None, complete=True):
        result_type = CompletedStepsHistory if _all_time else CompletedStepsWindow
        return result_type(
            source_id,
            min(history_days) if _all_time and history_days and complete else start_date,
            end_date,
            evaluated_at,
            identity,
            choices,
            tuple(cells),
            complete,
            candidates,
            provenance,
            artifacts,
            byte_count,
            reason,
            **({"requested_end_date": _requested_end_date} if _all_time else {}),
        )

    def incomplete(reason):
        if _all_time:
            return result(reason=reason, complete=False)
        return result(
            (
                CompletedStepsDay(
                    source_id or "",
                    day,
                    completion_boundary(day),
                    "search_incomplete",
                    reason=reason,
                    search_complete=False,
                )
                for day in dates
            ),
            reason,
            False,
        )

    def in_scope(day):
        return day <= end_date if _all_time else day in dates

    if _all_time and source_id is None:
        return result(reason="source_selection_required")
    if source_id and (source is None or source.provider_code != "garmin_connect"):
        return result(reason="source_not_found")
    if source:
        identity = StepsSourceIdentity(
            source.id, source.provider_code, source.source_kind, source.source_instance_id
        )
    if not dates and not _all_time:
        return result(reason="no_completed_days")
    obs = GarminPayloadObservation
    query = (
        select(
            obs,
            GarminSource,
            GarminRawPayload,
            RawArtifact,
            SyncRun,
            Provider,
            IngestEvent,
            IngestBatch,
            GarminDailySummaryAcquisitionReceipt,
        )
        .outerjoin(GarminSource, GarminSource.id == obs.garmin_source_id)
        .outerjoin(GarminRawPayload, GarminRawPayload.id == obs.garmin_raw_payload_id)
        .outerjoin(RawArtifact, RawArtifact.id == GarminRawPayload.raw_artifact_id)
        .outerjoin(SyncRun, SyncRun.id == obs.sync_run_id)
        .outerjoin(Provider, Provider.id == GarminSource.provider_id)
        .outerjoin(IngestEvent, IngestEvent.id == obs.ingest_event_id)
        .outerjoin(IngestBatch, IngestBatch.id == IngestEvent.ingest_batch_id)
        .outerjoin(
            GarminDailySummaryAcquisitionReceipt,
            GarminDailySummaryAcquisitionReceipt.observation_id == obs.id,
        )
        .where(
            obs.stream_code == "daily_health",
            obs.payload_format == "json",
            obs.source_filename == "daily_summary.json",
            obs.received_at <= evaluated_at,
        )
        .order_by(obs.received_at, obs.id)
        .limit(MAX_PROVENANCE + 1)
    )
    if not _all_time:
        query = query.where(obs.received_at >= completion_boundary(dates[0]))
    if source_id:
        query = query.where(obs.garmin_source_id == source_id)
    try:
        rows = list(session.execute(query))
    except (ValueError, TypeError, OverflowError):
        return incomplete("acquisition_receipt_unreadable")
    provenance = len(rows)
    if provenance > MAX_PROVENANCE:
        return incomplete("provenance_limit_exceeded")
    raw_ids = {row[0].garmin_raw_payload_id for row in rows}
    candidates = len(raw_ids)
    if candidates > MAX_CANDIDATES:
        return incomplete("candidate_limit_exceeded")
    # Receipts are a trusted-writer index, not a replacement for verifying any
    # selected original. Keep a raw group unless EVERY acquisition has a valid,
    # agreeing outside-window index. In particular, a good receipt cannot hide
    # a legacy/unproven competitor sharing the same bytes.
    indexed_days = defaultdict(set)
    retained_ids = set()
    for observation, src, raw, artifact, run, provider, event, batch, receipt in rows:
        if monotonic() - started > MAX_READ_SECONDS:
            return incomplete("time_limit_exceeded")
        if run is not None and run.stream_code == "garmin_reprocess":
            continue
        raw_id = observation.garmin_raw_payload_id
        if receipt is None or acquisition_reason(
            observation,
            src,
            raw,
            artifact,
            run,
            provider,
            event,
            batch,
            receipt,
            receipt.original_calendar_date,
        ):
            retained_ids.add(raw_id)
            continue
        day = receipt.original_calendar_date
        indexed_days[raw_id].add(day)
        if in_scope(day):
            retained_ids.add(raw_id)
    retained_ids.update(key for key, days in indexed_days.items() if len(days) != 1)
    if len(retained_ids) > (MAX_ALL_TIME_ARTIFACTS if _all_time else MAX_ARTIFACTS):
        return incomplete("artifact_limit_exceeded")
    decoded = {}
    by_source_day = defaultdict(list)
    identities = {}
    for observation, src, raw, artifact, run, provider, event, batch, receipt in rows:
        if monotonic() - started > MAX_READ_SECONDS:
            return incomplete("time_limit_exceeded")
        # Reprocess is positively known to be saved-byte replay, not acquisition.
        if run is not None and run.stream_code == "garmin_reprocess":
            continue
        if observation.garmin_raw_payload_id not in retained_ids:
            continue
        if raw is None or artifact is None:
            return incomplete("original_not_evidenced")
        if raw.id not in decoded:
            if artifact.byte_size > MAX_ARTIFACT_BYTES:
                return incomplete("artifact_byte_limit_exceeded")
            if byte_count + artifact.byte_size > MAX_TOTAL_BYTES:
                return incomplete("total_byte_limit_exceeded")
            try:
                content = payload_store.read(
                    artifact.relative_storage_path,
                    max_bytes=(min(MAX_ARTIFACT_BYTES, MAX_TOTAL_BYTES - byte_count)
                               if _all_time else MAX_ARTIFACT_BYTES),
                )
            except (OSError, ValueError):
                return incomplete("original_unreadable")
            artifacts += 1
            byte_count += len(content)
            if (
                len(content) != artifact.byte_size
                or hashlib.sha256(content).hexdigest() != raw.content_hash
                or artifact.content_hash != raw.content_hash
            ):
                return incomplete("original_integrity_mismatch")
            payload, reason = _decode(content)
            day = _calendar_date(payload) if payload is not None else None
            if day is None:
                return incomplete(reason or "original_calendar_date_unproven")
            decoded[raw.id] = (day, _metric(payload))
        day, metric = decoded[raw.id]
        received = restore_stored_utc(observation.received_at)
        if _all_time and in_scope(day):
            history_days.add(day)
        if not in_scope(day) or received < completion_boundary(day):
            continue
        reason = acquisition_reason(
            observation, src, raw, artifact, run, provider, event, batch, receipt, day
        )
        evidence = CompletedStepsEvidence(
            observation.id,
            raw.id,
            artifact.id,
            raw.content_hash,
            observation.sync_run_id,
            observation.ingest_event_id,
            received,
            metric.state.value,
            metric.value,
            reason or metric.reason,
            reason is None,
            ("daily_summary_receipt" if receipt is not None else "succeeded_run")
            if reason is None
            else None,
            receipt.contract_version if receipt is not None else None,
        )
        by_source_day[observation.garmin_source_id, day].append(evidence)
        if src is not None and src.provider_code == "garmin_connect":
            identities[src.id] = StepsSourceIdentity(
                src.id, src.provider_code, src.source_kind, src.source_instance_id
            )
    if monotonic() - started > MAX_READ_SECONDS:
        return incomplete("time_limit_exceeded")
    if _all_time:
        dates = tuple(sorted(history_days))
        if not dates:
            return result(reason="no_completed_days" if rows else "source_not_evidenced")
    choices = tuple(identities[key] for key in sorted(identities))
    if source_id is None:
        if len(choices) != 1:
            return result(reason="source_selection_required" if choices else "source_not_evidenced")
        identity = choices[0]
        source_id = identity.source_id
    cells = []
    for day in dates:
        evidence = tuple(by_source_day.get((source_id, day), ()))
        latest = max((item.received_at for item in evidence), default=None)
        group = [item for item in evidence if item.received_at == latest]
        states = {(item.state, item.value) for item in group}
        if not group:
            state, value, reason = "unavailable", None, "no_post_boundary_acquisition"
        elif any(not item.acquisition_proven for item in group):
            state, value, reason = (
                ("ambiguous", None, "divergent_latest_acquisitions")
                if any(item.acquisition_proven for item in group)
                else ("unavailable", None, "latest_acquisition_unproven")
            )
        elif len(states) != 1:
            state, value, reason = "ambiguous", None, "divergent_latest_acquisitions"
        else:
            state, value = next(iter(states))
            reason = group[0].reason
        cells.append(
            CompletedStepsDay(
                source_id, day, completion_boundary(day), state, value, reason, latest, evidence
            )
        )
    return result(cells)


def google_steps_interval_key_reference(interval: Any) -> str:
    """Key exact raw civil endpoint objects; never infer UTC or a day label."""
    if (
        _value(getattr(interval, "interval_kind", None)) != "daily_roll_up"
        or _value(getattr(interval, "state", getattr(interval, "interval_state", None))) != "value"
    ):
        raise ValueError("Steps requires a valid daily civil interval")
    endpoints = {}
    order = []
    for name in ("start", "end"):
        endpoint = getattr(interval, name, None)
        raw = getattr(endpoint, "raw_civil_json", None)
        if endpoint is None:
            evidence = json.loads(getattr(interval, f"{name}_temporal_json"))
            raw = evidence.get("raw_civil_json")
        if not isinstance(raw, str) or not isinstance(json.loads(raw), dict):
            raise ValueError("Steps interval requires raw civil endpoint objects")
        if canonical_json(json.loads(raw)) != raw:
            raise ValueError("Steps raw civil JSON must be canonical and unambiguous")
        day, wall, key = parse_steps_civil_endpoint(json.loads(raw))
        order.append(key)
        if endpoint is not None:
            precision, state = _value(endpoint.precision), _value(endpoint.state)
            local_day, local_wall, at_utc = (
                endpoint.local_date,
                endpoint.local_wall_time,
                endpoint.measured_at_utc,
            )
            zone, offset = endpoint.source_timezone, endpoint.source_utc_offset_minutes
        else:
            precision, state = (
                getattr(interval, f"{name}_precision"),
                getattr(interval, f"{name}_state"),
            )
            local_day, local_wall, at_utc = (
                getattr(interval, f"{name}_local_date"),
                getattr(interval, f"{name}_local_wall_time"),
                getattr(interval, f"{name}_at_utc"),
            )
            zone, offset = (
                getattr(interval, f"{name}_source_timezone"),
                getattr(interval, f"{name}_utc_offset_minutes"),
            )
        if (
            precision != "local"
            or state != "value"
            or local_day != day
            or local_wall != wall
            or at_utc is not None
            or zone is not None
            or offset is not None
        ):
            raise ValueError("Steps civil endpoint disagrees with raw evidence")
        endpoints[name] = canonical_json(json.loads(raw))
    if order[0] >= order[1]:
        raise ValueError("Steps civil interval must be strictly ordered")
    digest = hashlib.sha256(canonical_json(endpoints).encode()).hexdigest()
    return f"google-steps-interval-v1:{digest}"
