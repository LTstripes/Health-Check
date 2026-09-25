"""Loopback-only, read-only source freshness diagnostics."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

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
    if (set(not_requested) | set(disabled)) - SCOPE_BY_KEY.keys():
        raise HTTPException(status_code=422, detail="unsupported scope key")
    if set(not_requested) & set(disabled):
        raise HTTPException(status_code=422, detail="conflicting request facts")
    database = request.app.state.runtime_paths.database
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
                        disabled=scope.key in disabled,
                        weight_cadence_days=request.app.state.settings.weight_cadence_days,
                    ),
                    evaluated_at_utc=evaluated_at_utc,
                    evaluation_local_date=evaluation_local_date,
                )
                for scope in SCOPES
            ]
        return aggregate(results, evaluated_at_utc=evaluated_at_utc,
                         evaluation_local_date=evaluation_local_date,
                         policy_version=POLICY_VERSION)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database_unavailable") from exc
    finally:
        engine.dispose()
