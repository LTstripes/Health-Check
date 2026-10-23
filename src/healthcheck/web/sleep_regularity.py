"""Compact Sleep-only presentation of the accepted saved regularity analysis."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

from healthcheck.chat_evidence import EvidenceError
from healthcheck.saved_sleep_analysis import analyze_saved_sleep
from healthcheck.sleep_evidence import RANGE, _project


def _complete_range(packet: Any, provider: str, days: int, end: date) -> bool:
    if not isinstance(packet, Mapping) or packet.get("state") not in {"records", "no_records"}:
        return False
    start = end - timedelta(days=days - 1)
    expected = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    return (
        packet.get("provider") == provider
        and packet.get("start_date") == expected[0]
        and packet.get("end_date") == expected[-1]
        and isinstance(packet.get("days"), (list, tuple))
        and [item.get("wake_date") if isinstance(item, Mapping) else None
             for item in packet["days"]] == expected
        and all(isinstance(item.get("sources"), (list, tuple)) for item in packet["days"])
    )


def _source_input(packet: Mapping[str, Any], source_id: str) -> dict[str, Any]:
    # Presence counts and daily states belong to the provider-wide read. They
    # are deliberately absent here; the original timeline packet stays intact.
    view = {key: packet[key] for key in (
        "contract_version", "provider", "start_date", "end_date", "state", "limit",
    ) if key in packet}
    view["days"] = [{"wake_date": day["wake_date"], "sources": [
        source for source in day["sources"] if source["source"]["source_id"] == source_id
    ]} for day in packet["days"]]
    return {"selected_source_id": source_id, "acquisition_coverage": {"state": "unknown"},
            "source_range": _project(view, RANGE)}


def _clock_view(clock: Mapping[str, Any]) -> dict[str, Any]:
    value, state = clock["circular_sd_minutes"], clock["state"]
    if state == "sufficient" and value is not None:
        text = "0 мин" if value == 0 else "<1 мин" if value < 1 else f"{value:.0f} мин"
    elif state == "undefined_direction":
        text = "Нет устойчивого времени"
    else:
        text = "Недостаточно ночей"
    return {"state": state, "minutes": value, "text": text}


def build_sleep_regularity(
    ranges: Mapping[str, Mapping[str, Any]], display_series: Sequence[Mapping[str, Any]],
    *, google_selection: Mapping[str, Any], days: int, end_date: date,
) -> dict[str, Any]:
    """Reuse the already-read exact-source nights; never choose a new winner."""
    result: dict[str, Any] = {"state": "insufficient", "sources": [],
                             "empty_text": "Пока недостаточно подходящих ночей."}
    if days not in (7, 30):
        result.update(state="unavailable", empty_text="Не удалось оценить этот период.")
        return result
    complete = {provider: _complete_range(ranges.get(provider), provider, days, end_date)
                for provider in ("garmin", "google")}
    for series in display_series:
        provider, source_id = series["provider"], series["source"]["source_id"]
        if provider == "google" and source_id != google_selection.get("selected_source_id"):
            continue
        row = {"label": series["label"], "provider": provider, "source_id": source_id,
               "state": "unavailable", "groups": [], "eligible_nights": None,
               "min_nights": None, "excluded_nights": None, "exclusions": []}
        result["sources"].append(row)
        if not complete.get(provider):
            continue
        try:
            sections = {"sleep": {"providers": {provider: _source_input(
                ranges[provider], source_id,
            )}}}
            analyze_saved_sleep(sections, SimpleNamespace(
                include_sleep_regularity=True, include_context_recovery=False, sleep_day_types=(),
            ))
        except (EvidenceError, KeyError, TypeError, ValueError):
            # A malformed/incompatible packet is not an empty saved history.
            continue
        analysis = sections["sleep_regularity"]
        inputs = sections["sleep_analysis_inputs"]
        row.update(state=analysis["state"], eligible_nights=analysis["eligible_nights"],
                   min_nights=analysis["min_nights"],
                   excluded_nights=len(inputs["night_exclusions"]),
                   exclusions=[{"reason": reason, "count": count} for reason, count in sorted(
                       Counter(item["reason"] for item in inputs["night_exclusions"]).items())])
        for group in analysis["groups"]:
            row["groups"].append({"partition": group["partition"], "nights": group["nights"],
                                  "start": _clock_view(group["clocks"]["start"]),
                                  "end": _clock_view(group["clocks"]["end"])})
    if result["sources"]:
        result["state"] = "sources"
    elif google_selection.get("status") in {"require_selection", "invalid_selection"}:
        result.update(state="source_required", empty_text="Выберите источник Google выше.")
    elif not all(complete.values()):
        result.update(state="unavailable", empty_text="Не удалось оценить этот период.")
    return result
