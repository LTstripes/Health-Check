"""Bounded current Context → source sleep presentation; no provider or data writes."""

from dataclasses import asdict
from datetime import date, timedelta
from types import SimpleNamespace

from fastapi.encoders import jsonable_encoder

from healthcheck.chat_evidence import EvidenceError
from healthcheck.context.service import ContextService
from healthcheck.saved_sleep_analysis import (
    _instant,
    analyze_saved_sleep,
    compare_context_night,
    pair_context_nights,
)
from healthcheck.web.owner_presentation import owner_duration
from healthcheck.web.sleep_regularity import _complete_range, _source_input
from healthcheck.web.sleep_social_jetlag import travel_night_reasons

CONTEXT_LIMIT = 199
PAIRING_RULE = "первая ночь после окончания события"


def read_sleep_context(session, *, start, end):
    # 28 reference dates plus two local-date margins for the 24-hour UTC
    # pairing window and explicit offsets; never read created_at as event time.
    lower = max(date.min, start - timedelta(days=min(32, (start - date.min).days)))
    views = ContextService(session).list(from_date=lower, to_date=end,
                                         limit=CONTEXT_LIMIT + 1, history=False)
    return {"rows": jsonable_encoder([asdict(v) for v in views[:CONTEXT_LIMIT]]),
            "has_more": len(views) > CONTEXT_LIMIT, "start_date": lower.isoformat(),
            "end_date": end.isoformat(), "limit": CONTEXT_LIMIT}


def _time(row):
    temporal = row["temporal"]
    values = [str(temporal.get(f"{key}_source_timestamp") or
                  temporal.get(f"{key}_local_date") or "") for key in ("start", "end")]
    return " → ".join(values) if temporal["kind"] == "interval" else values[0]


def _short(row):
    value = row.get("original_text", "")
    return value if len(value) <= 60 else value[:59] + "…"


def _comparison_text(value):
    if not value["reference_complete"]:
        return "Сравнение недоступно: история прочитана не полностью"
    duration, start = value["duration_delta_minutes"], value["start_delta_minutes"]
    parts = []
    if duration is not None:
        parts.append(f"{duration:+.0f} мин к обычной длительности "
                     f"(обычное по {value['duration_reference_n']} ночам)")
    if start is not None:
        direction = "позже" if start > 0 else "раньше"
        parts.append((f"засыпание на {abs(start):.0f} мин {direction}" if start else
                      "засыпание в обычное время") +
                     f" (обычное по {value['reference_n']} ночам)")
    if duration is None or start is None:
        parts.append("мало ночей для сравнения" if value["reference_n"] < 7 or
                     value["duration_reference_n"] < 7 else "длительность недоступна")
    return " · ".join(parts)


def _unpaired_reason(row, inputs, packet=None):
    temporal = row["temporal"]
    endpoint = "end" if temporal["kind"] == "interval" else "start"
    anchor = _instant(temporal.get(f"{endpoint}_at_utc"))
    if temporal.get(f"{endpoint}_precision") not in {"minute", "second", "microsecond"} or (
            anchor is None):
        return "нет времени"
    candidates = set()
    for day in (packet or {}).get("source_range", {}).get("days", []):
        for source in day["sources"]:
            for item in source["sessions"]:
                instant = _instant(item.get("metrics", {}).get("sleep_start_at", {}).get("value"))
                if instant is not None and anchor <= instant <= anchor + timedelta(hours=24):
                    candidates.add(item["record_id"])
    nearby = [e["reason"] for e in inputs["night_exclusions"] if e["record_id"] in candidates]
    if any("timezone" in r for r in nearby):
        return "поездка / смена часового пояса"
    if any("nap" in r or "ambiguous" in r or "unconfirmed" in r for r in nearby):
        return "дневной сон / неоднозначная ночь"
    if nearby:
        return "нет пригодных данных времени ночи"
    later = any(_instant(n["start"]["utc"]) > anchor for n in inputs["nights"])
    return "вне окна 24 часов" if later else "нет данных следующей ночи"


def build_sleep_context(ranges, display_series, *, days, end_date, context=None,
                        history_ranges=None, google_selection=None):
    result = {"rows": [], "markers": {}, "technical": [], "has_more": False,
              "state": "unavailable", "rule": PAIRING_RULE}
    if context is None:
        return result
    result.update(state="available", has_more=context["has_more"],
                  empty_reason="выберите источник Google" if (google_selection or {}).get(
                      "status") in {"require_selection", "invalid_selection"} else "нет данных")
    start = end_date - timedelta(days=days - 1)
    events = [r for r in context["rows"] if
              str(r["temporal"]["start_local_date"]) <= end_date.isoformat() and
              str(r["temporal"].get("end_local_date") or
                  r["temporal"]["start_local_date"]) >= start.isoformat()]
    for row in events:
        result["rows"].append({"time": _time(row), "text": _short(row), "sources": [],
            "time_missing": _unpaired_reason(row, {"nights": [], "night_exclusions": []}) ==
                            "нет времени"})
    for series in display_series:
        provider, source_id = series["provider"], series["source"]["source_id"]
        identity = series["series_id"]
        inputs = {"nights": [], "night_exclusions": []}
        packet = None
        complete = _complete_range(ranges.get(provider), provider, days, end_date)
        history_end = start - timedelta(days=1)
        history_complete = _complete_range((history_ranges or {}).get(provider), provider,
                                           30, history_end)
        if complete:
            try:
                packet = _source_input(ranges[provider], source_id)
                if history_complete:
                    prior = _source_input(history_ranges[provider], source_id)
                    packet["source_range"]["days"] = (prior["source_range"]["days"] +
                                                        packet["source_range"]["days"])
                sections = {"sleep": {"providers": {provider: packet}}}
                analyze_saved_sleep(sections, SimpleNamespace(
                    include_sleep_regularity=False, include_context_recovery=False))
                inputs = sections["sleep_analysis_inputs"]
            except (EvidenceError, KeyError, TypeError, ValueError):
                complete = False
        pairs, exclusions = pair_context_nights(inputs["nights"], context)
        travel = travel_night_reasons(inputs)
        nights = {n["record_id"]: n for n in inputs["nights"]}
        comparable = [n for n in inputs["nights"] if n["record_id"] not in travel]
        markers = {}
        for pair in pairs:
            night = nights[pair["record_id"]]
            if pair["record_id"] in travel or not start.isoformat() <= night["wake_date"] <= (
                    end_date.isoformat()):
                continue
            row = next(r for r in context["rows"] if r["event_id"] == pair["event_id"])
            key = (night["wake_date"], night["record_id"])
            markers.setdefault(key, []).append(f"{_time(row)} · {_short(row)}")
        result["markers"][identity] = [{"wake_date": key[0], "record_id": key[1],
            "text": ("1 событие" if len(texts) == 1 else f"{len(texts)} события") + " · " +
                    " · ".join(texts) + " · " + PAIRING_RULE}
            for key, texts in markers.items()]
        for row, view in zip(events, result["rows"], strict=True):
            pair = next((p for p in pairs if p["event_id"] == row["event_id"]), None)
            cell = {"series_id": identity, "label": series["label"], "night": None,
                    "reason": "нет времени" if view["time_missing"] else
                              "источник недоступен" if not complete else
                              _unpaired_reason(row, inputs, packet)}
            if any(e["event_id"] == row["event_id"] and e["reason"] == "first_night_timing_tie"
                   for e in exclusions):
                cell["reason"] = "неоднозначная первая ночь"
            if pair:
                night = nights[pair["record_id"]]
                if pair["record_id"] in travel:
                    cell["reason"] = "поездка / смена часового пояса"
                elif night["wake_date"] > end_date.isoformat():
                    cell["reason"] = "ночь вне выбранного периода"
                else:
                    comparison = compare_context_night(night, comparable, pairs,
                        reference_complete=not context["has_more"] and (history_complete or
                            date.fromisoformat(night["wake_date"]) - timedelta(days=28) >= start))
                    duration = night["metrics"].get("sleep_duration_asleep_seconds")
                    value = duration.get("value") if duration and duration.get("eligible") and (
                        duration.get("state") == "value") else None
                    cell.update(night=night["wake_date"], duration=owner_duration(value),
                                start=night["start"]["local"], end=night["end"]["local"],
                                comparison=_comparison_text(comparison))
                    result["technical"].append({"event_id": row["event_id"],
                        "revision_id": row["revision_id"], "pair": pair, "comparison": comparison})
            view["sources"].append(cell)
        result["technical"].append({"series_id": identity, "event_exclusions": exclusions,
            "night_exclusions": inputs["night_exclusions"], "history_complete": history_complete})
    return result
