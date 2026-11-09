"""Trip/event passport (#463): a thin view over the accepted combined period export.

The passport never reads storage directly. It asks the existing combined
evidence reader (#341/#451) for its bounded 7- or 30-day window that ends on
the passport end date, then keeps only the passport dates. Every fact is copied
from those packets; nothing is pooled across sources, re-bucketed by UTC or
filled in. Unknown time zones stay unknown.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path
from typing import Any

from healthcheck.chat_evidence import MAX_OUTPUT_BYTES, MAX_ROWS, EvidenceError
from healthcheck.combined_evidence import (
    CombinedEvidenceRequest,
    encode_combined_evidence,
    read_combined_evidence,
)

PASSPORT_VERSION = "trip-passport-v1"
# The combined export accepts exactly 7 or 30 calendar days (sleep/activity
# readers). A longer trip is refused instead of stitching windows (#380).
EXPORT_WINDOWS = (7, 30)
MAX_PASSPORT_DAYS = max(EXPORT_WINDOWS)
MAX_TITLE_LENGTH = 120
MAX_PLACE_LENGTH = 120
CONTEXT_ROW_LIMIT = MAX_ROWS
# The composed download has the same cap as the source export; no larger prefix wins.
MAX_BUNDLE_BYTES = MAX_OUTPUT_BYTES

STEPS_COUNTED_STATES = ("completed", "zero")
STEPS_STATES = ("completed", "zero", "incomplete", "conflict", "missing", "future")


class PassportError(ValueError):
    """Stable, privacy-safe refusal code (no values, no text)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PassportRequest:
    start_date: date
    end_date: date
    title: str
    garmin_source_id: str
    place: str = ""
    compare_previous: bool = False
    context_event_id: str | None = None
    context_revision_id: str | None = None

    @property
    def day_count(self) -> int:
        return (self.end_date - self.start_date).days + 1

    @property
    def export_days(self) -> int:
        return next(days for days in EXPORT_WINDOWS if self.day_count <= days)

    @property
    def previous_start(self) -> date:
        return self.start_date - timedelta(days=self.day_count)

    @property
    def previous_end(self) -> date:
        return self.start_date - timedelta(days=1)

    def dates(self) -> list[date]:
        return [self.start_date + timedelta(days=i) for i in range(self.day_count)]

    def validate(self) -> None:
        if type(self.start_date) is not date or type(self.end_date) is not date:
            raise PassportError("invalid_calendar_date")
        if self.start_date > self.end_date:
            raise PassportError("start_after_end")
        if self.day_count > MAX_PASSPORT_DAYS:
            raise PassportError("period_exceeds_export_cap")
        if (self.start_date.toordinal() <= 2 * MAX_PASSPORT_DAYS
                or self.end_date >= date(9999, 1, 1)):
            raise PassportError("range_out_of_bounds")
        if type(self.title) is not str or not 1 <= len(self.title.strip()) <= MAX_TITLE_LENGTH:
            raise PassportError("title_required")
        if type(self.place) is not str or len(self.place.strip()) > MAX_PLACE_LENGTH:
            raise PassportError("place_too_long")
        if (type(self.garmin_source_id) is not str or not self.garmin_source_id.strip()
                or len(self.garmin_source_id) > 36):
            raise PassportError("garmin_source_required")
        if type(self.compare_previous) is not bool:
            raise PassportError("invalid_comparison_selection")


def _export_request(request: PassportRequest, end_date: date, *, context: bool):
    source = request.garmin_source_id
    # Same selection as the Owner analysis export, completed Steps view.
    return CombinedEvidenceRequest(
        end_date=end_date, days=request.export_days,
        activity_garmin_source_id=source, sleep_garmin_source_id=source,
        sleep_google_auto_select=True, projection="compact", include_context=context,
        context_limit=CONTEXT_ROW_LIMIT,
        stress_garmin_source_id=source, body_battery_garmin_source_id=source,
        hrv_garmin_source_id=source, rhr_garmin_source_id=source, rhr_google_auto_select=True,
        steps_garmin_source_id=source, include_weight=False, steps_view="completed",
    )


def export_requests(request: PassportRequest) -> dict[str, CombinedEvidenceRequest]:
    """The exact existing-export reads a passport is built from."""
    request.validate()
    source = request.garmin_source_id
    result = {
        "current": _export_request(request, request.end_date, context=True),
        # Observed Steps distinguish an incomplete day from a gap; no Context
        # here, so the current packet stays the only Context source.
        "observed_steps": CombinedEvidenceRequest(
            end_date=request.end_date, days=request.export_days,
            activity_garmin_source_id=source, sleep_garmin_source_id=source,
            projection="compact", include_context=False,
            steps_garmin_source_id=source, steps_view="observed",
        ),
    }
    if request.compare_previous:
        result["previous"] = _export_request(request, request.previous_end, context=False)
    return result


def read_passport_exports(
    *, profile: Path, profile_kind: str, request: PassportRequest,
    evaluated_at_utc: datetime, evaluation_local_date: date,
    reader=None,
) -> dict[str, dict[str, Any]]:
    """Run the accepted reader once per role; any reader refusal refuses the passport.

    Packets are returned exactly as their downloadable JSON decodes, so the
    passport is built from the same representation the export publishes.
    """
    reader = reader or read_combined_evidence
    return {
        role: json.loads(encode_combined_evidence(reader(
            profile=profile, profile_kind=profile_kind, request=export,
            evaluated_at_utc=evaluated_at_utc, evaluation_local_date=evaluation_local_date)))
        for role, export in export_requests(request).items()
    }


# ---------------------------------------------------------------------------
# Pure assembly from packets
# ---------------------------------------------------------------------------


def _in(day: str | None, start: str, end: str) -> bool:
    return isinstance(day, str) and start <= day <= end


def _exact_mean(total: int, count: int) -> str:
    with localcontext() as context:
        context.prec = max(28, total.bit_length() * 30103 // 100000 + 16)
        context.rounding = ROUND_HALF_EVEN
        return str(Decimal(total) / count)


def _steps_day(day: str, completed: dict | None, observed: dict | None, today: str) -> dict:
    observed_value = (observed["value"] if observed and observed.get("state") == "value"
                      and type(observed.get("value")) is int else None)
    base = {"date": day, "unit": "steps"}
    if completed is not None:
        value = completed.get("value")
        if completed.get("state") == "value" and type(value) is int and value >= 0:
            return {**base, "state": "zero" if value == 0 else "completed", "value": value,
                    "basis": "completed_day", "reason": None,
                    "completion_boundary_utc": completed.get("completion_boundary_utc")}
        if completed.get("state") == "ambiguous":
            return {**base, "state": "conflict", "value": None, "basis": "completed_day",
                    "reason": completed.get("reason")}
    if observed is not None and observed.get("state") == "ambiguous":
        return {**base, "state": "conflict", "value": None, "basis": "observed",
                "reason": observed.get("reason")}
    if observed_value is not None:
        # A saved observation that is not a proven completed day: shown, never summed.
        reason = (completed or {}).get("reason") or "completion_boundary_not_reached"
        return {**base, "state": "incomplete", "value": observed_value,
                "basis": "observed_not_completed", "reason": reason}
    if day > today:
        return {**base, "state": "future", "value": None, "basis": None,
                "reason": "date_after_evaluation_date"}
    reason = ((completed or {}).get("reason") or (observed or {}).get("reason")
              or "no_saved_value")
    return {**base, "state": "missing", "value": None, "basis": None, "reason": reason}


def _steps(current: dict, observed: dict, days: list[str], today: str) -> dict:
    section = current["sections"].get("steps")
    observed_section = observed["sections"].get("steps")
    if section is None or observed_section is None:
        raise PassportError("steps_section_unavailable")
    completed_cells = {cell["calendar_date"]: cell for cell in section["cells"]}
    observed_cells = {cell["calendar_date"]: cell for cell in observed_section["cells"]}
    rows = [_steps_day(day, completed_cells.get(day), observed_cells.get(day), today)
            for day in days]
    counted = [row["value"] for row in rows if row["state"] in STEPS_COUNTED_STATES]
    total = sum(counted) if counted else None
    return {
        "source_id": section.get("source_id"),
        "meaning": section.get("meaning"),
        "unit": section.get("unit"),
        "display_zone": section.get("display_zone"),
        "views": {"completed": section.get("contract_version"),
                  "observed": observed_section.get("contract_version")},
        "days": rows,
        "state_counts": {state: sum(row["state"] == state for row in rows)
                         for state in STEPS_STATES},
        "counted_day_count": len(counted),
        "total": total,
        "mean_exact": _exact_mean(total, len(counted)) if counted else None,
        "rule": "completed_day_values_only_incomplete_missing_future_excluded",
        "source_pooling": "not_performed",
        "distance": "not_computed",
        "warnings": list(section.get("warnings", ())),
    }


def _sleep(current: dict, start: str, end: str) -> dict:
    providers = {}
    for name, provider in sorted(current["sections"]["sleep"]["providers"].items()):
        source_range = provider.get("source_range")
        if source_range is None:
            providers[name] = {"state": "unavailable", "source_id": provider.get(
                "selected_source_id"), "nights": []}
            continue
        nights_detail = {night["wake_date"]: night for night in source_range.get("days", ())}
        nights = []
        for series in source_range.get("series", ()):
            for point in series.get("points", ()):
                if not _in(point.get("wake_date"), start, end):
                    continue
                night = nights_detail.get(point["wake_date"], {})
                start_at = end_at = None
                for source in night.get("sources", ()):
                    for session in source.get("sessions", ()):
                        if session.get("metrics", {}).get("sleep_duration_asleep_seconds", {}).get(
                                "record_id") != point.get("record_id"):
                            continue
                        metrics = session["metrics"]
                        start_at = (metrics.get("sleep_start_at") or {}).get("value")
                        end_at = (metrics.get("sleep_end_at") or {}).get("value")
                # The accepted resolved series is authoritative; a role-uncertain
                # point is a conflict, never a silently chosen value.
                uncertain = bool(point.get("role_uncertain"))
                value = point.get("value")
                nights.append({
                    "wake_date": point["wake_date"],
                    "state": "conflict" if uncertain else point.get("state"),
                    "value": None if uncertain else value,
                    "unit": point.get("unit"),
                    "partial": point.get("partial"),
                    "reason": "role_uncertain" if uncertain else point.get("reason"),
                    "excluded_record_ids": [item.get("record_id")
                                            for item in point.get("exclusions", ())],
                    "record_id": point.get("record_id"),
                    "sleep_start_utc": start_at, "sleep_end_utc": end_at,
                })
        providers[name] = {
            "state": source_range.get("state"),
            "source_id": provider.get("selected_source_id"),
            "provider_code": provider.get("provider_code"),
            "selection": provider.get("selection"),
            "metric": "sleep_duration_asleep_seconds",
            "date_basis": "source_local_wake_date",
            "nights": sorted(nights, key=lambda row: row["wake_date"]),
        }
    return {"providers": providers, "source_pooling": "not_performed",
            "contract": current["sections"]["sleep"].get("reader_contract")}


def _local_start(start: dict) -> tuple[str | None, str]:
    if start.get("local_wall_time"):
        return start["local_wall_time"], "stored_local_wall_time"
    if start.get("source_local_timestamp"):
        return start["source_local_timestamp"], "stored_source_local_timestamp"
    utc_text = start.get("measured_at_utc")
    offset = start.get("source_utc_offset_minutes")
    if utc_text and type(offset) is int:
        instant = datetime.fromisoformat(utc_text.replace("Z", "+00:00"))
        local = instant.astimezone(UTC) + timedelta(minutes=offset)
        return local.replace(tzinfo=None).isoformat(), "utc_plus_stored_offset"
    if utc_text:
        return None, "utc_only_zone_unknown"
    return None, "start_unavailable"


def _workouts(current: dict, start: str, end: str) -> dict:
    temporal = current["sections"]["activity"].get("temporal_evidence") or {}
    rows = []
    for session in temporal.get("sessions") or ():
        day = session.get("source_local_date")
        if not _in(day, start, end):
            continue
        begin = session.get("start") or {}
        local, basis = _local_start(begin)
        rows.append({
            "date": day,
            "activity_type": session.get("activity_type"),
            "record_status": session.get("record_status"),
            "record_id": session.get("record_id"),
            "start_utc": begin.get("measured_at_utc"),
            "start_local": local,
            "start_local_basis": basis,
            "timezone": begin.get("source_timezone"),
            "utc_offset_minutes": begin.get("source_utc_offset_minutes"),
            "start_precision": begin.get("precision"),
            "start_state": begin.get("state"),
            "start_reason": begin.get("reason"),
        })
    rows.sort(key=lambda row: (row["date"], row["start_utc"] or "", row["record_id"] or ""))
    # The reader reports exclusion counts over its entire 7/30-day window,
    # without dates. Keep that scope explicit rather than attributing them to the trip.
    retired = temporal.get("retired_exclusions")
    return {
        "state": temporal.get("state", "unavailable"),
        "reason": temporal.get("reason"),
        "date_basis": temporal.get("date_basis"),
        "sessions": rows,
        "session_count": len(rows) if temporal.get("state") == "complete" else None,
        "retired_exclusions": retired,
        "exclusions_window": temporal.get("window"),
        "duration_distance_calories": "not_in_passport_view",
    }


def _recovery(current: dict, start: str, end: str) -> dict:
    sections = current["sections"]
    result: dict[str, Any] = {}
    rhr = sections.get("rhr")
    if rhr is not None:
        result["rhr"] = {name: {
            "state": provider.get("state"), "unit": provider.get("unit"),
            "reason": provider.get("reason"), "search": provider.get("search"),
            "exclusions": provider.get("exclusions"),
            "meaning": provider.get("meaning"), "metric_code": provider.get("metric_code"),
            "source_id": (provider.get("source_identity") or {}).get("source_id"),
            "values": [{"date": row["source_local_date"], "value": row["value"],
                        "record_id": row.get("record_id")}
                       for row in provider.get("observations", ())
                       if _in(row.get("source_local_date"), start, end)],
        } for name, provider in sorted(rhr["providers"].items())}
    hrv = sections.get("hrv")
    if hrv is not None:
        result["hrv"] = {name: {
            "state": provider.get("state"), "reason": provider.get("reason"),
            "unit": provider.get("unit"), "meaning": provider.get("meaning"),
            "metric_code": provider.get("metric_code"),
            "source_id": (provider.get("source_identity") or {}).get("source_id"),
            "values": [{"date": row["source_local_date"],
                        "value": row["value"] if row.get("eligible") else None,
                        "state": row.get("state"), "eligible": row.get("eligible"),
                        "reason": row.get("reason") or row.get("exclusion_basis"),
                        "record_id": row.get("record_id")}
                       for row in provider.get("points", ())
                       if _in(row.get("source_local_date"), start, end)],
        } for name, provider in sorted(hrv["providers"].items())}
    battery = sections.get("body_battery")
    if battery is not None:
        result["body_battery"] = {"garmin": {
            "state": battery.get("state"), "unit": battery.get("unit"),
            "reason": battery.get("reason"), "search": battery.get("search"),
            "exclusions": battery.get("exclusions"),
            "meaning": battery.get("meaning"), "metric_code": battery.get("metric_code"),
            "source_id": (battery.get("source_identity") or {}).get("source_id"),
            "values": [{"date": row["source_local_date"], "value": row["value"]}
                       for row in battery.get("daily_maxima", ())
                       if _in(row.get("source_local_date"), start, end)],
        }}
    return result


def _context(current: dict, start: str, end: str) -> dict:
    section = current["sections"].get("context")
    if section is None:
        return {"state": "not_requested", "rows": []}
    rows = []
    for row in section.get("rows", ()):
        temporal = row.get("temporal") or {}
        first = temporal.get("start_local_date")
        last = temporal.get("end_local_date") or first
        if not (isinstance(first, str) and first <= end and last >= start):
            continue
        rows.append({
            "event_id": row.get("event_id"), "revision_id": row.get("revision_id"),
            "revision_number": row.get("revision_number"),
            "original_text": row.get("original_text"), "temporal": temporal,
            "tags": [tag.get("name") for tag in row.get("tags", ())],
        })
    rows.sort(key=lambda row: (row["temporal"].get("start_local_date") or "",
                               row["temporal"].get("start_at_utc") or "", row["event_id"] or ""))
    return {
        "state": "truncated" if section.get("truncated") or section.get("has_more") else "complete",
        "row_limit": section.get("limit"),
        "trust": section.get("trust"),
        "absence_semantics": section.get("absence_semantics"),
        "rows": rows,
    }


def _offset_label(minutes: int | None) -> str | None:
    if type(minutes) is not int:
        return None
    sign = "+" if minutes >= 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{rest:02d}"


def _zones(context: dict, workouts: dict, days: list[str]) -> dict:
    """Only stored zones/offsets; a day without one stays unknown (never carried)."""
    facts = []
    for row in context["rows"]:
        temporal = row["temporal"]
        for edge in ("start", "end"):
            day = temporal.get(f"{edge}_local_date")
            zone = temporal.get(f"{edge}_timezone")
            offset = temporal.get(f"{edge}_utc_offset_minutes")
            if day in days and (zone or type(offset) is int):
                facts.append({"date": day, "timezone": zone, "utc_offset_minutes": offset,
                              "origin": "context", "reference": row["event_id"]})
    for session in workouts["sessions"]:
        if session["timezone"] or type(session["utc_offset_minutes"]) is int:
            facts.append({"date": session["date"], "timezone": session["timezone"],
                          "utc_offset_minutes": session["utc_offset_minutes"],
                          "origin": "workout", "reference": session["record_id"]})
    facts.sort(key=lambda fact: (fact["date"], fact["origin"], fact["reference"] or ""))
    per_day = []
    changes = []
    previous = None
    for day in days:
        labels = sorted({(fact["timezone"] or "", fact["utc_offset_minutes"]
                          if type(fact["utc_offset_minutes"]) is int else 10**6)
                         for fact in facts if fact["date"] == day})
        zones = [{"timezone": zone or None,
                  "utc_offset_minutes": None if offset == 10**6 else offset,
                  "utc_offset": _offset_label(None if offset == 10**6 else offset)}
                 for zone, offset in labels]
        per_day.append({"date": day, "state": "known" if zones else "unknown", "zones": zones})
        if not zones:
            continue
        if previous is not None and zones != previous[1]:
            same_names = ({z["timezone"] for z in zones} == {z["timezone"] for z in previous[1]}
                          and all(z["timezone"] for z in zones))
            changes.append({"from_date": previous[0], "to_date": day,
                            "from": previous[1], "to": zones,
                            "kind": "offset_change_same_zone" if same_names else "zone_change"})
        previous = (day, zones)
    return {
        "facts": facts, "days": per_day, "changes": changes,
        "unknown_day_count": sum(item["state"] == "unknown" for item in per_day),
        "inference": "not_performed_unknown_zones_stay_unknown",
        "date_basis": "stored_source_local_dates_never_rebucketed_by_utc",
    }


def _packet_identity(packet: dict) -> dict:
    request = packet.get("request", {})
    return {
        "version": packet.get("version"), "envelope_hash": packet.get("envelope_hash"),
        "generated_at_utc": packet.get("generated_at_utc"),
        "evaluation_clock": packet.get("evaluation_clock"),
        "days": request.get("days"), "effective_range": request.get("effective_range"),
        "range_truncated": request.get("range_truncated"),
        "steps_view": request.get("steps_view", "observed"),
        "sources": request.get("sources"),
    }


def _comparison(request: PassportRequest, current: dict, previous: dict | None,
                current_steps: dict, current_sleep: dict) -> dict:
    if not request.compare_previous:
        return {"state": "not_requested"}
    if previous is None:
        return {"state": "unavailable", "reason": "previous_export_missing"}
    start, end = request.previous_start.isoformat(), request.previous_end.isoformat()
    today = previous["evaluation_clock"]["local_date"]
    prev_days = [d.isoformat() for d in (request.previous_start + timedelta(days=i)
                                         for i in range(request.day_count))]
    prev_section = previous["sections"].get("steps") or {}
    prev_cells = {cell["calendar_date"]: cell for cell in prev_section.get("cells", ())}
    prev_rows = [_steps_day(day, prev_cells.get(day), None, today) for day in prev_days]
    prev_counted = [row["value"] for row in prev_rows if row["state"] in STEPS_COUNTED_STATES]
    steps = {"current": {"counted_day_count": current_steps["counted_day_count"],
                         "total": current_steps["total"],
                         "mean_exact": current_steps["mean_exact"]},
             "previous": {"counted_day_count": len(prev_counted),
                          "total": sum(prev_counted) if prev_counted else None,
                          "mean_exact": _exact_mean(sum(prev_counted), len(prev_counted))
                          if prev_counted else None}}
    if prev_section.get("source_id") != current_steps["source_id"]:
        steps = {"state": "incompatible", "reason": "different_steps_source"}
    elif any(prev_section.get(key) != current_steps.get(key)
             for key in ("meaning", "unit", "display_zone")) or (
                 prev_section.get("contract_version") != current_steps["views"]["completed"]):
        steps = {"state": "incompatible", "reason": "different_steps_contract"}
    elif not prev_counted or not current_steps["counted_day_count"]:
        steps = {"state": "incompatible", "reason": "no_completed_days_in_one_period", **steps}
    else:
        steps = {"state": "compared", **steps}
    previous_sleep = _sleep(previous, start, end)["providers"]
    sleep = {}
    for name, provider in current_sleep["providers"].items():
        other = previous_sleep.get(name)
        values = [n["value"] for n in provider["nights"]
                  if n["state"] == "value" and not n.get("partial")
                  and n.get("unit") == "seconds" and type(n["value"]) is int]
        if other is None or other.get("source_id") != provider.get("source_id"):
            sleep[name] = {"state": "incompatible", "reason": "different_sleep_source"}
            continue
        other_values = [n["value"] for n in other["nights"]
                        if n["state"] == "value" and not n.get("partial")
                        and n.get("unit") == "seconds" and type(n["value"]) is int]
        summary = {
            "current": {"night_count": len(values),
                        "mean_seconds_exact": _exact_mean(sum(values), len(values))
                        if values else None},
            "previous": {"night_count": len(other_values),
                         "mean_seconds_exact": _exact_mean(sum(other_values), len(other_values))
                         if other_values else None},
        }
        sleep[name] = ({"state": "compared", **summary} if values and other_values
                       else {"state": "incompatible", "reason": "no_nights_in_one_period",
                             **summary})
    return {
        "state": "compared",
        "previous_period": {"start_date": start, "end_date": end,
                            "day_count": request.day_count},
        "steps": steps, "sleep": sleep,
        "rule": "same_length_window_immediately_before_same_sources_no_judgement",
    }


def build_passport(request: PassportRequest, packets: dict[str, dict]) -> dict[str, Any]:
    """Deterministic: the same packets always give the same passport."""
    request.validate()
    current, observed = packets["current"], packets["observed_steps"]
    start, end = request.start_date.isoformat(), request.end_date.isoformat()
    days = [d.isoformat() for d in request.dates()]
    today = current["evaluation_clock"]["local_date"]
    steps = _steps(current, observed, days, today)
    sleep = _sleep(current, start, end)
    workouts = _workouts(current, start, end)
    context = _context(current, start, end)
    if request.context_event_id and not any(
        row["event_id"] == request.context_event_id
        and row["revision_id"] == request.context_revision_id for row in context["rows"]
    ):
        # The chooser and evidence reader use separate snapshots. Do not attach
        # a stale or capped-out revision to a passport of the current export.
        raise PassportError("selected_context_revision_unavailable")
    zones = _zones(context, workouts, days)
    recovery = _recovery(current, start, end)
    future = [day for day in days if day > today]
    passport = {
        "version": PASSPORT_VERSION,
        "title": request.title.strip(),
        "place": request.place.strip() or None,
        "selection": {
            "kind": "context_event" if request.context_event_id else "manual_period",
            "context_event_id": request.context_event_id,
            "context_revision_id": request.context_revision_id,
        },
        "period": {"start_date": start, "end_date": end, "day_count": request.day_count,
                   "precision": "inclusive_local_date"},
        "coverage": {
            "requested_day_count": len(days),
            "past_or_today_day_count": len(days) - len(future),
            "future_dates": future,
            "evaluation_local_date": today,
            "steps_counted_day_count": steps["counted_day_count"],
            "sleep_nights_with_value": {
                name: sum(n["state"] == "value" for n in provider["nights"])
                for name, provider in sleep["providers"].items()},
            "zone_known_day_count": len(days) - zones["unknown_day_count"],
        },
        "source_exports": {role: _packet_identity(packet) for role, packet in packets.items()},
        "snapshot": "independent_source_export_transactions_not_one_shared_snapshot",
        "steps": steps,
        "sleep": sleep,
        "workouts": workouts,
        "recovery": recovery,
        "context": context,
        "zones": zones,
        "comparison": _comparison(request, current, packets.get("previous"), steps, sleep),
        "limits": {
            "max_passport_days": MAX_PASSPORT_DAYS,
            "export_window_days": request.export_days,
            "allowed_export_windows": list(EXPORT_WINDOWS),
            "context_row_limit": CONTEXT_ROW_LIMIT,
            "max_output_bytes": MAX_BUNDLE_BYTES,
            "over_cap_policy": "refuse_no_window_stitching",
        },
        "interpretation": {
            "relationship": "local_date_window_cooccurrence_only",
            "causality": "not_established",
            "source_pooling": "not_performed",
            "missing_is_not_zero": True,
            "not_computed": ["distance_from_steps", "route", "calories", "health_score",
                             "diagnosis"],
            "publication": "local_download_only",
        },
    }
    passport["passport_hash"] = hashlib.sha256(
        _json(passport).encode("utf-8")).hexdigest()
    return passport


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, default=str)


def encode_passport_bundle(passport: dict, packets: dict[str, dict]) -> str:
    """Passport facts together with the exact source export packets they came from."""
    bundle = {
        "version": "trip-passport-bundle-v1",
        "passport": passport,
        "source_exports": {role: json.loads(encode_combined_evidence(packet))
                           for role, packet in packets.items()},
    }
    result = json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=1,
                        allow_nan=False, default=str) + "\n"
    if len(result.encode("utf-8")) > MAX_BUNDLE_BYTES:
        raise EvidenceError("output_exceeds_byte_limit")
    return result


# ---------------------------------------------------------------------------
# Markdown rendering (same facts as JSON; no new numbers)
# ---------------------------------------------------------------------------

STEPS_LABELS = {
    "completed": "завершённый день", "zero": "завершённый день, 0 шагов",
    "incomplete": "день не подтверждён завершённым", "conflict": "конфликт сохранённых значений",
    "missing": "нет данных", "future": "дата позже даты просмотра",
}


def _md_duration(seconds: int | str | None) -> str:
    """Whole minutes, half-up, like the page; the exact seconds stay in JSON."""
    if seconds is None or isinstance(seconds, bool):
        return "—"
    if 0 < Decimal(seconds) < 60:
        return "<1 мин"
    minutes = int((Decimal(seconds) / 60).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    hours, rest = divmod(minutes, 60)
    return (f"{hours} ч " if hours else "") + f"{rest} мин"


def _md_mean(value: str | None) -> str:
    return "—" if value is None else str(Decimal(value).quantize(Decimal(1), ROUND_HALF_UP))


def _md_literal(value: str) -> str:
    # Owner text is literal data, never active Markdown/HTML or remote images.
    return re.sub(r"([\\`*_{}\[\]()<>#+.!|~-])", r"\\\1", value)


def render_passport_markdown(passport: dict) -> str:
    period = passport["period"]
    lines = [f"# {_md_literal(passport['title'])}"]
    if passport.get("place"):
        lines.append(f"Место: {_md_literal(passport['place'])}")
    lines += [
        "",
        f"Период: {period['start_date']} — {period['end_date']} ({period['day_count']} дн., "
        "локальные даты включительно)",
        f"Паспорт: {passport['version']} · sha256 {passport['passport_hash']}",
        "Исходные экспорты: " + ", ".join(
            f"{role} {item['version']} {item['envelope_hash']}"
            for role, item in sorted(passport["source_exports"].items())),
        "",
        "Только сохранённые данные. Нет данных ≠ 0. Источники не суммируются. "
        "Без км из шагов, маршрутов, калорий, общей оценки и диагнозов.",
        "",
        "## Шаги (Garmin)",
    ]
    steps = passport["steps"]
    total = steps["total"] if steps["total"] is not None else "—"
    lines.append(f"Учтено завершённых дней: {steps['counted_day_count']} из "
                 f"{period['day_count']}; сумма: {total}; "
                 f"в среднем за учтённый день: {_md_mean(steps['mean_exact'])}")
    lines += ["", "| Дата | Шаги | Состояние |", "|---|---|---|"]
    for row in steps["days"]:
        value = row["value"] if row["value"] is not None else "—"
        lines.append(f"| {row['date']} | {value} | {STEPS_LABELS[row['state']]} |")
    lines += ["", "## Сон по ночам (дата пробуждения)"]
    for name, provider in passport["sleep"]["providers"].items():
        lines.append(f"### {name} · источник {provider.get('source_id')}")
        lines += ["| Дата | Сон | Состояние |", "|---|---|---|"]
        for night in provider["nights"]:
            lines.append(f"| {night['wake_date']} | {_md_duration(night['value'])} | "
                         f"{night['state']}{' (частично)' if night.get('partial') else ''} |")
    lines += ["", "## Тренировки (сохранённый журнал)"]
    workouts = passport["workouts"]
    if workouts["state"] != "complete":
        lines.append(f"Список неполон: {workouts['state']} {workouts.get('reason') or ''}")
    if not workouts["sessions"] and workouts["state"] == "complete":
        lines.append("Сохранённых тренировок в периоде нет.")
    for item in workouts["sessions"]:
        start = item["start_local"] or (f"{item['start_utc']} (UTC, пояс не сохранён)"
                                        if item["start_utc"] else "время не сохранено")
        lines.append(f"- {item['date']}: {item['activity_type']}, начало {start}")
    lines += ["", "## Восстановление (как сохранено)"]
    for domain, providers in sorted(passport["recovery"].items()):
        for name, provider in sorted(providers.items()):
            values = ", ".join(f"{row['date']}: {row['value']}" for row in provider["values"]
                               if row["value"] is not None) or "нет сохранённых значений"
            lines.append(f"- {domain}/{name} ({provider.get('unit')}, "
                         f"{provider.get('meaning')}): {values}")
    lines += ["", "## Часовые пояса (только сохранённые)"]
    zones = passport["zones"]
    if not zones["changes"] and not zones["facts"]:
        lines.append("Пояс в сохранённых данных не указан.")
    for change in zones["changes"]:
        lines.append(f"- {change['from_date']} → {change['to_date']}: "
                     f"{_zones_text(change['from'])} → {_zones_text(change['to'])}")
    lines.append(f"Дней без сохранённого пояса: {zones['unknown_day_count']}")
    lines += ["", "## Комментарии"]
    context = passport["context"]
    if context["state"] == "truncated":
        lines.append(f"Показаны не все комментарии: предел {context['row_limit']}.")
    for row in context["rows"]:
        temporal = row["temporal"]
        when = temporal.get("start_source_timestamp") or temporal.get("start_local_date")
        if temporal.get("end_local_date"):
            when += " — " + (temporal.get("end_source_timestamp") or temporal["end_local_date"])
        lines.append(f"- {when}: {_md_literal(row['original_text'])}")
    if not context["rows"]:
        lines.append("Комментариев в периоде нет.")
    comparison = passport["comparison"]
    if comparison["state"] == "compared":
        prev = comparison["previous_period"]
        lines += ["", f"## Для сравнения: {prev['start_date']} — {prev['end_date']}"]
        steps_cmp = comparison["steps"]
        if steps_cmp["state"] == "compared":
            lines.append(f"- Шаги, в среднем за учтённый день: "
                         f"{_md_mean(steps_cmp['current']['mean_exact'])} "
                         f"({steps_cmp['current']['counted_day_count']} дн.) против "
                         f"{_md_mean(steps_cmp['previous']['mean_exact'])} "
                         f"({steps_cmp['previous']['counted_day_count']} дн.)")
        else:
            lines.append(f"- Шаги: сравнение недоступно ({steps_cmp['reason']})")
        for name, item in comparison["sleep"].items():
            if item["state"] == "compared":
                lines.append(
                    f"- Сон {name}, в среднем за ночь: "
                    f"{_md_duration(item['current']['mean_seconds_exact'])} "
                    f"({item['current']['night_count']} н.) против "
                    f"{_md_duration(item['previous']['mean_seconds_exact'])} "
                    f"({item['previous']['night_count']} н.)")
            else:
                lines.append(f"- Сон {name}: сравнение недоступно ({item['reason']})")
    result = "\n".join(lines) + "\n"
    if len(result.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise EvidenceError("output_exceeds_byte_limit")
    return result


def _zones_text(zones: list[dict]) -> str:
    return " / ".join(
        " ".join(part for part in (zone["timezone"], zone["utc_offset"]) if part)
        for zone in zones) or "неизвестно"
