import importlib.util
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


def test_missing_junit_is_explicitly_incomplete(tmp_path):
    rendered = _render(None, [], None)

    assert "Outcome: **INCOMPLETE**" in rendered
    assert "JUnit report missing" in rendered
    assert "evidence is incomplete" in rendered


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
        "1.20s setup tests/test_one.py::test_one\n"
        "0.80s call tests/test_one.py::test_one\n"
        "0.10s teardown tests/test_one.py::test_one\n",
        encoding="utf-8",
    )

    summary = _junit_summary(junit)
    phases = _slowest_phases(log)
    rendered = _render(summary, phases, 0)

    assert summary is not None
    assert summary.total == 2
    assert summary.passed == 1
    assert summary.skipped == 1
    assert [phase for _, phase, _ in phases] == ["setup", "call", "teardown"]
    assert "Outcome: **PASS**" in rendered
