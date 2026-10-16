"""Bounded #347 cycling-distance source discovery; selection belongs to callers."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.analytics import period_summary_read as bounded
from healthcheck.analytics.period_summary import (
    CONTRACT_VERSION as SUMMARY_VERSION,
)
from healthcheck.analytics.period_summary import (
    PeriodSummaryService,
    _identity,
    _window,
)
from healthcheck.db.models import GarminSource
from healthcheck.web.read_snapshot import ensure_read_snapshot

CONTRACT_VERSION = "cycling-distance-source-discovery-v1"
METRIC_CODE = "cycling_distance_meters"


class CyclingSourceDiscoveryService:
    """Enumerate exact sources and reuse accepted eligibility in one read snapshot.

    This session-backed backend does not open profiles, call providers, choose a
    source or change any existing consumer. A complete search is distinct from
    acquisition coverage. Incomplete discovery publishes no winning prefix.
    """

    def __init__(self, session: Session):
        self.session = session

    def discover(
        self,
        *,
        end_date: date | None = None,
        days: int | None = None,
        period_type: str | None = None,
        calendar_year: int | None = None,
    ) -> dict[str, Any]:
        # Reuse the accepted five explicit windows; never clip or use today's date.
        if end_date == date.max:
            raise ValueError("period end must allow a following coverage boundary")
        try:
            start, end, count, kind = _window(end_date, days, period_type, calendar_year)
        except OverflowError as exc:
            raise ValueError("period is outside supported calendar bounds") from exc
        ensure_read_snapshot(self.session)
        service = PeriodSummaryService(self.session)
        garmin = {
            "provider_code": "garmin_connect",
            "state": "source_missing",
            "search": {"complete": True, "reason": None},
            "source_count": 0,
            "eligible_source_count": 0,
            "ambiguous_source_count": 0,
            "reason_codes": ["source_missing"],
            "options": [],
        }
        with bounded.PeriodReadBudget(self.session) as budget:
            service._read = budget
            try:
                sources = budget.rows(
                    select(GarminSource).where(GarminSource.provider_code == "garmin_connect")
                    .order_by(GarminSource.id),
                    bounded.MAX_PERIOD_SOURCES, "source_inventory_limit_exceeded",
                )
                options = []
                for source in sources:
                    # Same bounded reducer hook as Activity evidence. Do not call
                    # build(), which also reads Sleep and unrelated providers.
                    cell = service._activities(source, start, end)[METRIC_CODE]
                    budget.check()
                    if cell["state"] == "search_incomplete":
                        raise bounded.IncompletePeriodRead(cell["search"]["reason"])
                    cell["search"] = {"complete": True, "reason": None}
                    ambiguous = sum(
                        item["count"] for item in cell["exclusions"]
                        if item["reason_code"] == "duplicate_current_identity"
                    )
                    eligible = cell["aggregation"]["eligible_count"] > 0
                    state = ("ambiguous_records" if ambiguous else
                             "eligible" if eligible else "no_eligible_values")
                    options.append({
                        "source_identity": _identity(source),
                        "eligibility": {
                            "state": state, "has_eligible_values": eligible,
                            "ambiguous_record_count": ambiguous,
                            "reason_codes": sorted({e["reason_code"] for e in cell["exclusions"]}
                                                   | ({"no_eligible_values"} if not eligible else
                                                      set())),
                        },
                        "summary": cell,
                    })
                budget.check()
                eligible_count = sum(o["eligibility"]["has_eligible_values"] for o in options)
                ambiguous_count = sum(o["eligibility"]["ambiguous_record_count"] > 0
                                      for o in options)
                state = (
                    "ambiguous_records" if ambiguous_count else
                    "multiple_eligible_sources" if eligible_count > 1 else
                    "unique_eligible_source" if eligible_count else
                    "no_eligible_values" if sources else "source_missing"
                )
                garmin.update(
                    state=state, source_count=len(sources), eligible_source_count=eligible_count,
                    ambiguous_source_count=ambiguous_count, options=options,
                    reason_codes=[state],
                )
            except bounded.IncompletePeriodRead as exc:
                garmin.update(
                    state="search_incomplete", search={"complete": False, "reason": str(exc)},
                    source_count=None, eligible_source_count=None, ambiguous_source_count=None,
                    reason_codes=["search_incomplete", str(exc)], options=[],
                )
            finally:
                service._read = None
        window = {"start_date": start.isoformat(), "end_date": end.isoformat(),
                  "inclusive_days": count}
        if kind is not None:
            window["period_type"] = kind
        return {
            "contract_version": CONTRACT_VERSION,
            "reader_contract": SUMMARY_VERSION,
            "evaluated_at": datetime.now(UTC).isoformat(),
            "requested_window": window,
            "metric": {
                "canonical_metric_code": METRIC_CODE, "source_metric_code": "distance_meters",
                "unit": "meters", "conversion": "identity_v1", "activity_types": ["cycling"],
                "date_basis": "persisted_source_local_date",
            },
            "selection_policy": "caller_owned_no_automatic_selection",
            "freshness": {"state": "unknown", "reason": "saved_period_not_live_freshness"},
            "read_limits": bounded.read_limits(),
            "providers": [garmin, {
                "provider_code": "google_health", "state": "not_collected",
                "search": {"complete": True, "reason": "typed_activity_stream_not_collected",
                           "scope": "persisted_stream_contract"},
                "source_count": None, "eligible_source_count": None,
                "ambiguous_source_count": None,
                "reason_codes": ["typed_activity_stream_not_collected"], "options": [],
            }],
        }
