"""Validate, run, and reconcile the three fail-closed Linux pytest lanes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LANE_NAMES = ("garmin", "core-sleep", "app-ingest")
COUNT_NAMES = ("passed", "skipped", "failed", "errors")
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


@dataclass(frozen=True)
class ExpectedWorkflowIdentity:
    event_name: str
    ref: str
    pr_base_ref: str
    pr_base_sha: str
    pr_head_ref: str
    pr_head_sha: str


@dataclass(frozen=True)
class EnvironmentIdentity:
    python: str
    uv: str
    runner: str


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _require_schema_v1(value: Any, label: str) -> None:
    _require(
        type(value) is int and value == 1,
        f"{label} schema_version must be integer 1",
    )


def _require_zero_exit_status(value: Any, label: str) -> None:
    _require(type(value) is int, f"{label} must be an integer")
    _require(value == 0, f"{label} did not exit successfully")


def _validate_counts(value: Any, label: str) -> dict[str, int]:
    _require(isinstance(value, dict), f"{label} counts must be an object")
    _require(set(value) == set(COUNT_NAMES), f"{label} count fields mismatch")
    for name in COUNT_NAMES:
        count = value[name]
        _require(type(count) is int, f"{label} {name} count must be an integer")
        _require(count >= 0, f"{label} {name} count must be nonnegative")
    return {name: value[name] for name in COUNT_NAMES}


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _selection_sha256(paths: Sequence[str]) -> str:
    return _sha256_bytes(("\n".join(paths) + "\n").encode())


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"missing, unreadable, or malformed JSON artifact: {path}") from error


def _read_required_text(path: Path, label: str) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ContractError(f"missing or unreadable {label}: {path}") from error
    _require(bool(text.strip()), f"{label} is empty: {path}")
    return text


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate_manifest(path: Path, repo_root: Path) -> LaneManifest:
    raw_bytes = path.read_bytes() if path.is_file() else b""
    _require(bool(raw_bytes), f"lane manifest is missing or empty: {path}")
    payload = _load_json(path)
    _require(isinstance(payload, dict), "lane manifest root must be an object")
    _require_schema_v1(payload.get("schema_version"), "lane manifest")
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


def _validate_workflow_identity(expected: ExpectedWorkflowIdentity) -> None:
    _require(
        expected.event_name in {"push", "pull_request"},
        f"unsupported workflow event: {expected.event_name!r}",
    )
    if expected.event_name == "push":
        _require(
            re.fullmatch(r"refs/(?:heads|tags)/[^\s]+", expected.ref) is not None,
            f"push workflow ref is malformed: {expected.ref!r}",
        )
        _require(
            not any(
                (
                    expected.pr_base_ref,
                    expected.pr_base_sha,
                    expected.pr_head_ref,
                    expected.pr_head_sha,
                )
            ),
            "push workflow identity must have explicit empty PR fields",
        )
        return

    _require(
        re.fullmatch(r"refs/pull/[1-9][0-9]*/merge", expected.ref) is not None,
        f"pull_request workflow ref is malformed: {expected.ref!r}",
    )
    for field, value in (
        ("PR base ref", expected.pr_base_ref),
        ("PR head ref", expected.pr_head_ref),
    ):
        _require(
            bool(value)
            and not value.startswith("refs/")
            and re.fullmatch(r"[^\s]+", value) is not None,
            f"pull_request {field} is malformed",
        )
    for field, value in (
        ("PR base SHA", expected.pr_base_sha),
        ("PR head SHA", expected.pr_head_sha),
    ):
        _require(
            re.fullmatch(r"[0-9a-f]{40}", value) is not None,
            f"pull_request {field} is malformed",
        )


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
    _require_schema_v1(payload.get("schema_version"), "collection evidence")
    _require(payload.get("mode") == "collect", "collection evidence mode mismatch")
    _validate_provenance(payload, expected)
    _require(payload.get("collection_complete") is True, "collection did not complete")
    _require(payload.get("collection_errors") == [], "collection errors were recorded")
    _require(payload.get("deselected_nodeids") == [], "unexpected deselection during collection")
    _require_zero_exit_status(payload.get("session_exit_status"), "collection process")
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
    _require_schema_v1(payload.get("schema_version"), "lane evidence")
    _require(payload.get("mode") == "run", "lane evidence mode mismatch")
    _validate_provenance(payload, expected)
    _require(payload.get("collection_complete") is True, "lane collection did not complete")
    _require(payload.get("collection_errors") == [], "lane collection errors were recorded")
    _require(payload.get("deselected_nodeids") == [], "lane had unexpected deselection")
    _require_zero_exit_status(payload.get("session_exit_status"), "lane process")
    collected = payload.get("collected_nodeids")
    cases = payload.get("cases")
    _require(
        isinstance(collected, list)
        and collected
        and all(isinstance(nodeid, str) and nodeid for nodeid in collected),
        "lane collected inventory is missing or malformed",
    )
    _require(isinstance(cases, list), "lane case outcomes are missing")
    case_nodeids = [case.get("nodeid") for case in cases if isinstance(case, dict)]
    _require(
        len(case_nodeids) == len(cases)
        and all(isinstance(nodeid, str) and nodeid for nodeid in case_nodeids),
        "lane case outcome has invalid shape",
    )
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
        phase_order: list[str] = []
        for phase in phases:
            _require(isinstance(phase, dict), f"invalid phase outcome for {nodeid}")
            _require(
                set(phase) == {"when", "outcome", "reason", "wasxfail"},
                f"phase outcome fields mismatch for {nodeid}",
            )
            when = phase["when"]
            outcome = phase["outcome"]
            reason = phase["reason"]
            wasxfail = phase["wasxfail"]
            _require(isinstance(when, str), f"phase name must be a string for {nodeid}")
            _require(when in {"setup", "call", "teardown"}, f"invalid phase name for {nodeid}")
            _require(when not in by_when, f"duplicate {when} phase for {nodeid}")
            _require(
                isinstance(outcome, str) and outcome in {"passed", "skipped", "failed"},
                f"invalid phase outcome for {nodeid}",
            )
            _require(isinstance(reason, str), f"phase reason must be a string for {nodeid}")
            _require(
                isinstance(wasxfail, str),
                f"phase wasxfail must be a string for {nodeid}",
            )
            _require(wasxfail == "", f"xfail/xpass is not allowed: {nodeid}")
            by_when[when] = phase
            phase_order.append(when)
        failed_phases = [phase for phase in phases if phase["outcome"] == "failed"]
        if failed_phases:
            kind = (
                "failed" if "call" in {phase["when"] for phase in failed_phases} else "errors"
            )
            counts[kind] += 1
            raise ContractError(f"lane contains {kind}: {nodeid}")

        outcomes = [phase["outcome"] for phase in phases]
        passed_pattern = phase_order == ["setup", "call", "teardown"] and outcomes == [
            "passed",
            "passed",
            "passed",
        ]
        setup_skip_pattern = phase_order == ["setup", "teardown"] and outcomes == [
            "skipped",
            "passed",
        ]
        call_skip_pattern = phase_order == ["setup", "call", "teardown"] and outcomes == [
            "passed",
            "skipped",
            "passed",
        ]
        _require(
            passed_pattern or setup_skip_pattern or call_skip_pattern,
            f"illegal phase outcome structure: {nodeid}",
        )
        if setup_skip_pattern or call_skip_pattern:
            skipped_phase = next(phase for phase in phases if phase["outcome"] == "skipped")
            identity = (nodeid, expected.platform, skipped_phase["reason"])
            _require(identity in allowed, f"unexpected skip: {identity}")
            counts["skipped"] += 1
            continue
        counts["passed"] += 1
    return counts


def validate_gate_job_results(*, quality_result: str, test_result: str) -> None:
    _require(quality_result == "success", f"mandatory quality job result is {quality_result}")
    _require(test_result == "success", f"mandatory test job result is {test_result}")


def _one_directory(root: Path, pattern: str, missing_message: str) -> Path:
    matches = [path for path in root.glob(pattern) if path.is_dir()]
    _require(len(matches) == 1, f"{missing_message}: found {len(matches)}")
    return matches[0]


def _artifact_coordinates(path: Path, pattern: str, label: str) -> tuple[str, str]:
    match = re.fullmatch(pattern, path.name)
    _require(match is not None, f"malformed {label} artifact directory: {path.name}")
    assert match is not None
    return match.group("run"), match.group("attempt")


def _parse_metadata(path: Path, *, kind: str) -> dict[str, str]:
    text = _read_required_text(path, f"{kind} metadata")
    lines = text.splitlines()
    _require(lines[0] == f"# CI {kind} identity", f"{kind} metadata header is malformed")
    fields: dict[str, str] = {}
    ordinary = re.compile(r"^- ([^:]+): `(.*)`$")
    workflow = re.compile(r"^- workflow run: `(\d+)` attempt `(\d+)`$")
    pr_identity = re.compile(r"^- (PR (?:base|head) ref/SHA): `(.*)` / `(.*)`$")
    for line in lines[1:]:
        match = workflow.fullmatch(line)
        if match:
            key, value = "workflow run", f"{match.group(1)} attempt {match.group(2)}"
        else:
            match = pr_identity.fullmatch(line)
            if match:
                key, value = match.group(1), f"{match.group(2)} / {match.group(3)}"
            else:
                match = ordinary.fullmatch(line)
                _require(match is not None, f"{kind} metadata line is malformed: {line!r}")
                assert match is not None
                key, value = match.group(1), match.group(2)
        _require(key not in fields, f"{kind} metadata field is duplicated: {key}")
        fields[key] = value
    return fields


def _validate_metadata(
    path: Path,
    *,
    kind: str,
    expected: Mapping[str, str],
    run_id: str,
    attempt: str,
    workflow_identity: ExpectedWorkflowIdentity,
    expected_platform: str,
    expected_environment: EnvironmentIdentity | None = None,
) -> EnvironmentIdentity:
    fields = _parse_metadata(path, kind=kind)
    expected_fields = dict(expected)
    expected_fields.update(
        {
            "event": workflow_identity.event_name,
            "ref": workflow_identity.ref,
            "PR base ref/SHA": (
                f"{workflow_identity.pr_base_ref} / {workflow_identity.pr_base_sha}"
            ),
            "PR head ref/SHA": (
                f"{workflow_identity.pr_head_ref} / {workflow_identity.pr_head_sha}"
            ),
            "workflow run": f"{run_id} attempt {attempt}",
        }
    )
    exact_fields = set(expected_fields) | {"Python", "uv", "runner"}
    _require(
        set(fields) == exact_fields,
        f"{kind} metadata fields mismatch: "
        f"expected={sorted(exact_fields)}; actual={sorted(fields)}",
    )
    for field, value in expected_fields.items():
        _require(fields.get(field) == value, f"{kind} metadata {field} mismatch")
    python = fields["Python"]
    uv = fields["uv"]
    runner = fields["runner"]
    _require(
        re.fullmatch(r"Python 3\.12\.\d+", python) is not None,
        f"{kind} metadata Python identity is malformed",
    )
    _require(
        re.fullmatch(r"uv \d+\.\d+\.\d+ \(x86_64-unknown-linux-gnu\)", uv) is not None,
        f"{kind} metadata uv identity is malformed or platform-incoherent",
    )
    expected_runner = {"linux": "Linux/X64"}.get(expected_platform)
    _require(expected_runner is not None, f"unsupported metadata platform: {expected_platform}")
    _require(
        runner == expected_runner,
        f"{kind} metadata runner platform mismatch: expected {expected_runner}",
    )
    environment = EnvironmentIdentity(python=python, uv=uv, runner=runner)
    if expected_environment is not None:
        _require(
            environment == expected_environment,
            f"{kind} metadata environment mismatch quality",
        )
    return environment


def _validate_git_status(path: Path, *, head_sha: str) -> None:
    lines = _read_required_text(path, "git status evidence").splitlines()
    fields: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"# branch\.([^ ]+) (.+)", line)
        _require(match is not None, f"git status evidence is malformed or dirty: {line!r}")
        assert match is not None
        key, value = match.group(1), match.group(2)
        _require(key not in fields, f"git status evidence field is duplicated: {key}")
        fields[key] = value
    _require(fields.get("oid") == head_sha, "git status evidence HEAD mismatch")
    _require(bool(fields.get("head")), "git status evidence branch head is missing")


def _validate_lock_digest(path: Path, *, lock_sha256: str) -> None:
    text = _read_required_text(path, "lock digest evidence")
    match = re.fullmatch(r"([0-9a-f]{64})  uv\.lock\n?", text)
    _require(match is not None, "lock digest evidence is malformed")
    assert match is not None
    _require(match.group(1) == lock_sha256, "lock digest mismatch")


def _path_name(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1]


def _parent_name(value: str) -> str:
    normalized = value.replace("\\", "/").rstrip("/")
    parts = normalized.split("/")
    return parts[-2] if len(parts) >= 2 else ""


def _validate_lane_command(
    path: Path,
    *,
    lane_dir: Path,
    expected: ExpectedProvenance,
    run_id: str,
    attempt: str,
) -> None:
    text = _read_required_text(path, f"lane {expected.lane} command evidence")
    _require(len(text.splitlines()) == 1, f"lane {expected.lane} command evidence is malformed")
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError as error:
        raise ContractError(f"lane {expected.lane} command evidence is malformed") from error
    _require(len(tokens) >= 3, f"lane {expected.lane} command evidence is malformed")
    _require(
        re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", _path_name(tokens[0])) is not None,
        f"lane {expected.lane} command Python executable is malformed",
    )
    _require(
        tokens[1:3] == ["-m", "pytest"],
        f"lane {expected.lane} command pytest invocation mismatch",
    )
    selection_end = 3 + len(expected.selected_paths)
    _require(
        tokens[3:selection_end] == list(expected.selected_paths),
        f"lane {expected.lane} command selection mismatch",
    )
    options = tokens[selection_end:]
    _require(len(options) >= 7, f"lane {expected.lane} command options are incomplete")
    _require(
        options[:2] == ["--durations=25", "--durations-min=1.0"],
        f"lane {expected.lane} command timing contract mismatch",
    )
    expected_artifact_name = lane_dir.name
    junit = options[2].removeprefix("--junitxml=")
    basetemp = options[3].removeprefix("--basetemp=")
    _require(options[2].startswith("--junitxml="), f"lane {expected.lane} command JUnit is missing")
    _require(
        _path_name(junit) == "junit.xml" and _parent_name(junit) == expected_artifact_name,
        f"lane {expected.lane} command JUnit path mismatch",
    )
    _require(
        options[3].startswith("--basetemp="),
        f"lane {expected.lane} command basetemp is missing",
    )
    _require(
        _path_name(basetemp) == f"pytest-{expected.lane}-{run_id}-{attempt}",
        f"lane {expected.lane} command basetemp mismatch",
    )
    fixed = [
        "-p",
        "scripts.ci_lane_plugin",
    ]
    _require(options[4:6] == fixed, f"lane {expected.lane} command evidence plugin mismatch")
    evidence = options[6].removeprefix("--ci-lane-evidence=")
    _require(
        options[6].startswith("--ci-lane-evidence=")
        and _path_name(evidence) == "lane-evidence.json"
        and _parent_name(evidence) == expected_artifact_name,
        f"lane {expected.lane} command raw evidence path mismatch",
    )
    expected_tail = [
        "--ci-lane-mode=run",
        f"--ci-lane-name={expected.lane}",
        f"--ci-platform={expected.platform}",
        f"--ci-head-sha={expected.head_sha}",
        f"--ci-tree-sha={expected.tree_sha}",
        f"--ci-manifest-sha256={expected.manifest_sha256}",
        f"--ci-selection-sha256={expected.selection_sha256}",
        *(f"--ci-selected-path={selected}" for selected in expected.selected_paths),
    ]
    _require(options[7:] == expected_tail, f"lane {expected.lane} command provenance mismatch")


def validate_gate_artifacts(
    artifacts_root: Path,
    *,
    head_sha: str,
    tree_sha: str,
    manifest_sha256: str,
    workflow_identity: ExpectedWorkflowIdentity,
    expected_platform: str,
    manifest: LaneManifest | None = None,
    lock_sha256: str | None = None,
) -> dict[str, Any]:
    _validate_workflow_identity(workflow_identity)
    _require(expected_platform == "linux", "GitHub workflow gate platform must be linux")
    quality_dir = _one_directory(artifacts_root, "ci-quality-*", "missing quality artifact")
    summary_path = quality_dir / "collection-summary.json"
    summary = _load_json(summary_path)
    _require(isinstance(summary, dict), "quality collection summary is malformed")
    _require_schema_v1(summary.get("schema_version"), "quality collection summary")
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
    _require(
        set(lanes) == set(LANE_NAMES),
        "quality collection summary must contain exactly the three mandatory lanes",
    )
    platform = summary.get("platform")
    _require(
        isinstance(platform, str) and bool(platform),
        "quality collection summary platform is missing or malformed",
    )
    _require(platform == expected_platform, "quality collection summary platform mismatch")
    if manifest is not None:
        _require(lock_sha256 is not None, "expected lock digest is required")
        for required in (
            "metadata.md",
            "git-status.txt",
            "uv-lock.sha256",
            "reference.json",
            "reference-collection.log",
        ):
            _require((quality_dir / required).is_file(), f"missing quality report: {required}")
        quality_run, quality_attempt = _artifact_coordinates(
            quality_dir,
            r"ci-quality-(?P<run>\d+)-(?P<attempt>\d+)",
            "quality",
        )
        quality_environment = _validate_metadata(
            quality_dir / "metadata.md",
            kind="quality",
            expected={
                "event SHA": head_sha,
                "checked-out HEAD": head_sha,
                "checked-out tree": tree_sha,
                "manifest": "ci/test-lanes.json",
                "manifest SHA-256": manifest_sha256,
                "lockfile SHA-256": lock_sha256,
            },
            run_id=quality_run,
            attempt=quality_attempt,
            workflow_identity=workflow_identity,
            expected_platform=platform,
        )
        _validate_git_status(quality_dir / "git-status.txt", head_sha=head_sha)
        _validate_lock_digest(quality_dir / "uv-lock.sha256", lock_sha256=lock_sha256)
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
        _require(isinstance(verified, dict), f"lane {lane} verified evidence is malformed")
        _require_schema_v1(verified.get("schema_version"), f"lane {lane} verified evidence")
        verified_counts = _validate_counts(verified.get("counts"), f"lane {lane} verified")
        for field, expected in (
            ("status", "verified"),
            ("lane", lane),
            ("platform", platform),
            ("head_sha", head_sha),
            ("tree_sha", tree_sha),
            ("manifest_sha256", manifest_sha256),
        ):
            _require(verified.get(field) == expected, f"lane {lane} {field} provenance mismatch")
        expected_nodeids = lanes[lane].get("nodeids", [])
        actual_nodeids = verified.get("nodeids")
        _require(
            isinstance(expected_nodeids, list)
            and expected_nodeids
            and all(isinstance(nodeid, str) and nodeid for nodeid in expected_nodeids),
            f"quality lane {lane} inventory is missing or malformed",
        )
        _require(
            isinstance(actual_nodeids, list)
            and actual_nodeids
            and all(isinstance(nodeid, str) and nodeid for nodeid in actual_nodeids),
            f"lane {lane} verified inventory is missing or malformed",
        )
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
            lane_run, lane_attempt = _artifact_coordinates(
                lane_dir,
                rf"ci-lane-{re.escape(lane)}-(?P<run>\d+)-(?P<attempt>\d+)",
                f"lane {lane}",
            )
            _require(
                (lane_run, lane_attempt) == (quality_run, quality_attempt),
                f"lane {lane} artifact run/attempt mismatch",
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
            assert lock_sha256 is not None
            _validate_metadata(
                lane_dir / "metadata.md",
                kind="lane",
                expected={
                    "lane": lane,
                    "event SHA": head_sha,
                    "checked-out HEAD": head_sha,
                    "checked-out tree": tree_sha,
                    "manifest": "ci/test-lanes.json",
                    "manifest SHA-256": manifest_sha256,
                    "selection SHA-256": selection_sha,
                    "lockfile SHA-256": lock_sha256,
                },
                run_id=lane_run,
                attempt=lane_attempt,
                workflow_identity=workflow_identity,
                expected_platform=platform,
                expected_environment=quality_environment,
            )
            _validate_git_status(lane_dir / "git-status.txt", head_sha=head_sha)
            _validate_lock_digest(lane_dir / "uv-lock.sha256", lock_sha256=lock_sha256)
            _validate_lane_command(
                lane_dir / "command.txt",
                lane_dir=lane_dir,
                expected=expected,
                run_id=lane_run,
                attempt=lane_attempt,
            )
            raw_payload = _load_json(lane_dir / "lane-evidence.json")
            counts = validate_lane_payload(
                raw_payload, expected, allowed_skips=manifest.allowed_skips
            )
            raw_nodeids = raw_payload["collected_nodeids"]
            missing, extra = _counter_delta(Counter(expected_nodeids), Counter(raw_nodeids))
            _require(
                not missing and not extra,
                f"lane {lane} raw inventory mismatch quality: missing={missing}; extra={extra}",
            )
            missing, extra = _counter_delta(Counter(actual_nodeids), Counter(raw_nodeids))
            _require(
                not missing and not extra,
                f"lane {lane} raw inventory mismatch verified: missing={missing}; extra={extra}",
            )
            _require(
                counts == verified_counts,
                f"lane {lane} verified counts mismatch raw outcomes",
            )
            _verify_report_sources(
                lane_dir, counts, len(expected_nodeids), write_summary=False
            )
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


def _verify_report_sources(
    output_dir: Path,
    counts: Mapping[str, int],
    total: int,
    *,
    write_summary: bool = True,
) -> str:
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
    summary_path = output_dir / "summary.md"
    if write_summary:
        summary_path.write_bytes(rendered.encode("utf-8"))
    else:
        try:
            retained_summary = summary_path.read_bytes()
        except OSError as error:
            raise ContractError(
                f"missing or unreadable retained summary: {summary_path}"
            ) from error
        _require(
            retained_summary == rendered.encode("utf-8"),
            "retained summary does not match recomputed JUnit/log/status evidence",
        )
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
    gate_parser.add_argument("--event-name", required=True)
    gate_parser.add_argument("--ref", required=True)
    gate_parser.add_argument("--pr-base-ref", required=True)
    gate_parser.add_argument("--pr-base-sha", required=True)
    gate_parser.add_argument("--pr-head-ref", required=True)
    gate_parser.add_argument("--pr-head-sha", required=True)
    gate_parser.add_argument("--expected-platform", required=True)
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
                workflow_identity=ExpectedWorkflowIdentity(
                    event_name=args.event_name,
                    ref=args.ref,
                    pr_base_ref=args.pr_base_ref,
                    pr_base_sha=args.pr_base_sha,
                    pr_head_ref=args.pr_head_ref,
                    pr_head_sha=args.pr_head_sha,
                ),
                expected_platform=args.expected_platform,
                manifest=manifest,
                lock_sha256=_sha256_bytes((repo_root / "uv.lock").read_bytes()),
            )
            total = len(result["quality"]["reference_nodeids"])
            print(f"checks PASS: {total} exact nodeids reconciled across all mandatory jobs")
    except ContractError as error:
        print(f"CI lane contract failure: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
