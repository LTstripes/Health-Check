"""Bounded default-only sleep card over accepted source-night eligibility."""

from __future__ import annotations

from datetime import date
from itertools import groupby

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.analytics.sleep_source_view import (
    MAX_SOURCE_SLEEP_RECORDS,
    read_source_sleep_night,
    resolve_source_sleep_point,
)
from healthcheck.db.models import (
    GarminSleepRecord,
    GarminSource,
    GarminSourceRecord,
    GoogleSleepRecord,
    GoogleSource,
    GoogleSourceRecord,
)
from healthcheck.metric_source_selection import SourceCandidate, select_metric_source
from healthcheck.web.read_snapshot import ensure_read_snapshot

CONTRACT_VERSION = "data-saved-sleep-v1"
MAX_SOURCES = 32
MAX_DATE_GROUPS = 32
MAX_RECORDS = 256
PROVIDERS = {
    "garmin": (GarminSource, GarminSourceRecord, GarminSleepRecord, "garmin_source_id"),
    "google": (GoogleSource, GoogleSourceRecord, GoogleSleepRecord, "google_source_id"),
}


def read_saved_sleep(
    session: Session, *, provider: str, evaluation_local_date: date, source_id: str | None = None,
) -> dict:
    """No period fallback, pooling, refresh inference or new eligibility rule.

    Caller bounds SQLite work/time as well as opening a read-only connection.
    The accepted source reader resolves each complete dated group; sorting is
    by typed wake date, never the indexed but semantically different parent date.
    """
    if provider not in PROVIDERS or type(evaluation_local_date) is not date:
        raise ValueError("invalid saved sleep query")
    if source_id is not None and not source_id.strip():
        raise ValueError("invalid saved sleep source")
    ensure_read_snapshot(session)
    source_model, model, typed, source_column = PROVIDERS[provider]
    result = {
        "contract_version": CONTRACT_VERSION, "provider": provider,
        "evaluation_local_date": evaluation_local_date.isoformat(),
        "requested_source_id": source_id, "state": "unavailable", "reason": None,
        "available_sources": [], "source": None, "observation": None,
        "newer_exclusions": [], "search_complete": False,
        "snapshot_age": "unknown", "age_policy": "not_configured",
    }
    provider_code = "garmin_connect" if provider == "garmin" else "google_health"
    query = select(source_model).where(
        source_model.provider_code == provider_code
    ).order_by(source_model.id).limit(MAX_SOURCES + 1)
    if source_id is not None:
        query = query.where(source_model.id == source_id)
    sources = list(session.scalars(query))
    if len(sources) > MAX_SOURCES:
        result.update(state="search_incomplete", reason="source_inventory_cap")
        return result
    for source in sources:
        result["available_sources"].append({
            "source_id": source.id, "source_instance_id": source.source_instance_id,
            "source_kind": source.source_kind, "device_model": source.device_model,
        })
    if provider == "google" and source_id is None:
        def read_candidate(source):
            packet = read_saved_sleep(
                session, provider=provider, evaluation_local_date=evaluation_local_date,
                source_id=source.id,
            )
            return SourceCandidate(
                source, packet, int(packet["observation"] is not None),
                sum(item["state"] == "ambiguous" for item in packet["newer_exclusions"]),
                packet["search_complete"], packet["reason"],
            )

        decision = select_metric_source(sources, read_candidate, source_cap=MAX_SOURCES)
        selection = {"state": decision.state, "mode": "auto",
                     "selected_source_id": decision.chosen.source.id if decision.chosen else None}
        if decision.chosen:
            return {**decision.chosen.payload, "requested_source_id": None,
                    "available_sources": result["available_sources"], "source_selection": selection}
        # Keep single-source exclusion disclosure even when no night is usable.
        if decision.state == "no_eligible_values" and len(decision.candidates) == 1:
            return {**decision.candidates[0].payload, "requested_source_id": None,
                    "source_selection": selection}
        result.update(
            state={"selection_required": "ambiguous", "source_missing": "unavailable",
                   "no_eligible_values": "no_eligible_in_search"}.get(
                       decision.state, decision.state),
            reason={"selection_required": "source_selection_required",
                    "source_missing": "source_not_found"}.get(decision.state, decision.reason),
            search_complete=decision.state != "search_incomplete", source_selection=selection,
        )
        return result
    if len(sources) != 1:
        result.update(
            state="ambiguous" if sources else "unavailable",
            reason="source_selection_required" if sources else "source_not_found",
            search_complete=True,
        )
        return result
    result["source"] = result["available_sources"][0]
    source_id = sources[0].id
    conditions = (
        getattr(model, source_column) == source_id,
        model.stream_code == "sleep", model.projection_status == "current",
    )
    unplaced = session.scalar(
        select(model.id).outerjoin(typed, typed.record_id == model.id)
        .where(*conditions, typed.wake_date.is_(None)).limit(1)
    )
    if unplaced:
        result["newer_exclusions"].append({"wake_date": None, "state": "undated"})
    rows = list(session.execute(
        select(typed.wake_date, model.id).join(typed, typed.record_id == model.id)
        .where(*conditions, typed.wake_date <= evaluation_local_date)
        .order_by(typed.wake_date.desc(), model.id).limit(MAX_RECORDS + 1)
    ))
    examined = 0
    for day, items in groupby(rows, key=lambda row: row[0]):
        group = list(items)
        # The lookahead may be a partial group, never a trustworthy winner.
        if examined >= MAX_DATE_GROUPS or len(group) > MAX_SOURCE_SLEEP_RECORDS or (
            len(rows) > MAX_RECORDS and day == rows[-1][0]
        ):
            result.update(state="search_incomplete", reason="search_work_cap")
            return result
        examined += 1
        packet = read_source_sleep_night(
            session, provider=provider, wake_date=day, source_id=source_id,
        )
        if packet["state"] == "read_limit_exceeded":
            result.update(state="search_incomplete", reason="night_read_cap")
            return result
        point = resolve_source_sleep_point(
            packet["sources"][0] if packet["sources"] else {"sessions": []}, provider=provider,
        )
        if point["state"] == "value":
            result.update(
                state="exact" if day == evaluation_local_date else "last_eligible",
                search_complete=True,
                observation={**point, "wake_date": day.isoformat(),
                             "observation_age_days": (evaluation_local_date - day).days},
            )
            return result
        result["newer_exclusions"].append({
            "wake_date": day.isoformat(), "state": point["state"], "reason": point["reason"],
        })
    result.update(state="no_eligible_in_search", search_complete=True)
    return result
