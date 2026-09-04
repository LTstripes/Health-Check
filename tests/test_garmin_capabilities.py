"""Offline R02 Garmin capability inventory and fixture-contract tests."""

from __future__ import annotations

import ast
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from healthcheck.garmin.capabilities import (
    CAPABILITY_CONTRACT_VERSION,
    CAPABILITY_MATRIX,
    GARMIN_CAPABILITY_INVENTORY,
    CapabilityStatus,
    DeviceSupport,
    capability_inventory,
    capability_matrix,
    get_capability,
    live_spike_questions,
)
from healthcheck.garmin.contracts import (
    CAPABILITY_FIXTURE_CONTRACT_VERSION,
    GarminCapabilityFixture,
    GarminCapabilityFixtureError,
    load_synthetic_fixture,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "garmin"

EXPECTED_CODES = (
    "sleep",
    "sleep_score",
    "sleep_stages",
    "naps",
    "heart_rate",
    "resting_heart_rate",
    "hrv_status",
    "stress",
    "body_battery",
    "spo2",
    "respiration",
    "vo2_max",
    "recovery_time",
    "training_readiness",
    "training_status",
    "unified_training_status",
    "training_effect",
    "acute_training_load",
    "activities",
    "cycling_metrics",
)


def fixture(name: str) -> GarminCapabilityFixture:
    return load_synthetic_fixture(FIXTURE_ROOT / f"{name}.json")


def test_inventory_is_static_and_complete() -> None:
    assert CAPABILITY_CONTRACT_VERSION == "r02-garmin-capability-contract-v1"
    assert GARMIN_CAPABILITY_INVENTORY.contract_version == CAPABILITY_CONTRACT_VERSION
    assert tuple(item.code for item in capability_inventory()) == EXPECTED_CODES
    assert CAPABILITY_MATRIX == GARMIN_CAPABILITY_INVENTORY.capabilities
    assert all(item.owner_account_verification == "not_run" for item in CAPABILITY_MATRIX)


def test_matrix_rows_keep_client_surface_separate_from_device_evidence() -> None:
    readiness = get_capability("training_readiness")
    status = get_capability("training_status")
    effect = get_capability("training_effect")
    load = get_capability("acute_training_load")

    assert readiness.client_methods == ("get_training_readiness",)
    assert readiness.device_support is DeviceSupport.NOT_SUPPORTED
    assert readiness.audit_status is CapabilityStatus.UNAVAILABLE
    assert status.client_methods == ("get_training_status",)
    assert status.audit_status is CapabilityStatus.NOT_DEVICE_PRODUCED
    assert effect.client_fields == ("trainingEffect",)
    assert effect.audit_status is CapabilityStatus.UNVERIFIED
    assert load.client_fields == ("trainingLoad",)
    assert load.audit_status is CapabilityStatus.UNVERIFIED
    assert all(not item.method_presence_is_device_evidence for item in CAPABILITY_MATRIX)


def test_capability_matrix_is_json_safe_and_preserves_unknown_live_state() -> None:
    rows = capability_matrix()
    assert len(rows) == len(EXPECTED_CODES)
    assert rows[0]["code"] == "sleep"
    assert rows[0]["audit_status"] == "verified"
    assert rows[0]["owner_account_verification"] == "not_run"
    assert rows[0]["method_presence_is_device_evidence"] is False
    json.dumps(rows)


def test_aliases_only_select_existing_rows() -> None:
    assert get_capability("HR").code == "heart_rate"
    assert get_capability("rhr").code == "resting_heart_rate"
    assert get_capability("training_load").code == "acute_training_load"
    with pytest.raises(KeyError):
        get_capability("does-not-exist")


def test_synthetic_sleep_fixture_contract() -> None:
    value = fixture("sleep")

    assert value.contract_version == CAPABILITY_FIXTURE_CONTRACT_VERSION
    assert value.device_attributed is True
    assert value.payload_field_present("sleep") is True
    assert value.payload_has_value("sleep_score") is True
    assert value.payload_has_value("naps") is True
    with pytest.raises(FrozenInstanceError):
        value.fixture_id = "mutated"
    assert value.as_dict()["device"] == {
        "attributed": True,
        "code": "garmin_vivoactive_5",
        "model": "Vivoactive 5",
    }


def test_synthetic_daily_fixture_keeps_null_and_present_distinct() -> None:
    value = fixture("daily_health")

    assert value.payload_field_present("training_readiness") is True
    assert value.payload_value("training_readiness") is None
    assert value.payload_has_value("training_readiness") is False
    assert value.payload_has_value("vo2_max") is True
    assert get_capability("training_readiness").audit_status is CapabilityStatus.UNAVAILABLE


def test_synthetic_activity_fixture_does_not_promote_typed_score_fields() -> None:
    value = fixture("activity")

    assert value.payload_has_value("activities") is True
    assert value.payload_has_value("training_effect") is True
    assert value.payload_has_value("acute_training_load") is True
    assert get_capability("training_effect").audit_status is CapabilityStatus.UNVERIFIED
    assert get_capability("acute_training_load").audit_status is CapabilityStatus.UNVERIFIED


def test_original_fit_recovery_fixture_remains_watch_only_and_unverified() -> None:
    value = fixture("original_fit")

    assert value.payload_field_present("recovery_time") is True
    assert value.payload_has_value("recovery_time") is False
    recovery = get_capability("recovery_time")
    assert recovery.device_support is DeviceSupport.WATCH_ONLY
    assert recovery.audit_status is CapabilityStatus.WATCH_ONLY
    assert recovery.client_methods == ()


def test_method_surface_fixture_has_no_device_evidence() -> None:
    value = fixture("method_surface_only")

    assert value.device_attributed is False
    assert value.device_code is None
    assert value.device_model is None
    assert value.payload_fields == {}
    assert value.client_methods == (
        "get_training_readiness",
        "get_training_status",
        "get_max_metrics",
    )
    assert not any(value.payload_has_value(code) for code in EXPECTED_CODES)
    assert get_capability("training_readiness").audit_status is CapabilityStatus.UNAVAILABLE


def test_unattributed_account_value_does_not_become_device_evidence() -> None:
    value = fixture("unattributed_account_value")

    assert value.device_attributed is False
    assert value.payload_has_value("training_status") is True
    assert get_capability("training_status").device_support is DeviceSupport.NOT_DEVICE_PRODUCED
    assert get_capability("training_status").audit_status is CapabilityStatus.NOT_DEVICE_PRODUCED


def test_all_checked_in_fixtures_are_synthetic_and_credential_free() -> None:
    fixture_paths = sorted(FIXTURE_ROOT.glob("*.json"))
    assert {path.stem for path in fixture_paths} == {
        "activity",
        "daily_health",
        "method_surface_only",
        "original_fit",
        "sleep",
        "unattributed_account_value",
    }
    for path in fixture_paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["source_kind"] == "synthetic"
        assert raw["fixture_id"].startswith("synthetic-")
        assert "token" not in json.dumps(raw).lower()
        load_synthetic_fixture(path)


def test_fixture_contract_rejects_live_or_private_shapes() -> None:
    raw = json.loads((FIXTURE_ROOT / "sleep.json").read_text(encoding="utf-8"))

    private = json.loads(json.dumps(raw))
    private["payload"]["access_token"] = "never-store-this"
    with pytest.raises(GarminCapabilityFixtureError, match="forbidden"):
        GarminCapabilityFixture.from_mapping(private)

    non_synthetic = json.loads(json.dumps(raw))
    non_synthetic["source_kind"] = "owner-live"
    with pytest.raises(GarminCapabilityFixtureError, match="synthetic"):
        GarminCapabilityFixture.from_mapping(non_synthetic)

    wrong_device = json.loads(json.dumps(raw))
    wrong_device["device"]["model"] = "Forerunner"
    with pytest.raises(GarminCapabilityFixtureError, match="model"):
        GarminCapabilityFixture.from_mapping(wrong_device)


def test_fixture_contract_rejects_unknown_or_absent_payload_fields() -> None:
    raw = json.loads((FIXTURE_ROOT / "sleep.json").read_text(encoding="utf-8"))

    unknown = json.loads(json.dumps(raw))
    unknown["payload_fields"]["made_up_metric"] = "sleepTimeSeconds"
    with pytest.raises(GarminCapabilityFixtureError, match="unknown capability"):
        GarminCapabilityFixture.from_mapping(unknown)

    absent = json.loads(json.dumps(raw))
    absent["payload_fields"]["sleep"] = "missing.path"
    with pytest.raises(GarminCapabilityFixtureError, match="absent"):
        GarminCapabilityFixture.from_mapping(absent)

    mismatch = json.loads(json.dumps(raw))
    mismatch["stream_code"] = "activity"
    with pytest.raises(GarminCapabilityFixtureError, match="stream mismatch"):
        GarminCapabilityFixture.from_mapping(mismatch)


def test_capability_contract_has_no_runtime_or_persistence_imports() -> None:
    for module_name in ("capabilities.py", "contracts.py"):
        source = (
            Path(__file__).parents[1] / "src" / "healthcheck" / "garmin" / module_name
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
            for alias in node.names
        )
        assert imports.isdisjoint({"garminconnect", "httpx", "requests", "sqlalchemy", "alembic"})


def test_future_live_spike_questions_are_explicit_and_deduplicated() -> None:
    questions = live_spike_questions()

    assert questions
    assert len(questions) == len(set(questions))
    assert any("backfill" in question.lower() for question in questions)
    assert any("original fit" in question.lower() for question in questions)
    assert any("mfa" in question.lower() for question in questions)
