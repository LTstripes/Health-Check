"""Read-only maxima of proven typed saved Body Battery samples (#394).

The sync adapter's scalar alias is not a sample. Legacy scalar eligibility is
unknown; no raw reparse, ingestion, source-date conversion or provider access.
Every mean requires a complete bounded read and weights saved days equally.
"""

import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from fractions import Fraction
from math import isfinite

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from healthcheck.db.models import GarminRecordMetric, GarminSource, GarminSourceRecord
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.saved_values import _source_identity
from healthcheck.web.read_snapshot import ensure_read_snapshot

CONTRACT_VERSION = "r394-saved-body-battery-maxima-v1"
# Work limits bound samples, not calendar history. No truncated mean is exposed.
MAX_PERIOD_RECORDS = 100_000
MAX_RECORDS_PER_DAY = 10_000
_SAMPLE_PATH = re.compile(r"payload\.bodyBatteryValuesArray\[[0-9]+\]\Z")


@dataclass(frozen=True)
class BodyBatteryQuery:
    start_date: date
    end_date: date
    source_id: str | None
    evaluated_at_utc: datetime
    evaluation_local_date: date
    max_candidate_records: int = MAX_PERIOD_RECORDS
    max_records_per_day: int = MAX_RECORDS_PER_DAY

    def validate(self):
        for day in (self.start_date, self.end_date, self.evaluation_local_date):
            if type(day) is not date:
                raise ValueError("Body Battery dates must be civil dates")
        if self.end_date < self.start_date:
            raise ValueError("Body Battery period is reversed")
        if not isinstance(self.evaluated_at_utc, datetime) or (
            self.evaluated_at_utc.tzinfo is None or self.evaluated_at_utc.utcoffset() is None
        ):
            raise ValueError("Body Battery evaluation must be timezone-aware")
        if self.source_id is not None and not self.source_id.strip():
            raise ValueError("Body Battery source ID must not be blank")
        for cap, maximum in ((self.max_candidate_records, MAX_PERIOD_RECORDS),
                             (self.max_records_per_day, MAX_RECORDS_PER_DAY)):
            if type(cap) is not int or not 1 <= cap <= maximum:
                raise ValueError("invalid Body Battery work cap")


def read_body_battery_period(session: Session, query: BodyBatteryQuery) -> dict:
    """Inclusive saved source-local dates; incomplete search never yields a mean."""
    query.validate()
    result = {
        "contract_version": CONTRACT_VERSION, "state": "unavailable", "reason": None,
        "start_date": query.start_date.isoformat(), "end_date": query.end_date.isoformat(),
        "requested_day_count": (query.end_date - query.start_date).days + 1,
        "source_identity": None, "daily_maxima": [], "exclusions": [],
        "eligible_day_count": None, "missing_day_count": None,
        "mean_exact": None, "mean_value": None, "latest_maximum": None,
        "acquisition_coverage_state": "unknown", "legacy_eligibility": "unknown",
        "search": {"complete": False, "records_examined": 0, "groups_examined": 0,
                   "candidate_record_cap": query.max_candidate_records,
                   "per_day_record_cap": query.max_records_per_day},
    }
    if session.new or session.dirty or session.deleted:
        ensure_read_snapshot(session)
    try:
        ensure_read_snapshot(session)
        return _read_period(session, query, result)
    except SQLAlchemyError:
        # Discard all intermediate observations if any read fails.
        return dict(result, reason="saved_value_read_failed")


def _read_period(session, query, result):
    source = session.get(GarminSource, query.source_id) if query.source_id else None
    if source is None or source.provider_code != "garmin_connect":
        return dict(result, reason="source_not_selected" if query.source_id is None
                    else "source_not_found")
    result = dict(result, source_identity=asdict(_source_identity(source)))
    record, metric = GarminSourceRecord, GarminRecordMetric
    scope = (
        record.garmin_source_id == source.id, record.projection_status == "current",
        or_(record.surface_code == "body_battery", metric.id.is_not(None)),
    )
    statement = select(record, metric).outerjoin(metric, and_(
        metric.record_id == record.id, metric.metric_code == "body_battery",
    ))
    rows = session.execute(statement.where(
        *scope, record.source_local_date >= query.start_date,
        record.source_local_date <= query.end_date,
    ).order_by(record.source_local_date, record.id).limit(query.max_candidate_records + 1)).all()
    search = dict(result["search"], records_examined=len(rows))
    if len(rows) > query.max_candidate_records:
        return dict(result, state="search_incomplete", reason="period_record_cap", search=search)
    groups = {}
    for row in rows:
        groups.setdefault(row[0].source_local_date, []).append(row)
    for day, group in groups.items():
        if len(group) > query.max_records_per_day:
            return dict(result, state="search_incomplete", reason="candidate_group_cap",
                        search=dict(search, incomplete_group_date=day.isoformat()))
    exclusions = []
    if session.execute(statement.where(
        *scope, record.source_local_date.is_(None),
    ).limit(1)).first() is not None:
        exclusions.append({"source_local_date": None, "reason": "unknown_date"})
    maxima = []
    for day, group in groups.items():
        point, excluded = _project_day(day, group, query)
        exclusions.extend(excluded)
        if point is not None:
            maxima.append(point)
    count = len(maxima)
    exact = mean_value = None
    if count:
        mean = sum((Fraction(str(point["value"])) for point in maxima), Fraction()) / count
        with localcontext() as context:
            context.prec = 40
            mean_value = Decimal(mean.numerator) / Decimal(mean.denominator)
        exact = {"numerator": str(mean.numerator), "denominator": str(mean.denominator),
                 "decimal": str(mean_value)}
    return dict(result, state="observed" if count else "no_eligible_in_period",
                eligible_day_count=count, missing_day_count=result["requested_day_count"] - count,
                daily_maxima=maxima, exclusions=exclusions, mean_exact=exact,
                mean_value=mean_value, latest_maximum=maxima[-1] if count else None,
                search=dict(search, complete=True, groups_examined=len(groups)))


def _project_day(day, group, query):
    samples, exclusions = [], []
    for record, metric in group:
        reason = None
        if (record.stream_code != "intraday" or record.surface_code != "body_battery"
                or not _SAMPLE_PATH.fullmatch(record.source_path or "")
                or metric is not None and metric.field_path != "payload.bodyBatteryValuesArray"):
            reason = "legacy_or_alias_eligibility_unknown"
        elif metric is None:
            reason = "metric_row_missing"
        elif metric.capability_code != "body_battery":
            reason = "metric_identity_mismatch"
        if reason:
            exclusions.append({"source_local_date": day.isoformat(), "reason": reason,
                               "record_id": record.id})
        else:
            samples.append((record, metric))
    # Validate the entire timestamp group before filtering bad values: a valid
    # number cannot silently win against a missing/conflicting current sample.
    coordinates = []
    for record, _ in samples:
        stamp = restore_stored_utc(record.source_timestamp_utc)
        if record.temporal_precision == "instant" and stamp is not None:
            coordinate = ("instant", stamp)
        elif record.temporal_precision == "local" and record.local_wall_time:
            try:
                wall = datetime.fromisoformat(record.local_wall_time)
                coordinate = ("local", wall) if wall.tzinfo is None else None
            except ValueError:
                coordinate = None
        else:
            coordinate = None
        coordinates.append(coordinate)
    if len(samples) > 1 and (None in coordinates or len(set(coordinates)) != len(coordinates)
                            or len({item[0] for item in coordinates}) != 1):
        return None, exclusions + [{"source_local_date": day.isoformat(),
                                    "reason": "ambiguous_sample_coordinates"}]
    usable = []
    for (record, metric), coordinate in zip(samples, coordinates, strict=True):
        stamp = restore_stored_utc(record.source_timestamp_utc)
        number = metric.value_number
        reason = (
            "future_chronology" if day > query.evaluation_local_date or (
                stamp is not None and stamp > query.evaluated_at_utc.astimezone(UTC)
            ) else "unknown_temporal_precision" if record.temporal_precision == "unknown"
            or record.temporal_precision != "date" and coordinate is None
            else f"metric_{metric.state}" if metric.state != "value"
            else "metric_unit_mismatch" if metric.unit != "points"
            else "record_invalid" if record.record_status not in {"ok", "partial"}
            else "metric_value_invalid" if isinstance(number, bool)
            or not isinstance(number, (int, float)) or not isfinite(number)
            or not 0 <= number <= 100 else None
        )
        if reason:
            exclusions.append({"source_local_date": day.isoformat(), "reason": reason,
                               "record_id": record.id})
        else:
            usable.append((record, metric))
    if not usable:
        return None, exclusions
    maximum = max(metric.value_number for _, metric in usable)
    winners = [(record, metric) for record, metric in usable if metric.value_number == maximum]
    return {"source_local_date": day.isoformat(), "value": maximum,
            "eligible_sample_count": len(usable), "is_zero": maximum == 0,
            "evidence": [{"record_id": record.id, "metric_row_id": metric.id,
                          "raw_payload_id": record.raw_payload_id,
                          "field_path": metric.field_path, "source_path": record.source_path,
                          "source_timestamp_utc": restore_stored_utc(record.source_timestamp_utc)
                          .isoformat() if record.source_timestamp_utc else None,
                          "record_status": record.record_status,
                          "normalization_version": record.normalization_contract_version,
                          "reconciliation_version": record.reconciliation_contract_version}
                         for record, metric in winners]}, exclusions
