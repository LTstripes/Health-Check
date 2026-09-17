"""Validate, run, and reconcile the three fail-closed Linux pytest lanes."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LANE_NAMES = ("garmin", "core-sleep", "app-ingest")
MANIFEST_PATH = Path("ci/test-lanes.json")


class ContractError(ValueError):
    """The lane contract or retained evidence is incomplete or contradictory."""


@dataclass(frozen=True)
class LaneManifest:
    lanes: dict[str, tuple[str, ...]]
    allowed_skips: tuple[dict[str, str], ...]
    sha256: str


@dataclass(frozen=True)
class ExpectedProvenance:
    lane: str
    platform: str
    head_sha: str
    tree_sha: str
    manifest_sha256: str
    selection_sha256: str
    selected_paths: tuple[str, ...]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _selection_sha256(paths: Sequence[str]) -> str:
    return _sha256_bytes(("\n".join(paths) + "\n").encode())


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"missing, unreadable, or malformed JSON artifact: {path}") from error


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_manifest(path: Path, repo_root: Path) -> LaneManifest:
    raw_bytes = path.read_bytes() if path.is_file() else b""
    _require(bool(raw_bytes), f"lane manifest is missing or empty: {path}")
    payload = _load_json(path)
    _require(isinstance(payload, dict), "lane manifest root must be an object")
    _require(payload.get("schema_version") == 1, "unsupported lane manifest schema")
    lanes_raw = payload.get("lanes")
    _require(isinstance(lanes_raw, dict), "lane manifest lanes must be an object")
    _require(set(lanes_raw) == set(LANE_NAMES), "lane manifest must define exactly three lanes")

    lanes: dict[str, tuple[str, ...]] = {}
    owner: dict[str, str] = {}
    for lane in LANE_NAMES:
        values = lanes_raw[lane]
        _require(isinstance(values, list) and values, f"lane {lane} must not be empty")
        normalized: list[str] = []
        for value in values:
            _require(isinstance(value, str), f"lane {lane} contains a non-string path")
            normalized_path = Path(value).as_posix()
            _require(
                value == normalized_path, f"lane path must use normalized '/' separators: {value}"
            )
            path_parts = Path(value).parts
            _require(
                len(path_parts) >= 2
                and path_parts[0] == "tests"
                and path_parts[-1].startswith("test_")
                and path_parts[-1].endswith(".py")
                and ".." not in path_parts,
                f"lane path is not a pytest file below tests/: {value}",
            )
            _require(value not in normalized, f"duplicate path within lane {lane}: {value}")
            _require(
                value not in owner,
                f"overlapping assignment: {value} in {owner.get(value)} and {lane}",
            )
            _require(
                (repo_root / value).is_file(), f"stale or nonexistent assigned test file: {value}"
            )
            owner[value] = lane
            normalized.append(value)
        lanes[lane] = tuple(normalized)

    discovered = {
        candidate.relative_to(repo_root).as_posix()
        for candidate in (repo_root / "tests").rglob("test_*.py")
        if candidate.is_file()
    }
    assigned = set(owner)
    missing = sorted(discovered - assigned)
    stale = sorted(assigned - discovered)
    _require(not missing, f"unassigned test files: {missing}")
    _require(not stale, f"stale or nonexistent assigned test files: {stale}")

    skips_raw = payload.get("allowed_skips", [])
    _require(isinstance(skips_raw, list), "allowed_skips must be a list")
    skips: list[dict[str, str]] = []
    seen_skips: set[tuple[str, str, str]] = set()
    for entry in skips_raw:
        _require(isinstance(entry, dict), "allowed skip must be an object")
        _require(set(entry) == {"nodeid", "platform", "reason"}, "allowed skip fields are invalid")
        _require(
            all(isinstance(entry[key], str) and entry[key] for key in entry),
            "allowed skip fields must be non-empty strings",
        )
        test_path = entry["nodeid"].split("::", 1)[0]
        _require(
            test_path in assigned, f"allowed skip references unassigned test file: {test_path}"
        )
        identity = (entry["nodeid"], entry["platform"], entry["reason"])
        _require(identity not in seen_skips, f"duplicate allowed skip: {identity}")
        seen_skips.add(identity)
        skips.append(dict(entry))
    return LaneManifest(lanes=lanes, allowed_skips=tuple(skips), sha256=_sha256_bytes(raw_bytes))


def _counter_delta(expected: Counter[str], actual: Counter[str]) -> tuple[list[str], list[str]]:
    return sorted((expected - actual).elements()), sorted((actual - expected).elements())


def reconcile_collections(
    reference: Sequence[str], lane_nodeids: Mapping[str, Sequence[str]]
) -> Counter[str]:
    _require(bool(reference), "unrestricted reference collection is empty")
    _require(
        set(lane_nodeids) == set(LANE_NAMES), "collection evidence must contain exactly three lanes"
    )
    lane_counters = {lane: Counter(lane_nodeids[lane]) for lane in LANE_NAMES}
    for lane, counter in lane_counters.items():
        _require(bool(counter), f"lane collection is empty: {lane}")
    overlaps: list[str] = []
    for index, left in enumerate(LANE_NAMES):
        for right in LANE_NAMES[index + 1 :]:
            overlaps.extend(sorted((lane_counters[left] & lane_counters[right]).elements()))
    _require(not overlaps, f"lane collection overlap: {overlaps}")
    union: Counter[str] = Counter()
    for counter in lane_counters.values():
        union.update(counter)
    expected = Counter(reference)
    missing, extra = _counter_delta(expected, union)
    _require(not missing and not extra, f"collection mismatch: missing={missing}; extra={extra}")
    return expected


def _validate_provenance(payload: Mapping[str, Any], expected: ExpectedProvenance) -> None:
    for field in (
        "lane",
        "platform",
        "head_sha",
        "tree_sha",
        "manifest_sha256",
        "selection_sha256",
    ):
        _require(payload.get(field) == getattr(expected, field), f"{field} provenance mismatch")
    _require(
        payload.get("selected_paths") == list(expected.selected_paths),
        "selected_paths provenance mismatch",
    )


def _validate_collection_payload(
    payload: Mapping[str, Any], expected: ExpectedProvenance
) -> list[str]:
    _require(payload.get("schema_version") == 1, "unsupported collection evidence schema")
    _require(payload.get("mode") == "collect", "collection evidence mode mismatch")
    _validate_provenance(payload, expected)
    _require(payload.get("collection_complete") is True, "collection did not complete")
    _require(payload.get("collection_errors") == [], "collection errors were recorded")
    _require(payload.get("deselected_nodeids") == [], "unexpected deselection during collection")
    _require(
        payload.get("session_exit_status") == 0, "collection process did not exit successfully"
    )
    nodeids = payload.get("collected_nodeids")
    _require(
        isinstance(nodeids, list) and nodeids and all(isinstance(item, str) for item in nodeids),
        "collection nodeid inventory is missing or empty",
    )
    return list(nodeids)


def validate_lane_payload(
    payload: Mapping[str, Any],
    expected: ExpectedProvenance,
    *,
    allowed_skips: Iterable[Mapping[str, str]],
) -> dict[str, int]:
    _require(payload.get("schema_version") == 1, "unsupported lane evidence schema")
    _require(payload.get("mode") == "run", "lane evidence mode mismatch")
    _validate_provenance(payload, expected)
    _require(payload.get("collection_complete") is True, "lane collection did not complete")
    _require(payload.get("collection_errors") == [], "lane collection errors were recorded")
    _require(payload.get("deselected_nodeids") == [], "lane had unexpected deselection")
    _require(payload.get("session_exit_status") == 0, "lane process was failed or incomplete")
    collected = payload.get("collected_nodeids")
    cases = payload.get("cases")
    _require(isinstance(collected, list) and collected, "lane collected inventory is empty")
    _require(isinstance(cases, list), "lane case outcomes are missing")
    case_nodeids = [case.get("nodeid") for case in cases if isinstance(case, dict)]
    _require(len(case_nodeids) == len(cases), "lane case outcome has invalid shape")
    missing, extra = _counter_delta(Counter(collected), Counter(case_nodeids))
    _require(
        not missing and not extra, f"lane execution mismatch: missing={missing}; extra={extra}"
    )

    allowed = {
        (entry.get("nodeid"), entry.get("platform"), entry.get("reason")) for entry in allowed_skips
    }
    counts = {"passed": 0, "skipped": 0, "failed": 0, "errors": 0}
    for case in cases:
        nodeid = case["nodeid"]
        phases = case.get("phases")
        _require(isinstance(phases, list) and phases, f"missing phase outcomes for {nodeid}")
        by_when: dict[str, Mapping[str, Any]] = {}
        for phase in phases:
            _require(isinstance(phase, dict), f"invalid phase outcome for {nodeid}")
            when = phase.get("when")
            _require(when in {"setup", "call", "teardown"}, f"invalid phase name for {nodeid}")
            _require(when not in by_when, f"duplicate {when} phase for {nodeid}")
            _require(not phase.get("wasxfail"), f"xfail/xpass is not allowed: {nodeid}")
            by_when[when] = phase
        _require(
            "setup" in by_when and "teardown" in by_when, f"incomplete worker outcome: {nodeid}"
        )
        failed_phases = [phase for phase in phases if phase.get("outcome") == "failed"]
        if failed_phases:
            kind = (
                "failed" if "call" in {phase.get("when") for phase in failed_phases} else "errors"
            )
            counts[kind] += 1
            raise ContractError(f"lane contains {kind}: {nodeid}")
        skipped = [phase for phase in phases if phase.get("outcome") == "skipped"]
        if skipped:
            _require(len(skipped) == 1, f"ambiguous skip outcome: {nodeid}")
            identity = (nodeid, expected.platform, str(skipped[0].get("reason", "")))
            _require(identity in allowed, f"unexpected skip: {identity}")
            counts["skipped"] += 1
            continue
        _require(
            set(by_when) == {"setup", "call", "teardown"}, f"incomplete worker outcome: {nodeid}"
        )
        _require(
            all(phase.get("outcome") == "passed" for phase in phases),
            f"unexpected phase outcome: {nodeid}",
        )
        counts["passed"] += 1
    return counts


def validate_gate_job_results(*, quality_result: str, test_result: str) -> None:
    _require(quality_result == "success", f"mandatory quality job result is {quality_result}")
    _require(test_result == "success", f"mandatory test job result is {test_result}")


def _one_directory(root: Path, pattern: str, missing_message: str) -> Path:
    matches = [path for path in root.glob(pattern) if path.is_dir()]
    _require(len(matches) == 1, f"{missing_message}: found {len(matches)}")
    return matches[0]


def validate_gate_artifacts(
    artifacts_root: Path,
    *,
    head_sha: str,
    tree_sha: str,
    manifest_sha256: str,
    manifest: LaneManifest | None = None,
) -> dict[str, Any]:
    quality_dir = _one_directory(artifacts_root, "ci-quality-*", "missing quality artifact")
    summary_path = quality_dir / "collection-summary.json"
    summary = _load_json(summary_path)
    for field, expected in (
        ("head_sha", head_sha),
        ("tree_sha", tree_sha),
        ("manifest_sha256", manifest_sha256),
    ):
        _require(summary.get(field) == expected, f"quality {field} provenance mismatch")
    lanes = summary.get("lanes")
    reference = summary.get("reference_nodeids")
    _require(
        isinstance(lanes, dict) and isinstance(reference, list),
        "quality collection summary is malformed",
    )
    platform = summary.get("platform", sys.platform)
    if manifest is not None:
        _require(platform == sys.platform, "quality platform provenance mismatch")
        for required in (
            "metadata.md",
            "git-status.txt",
            "uv-lock.sha256",
            "reference.json",
            "reference-collection.log",
        ):
            _require((quality_dir / required).is_file(), f"missing quality report: {required}")
        reference_expected = ExpectedProvenance(
            lane="reference",
            platform=platform,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest_sha256,
            selection_sha256=_selection_sha256(()),
            selected_paths=(),
        )
        raw_reference = _validate_collection_payload(
            _load_json(quality_dir / "reference.json"), reference_expected
        )
        missing, extra = _counter_delta(Counter(reference), Counter(raw_reference))
        _require(
            not missing and not extra,
            f"reference artifact mismatch: missing={missing}; extra={extra}",
        )
        for lane in LANE_NAMES:
            selected_paths = tuple(lanes.get(lane, {}).get("selected_paths", []))
            selection_sha = lanes.get(lane, {}).get("selection_sha256")
            _require(
                selected_paths == manifest.lanes[lane],
                f"quality lane {lane} selection differs from checked-in manifest",
            )
            _require(
                selection_sha == _selection_sha256(selected_paths),
                f"quality lane {lane} selection digest mismatch",
            )
            raw_path = quality_dir / f"{lane}-collection.json"
            log_path = quality_dir / f"{lane}-collection.log"
            _require(raw_path.is_file(), f"missing quality lane collection: {lane}")
            _require(log_path.is_file(), f"missing quality lane collection log: {lane}")
            expected = ExpectedProvenance(
                lane=lane,
                platform=platform,
                head_sha=head_sha,
                tree_sha=tree_sha,
                manifest_sha256=manifest_sha256,
                selection_sha256=selection_sha,
                selected_paths=selected_paths,
            )
            raw_nodeids = _validate_collection_payload(_load_json(raw_path), expected)
            summary_nodeids = lanes[lane].get("nodeids", [])
            missing, extra = _counter_delta(Counter(summary_nodeids), Counter(raw_nodeids))
            _require(
                not missing and not extra,
                f"quality lane {lane} artifact mismatch: missing={missing}; extra={extra}",
            )
    reconcile_collections(
        reference, {lane: lanes.get(lane, {}).get("nodeids", []) for lane in LANE_NAMES}
    )

    verified_lanes: dict[str, Any] = {}
    for lane in LANE_NAMES:
        lane_dir = _one_directory(
            artifacts_root, f"ci-lane-{lane}-*", f"missing lane artifact for {lane}"
        )
        verified = _load_json(lane_dir / "verified.json")
        for field, expected in (
            ("schema_version", 1),
            ("status", "verified"),
            ("lane", lane),
            ("platform", platform),
            ("head_sha", head_sha),
            ("tree_sha", tree_sha),
            ("manifest_sha256", manifest_sha256),
        ):
            _require(verified.get(field) == expected, f"lane {lane} {field} provenance mismatch")
        expected_nodeids = lanes[lane].get("nodeids", [])
        actual_nodeids = verified.get("nodeids", verified.get("collected_nodeids", []))
        missing, extra = _counter_delta(Counter(expected_nodeids), Counter(actual_nodeids))
        _require(
            not missing and not extra,
            f"lane {lane} inventory mismatch: missing={missing}; extra={extra}",
        )
        selected_paths = tuple(lanes[lane].get("selected_paths", []))
        selection_sha = lanes[lane].get("selection_sha256")
        _require(
            verified.get("selected_paths") == list(selected_paths),
            f"lane {lane} selected_paths provenance mismatch",
        )
        _require(
            verified.get("selection_sha256") == selection_sha,
            f"lane {lane} selection_sha256 provenance mismatch",
        )
        if manifest is not None:
            _require(
                selected_paths == manifest.lanes[lane],
                f"lane {lane} selection differs from checked-in manifest",
            )
            required_files = (
                "metadata.md",
                "git-status.txt",
                "uv-lock.sha256",
                "command.txt",
                "lane-evidence.json",
                "junit.xml",
                "pytest.log",
                "pytest-status.txt",
                "summary.md",
            )
            for required in required_files:
                _require(
                    (lane_dir / required).is_file(),
                    f"missing lane {lane} report: {required}",
                )
            expected = ExpectedProvenance(
                lane=lane,
                platform=platform,
                head_sha=head_sha,
                tree_sha=tree_sha,
                manifest_sha256=manifest_sha256,
                selection_sha256=selection_sha,
                selected_paths=selected_paths,
            )
            raw_payload = _load_json(lane_dir / "lane-evidence.json")
            counts = validate_lane_payload(
                raw_payload, expected, allowed_skips=manifest.allowed_skips
            )
            _require(
                counts == verified.get("counts"),
                f"lane {lane} verified counts mismatch raw outcomes",
            )
            _verify_report_sources(lane_dir, counts, len(expected_nodeids))
        verified_lanes[lane] = verified
    return {"quality": summary, "lanes": verified_lanes}


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, check=False
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise ContractError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _identity(repo_root: Path, manifest: LaneManifest) -> tuple[str, str, str]:
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    _require(status.returncode == 0, f"git status failed: {status.stderr.strip()}")
    _require(not status.stdout.strip(), "exact evidence requires a clean working tree")
    return (
        _git(repo_root, "rev-parse", "HEAD"),
        _git(repo_root, "rev-parse", "HEAD^{tree}"),
        manifest.sha256,
    )


def _plugin_args(
    output: Path,
    *,
    mode: str,
    lane: str,
    platform: str,
    head_sha: str,
    tree_sha: str,
    manifest_sha256: str,
    selected_paths: Sequence[str],
) -> list[str]:
    args = [
        "-p",
        "scripts.ci_lane_plugin",
        f"--ci-lane-evidence={output}",
        f"--ci-lane-mode={mode}",
        f"--ci-lane-name={lane}",
        f"--ci-platform={platform}",
        f"--ci-head-sha={head_sha}",
        f"--ci-tree-sha={tree_sha}",
        f"--ci-manifest-sha256={manifest_sha256}",
        f"--ci-selection-sha256={_selection_sha256(selected_paths)}",
    ]
    for path in selected_paths:
        args.append(f"--ci-selected-path={path}")
    return args


def _run_logged(command: Sequence[str], *, cwd: Path, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", newline="") as stream:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            stream.write(line)
        return process.wait()


def collect_inventories(repo_root: Path, output_dir: Path, manifest_path: Path) -> dict:
    manifest = validate_manifest(manifest_path, repo_root)
    head_sha, tree_sha, manifest_sha = _identity(repo_root, manifest)
    output_dir.mkdir(parents=True, exist_ok=True)
    inventories: dict[str, list[str]] = {}
    selections: dict[str, tuple[str, ...]] = {"reference": ()}
    selections.update(manifest.lanes)
    for lane, paths in selections.items():
        evidence_path = output_dir / (
            "reference.json" if lane == "reference" else f"{lane}-collection.json"
        )
        command = [sys.executable, "-m", "pytest", "--collect-only", "-q"]
        command.extend(paths)
        command.extend(
            _plugin_args(
                evidence_path,
                mode="collect",
                lane=lane,
                platform=sys.platform,
                head_sha=head_sha,
                tree_sha=tree_sha,
                manifest_sha256=manifest_sha,
                selected_paths=paths,
            )
        )
        status = _run_logged(command, cwd=repo_root, log_path=output_dir / f"{lane}-collection.log")
        _require(status == 0, f"collection command failed for {lane}: exit {status}")
        expected = ExpectedProvenance(
            lane=lane,
            platform=sys.platform,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest_sha,
            selection_sha256=_selection_sha256(paths),
            selected_paths=tuple(paths),
        )
        inventories[lane] = _validate_collection_payload(_load_json(evidence_path), expected)
    reconcile_collections(
        inventories["reference"], {lane: inventories[lane] for lane in LANE_NAMES}
    )
    summary = {
        "schema_version": 1,
        "platform": sys.platform,
        "head_sha": head_sha,
        "tree_sha": tree_sha,
        "manifest_sha256": manifest_sha,
        "reference_nodeids": inventories["reference"],
        "lanes": {
            lane: {
                "selected_paths": list(manifest.lanes[lane]),
                "selection_sha256": _selection_sha256(manifest.lanes[lane]),
                "nodeids": inventories[lane],
            }
            for lane in LANE_NAMES
        },
    }
    _write_json(output_dir / "collection-summary.json", summary)
    return summary


def run_lane(
    repo_root: Path,
    output_dir: Path,
    manifest_path: Path,
    lane: str,
    basetemp: Path,
) -> int:
    manifest = validate_manifest(manifest_path, repo_root)
    _require(lane in manifest.lanes, f"unknown lane: {lane}")
    head_sha, tree_sha, manifest_sha = _identity(repo_root, manifest)
    paths = manifest.lanes[lane]
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = output_dir / "lane-evidence.json"
    command = [
        sys.executable,
        "-m",
        "pytest",
        *paths,
        "--durations=25",
        "--durations-min=1.0",
        f"--junitxml={output_dir / 'junit.xml'}",
        f"--basetemp={basetemp}",
        *_plugin_args(
            evidence_path,
            mode="run",
            lane=lane,
            platform=sys.platform,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest_sha,
            selected_paths=paths,
        ),
    ]
    (output_dir / "command.txt").write_text(
        subprocess.list2cmdline(command) + "\n", encoding="utf-8"
    )
    status = _run_logged(command, cwd=repo_root, log_path=output_dir / "pytest.log")
    (output_dir / "pytest-status.txt").write_text(
        f"pytest_exit_status={status}\n", encoding="utf-8"
    )
    return status


def _verify_report_sources(output_dir: Path, counts: Mapping[str, int], total: int) -> str:
    from ci_evidence_summary import (  # type: ignore[import-not-found]
        _junit_summary,
        _pytest_log_summary,
        _pytest_status,
        _render,
        _slowest_phases,
    )

    junit = _junit_summary(output_dir / "junit.xml")
    log = _pytest_log_summary(output_dir / "pytest.log")
    status = _pytest_status(output_dir / "pytest-status.txt")
    rendered = _render(junit, _slowest_phases(output_dir / "pytest.log"), status, log_summary=log)
    (output_dir / "summary.md").write_text(rendered, encoding="utf-8")
    _require(
        junit is not None and log is not None and status == 0,
        "missing or incomplete JUnit/log/status evidence",
    )
    expected = (total, counts["passed"], counts["skipped"], 0, 0)
    junit_actual = (junit.total, junit.passed, junit.skipped, junit.failed, junit.errors)
    log_actual = (log.collected, log.passed, log.skipped, log.failed, log.errors)
    _require(
        junit_actual == expected,
        f"JUnit evidence mismatch: expected={expected}; actual={junit_actual}",
    )
    _require(
        log_actual == expected,
        f"pytest log evidence mismatch: expected={expected}; actual={log_actual}",
    )
    return rendered


def verify_lane(repo_root: Path, output_dir: Path, manifest_path: Path, lane: str) -> dict:
    manifest = validate_manifest(manifest_path, repo_root)
    _require(lane in manifest.lanes, f"unknown lane: {lane}")
    head_sha, tree_sha, manifest_sha = _identity(repo_root, manifest)
    paths = manifest.lanes[lane]
    expected = ExpectedProvenance(
        lane=lane,
        platform=sys.platform,
        head_sha=head_sha,
        tree_sha=tree_sha,
        manifest_sha256=manifest_sha,
        selection_sha256=_selection_sha256(paths),
        selected_paths=paths,
    )
    payload = _load_json(output_dir / "lane-evidence.json")
    counts = validate_lane_payload(payload, expected, allowed_skips=manifest.allowed_skips)
    nodeids = payload["collected_nodeids"]
    _verify_report_sources(output_dir, counts, len(nodeids))
    verified = {
        "schema_version": 1,
        "status": "verified",
        "lane": lane,
        "platform": sys.platform,
        "head_sha": head_sha,
        "tree_sha": tree_sha,
        "manifest_sha256": manifest_sha,
        "selection_sha256": expected.selection_sha256,
        "selected_paths": list(paths),
        "nodeids": nodeids,
        "counts": counts,
    }
    _write_json(output_dir / "verified.json", verified)
    return verified


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _manifest_arg(repo_root: Path, value: Path) -> Path:
    return value if value.is_absolute() else repo_root / value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-manifest")
    paths_parser = subparsers.add_parser("paths")
    paths_parser.add_argument("--lane", choices=LANE_NAMES, required=True)
    collect_parser = subparsers.add_parser("collect")
    collect_parser.add_argument("--output-dir", type=Path, required=True)
    run_parser = subparsers.add_parser("run-lane")
    run_parser.add_argument("--lane", choices=LANE_NAMES, required=True)
    run_parser.add_argument("--output-dir", type=Path, required=True)
    run_parser.add_argument("--basetemp", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify-lane")
    verify_parser.add_argument("--lane", choices=LANE_NAMES, required=True)
    verify_parser.add_argument("--output-dir", type=Path, required=True)
    gate_parser = subparsers.add_parser("gate")
    gate_parser.add_argument("--artifacts-root", type=Path, required=True)
    gate_parser.add_argument("--quality-result", required=True)
    gate_parser.add_argument("--test-result", required=True)
    gate_parser.add_argument("--head-sha", required=True)
    gate_parser.add_argument("--tree-sha", required=True)
    args = parser.parse_args()

    repo_root = _repo_root()
    manifest_path = _manifest_arg(repo_root, args.manifest)
    try:
        if args.command == "validate-manifest":
            manifest = validate_manifest(manifest_path, repo_root)
            print(f"validated {sum(map(len, manifest.lanes.values()))} files in 3 lanes")
        elif args.command == "paths":
            manifest = validate_manifest(manifest_path, repo_root)
            print("\n".join(manifest.lanes[args.lane]))
        elif args.command == "collect":
            summary = collect_inventories(repo_root, args.output_dir, manifest_path)
            print(
                f"reconciled {len(summary['reference_nodeids'])} exact nodeids across "
                + ", ".join(
                    f"{lane}={len(summary['lanes'][lane]['nodeids'])}" for lane in LANE_NAMES
                )
            )
        elif args.command == "run-lane":
            return run_lane(repo_root, args.output_dir, manifest_path, args.lane, args.basetemp)
        elif args.command == "verify-lane":
            verified = verify_lane(repo_root, args.output_dir, manifest_path, args.lane)
            print(f"verified {args.lane}: {verified['counts']}")
        else:
            validate_gate_job_results(
                quality_result=args.quality_result, test_result=args.test_result
            )
            manifest = validate_manifest(manifest_path, repo_root)
            result = validate_gate_artifacts(
                args.artifacts_root,
                head_sha=args.head_sha,
                tree_sha=args.tree_sha,
                manifest_sha256=manifest.sha256,
                manifest=manifest,
            )
            total = len(result["quality"]["reference_nodeids"])
            print(f"checks PASS: {total} exact nodeids reconciled across all mandatory jobs")
    except ContractError as error:
        print(f"CI lane contract failure: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
