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


@dataclass(frozen=True)
class TestSummary:
    total: int
    passed: int
    skipped: int
    failed: int
    errors: int
    duration: float


def _junit_summary(path: Path) -> TestSummary | None:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError):
        return None

    cases = list(root.iter("testcase"))
    if not cases:
        return None
    skipped = sum(case.find("skipped") is not None for case in cases)
    failed = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    try:
        duration = sum(float(case.attrib.get("time", "0")) for case in cases)
    except (TypeError, ValueError):
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
    if not path.is_file():
        return []
    entries: list[tuple[float, str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        match = _DURATION_RE.match(line)
        if match:
            entries.append(
                (float(match["seconds"]), match["phase"], match["nodeid"].strip())
            )
    return sorted(entries, reverse=True)[:limit]


def _pytest_status(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"pytest_exit_status=(\d+)", content)
    return int(match[1]) if match else None


def _render(
    summary: TestSummary | None,
    phases: list[tuple[float, str, str]],
    pytest_status: int | None,
) -> str:
    if summary is None:
        outcome = "INCOMPLETE"
        counts = "JUnit report missing, empty, malformed, or contained no test cases."
    else:
        counts = (
            f"{summary.total} collected; {summary.passed} passed; "
            f"{summary.skipped} skipped; {summary.failed} failed; "
            f"{summary.errors} errors; JUnit time {summary.duration:.2f}s."
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
        lines.append(
            "- No phase timing entries were retained; evidence is incomplete for attribution."
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--junitxml", type=Path, required=True)
    parser.add_argument("--pytest-log", type=Path, required=True)
    parser.add_argument("--status-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    summary = _junit_summary(args.junitxml)
    phases = _slowest_phases(args.pytest_log)
    pytest_status = _pytest_status(args.status_file)
    rendered = _render(summary, phases, pytest_status)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    return (
        0
        if summary is not None and pytest_status == 0 and not summary.failed and not summary.errors
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
