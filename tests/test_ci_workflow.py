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


def test_ci_cancellation_is_limited_to_task_or_pr_lanes():
    assert "format('ci-pr-{0}', github.event.pull_request.number)" in WORKFLOW
    assert "format('ci-push-{0}', github.ref)" in WORKFLOW
    assert (
        "cancel-in-progress: ${{ github.event_name == 'pull_request' || "
        "(github.event_name == 'push' && startsWith(github.ref, 'refs/heads/task/')) }}"
    ) in WORKFLOW
    assert "cancel-in-progress: true" not in WORKFLOW
    assert "ci-evidence-${{ github.run_id }}-${{ github.run_attempt }}" in WORKFLOW


def test_ci_retains_and_validates_failure_evidence():
    assert "if: always()" in WORKFLOW
    assert "if-no-files-found: error" in WORKFLOW
    assert "ci-evidence/pytest.log" in WORKFLOW
    assert "ci-evidence/failure-diagnostics.md" in WORKFLOW
