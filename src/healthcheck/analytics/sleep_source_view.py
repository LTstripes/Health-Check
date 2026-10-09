"""Bounded #317 source-only view of one persisted local wake date.

This adapter does not pair nights, select a main/canonical source, or write a
projection. R05 account-observation eligibility and single-side validators
decide each field; uncertain roles and explicit nap exclusions remain visible.
This view establishes neither device agreement nor canonical eligibility.
Garmin native score and calendar-day nap duration keep their separate persisted
scalar identities.
Raw payload bodies are never opened. Original timing evidence is retained;
UTC display never applies the host's current offset.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from healthcheck.analytics.sleep_metrics import (
    SLEEP_CANONICAL_METRIC_CODES,
    _excluded_stage_outcome,
    _garmin_timing_outcome,
    _google_sleep_variant,
    _google_timing_outcome,
    _iso_utc,
    _load_garmin_sleep_record_side,
    _load_google_sleep_record_side,
    _metric_input,
    _outcome_from_scalar,
    _stage_projection_outcome,
    _StoredSleepSide,
    _tib_outcome,
    _with_variant_gate,
)
from healthcheck.analytics.sleep_pairing import (
    ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS,
    _google_observation_role,
)
from healthcheck.db.models import (
    GarminSleepRecord,
    GarminSourceRecord,
    GoogleSleepRecord,
    GoogleSourceRecord,
)
from healthcheck.web.read_snapshot import ensure_read_snapshot

# A pathological date fails closed instead of displaying a winning prefix.
MAX_SOURCE_SLEEP_RECORDS = 200
MAX_SOURCE_SLEEP_RANGE_RECORDS = 400
SOURCE_SLEEP_RANGE_VERSION = "source-sleep-range-v1"


def _canonical_outcome(side: _StoredSleepSide, code: str, variant: str | None):
    if code == "sleep_duration_asleep_seconds":
        if side.provider == "garmin":
            return _outcome_from_scalar(
                side, metric_code="sleep_duration_seconds", expected_unit="seconds", variant=variant
            )
        return _outcome_from_scalar(
            side, metric_code="sleep_summary_minutes_asleep", expected_unit="min",
            multiplier=60, output_unit="seconds", variant=variant,
        )
    if code == "sleep_time_in_bed_seconds":
        return _tib_outcome(side, variant=variant)
    if code in {"sleep_start_at", "sleep_end_at"}:
        reader = _garmin_timing_outcome if side.provider == "garmin" else _google_timing_outcome
        return reader(
            side, endpoint="start" if code == "sleep_start_at" else "end", variant=variant
        )
    target = {
        "sleep_stage_light_seconds": "LIGHT",
        "sleep_stage_deep_seconds": "DEEP",
        "sleep_stage_rem_seconds": "REM",
        "sleep_awake_waso_seconds": "AWAKE",
    }[code]
    if side.provider == "google" and variant == "CLASSIC":
        return _excluded_stage_outcome(side, variant=variant)
    return _stage_projection_outcome(side, target=target, variant=variant)


def _session_view(side: _StoredSleepSide, wake_date: date) -> dict[str, Any]:
    source_decision = dict(side.evidence.attribution["source_eligibility"])
    reason = source_decision.get("reason")
    if side.record.record_status == "invalid":
        reason = reason or f"{side.provider}_record_invalid"
    role: dict[str, Any] | None = None
    if side.provider == "google":
        decision = _google_observation_role(side.metrics)
        role = {
            "main_state": decision[2], "nap_state": decision[3],
            "main_value": decision[4], "nap_value": decision[5],
            "selection": decision[6] if len(decision) > 6 else None,
            "reason": decision[1] or None,
        }
        if decision[0] is None:
            reason = reason or decision[1]
    # A Garmin-only view has no Google variant to infer or require.
    variant = None if side.provider == "garmin" else _google_sleep_variant(side)
    metrics = {}
    for code in SLEEP_CANONICAL_METRIC_CODES:
        outcome = _canonical_outcome(side, code, variant)
        if side.provider == "google":
            outcome = _with_variant_gate(outcome, variant=variant)
        if reason and outcome.eligible:
            outcome = replace(
                outcome, eligible=False, reason=str(reason), exclusion_basis=str(reason)
            )
        metrics[code] = _metric_input(
            provider=side.provider, record_id=side.record.id, outcome=outcome
        ).as_dict()
    if side.provider == "garmin":
        for code, unit in (("sleep_score", "points"), ("nap_duration_seconds", "seconds")):
            outcome = _outcome_from_scalar(side, metric_code=code, expected_unit=unit, variant=None)
            if reason and outcome.eligible:
                outcome = replace(
                    outcome, eligible=False, reason=str(reason), exclusion_basis=str(reason)
                )
            metrics[code] = _metric_input(
                provider="garmin", record_id=side.record.id, outcome=outcome
            ).as_dict()
    record = side.record
    return {
        "record_id": record.id, "wake_date": wake_date.isoformat(),
        "record_status": record.record_status,
        "source_eligibility": source_decision, "reason": reason, "role": role,
        "variant": variant, "metrics": metrics,
        "field_states": {
            "session": side.field_state.sleep_interval_state,
            "stages": side.field_state.sleep_stages_state,
            "out_of_bed": side.field_state.out_of_bed_state,
        } if side.field_state is not None else None,
        "temporal_evidence": {
            "precision": record.temporal_precision,
            "source_local_date": (
                record.source_local_date.isoformat() if record.source_local_date else None
            ),
            "source_timestamp_utc": _iso_utc(record.source_timestamp_utc),
            "source_local_timestamp": record.source_local_timestamp,
            "local_wall_time": record.local_wall_time,
            "source_utc_offset_minutes": record.source_utc_offset_minutes,
            "source_timezone": record.source_timezone,
        },
    }


def read_source_sleep_night(
    session: Session, *, provider: str, wake_date: date, source_id: str | None = None,
) -> dict[str, Any]:
    """Read current typed sessions, grouped by exact source, for one date only.

    Multiple sessions remain separate; there is no longest/latest winner,
    source pooling, earlier-date fallback or fabricated cross-source pair.
    Ineligible cells keep their persisted state/value/evidence for disclosure.
    """
    if provider not in {"garmin", "google"}:
        raise ValueError("source sleep provider must be garmin or google")
    if not isinstance(wake_date, date):
        raise ValueError("source sleep wake_date must be a date")
    record_type, typed, source_column, loader = (
        (GarminSourceRecord, GarminSleepRecord, GarminSourceRecord.garmin_source_id,
         _load_garmin_sleep_record_side)
        if provider == "garmin" else
        (GoogleSourceRecord, GoogleSleepRecord, GoogleSourceRecord.google_source_id,
         _load_google_sleep_record_side)
    )
    query = (
        select(record_type.id)
        .join(typed, typed.record_id == record_type.id)
        .where(record_type.stream_code == "sleep", record_type.projection_status == "current",
               typed.wake_date == wake_date)
        .order_by(source_column, record_type.id)
        .limit(MAX_SOURCE_SLEEP_RECORDS + 1)
    )
    if source_id is not None:
        query = query.where(source_column == source_id)
    record_ids = tuple(session.scalars(query))
    result: dict[str, Any] = {
        "provider": provider, "wake_date": wake_date.isoformat(), "sources": [],
        "state": "no_records", "limit": MAX_SOURCE_SLEEP_RECORDS,
    }
    if len(record_ids) > MAX_SOURCE_SLEEP_RECORDS:
        result["state"] = "read_limit_exceeded"
        return result
    result["sources"] = _night_sources(session, record_ids, loader, wake_date)
    result["state"] = "records" if result["sources"] else "no_records"
    return result


def _night_sources(session, record_ids, loader, wake_date: date) -> list[dict[str, Any]]:
    """Shared typed disclosure; keep the one-night packet unchanged."""
    sources: dict[str, dict[str, Any]] = {}
    for record_id in record_ids:
        side = loader(session, record_id, cohort=ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS)
        if side is None:
            continue
        source = side.source
        item = sources.setdefault(source.id, {
            "source": {
                "source_id": source.id, "source_kind": source.source_kind,
                "source_instance_id": source.source_instance_id,
                "device_attributed": source.device_attributed,
                "device_code": source.device_code, "device_model": source.device_model,
                "device_manufacturer": getattr(source, "device_manufacturer", None),
                "platform": getattr(source, "platform", None),
                "data_source_name": getattr(source, "data_source_name", None),
            },
            "sessions": [],
        })
        item["sessions"].append(_session_view(side, wake_date))
    for item in sources.values():
        item["ambiguous"] = len(item["sessions"]) > 1
        item["summary"] = item["sessions"][0] if not item["ambiguous"] else None
    return list(sources.values())


def resolve_source_sleep_point(source: dict[str, Any], *, provider: str) -> dict[str, Any]:
    """Resolve one exact source/date from typed night disclosure, without mutation.

    Source/record/role gates precede uniqueness; duration values never choose a
    session. Google explicit-main preference precedes its uncertain singleton
    fallback. Excluded sessions stay disclosed in the original night packet.
    """
    if provider not in {"garmin", "google"}:
        raise ValueError("source sleep provider must be garmin or google")
    exclusions = []
    candidates = []
    for item in source["sessions"]:
        if item["reason"]:
            exclusions.append({"record_id": item["record_id"], "reason": item["reason"]})
        else:
            candidates.append(item)
    if provider == "google":
        preferred = [i for i in candidates if i["role"]["selection"] == "explicit_main"]
        if preferred:
            exclusions.extend({"record_id": i["record_id"],
                               "reason": "google_explicit_main_preferred"}
                              for i in candidates if i not in preferred)
            candidates = preferred
    point = {
        "state": "no_records" if not source["sessions"] else "unavailable",
        "value": None, "unit": "seconds", "record_id": None,
        "reason": None, "is_zero": False, "partial": False,
        "role_uncertain": False, "candidate_record_ids": [i["record_id"] for i in candidates],
        "exclusions": exclusions,
    }
    if len(candidates) > 1:
        point.update(state="ambiguous", reason=f"ambiguous_{provider}_main")
    elif candidates:
        item = candidates[0]
        cell = item["metrics"]["sleep_duration_asleep_seconds"]
        point.update(record_id=item["record_id"], partial=item["record_status"] == "partial",
                     role_uncertain=provider == "google" and
                     item["role"]["selection"] != "explicit_main")
        if cell["eligible"]:
            point.update(state="value", value=cell["value"], is_zero=cell["is_zero"])
        else:
            point.update(state=cell["state"] if cell["state"] != "value" else "unavailable",
                         reason=cell["reason"])
    elif exclusions:
        point["reason"] = exclusions[0]["reason"]
    return point


def read_source_sleep_range(
    session: Session, *, provider: str, wake_date: date, days: int = 30,
    source_id: str | None = None,
) -> dict[str, Any]:
    """V1 independent 7/30 inclusive persisted source-local wake dates.

    One bounded presence scan and typed loaders share a physical read snapshot.
    Null wake dates count only when the parent has a persisted source_local_date
    within this window; UTC, acquisition time and host offsets are never fallback
    dates. Those rows count toward the 400/provider cap, separately per source,
    and never become plotted nights. Unlocatable null dates are outside this
    bounded read. The existing 200-record one-night cap also fails the range
    closed. Overflow returns no days/series or misleading completeness counts.

    `days` preserves exact one-night packets. `series` resolves one point per
    requested date per exact source, including explicit gaps. Observed/missing
    dates describe stored row presence, not sleep or acquisition coverage.
    No pairing, canonical selection, raw bodies, writes or provider calls.
    Caller owns the transaction, including when embedding in an SSR snapshot.
    """
    if provider not in {"garmin", "google"}:
        raise ValueError("source sleep provider must be garmin or google")
    if type(wake_date) is not date:
        raise ValueError("source sleep wake_date must be a date")
    if type(days) is not int or days not in {7, 30}:
        raise ValueError("source sleep range days must be 7 or 30")
    start = wake_date - timedelta(days=days - 1)
    dates = [start + timedelta(days=i) for i in range(days)]
    model, typed, column, loader = (
        (GarminSourceRecord, GarminSleepRecord, GarminSourceRecord.garmin_source_id,
         _load_garmin_sleep_record_side) if provider == "garmin" else
        (GoogleSourceRecord, GoogleSleepRecord, GoogleSourceRecord.google_source_id,
         _load_google_sleep_record_side)
    )
    result = {
        "contract_version": SOURCE_SLEEP_RANGE_VERSION, "provider": provider,
        "start_date": start.isoformat(), "end_date": wake_date.isoformat(),
        "state": "no_records", "days": [], "series": [],
        "observed_dates": None, "missing_dates": None, "wake_date_missing_count": None,
        "wake_date_missing_by_source": None, "limit": MAX_SOURCE_SLEEP_RANGE_RECORDS,
    }
    ensure_read_snapshot(session)
    query = (
        select(model.id, typed.wake_date, column)
        .outerjoin(typed, typed.record_id == model.id)
        .where(model.stream_code == "sleep", model.projection_status == "current",
               or_(typed.wake_date.between(start, wake_date),
                   typed.wake_date.is_(None) & model.source_local_date.between(start, wake_date)))
        .order_by(typed.wake_date, column, model.id)
        .limit(MAX_SOURCE_SLEEP_RANGE_RECORDS + 1)
    )
    if source_id is not None:
        query = query.where(column == source_id)
    rows = list(session.execute(query))
    by_date: dict[date, list[str]] = {}
    missing_by_source: dict[str, int] = {}
    for record_id, local_date, identity in rows:
        if local_date is None:
            missing_by_source[identity] = missing_by_source.get(identity, 0) + 1
        else:
            by_date.setdefault(local_date, []).append(record_id)
    if len(rows) > MAX_SOURCE_SLEEP_RANGE_RECORDS or any(
        len(ids) > MAX_SOURCE_SLEEP_RECORDS for ids in by_date.values()
    ):
        result["state"] = "read_limit_exceeded"
        return result
    series: dict[str, dict[str, Any]] = {}
    for local_date in dates:
        sources = _night_sources(session, by_date.get(local_date, ()), loader, local_date)
        night = {"provider": provider, "wake_date": local_date.isoformat(), "sources": sources,
                 "state": "records" if sources else "no_records", "limit": MAX_SOURCE_SLEEP_RECORDS}
        result["days"].append(night)
        for source in sources:
            identity = source["source"]["source_id"]
            series.setdefault(identity, {"source": source["source"], "points": []})
    for identity, item in series.items():
        for night in result["days"]:
            source = next((s for s in night["sources"] if s["source"]["source_id"] == identity),
                          {"sessions": []})
            item["points"].append({"wake_date": night["wake_date"],
                                   **resolve_source_sleep_point(source, provider=provider)})
    result.update(state="records" if rows else "no_records", series=list(series.values()),
                  observed_dates=[d.isoformat() for d in dates if d in by_date],
                  missing_dates=[d.isoformat() for d in dates if d not in by_date],
                  wake_date_missing_count=sum(missing_by_source.values()),
                  wake_date_missing_by_source=missing_by_source)
    return result
