"""Optional analyses of the already allowlisted, bounded saved Sleep snapshot.

No queries, source selection, persistence, provider access or host timezone.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta, timezone
from statistics import mean
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from healthcheck.analytics.sleep_source_view import resolve_source_sleep_point
from healthcheck.chat_evidence import EvidenceError, _json

MIN_NIGHTS = 3
METRICS = ("sleep_duration_asleep_seconds", "sleep_time_in_bed_seconds",
           "sleep_awake_waso_seconds", "sleep_score")


def validate_options(request):
    for key in ("include_context_recovery", "include_sleep_regularity"):
        if type(getattr(request, key)) is not bool:
            raise EvidenceError("invalid_analysis_selection")
    if (type(request.context_pairing_hours) is not int
            or not 1 <= request.context_pairing_hours <= 48):
        raise EvidenceError("invalid_context_pairing_window")
    if request.include_context_recovery and not request.include_context:
        raise EvidenceError("context_analysis_requires_context")
    if type(request.sleep_day_types) is not tuple or len(request.sleep_day_types) > 30:
        raise EvidenceError("invalid_sleep_day_classification")
    seen = set()
    start = request.end_date - timedelta(days=request.days - 1)
    for item in request.sleep_day_types:
        if type(item) is not tuple or len(item) != 2:
            raise EvidenceError("invalid_sleep_day_classification")
        day, kind = item
        if type(day) is not str or type(kind) is not str:
            raise EvidenceError("invalid_sleep_day_classification")
        try:
            parsed = date.fromisoformat(day)
        except (TypeError, ValueError):
            raise EvidenceError("invalid_sleep_day_classification") from None
        if (day != parsed.isoformat() or day in seen or not start <= parsed <= request.end_date
                or kind not in {"work", "free", "unknown"}):
            raise EvidenceError("invalid_sleep_day_classification")
        seen.add(day)
    if request.sleep_day_types and not request.include_sleep_regularity:
        raise EvidenceError("classification_requires_sleep_regularity")


def _instant(value):
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.utcoffset() is not None else None
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value)
        return result.astimezone(UTC) if result.utcoffset() is not None else None
    except ValueError:
        return None


def _endpoint(item, provider, endpoint):
    cell = item["metrics"][f"sleep_{endpoint}_at"]
    instant = _instant(cell["value"])
    if not cell["eligible"] or cell["state"] != "value" or instant is None:
        return None, cell.get("reason") or f"{endpoint}_instant_unavailable"
    if provider == "garmin" and endpoint == "start":
        temporal = item["temporal_evidence"]
    else:
        matches = [row for row in cell["evidence"]["interval_snapshots"]
                   if _instant(row.get(f"{endpoint}_at_utc")) == instant
                   and (provider != "google" or row.get("interval_kind") == "sleep_session")]
        if len(matches) != 1:
            return None, f"{endpoint}_temporal_ambiguous_or_missing"
        temporal = matches[0].get(f"{endpoint}_temporal")
    if not isinstance(temporal, dict):
        return None, f"{endpoint}_temporal_unavailable"
    if temporal.get("precision") != "instant":
        return None, f"{endpoint}_precision_unavailable"
    zone, offset = temporal.get("source_timezone"), temporal.get("source_utc_offset_minutes")
    if (zone is not None and (type(zone) is not str or not zone)
            or offset is not None and (type(offset) not in (int, float)
                                       or not math.isfinite(offset) or not -1440 < offset < 1440)):
        return None, f"{endpoint}_timezone_invalid"
    try:
        if zone:
            tz = ZoneInfo(zone)
            local = instant.astimezone(tz)
            if offset is not None and local.utcoffset().total_seconds() != offset * 60:
                return None, f"{endpoint}_zone_offset_conflict"
            regime = {"kind": "iana_zone", "zone": zone}
        elif type(offset) in (int, float) and math.isfinite(offset) and -1440 < offset < 1440:
            tz = timezone(timedelta(minutes=offset))
            local = instant.astimezone(tz)
            regime = {"kind": "explicit_fixed_offset", "minutes": offset}
        else:
            return None, f"{endpoint}_local_timezone_unavailable"
    except (ValueError, ZoneInfoNotFoundError):
        return None, f"{endpoint}_timezone_invalid"
    return {"utc": instant.isoformat(), "local": local.isoformat(), "fold": local.fold,
            "clock_minutes": local.hour * 60 + local.minute + local.second / 60
            + local.microsecond / 60000000,
            "regime": regime, "temporal": temporal, "method": cell["comparison_basis"],
            "field_path": cell["field_path"]}, None


def _nights(sleep):
    nights, exclusions, coverage = [], [], {}
    seen = set()
    seen_nights = set()
    for provider, section in sleep["providers"].items():
        source_range = section["source_range"]
        coverage[provider] = {"source_id": section["selected_source_id"],
                              "acquisition_coverage": section["acquisition_coverage"],
                              "range": None if source_range is None else {
                                  key: value for key, value in source_range.items()
                                  if key not in {"days", "series"}}}
        if source_range is None:
            continue
        for day in source_range["days"]:
            for source in day["sources"]:
                point = resolve_source_sleep_point(source, provider=provider)
                for item in source["sessions"]:
                    record_id = item["record_id"]
                    identity = (provider, source["source"]["source_id"], record_id)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    base = {"provider": provider, "source_id": identity[1],
                            "record_id": record_id, "wake_date": day["wake_date"]}
                    reason = item["reason"]
                    if record_id != point["record_id"]:
                        reason = reason or point["reason"] or "not_selected_source_night"
                    if provider == "google" and (item.get("role") or {}).get(
                            "selection") != "explicit_main":
                        reason = reason or "google_main_sleep_unconfirmed"
                    if reason:
                        exclusions.append({**base, "reason": reason})
                        continue
                    start, start_error = _endpoint(item, provider, "start")
                    end, end_error = _endpoint(item, provider, "end")
                    reason = start_error or end_error
                    if not reason:
                        if _instant(end["utc"]) <= _instant(start["utc"]):
                            reason = "nonpositive_sleep_interval"
                        elif start["regime"] != end["regime"]:
                            reason = "within_night_timezone_change"
                        elif datetime.fromisoformat(end["local"]).date().isoformat() != base[
                                "wake_date"]:
                            reason = "local_wake_date_conflict"
                    if reason:
                        exclusions.append({**base, "reason": reason})
                        continue
                    night_key = (provider, identity[1], base["wake_date"])
                    if night_key in seen_nights:
                        exclusions.append({**base, "reason": "duplicate_source_wake_date"})
                        continue
                    seen_nights.add(night_key)
                    regime = start["regime"]
                    tz = (ZoneInfo(regime["zone"]) if regime["kind"] == "iana_zone" else
                          timezone(timedelta(minutes=regime["minutes"])))
                    midpoint = (_instant(start["utc"]) + (
                        _instant(end["utc"]) - _instant(start["utc"])) / 2).astimezone(tz)
                    normalization = item["metrics"]["sleep_start_at"]["evidence"][
                        "normalization_provenance"]
                    partition = {"provider": provider, "source_id": identity[1],
                                 "variant": item["variant"], "start_method": start["method"],
                                 "end_method": end["method"], "local_clock_regime": regime,
                                 "normalization_contract": normalization.get(
                                     "normalization_contract_version")}
                    metrics = {code: {key: cell.get(key) for key in (
                        "state", "value", "unit", "eligible", "reason", "comparison_basis",
                        "variant", "field_path")} for code in METRICS
                        if (cell := item["metrics"].get(code)) is not None}
                    nights.append({**base, "partition": partition, "role": item["role"],
                                   "selection_basis": "accepted_source_night",
                                   "start": start, "end": end,
                                   "midpoint": {"local": midpoint.isoformat(),
                                                "fold": midpoint.fold,
                                                "clock_minutes": midpoint.hour * 60
                                                + midpoint.minute + midpoint.second / 60
                                                + midpoint.microsecond / 60000000},
                                   "metrics": metrics,
                                   "evidence_reference": "sections.sleep.providers / source_id / "
                                                         "wake_date / record_id / metrics"})
    return sorted(nights, key=lambda n: (n["start"]["utc"], n["provider"], n["record_id"])), (
        exclusions, coverage)


def circular_local_clock(values):
    """Population circular SD on a 1440-minute circle; never linear clock SD."""
    result = {"n": len(values), "state": "insufficient", "mean_clock_minutes": None,
              "circular_sd_minutes": None, "resultant_length": None}
    if len(values) < MIN_NIGHTS:
        return result
    angles = [value * math.tau / 1440 for value in values]
    x, y = mean(math.cos(a) for a in angles), mean(math.sin(a) for a in angles)
    radius = min(1.0, math.hypot(x, y))
    result["resultant_length"] = radius
    if radius < 1e-12:
        result["state"] = "undefined_direction"
        return result
    result.update(state="sufficient", mean_clock_minutes=(math.atan2(y, x) % math.tau)
                  * 1440 / math.tau,
                  circular_sd_minutes=math.sqrt(-2 * math.log(radius)) * 1440 / math.tau)
    return result


def _regularity(nights, request):
    day_types = dict(request.sleep_day_types)
    groups = defaultdict(list)
    for night in nights:
        groups[_json(night["partition"])].append(night)
    results = []
    for rows in groups.values():
        clocks = {endpoint: circular_local_clock([n[endpoint]["clock_minutes"] for n in rows])
                  for endpoint in ("start", "end", "midpoint")}
        classified = {kind: [n for n in rows if day_types.get(n["wake_date"], "unknown") == kind]
                      for kind in ("work", "free", "unknown")}
        social = {kind: circular_local_clock([n["midpoint"]["clock_minutes"] for n in selected])
                  for kind, selected in classified.items() if kind != "unknown"}
        available = all(item["state"] == "sufficient" for item in social.values())
        signed = ((social["free"]["mean_clock_minutes"] - social["work"]["mean_clock_minutes"]
                   + 720) % 1440 - 720) if available else None
        results.append({"partition": rows[0]["partition"], "nights": len(rows),
                        "record_ids": [n["record_id"] for n in rows], "clocks": clocks,
                        "social_jetlag": {"variant": "uncorrected_circular_free_minus_work",
                                          "state": "sufficient" if available else "insufficient",
                                          "signed_minutes": signed,
                                          "absolute_minutes": abs(signed) if available else None,
                                          "groups": social,
                                          "unknown_nights": len(classified["unknown"])}})
    return {"version": "saved-sleep-circular-local-clock-v1", "min_nights": MIN_NIGHTS,
            "eligible_nights": len(nights),
            "state": "partitioned" if nights else "insufficient",
            "formula": "theta=2*pi*minutes/1440; R=abs(mean(exp(i*theta))); "
                       "SD=sqrt(-2*ln(R))*1440/(2*pi)",
            "midpoint_method": "elapsed_UTC_midpoint_converted_to_source_local_clock",
            "classification": {"authority": "explicit_caller_wake_date_labels",
                               "dates": day_types, "unlisted": "unknown"},
            "groups": results}


def _numeric(cell):
    return (cell is not None and cell.get("eligible") is True and cell.get("state") == "value"
            and type(cell.get("value")) in (int, float) and math.isfinite(cell["value"]))


def _recovery(nights, context, request):
    pairs, excluded = [], []
    groups = defaultdict(list)
    for night in nights:
        groups[_json(night["partition"])].append(night)
    pairing_groups = defaultdict(list)
    for night in nights:
        pairing_groups[(night["provider"], night["source_id"])].append(night)
    for row in context["rows"]:
        temporal = row["temporal"]
        endpoint = "end" if temporal["kind"] == "interval" else "start"
        anchor = _instant(temporal.get(f"{endpoint}_at_utc"))
        event = {key: row[key] for key in ("event_id", "revision_id", "revision_number",
                                          "capture_source", "temporal", "tags")}
        if temporal.get(f"{endpoint}_precision") not in {
                "minute", "second", "microsecond"} or anchor is None:
            excluded.append({**event, "reason": "event_anchor_not_an_explicit_instant"})
            continue
        found = False
        for rows in pairing_groups.values():
            eligible = [n for n in rows if anchor <= _instant(n["start"]["utc"])
                        <= anchor + timedelta(hours=request.context_pairing_hours)]
            if not eligible:
                continue
            earliest = min(n["start"]["utc"] for n in eligible)
            choices = [n for n in eligible if n["start"]["utc"] == earliest]
            if len(choices) != 1:
                excluded.append({**event, "partition": rows[0]["partition"],
                                 "reason": "first_night_timing_tie"})
                continue
            found = True
            night = choices[0]
            pairs.append({**event, "partition": night["partition"],
                          "record_id": night["record_id"], "wake_date": night["wake_date"],
                          "anchor": endpoint, "anchor_at_utc": anchor.isoformat(),
                          "lag_to_sleep_start_hours": (
                              _instant(night["start"]["utc"]) - anchor).total_seconds() / 3600})
        if not found:
            excluded.append({**event, "reason": "no_eligible_night_in_bounded_snapshot_window"})
    comparisons = []
    for key, rows in groups.items():
        paired_ids = {p["record_id"] for p in pairs if _json(p["partition"]) == key}
        paired = [n for n in rows if n["record_id"] in paired_ids]
        reference = [n for n in rows if n["record_id"] not in paired_ids]
        metrics = []
        # Partition each metric's actual accepted method too; no source/variant/unit pooling.
        for code in METRICS:
            signatures = sorted({_json({k: c.get(k) for k in (
                "unit", "comparison_basis", "variant")}) for n in rows
                if (c := n["metrics"].get(code)) is not None})
            for signature in signatures:
                def compatible(n):
                    c = n["metrics"].get(code)
                    return _numeric(c) and _json({k: c.get(k) for k in (
                        "unit", "comparison_basis", "variant")}) == signature
                left, right = ([n for n in selection if compatible(n)]
                               for selection in (paired, reference))
                sufficient = len(left) >= MIN_NIGHTS and len(right) >= MIN_NIGHTS
                metrics.append({"metric": code, "method": json.loads(signature),
                                "state": "sufficient" if sufficient else "insufficient",
                                "paired_n": len(left), "reference_n": len(right),
                                "paired_missing_or_incompatible": len(paired) - len(left),
                                "reference_missing_or_incompatible": len(reference) - len(right),
                                "paired_record_ids": [n["record_id"] for n in left],
                                "reference_record_ids": [n["record_id"] for n in right],
                                "paired_mean": mean(n["metrics"][code]["value"] for n in left)
                                if sufficient else None,
                                "reference_mean": mean(n["metrics"][code]["value"] for n in right)
                                if sufficient else None,
                                "mean_difference": (mean(n["metrics"][code]["value"] for n in left)
                                                    - mean(n["metrics"][code]["value"]
                                                           for n in right))
                                 if sufficient else None})
        comparisons.append({"partition": rows[0]["partition"],
                            "paired_unique_nights": len(paired), "reference_nights": len(reference),
                            "metrics": metrics})
    return {"version": "saved-context-next-sleep-v1", "pairing_window_hours": [
        0, request.context_pairing_hours], "window_inclusive": True,
        "selection": "first_eligible_start_per_exact_source_then_partition_for_comparison",
        "reference": "other_compatible_snapshot_nights_exposure_unknown_not_event_free_controls",
        "comparison": "descriptive_pooled_timed_context_events_no_causal_or_diagnostic_inference",
        "recovery_scope": "accepted_sleep_measures_only_no_HRV_Body_Battery_or_workout_join",
        "min_unique_nights_per_comparison_group": MIN_NIGHTS,
        "context_coverage": {key: value for key, value in context.items() if key != "rows"},
        "pairs": pairs, "event_exclusions": excluded, "comparisons": comparisons}


def analyze_saved_sleep(sections, request):
    nights, (exclusions, coverage) = _nights(sections["sleep"])
    result = {"version": "saved-sleep-analysis-inputs-v1", "nights": nights,
              "night_exclusions": exclusions, "coverage": coverage,
              "limits": "inherited_bounded_snapshot_no_window_expansion_or_winning_prefix",
              "limitations": ["stored_presence_not_acquisition_completeness",
                              "date_window_edges_can_omit_events_or_following_nights",
                              "travel_partitioned_by_explicit_zone_or_fixed_offset",
                              "within_night_zone_changes_excluded_shift_work_not_corrected"]}
    sections["sleep_analysis_inputs"] = result
    if request.include_sleep_regularity:
        sections["sleep_regularity"] = _regularity(nights, request)
    if request.include_context_recovery:
        sections["context_recovery"] = _recovery(nights, sections["context"], request)
