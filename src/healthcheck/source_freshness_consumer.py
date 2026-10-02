"""Privacy-safe projection shared by owner-facing freshness consumers."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from healthcheck.collection_policy import (
    CollectionPolicyResolution,
    CollectionPolicyStatus,
    project_collection_policy_resolution,
)
from healthcheck.source_freshness import POLICY_VERSION, SCOPES, aggregate, evaluate_scope
from healthcheck.source_freshness_read import read_facts


def _absent_collection_policy() -> CollectionPolicyResolution:
    return CollectionPolicyResolution(status=CollectionPolicyStatus.ABSENT)


def evaluate_persisted_freshness(
    session: Session,
    *,
    evaluated_at_utc: datetime,
    evaluation_local_date: date,
    weight_cadence_days: int | None = None,
    collection_policy: CollectionPolicyResolution | None = None,
) -> dict[str, object]:
    """Evaluate the accepted core against persisted facts and explicit clocks.

    Persisted chronology is always read first; explicit disabled/unrequested
    disposition is applied afterwards and never erases the observed history.
    """

    resolution = (
        collection_policy if collection_policy is not None else _absent_collection_policy()
    )
    disabled_scopes = (
        resolution.snapshot.disabled_streams
        if resolution.status is CollectionPolicyStatus.VALID
        and resolution.snapshot is not None
        else ()
    )
    with session.no_autoflush:
        results = []
        for scope in SCOPES:
            facts = read_facts(
                session,
                scope,
                evaluation_local_date=evaluation_local_date,
                weight_cadence_days=weight_cadence_days,
            )
            if scope.key in disabled_scopes:
                facts = replace(facts, disabled=True)
            results.append(
                evaluate_scope(
                    scope,
                    facts,
                    evaluated_at_utc=evaluated_at_utc,
                    evaluation_local_date=evaluation_local_date,
                )
            )
    return aggregate(
        results,
        evaluated_at_utc=evaluated_at_utc,
        evaluation_local_date=evaluation_local_date,
        policy_version=POLICY_VERSION,
    )


def _public_item(item: Mapping[str, Any]) -> dict[str, str]:
    values = {
        key: item.get(key)
        for key in ("scope_key", "state", "reason_code")
    }
    if not all(isinstance(value, str) for value in values.values()):
        raise ValueError("freshness core returned an invalid consumer item")
    return {
        "scope_key": values["scope_key"],
        "state": values["state"],
        "reason_code": values["reason_code"],
    }


def project_consumer_freshness(
    aggregate_result: Mapping[str, Any],
    *,
    collection_policy: CollectionPolicyResolution | None = None,
) -> dict[str, Any]:
    """Keep only owner-safe state and stable reason fields from the core result."""

    policy_version = aggregate_result.get("policy_version")
    owner = aggregate_result.get("owner")
    providers = aggregate_result.get("providers")
    if (
        not isinstance(policy_version, str)
        or not isinstance(owner, Mapping)
        or not isinstance(providers, Mapping)
    ):
        raise ValueError("freshness core returned an invalid aggregate")
    owner_state = owner.get("state")
    actionable = owner.get("actionable_reasons")
    if not isinstance(owner_state, str) or not isinstance(actionable, list):
        raise ValueError("freshness core returned an invalid owner summary")

    provider_states: dict[str, dict[str, str]] = {}
    not_requested_required: list[dict[str, str]] = []
    optional_details: list[dict[str, str]] = []
    for provider_name in ("garmin", "google"):
        provider = providers.get(provider_name)
        if not isinstance(provider, Mapping) or not isinstance(provider.get("state"), str):
            raise ValueError("freshness core returned an invalid provider summary")
        provider_states[provider_name] = {"state": provider["state"]}
        required = provider.get("required")
        if not isinstance(required, list) or any(
            not isinstance(item, Mapping) for item in required
        ):
            raise ValueError("freshness core returned invalid required details")
        not_requested_required.extend(
            _public_item(item) for item in required if item.get("state") == "not_requested"
        )
        optional = provider.get("optional")
        if not isinstance(optional, list) or any(
            not isinstance(item, Mapping) for item in optional
        ):
            raise ValueError("freshness core returned invalid optional details")
        optional_details.extend(_public_item(item) for item in optional)

    if any(not isinstance(item, Mapping) for item in actionable):
        raise ValueError("freshness core returned invalid actionable details")

    return {
        "policy_version": policy_version,
        "collection_policy": project_collection_policy_resolution(
            collection_policy if collection_policy is not None else _absent_collection_policy()
        ),
        "owner": {
            "state": owner_state,
            "actionable_items": [_public_item(item) for item in actionable],
        },
        "providers": provider_states,
        "not_requested_required": sorted(
            not_requested_required, key=lambda item: item["scope_key"]
        ),
        "optional_details": sorted(optional_details, key=lambda item: item["scope_key"]),
    }


def read_consumer_freshness_projection(
    session: Session,
    *,
    evaluated_at_utc: datetime,
    evaluation_local_date: date,
    weight_cadence_days: int | None = None,
    collection_policy: CollectionPolicyResolution | None = None,
) -> dict[str, Any]:
    return project_consumer_freshness(
        evaluate_persisted_freshness(
            session,
            evaluated_at_utc=evaluated_at_utc,
            evaluation_local_date=evaluation_local_date,
            weight_cadence_days=weight_cadence_days,
            collection_policy=collection_policy,
        ),
        collection_policy=collection_policy,
    )


def _readonly_engine(database_path: Path) -> Engine:
    if not database_path.is_file():
        raise FileNotFoundError("database_unavailable")

    def connect() -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"file:{database_path.as_posix()}?mode=ro", uri=True
        )
        connection.execute("PRAGMA query_only=ON")
        return connection

    return create_engine("sqlite://", creator=connect)


def read_consumer_freshness_projection_from_database(
    database_path: Path,
    *,
    evaluated_at_utc: datetime,
    evaluation_local_date: date,
    weight_cadence_days: int | None = None,
    collection_policy: CollectionPolicyResolution | None = None,
) -> dict[str, Any]:
    """Read and project persisted freshness through a SQLite read-only connection."""

    engine = _readonly_engine(database_path)
    try:
        with Session(engine, autoflush=False) as session:
            return read_consumer_freshness_projection(
                session,
                evaluated_at_utc=evaluated_at_utc,
                evaluation_local_date=evaluation_local_date,
                weight_cadence_days=weight_cadence_days,
                collection_policy=collection_policy,
            )
    finally:
        engine.dispose()


__all__ = [
    "evaluate_persisted_freshness",
    "project_consumer_freshness",
    "read_consumer_freshness_projection",
    "read_consumer_freshness_projection_from_database",
]
