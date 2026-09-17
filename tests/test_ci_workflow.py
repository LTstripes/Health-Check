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


def _windows_smoke_fixture(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "artifacts"
    artifact = root / "ci-windows-smoke-123-1"
    artifact.mkdir(parents=True)
    head = "a" * 40
    tree = "b" * 40
    cleanup = {
        "scope": "harness-root-and-descendants-only",
        "root_pid": 101,
        "started_process_ids": [101, 102],
        "terminated_process_ids": [102, 101],
        "remaining_owned_process_ids": [],
        "identity_changed_process_ids": [],
        "errors": [],
    }
    evidence = {
        "schema_version": 1,
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
        "runtime": {"outside_checkout": True, "removed": True},
        "http": {
            "host": "127.0.0.1",
            "path": "/healthz",
            "status_code": 200,
            "body": {"service": "loopback-ui", "status": "ok"},
        },
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
    for name in ("start.stdout.log", "start.stderr.log"):
        (artifact / name).write_text("synthetic evidence\n", encoding="utf-8")
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
