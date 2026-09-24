"""Owner presentation DTO for persisted Garmin Training & recovery evidence (#187).

Read-only. Consumes the #180 private read contract only. Never calls a provider,
never writes, never invents units or recomputes proprietary Garmin metrics.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.db.models import GarminSourceRecord
from healthcheck.garmin.training import TRAINING_CONTRACT_VERSION, read_training_evidence

TRAINING_OVERVIEW_CONTRACT = "garmin-training-owner-view-v1"
DEFAULT_RECENT_ACTIVITIES = 5
MAX_RECENT_ACTIVITIES = 10

_STATUS_FIELD_CODES = (
    "trainingStatus",
    "trainingStatusFeedbackPhrase",
    "dailyTrainingLoadAcute",
    "dailyTrainingLoadChronic",
    "acwrPercent",
    "dailyAcuteChronicWorkloadRatio",
    "acwrStatus",
)
_LOAD_FOCUS_FIELD_CODES = (
    "monthlyLoadAerobicLow",
    "monthlyLoadAerobicHigh",
    "monthlyLoadAnaerobic",
    "monthlyLoadAerobicLowTargetMin",
    "monthlyLoadAerobicLowTargetMax",
    "monthlyLoadAerobicHighTargetMin",
    "monthlyLoadAerobicHighTargetMax",
    "monthlyLoadAnaerobicTargetMin",
    "monthlyLoadAnaerobicTargetMax",
)
_READINESS_FIELD_CODES = (
    "score",
    "level",
    "recoveryTime",
    "recoveryTimeFactorPercent",
    "recoveryTimeFactorFeedback",
    "recoveryTimeChangePhrase",
    "acuteLoad",
    "acwrFactorPercent",
    "acwrFactorFeedback",
    "inputContext",
)
_ACTIVITY_FIELD_CODES = (
    "activityTrainingLoad",
    "aerobicTrainingEffect",
    "anaerobicTrainingEffect",
    "trainingEffectLabel",
)
_RECOVERY_TIME_CODE = "recoveryTime"

_ATTRIBUTION_LABELS = {
    "associated_device": "associated device",
    "activity_recorder": "activity recorder",
    "account": "account",
}

TRAINING_OVERVIEW_WORDING = {
    "garmin_native": "Garmin-native",
    "associated_device": "associated device",
    "activity_recorder": "activity recorder",
    "metric_producer_unverified": "metric producer unverified",
    "disclaimer": (
        "Garmin-native Training & recovery from persisted evidence only. "
        "No custom readiness/status/load score, no coaching or medical claims, "
        "and no provider calls from this view."
    ),
}


def _chronology_key(row: dict[str, Any]) -> tuple[str, str, str]:
    """Source chronology only — never requested acquisition dates."""

    return (
        row.get("source_date") or "",
        row.get("source_timestamp_utc") or "",
        row.get("record_id") or "",
    )


def _present_field(raw: dict[str, Any] | None, *, recovery_time: bool = False) -> dict[str, Any]:
    """Map #180 field state to owner presentation; never coerce missing to 0."""

    if raw is None:
        presented: dict[str, Any] = {"state": "missing", "value": None}
    else:
        state = str(raw.get("state") or "missing")
        value = raw.get("value")
        if state == "value" and isinstance(value, (int, float)) and not isinstance(value, bool):
            if value == 0 or value == 0.0:
                presented = {"state": "zero", "value": 0 if float(value) == 0.0 else value}
            else:
                presented = {"state": "value", "value": value}
        elif state == "value":
            presented = {"state": "value", "value": value}
        elif state in {"missing", "null", "invalid"}:
            presented = {"state": state, "value": None}
        else:
            presented = {"state": state or "unavailable", "value": None}
    if recovery_time:
        # Accepted #180 contract does not encode recoveryTime units. Do not guess.
        presented["unit_status"] = "unavailable"
        presented["unit"] = None
        presented["presentation"] = "garmin_native"
    return presented


def _present_fields(
    fields: dict[str, Any],
    codes: tuple[str, ...],
) -> dict[str, Any]:
    presented: dict[str, Any] = {}
    for code in codes:
        presented[code] = _present_field(
            fields.get(code) if isinstance(fields, dict) else None,
            recovery_time=code == _RECOVERY_TIME_CODE,
        )
    return presented


def _attribution_label(attribution: str | None) -> str:
    if not attribution:
        return _ATTRIBUTION_LABELS["account"]
    return _ATTRIBUTION_LABELS.get(attribution, attribution.replace("_", " "))


def _pick_latest(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return max(rows, key=_chronology_key)


def _empty_overview(
    *,
    status: str,
    reason: str,
    garmin_source_id: str | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": TRAINING_OVERVIEW_CONTRACT,
        "evidence_contract_version": TRAINING_CONTRACT_VERSION,
        "status": status,
        "reason": reason,
        "garmin_source_id": garmin_source_id,
        "metric_producer": "unverified",
        "wording": dict(TRAINING_OVERVIEW_WORDING),
        "training_status": None,
        "load_focus": None,
        "readiness": None,
        "recent_activities": [],
        "availability": {
            "has_status": False,
            "has_load_focus": False,
            "has_readiness": False,
            "has_activities": False,
            "readiness_snapshot_count": 0,
            "activity_count": 0,
        },
    }


def _status_block(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_date": row.get("source_date"),
        "source_timestamp_utc": row.get("source_timestamp_utc"),
        "attribution": row.get("attribution"),
        "attribution_label": _attribution_label(row.get("attribution")),
        "metric_producer": "unverified",
        "fields": _present_fields(row.get("fields") or {}, _STATUS_FIELD_CODES),
    }


def _load_focus_block(row: dict[str, Any]) -> dict[str, Any]:
    source_date = row.get("source_date")
    return {
        "source_date": source_date,
        "dated": source_date is not None,
        "source_timestamp_utc": row.get("source_timestamp_utc"),
        "attribution": row.get("attribution"),
        "attribution_label": _attribution_label(row.get("attribution")),
        "metric_producer": "unverified",
        "fields": _present_fields(row.get("fields") or {}, _LOAD_FOCUS_FIELD_CODES),
    }


def _readiness_block(row: dict[str, Any], *, snapshot_count: int) -> dict[str, Any]:
    return {
        "source_date": row.get("source_date"),
        "source_timestamp_utc": row.get("source_timestamp_utc"),
        "source_local_timestamp": row.get("source_local_timestamp"),
        "attribution": row.get("attribution"),
        "attribution_label": _attribution_label(row.get("attribution")),
        "metric_producer": "unverified",
        "snapshot_count": snapshot_count,
        "fields": _present_fields(row.get("fields") or {}, _READINESS_FIELD_CODES),
    }


def _activity_block(row: dict[str, Any], *, activity_type: str | None) -> dict[str, Any]:
    fields = dict(row.get("fields") or {})
    # Never surface activity recorder device identifiers in owner presentation.
    fields.pop("activityRecorderDeviceId", None)
    return {
        "activity_type": activity_type,
        "source_date": row.get("source_date"),
        "source_timestamp_utc": row.get("source_timestamp_utc"),
        "attribution": row.get("attribution"),
        "attribution_label": _attribution_label(row.get("attribution")),
        "metric_producer": "unverified",
        "fields": _present_fields(fields, _ACTIVITY_FIELD_CODES),
    }


def _activity_types(session: Session, record_ids: list[str]) -> dict[str, str | None]:
    if not record_ids:
        return {}
    rows = session.scalars(
        select(GarminSourceRecord).where(GarminSourceRecord.id.in_(record_ids))
    )
    return {row.id: row.activity_type for row in rows}


def build_training_overview(
    session: Session,
    *,
    garmin_source_id: str,
    activity_limit: int = DEFAULT_RECENT_ACTIVITIES,
) -> dict[str, Any]:
    """Build a sanitized Training & recovery overview for one explicit source."""

    limit = int(activity_limit)
    if not 1 <= limit <= MAX_RECENT_ACTIVITIES:
        raise ValueError("activity_limit must be between 1 and 10")
    evidence = list(read_training_evidence(session, garmin_source_id=garmin_source_id, limit=200))
    status_rows = [row for row in evidence if row.get("kind") == "status"]
    balance_rows = [row for row in evidence if row.get("kind") == "load_balance"]
    readiness_rows = [row for row in evidence if row.get("kind") == "readiness"]
    activity_rows = [row for row in evidence if row.get("kind") == "activity"]

    if not status_rows and not balance_rows and not readiness_rows and not activity_rows:
        return _empty_overview(
            status="no_training_evidence",
            reason="no_training_evidence",
            garmin_source_id=garmin_source_id,
        )

    latest_status = _pick_latest(status_rows)
    # Undated load-focus stays undated; chronology uses source fields only.
    latest_balance = _pick_latest(balance_rows)
    latest_readiness = _pick_latest(readiness_rows)

    ordered_activities = sorted(activity_rows, key=_chronology_key, reverse=True)[:limit]
    type_by_id = _activity_types(
        session, [row["record_id"] for row in ordered_activities if row.get("record_id")]
    )
    recent = [
        _activity_block(row, activity_type=type_by_id.get(row.get("record_id") or ""))
        for row in ordered_activities
    ]

    return {
        "contract_version": TRAINING_OVERVIEW_CONTRACT,
        "evidence_contract_version": TRAINING_CONTRACT_VERSION,
        "status": "available",
        "reason": None,
        "garmin_source_id": garmin_source_id,
        "metric_producer": "unverified",
        "wording": dict(TRAINING_OVERVIEW_WORDING),
        "training_status": _status_block(latest_status) if latest_status else None,
        "load_focus": _load_focus_block(latest_balance) if latest_balance else None,
        "readiness": (
            _readiness_block(latest_readiness, snapshot_count=len(readiness_rows))
            if latest_readiness
            else None
        ),
        "recent_activities": recent,
        "availability": {
            "has_status": latest_status is not None,
            "has_load_focus": latest_balance is not None,
            "has_readiness": latest_readiness is not None,
            "has_activities": bool(recent),
            "readiness_snapshot_count": len(readiness_rows),
            "activity_count": len(recent),
        },
    }


def training_overview_for_selection(
    session: Session,
    *,
    source_selection: dict[str, Any],
    activity_limit: int = DEFAULT_RECENT_ACTIVITIES,
) -> dict[str, Any]:
    """Map Garmin source-selection outcomes to an honest Training overview."""

    status = source_selection.get("status")
    if status == "no_data":
        return _empty_overview(
            status="no_data",
            reason=str(source_selection.get("reason") or "no_garmin_sources"),
        )
    if status == "require_selection":
        return _empty_overview(
            status="require_selection",
            reason=str(source_selection.get("reason") or "multiple_garmin_sources"),
        )
    selected_id = source_selection.get("selected_source_id")
    if not selected_id:
        return _empty_overview(status="no_data", reason="no_garmin_sources")
    return build_training_overview(
        session,
        garmin_source_id=str(selected_id),
        activity_limit=activity_limit,
    )


def unavailable_training_overview(*, reason: str = "no_data") -> dict[str, Any]:
    return _empty_overview(status="no_data", reason=reason)


__all__ = [
    "DEFAULT_RECENT_ACTIVITIES",
    "MAX_RECENT_ACTIVITIES",
    "TRAINING_OVERVIEW_CONTRACT",
    "TRAINING_OVERVIEW_WORDING",
    "build_training_overview",
    "training_overview_for_selection",
    "unavailable_training_overview",
]
