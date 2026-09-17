import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

_HELPER_PATH = Path(__file__).parents[1] / "scripts" / "ci_test_lanes.py"
_SPEC = importlib.util.spec_from_file_location("ci_test_lanes", _HELPER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_HELPER = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _HELPER
_SPEC.loader.exec_module(_HELPER)

ContractError = _HELPER.ContractError
ExpectedProvenance = _HELPER.ExpectedProvenance
validate_manifest = _HELPER.validate_manifest
reconcile_collections = _HELPER.reconcile_collections
validate_lane_payload = _HELPER.validate_lane_payload
validate_gate_job_results = _HELPER.validate_gate_job_results
validate_gate_artifacts = _HELPER.validate_gate_artifacts
verify_report_sources = _HELPER._verify_report_sources

LANES = ("garmin", "core-sleep", "app-ingest")


def _write_test(repo: Path, name: str) -> str:
    path = repo / "tests" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def test_synthetic():\n    assert True\n", encoding="utf-8")
    return path.relative_to(repo).as_posix()


def _manifest(repo: Path, lanes: dict[str, list[str]]) -> Path:
    path = repo / "ci" / "test-lanes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "lanes": lanes, "allowed_skips": []}),
        encoding="utf-8",
    )
    return path


def _valid_lane_payload(*, nodeid: str = "tests/test_a.py::test_one") -> dict:
    return {
        "schema_version": 1,
        "mode": "run",
        "lane": "garmin",
        "platform": "linux",
        "head_sha": "a" * 40,
        "tree_sha": "b" * 40,
        "manifest_sha256": "c" * 64,
        "selection_sha256": "d" * 64,
        "selected_paths": ["tests/test_a.py"],
        "collection_complete": True,
        "collected_nodeids": [nodeid],
        "deselected_nodeids": [],
        "collection_errors": [],
        "session_exit_status": 0,
        "cases": [
            {
                "nodeid": nodeid,
                "phases": [
                    {"when": "setup", "outcome": "passed", "reason": "", "wasxfail": ""},
                    {"when": "call", "outcome": "passed", "reason": "", "wasxfail": ""},
                    {
                        "when": "teardown",
                        "outcome": "passed",
                        "reason": "",
                        "wasxfail": "",
                    },
                ],
            }
        ],
    }


def _expected() -> ExpectedProvenance:
    return ExpectedProvenance(
        lane="garmin",
        platform="linux",
        head_sha="a" * 40,
        tree_sha="b" * 40,
        manifest_sha256="c" * 64,
        selection_sha256="d" * 64,
        selected_paths=("tests/test_a.py",),
    )


def test_manifest_and_exact_collection_multisets_accept_complete_partition(tmp_path):
    paths = [_write_test(tmp_path, f"test_{name}.py") for name in ("a", "b", "c")]
    manifest = _manifest(
        tmp_path,
        {lane: [path] for lane, path in zip(LANES, paths, strict=True)},
    )

    parsed = validate_manifest(manifest, tmp_path)
    reference = ["a::test_one", "b::test_two", "b::test_two", "c::test_three"]
    lane_nodeids = {
        "garmin": ["a::test_one"],
        "core-sleep": ["b::test_two", "b::test_two"],
        "app-ingest": ["c::test_three"],
    }

    assert set(parsed.lanes) == set(LANES)
    assert reconcile_collections(reference, lane_nodeids) == Counter(reference)


@pytest.mark.parametrize("failure", ["unassigned", "overlap", "stale", "empty"])
def test_manifest_rejects_assignment_gaps_overlap_stale_and_empty(tmp_path, failure):
    paths = [_write_test(tmp_path, f"test_{name}.py") for name in ("a", "b", "c")]
    lanes = {lane: [path] for lane, path in zip(LANES, paths, strict=True)}
    if failure == "unassigned":
        _write_test(tmp_path, "test_new.py")
    elif failure == "overlap":
        lanes["core-sleep"].append(paths[0])
    elif failure == "stale":
        lanes["garmin"] = ["tests/test_missing.py"]
    else:
        lanes["garmin"] = []

    with pytest.raises(ContractError):
        validate_manifest(_manifest(tmp_path, lanes), tmp_path)


def test_collection_reconciliation_rejects_count_preserving_substitution():
    reference = [
        "tests/test_a.py::test_one",
        "tests/test_b.py::test_two",
        "tests/test_d.py::test_four",
    ]
    lanes = {
        "garmin": ["tests/test_a.py::test_one"],
        "core-sleep": ["tests/test_c.py::test_three"],
        "app-ingest": ["tests/test_d.py::test_four"],
    }

    with pytest.raises(ContractError, match="missing=.*test_b.*extra=.*test_c"):
        reconcile_collections(reference, lanes)


@pytest.mark.parametrize(
    ("field", "value"),
    (("head_sha", "e" * 40), ("tree_sha", "f" * 40), ("selection_sha256", "0" * 64)),
)
def test_lane_evidence_rejects_wrong_sha_tree_or_selection(field, value):
    payload = _valid_lane_payload()
    payload[field] = value

    with pytest.raises(ContractError, match=field):
        validate_lane_payload(payload, _expected(), allowed_skips=())


def test_lane_evidence_rejects_unexpected_skip_deselection_and_xfail():
    skipped = _valid_lane_payload()
    skipped["cases"][0]["phases"][1] = {
        "when": "call",
        "outcome": "skipped",
        "reason": "not reviewed",
        "wasxfail": "",
    }
    deselected = _valid_lane_payload()
    deselected["deselected_nodeids"] = ["tests/test_a.py::test_one"]
    xfailed = _valid_lane_payload()
    xfailed["cases"][0]["phases"][1] = {
        "when": "call",
        "outcome": "skipped",
        "reason": "known bug",
        "wasxfail": "known bug",
    }

    for payload in (skipped, deselected, xfailed):
        with pytest.raises(ContractError):
            validate_lane_payload(payload, _expected(), allowed_skips=())


def test_lane_evidence_accepts_only_exact_platform_skip_allowlist():
    payload = _valid_lane_payload(nodeid="tests/test_a.py::test_linux_only")
    payload["cases"][0]["phases"] = [
        {
            "when": "setup",
            "outcome": "skipped",
            "reason": "Windows DPAPI regression",
            "wasxfail": "",
        },
        {"when": "teardown", "outcome": "passed", "reason": "", "wasxfail": ""},
    ]
    allowed = (
        {
            "nodeid": "tests/test_a.py::test_linux_only",
            "platform": "linux",
            "reason": "Windows DPAPI regression",
        },
    )

    result = validate_lane_payload(payload, _expected(), allowed_skips=allowed)
    assert result == {"passed": 0, "skipped": 1, "failed": 0, "errors": 0}

    payload["platform"] = "win32"
    with pytest.raises(ContractError):
        validate_lane_payload(payload, _expected(), allowed_skips=allowed)


@pytest.mark.parametrize("incomplete", ["collection", "exit", "case"])
def test_lane_evidence_rejects_incomplete_or_killed_worker(incomplete):
    payload = _valid_lane_payload()
    if incomplete == "collection":
        payload["collection_complete"] = False
    elif incomplete == "exit":
        payload["session_exit_status"] = 2
    else:
        payload["cases"][0]["phases"].pop()

    with pytest.raises(ContractError):
        validate_lane_payload(payload, _expected(), allowed_skips=())


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped"])
def test_gate_rejects_failed_cancelled_or_skipped_mandatory_job(result):
    with pytest.raises(ContractError, match=result):
        validate_gate_job_results(quality_result="success", test_result=result)


def test_gate_rejects_missing_or_mismatched_artifacts(tmp_path):
    quality = tmp_path / "ci-quality-1"
    quality.mkdir()
    (quality / "collection-summary.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "platform": "linux",
                "head_sha": "a" * 40,
                "tree_sha": "b" * 40,
                "manifest_sha256": "c" * 64,
                "lanes": {lane: {"nodeids": [f"{lane}::test"]} for lane in LANES},
                "reference_nodeids": [f"{lane}::test" for lane in LANES],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ContractError, match="missing lane artifact"):
        validate_gate_artifacts(
            tmp_path,
            head_sha="a" * 40,
            tree_sha="b" * 40,
            manifest_sha256="c" * 64,
        )

    for lane in LANES:
        lane_dir = tmp_path / f"ci-lane-{lane}-1"
        lane_dir.mkdir()
        payload = _valid_lane_payload(nodeid=f"{lane}::test")
        payload["lane"] = lane
        payload["status"] = "verified"
        (lane_dir / "verified.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "ci-lane-garmin-1" / "verified.json").write_text(
        json.dumps(
            {
                **_valid_lane_payload(),
                "status": "verified",
                "lane": "garmin",
                "tree_sha": "f" * 40,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ContractError, match="tree_sha"):
        validate_gate_artifacts(
            tmp_path,
            head_sha="a" * 40,
            tree_sha="b" * 40,
            manifest_sha256="c" * 64,
        )


def test_lane_report_reconciliation_rejects_missing_and_mismatched_sources(tmp_path):
    counts = {"passed": 1, "skipped": 0, "failed": 0, "errors": 0}
    (tmp_path / "junit.xml").write_text(
        '<testsuite tests="1" failures="0" errors="0" skipped="0">'
        '<testcase classname="synthetic" name="test_one" time="0.1" />'
        "</testsuite>",
        encoding="utf-8",
    )
    (tmp_path / "pytest-status.txt").write_text("pytest_exit_status=0\n", encoding="utf-8")

    with pytest.raises(ContractError, match="missing or incomplete"):
        verify_report_sources(tmp_path, counts, 1)

    (tmp_path / "pytest.log").write_text(
        "collected 2 items\n================ 2 passed in 0.1s ================\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="pytest log evidence mismatch"):
        verify_report_sources(tmp_path, counts, 1)
