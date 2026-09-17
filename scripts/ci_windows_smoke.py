"""Validate fail-closed evidence from the focused Windows smoke job."""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ContractError(ValueError):
    """Raised when Windows smoke evidence is missing or inconsistent."""


@dataclass(frozen=True)
class ExpectedWorkflowIdentity:
    event_name: str
    ref: str
    pr_base_ref: str
    pr_base_sha: str
    pr_head_ref: str
    pr_head_sha: str


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"missing, unreadable, or malformed JSON artifact: {path}") from error


def _validate_workflow_identity(identity: ExpectedWorkflowIdentity) -> None:
    _require(identity.event_name in {"push", "pull_request"}, "unsupported workflow event")
    if identity.event_name == "push":
        _require(
            re.fullmatch(r"refs/(?:heads|tags)/[^\s]+", identity.ref) is not None,
            "push workflow ref is malformed",
        )
        _require(
            not any(
                (
                    identity.pr_base_ref,
                    identity.pr_base_sha,
                    identity.pr_head_ref,
                    identity.pr_head_sha,
                )
            ),
            "push workflow identity must have empty PR fields",
        )
        return
    _require(
        re.fullmatch(r"refs/pull/[1-9][0-9]*/merge", identity.ref) is not None,
        "pull_request workflow ref is malformed",
    )
    for value in (identity.pr_base_ref, identity.pr_head_ref):
        _require(bool(value) and re.fullmatch(r"[^\s]+", value) is not None, "PR ref is malformed")
    for value in (identity.pr_base_sha, identity.pr_head_sha):
        _require(re.fullmatch(r"[0-9a-f]{40}", value) is not None, "PR SHA is malformed")


def _one_directory(root: Path, pattern: str, message: str) -> Path:
    matches = [path for path in root.glob(pattern) if path.is_dir()]
    _require(len(matches) == 1, f"{message}: found {len(matches)}")
    return matches[0]


def _junit_counts(path: Path) -> dict[str, int]:
    try:
        root = ET.fromstring(path.read_bytes())
    except (OSError, ET.ParseError) as error:
        raise ContractError(f"missing, unreadable, or malformed DPAPI JUnit: {path}") from error
    suites = list(root.findall("./testsuite")) if root.tag == "testsuites" else [root]
    try:
        counts = {
            name: sum(int(suite.attrib.get(name, "0")) for suite in suites)
            for name in ("tests", "failures", "errors", "skipped")
        }
    except (TypeError, ValueError) as error:
        raise ContractError("DPAPI JUnit counts are malformed") from error
    _require(
        counts == {"tests": 1, "failures": 0, "errors": 0, "skipped": 0},
        "DPAPI evidence is not exactly one passed test",
    )
    return counts


def _positive_unique_ids(value: Any, message: str) -> None:
    _require(isinstance(value, list), message)
    _require(
        all(isinstance(item, int) and not isinstance(item, bool) and item > 0 for item in value),
        message,
    )
    _require(len(value) == len(set(value)), message)


def _validate_scenario(scenario: Any, expected_name: str) -> None:
    _require(isinstance(scenario, dict), f"Windows scenario {expected_name} is malformed")
    _require(scenario.get("name") == expected_name, f"Windows scenario {expected_name} is missing")
    _require(scenario.get("status") == "passed", f"Windows scenario {expected_name} did not pass")
    runtime = scenario.get("runtime")
    _require(
        isinstance(runtime, dict)
        and runtime.get("outside_checkout") is True
        and runtime.get("path_contains_spaces") is True
        and runtime.get("removed") is True
        and isinstance(runtime.get("path"), str)
        and bool(re.search(r"\s", runtime["path"])),
        f"Windows scenario {expected_name} runtime evidence is incomplete",
    )
    surfaces = scenario.get("surfaces")
    _require(
        isinstance(surfaces, dict)
        and surfaces.get("ui_host") == "127.0.0.1"
        and surfaces.get("ingest_host") == "127.0.0.1"
        and isinstance(surfaces.get("ui_health"), dict)
        and surfaces["ui_health"].get("status_code") == 200
        and surfaces["ui_health"].get("body") == {"service": "loopback-ui", "status": "ok"},
        f"Windows scenario {expected_name} UI evidence is incomplete",
    )
    cleanup = scenario.get("cleanup")
    _require(
        isinstance(cleanup, dict)
        and cleanup.get("scope") == "verified-root-process-tree-only"
        and isinstance(cleanup.get("root_pid"), int)
        and cleanup["root_pid"] > 0
        and cleanup.get("root_identity_verified") is True
        and cleanup.get("termination") == "taskkill /PID <verified-root> /T /F"
        and isinstance(cleanup.get("ports_closed"), dict)
        and cleanup["ports_closed"].get("ui") is True
        and cleanup["ports_closed"].get("ingest") is True
        and cleanup.get("remaining_owned_process_ids") == []
        and cleanup.get("errors") == [],
        f"Windows scenario {expected_name} cleanup evidence is incomplete",
    )
    _positive_unique_ids(
        cleanup.get("identity_changed_process_ids"),
        f"Windows scenario {expected_name} identity-change evidence is invalid",
    )
    if expected_name == "ingest-disabled":
        _require(
            surfaces.get("ingest_health") is None
            and surfaces.get("ingest_port_closed_before_start") is True,
            "disabled-ingest scenario evidence is invalid",
        )
    else:
        _require(
            isinstance(surfaces.get("ingest_health"), dict)
            and surfaces["ingest_health"].get("status_code") == 200
            and surfaces["ingest_health"].get("body") == {"service": "ingest", "status": "ok"}
            and surfaces.get("ui_ingest_route_status") == 404
            and surfaces.get("ingest_openscale_get_status") == 405,
            "enabled-ingest route separation evidence is invalid",
        )


def validate_windows_smoke_artifact(
    artifacts_root: Path,
    *,
    job_result: str,
    head_sha: str,
    tree_sha: str,
    workflow_identity: ExpectedWorkflowIdentity,
) -> dict[str, Any]:
    _require(job_result == "success", f"mandatory Windows smoke job result is {job_result}")
    _validate_workflow_identity(workflow_identity)
    artifact = _one_directory(
        artifacts_root, "ci-windows-smoke-*", "missing Windows smoke artifact"
    )
    _require(
        re.fullmatch(r"ci-windows-smoke-[0-9]+-[0-9]+", artifact.name) is not None,
        "malformed Windows smoke artifact directory",
    )
    required = ("smoke-evidence.json", "cleanup.json", "dpapi.junit.xml", "dpapi.log")
    for name in required:
        _require((artifact / name).is_file(), f"missing Windows smoke report: {name}")
    for scenario_name in ("ingest-disabled", "ingest-enabled"):
        for log_name in ("start.stdout.log", "start.stderr.log"):
            _require(
                (artifact / scenario_name / log_name).is_file(),
                f"missing Windows scenario report: {scenario_name}/{log_name}",
            )

    evidence = _load_json(artifact / "smoke-evidence.json")
    _require(isinstance(evidence, dict), "Windows smoke evidence must be an object")
    _require(evidence.get("schema_version") == 2, "Windows smoke schema_version must be integer 2")
    _require(evidence.get("status") == "passed", "Windows smoke status is not passed")
    _require(evidence.get("platform") == "win32", "Windows smoke platform mismatch")
    _require(evidence.get("runner") == "Windows/X64", "Windows smoke runner mismatch")
    for field, expected in (
        ("head_sha", head_sha),
        ("tree_sha", tree_sha),
        ("event_name", workflow_identity.event_name),
        ("ref", workflow_identity.ref),
        ("pr_base_ref", workflow_identity.pr_base_ref),
        ("pr_base_sha", workflow_identity.pr_base_sha),
        ("pr_head_ref", workflow_identity.pr_head_ref),
        ("pr_head_sha", workflow_identity.pr_head_sha),
    ):
        _require(evidence.get(field) == expected, f"Windows smoke {field} provenance mismatch")
    _require(evidence.get("checked_out_head") == head_sha, "Windows checked-out HEAD mismatch")
    _require(evidence.get("checked_out_tree") == tree_sha, "Windows checked-out tree mismatch")
    _require(evidence.get("git_clean") is True, "Windows smoke checkout was not clean")
    _require(
        not evidence.get("process_snapshot_error"),
        "Windows process identity evidence is incomplete",
    )

    runtime = evidence.get("runtime")
    _require(
        isinstance(runtime, dict)
        and runtime.get("outside_checkout") is True
        and runtime.get("path_contains_spaces") is True
        and runtime.get("removed") is True,
        "Windows smoke runtime provenance is not fail-closed",
    )
    scenarios = evidence.get("scenarios")
    _require(isinstance(scenarios, list) and len(scenarios) == 2, "Windows scenarios are missing")
    scenario_map = {
        scenario.get("name"): scenario for scenario in scenarios if isinstance(scenario, dict)
    }
    _require(
        set(scenario_map) == {"ingest-disabled", "ingest-enabled"},
        "Windows scenario names are invalid",
    )
    _validate_scenario(scenario_map["ingest-disabled"], "ingest-disabled")
    _validate_scenario(scenario_map["ingest-enabled"], "ingest-enabled")
    _require(
        evidence.get("http") == scenario_map["ingest-disabled"]["surfaces"]["ui_health"],
        "legacy UI HTTP evidence mismatch",
    )

    dpapi = evidence.get("dpapi")
    _require(
        isinstance(dpapi, dict)
        and dpapi.get("nodeid")
        == (
            "tests/test_garmin_auth.py::"
            "test_windows_user_scoped_protection_round_trips_and_rejects_owner_tampering"
        )
        and dpapi.get("outcome") == "passed",
        "native DPAPI test outcome is missing or not passed",
    )
    _require(
        dpapi.get("counts") == _junit_counts(artifact / "dpapi.junit.xml"),
        "DPAPI evidence counts do not match JUnit",
    )

    cleanup = evidence.get("cleanup")
    retained_cleanup = _load_json(artifact / "cleanup.json")
    _require(cleanup == retained_cleanup, "retained cleanup evidence does not match smoke evidence")
    _require(
        isinstance(cleanup, dict)
        and cleanup.get("scope") == "verified-root-process-tree-only"
        and isinstance(cleanup.get("root_pid"), int)
        and cleanup["root_pid"] > 0
        and isinstance(cleanup.get("started_process_ids"), list)
        and cleanup["root_pid"] in cleanup["started_process_ids"]
        and cleanup.get("remaining_owned_process_ids") == []
        and cleanup.get("errors") == [],
        "process cleanup evidence is missing or not clean",
    )
    _positive_unique_ids(
        cleanup.get("identity_changed_process_ids"),
        "process cleanup identity-change evidence is invalid",
    )
    _require(
        isinstance(cleanup.get("scenarios"), list)
        and len(cleanup["scenarios"]) == 2,
        "per-scenario cleanup evidence is missing",
    )
    _require(
        isinstance(evidence.get("powershell"), dict)
        and bool(evidence["powershell"].get("version")),
        "PowerShell execution evidence is missing",
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--job-result", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--tree-sha", required=True)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--pr-base-ref", required=True)
    parser.add_argument("--pr-base-sha", required=True)
    parser.add_argument("--pr-head-ref", required=True)
    parser.add_argument("--pr-head-sha", required=True)
    args = parser.parse_args()
    try:
        validate_windows_smoke_artifact(
            args.artifacts_root,
            job_result=args.job_result,
            head_sha=args.head_sha,
            tree_sha=args.tree_sha,
            workflow_identity=ExpectedWorkflowIdentity(
                event_name=args.event_name,
                ref=args.ref,
                pr_base_ref=args.pr_base_ref,
                pr_base_sha=args.pr_base_sha,
                pr_head_ref=args.pr_head_ref,
                pr_head_sha=args.pr_head_sha,
            ),
        )
    except ContractError as error:
        print(f"WINDOWS_SMOKE_EVIDENCE_FAILURE: {error}", file=sys.stderr)
        return 1
    print("WINDOWS_SMOKE_EVIDENCE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
