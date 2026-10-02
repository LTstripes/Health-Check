"""Loopback-only, read-only source freshness diagnostics."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from healthcheck.collection_policy import (
    CollectionPolicyStatus,
    collection_policy_path,
    project_collection_policy_resolution,
    resolve_collection_policy,
)
from healthcheck.source_freshness import (
    POLICY_VERSION,
    SCOPE_BY_KEY,
    SCOPES,
    aggregate,
    evaluate_scope,
)
from healthcheck.source_freshness_read import read_facts

router = APIRouter()


@router.get("/api/source-freshness")
def source_freshness(
    request: Request,
    evaluated_at_utc: datetime,
    evaluation_local_date: date,
    not_requested: list[str] = Query(default=[]),
    disabled: list[str] = Query(default=[]),
) -> dict[str, object]:
    """Explicit clocks/configuration in, allowlisted chronology and reason codes out."""
    if evaluated_at_utc.tzinfo is None or evaluated_at_utc.utcoffset() is None:
        raise HTTPException(status_code=422, detail="evaluated_at_utc must be timezone-aware")
    runtime_paths = request.app.state.runtime_paths
    collection_policy = resolve_collection_policy(collection_policy_path(runtime_paths))
    persisted_disabled = (
        set(collection_policy.snapshot.disabled_streams)
        if collection_policy.status is CollectionPolicyStatus.VALID
        and collection_policy.snapshot is not None
        else set()
    )
    # Caller-local request facts may add diagnostic conditions, but a persisted
    # OFF always remains in force for this evaluation.
    disabled_scopes = set(disabled) | persisted_disabled
    if (set(not_requested) | disabled_scopes) - SCOPE_BY_KEY.keys():
        raise HTTPException(status_code=422, detail="unsupported scope key")
    if set(not_requested) & set(disabled):
        raise HTTPException(status_code=422, detail="conflicting request facts")
    database = runtime_paths.database
    if not database.is_file():
        raise HTTPException(status_code=503, detail="database_unavailable")

    def connect() -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only=ON")
        return connection

    engine = create_engine("sqlite://", creator=connect)
    try:
        with Session(engine, autoflush=False) as session:
            results = [
                evaluate_scope(
                    scope,
                    read_facts(
                        session, scope, evaluation_local_date=evaluation_local_date,
                        requested=scope.key not in not_requested,
                        disabled=scope.key in disabled_scopes,
                        weight_cadence_days=request.app.state.settings.weight_cadence_days,
                    ),
                    evaluated_at_utc=evaluated_at_utc,
                    evaluation_local_date=evaluation_local_date,
                )
                for scope in SCOPES
            ]
        result = aggregate(results, evaluated_at_utc=evaluated_at_utc,
                           evaluation_local_date=evaluation_local_date,
                           policy_version=POLICY_VERSION)
        result["collection_policy"] = project_collection_policy_resolution(collection_policy)
        return result
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database_unavailable") from exc
    finally:
        engine.dispose()
