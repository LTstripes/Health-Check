"""Pytest plugin that records exact collection, outcomes, and provenance for one CI lane."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def pytest_addoption(parser) -> None:
    group = parser.getgroup("health-check-ci-lane")
    group.addoption("--ci-lane-evidence", type=Path)
    group.addoption("--ci-lane-mode", choices=("collect", "run"))
    group.addoption("--ci-lane-name")
    group.addoption("--ci-platform")
    group.addoption("--ci-head-sha")
    group.addoption("--ci-tree-sha")
    group.addoption("--ci-manifest-sha256")
    group.addoption("--ci-selection-sha256")
    group.addoption("--ci-selected-path", action="append", default=[])


def _reason(report) -> str:
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        value = str(longrepr[2])
    else:
        value = str(longrepr or "")
    for prefix in ("Skipped: ", "SKIPPED: "):
        if value.startswith(prefix):
            return value[len(prefix) :].strip()
    return value.strip()


class _LaneEvidencePlugin:
    def __init__(self, config) -> None:
        option = config.option
        self.output = option.ci_lane_evidence
        self.payload: dict[str, Any] = {
            "schema_version": 1,
            "mode": option.ci_lane_mode,
            "lane": option.ci_lane_name,
            "platform": option.ci_platform,
            "head_sha": option.ci_head_sha,
            "tree_sha": option.ci_tree_sha,
            "manifest_sha256": option.ci_manifest_sha256,
            "selection_sha256": option.ci_selection_sha256,
            "selected_paths": list(option.ci_selected_path),
            "collection_complete": False,
            "collected_nodeids": [],
            "deselected_nodeids": [],
            "collection_errors": [],
            "session_exit_status": None,
            "cases": [],
        }
        self._active_case: dict[str, Any] | None = None

    def pytest_collectreport(self, report) -> None:
        if report.failed:
            self.payload["collection_errors"].append(str(report.longrepr))

    def pytest_deselected(self, items) -> None:
        self.payload["deselected_nodeids"].extend(item.nodeid for item in items)

    def pytest_collection_finish(self, session) -> None:
        self.payload["collected_nodeids"] = [item.nodeid for item in session.items]
        self.payload["collection_complete"] = not self.payload["collection_errors"]

    def pytest_runtest_logreport(self, report) -> None:
        if report.when == "setup":
            self._active_case = {"nodeid": report.nodeid, "phases": []}
            self.payload["cases"].append(self._active_case)
        if self._active_case is None or self._active_case["nodeid"] != report.nodeid:
            self._active_case = {"nodeid": report.nodeid, "phases": []}
            self.payload["cases"].append(self._active_case)
        self._active_case["phases"].append(
            {
                "when": report.when,
                "outcome": report.outcome,
                "reason": _reason(report) if report.skipped or report.failed else "",
                "wasxfail": str(getattr(report, "wasxfail", "") or ""),
            }
        )
        if report.when == "teardown":
            self._active_case = None

    def pytest_sessionfinish(self, session, exitstatus) -> None:
        self.payload["session_exit_status"] = int(exitstatus)
        if self.output is None:
            return
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(
            json.dumps(self.payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def pytest_configure(config) -> None:
    if config.option.ci_lane_evidence is None:
        return
    required = {
        "mode": config.option.ci_lane_mode,
        "lane": config.option.ci_lane_name,
        "platform": config.option.ci_platform,
        "head": config.option.ci_head_sha,
        "tree": config.option.ci_tree_sha,
        "manifest": config.option.ci_manifest_sha256,
        "selection": config.option.ci_selection_sha256,
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        raise ValueError(f"missing CI lane provenance options: {', '.join(missing)}")
    config.pluginmanager.register(_LaneEvidencePlugin(config), "health-check-ci-lane-evidence")
