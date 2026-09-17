"""Create a compact, privacy-safe summary from pytest's retained evidence."""

from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path

_DURATION_RE = re.compile(
    r"^\s*(?P<seconds>\d+(?:\.\d+)?)s\s+(?P<phase>setup|call|teardown)\s+(?P<nodeid>.+?)\s*$"
)
_COLLECTED_RE = re.compile(r"^\s*collected\s+(?P<count>\d+)\s+items?\b")
_OUTCOME_RE = re.compile(r"\b(?P<count>\d+)\s+(?P<kind>failed|passed|skipped|errors?)\b")
_DURATION_SUFFIX_RE = re.compile(
    r"\bin\s+(?P<seconds>\d+(?:\.\d+)?)s\b"
)
_STATUS_RE = re.compile(r"^pytest_exit_status=(?P<status>\d+)$")


@dataclass(frozen=True)
class TestSummary:
    total: int
    passed: int
    skipped: int
    failed: int
    errors: int
    duration: float


@dataclass(frozen=True)
class PytestLogSummary:
    collected: int
    passed: int
    skipped: int
    failed: int
    errors: int
    duration: float


def _read_required_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    return content if content.strip() else None


def _declared_count(attributes: dict[str, str], name: str) -> int | None:
    value = attributes.get(name)
    if value is None:
        return None
    if not re.fullmatch(r"\d+", value):
        return -1
    return int(value)


def _validate_declared_counts(
    element: ElementTree.Element, cases: list[ElementTree.Element]
) -> bool:
    actual = {
        "tests": len(cases),
        "skipped": sum(case.find("skipped") is not None for case in cases),
        "failures": sum(case.find("failure") is not None for case in cases),
        "errors": sum(case.find("error") is not None for case in cases),
    }
    return all(
        declared is None or (declared >= 0 and declared == actual[name])
        for name in actual
        for declared in [_declared_count(element.attrib, name)]
    )


def _junit_summary(path: Path) -> TestSummary | None:
    try:
        if not path.is_file() or path.stat().st_size == 0:
            return None
    except OSError:
        return None
    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError):
        return None

    cases = list(root.iter("testcase"))
    if not cases or root.tag not in {"testsuite", "testsuites"}:
        return None
    if not _validate_declared_counts(root, cases):
        return None
    for suite in root.iter("testsuite"):
        if not _validate_declared_counts(suite, list(suite.iter("testcase"))):
            return None
    skipped = sum(case.find("skipped") is not None for case in cases)
    failed = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    if skipped + failed + errors > len(cases):
        return None
    try:
        duration = sum(float(case.attrib.get("time", "0")) for case in cases)
    except (TypeError, ValueError):
        return None
    if duration < 0:
        return None
    return TestSummary(
        total=len(cases),
        passed=len(cases) - skipped - failed - errors,
        skipped=skipped,
        failed=failed,
        errors=errors,
        duration=duration,
    )


def _slowest_phases(path: Path, limit: int = 10) -> list[tuple[float, str, str]]:
    content = _read_required_text(path)
    if content is None:
        return []
    entries: list[tuple[float, str, str]] = []
    for line in content.splitlines():
        match = _DURATION_RE.match(line)
        if match:
            entries.append(
                (float(match["seconds"]), match["phase"], match["nodeid"].strip())
            )
    return sorted(entries, reverse=True)[:limit]


def _pytest_log_summary(path: Path) -> PytestLogSummary | None:
    content = _read_required_text(path)
    if content is None:
        return None
    collected = next(
        (
            int(match["count"])
            for match in (_COLLECTED_RE.match(line) for line in content.splitlines())
            if match is not None
        ),
        None,
    )
    if collected is None:
        return None

    outcome: tuple[int, int, int, int, float] | None = None
    for line in content.splitlines():
        duration_match = _DURATION_SUFFIX_RE.search(line)
        outcome_matches = list(_OUTCOME_RE.finditer(line))
        if not duration_match or not outcome_matches:
            continue
        counts = {"passed": 0, "skipped": 0, "failed": 0, "errors": 0}
        for match in outcome_matches:
            kind = "errors" if match["kind"] == "error" else match["kind"]
            counts[kind] += int(match["count"])
        outcome = (
            counts["passed"],
            counts["skipped"],
            counts["failed"],
            counts["errors"],
            float(duration_match["seconds"]),
        )
    if outcome is None:
        return None
    passed, skipped, failed, errors, duration = outcome
    if passed + skipped + failed + errors != collected or duration < 0:
        return None
    return PytestLogSummary(collected, passed, skipped, failed, errors, duration)


def _pytest_status(path: Path) -> int | None:
    content = _read_required_text(path)
    if content is None:
        return None
    match = _STATUS_RE.fullmatch(content.strip())
    return int(match["status"]) if match else None


def _render(
    summary: TestSummary | None,
    phases: list[tuple[float, str, str]],
    pytest_status: int | None,
    *,
    log_summary: PytestLogSummary | None = None,
) -> str:
    if summary is None:
        outcome = "INCOMPLETE"
        counts = "JUnit report missing, empty, malformed, or contained no test cases."
    elif log_summary is None:
        outcome = "INCOMPLETE"
        counts = "Pytest terminal log missing, empty, malformed, or missing a complete outcome."
    elif pytest_status is None:
        outcome = "INCOMPLETE"
        counts = "Pytest status file missing, empty, malformed, or ambiguous."
    elif (
        summary.total != log_summary.collected
        or summary.passed != log_summary.passed
        or summary.skipped != log_summary.skipped
        or summary.failed != log_summary.failed
        or summary.errors != log_summary.errors
    ):
        outcome = "INCOMPLETE"
        counts = "JUnit and terminal pytest counts are contradictory."
    else:
        counts = (
            f"{log_summary.collected} collected; {log_summary.passed} passed; "
            f"{log_summary.skipped} skipped; {log_summary.failed} failed; "
            f"{log_summary.errors} errors; terminal time {log_summary.duration:.2f}s; "
            f"JUnit time {summary.duration:.2f}s."
        )
        outcome = (
            "PASS"
            if pytest_status == 0 and not summary.failed and not summary.errors
            else "FAIL"
        )
        if pytest_status is None:
            outcome = "INCOMPLETE"

    lines = ["# Pytest evidence summary", f"- Outcome: **{outcome}**", f"- {counts}"]
    if pytest_status is not None:
        lines.append(f"- pytest exit status: `{pytest_status}`")
    lines.append(
        "- Timing source: pytest built-in `--durations=25` with setup/call/teardown phases."
    )
    lines.append("")
    lines.append("## Slowest phases")
    if phases:
        lines.extend(
            f"- `{seconds:.2f}s` `{phase}` `{nodeid}`" for seconds, phase, nodeid in phases
        )
    else:
        lines.append("- No phase timing entries exceeded the retained threshold.")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--junitxml", type=Path, required=True)
    parser.add_argument("--pytest-log", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    summary = _junit_summary(args.junitxml)
    log_summary = _pytest_log_summary(args.pytest_log)
    phases = _slowest_phases(args.pytest_log)
    pytest_status = _pytest_status(args.status_file)
    rendered = _render(summary, phases, pytest_status, log_summary=log_summary)
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    except OSError:
        return 1
    consistent = (
        summary is not None
        and log_summary is not None
        and summary.total == log_summary.collected
        and summary.passed == log_summary.passed
        and summary.skipped == log_summary.skipped
        and summary.failed == log_summary.failed
        and summary.errors == log_summary.errors
    )
    return (
        0
        if consistent and pytest_status == 0 and not summary.failed and not summary.errors
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
