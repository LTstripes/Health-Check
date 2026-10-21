"""Bounded read-only Google Steps observations; no completed-day or coverage claim."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from time import monotonic

from sqlalchemy import LargeBinary, func, select
from sqlalchemy.orm import Load, Session, load_only

from healthcheck.db.models import (
    GooglePayloadObservation,
    GoogleRawPayload,
    GoogleRecordInterval,
    GoogleRecordMetric,
    GoogleSource,
    GoogleSourceRecord,
)
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.google.contracts import (
    GOOGLE_PROVIDER_CODE,
    KNOWN_DATA_SOURCE_FAMILIES,
    decode_count_sum_metric,
)
from healthcheck.google.identity import google_steps_interval_key, parse_steps_civil_endpoint
from healthcheck.google.persistence import build_google_record_identity_key
from healthcheck.web.read_snapshot import ensure_read_snapshot

CONTRACT = "google-saved-steps-window-v1"
MAX_SOURCES = 128
MAX_RECORDS = 4096
MAX_CHILDREN = 4096
MAX_TEXT_BYTES = 16 * 1024 * 1024
COOPERATIVE_SECONDS = 5.0


def read_saved_steps_window(
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
            # Accepted identity validator checks raw/typed fields, no zone/UTC
            # invention, nanoseconds and omitted raw components.
            if google_steps_interval_key(interval) != row.idempotency_key:
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
            start_raw = json.loads(json.loads(interval.start_temporal_json)["raw_civil_json"])
            end_raw = json.loads(json.loads(interval.end_temporal_json)["raw_civil_json"])
            first, _, start_key = parse_steps_civil_endpoint(start_raw)
            last, _, end_key = parse_steps_civil_endpoint(end_raw)
        except (ValueError, KeyError, TypeError, OverflowError):
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
