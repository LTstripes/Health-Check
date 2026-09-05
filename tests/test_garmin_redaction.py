"""Synthetic Garmin shape and privacy-boundary tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from healthcheck import cli
from healthcheck.garmin.redaction import (
    GarminDeviceAttribution,
    GarminValueState,
    field_state_counts,
    garmin_value_state,
    infer_device_attribution,
    redact_garmin_payload,
    summarize_garmin_payload,
    validate_external_export_paths,
)

SYNTHETIC_PRIVATE_VALUE = "synthetic-health-value-never-exported"
SYNTHETIC_TOKEN = "synthetic-access-token-never-exported"
SYNTHETIC_ACTIVITY_ID = "987654321"


def _payload() -> dict[str, object]:
    return {
        "calendarDate": "2026-09-05",
        "heartRateValues": [0, 72],
        "value": SYNTHETIC_PRIVATE_VALUE,
        "accessToken": SYNTHETIC_TOKEN,
        "userId": SYNTHETIC_ACTIVITY_ID,
        "activityId": 987654321,
        "device": {
            "model": "Vivoactive 5",
            "serialNumber": "synthetic-device-serial",
        },
        "route": [{"latitude": 55.0, "longitude": 37.0}],
    }


def test_summary_contains_shape_only_and_redacts_private_keys() -> None:
    summary = summarize_garmin_payload(_payload())
    serialized = json.dumps(summary.as_dict(), ensure_ascii=True, sort_keys=True)

    assert summary.root_shape == "object"
    assert summary.value_state is GarminValueState.PRESENT
    assert summary.redacted_field_count >= 5
    assert "calendarDate" in summary.field_paths
    assert "accessToken" not in serialized
    assert SYNTHETIC_PRIVATE_VALUE not in serialized
    assert SYNTHETIC_TOKEN not in serialized
    assert SYNTHETIC_ACTIVITY_ID not in serialized
    assert "synthetic-device-serial" not in serialized


def test_redaction_export_is_value_free_even_for_safe_field_names() -> None:
    redacted = redact_garmin_payload(_payload())
    serialized = json.dumps(redacted, ensure_ascii=True, sort_keys=True)

    assert redacted["redaction_contract_version"] == "r02-garmin-redaction-v1"
    assert SYNTHETIC_PRIVATE_VALUE not in serialized
    assert SYNTHETIC_TOKEN not in serialized
    assert SYNTHETIC_ACTIVITY_ID not in serialized
    assert "accessToken" not in serialized
    assert "activityId" not in serialized
    assert "serialNumber" not in serialized
    assert '"key": "calendarDate"' in serialized
    assert '"key": "value"' in serialized


def test_zero_is_present_and_missing_null_empty_are_distinct() -> None:
    value = {"zero": 0, "empty": [], "null": None}

    assert garmin_value_state(0) is GarminValueState.PRESENT
    assert garmin_value_state([]) is GarminValueState.EMPTY
    assert field_state_counts(value, ("zero", "empty", "null", "missing")) == {
        "empty": 1,
        "missing": 1,
        "null": 1,
        "present": 1,
    }


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"device": {"model": "Vivoactive 5"}}, GarminDeviceAttribution.TARGET_DEVICE),
        ({"device": {"model": "Forerunner 265"}}, GarminDeviceAttribution.OTHER_DEVICE),
        ({"isDeviceAttributed": False}, GarminDeviceAttribution.UNATTRIBUTED),
        ({"device": {"model": "synthetic-device-marker"}}, GarminDeviceAttribution.UNKNOWN),
        ({}, GarminDeviceAttribution.UNATTRIBUTED),
    ],
)
def test_device_attribution_is_coarse_and_value_free(
    payload: dict[str, object], expected: GarminDeviceAttribution
) -> None:
    evidence = infer_device_attribution(payload)

    assert evidence.status is expected
    serialized = json.dumps(evidence.as_dict(), sort_keys=True)
    assert "Vivoactive" not in serialized
    assert "Forerunner" not in serialized
    assert "synthetic-device-marker" not in serialized


def test_shape_summary_is_bounded() -> None:
    summary = summarize_garmin_payload({"items": list(range(20))}, max_nodes=5, max_array_items=3)

    assert summary.truncated is True
    assert summary.item_count is None


def test_redaction_export_is_bounded() -> None:
    redacted = redact_garmin_payload(
        {"outer": {"inner": {"value": SYNTHETIC_PRIVATE_VALUE}}}, max_nodes=2
    )
    serialized = json.dumps(redacted, sort_keys=True)

    assert redacted["payload"]["truncated"] is True
    assert SYNTHETIC_PRIVATE_VALUE not in serialized


def test_redaction_paths_reject_checkout_local_input_or_output(tmp_path: Path) -> None:
    checkout = Path(__file__).resolve().parents[1]

    with pytest.raises(ValueError, match="outside the checkout"):
        validate_external_export_paths(checkout / "raw.json", tmp_path / "sanitized.json")
    with pytest.raises(ValueError, match="outside the checkout"):
        validate_external_export_paths(tmp_path / "raw.json", checkout / "sanitized.json")


def test_redaction_cli_writes_only_the_sanitized_external_shape(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "raw.json"
    output_path = tmp_path / "sanitized.json"
    input_path.write_text(json.dumps(_payload()), encoding="utf-8")

    assert (
        cli.main(
            [
                "garmin-redact",
                "--input",
                str(input_path),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )

    output = output_path.read_text(encoding="utf-8")
    assert SYNTHETIC_PRIVATE_VALUE not in output
    assert SYNTHETIC_TOKEN not in output
    assert "raw values were not copied" in capsys.readouterr().out
