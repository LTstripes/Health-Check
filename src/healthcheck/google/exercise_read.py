"""Read only saved Google exercise sessions, with explicit source separation."""

from datetime import date

from sqlalchemy import select

from healthcheck.db.models import (
    GoogleRecordInterval,
    GoogleRecordMetric,
    GoogleSource,
    GoogleSourceRecord,
)
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.google.contracts import FAMILY_GOOGLE_WEARABLES
from healthcheck.google.exercise import ACQUISITION_CONTRACT, CONTRACT

MAX_SOURCES = 25
MAX_SESSIONS = 200


def _offset_label(minutes):
    if minutes is None:
        return None
    return f"{'+' if minutes >= 0 else '-'}{abs(minutes) // 60:02}:{abs(minutes) % 60:02}"


def read_saved_exercise(
    session,
    *,
    source_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
):
    if (start_date is None) != (end_date is None) or (
        start_date is not None and not 0 <= (end_date - start_date).days < 30
    ):
        raise ValueError("exercise window must be 1-30 civil start dates")
    eligible = (
        GoogleSourceRecord.stream_code == "exercise",
        GoogleSourceRecord.query_mode == "list",
        GoogleSourceRecord.data_source_family == FAMILY_GOOGLE_WEARABLES,
        GoogleSourceRecord.source_contract_version.in_((CONTRACT, ACQUISITION_CONTRACT)),
        GoogleSourceRecord.normalization_contract_version == CONTRACT,
        GoogleSourceRecord.projection_status == "current",
    )
    sources = list(
        session.scalars(
            select(GoogleSource)
            .where(
                GoogleSource.id.in_(select(GoogleSourceRecord.google_source_id).where(*eligible))
            )
            .order_by(GoogleSource.id)
            .limit(MAX_SOURCES + 1)
        )
    )
    packet = {
        "sources": [],
        "selected_source_id": source_id,
        "sessions": [],
        "search_complete": False,
        "provider_history_complete": False,
        "coverage": "unknown",
        "pagination": "unknown",
        "finality": "unknown",
        "start_date": start_date,
        "end_date": end_date,
        "reason": None,
        "session_cap": MAX_SESSIONS,
    }
    if len(sources) > MAX_SOURCES:
        return {**packet, "reason": "source_search_incomplete"}
    packet["sources"] = [
        {"source_id": s.id, "label": f"Google / Fitbit {i + 1}"} for i, s in enumerate(sources)
    ]
    if not source_id and len(sources) == 1:
        source_id = sources[0].id
    packet["selected_source_id"] = source_id
    if not source_id:
        return {
            **packet,
            "search_complete": True,
            "reason": "selection_required" if sources else "no_saved_exercise",
        }
    if source_id not in {s.id for s in sources}:
        raise ValueError("unknown exercise source")
    statement = select(GoogleSourceRecord).where(
        *eligible, GoogleSourceRecord.google_source_id == source_id
    )
    if start_date:
        statement = statement.where(
            GoogleSourceRecord.source_local_date >= start_date,
            GoogleSourceRecord.source_local_date <= end_date,
        )
    rows = list(
        session.scalars(
            statement.order_by(
                GoogleSourceRecord.source_timestamp_utc.desc(), GoogleSourceRecord.id
            ).limit(MAX_SESSIONS + 1)
        )
    )
    if len(rows) > MAX_SESSIONS:
        return {**packet, "reason": "session_search_incomplete"}
    ids = [r.id for r in rows]
    metrics = {}
    for metric in session.scalars(
        select(GoogleRecordMetric).where(GoogleRecordMetric.record_id.in_(ids))
    ):
        metrics.setdefault(metric.record_id, {})[metric.metric_code] = metric
    intervals = {
        i.record_id: i
        for i in session.scalars(
            select(GoogleRecordInterval).where(
                GoogleRecordInterval.record_id.in_(ids),
                GoogleRecordInterval.interval_kind == "exercise_session",
                GoogleRecordInterval.ordinal == 0,
            )
        )
    }
    for row in rows:
        values = metrics.get(row.id, {})
        interval = intervals.get(row.id)
        usable = row.record_status in {"ok", "partial"} and interval is not None

        def number(code):
            value = values.get(code)
            return value.value_number if usable and value and value.state == "value" else None

        kind = values.get("exercise_type")
        packet["sessions"].append(
            {
                "record_id": row.id,
                "type": kind.value_text if usable and kind and kind.state == "value" else None,
                "start_local": interval.start_local_wall_time if usable else None,
                "end_local": interval.end_local_wall_time if usable else None,
                "start_at_utc": restore_stored_utc(interval.start_at_utc) if usable else None,
                "end_at_utc": restore_stored_utc(interval.end_at_utc) if usable else None,
                "start_offset_minutes": interval.start_utc_offset_minutes if usable else None,
                "end_offset_minutes": interval.end_utc_offset_minutes if usable else None,
                "start_offset_label": _offset_label(interval.start_utc_offset_minutes)
                if usable
                else None,
                "end_offset_label": _offset_label(interval.end_utc_offset_minutes)
                if usable
                else None,
                "active_seconds": number("exercise_active_duration_seconds"),
                "elapsed_seconds": number("exercise_elapsed_seconds"),
                "state": row.record_status if usable else "unavailable",
            }
        )
    packet["search_complete"] = True
    return packet
