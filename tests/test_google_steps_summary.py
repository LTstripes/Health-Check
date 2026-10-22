"""Pure observed-day aggregates, independent of acquisition and presentation."""

from copy import deepcopy
from datetime import date, datetime, timedelta

import pytest

from healthcheck.google.contracts import (
    FAMILY_ALL_SOURCES,
    FAMILY_GOOGLE_WEARABLES,
    GOOGLE_PROVIDER_CODE,
    INT64_MAX,
)
from healthcheck.google.steps_summary import CONTRACT_VERSION, summarize_saved_steps_window

END = date(2099, 2, 2)


def packet(*values, days=7, source="source-one", family=FAMILY_GOOGLE_WEARABLES):
    start = END - timedelta(days=days - 1)
    cells = []
    for index in range(days):
        value = values[index] if index < len(values) else None
        state = "value" if value is not None else "no_observation"
        cells.append(
            {
                "calendar_date": start + timedelta(days=index),
                "state": state,
                "value": value,
                "reason": None if value is not None else "no_saved_interval",
                "evidence": [],
            }
        )
    return {
        "contract_version": "google-saved-steps-window-v1",
        "start_date": start,
        "end_date": END,
        "source_id": source,
        "source_identity": {
            "source_id": source,
            "provider_code": GOOGLE_PROVIDER_CODE,
            "source_kind": "family_aggregate",
            "family": family,
        },
        "source_choices": [{"source_id": source, "family": family, "family_label": "wearables"}],
        "cells": cells,
        "search_complete": True,
        "reason": None,
        "coverage": "unknown",
        "pagination": "unknown",
        "timezone": "unknown",
        "finality": "unknown",
        "records_examined": len(values),
    }


def assert_unassessed(result):
    assert result["state"] == "unassessed"
    for key in (
        "requested_day_count",
        "observed_day_count",
        "nonvalue_day_count",
        "total",
        "total_display",
        "mean_ratio",
        "mean_display",
    ):
        assert result[key] is None


@pytest.mark.parametrize("days", [7, 30])
def test_one_observed_day_is_not_mean_over_requested_period(days):
    original = packet(123, days=days)
    before = deepcopy(original)
    got = summarize_saved_steps_window(original)
    assert got["contract_version"] == CONTRACT_VERSION
    assert (got["requested_day_count"], got["observed_day_count"], got["nonvalue_day_count"]) == (
        days,
        1,
        days - 1,
    )
    assert got["total"] == 123
    assert got["mean_ratio"] == {"numerator": 123, "denominator": 1}
    assert got["mean_display"] == "123.0"
    assert all(got[key] == "unknown" for key in ("coverage", "pagination", "timezone", "finality"))
    assert original == before


def test_explicit_zero_counts_while_missing_and_other_nonvalues_do_not():
    original = packet(0, 12)
    for cell, state in zip(
        original["cells"][2:],
        ("missing", "null", "invalid", "ambiguous", "unavailable"),
        strict=True,
    ):
        cell.update(state=state, reason="reader_exclusion")
    got = summarize_saved_steps_window(original)
    assert (got["total"], got["observed_day_count"], got["nonvalue_day_count"]) == (12, 2, 5)
    assert got["mean_ratio"] == {"numerator": 12, "denominator": 2}
    assert got["mean_display"] == "6.0"


@pytest.mark.parametrize("zero_count", [1, 7])
def test_proved_zero_observations_are_available_values(zero_count):
    got = summarize_saved_steps_window(packet(*([0] * zero_count)))
    assert got["state"] == "observed"
    assert got["total"] == 0 and got["total_display"] == "0"
    assert got["mean_ratio"] == {"numerator": 0, "denominator": zero_count}
    assert got["mean_display"] == "0.0"


def test_complete_selected_source_all_missing_proves_zero_observed_days_not_zero_steps():
    got = summarize_saved_steps_window(packet())
    assert got["state"] == "no_eligible_observations"
    assert got["observed_day_count"] == 0 and got["nonvalue_day_count"] == 7
    assert got["total"] is got["mean_ratio"] is got["mean_display"] is None


def test_full_requested_observation_grid_still_does_not_prove_coverage():
    got = summarize_saved_steps_window(packet(1, 2, 3, 4, 5, 6, 7))
    assert got["observed_day_count"] == got["requested_day_count"] == 7
    assert got["coverage"] == got["pagination"] == got["timezone"] == got["finality"] == "unknown"


def test_int64_values_sum_beyond_int64_and_javascript_exact_range():
    got = summarize_saved_steps_window(packet(INT64_MAX, INT64_MAX, 2**53 + 1))
    expected = 2 * INT64_MAX + 2**53 + 1
    assert type(got["total"]) is int and got["total"] == expected
    assert got["total_display"] == str(expected)
    assert got["mean_ratio"] == {"numerator": expected, "denominator": 3}
    assert got["mean_display"] == "6151917090988097535.7"


@pytest.mark.parametrize(
    "total,count,display",
    [(1, 20, "<0.1"), (3, 20, "0.2"), (5, 20, "0.2"), (1, 3, "0.3"), (2, 3, "0.7")],
)
def test_mean_rounding_uses_exact_half_even_and_never_labels_small_positive_zero(
    total, count, display
):
    got = summarize_saved_steps_window(packet(total, *([0] * (count - 1)), days=30))
    assert got["mean_ratio"] == {"numerator": total, "denominator": count}
    assert got["mean_display"] == display


def test_current_nonvalue_correction_does_not_reuse_a_previous_number_in_evidence():
    original = packet(7, 30)
    original["cells"][1].update(
        state="invalid",
        value=None,
        reason="current_record_unavailable",
        evidence=[{"previous_value": 30}],
    )
    got = summarize_saved_steps_window(original)
    assert got["total"] == 7 and got["observed_day_count"] == 1


def test_source_families_remain_independent():
    wearable = summarize_saved_steps_window(packet(12))
    all_sources = summarize_saved_steps_window(
        packet(99, source="source-two", family=FAMILY_ALL_SOURCES)
    )
    assert (wearable["source_id"], wearable["family"], wearable["total"]) == (
        "source-one",
        FAMILY_GOOGLE_WEARABLES,
        12,
    )
    assert (all_sources["source_id"], all_sources["family"], all_sources["total"]) == (
        "source-two",
        FAMILY_ALL_SOURCES,
        99,
    )


def test_explicit_selection_does_not_require_a_single_global_source_choice():
    original = packet(12)
    original["source_choices"].append(
        {"source_id": "source-two", "family": FAMILY_ALL_SOURCES, "family_label": "all"}
    )
    got = summarize_saved_steps_window(original)
    assert got["source_id"] == "source-one"
    assert got["family"] == FAMILY_GOOGLE_WEARABLES
    assert got["total"] == 12


@pytest.mark.parametrize(
    "reason",
    [
        "record_search_incomplete",
        "child_search_incomplete",
        "text_budget_exceeded",
        "work_budget_exceeded",
        "unlocatable_interval",
    ],
)
def test_incomplete_search_never_summarizes_a_numeric_prefix(reason):
    original = packet(999)
    original.update(search_complete=False, reason=reason)
    got = summarize_saved_steps_window(original)
    assert_unassessed(got)
    assert got["reason"] == "search_incomplete"


@pytest.mark.parametrize(
    "reason",
    [
        "source_selection_required",
        "no_saved_source",
        "source_not_evidenced",
        "invalid_source_identity",
    ],
)
def test_unavailable_selection_is_not_zero_observed_days(reason):
    original = packet(999)
    original.update(reason=reason, source_id=None, source_identity=None)
    assert_unassessed(summarize_saved_steps_window(original))


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_id", "other"),
        ("provider_code", "garmin_connect"),
        ("source_kind", "device"),
        ("family", "unknown-family"),
    ],
)
def test_packet_source_identity_mismatch_fails_closed(field, value):
    original = packet(999)
    original["source_identity"][field] = value
    assert_unassessed(summarize_saved_steps_window(original))


@pytest.mark.parametrize("family", [[], {}, True, None])
def test_malformed_family_is_unassessed_without_membership_errors(family):
    original = packet(999)
    original["source_identity"]["family"] = family
    assert_unassessed(summarize_saved_steps_window(original))


@pytest.mark.parametrize("kind", ["missing", "different_family", "duplicate"])
def test_selected_source_choice_must_match_exact_family_once(kind):
    original = packet(999)
    if kind == "missing":
        original["source_choices"] = []
    elif kind == "different_family":
        original["source_choices"][0]["family"] = FAMILY_ALL_SOURCES
    else:
        original["source_choices"] *= 2
    assert_unassessed(summarize_saved_steps_window(original))


@pytest.mark.parametrize("kind", ["duplicate", "missing", "outside", "datetime", "json_date"])
def test_full_unique_civil_date_grid_required(kind):
    original = packet(12, 18)
    if kind == "duplicate":
        original["cells"][1]["calendar_date"] = original["cells"][0]["calendar_date"]
    elif kind == "missing":
        original["cells"].pop()
    elif kind == "outside":
        original["cells"][0]["calendar_date"] = original["start_date"] - timedelta(days=1)
    elif kind == "datetime":
        original["cells"][0]["calendar_date"] = datetime(2099, 1, 27)
    else:
        original["cells"][0]["calendar_date"] = original["start_date"].isoformat()
    assert_unassessed(summarize_saved_steps_window(original))


@pytest.mark.parametrize("value", [True, False, 1.0, "1", -1, INT64_MAX + 1, None])
def test_value_state_requires_reader_v1_exact_nonnegative_int64(value):
    original = packet(7)
    original["cells"][0]["value"] = value
    assert_unassessed(summarize_saved_steps_window(original))


@pytest.mark.parametrize("state,value", [("invalid", 999), ("missing", 0), ("value-ish", None)])
def test_malformed_nonvalue_cannot_carry_a_number_or_unknown_state(state, value):
    original = packet(7)
    original["cells"][0].update(state=state, value=value)
    assert_unassessed(summarize_saved_steps_window(original))


@pytest.mark.parametrize("state", [None, [], {}, 1])
def test_malformed_state_is_not_an_exception_or_a_number(state):
    original = packet(7)
    original["cells"][0].update(state=state, value=None)
    assert_unassessed(summarize_saved_steps_window(original))


@pytest.mark.parametrize(
    "field,value",
    [
        ("contract_version", "google-saved-steps-window-v2"),
        ("search_complete", 1),
        ("coverage", "complete"),
        ("records_examined", 4097),
        ("records_examined", True),
        ("records_examined", 0),
    ],
)
def test_unrecognized_or_contradictory_reader_packet_fails_closed(field, value):
    original = packet(7)
    original[field] = value
    assert_unassessed(summarize_saved_steps_window(original))


@pytest.mark.parametrize("days", [1, 6, 8, 90, 365, 366])
def test_future_window_support_requires_an_explicit_reader_contract_extension(days):
    assert_unassessed(summarize_saved_steps_window(packet(7, days=days)))


def test_reordering_cells_does_not_change_the_observed_day_aggregate():
    original = packet(3, 0, 8)
    expected = summarize_saved_steps_window(original)
    original["cells"].reverse()
    assert summarize_saved_steps_window(original) == expected


@pytest.mark.parametrize("malformed", [None, [], {}, {"contract_version": "unexpected"}])
def test_invalid_input_is_unassessed_not_a_partial_total(malformed):
    assert_unassessed(summarize_saved_steps_window(malformed))
