"""Adversarial synthetic tests for the openScale-sync contract layer.

Every payload uses invented values (synthetic users, fixed dates); no real
health data, captures, tokens, or device material enters this file.  JSON
fixtures live in ``tests/fixtures/openscale/``; key/values reorderings are
built inline to prove determinism.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from healthcheck.ingestion.openscale import (
    OPENSCALE_CONTRACT_VERSION,
    delete_fallback_identity,
    measurement_fingerprint,
    normalize_envelope,
    semantic_fingerprint,
    stable_record_identity,
)

FIXTURES = Path(__file__).parent / "fixtures" / "openscale"
SOURCE_INSTANCE = "11111111-2222-3333-4444-555555555555"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def single_measurement(**overrides):
    payload = {
        "event": "insert",
        "id": "synthetic-record-1",
        "userId": "synthetic-user-1",
        "username": "Synthetic User",
        "date": "2026-02-10T08:15:00+03:00",
    }
    payload.update(overrides)
    return payload


def weight_item(value, **overrides):
    item = {"key": "weight", "name": "Weight", "unit": "kg", "value": value, "isDerived": False}
    item.update(overrides)
    return item


def test_convenience_zero_with_no_weight_item_yields_no_weight() -> None:
    """Adversarial case 1: convenience weight=0 is transport default, not evidence."""

    result = normalize_envelope(
        load_fixture("convenience_zero_no_weight_item.json"),
        source_instance_id=SOURCE_INSTANCE,
    )
    assert result.ok
    assert len(result.measurements) == 1
    measurement = result.measurements[0]
    assert measurement.values_authoritative is True
    assert "weight" not in measurement.metric_codes()
    assert [item.metric_code for item in measurement.metrics if item.status == "ok"] == [
        "body_fat_pct"
    ]
    fat = [item for item in measurement.metrics if item.metric_code == "body_fat_pct"]
    assert len(fat) == 1 and fat[0].status == "ok" and fat[0].value == pytest.approx(24.5)


def test_explicit_zero_for_invalid_metric_is_typed_invalid_not_missing() -> None:
    """Adversarial case 2: explicit zero stays explicit and unusable."""

    payload = single_measurement(values=[weight_item(0)])
    result = normalize_envelope(payload, source_instance_id=SOURCE_INSTANCE)
    assert len(result.measurements) == 1
    (metric,) = result.measurements[0].metrics
    assert metric.metric_code == "weight"
    assert metric.status == "invalid"
    assert metric.reason == "explicit_zero_or_negative_invalid"
    assert metric.has_explicit_value is True
    assert metric.value == pytest.approx(0.0)
    assert result.measurements[0].usable_metrics() == ()


def test_reordered_keys_and_values_give_identical_output() -> None:
    """Adversarial case 3: JSON/object ordering never affects semantics."""

    base = {
        "event": "insert",
        "id": "synthetic-record-7",
        "userId": "synthetic-user-1",
        "username": "Synthetic User",
        "date": "2026-02-10T08:15:00+03:00",
        "values": [
            {"key": "fat", "name": "Body fat", "unit": "%", "value": 24.5, "isDerived": True},
            {"key": "weight", "name": "Weight", "unit": "kg", "value": 76.4, "isDerived": False},
        ],
    }
    shuffled = {
        "username": "Synthetic User",
        "values": list(reversed(base["values"])),
        "date": "2026-02-10T08:15:00+03:00",
        "userId": "synthetic-user-1",
        "id": "synthetic-record-7",
        "event": "insert",
    }
    first = normalize_envelope(base, source_instance_id=SOURCE_INSTANCE)
    second = normalize_envelope(shuffled, source_instance_id=SOURCE_INSTANCE)
    assert first.measurements[0].as_dict() == second.measurements[0].as_dict()
    assert measurement_fingerprint(
        first.measurements[0], source_instance_id=SOURCE_INSTANCE
    ) == measurement_fingerprint(second.measurements[0], source_instance_id=SOURCE_INSTANCE)


def test_unknown_values_key_retained_without_invented_metric() -> None:
    """Adversarial case 4: unknown keys are evidence, never canonical metrics."""

    payload = single_measurement(
        values=[
            weight_item(76.4),
            {"key": "quantumFlux", "name": "Quantum", "unit": "qf", "value": 9.5},
        ]
    )
    result = normalize_envelope(payload, source_instance_id=SOURCE_INSTANCE)
    measurement = result.measurements[0]
    assert measurement.metric_codes() == ("weight",)
    (unknown,) = measurement.unknown_items
    assert unknown.key == "quantumFlux"
    assert unknown.detail == "unknown_metric_key_or_unit"


def test_duplicate_contradictory_values_fail_closed_as_ambiguity() -> None:
    """Adversarial case 5: no last-one-wins, ever."""

    payload = single_measurement(values=[weight_item(76.4), weight_item(77.9)])
    result = normalize_envelope(payload, source_instance_id=SOURCE_INSTANCE)
    measurement = result.measurements[0]
    (metric,) = [item for item in measurement.metrics if item.metric_code == "weight"]
    assert metric.status == "ambiguous"
    assert metric.reason == "duplicate_conflicting_values"
    assert metric.value is None
    assert measurement.usable_metrics() == ()
    assert "duplicate_conflicting_values" in [
        item.reason_code for item in result.failures
    ]


def test_identical_duplicates_collapse_deterministically() -> None:
    payload = single_measurement(values=[weight_item(76.4), weight_item(76.4)])
    result = normalize_envelope(payload, source_instance_id=SOURCE_INSTANCE)
    measurement = result.measurements[0]
    assert [item.metric_code for item in measurement.metrics] == ["weight"]
    assert measurement.metrics[0].status == "ok"
    assert any(
        item.detail == "duplicate_identical_collapsed" for item in measurement.unknown_items
    )


def test_numeric_string_is_never_silently_coerced() -> None:
    """Adversarial case 6: contract carries numbers as numbers."""

    payload = single_measurement(values=[weight_item("76.4")])
    result = normalize_envelope(payload, source_instance_id=SOURCE_INSTANCE)
    measurement = result.measurements[0]
    assert measurement.metric_codes() == ()
    codes = [item.reason_code for item in result.failures] + [
        item.failures[0].reason_code for item in result.item_warnings
    ]
    assert "numeric_string_not_coerced" in codes


def test_malformed_inputs_are_sanitized_failures() -> None:
    """Adversarial case 7: typed failures carry no values or payload dumps."""

    bad_payloads = [
        {"event": "insert", "userId": "u", "date": "not-a-date", "values": [weight_item(76.4)]},
        {
            "event": "insert",
            "userId": "u",
            "date": "2026-13-99T99:99:99",
            "values": [weight_item(76.4)],
        },
        {"event": "teleport", "userId": "u"},
        {"event": "insert", "date": "2026-02-10", "values": [weight_item(76.4)]},
        {"event": "insert", "userId": "u", "date": "2026-02-10", "values": {"key": "weight"}},
        ["not", "an", "object"],
    ]
    for payload in bad_payloads:
        result = normalize_envelope(payload, source_instance_id=SOURCE_INSTANCE)
        assert result.measurements == () or result.failures or result.invalid_items
        # Typed failure texts carry reason codes, never values or payload dumps.
        failure_texts = [
            f"{item.reason_code}: {item.message} @ {item.path}" for item in result.failures
        ]
        for quarantined in result.invalid_items:
            failure_texts.extend(
                f"{item.reason_code}: {item.message} @ {item.path}"
                for item in quarantined.failures
            )
        assert failure_texts
        blob = json.dumps(failure_texts)
        assert "76.4" not in blob
        assert "not-a-date" not in blob
    reasons = normalize_envelope(
        {"event": "teleport"}, source_instance_id=SOURCE_INSTANCE
    ).failures
    assert [item.reason_code for item in reasons] == ["invalid_event"]


def test_non_finite_value_is_typed_invalid() -> None:
    payload = single_measurement(values=[weight_item(float("inf"))])
    result = normalize_envelope(payload, source_instance_id=SOURCE_INSTANCE)
    (metric,) = result.measurements[0].metrics
    assert metric.status == "invalid"
    assert metric.reason == "non_finite_value"


def test_stable_identity_ignores_username_and_formatting() -> None:
    """Adversarial case 8: (source_instance, userId, id) is the whole identity."""

    first = stable_record_identity(SOURCE_INSTANCE, "synthetic-user-1", "synthetic-record-1")
    second = stable_record_identity(SOURCE_INSTANCE, "synthetic-user-1", "synthetic-record-1")
    assert first == second
    assert first.startswith("stable:")
    renamed = single_measurement(username="Completely Different Name", values=[weight_item(76.4)])
    result = normalize_envelope(renamed, source_instance_id=SOURCE_INSTANCE)
    assert result.measurements[0].identity == first
    assert result.measurements[0].identity_kind == "stable_id"


def test_delete_fallback_identity_stable_under_ordering_noise() -> None:
    """Adversarial case 9: delete identity uses (source_instance, user, time)."""

    first = normalize_envelope(
        load_fixture("delete_fallback.json"), source_instance_id=SOURCE_INSTANCE
    )
    reordered = {
        "date": "2026-02-10T08:15:00+03:00",
        "username": "Someone Else Entirely",
        "userId": "synthetic-user-1",
        "event": "delete",
    }
    second = normalize_envelope(reordered, source_instance_id=SOURCE_INSTANCE)
    assert first.measurements[0].identity == second.measurements[0].identity
    assert first.measurements[0].identity_kind == "fallback_time"
    assert first.measurements[0].identity == delete_fallback_identity(
        SOURCE_INSTANCE, "synthetic-user-1", "2026-02-10T05:15:00+00:00"
    )
    assert first.measurements[0].metrics == ()


def test_semantic_fingerprint_sensitivity() -> None:
    """Adversarial case 10: fingerprint moves with time, metrics, algorithm."""

    base = dict(
        source_instance_id=SOURCE_INSTANCE,
        user_id="synthetic-user-1",
        measured_key="2026-02-10T08:15:00+00:00",
        metrics=[("weight", 76.4, "kg")],
        algorithm_identity="openscale-app-1",
        config_identity="config-a",
    )
    expected = semantic_fingerprint(**base)
    assert expected.startswith("fp:")
    changed_time = semantic_fingerprint(**{**base, "measured_key": "2026-02-11T08:15:00+00:00"})
    changed_metric = semantic_fingerprint(**{**base, "metrics": [("weight", 76.5, "kg")]})
    changed_algo = semantic_fingerprint(**{**base, "algorithm_identity": "openscale-app-2"})
    assert len({expected, changed_time, changed_metric, changed_algo}) == 4
    reordered_metrics = semantic_fingerprint(
        **{**base, "metrics": [("body_fat_pct", 24.5, "%"), ("weight", 76.4, "kg")]}
    )
    same_reordered = semantic_fingerprint(
        **{**base, "metrics": [("weight", 76.4, "kg"), ("body_fat_pct", 24.5, "%")]}
    )
    assert reordered_metrics == same_reordered
    # Username is not an input: no parameter exists for it by construction.
    import inspect

    assert "username" not in inspect.signature(semantic_fingerprint).parameters
    assert "payload" not in inspect.signature(semantic_fingerprint).parameters


def test_test_event_produces_no_measurements() -> None:
    """Adversarial case 11."""

    result = normalize_envelope(load_fixture("test.json"), source_instance_id=SOURCE_INSTANCE)
    assert result.ok
    assert result.is_control is True
    assert result.measurements == ()


def test_clear_is_control_not_zero_measurements() -> None:
    """Adversarial case 12."""

    result = normalize_envelope(load_fixture("clear.json"), source_instance_id=SOURCE_INSTANCE)
    assert result.ok
    assert result.is_control is True
    assert result.measurements == ()
    assert "weight" not in json.dumps(result.as_dict())


def test_fixture_insert_single_normalizes_deterministically() -> None:
    result = normalize_envelope(
        load_fixture("insert_single.json"), source_instance_id=SOURCE_INSTANCE
    )
    assert result.ok
    assert result.event == "insert"
    assert result.contract_version == OPENSCALE_CONTRACT_VERSION
    (measurement,) = result.measurements
    assert measurement.metric_codes() == (
        "body_fat_pct",
        "body_water_pct",
        "muscle_mass_kg",
        "weight",
    )
    assert measurement.precision == "instant"
    assert measurement.measured_at_utc is not None
    assert measurement.measured_at_utc.isoformat() == "2026-02-10T05:15:00+00:00"
    assert measurement.local_date.isoformat() == "2026-02-10"
    assert measurement.username == "Synthetic User"
    by_code = {item.metric_code: item for item in measurement.metrics}
    assert by_code["weight"].value == pytest.approx(76.4)
    assert by_code["body_fat_pct"].value == pytest.approx(24.5)


def test_fixture_batch_mixed_valid_unknown_and_date_only() -> None:
    result = normalize_envelope(
        load_fixture("batch_mixed.json"), source_instance_id=SOURCE_INSTANCE
    )
    assert result.ok
    assert len(result.measurements) == 2
    dated, timed = result.measurements
    assert dated.precision == "date"
    assert dated.measured_at_utc is None
    assert dated.local_date.isoformat() == "2026-02-10"
    assert timed.unknown_items and timed.unknown_items[0].key == "mysteryMetric"


def test_batch_conflicting_single_fields_fail_closed() -> None:
    payload = load_fixture("batch_mixed.json")
    payload["userId"] = "synthetic-user-1"
    result = normalize_envelope(payload, source_instance_id=SOURCE_INSTANCE)
    assert result.measurements == ()
    assert [item.reason_code for item in result.failures] == ["conflicting_single_and_batch"]


def test_batch_item_failure_quarantines_only_that_item() -> None:
    payload = {
        "event": "insert",
        "measurements": [
            {
                "id": "good-1",
                "userId": "synthetic-user-1",
                "date": "2026-02-10",
                "values": [weight_item(76.4)],
            },
            {"userId": "synthetic-user-1", "date": "not-a-date", "values": [weight_item(76.0)]},
        ],
    }
    result = normalize_envelope(payload, source_instance_id=SOURCE_INSTANCE)
    assert len(result.measurements) == 1
    assert result.measurements[0].record_id == "good-1"
    (quarantined,) = result.invalid_items
    assert quarantined.batch_index == 1
    assert quarantined.failures[0].reason_code == "invalid_datetime"


def test_values_absent_falls_back_to_convenience_without_zero_invention() -> None:
    present = normalize_envelope(
        single_measurement(weight=76.4), source_instance_id=SOURCE_INSTANCE
    )
    assert present.measurements[0].values_authoritative is False
    assert present.measurements[0].metric_codes() == ("weight",)
    missing = normalize_envelope(single_measurement(), source_instance_id=SOURCE_INSTANCE)
    assert missing.measurements[0].metric_codes() == ()
    zero = normalize_envelope(single_measurement(weight=0), source_instance_id=SOURCE_INSTANCE)
    assert zero.measurements[0].metric_codes() == ()


def test_unsupported_unit_never_converts() -> None:
    payload = single_measurement(values=[weight_item(168.0, unit="lb")])
    result = normalize_envelope(payload, source_instance_id=SOURCE_INSTANCE)
    assert result.measurements[0].metric_codes() == ()
    (unknown,) = result.measurements[0].unknown_items
    assert unknown.key == "weight"
    assert unknown.detail == "unknown_metric_key_or_unit"


def test_control_with_measurements_fails_closed() -> None:
    result = normalize_envelope(
        {"event": "clear", "measurements": [single_measurement()]},
        source_instance_id=SOURCE_INSTANCE,
    )
    assert result.measurements == ()
    assert [item.reason_code for item in result.failures] == [
        "conflicting_control_with_measurements"
    ]
