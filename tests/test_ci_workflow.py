from pathlib import Path

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


def test_workflow_has_no_per_candidate_fourth_serial_suite():
    assert WORKFLOW.count("run-lane") == 1
    assert "uv run pytest" not in WORKFLOW
    assert "full pytest" not in WORKFLOW.lower()
