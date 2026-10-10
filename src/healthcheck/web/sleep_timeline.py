"""Owner presentation for the accepted #343 B1 7/30-day source sleep ranges.

The UI only translates the accepted read-only packets: no pairing, canonical
selection, score invention, gap bridging or stored writes. Each exact persisted
source keeps its own labelled series; toggles hide a chart series only. Native
Garmin score stays a per-session detail; no Google score is promised.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from healthcheck.web.sleep_view import source_sleep_label, source_sleep_note

SLEEP_TIMELINE_CONTRACT_VERSION = "sleep-timeline-ui-v1"
SLEEP_TIMELINE_DEFAULT_DAYS = 30
SLEEP_TIMELINE_WINDOWS = (7, 30)
SLEEP_TIMELINE_PROVIDERS = ("garmin", "google")
SLEEP_SOURCE_FRESHNESS_SCOPES = ("garmin:sleep", "google:sleep")
SLEEP_FRESHNESS_ATTENTION_STATES = ("stale", "unavailable", "unknown", "not_requested")

# Bounded per-session evidence inside the Owner-visible technical disclosure.
SLEEP_TECHNICAL_METRIC_CODES = (
    "sleep_duration_asleep_seconds",
    "sleep_time_in_bed_seconds",
    "sleep_start_at",
    "sleep_end_at",
    "sleep_stage_light_seconds",
    "sleep_stage_deep_seconds",
    "sleep_stage_rem_seconds",
    "sleep_awake_waso_seconds",
    "sleep_score",
    "nap_duration_seconds",
)
SLEEP_TECHNICAL_METRIC_FIELDS = ("state", "eligible", "value", "reason", "is_zero")


def _provider_label(provider: str) -> str:
    return "Garmin" if provider == "garmin" else "Google"

SLEEP_FRESHNESS_STATE_TEXT = {
    "fresh": "обновления поступают",
    "quiet": "новых обновлений недавно не было",
    "stale": "данные обновлений устарели",
    "unavailable": "обновление источника недоступно",
    "unknown": "состояние обновлений неизвестно",
    "not_requested": "сбор не запрашивался",
}

# Only the accepted actionable vocabulary gets compact Owner prose; exact codes
# remain in the technical disclosure.
SLEEP_FRESHNESS_REASON_TEXT = {
    "reauth_required": "нужно повторное подключение",
    "required_stream_unavailable": "обязательные данные недоступны",
    "refresh_failed": "последняя попытка обновления не удалась",
    "refresh_overdue": "обновление задерживается",
    "expected_evidence_absent": "ожидаемые записи не поступили",
}


def sleep_timeline_days(value: str | None) -> int:
    """Accept only the accepted 7/30-day range windows; default is 30."""

    if value is None:
        return SLEEP_TIMELINE_DEFAULT_DAYS
    try:
        days = int(value)
    except (TypeError, ValueError):
        return SLEEP_TIMELINE_DEFAULT_DAYS
    return days if days in SLEEP_TIMELINE_WINDOWS else SLEEP_TIMELINE_DEFAULT_DAYS


def timeline_point_note(point: Mapping[str, Any]) -> str:
    """Owner note for one resolved source-local point; never a substituted value."""

    state = point.get("state")
    if state == "no_records":
        return "Нет сохранённой записи за эту дату."
    if state == "ambiguous":
        return "Несколько сохранённых сессий за дату; единое значение не выбрано."
    if state == "value":
        if point.get("is_zero"):
            return "Источник передал явный ноль; это значение, а не пропуск."
        if point.get("partial"):
            return "Запись неполная."
        return ""
    return source_sleep_note(
        {
            "eligible": False,
            "is_zero": False,
            "state": state,
            "reason": point.get("reason"),
        }
    )


def _point_view(raw: Mapping[str, Any] | None, day: str) -> dict[str, Any]:
    if raw is None:
        return {
            "wake_date": day,
            "state": "no_records",
            "value_seconds": None,
            "value_hours": None,
            "is_zero": False,
            "partial": False,
            "role_uncertain": False,
            "record_id": None,
            "reason": None,
            "candidate_record_ids": [],
            "candidate_count": 0,
            "exclusions": [],
            "exclusion_reasons": [],
            "note": "Нет сохранённой записи за эту дату.",
        }
    value = raw.get("value") if raw.get("state") == "value" else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        value = None
    candidates = list(raw.get("candidate_record_ids") or ())
    exclusions = [
        {"record_id": exclusion.get("record_id"), "reason": exclusion.get("reason")}
        for exclusion in raw.get("exclusions") or ()
        if isinstance(exclusion, Mapping)
    ]
    return {
        "wake_date": day,
        "state": raw.get("state"),
        "value_seconds": value,
        "value_hours": round(value / 3600.0, 6) if value is not None else None,
        "is_zero": bool(raw.get("is_zero")),
        "partial": bool(raw.get("partial")),
        "role_uncertain": bool(raw.get("role_uncertain")),
        "record_id": raw.get("record_id"),
        "reason": raw.get("reason"),
        "candidate_record_ids": candidates,
        "candidate_count": len(candidates),
        "exclusions": exclusions,
        "exclusion_reasons": [item["reason"] for item in exclusions],
        "note": timeline_point_note(raw),
    }


def _series_view(provider: str, item: Mapping[str, Any], dates: Sequence[str]) -> dict[str, Any]:
    source = item["source"]
    by_date = {point["wake_date"]: point for point in item.get("points") or ()}
    return {
        "series_id": f"{provider}:{source['source_id']}",
        "provider": provider,
        "label": source_sleep_label(source, provider),
        "source": source,
        "points": [_point_view(by_date.get(day), day) for day in dates],
    }


def _disambiguate_labels(series: Sequence[dict[str, Any]]) -> None:
    """Never let two exact sources silently share one legend label."""

    totals: dict[str, int] = {}
    for item in series:
        totals[item["label"]] = totals.get(item["label"], 0) + 1
    seen: dict[str, int] = {}
    for item in series:
        if totals[item["label"]] > 1:
            seen[item["label"]] = seen.get(item["label"], 0) + 1
            item["label"] = f"{item['label']} · источник {seen[item['label']]}"


def timeline_freshness_items(
    freshness: Mapping[str, Any] | None,
) -> list[dict[str, Any]] | None:
    """Compact truthful sleep freshness per provider; None means unreadable.

    Fresh/quiet required scopes do not appear in the accepted consumer pools.
    Absence therefore means "no attention item", not a claimed refresh.
    """

    if not isinstance(freshness, Mapping):
        return None
    pools: list[Mapping[str, Any]] = []
    owner = freshness.get("owner")
    if isinstance(owner, Mapping):
        pools.extend(
            item for item in owner.get("actionable_items") or () if isinstance(item, Mapping)
        )
    for key in ("optional_details", "not_requested_required"):
        pools.extend(item for item in freshness.get(key) or () if isinstance(item, Mapping))
    items: list[dict[str, Any]] = []
    for scope_key in SLEEP_SOURCE_FRESHNESS_SCOPES:
        provider = scope_key.split(":", 1)[0]
        match = next((item for item in pools if item.get("scope_key") == scope_key), None)
        state = match.get("state") if match else None
        reason = match.get("reason_code") if match else None
        attention = state in SLEEP_FRESHNESS_ATTENTION_STATES
        items.append(
            {
                "scope_key": scope_key,
                "provider": provider,
                "provider_label": "Garmin" if provider == "garmin" else "Google",
                "state": state,
                "state_text": SLEEP_FRESHNESS_STATE_TEXT.get(state),
                "reason_code": reason if attention else None,
                "reason_text": SLEEP_FRESHNESS_REASON_TEXT.get(reason) if attention else None,
                "attention": attention,
            }
        )
    return items


def build_sleep_timeline(
    ranges: Mapping[str, Mapping[str, Any]],
    *,
    days: int,
    end_date: date,
    freshness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge the accepted per-provider range packets into one display packet."""

    start = end_date - timedelta(days=days - 1)
    dates = [(start + timedelta(days=offset)).isoformat() for offset in range(days)]
    providers: dict[str, Any] = {}
    nights: dict[str, dict[str, Any]] = {}
    series: list[dict[str, Any]] = []
    undated_records: list[dict[str, Any]] = []
    read_limited = False
    for provider in SLEEP_TIMELINE_PROVIDERS:
        packet = ranges.get(provider)
        if not isinstance(packet, Mapping):
            packet = {"state": "unavailable", "days": [], "series": []}
        limited = packet.get("state") == "read_limit_exceeded"
        read_limited = read_limited or limited
        providers[provider] = {
            "state": packet.get("state"),
            "read_limit_exceeded": limited,
            # Overflow keeps completeness counts unavailable, not misleading.
            "observed_dates": None if limited else packet.get("observed_dates"),
            "missing_dates": None if limited else packet.get("missing_dates"),
            "wake_date_missing_count": (
                None if limited else packet.get("wake_date_missing_count")
            ),
            "wake_date_missing_by_source": (
                None if limited else packet.get("wake_date_missing_by_source")
            ),
            "limit": packet.get("limit"),
        }
        # B1 retains bounded null-wake-date records as real saved evidence.
        # They never get an invented date and must never read as confirmed empty.
        missing = 0 if limited else int(packet.get("wake_date_missing_count") or 0)
        if missing:
            undated_records.append(
                {
                    "provider": provider,
                    "provider_label": _provider_label(provider),
                    "count": missing,
                }
            )
        nights[provider] = {
            day["wake_date"]: day
            for day in packet.get("days") or ()
            if isinstance(day, Mapping) and day.get("wake_date")
        }
        if not limited:
            series.extend(
                _series_view(provider, item, dates) for item in packet.get("series") or ()
            )
    _disambiguate_labels(series)
    return {
        "contract_version": SLEEP_TIMELINE_CONTRACT_VERSION,
        "days": days,
        "start_date": start.isoformat(),
        "end_date": end_date.isoformat(),
        "dates": dates,
        "providers": providers,
        "series": series,
        "table_rows": [
            {"date": day, "cells": [item["points"][index] for item in series]}
            for index, day in enumerate(dates)
        ],
        "nights": nights,
        "undated_records": undated_records,
        "freshness": timeline_freshness_items(freshness),
        "read_limit_exceeded": read_limited,
    }


def _technical_session(session: Mapping[str, Any]) -> dict[str, Any]:
    metrics = session.get("metrics") or {}
    return {
        "record_id": session.get("record_id"),
        "record_status": session.get("record_status"),
        "reason": session.get("reason"),
        "role": session.get("role"),
        "field_states": session.get("field_states"),
        "temporal_evidence": session.get("temporal_evidence"),
        "metrics": {
            code: {
                field: metrics[code].get(field)
                for field in SLEEP_TECHNICAL_METRIC_FIELDS
                if field in metrics[code]
            }
            for code in SLEEP_TECHNICAL_METRIC_CODES
            if isinstance(metrics.get(code), Mapping)
        },
    }


def _technical_nights(nights: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Bounded exact per-night evidence for the Owner-visible disclosure."""

    out: list[dict[str, Any]] = []
    for provider in SLEEP_TIMELINE_PROVIDERS:
        for day, packet in (nights.get(provider) or {}).items():
            sources = packet.get("sources") or []
            if not sources:
                continue
            out.append(
                {
                    "provider": provider,
                    "wake_date": day,
                    "sources": [
                        {
                            "source_id": source["source"]["source_id"],
                            "source_kind": source["source"]["source_kind"],
                            "source_instance_id": source["source"]["source_instance_id"],
                            "device_attributed": source["source"]["device_attributed"],
                            "sessions": [
                                _technical_session(session)
                                for session in source.get("sessions") or ()
                            ],
                        }
                        for source in sources
                    ],
                }
            )
    return out


def sleep_timeline_technical(timeline: Mapping[str, Any]) -> dict[str, Any]:
    """Bounded per-night/point disclosure; no raw provider payload bodies."""

    return {
        "contract_version": timeline.get("contract_version"),
        "window": {
            "days": timeline.get("days"),
            "start_date": timeline.get("start_date"),
            "end_date": timeline.get("end_date"),
        },
        "providers": timeline.get("providers"),
        "undated_records": timeline.get("undated_records"),
        "series": [
            {
                "series_id": item["series_id"],
                "provider": item["provider"],
                "label": item["label"],
                "source": item["source"],
                "point_states": _point_state_counts(item["points"]),
                "points": item["points"],
            }
            for item in timeline.get("series") or ()
        ],
        "nights": _technical_nights(timeline.get("nights") or {}),
    }


def _point_state_counts(points: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for point in points:
        state = str(point.get("state"))
        counts[state] = counts.get(state, 0) + 1
    return counts
