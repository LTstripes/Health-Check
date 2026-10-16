"""#393 complete bounded mean of distinct eligible saved source-local RHR days.

The #376 latest reader remains separate. Reuse its source/group eligibility and
refresh rules, but never average repeated latest-reader results or a read prefix.
Saved-day coverage does not prove acquisition completeness or device wear.
"""

from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from healthcheck.db.models import GarminSource, GoogleSource
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.google.daily_vitals import GOOGLE_DAILY_VITALS_CONTRACT_VERSION
from healthcheck.metric_source_selection import SourceCandidate, select_metric_source
from healthcheck.saved_values import (
    MAX_SOURCE_IDENTITIES,
    SavedExclusion,
    SavedObservation,
    SavedValueQuery,
    _project_group,
    _record_scope,
    _refresh,
    _source_identity,
)
from healthcheck.web.read_snapshot import ensure_read_snapshot

CONTRACT_VERSION = "r393-saved-rhr-period-v1"
MAX_PERIOD_DAYS = 400
MAX_PERIOD_RECORDS = 4096
MAX_RECORDS_PER_DAY = 256


@dataclass(frozen=True)
class SavedRhrPeriodQuery:
    provider_code: str
    metric_code: str
    requested_start_date: date
    requested_end_date: date
    evaluated_at_utc: datetime
    evaluation_local_date: date
    source_id: str | None = None
    max_candidate_records: int = MAX_PERIOD_RECORDS
    max_records_per_day: int = MAX_RECORDS_PER_DAY

    def validate(self):
        # Identity/date/clock validation is the accepted #376 contract. Its
        # latest-reader work caps are deliberately not period-reader limits.
        SavedValueQuery(
            self.provider_code, self.metric_code, self.requested_start_date,
            self.requested_end_date, self.evaluated_at_utc, self.evaluation_local_date,
            source_id=self.source_id,
        ).validate()
        for value, maximum in ((self.max_candidate_records, MAX_PERIOD_RECORDS),
                               (self.max_records_per_day, MAX_RECORDS_PER_DAY)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError("invalid RHR period work cap")


def _encode(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_encode(item) for item in value]
    return value


def read_saved_rhr_period(session: Session, query: SavedRhrPeriodQuery) -> dict:
    """Read an unchanged inclusive window; no value unless its search is complete."""
    query.validate()
    days = (query.requested_end_date - query.requested_start_date).days + 1
    result = {
        "contract_version": CONTRACT_VERSION, "state": "unavailable", "reason": None,
        "query": _encode(asdict(query)), "requested_day_count": days,
        "source_identity": None, "available_sources": [], "observations": [],
        "exclusions": [], "eligible_day_count": None, "excluded_day_count": None,
        "mean_exact": None, "mean_display": None, "last_observation": None,
        "search": {"complete": False, "candidate_record_cap": query.max_candidate_records,
                   "per_day_record_cap": query.max_records_per_day,
                   "groups_examined": 0, "records_examined": 0},
        "refresh": {"scope": "not_resolved"},
        "acquisition_coverage_state": "unknown", "origin_state": "unknown",
        "snapshot_as_of": None,
    }
    if days > MAX_PERIOD_DAYS:
        return dict(result, state="period_too_long", reason="narrow_period_to_400_days")
    if session.new or session.dirty or session.deleted:
        ensure_read_snapshot(session)  # Pending writes are caller errors.
    try:
        ensure_read_snapshot(session)
        return _read_period(session, query, result)
    except SQLAlchemyError:
        # A failure after some groups must not publish their partial mean.
        return dict(result, reason="saved_value_read_failed")


def _read_period(session, query, result):
    source_model = GarminSource if query.provider_code == "garmin_connect" else GoogleSource
    if query.source_id is not None:
        source = session.get(source_model, query.source_id)
        if source is None or source.provider_code != query.provider_code:
            return dict(result, reason="source_not_found")
        sources = [source]
    else:
        sources = list(session.scalars(select(source_model).where(
            source_model.provider_code == query.provider_code,
        ).order_by(source_model.id).limit(MAX_SOURCE_IDENTITIES + 1)))
        if len(sources) > MAX_SOURCE_IDENTITIES:
            return dict(result, state="search_incomplete", reason="source_inventory_cap")
        result = dict(result, available_sources=[asdict(_source_identity(s)) for s in sources])
        if query.provider_code == "google_health":
            def read_candidate(source):
                packet = _read_period(session, replace(query, source_id=source.id), result)
                return SourceCandidate(
                    source, packet, packet["eligible_day_count"] or 0,
                    sum(item["candidate_count"] or 0 for item in packet["exclusions"]
                        if item["reason"].startswith("ambiguous_")),
                    packet["search"]["complete"], packet["reason"],
                )

            decision = select_metric_source(
                sources, read_candidate, source_cap=MAX_SOURCE_IDENTITIES,
            )
            selection = {
                "state": decision.state, "mode": "auto",
                "selected_source_id": decision.chosen.source.id if decision.chosen else None,
                "search_complete": decision.state != "search_incomplete",
            }
            if decision.chosen:
                return dict(decision.chosen.payload, query=result["query"],
                            available_sources=result["available_sources"],
                            source_selection=selection)
            if decision.state == "no_eligible_values" and len(decision.candidates) == 1:
                return dict(decision.candidates[0].payload, query=result["query"],
                            source_selection=selection)
            state = {"selection_required": "ambiguous", "source_missing": "unavailable",
                     "no_eligible_values": "no_eligible_in_period"}.get(
                         decision.state, decision.state)
            reason = {"selection_required": "source_selection_required",
                      "source_missing": "source_not_found"}.get(decision.state, decision.reason)
            return dict(result, state=state, reason=reason, source_selection=selection,
                        search=dict(result["search"], complete=selection["search_complete"]))
        if len(sources) != 1:
            return dict(result, state="ambiguous" if sources else "unavailable",
                        reason="source_selection_required" if sources else "source_not_found")
        source = sources[0]
    result = dict(result, source_identity=asdict(_source_identity(source)),
                  available_sources=[asdict(_source_identity(s)) for s in sources],
                  refresh=_encode(asdict(_refresh(session, source, query))))
    model, scope = _record_scope(query, source.id)
    current = (*scope, model.projection_status == "current")
    dated = (*current, model.source_local_date >= query.requested_start_date,
             model.source_local_date <= query.requested_end_date)
    if query.provider_code == "google_health":
        dated = (*dated, model.temporal_precision == "date")
    records = list(session.scalars(select(model).where(*dated).order_by(
        model.source_local_date.desc(),
    ).limit(query.max_candidate_records + 1)))
    search = dict(result["search"], records_examined=len(records))
    if len(records) > query.max_candidate_records:
        return dict(result, state="search_incomplete", reason="period_record_cap", search=search)
    groups = {}
    for record in records:
        groups.setdefault(record.source_local_date, []).append(record)
    for day, group in groups.items():
        if len(group) > query.max_records_per_day:
            return dict(result, state="search_incomplete", reason="candidate_group_cap",
                        search=dict(search, incomplete_group_date=day.isoformat()))
    observations, exclusions = [], []
    # Retain unknown-date presence without assigning it to the selected window.
    if session.scalar(select(model.id).where(
        *current, model.source_local_date.is_(None),
    ).limit(1)) is not None:
        exclusions.append(SavedExclusion(None, "ineligible_temporal_coordinate", None))
    for offset in range(result["requested_day_count"]):
        day = query.requested_start_date + timedelta(days=offset)
        group = groups.get(day, [])
        if not group:
            exclusions.append(SavedExclusion(day, "no_saved_observation", 0))
            continue
        record, metric, reason, states = _project_group(session, query, group)
        stamp = restore_stored_utc(record.source_timestamp_utc) if record else None
        if record is not None and (day > query.evaluation_local_date or (
            stamp is not None and stamp > query.evaluated_at_utc.astimezone(UTC)
        )):
            record, reason = None, "future_chronology"
        if record is None:
            exclusions.append(SavedExclusion(day, reason, len(group),
                                             tuple(row.id for row in group), states))
            continue
        observations.append(SavedObservation(
            float(metric.value_number), metric.unit, day, record.temporal_precision, stamp,
            (query.evaluation_local_date - day).days, metric.value_number == 0,
            record.id, metric.id, record.raw_payload_id, getattr(record, "observation_id", None),
            record.ingest_event_id, metric.field_path, record.record_status,
            record.normalization_contract_version,
            GOOGLE_DAILY_VITALS_CONTRACT_VERSION if query.provider_code == "google_health"
            else "r340-garmin-overview-rhr-v1",
        ))
    count = len(observations)
    exact = display = None
    if count:
        mean = sum((Fraction(str(point.value)) for point in observations), Fraction()) / count
        with localcontext() as context:
            context.prec = 40
            decimal = str(Decimal(mean.numerator) / Decimal(mean.denominator))
        exact = {"numerator": str(mean.numerator), "denominator": str(mean.denominator),
                 "decimal": decimal}
        # Exact ROUND_HALF_UP: round the final mean's magnitude once, then
        # restore its sign so half ties go away from zero on either side.
        magnitude = (2 * abs(mean.numerator) + mean.denominator) // (2 * mean.denominator)
        display = -magnitude if mean.numerator < 0 else magnitude
    return dict(result, state="observed" if count else "no_eligible_in_period",
                eligible_day_count=count, excluded_day_count=result["requested_day_count"] - count,
                mean_exact=exact, mean_display=display,
                observations=_encode([asdict(point) for point in observations]),
                exclusions=_encode([asdict(item) for item in exclusions]),
                last_observation=_encode(asdict(observations[-1])) if count else None,
                search=dict(search, complete=True, groups_examined=len(groups)))
