import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SMOKE_HELPER_PATH = Path(__file__).parents[1] / "scripts" / "ci_windows_smoke.py"
_SMOKE_SPEC = importlib.util.spec_from_file_location("ci_windows_smoke", _SMOKE_HELPER_PATH)
assert _SMOKE_SPEC is not None and _SMOKE_SPEC.loader is not None
_SMOKE_HELPER = importlib.util.module_from_spec(_SMOKE_SPEC)
sys.modules[_SMOKE_SPEC.name] = _SMOKE_HELPER
_SMOKE_SPEC.loader.exec_module(_SMOKE_HELPER)

ContractError = _SMOKE_HELPER.ContractError
ExpectedWorkflowIdentity = _SMOKE_HELPER.ExpectedWorkflowIdentity
validate_windows_smoke_artifact = _SMOKE_HELPER.validate_windows_smoke_artifact

WORKFLOW = (Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml").read_text(
    encoding="utf-8"
)
LANE_HELPER = (Path(__file__).parents[1] / "scripts" / "ci_test_lanes.py").read_text(
    encoding="utf-8"
)


def _job(name: str, next_name: str | None = None) -> str:
    section = WORKFLOW.split(f"  {name}:\n", 1)[1]
    return section if next_name is None else section.split(f"  {next_name}:\n", 1)[0]


def test_ci_keeps_push_pull_request_and_lane_scoped_cancellation():
    assert "  push:\n" in WORKFLOW
    assert "  pull_request:\n" in WORKFLOW
    assert "format('ci-pr-{0}', github.event.pull_request.number)" in WORKFLOW
    assert "format('ci-task-{0}', github.ref)" in WORKFLOW
    assert "format('ci-run-{0}', github.run_id)" in WORKFLOW
    assert "format('ci-push-{0}', github.ref)" not in WORKFLOW
    assert (
        "cancel-in-progress: ${{ github.event_name == 'pull_request' || "
        "(github.event_name == 'push' && startsWith(github.ref, 'refs/heads/task/')) }}"
    ) in WORKFLOW


def test_quality_and_three_serial_lanes_are_independent_and_locked():
    quality = _job("quality", "test")
    test = _job("test", "checks")

    assert "needs:" not in quality
    assert "needs:" not in test
    assert "uv sync --locked" in quality
    assert "uv sync --locked" in test
    assert "uv run ruff check ." in quality
    assert "healthcheck.db.migration_guard" in quality
    assert "validate-manifest" in quality
    assert 'collect --output-dir "$quality_dir"' in quality
    assert "fail-fast: false" in test
    assert "- garmin\n" in test
    assert "- core-sleep\n" in test
    assert "- app-ingest\n" in test
    assert "run-lane" in test
    assert "pytest-$LANE-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT" in test
    assert "HEALTHCHECK_DATA_DIR:" in test
    assert "xdist" not in WORKFLOW


def test_windows_smoke_is_focused_and_is_required_by_the_final_gate():
    windows = _job("windows-smoke", "checks")
    checks = _job("checks")

    assert "runs-on: windows-latest" in windows
    assert "shell: pwsh" in windows
    assert "scripts/ci_windows_smoke.ps1" in windows
    assert "tests/test_ci_windows_process.ps1" in windows
    smoke_script = (Path(__file__).parents[1] / "scripts" / "ci_windows_smoke.ps1").read_text(
        encoding="utf-8"
    )
    assert "test_garmin_auth.py::test_windows_user_scoped_protection_round_trips" in smoke_script
    assert "ingest-disabled" in smoke_script
    assert "ingest-enabled" in smoke_script
    assert "taskkill.exe" in (
        Path(__file__).parents[1] / "scripts" / "ci_windows_process.ps1"
    ).read_text(encoding="utf-8")
    assert "full pytest" not in windows.lower()
    assert "xdist" not in windows
    assert "      - windows-smoke\n" in checks
    assert "WINDOWS_RESULT: ${{ needs.windows-smoke.result }}" in checks
    assert "scripts/ci_windows_smoke.py" in checks
    assert "native DPAPI" in (
        Path(__file__).parents[1] / "scripts" / "ci_windows_smoke.py"
    ).read_text(encoding="utf-8")


def test_lane_artifacts_keep_timing_junit_metadata_and_distinct_provenance():
    test = _job("test", "checks")

    assert "--durations=25" in LANE_HELPER
    assert "--durations-min=1.0" in LANE_HELPER
    assert "--junitxml=" in LANE_HELPER
    assert "lane-evidence.json" in LANE_HELPER
    assert "pytest-status.txt" in LANE_HELPER
    assert "verify-lane" in test
    assert "if: always()" in test
    assert "set -euo pipefail" in test
    assert 'cat "$lane_dir/metadata.md"' in test
    assert "ci-lane-${{ matrix.lane }}-${{ github.run_id }}-${{ github.run_attempt }}" in test
    assert "if-no-files-found: error" in test
    assert "retention-days: 14" in test
    assert "git status --porcelain=v2 --branch --untracked-files=all" in test
    assert "selection SHA-256" in test


def test_checks_is_stable_always_and_requires_status_plus_all_artifacts():
    checks = _job("checks")

    assert checks.startswith("    if: always()\n")
    assert "      - quality\n" in checks
    assert "      - test\n" in checks
    assert "actions/download-artifact@v4" in checks
    assert "merge-multiple: false" in checks
    assert "QUALITY_RESULT: ${{ needs.quality.result }}" in checks
    assert "TEST_RESULT: ${{ needs.test.result }}" in checks
    assert "Fail-closed final verdict" in checks
    assert "scripts/ci_test_lanes.py gate" in checks
    assert '--head-sha "$(git rev-parse HEAD)"' in checks
    assert "--tree-sha \"$(git rev-parse 'HEAD^{tree}')\"" in checks
    assert "EXPECTED_EVENT_NAME: ${{ github.event_name }}" in checks
    assert "EXPECTED_REF: ${{ github.ref }}" in checks
    assert "EXPECTED_PR_BASE_REF: ${{ github.base_ref }}" in checks
    assert "EXPECTED_PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}" in checks
    assert "EXPECTED_PR_HEAD_REF: ${{ github.head_ref }}" in checks
    assert "EXPECTED_PR_HEAD_SHA: ${{ github.event.pull_request.head.sha }}" in checks
    assert '--event-name "$EXPECTED_EVENT_NAME"' in checks
    assert '--ref "$EXPECTED_REF"' in checks
    assert '--pr-base-ref "$EXPECTED_PR_BASE_REF"' in checks
    assert '--pr-base-sha "$EXPECTED_PR_BASE_SHA"' in checks
    assert '--pr-head-ref "$EXPECTED_PR_HEAD_REF"' in checks
    assert '--pr-head-sha "$EXPECTED_PR_HEAD_SHA"' in checks
    assert "--expected-platform linux" in checks


def test_workflow_has_no_per_candidate_fourth_serial_suite():
    assert WORKFLOW.count("run-lane") == 1
    assert "uv run pytest" not in WORKFLOW
    assert "full pytest" not in WORKFLOW.lower()


def test_checks_enforces_full_rerun_only_before_content_verdicts():
    checks = _job("checks")
    assert "pattern: ci-*-${{ github.run_id }}-${{ github.run_attempt }}" in checks
    assert "scripts/ci_test_lanes.py verify-attempt" in checks
    assert '--run-id "$GITHUB_RUN_ID" --attempt "$GITHUB_RUN_ATTEMPT"' in checks
    assert 'if [ "$attempt_status" -ne 0 ]' in checks


def _windows_smoke_fixture(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "artifacts"
    artifact = root / "ci-windows-smoke-123-1"
    artifact.mkdir(parents=True)
    head = "a" * 40
    tree = "b" * 40

    def scenario(name: str, root_pid: int, runtime_path: str, identity_changed: list[int]):
        surfaces = {
            "ui_host": "127.0.0.1",
            "ui_port": 8120,
            "ingest_host": "127.0.0.1",
            "ingest_port": 8121,
            "ui_health": {
                "host": "127.0.0.1",
                "path": "/healthz",
                "status_code": 200,
                "body": {"service": "loopback-ui", "status": "ok"},
            },
            "ingest_health": None,
            "ui_ingest_route_status": None,
            "ingest_openscale_get_status": None,
            "ingest_port_closed_before_start": True,
        }
        if name == "ingest-enabled":
            surfaces["ingest_health"] = {
                "host": "127.0.0.1",
                "path": "/healthz",
                "status_code": 200,
                "body": {"service": "ingest", "status": "ok"},
            }
            surfaces["ui_ingest_route_status"] = 404
            surfaces["ingest_openscale_get_status"] = 405
        return {
            "name": name,
            "status": "passed",
            "failure": None,
            "runtime": {
                "path": runtime_path,
                "outside_checkout": True,
                "path_contains_spaces": True,
                "removed": True,
            },
            "surfaces": surfaces,
            "cleanup": {
                "scope": "verified-root-process-tree-only",
                "root_pid": root_pid,
                "root_name": "pwsh.exe",
                "root_command_line": "start.ps1 -DataDir synthetic",
                "root_creation_time": "637134336000000000",
                "root_identity_verified": True,
                "termination": "taskkill /PID <verified-root> /T /F",
                "termination_issued": True,
                "root_already_exited": False,
                "termination_outcome": "terminated",
                "taskkill_exit_code": 0,
                "taskkill_output": ["synthetic native success"],
                "lifecycle_diagnostic_verified": False,
                "owned_process_identities": [
                    {
                        "Id": root_pid,
                        "Name": "pwsh.exe",
                        "CommandLine": "start.ps1 -DataDir synthetic",
                        "CreationTime": "637134336000000000",
                    }
                ],
                "remaining_owned_process_ids": [],
                "identity_changed_process_ids": identity_changed,
                "ports_closed": {"ui": True, "ingest": True},
                "errors": [],
            },
        }

    disabled = scenario("ingest-disabled", 101, r"C:\Temp\Health Check disabled", [])
    enabled = scenario("ingest-enabled", 202, r"C:\Temp\Health Check enabled", [])
    cleanup = {
        "scope": "verified-root-process-tree-only",
        "root_pid": 101,
        "started_process_ids": [101, 202],
        "terminated_process_ids": [101, 202],
        "remaining_owned_process_ids": [],
        "identity_changed_process_ids": [],
        "errors": [],
        "scenarios": [disabled["cleanup"], enabled["cleanup"]],
    }
    evidence = {
        "schema_version": 3,
        "status": "passed",
        "failure": None,
        "platform": "win32",
        "runner": "Windows/X64",
        "head_sha": head,
        "tree_sha": tree,
        "event_name": "push",
        "ref": "refs/heads/task/125-ci-windows-smoke",
        "pr_base_ref": "",
        "pr_base_sha": "",
        "pr_head_ref": "",
        "pr_head_sha": "",
        "checked_out_head": head,
        "checked_out_tree": tree,
        "git_clean": True,
        "powershell": {"version": "7.5.0"},
        "runtime": {"outside_checkout": True, "path_contains_spaces": True, "removed": True},
        "http": disabled["surfaces"]["ui_health"],
        "scenarios": [disabled, enabled],
        "dpapi": {
            "nodeid": (
                "tests/test_garmin_auth.py::"
                "test_windows_user_scoped_protection_round_trips_and_rejects_owner_tampering"
            ),
            "outcome": "passed",
            "counts": {"tests": 1, "failures": 0, "errors": 0, "skipped": 0},
        },
        "cleanup": cleanup,
        "process_snapshot_error": None,
    }
    (artifact / "smoke-evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
    (artifact / "cleanup.json").write_text(json.dumps(cleanup), encoding="utf-8")
    (artifact / "dpapi.junit.xml").write_text(
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase classname="tests.test_garmin_auth" name="native_dpapi" />'
        "</testsuite>",
        encoding="utf-8",
    )
    (artifact / "dpapi.log").write_text("1 passed, 0 skipped\n", encoding="utf-8")
    for scenario_name in ("ingest-disabled", "ingest-enabled"):
        scenario_dir = artifact / scenario_name
        scenario_dir.mkdir()
        for name in ("start.stdout.log", "start.stderr.log"):
            (scenario_dir / name).write_text("synthetic evidence\n", encoding="utf-8")
    return root, head, tree


def test_windows_smoke_validator_accepts_complete_bound_evidence(tmp_path: Path):
    root, head, tree = _windows_smoke_fixture(tmp_path)
    result = validate_windows_smoke_artifact(
        root,
        job_result="success",
        head_sha=head,
        tree_sha=tree,
        workflow_identity=ExpectedWorkflowIdentity(
            event_name="push",
            ref="refs/heads/task/125-ci-windows-smoke",
            pr_base_ref="",
            pr_base_sha="",
            pr_head_ref="",
            pr_head_sha="",
        ),
    )
    assert result["dpapi"]["counts"]["skipped"] == 0
    assert result["cleanup"]["identity_changed_process_ids"] == []


def test_windows_smoke_validator_rejects_remaining_owned_process(tmp_path: Path):
    root, head, tree = _windows_smoke_fixture(tmp_path)
    artifact = root / "ci-windows-smoke-123-1"
    evidence_path = artifact / "smoke-evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["cleanup"]["remaining_owned_process_ids"] = [90]
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    cleanup_path = artifact / "cleanup.json"
    cleanup = json.loads(cleanup_path.read_text(encoding="utf-8"))
    cleanup["remaining_owned_process_ids"] = [90]
    cleanup_path.write_text(json.dumps(cleanup), encoding="utf-8")
    with pytest.raises(ContractError, match="process cleanup evidence"):
        validate_windows_smoke_artifact(
            root,
            job_result="success",
            head_sha=head,
            tree_sha=tree,
            workflow_identity=ExpectedWorkflowIdentity(
                event_name="push",
                ref="refs/heads/task/125-ci-windows-smoke",
                pr_base_ref="",
                pr_base_sha="",
                pr_head_ref="",
                pr_head_sha="",
            ),
        )


def test_windows_smoke_validator_rejects_invalid_identity_change_list(tmp_path: Path):
    root, head, tree = _windows_smoke_fixture(tmp_path)
    artifact = root / "ci-windows-smoke-123-1"
    evidence_path = artifact / "smoke-evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["cleanup"]["identity_changed_process_ids"] = [0, 0]
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    cleanup_path = artifact / "cleanup.json"
    cleanup = json.loads(cleanup_path.read_text(encoding="utf-8"))
    cleanup["identity_changed_process_ids"] = [0, 0]
    cleanup_path.write_text(json.dumps(cleanup), encoding="utf-8")
    with pytest.raises(ContractError, match="identity-change evidence"):
        validate_windows_smoke_artifact(
            root,
            job_result="success",
            head_sha=head,
            tree_sha=tree,
            workflow_identity=ExpectedWorkflowIdentity(
                event_name="push",
                ref="refs/heads/task/125-ci-windows-smoke",
                pr_base_ref="",
                pr_base_sha="",
                pr_head_ref="",
                pr_head_sha="",
            ),
        )


def test_windows_smoke_validator_rejects_failed_scenario(tmp_path: Path):
    root, head, tree = _windows_smoke_fixture(tmp_path)
    artifact = root / "ci-windows-smoke-123-1"
    evidence_path = artifact / "smoke-evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["scenarios"][0]["status"] = "failed"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(ContractError, match="scenario ingest-disabled did not pass"):
        validate_windows_smoke_artifact(
            root,
            job_result="success",
            head_sha=head,
            tree_sha=tree,
            workflow_identity=ExpectedWorkflowIdentity(
                event_name="push",
                ref="refs/heads/task/125-ci-windows-smoke",
                pr_base_ref="",
                pr_base_sha="",
                pr_head_ref="",
                pr_head_sha="",
            ),
        )


def test_windows_smoke_validator_rejects_cleanup_error(tmp_path: Path):
    root, head, tree = _windows_smoke_fixture(tmp_path)
    artifact = root / "ci-windows-smoke-123-1"
    evidence_path = artifact / "smoke-evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["cleanup"]["errors"] = ["synthetic cleanup failure"]
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    cleanup_path = artifact / "cleanup.json"
    cleanup = json.loads(cleanup_path.read_text(encoding="utf-8"))
    cleanup["errors"] = ["synthetic cleanup failure"]
    cleanup_path.write_text(json.dumps(cleanup), encoding="utf-8")
    with pytest.raises(ContractError, match="process cleanup evidence"):
        validate_windows_smoke_artifact(
            root,
            job_result="success",
            head_sha=head,
            tree_sha=tree,
            workflow_identity=ExpectedWorkflowIdentity(
                event_name="push",
                ref="refs/heads/task/125-ci-windows-smoke",
                pr_base_ref="",
                pr_base_sha="",
                pr_head_ref="",
                pr_head_sha="",
            ),
        )


@pytest.mark.parametrize("job_result", ("failure", "cancelled", "skipped"))
def test_windows_smoke_validator_rejects_non_success_job(tmp_path: Path, job_result: str):
    root, head, tree = _windows_smoke_fixture(tmp_path)
    with pytest.raises(ContractError, match="job result"):
        validate_windows_smoke_artifact(
            root,
            job_result=job_result,
            head_sha=head,
            tree_sha=tree,
            workflow_identity=ExpectedWorkflowIdentity(
                event_name="push",
                ref="refs/heads/task/125-ci-windows-smoke",
                pr_base_ref="",
                pr_base_sha="",
                pr_head_ref="",
                pr_head_sha="",
            ),
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "safe",
        "access_denied",
        "empty_output",
        "unknown_pid",
        "live_child",
        "reused_child",
        "missing_tree",
        "missing_creation",
        "other_exit",
    ),
)
def test_windows_cleanup_lifecycle_contract(tmp_path, mutation):
    root, head, tree = _windows_smoke_fixture(tmp_path)
    artifact = root / "ci-windows-smoke-123-1"
    evidence = json.loads((artifact / "smoke-evidence.json").read_text())
    cleanup = evidence["scenarios"][1]["cleanup"]
    cleanup.update(
        termination_outcome="exited-during-termination",
        taskkill_exit_code=255,
        lifecycle_diagnostic_verified=True,
        taskkill_output=[
            "ERROR: The process with PID 202 (child process of PID 1) could not be terminated.",
            "Reason: There is no running instance of the task.",
        ],
    )
    if mutation == "access_denied":
        cleanup["taskkill_output"][1] = "Reason: Access is denied."
    elif mutation == "empty_output":
        cleanup["taskkill_output"] = []
    elif mutation == "unknown_pid":
        cleanup["taskkill_output"][0] = cleanup["taskkill_output"][0].replace("202", "303")
    elif mutation == "live_child":
        cleanup["remaining_owned_process_ids"] = [303]
    elif mutation == "reused_child":
        cleanup["identity_changed_process_ids"] = [303]
    elif mutation == "missing_tree":
        cleanup["owned_process_identities"] = []
    elif mutation == "missing_creation":
        cleanup["owned_process_identities"][0]["CreationTime"] = ""
    elif mutation == "other_exit":
        cleanup["taskkill_exit_code"] = 5
    evidence["cleanup"]["scenarios"][1] = cleanup
    (artifact / "smoke-evidence.json").write_text(json.dumps(evidence))
    (artifact / "cleanup.json").write_text(json.dumps(evidence["cleanup"]))
    kwargs = dict(
        job_result="success",
        head_sha=head,
        tree_sha=tree,
        workflow_identity=ExpectedWorkflowIdentity(
            "push", "refs/heads/task/125-ci-windows-smoke", "", "", "", ""
        ),
    )
    if mutation == "safe":
        validate_windows_smoke_artifact(root, **kwargs)
    else:
        with pytest.raises(ContractError):
            validate_windows_smoke_artifact(root, **kwargs)


_EXACT_ERROR = "ERROR: The process with PID 202 (child process of PID 1) could not be terminated."
_EXACT_REASON = "Reason: There is no running instance of the task."
_EXACT_SUCCESS = "SUCCESS: The process with PID 203 (child process of PID 202) has been terminated."
_LIFECYCLE_TRANSCRIPTS = {
    "valid": [_EXACT_ERROR, _EXACT_REASON, _EXACT_SUCCESS],
    "valid_native_order": [_EXACT_SUCCESS, _EXACT_ERROR, _EXACT_REASON],
    "valid_all_errors": [
        _EXACT_ERROR,
        _EXACT_REASON,
        "ERROR: The process with PID 203 (child process of PID 202) could not be terminated.",
        _EXACT_REASON,
    ],
    "missing_record": [_EXACT_ERROR, _EXACT_REASON],
    "reason_trailing": [_EXACT_ERROR, _EXACT_REASON + " UNRECOGNIZED_DIAGNOSTIC", _EXACT_SUCCESS],
    "unknown_line": [_EXACT_ERROR, _EXACT_REASON, _EXACT_SUCCESS, "UNRECOGNIZED_DIAGNOSTIC"],
    "malformed_success": [
        _EXACT_ERROR,
        _EXACT_REASON,
        "SUCCESS: The process with PID 203 nonsense",
    ],
    "incomplete_error": [_EXACT_ERROR, _EXACT_SUCCESS],
    "malformed_reason": [_EXACT_ERROR, _EXACT_REASON[:-1], _EXACT_SUCCESS],
    "malformed_error": [
        "ERROR: The process with PID 202 nonsense could not be terminated.",
        _EXACT_REASON,
        _EXACT_SUCCESS,
    ],
    "duplicate_success": [_EXACT_ERROR, _EXACT_REASON, _EXACT_SUCCESS, _EXACT_SUCCESS],
    "duplicate_error": [_EXACT_ERROR, _EXACT_REASON, _EXACT_ERROR, _EXACT_REASON, _EXACT_SUCCESS],
    "unexpected_record": [
        _EXACT_ERROR,
        _EXACT_REASON,
        _EXACT_SUCCESS,
        "SUCCESS: The process with PID 204 (child process of PID 202) has been terminated.",
    ],
    "error_trailing": [_EXACT_ERROR + " garbage", _EXACT_REASON, _EXACT_SUCCESS],
    "success_trailing": [_EXACT_ERROR, _EXACT_REASON, _EXACT_SUCCESS + " garbage"],
    "orphan_reason": [_EXACT_ERROR, _EXACT_REASON, _EXACT_SUCCESS, _EXACT_REASON],
    "blank_line": [_EXACT_ERROR, _EXACT_REASON, "", _EXACT_SUCCESS],
    "case_changed": [_EXACT_ERROR.lower(), _EXACT_REASON, _EXACT_SUCCESS],
    "embedded_newline": [_EXACT_ERROR, _EXACT_REASON, _EXACT_SUCCESS + "\nUNKNOWN"],
    "trailing_newline": [_EXACT_ERROR, _EXACT_REASON + "\n", _EXACT_SUCCESS],
    "trailing_carriage_return": [_EXACT_ERROR, _EXACT_REASON + "\r", _EXACT_SUCCESS],
    "success_only": [
        "SUCCESS: The process with PID 202 (child process of PID 1) has been terminated.",
        _EXACT_SUCCESS,
    ],
}


@pytest.mark.parametrize("case", _LIFECYCLE_TRANSCRIPTS)
def test_windows_validator_consumes_complete_lifecycle_transcript(tmp_path, case):
    root, head, tree = _windows_smoke_fixture(tmp_path)
    artifact = root / "ci-windows-smoke-123-1"
    evidence = json.loads((artifact / "smoke-evidence.json").read_text())
    cleanup = evidence["scenarios"][1]["cleanup"]
    cleanup["owned_process_identities"].append(
        {
            "Id": 203,
            "Name": "python.exe",
            "CommandLine": "synthetic child",
            "CreationTime": "637134336010000000",
        }
    )
    cleanup.update(
        termination_outcome="exited-during-termination",
        taskkill_exit_code=255,
        lifecycle_diagnostic_verified=True,
        taskkill_output=_LIFECYCLE_TRANSCRIPTS[case],
    )
    evidence["cleanup"]["scenarios"][1] = cleanup
    (artifact / "smoke-evidence.json").write_text(json.dumps(evidence))
    (artifact / "cleanup.json").write_text(json.dumps(evidence["cleanup"]))
    kwargs = dict(
        job_result="success",
        head_sha=head,
        tree_sha=tree,
        workflow_identity=ExpectedWorkflowIdentity(
            "push",
            "refs/heads/task/125-ci-windows-smoke",
            "",
            "",
            "",
            "",
        ),
    )
    if case in {"valid", "valid_native_order", "valid_all_errors"}:
        validate_windows_smoke_artifact(root, **kwargs)
    else:
        with pytest.raises(ContractError):
            validate_windows_smoke_artifact(root, **kwargs)
