"""Steps-only acquisition progress; never provider coverage or a history engine."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.config import Settings
from healthcheck.db.models import GooglePayloadObservation, SyncRun, SyncStreamState
from healthcheck.db.repositories import repositories_for
from healthcheck.google.persistence import google_persistence_for
from healthcheck.google.steps import (
    ACQUISITION_CONTRACT,
    ACQUISITION_NORMALIZATION,
    IDENTITY,
    QUERY,
    StepsPlan,
    _unique_keys,
    replay_context,
)
from healthcheck.google.sync import _google_execution_resources

STEPS_REFRESH_CONTRACT = "google-steps-owner-catchup-v1"
STEPS_REFRESH_STATE_CODE = STEPS_REFRESH_CONTRACT
STEPS_REFRESH_SELECTION_ZONE = "Europe/Moscow"
MAX_REFRESH_DATES = 7
_BINDING = {
    "provider": IDENTITY.provider_code,
    "source_kind": IDENTITY.source_kind.value,
    "source_instance": IDENTITY.source_instance_id,
    "family": QUERY.data_source_family,
    "query_mode": QUERY.query_mode.value,
    "acquisition_contract": ACQUISITION_CONTRACT,
    "normalization_contract": ACQUISITION_NORMALIZATION,
    "selection_zone": STEPS_REFRESH_SELECTION_ZONE,
}


class StepsRefreshStateError(ValueError):
    """Progress or its exact acquisition receipt is unavailable/incompatible."""

    def __init__(self) -> None:
        super().__init__("steps_catchup_state_invalid")


@dataclass(frozen=True, slots=True)
class StepsRefreshProgress:
    state_id: str
    cursor: str
    source_id: str
    activation_floor: date
    next_date: date

    def dates(self, as_of: date) -> tuple[date, ...]:
        if type(as_of) is not date or not self.activation_floor < as_of:
            raise StepsRefreshStateError()
        if self.next_date > as_of:
            # A backwards clock must not move the floor/cursor or acquire older history.
            raise StepsRefreshStateError()
        yesterday = as_of - timedelta(days=1)
        if self.next_date == as_of:
            return (yesterday,)
        count = min(MAX_REFRESH_DATES, (as_of - self.next_date).days)
        return tuple(self.next_date + timedelta(days=i) for i in range(count))


def _day(value: object) -> date:
    if not isinstance(value, str):
        raise StepsRefreshStateError()
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise StepsRefreshStateError() from exc
    if parsed.isoformat() != value:
        raise StepsRefreshStateError()
    return parsed


def _receipt(session: Session, value: object, *, source, expected_day: date) -> None:
    if not isinstance(value, dict) or set(value) != {"day", "observation_id", "run_id"}:
        raise StepsRefreshStateError()
    if _day(value["day"]) != expected_day or any(
        not isinstance(value[key], str) or not 1 <= len(value[key]) <= 100
        for key in ("observation_id", "run_id")
    ):
        raise StepsRefreshStateError()
    observation = session.get(GooglePayloadObservation, value["observation_id"])
    run = session.get(SyncRun, value["run_id"])
    if (
        observation is None
        or run is None
        or observation.sync_run_id != run.id
        or observation.google_source_id != source.id
        or observation.stream_code != "steps"
        or observation.query_mode != QUERY.query_mode.value
        or observation.data_source_family != QUERY.data_source_family
        or observation.source_contract_version != ACQUISITION_CONTRACT
        or observation.normalization_contract_version != ACQUISITION_NORMALIZATION
        or observation.parse_status not in {"ok", "empty"}
        or observation.payload_format != "json"
        or observation.source_window_start_utc is not None
        or observation.source_window_end_utc is not None
        or run.provider_id != source.provider_id
        or run.stream_code != ACQUISITION_CONTRACT
        or run.status != "succeeded"
        or run.completed_at is None
        or run.received_count != observation.record_count
        or run.requested_start is not None
        or run.requested_end is not None
        or run.actual_start is not None
        or run.actual_end is not None
    ):
        raise StepsRefreshStateError()
    try:
        context = replay_context(observation.diagnostics_json)
        if context != StepsPlan(expected_day).context(context["request_count"]):
            raise StepsRefreshStateError()
    except (ValueError, KeyError, TypeError) as exc:
        raise StepsRefreshStateError() from exc


def _progress(session: Session, state: SyncStreamState, source) -> StepsRefreshProgress:
    if (
        state.stream_code != STEPS_REFRESH_STATE_CODE
        or state.provider_id != source.provider_id
        or state.acquisition_source_id != source.acquisition_source_id
        or source.provider_code != IDENTITY.provider_code
        or source.source_instance_id != IDENTITY.source_instance_id
        or source.source_kind != IDENTITY.source_kind.value
        or source.source_contract_version != IDENTITY.source_contract_version
        or state.watermark is not None
        or not isinstance(state.cursor, str)
        or len(state.cursor) > 4096
    ):
        raise StepsRefreshStateError()
    try:
        value = json.loads(state.cursor, object_pairs_hook=_unique_keys)
    except (ValueError, TypeError) as exc:
        raise StepsRefreshStateError() from exc
    if (
        not isinstance(value, dict)
        or set(value)
        != {"contract", "binding", "source_id", "activation_floor", "next_date", "receipt"}
        or value["contract"] != STEPS_REFRESH_CONTRACT
        or value["binding"] != _BINDING
        or value["source_id"] != source.id
    ):
        raise StepsRefreshStateError()
    floor, next_date = _day(value["activation_floor"]), _day(value["next_date"])
    if floor == date.max or not floor <= next_date:
        raise StepsRefreshStateError()
    if value["receipt"] is None:
        if next_date != floor:
            raise StepsRefreshStateError()
    else:
        if next_date <= floor:
            raise StepsRefreshStateError()
        _receipt(
            session, value["receipt"], source=source, expected_day=next_date - timedelta(days=1)
        )
    return StepsRefreshProgress(state.id, state.cursor, source.id, floor, next_date)


def activate_steps_refresh(settings: Settings, *, as_of: date) -> StepsRefreshProgress:
    """Commit the declared source/floor before any provider auth; validate on resume.

    Caller holds the owner profile lock. The fixed family aggregate is an explicit
    adapter identity, never a first-observed source or a proof of provider coverage.
    """
    if type(as_of) is not date or as_of == date.min:
        raise StepsRefreshStateError()
    with _google_execution_resources(settings) as resources, resources.factory() as session:
        source = google_persistence_for(session).sources.get_or_create(IDENTITY)
        state = session.scalar(
            select(SyncStreamState).where(
                SyncStreamState.provider_id == source.provider_id,
                SyncStreamState.acquisition_source_id == source.acquisition_source_id,
                SyncStreamState.stream_code == STEPS_REFRESH_STATE_CODE,
            )
        )
        if state is None:
            floor = (as_of - timedelta(days=1)).isoformat()
            state = repositories_for(session).sync.get_or_create_state(
                provider_id=source.provider_id,
                acquisition_source_id=source.acquisition_source_id,
                stream_code=STEPS_REFRESH_STATE_CODE,
                cursor=json.dumps(
                    {
                        "contract": STEPS_REFRESH_CONTRACT,
                        "binding": _BINDING,
                        "source_id": source.id,
                        "activation_floor": floor,
                        "next_date": floor,
                        "receipt": None,
                    },
                    sort_keys=True,
                ),
                diagnostic_status="acquisition_pending_coverage_unknown",
            )
        progress = _progress(session, state, source)
        progress.dates(as_of)
        session.commit()
        return progress


def advance_steps_refresh(
    session: Session,
    progress: StepsRefreshProgress,
    *,
    plan: StepsPlan,
    source,
    observation: GooglePayloadObservation,
    run: SyncRun,
) -> None:
    """Advance only in the same transaction as a successful immutable acquisition."""
    state = session.get(SyncStreamState, progress.state_id)
    if state is None or state.cursor != progress.cursor or source.id != progress.source_id:
        raise StepsRefreshStateError()
    current = _progress(session, state, source)
    previous = progress.next_date - timedelta(days=1) if progress.next_date > date.min else None
    if (
        current != progress
        or plan.day not in {progress.next_date, previous}
        or plan.day < progress.activation_floor
    ):
        raise StepsRefreshStateError()
    receipt = {"day": plan.day.isoformat(), "observation_id": observation.id, "run_id": run.id}
    _receipt(session, receipt, source=source, expected_day=plan.day)
    value = json.loads(state.cursor)
    value["next_date"] = (plan.day + timedelta(days=1)).isoformat()
    value["receipt"] = receipt
    state.cursor = json.dumps(value, sort_keys=True)
    state.diagnostic_status = "acquisition_succeeded_coverage_unknown"
    state.last_success_at = run.completed_at
    state.last_attempt_at = run.completed_at
    session.flush()
