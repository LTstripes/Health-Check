from pathlib import Path

WORKFLOW = (Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml").read_text(
    encoding="utf-8"
)
SUMMARY_SCRIPT = (Path(__file__).parents[1] / "scripts" / "ci_evidence_summary.py").read_text(
    encoding="utf-8"
)


def test_ci_keeps_full_push_and_pull_request_coverage():
    assert "  push:\n" in WORKFLOW
    assert "  pull_request:\n" in WORKFLOW
    assert "uv run pytest --durations=25 --durations-min=1.0" in WORKFLOW
    assert "--junitxml=ci-evidence/junit.xml" in WORKFLOW
    assert "setup/call/teardown" in SUMMARY_SCRIPT
    assert "timeout-minutes: 30" in WORKFLOW
    assert WORKFLOW.index('git_status="$(git status --short --branch)"') < WORKFLOW.index(
        "mkdir -p ci-evidence"
    )


def test_ci_cancellation_is_limited_to_task_or_pr_lanes():
    assert "format('ci-pr-{0}', github.event.pull_request.number)" in WORKFLOW
    assert "format('ci-task-{0}', github.ref)" in WORKFLOW
    assert "format('ci-run-{0}', github.run_id)" in WORKFLOW
    assert "format('ci-push-{0}', github.ref)" not in WORKFLOW
    assert (
        "cancel-in-progress: ${{ github.event_name == 'pull_request' || "
        "(github.event_name == 'push' && startsWith(github.ref, 'refs/heads/task/')) }}"
    ) in WORKFLOW
    assert "cancel-in-progress: true" not in WORKFLOW
    assert "ci-evidence-${{ github.run_id }}-${{ github.run_attempt }}" in WORKFLOW


def test_ci_concurrency_behavioral_lanes_are_bound_to_actual_expression():
    group_line = next(line for line in WORKFLOW.splitlines() if line.startswith("  group:"))
    cancel_line = next(
        line for line in WORKFLOW.splitlines() if line.startswith("  cancel-in-progress:")
    )
    cases = (
        ("pull_request", "refs/pull/123/merge", "ci-pr-{0}", True),
        ("push", "refs/heads/task/123-ci-evidence-and-gates", "ci-task-{0}", True),
        ("push", "refs/heads/task/other", "ci-task-{0}", True),
        ("push", "refs/heads/main", "ci-run-{0}", False),
        ("push", "refs/heads/integration", "ci-run-{0}", False),
        ("push", "refs/tags/v1", "ci-run-{0}", False),
    )
    for event, ref, expected_prefix, cancelable in cases:
        assert event in group_line or event == "push"
        assert ref.startswith("refs/")
        assert f"format('{expected_prefix}'" in group_line
        if cancelable:
            assert "cancel-in-progress: ${{" in cancel_line
        else:
            assert "github.run_id" in group_line
            assert "cancel-in-progress: ${{" in cancel_line
    assert "github.event.pull_request.number" in group_line
    assert "startsWith(github.ref, 'refs/heads/task/')" in group_line
    assert "github.run_id" in group_line
    assert "cancel-in-progress: true" not in WORKFLOW


def test_ci_retains_and_validates_failure_evidence():
    assert "if: always()" in WORKFLOW
    assert "if-no-files-found: error" in WORKFLOW
    assert "ci-evidence/pytest.log" in WORKFLOW
    assert "ci-evidence/failure-diagnostics.md" in WORKFLOW
    summary_step = WORKFLOW.split("      - name: Summarize test evidence\n", 1)[1].split(
        "      - name: Capture failure diagnostics\n", 1
    )[0]
    assert "set -euo pipefail" in summary_step
    assert "set +e" not in summary_step
    assert "if uv run python scripts/ci_evidence_summary.py" in summary_step
    assert "cat ci-evidence/metadata.md" in summary_step
