"""#493 display contract, independent endpoint proof and unchanged typed evidence."""

from copy import deepcopy

import pytest

from healthcheck.web.owner_presentation import (
    owner_activity_count,
    owner_activity_type,
    owner_activity_types,
    owner_duration,
)
from healthcheck.web.sleep_comparison import comparison_value
from healthcheck.web.sleep_view import source_sleep_note, source_sleep_value


@pytest.mark.parametrize("seconds,text", [
    (0, "0 мин"), (0.001, "<1 мин"), (59.999, "<1 мин"), (60, "1 мин"),
    (89.999, "1 мин"), (90, "2 мин"), (150, "3 мин"), (3599.99, "1 ч 0 мин"),
    (None, "Недоступно"), (False, "Недоступно"), (-1, "Недоступно"),
])
def test_readable_duration_keeps_zero_subminute_and_half_up(seconds, text):
    assert owner_duration(seconds) == text


@pytest.mark.parametrize("seconds,text", [
    (-0.001, "−<1 мин"), (0, "0 мин"), (0.001, "+<1 мин"),
    (-90, "−2 мин"), (90, "+2 мин"),
])
def test_signed_deltas_keep_sign_even_below_display_minute(seconds, text):
    assert comparison_value(seconds, "seconds", signed=True) == text


@pytest.mark.parametrize("count,text", [
    (0, "0 тренировок"), (1, "1 тренировка"), (2, "2 тренировки"),
    (5, "5 тренировок"), (11, "11 тренировок"), (14, "14 тренировок"),
    (21, "21 тренировка"), (22, "22 тренировки"),
])
def test_activity_composition_is_localized_without_reclassifying(count, text):
    assert owner_activity_count(count) == text
    assert owner_activity_type("tennis_v2") == "Теннис"
    assert owner_activity_type("unreviewed_sport") == "Другой вид активности"
    counts = {"tennis": 1, "tennis_v2": 1, "cycling": 1, "unreviewed_sport": 1}
    original = deepcopy(counts)
    assert owner_activity_types(counts) == "теннис, велосипед, другой вид активности"
    assert counts == original


def _cell(value, *, eligible=True, temporal=None):
    return {"eligible": eligible, "value": value, "unit": "UTC instant",
            "evidence": {"interval_snapshots": [
                {"start_precision": "instant", "end_precision": "instant",
                 "start_temporal": temporal, "end_temporal": temporal}]} }


def _temporal(stamp, offset):
    return {"precision": "instant", "measured_at_utc": stamp,
            "source_utc_offset_minutes": offset}


def test_endpoint_offsets_are_independent_across_dst_and_never_host_based():
    start = _cell("2026-10-24T20:00:00Z", temporal=_temporal("2026-10-24T20:00:00Z", 120))
    end = _cell("2026-10-25T06:00:00Z", temporal=_temporal("2026-10-25T06:00:00Z", 60))
    session = {"metrics": {"sleep_start_at": start, "sleep_end_at": end},
               "temporal_evidence": {"source_utc_offset_minutes": 180}}
    original = deepcopy(session)
    assert source_sleep_value(start, session, "sleep_start_at") == (
        "24 октября 2026, 22:00 UTC+0200")
    assert source_sleep_value(end, session, "sleep_end_at") == (
        "25 октября 2026, 07:00 UTC+0100")
    end["evidence"] = {}
    assert source_sleep_value(end, session, "sleep_end_at") == "25 октября 2026, 06:00 UTC"
    end["evidence"] = original["metrics"]["sleep_end_at"]["evidence"]
    assert session == original


def test_summary_metadata_formats_only_matching_eligible_endpoint_and_conflict_is_utc():
    cell = _cell("2026-10-25T06:00:00Z")
    boundary = {"quality_inputs": {"summary_boundary": {
        "start": _temporal("2026-10-24T20:00:00Z", 120),
        "end": _temporal("2026-10-25T06:00:00Z", 60)}}}
    session = {"metrics": {"duration": {"evidence": boundary}}}
    assert source_sleep_value(cell, session, "sleep_end_at").endswith("07:00 UTC+0100")
    cell["eligible"] = False
    assert source_sleep_value(cell, session, "sleep_end_at") == "—"
    cell["eligible"] = True
    cell["evidence"] = _cell(cell["value"], temporal=_temporal(cell["value"], 120))["evidence"]
    assert source_sleep_value(cell, session, "sleep_end_at").endswith("06:00 UTC")
    cell["value"] = "2026-10-25T08:00:00Z"
    assert source_sleep_value(cell, session, "sleep_end_at").endswith("08:00 UTC")


def test_legacy_a_valid_scalar_keeps_duration_and_unverified_disclosure_without_stages():
    cell = {"eligible": True, "value": 25200, "unit": "seconds", "is_zero": False,
            "evidence": {"quality_inputs": {"session_bound_validation": {
                "state": "unverified", "reason": "summary_session_boundary_unavailable"}}}}
    original = deepcopy(cell)
    assert source_sleep_value(cell) == "7 ч 0 мин"
    assert "не проверена" in source_sleep_note(cell)
    assert cell == original
