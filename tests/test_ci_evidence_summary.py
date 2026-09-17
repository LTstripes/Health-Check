import importlib.util
import subprocess
import sys
from pathlib import Path

_HELPER_PATH = Path(__file__).parents[1] / "scripts" / "ci_evidence_summary.py"
_SPEC = importlib.util.spec_from_file_location("ci_evidence_summary", _HELPER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_HELPER = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _HELPER
_SPEC.loader.exec_module(_HELPER)
_junit_summary = _HELPER._junit_summary
_render = _HELPER._render
_slowest_phases = _HELPER._slowest_phases
_pytest_log_summary = _HELPER._pytest_log_summary


def _run_summary(tmp_path, junit, log, status="pytest_exit_status=0\n"):
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(junit, encoding="utf-8")
    if log is not None:
        (tmp_path / "pytest.log").write_text(log, encoding="utf-8")
    (tmp_path / "pytest-status.txt").write_text(status, encoding="utf-8")
    output = tmp_path / "summary.md"
    result = subprocess.run(
        [
            sys.executable,
            str(_HELPER_PATH),
            "--junitxml",
            str(junit_path),
            "--pytest-log",
            str(tmp_path / "pytest.log"),
            "--status-file",
            str(tmp_path / "pytest-status.txt"),
            "--output",
            str(output),
        ],
        cwd=_HELPER_PATH.parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    return result, output.read_text(encoding="utf-8") if output.is_file() else ""


def test_missing_junit_is_explicitly_incomplete(tmp_path):
    rendered = _render(None, [], None)

    assert "Outcome: **INCOMPLETE**" in rendered
    assert "JUnit report missing" in rendered


def test_summary_retains_setup_call_and_teardown_attribution(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuite><testcase classname="synthetic" name="test_one" time="1.5" />'
        '<testcase classname="synthetic" name="test_two" time="0.5"><skipped /></testcase>'
        "</testsuite>",
        encoding="utf-8",
    )
    log = tmp_path / "pytest.log"
    log.write_text(
        "collected 2 items\n"
        "1.20s setup tests/test_one.py::test_one\n"
        "0.80s call tests/test_one.py::test_one\n"
        "0.10s teardown tests/test_one.py::test_one\n"
        "================ 1 passed, 1 skipped in 2.0s (0:00:02) ================\n",
        encoding="utf-8",
    )

    summary = _junit_summary(junit)
    phases = _slowest_phases(log)
    log_summary = _pytest_log_summary(log)
    rendered = _render(summary, phases, 0, log_summary=log_summary)

    assert summary is not None
    assert summary.total == 2
    assert summary.passed == 1
    assert summary.skipped == 1
    assert [phase for _, phase, _ in phases] == ["setup", "call", "teardown"]
    assert "Outcome: **PASS**" in rendered


def test_cli_fails_when_required_pytest_log_is_missing(tmp_path):
    result, rendered = _run_summary(
        tmp_path,
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase classname="synthetic" name="test_one" time="0.1" />'
        "</testsuite>",
        None,
    )

    assert result.returncode != 0
    assert "Outcome: **INCOMPLETE**" in rendered
    assert "terminal log missing" in rendered


def test_cli_fails_when_junit_and_terminal_counts_disagree(tmp_path):
    result, rendered = _run_summary(
        tmp_path,
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase classname="synthetic" name="test_one" time="0.1" />'
        "</testsuite>",
        "collected 745 items\n================ 745 passed in 1.0s ================\n",
    )

    assert result.returncode != 0
    assert "Outcome: **INCOMPLETE**" in rendered
    assert "contradictory" in rendered


def test_cli_fails_on_contradictory_junit_declared_counters(tmp_path):
    result, rendered = _run_summary(
        tmp_path,
        '<testsuite tests="2" failures="0" errors="0" skipped="0">'
        '<testcase classname="synthetic" name="test_one" time="0.1" />'
        "</testsuite>",
        "collected 1 item\n================ 1 passed in 0.1s ================\n",
    )

    assert result.returncode != 0
    assert "Outcome: **INCOMPLETE**" in rendered
    assert "JUnit report missing" in rendered


def test_cli_fails_on_ambiguous_status_file(tmp_path):
    result, rendered = _run_summary(
        tmp_path,
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase classname="synthetic" name="test_one" time="0.1" />'
        "</testsuite>",
        "collected 1 item\n================ 1 passed in 0.1s ================\n",
        status="pytest_exit_status=0\nextra=unexpected\n",
    )

    assert result.returncode != 0
    assert "Outcome: **INCOMPLETE**" in rendered
    assert "status file" in rendered


def test_cli_accepts_valid_non_slow_run_without_phase_entries(tmp_path):
    result, rendered = _run_summary(
        tmp_path,
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase classname="synthetic" name="test_one" time="0.1" />'
        "</testsuite>",
        "collected 1 item\n================ 1 passed in 0.1s ================\n",
    )

    assert result.returncode == 0
    assert "Outcome: **PASS**" in rendered
    assert "No phase timing entries exceeded" in rendered
    assert "evidence is incomplete" not in rendered
