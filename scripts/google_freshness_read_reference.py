"""Frozen Google query oracle from main 697e56fbebbd912f2c3a186bd9bca265884881b2.

Synthetic verification only; the pre-B2 aggregate body is copied verbatim.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from healthcheck.db.models import GoogleSource, GoogleSourceRecord
from healthcheck.db.repositories import restore_stored_utc


def _evidence_query(session: Session, model, *, joins: tuple, conditions: tuple,
                    source_identity=None, latest_slice: bool = True) -> tuple[
    datetime | None, date | None, str | None, bool, bool
]:
    """Resolve daily ambiguity within the latest persisted evidence slice."""
    timestamp_kind = model.temporal_precision.in_(("instant", "minute"))
    date_kind = model.temporal_precision == "date"
    invalid = (
        model.temporal_precision.in_(("local", "unknown"))
        | (timestamp_kind & model.source_timestamp_utc.is_(None))
        | (date_kind & model.source_local_date.is_(None))
    )

    def query(*columns, slice_conditions: tuple = ()):
        statement = select(*columns).select_from(model)
        for target, condition in joins:
            statement = statement.join(target, condition)
        return statement.where(*conditions, *slice_conditions)

    if not latest_slice:
        stamp, local_day, invalid_count, count = session.execute(query(
            func.max(case((timestamp_kind, model.source_timestamp_utc))),
            func.max(case((date_kind, model.source_local_date))),
            func.sum(case((invalid, 1), else_=0)),
            func.count(),
        )).one()
        chronology_issue = (
            "invalid_chronology" if invalid_count else
            "chronology_unresolved" if stamp is not None and local_day is not None else None
        )
        return restore_stored_utc(stamp), local_day, chronology_issue, True, count > 0

    latest_day, count = session.execute(query(
        func.max(model.source_local_date), func.count(),
    )).one()
    if not count:
        return None, None, None, True, False
    if latest_day is not None:
        selected = (model.source_local_date == latest_day,)
        undated_invalid = False
    else:
        # An undated invalid row has no defensible position in the chronology.
        latest_stamp, undated_invalid = session.execute(query(
            func.max(case((timestamp_kind, model.source_timestamp_utc))),
            func.sum(case((invalid, 1), else_=0)),
        )).one()
        if latest_stamp is None:
            return None, None, "invalid_chronology", True, True
        selected = (model.source_timestamp_utc == latest_stamp,)
    stamp, local_day, invalid_count, source_count = session.execute(query(
        func.max(case((timestamp_kind, model.source_timestamp_utc))),
        func.max(case((date_kind, model.source_local_date))),
        func.sum(case((invalid, 1), else_=0)),
        func.count(func.distinct(source_identity)) if source_identity is not None else func.count(),
        slice_conditions=selected,
    )).one()
    chronology_issue = (
        "invalid_chronology" if invalid_count or undated_invalid else
        "chronology_unresolved" if stamp is not None and local_day is not None else None
    )
    source_resolved = source_identity is None or source_count <= 1
    return restore_stored_utc(stamp), local_day, chronology_issue, source_resolved, True


def google_evidence_reference(session, provider_id, stream, mode, family):
    return _evidence_query(
        session, GoogleSourceRecord,
        joins=((GoogleSource, GoogleSource.id == GoogleSourceRecord.google_source_id),),
        conditions=(GoogleSource.provider_id == provider_id,
                    GoogleSourceRecord.stream_code == stream,
                    GoogleSourceRecord.query_mode == mode,
                    GoogleSourceRecord.data_source_family == family,
                    GoogleSourceRecord.projection_status == "current",
                    GoogleSourceRecord.record_status == "ok"),
        source_identity=GoogleSourceRecord.google_source_id,
    )
