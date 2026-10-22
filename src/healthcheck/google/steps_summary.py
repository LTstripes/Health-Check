"""Pure summaries of an authoritative saved Google Steps reader packet.

The v1 reader proves currentness, raw interval identity, provenance and its I/O
limits. This adapter does not repeat that proof or read history. It checks the
packet's selected identity and complete daily grain before aggregating the
reader's eligible values. It never establishes full-day/provider completeness.
"""

from collections.abc import Mapping
from datetime import date
from typing import Any

from healthcheck.google.contracts import (
    GOOGLE_PROVIDER_CODE,
    INT64_MAX,
    KNOWN_DATA_SOURCE_FAMILIES,
)

CONTRACT_VERSION = "google-observed-steps-summary-v1"
READER_CONTRACT_VERSION = "google-saved-steps-window-v1"
_NONVALUE_STATES = frozenset(
    {"no_observation", "missing", "null", "invalid", "ambiguous", "unavailable"}
)


def _unassessed(reason: str) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "state": "unassessed",
        "reason": reason,
        "source_id": None,
        "family": None,
        "start_date": None,
        "end_date": None,
        "requested_day_count": None,
        "observed_day_count": None,
        "nonvalue_day_count": None,
        "total": None,
        "total_display": None,
        "mean_ratio": None,
        "mean_display": None,
        "coverage": "unknown",
        "pagination": "unknown",
        "timezone": "unknown",
        "finality": "unknown",
    }


def _mean_display(total: int, count: int) -> str:
    # Exact HALF_EVEN to one decimal, independent of float/Decimal contexts.
    tenths, remainder = divmod(total * 10, count)
    if remainder * 2 > count or (remainder * 2 == count and tenths % 2):
        tenths += 1
    if total > 0 and tenths == 0:
        return "<0.1"
    return f"{tenths // 10}.{tenths % 10}"


def summarize_saved_steps_window(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Aggregate one complete v1 Python reader packet, without mutating it.

    Dates are the reader's civil ``date`` objects, not JSON-decoded timestamps.
    Selection, incomplete search or malformed packets leave all counts unassessed.
    Only a complete selected-source window may establish zero observed days.
    Per-cell source/provenance is inherited from the reader: v1 cells themselves
    carry no independent source identity and are not a raw-data import interface.
    """
    if not isinstance(packet, Mapping):
        return _unassessed("invalid_packet")
    if packet.get("contract_version") != READER_CONTRACT_VERSION:
        return _unassessed("unsupported_reader_contract")
    if packet.get("search_complete") is False:
        return _unassessed("search_incomplete")
    if packet.get("search_complete") is not True:
        return _unassessed("invalid_packet")
    if packet.get("reason") is not None:
        return _unassessed("reader_unavailable")
    if any(
        packet.get(key) != "unknown" for key in ("coverage", "pagination", "timezone", "finality")
    ):
        return _unassessed("invalid_packet")

    start, end = packet.get("start_date"), packet.get("end_date")
    if type(start) is not date or type(end) is not date:
        return _unassessed("invalid_window")
    days = (end - start).days + 1
    if days not in {7, 30} or end == date.max:
        return _unassessed("invalid_window")

    source_id, identity = packet.get("source_id"), packet.get("source_identity")
    if (
        not isinstance(source_id, str)
        or not 1 <= len(source_id) <= 36
        or not isinstance(identity, Mapping)
    ):
        return _unassessed("invalid_source_identity")
    family = identity.get("family")
    if (
        identity.get("source_id") != source_id
        or identity.get("provider_code") != GOOGLE_PROVIDER_CODE
        or identity.get("source_kind") != "family_aggregate"
        or not isinstance(family, str)
        or family not in KNOWN_DATA_SOURCE_FAMILIES
    ):
        return _unassessed("invalid_source_identity")
    choices = packet.get("source_choices")
    if (
        not isinstance(choices, list)
        or len(choices) > 128
        or any(not isinstance(item, Mapping) for item in choices)
    ):
        return _unassessed("invalid_source_identity")
    selected = [
        item for item in choices if isinstance(item, Mapping) and item.get("source_id") == source_id
    ]
    if len(selected) != 1 or selected[0].get("family") != family:
        return _unassessed("invalid_source_identity")
    examined = packet.get("records_examined")
    if type(examined) is not int or not 0 <= examined <= 4096:
        return _unassessed("invalid_packet")

    cells = packet.get("cells")
    if not isinstance(cells, list) or len(cells) != days:
        return _unassessed("invalid_daily_grain")
    seen: set[date] = set()
    total = count = 0
    for cell in cells:
        if not isinstance(cell, Mapping):
            return _unassessed("invalid_daily_grain")
        day, state, value = cell.get("calendar_date"), cell.get("state"), cell.get("value")
        if type(day) is not date or not start <= day <= end or day in seen:
            return _unassessed("invalid_daily_grain")
        seen.add(day)
        if not isinstance(state, str):
            return _unassessed("invalid_daily_value")
        if state == "value":
            if type(value) is not int or not 0 <= value <= INT64_MAX:
                return _unassessed("invalid_daily_value")
            total += value
            count += 1
        elif state not in _NONVALUE_STATES or value is not None:
            # A current nonvalue can never carry an older corrected number.
            return _unassessed("invalid_daily_value")
    if count > examined:
        return _unassessed("invalid_packet")

    result = _unassessed("no_eligible_observations")
    result.update(
        state="observed" if count else "no_eligible_observations",
        reason=None if count else "no_eligible_observations",
        source_id=source_id,
        family=family,
        start_date=start,
        end_date=end,
        requested_day_count=days,
        observed_day_count=count,
        nonvalue_day_count=days - count,
    )
    if count:
        result.update(
            total=total,
            total_display=str(total),
            mean_ratio={"numerator": total, "denominator": count},
            mean_display=_mean_display(total, count),
        )
    return result
