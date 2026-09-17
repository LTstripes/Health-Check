import importlib.util
import json
import sys
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

_HELPER_PATH = Path(__file__).parents[1] / "scripts" / "ci_test_lanes.py"
sys.path.insert(0, str(_HELPER_PATH.parent))
_SPEC = importlib.util.spec_from_file_location("ci_test_lanes", _HELPER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_HELPER = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _HELPER
_SPEC.loader.exec_module(_HELPER)

ContractError = _HELPER.ContractError
ExpectedProvenance = _HELPER.ExpectedProvenance
ExpectedWorkflowIdentity = _HELPER.ExpectedWorkflowIdentity
validate_manifest = _HELPER.validate_manifest
reconcile_collections = _HELPER.reconcile_collections
validate_lane_payload = _HELPER.validate_lane_payload
validate_gate_job_results = _HELPER.validate_gate_job_results
validate_gate_artifacts = _HELPER.validate_gate_artifacts
verify_report_sources = _HELPER._verify_report_sources
selection_sha256 = _HELPER._selection_sha256

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


def _metadata_text(
    *,
    kind: str,
    head_sha: str,
    tree_sha: str,
    manifest_sha256: str,
    lock_sha256: str,
    run_id: str,
    attempt: str,
    lane: str | None = None,
    selection_sha: str | None = None,
    workflow_identity: object | None = None,
) -> str:
    identity = workflow_identity or _push_identity()
    lines = [f"# CI {kind} identity"]
    if lane is not None:
        lines.append(f"- lane: `{lane}`")
    lines.extend(
        (
            f"- event: `{identity.event_name}`",
            f"- ref: `{identity.ref}`",
            f"- event SHA: `{head_sha}`",
            f"- checked-out HEAD: `{head_sha}`",
            f"- checked-out tree: `{tree_sha}`",
            f"- PR base ref/SHA: `{identity.pr_base_ref}` / `{identity.pr_base_sha}`",
            f"- PR head ref/SHA: `{identity.pr_head_ref}` / `{identity.pr_head_sha}`",
            f"- workflow run: `{run_id}` attempt `{attempt}`",
            "- manifest: `ci/test-lanes.json`",
            f"- manifest SHA-256: `{manifest_sha256}`",
        )
    )
    if selection_sha is not None:
        lines.append(f"- selection SHA-256: `{selection_sha}`")
    lines.extend(
        (
            f"- lockfile SHA-256: `{lock_sha256}`",
            "- Python: `Python 3.12.0`",
            "- uv: `uv 0.12.0 (x86_64-unknown-linux-gnu)`",
            "- runner: `Linux/X64`",
        )
    )
    return "\n".join(lines) + "\n"


def _push_identity() -> ExpectedWorkflowIdentity:
    return ExpectedWorkflowIdentity(
        event_name="push",
        ref="refs/heads/task/synthetic",
        pr_base_ref="",
        pr_base_sha="",
        pr_head_ref="",
        pr_head_sha="",
    )


def _pr_identity() -> ExpectedWorkflowIdentity:
    return ExpectedWorkflowIdentity(
        event_name="pull_request",
        ref="refs/pull/17/merge",
        pr_base_ref="integration/ci-feedback-v1",
        pr_base_sha="1" * 40,
        pr_head_ref="task/synthetic",
        pr_head_sha="2" * 40,
    )


def _collection_payload(expected: ExpectedProvenance, nodeids: list[str]) -> dict:
    return {
        "schema_version": 1,
        "mode": "collect",
        "lane": expected.lane,
        "platform": expected.platform,
        "head_sha": expected.head_sha,
        "tree_sha": expected.tree_sha,
        "manifest_sha256": expected.manifest_sha256,
        "selection_sha256": expected.selection_sha256,
        "selected_paths": list(expected.selected_paths),
        "collection_complete": True,
        "collected_nodeids": nodeids,
        "deselected_nodeids": [],
        "collection_errors": [],
        "session_exit_status": 0,
    }


def _complete_gate_fixture(
    tmp_path: Path, workflow_identity: ExpectedWorkflowIdentity | None = None
) -> tuple[Path, object, str, str, str]:
    identity = workflow_identity or _push_identity()
    repo = tmp_path / "repo"
    paths = [_write_test(repo, f"test_{name}.py") for name in ("a", "b", "c")]
    manifest = validate_manifest(
        _manifest(repo, {lane: [path] for lane, path in zip(LANES, paths, strict=True)}),
        repo,
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    head_sha = "a" * 40
    tree_sha = "b" * 40
    lock_sha = "e" * 64
    run_id = "123"
    attempt = "1"
    platform = "linux"
    nodeids = {lane: [f"{path}::test_synthetic"] for lane, path in zip(LANES, paths, strict=True)}

    quality = artifacts / f"ci-quality-{run_id}-{attempt}"
    quality.mkdir()
    (quality / "metadata.md").write_text(
        _metadata_text(
            kind="quality",
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest.sha256,
            lock_sha256=lock_sha,
            run_id=run_id,
            attempt=attempt,
            workflow_identity=identity,
        ),
        encoding="utf-8",
    )
    (quality / "git-status.txt").write_text(
        f"# branch.oid {head_sha}\n# branch.head task/synthetic\n", encoding="utf-8"
    )
    (quality / "uv-lock.sha256").write_text(f"{lock_sha}  uv.lock\n", encoding="utf-8")
    reference = [nodeid for lane in LANES for nodeid in nodeids[lane]]
    summary_lanes = {}
    reference_expected = ExpectedProvenance(
        lane="reference",
        platform=platform,
        head_sha=head_sha,
        tree_sha=tree_sha,
        manifest_sha256=manifest.sha256,
        selection_sha256=selection_sha256(()),
        selected_paths=(),
    )
    (quality / "reference.json").write_text(
        json.dumps(_collection_payload(reference_expected, reference)), encoding="utf-8"
    )
    (quality / "reference-collection.log").write_text("3 tests collected\n", encoding="utf-8")
    for lane in LANES:
        selected_paths = manifest.lanes[lane]
        selection_sha = selection_sha256(selected_paths)
        expected = ExpectedProvenance(
            lane=lane,
            platform=platform,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest.sha256,
            selection_sha256=selection_sha,
            selected_paths=selected_paths,
        )
        summary_lanes[lane] = {
            "selected_paths": list(selected_paths),
            "selection_sha256": selection_sha,
            "nodeids": nodeids[lane],
        }
        (quality / f"{lane}-collection.json").write_text(
            json.dumps(_collection_payload(expected, nodeids[lane])), encoding="utf-8"
        )
        (quality / f"{lane}-collection.log").write_text("1 test collected\n", encoding="utf-8")
    (quality / "collection-summary.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "platform": platform,
                "head_sha": head_sha,
                "tree_sha": tree_sha,
                "manifest_sha256": manifest.sha256,
                "lanes": summary_lanes,
                "reference_nodeids": reference,
            }
        ),
        encoding="utf-8",
    )

    for lane in LANES:
        selected_paths = manifest.lanes[lane]
        selection_sha = selection_sha256(selected_paths)
        lane_dir = artifacts / f"ci-lane-{lane}-{run_id}-{attempt}"
        lane_dir.mkdir()
        expected = ExpectedProvenance(
            lane=lane,
            platform=platform,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest.sha256,
            selection_sha256=selection_sha,
            selected_paths=selected_paths,
        )
        payload = _valid_lane_payload(nodeid=nodeids[lane][0])
        payload.update(
            {
                "lane": lane,
                "platform": platform,
                "head_sha": head_sha,
                "tree_sha": tree_sha,
                "manifest_sha256": manifest.sha256,
                "selection_sha256": selection_sha,
                "selected_paths": list(selected_paths),
            }
        )
        counts = {"passed": 1, "skipped": 0, "failed": 0, "errors": 0}
        (lane_dir / "lane-evidence.json").write_text(json.dumps(payload), encoding="utf-8")
        (lane_dir / "verified.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "verified",
                    "lane": lane,
                    "platform": platform,
                    "head_sha": head_sha,
                    "tree_sha": tree_sha,
                    "manifest_sha256": manifest.sha256,
                    "selection_sha256": selection_sha,
                    "selected_paths": list(selected_paths),
                    "nodeids": nodeids[lane],
                    "counts": counts,
                }
            ),
            encoding="utf-8",
        )
        (lane_dir / "metadata.md").write_text(
            _metadata_text(
                kind="lane",
                head_sha=head_sha,
                tree_sha=tree_sha,
                manifest_sha256=manifest.sha256,
                lock_sha256=lock_sha,
                run_id=run_id,
                attempt=attempt,
                lane=lane,
                selection_sha=selection_sha,
                workflow_identity=identity,
            ),
            encoding="utf-8",
        )
        (lane_dir / "git-status.txt").write_text(
            f"# branch.oid {head_sha}\n# branch.head task/synthetic\n", encoding="utf-8"
        )
        (lane_dir / "uv-lock.sha256").write_text(f"{lock_sha}  uv.lock\n", encoding="utf-8")
        artifact_stem = lane_dir.name
        command = [
            "/venv/bin/python",
            "-m",
            "pytest",
            *selected_paths,
            "--durations=25",
            "--durations-min=1.0",
            f"--junitxml=/tmp/{artifact_stem}/junit.xml",
            f"--basetemp=/tmp/pytest-{lane}-{run_id}-{attempt}",
            "-p",
            "scripts.ci_lane_plugin",
            f"--ci-lane-evidence=/tmp/{artifact_stem}/lane-evidence.json",
            "--ci-lane-mode=run",
            f"--ci-lane-name={lane}",
            f"--ci-platform={platform}",
            f"--ci-head-sha={head_sha}",
            f"--ci-tree-sha={tree_sha}",
            f"--ci-manifest-sha256={manifest.sha256}",
            f"--ci-selection-sha256={selection_sha}",
            *(f"--ci-selected-path={path}" for path in selected_paths),
        ]
        (lane_dir / "command.txt").write_text(" ".join(command) + "\n", encoding="utf-8")
        (lane_dir / "junit.xml").write_text(
            '<testsuite tests="1" failures="0" errors="0" skipped="0">'
            '<testcase classname="synthetic" name="test_synthetic" time="0.1" />'
            "</testsuite>",
            encoding="utf-8",
        )
        (lane_dir / "pytest.log").write_text(
            "collected 1 item\n================ 1 passed in 0.1s ================\n",
            encoding="utf-8",
        )
        (lane_dir / "pytest-status.txt").write_text("pytest_exit_status=0\n", encoding="utf-8")
        verify_report_sources(lane_dir, counts, 1)
    return artifacts, manifest, head_sha, tree_sha, lock_sha


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


@pytest.mark.parametrize("schema_version", (True, "1", 1.0, 2, None))
def test_manifest_requires_strict_integer_schema_v1(tmp_path, schema_version):
    paths = [_write_test(tmp_path, f"test_{name}.py") for name in ("a", "b", "c")]
    manifest_path = _manifest(
        tmp_path,
        {lane: [path] for lane, path in zip(LANES, paths, strict=True)},
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["schema_version"] = schema_version
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContractError, match="schema_version must be integer 1"):
        validate_manifest(manifest_path, tmp_path)


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


@pytest.mark.parametrize("schema_version", (True, "1", 1.0, 2, None))
def test_lane_evidence_requires_strict_integer_schema_v1(schema_version):
    payload = _valid_lane_payload()
    payload["schema_version"] = schema_version

    with pytest.raises(ContractError, match="schema_version must be integer 1"):
        validate_lane_payload(payload, _expected(), allowed_skips=())


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        ("missing_reason", "phase outcome fields mismatch"),
        ("missing_wasxfail", "phase outcome fields mismatch"),
        ("extra_field", "phase outcome fields mismatch"),
        ("reason_bool", "phase reason must be a string"),
        ("reason_none", "phase reason must be a string"),
        ("wasxfail_bool", "phase wasxfail must be a string"),
        ("wasxfail_none", "phase wasxfail must be a string"),
    ),
)
def test_lane_evidence_requires_exact_typed_phase_schema(mutation, match):
    payload = _valid_lane_payload()
    phase = payload["cases"][0]["phases"][1]
    if mutation == "missing_reason":
        phase.pop("reason")
    elif mutation == "missing_wasxfail":
        phase.pop("wasxfail")
    elif mutation == "extra_field":
        phase["unexpected"] = ""
    elif mutation == "reason_bool":
        phase["reason"] = False
    elif mutation == "reason_none":
        phase["reason"] = None
    elif mutation == "wasxfail_bool":
        phase["wasxfail"] = False
    else:
        phase["wasxfail"] = None

    with pytest.raises(ContractError, match=match):
        validate_lane_payload(payload, _expected(), allowed_skips=())


def test_lane_evidence_rejects_removed_xfail_marker_field():
    payload = _valid_lane_payload()
    phase = payload["cases"][0]["phases"][1]
    phase.update(outcome="skipped", reason="known bug", wasxfail="known bug")
    phase.pop("wasxfail")

    with pytest.raises(ContractError, match="phase outcome fields mismatch"):
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
            workflow_identity=_push_identity(),
            expected_platform="linux",
        )

    for lane in LANES:
        lane_dir = tmp_path / f"ci-lane-{lane}-1"
        lane_dir.mkdir()
        payload = _valid_lane_payload(nodeid=f"{lane}::test")
        payload["lane"] = lane
        payload["status"] = "verified"
        payload["counts"] = {"passed": 1, "skipped": 0, "failed": 0, "errors": 0}
        (lane_dir / "verified.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "ci-lane-garmin-1" / "verified.json").write_text(
        json.dumps(
            {
                **_valid_lane_payload(),
                "status": "verified",
                "lane": "garmin",
                "tree_sha": "f" * 40,
                "counts": {"passed": 1, "skipped": 0, "failed": 0, "errors": 0},
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
            workflow_identity=_push_identity(),
            expected_platform="linux",
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


def test_final_gate_rejects_same_count_raw_lane_inventory_substitution(tmp_path):
    artifacts, manifest, head_sha, tree_sha, lock_sha = _complete_gate_fixture(tmp_path)
    lane_path = artifacts / "ci-lane-garmin-123-1" / "lane-evidence.json"
    payload = json.loads(lane_path.read_text(encoding="utf-8"))
    substituted = "tests/test_a.py::test_substituted"
    payload["collected_nodeids"] = [substituted]
    payload["cases"][0]["nodeid"] = substituted
    lane_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContractError, match="raw inventory mismatch"):
        validate_gate_artifacts(
            artifacts,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest.sha256,
            manifest=manifest,
            lock_sha256=lock_sha,
            workflow_identity=_push_identity(),
            expected_platform="linux",
        )


@pytest.mark.parametrize("mutation", ("missing", "alias"))
def test_final_gate_requires_canonical_verified_nodeids_field(tmp_path, mutation):
    artifacts, manifest, head_sha, tree_sha, lock_sha = _complete_gate_fixture(tmp_path)
    verified_path = artifacts / "ci-lane-garmin-123-1" / "verified.json"
    payload = json.loads(verified_path.read_text(encoding="utf-8"))
    nodeids = payload.pop("nodeids")
    if mutation == "alias":
        payload["collected_nodeids"] = nodeids
    verified_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContractError, match="verified inventory is missing or malformed"):
        validate_gate_artifacts(
            artifacts,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest.sha256,
            manifest=manifest,
            lock_sha256=lock_sha,
            workflow_identity=_push_identity(),
            expected_platform="linux",
        )


def test_final_gate_accepts_complete_bound_artifacts(tmp_path):
    artifacts, manifest, head_sha, tree_sha, lock_sha = _complete_gate_fixture(tmp_path)

    result = validate_gate_artifacts(
        artifacts,
        head_sha=head_sha,
        tree_sha=tree_sha,
        manifest_sha256=manifest.sha256,
        manifest=manifest,
        lock_sha256=lock_sha,
        workflow_identity=_push_identity(),
        expected_platform="linux",
    )

    assert result["quality"]["reference_nodeids"] == [
        "tests/test_a.py::test_synthetic",
        "tests/test_b.py::test_synthetic",
        "tests/test_c.py::test_synthetic",
    ]


def test_final_gate_requires_linux_as_the_explicit_expected_platform(tmp_path):
    artifacts, manifest, head_sha, tree_sha, lock_sha = _complete_gate_fixture(tmp_path)

    with pytest.raises(ContractError, match="platform must be linux"):
        validate_gate_artifacts(
            artifacts,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest.sha256,
            manifest=manifest,
            lock_sha256=lock_sha,
            workflow_identity=_push_identity(),
            expected_platform="win32",
        )


def test_final_gate_accepts_exact_pull_request_identity(tmp_path):
    identity = _pr_identity()
    artifacts, manifest, head_sha, tree_sha, lock_sha = _complete_gate_fixture(
        tmp_path, identity
    )

    result = validate_gate_artifacts(
        artifacts,
        head_sha=head_sha,
        tree_sha=tree_sha,
        manifest_sha256=manifest.sha256,
        manifest=manifest,
        lock_sha256=lock_sha,
        workflow_identity=identity,
        expected_platform="linux",
    )

    assert len(result["quality"]["reference_nodeids"]) == 3


@pytest.mark.parametrize(
    "identity",
    (
        replace(_push_identity(), event_name="schedule"),
        replace(_push_identity(), ref="task/synthetic"),
        replace(_push_identity(), pr_head_ref="task/unexpected"),
        replace(_pr_identity(), ref="refs/heads/task/synthetic"),
        replace(_pr_identity(), pr_head_sha=""),
    ),
)
def test_final_gate_rejects_incoherent_expected_workflow_identity(tmp_path, identity):
    artifacts, manifest, head_sha, tree_sha, lock_sha = _complete_gate_fixture(tmp_path)

    with pytest.raises(ContractError, match="workflow|pull_request|push"):
        validate_gate_artifacts(
            artifacts,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest.sha256,
            manifest=manifest,
            lock_sha256=lock_sha,
            workflow_identity=identity,
            expected_platform="linux",
        )


def test_final_gate_rejects_wrong_pull_request_base_head_identity(tmp_path):
    identity = _pr_identity()
    artifacts, manifest, head_sha, tree_sha, lock_sha = _complete_gate_fixture(
        tmp_path, identity
    )
    metadata = artifacts / "ci-lane-app-ingest-123-1" / "metadata.md"
    original = metadata.read_text(encoding="utf-8")
    metadata.write_text(
        original.replace(identity.pr_head_sha, "3" * 40, 1), encoding="utf-8"
    )

    with pytest.raises(ContractError, match="lane metadata PR head ref/SHA mismatch"):
        validate_gate_artifacts(
            artifacts,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest.sha256,
            manifest=manifest,
            lock_sha256=lock_sha,
            workflow_identity=identity,
            expected_platform="linux",
        )


@pytest.mark.parametrize(
    ("artifact", "old", "new"),
    (
        ("ci-quality-123-1", "- event: `push`\n", ""),
        ("ci-quality-123-1", "- event: `push`", "- event: `pull_request`"),
        ("ci-quality-123-1", "- ref: `refs/heads/task/synthetic`\n", ""),
        (
            "ci-quality-123-1",
            "- ref: `refs/heads/task/synthetic`",
            "- ref: `refs/heads/task/wrong`",
        ),
        ("ci-quality-123-1", "- PR base ref/SHA: `` / ``\n", ""),
        (
            "ci-quality-123-1",
            "- PR base ref/SHA: `` / ``",
            f"- PR base ref/SHA: `main` / `{'1' * 40}`",
        ),
        ("ci-quality-123-1", "- PR head ref/SHA: `` / ``\n", ""),
        (
            "ci-quality-123-1",
            "- PR head ref/SHA: `` / ``",
            f"- PR head ref/SHA: `task/wrong` / `{'2' * 40}`",
        ),
        (
            "ci-lane-garmin-123-1",
            "- ref: `refs/heads/task/synthetic`",
            "- ref: `refs/heads/task/other`",
        ),
    ),
)
def test_final_gate_rejects_partial_wrong_or_cross_artifact_workflow_identity(
    tmp_path, artifact, old, new
):
    artifacts, manifest, head_sha, tree_sha, lock_sha = _complete_gate_fixture(tmp_path)
    metadata = artifacts / artifact / "metadata.md"
    original = metadata.read_text(encoding="utf-8")
    assert old in original
    metadata.write_text(original.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(ContractError, match="metadata"):
        validate_gate_artifacts(
            artifacts,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest.sha256,
            manifest=manifest,
            lock_sha256=lock_sha,
            workflow_identity=_push_identity(),
            expected_platform="linux",
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_schema",
        "true_schema",
        "string_schema",
        "float_schema",
        "wrong_schema",
        "missing_lane",
        "extra_lane",
    ),
)
def test_final_gate_rejects_malformed_quality_summary_shape(tmp_path, mutation):
    artifacts, manifest, head_sha, tree_sha, lock_sha = _complete_gate_fixture(tmp_path)
    summary_path = artifacts / "ci-quality-123-1" / "collection-summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if mutation == "missing_schema":
        summary.pop("schema_version")
    elif mutation == "true_schema":
        summary["schema_version"] = True
    elif mutation == "string_schema":
        summary["schema_version"] = "1"
    elif mutation == "float_schema":
        summary["schema_version"] = 1.0
    elif mutation == "wrong_schema":
        summary["schema_version"] = 2
    elif mutation == "missing_lane":
        summary["lanes"].pop("garmin")
    else:
        summary["lanes"]["fourth"] = deepcopy(summary["lanes"]["garmin"])
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(ContractError, match="quality collection summary"):
        validate_gate_artifacts(
            artifacts,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest.sha256,
            manifest=manifest,
            lock_sha256=lock_sha,
            workflow_identity=_push_identity(),
            expected_platform="linux",
        )


@pytest.mark.parametrize(
    "relative_path",
    (
        "ci-quality-123-1/reference.json",
        "ci-quality-123-1/garmin-collection.json",
        "ci-lane-garmin-123-1/lane-evidence.json",
        "ci-lane-garmin-123-1/verified.json",
    ),
)
def test_final_gate_rejects_boolean_schema_at_every_evidence_boundary(
    tmp_path, relative_path
):
    artifacts, manifest, head_sha, tree_sha, lock_sha = _complete_gate_fixture(tmp_path)
    evidence_path = artifacts / relative_path
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload["schema_version"] = True
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContractError, match="schema_version must be integer 1"):
        validate_gate_artifacts(
            artifacts,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest.sha256,
            manifest=manifest,
            lock_sha256=lock_sha,
            workflow_identity=_push_identity(),
            expected_platform="linux",
        )


@pytest.mark.parametrize(
    ("relative_path", "value"),
    (
        ("ci-quality-123-1/reference.json", False),
        ("ci-quality-123-1/reference.json", 0.0),
        ("ci-quality-123-1/garmin-collection.json", False),
        ("ci-quality-123-1/garmin-collection.json", 0.0),
    ),
)
def test_final_gate_requires_integer_collection_exit_status(tmp_path, relative_path, value):
    artifacts, manifest, head_sha, tree_sha, lock_sha = _complete_gate_fixture(tmp_path)
    evidence_path = artifacts / relative_path
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload["session_exit_status"] = value
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContractError, match="collection process must be an integer"):
        validate_gate_artifacts(
            artifacts,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest.sha256,
            manifest=manifest,
            lock_sha256=lock_sha,
            workflow_identity=_push_identity(),
            expected_platform="linux",
        )


@pytest.mark.parametrize("value", (False, 0.0))
def test_final_gate_requires_integer_lane_exit_status(tmp_path, value):
    artifacts, manifest, head_sha, tree_sha, lock_sha = _complete_gate_fixture(tmp_path)
    evidence_path = artifacts / "ci-lane-garmin-123-1" / "lane-evidence.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload["session_exit_status"] = value
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContractError, match="lane process must be an integer"):
        validate_gate_artifacts(
            artifacts,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest.sha256,
            manifest=manifest,
            lock_sha256=lock_sha,
            workflow_identity=_push_identity(),
            expected_platform="linux",
        )


@pytest.mark.parametrize(
    ("count_name", "value"),
    (
        ("passed", True),
        ("passed", 1.0),
        ("skipped", False),
        ("skipped", 0.0),
        ("failed", False),
        ("failed", 0.0),
        ("errors", False),
        ("errors", 0.0),
    ),
)
def test_final_gate_requires_integer_verified_counts(tmp_path, count_name, value):
    artifacts, manifest, head_sha, tree_sha, lock_sha = _complete_gate_fixture(tmp_path)
    evidence_path = artifacts / "ci-lane-garmin-123-1" / "verified.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload["counts"][count_name] = value
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContractError, match=f"{count_name} count must be an integer"):
        validate_gate_artifacts(
            artifacts,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest.sha256,
            manifest=manifest,
            lock_sha256=lock_sha,
            workflow_identity=_push_identity(),
            expected_platform="linux",
        )


@pytest.mark.parametrize("mutation", ("missing", "extra", "negative"))
def test_final_gate_requires_exact_nonnegative_verified_count_shape(tmp_path, mutation):
    artifacts, manifest, head_sha, tree_sha, lock_sha = _complete_gate_fixture(tmp_path)
    evidence_path = artifacts / "ci-lane-garmin-123-1" / "verified.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    if mutation == "missing":
        payload["counts"].pop("errors")
    elif mutation == "extra":
        payload["counts"]["deselected"] = 0
    else:
        payload["counts"]["failed"] = -1
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")

    match = "count fields mismatch" if mutation != "negative" else "must be nonnegative"
    with pytest.raises(ContractError, match=match):
        validate_gate_artifacts(
            artifacts,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest.sha256,
            manifest=manifest,
            lock_sha256=lock_sha,
            workflow_identity=_push_identity(),
            expected_platform="linux",
        )


@pytest.mark.parametrize(
    ("relative_path", "value", "remove"),
    (
        ("ci-quality-123-1/collection-summary.json", None, True),
        ("ci-quality-123-1/collection-summary.json", True, False),
        ("ci-quality-123-1/collection-summary.json", "win32", False),
        ("ci-quality-123-1/reference.json", True, False),
        ("ci-quality-123-1/garmin-collection.json", "win32", False),
        ("ci-lane-garmin-123-1/lane-evidence.json", "win32", False),
        ("ci-lane-garmin-123-1/verified.json", True, False),
    ),
)
def test_final_gate_rejects_missing_wrong_or_boolean_platform(
    tmp_path, relative_path, value, remove
):
    artifacts, manifest, head_sha, tree_sha, lock_sha = _complete_gate_fixture(tmp_path)
    evidence_path = artifacts / relative_path
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    if remove:
        payload.pop("platform")
    else:
        payload["platform"] = value
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ContractError, match="platform"):
        validate_gate_artifacts(
            artifacts,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest.sha256,
            manifest=manifest,
            lock_sha256=lock_sha,
            workflow_identity=_push_identity(),
            expected_platform="linux",
        )


@pytest.mark.parametrize(
    ("relative_path", "field", "original", "replacement", "match"),
    (
        (
            "ci-quality-123-1/metadata.md",
            "runner",
            "Linux/X64",
            "Windows/X64",
            "quality metadata runner platform mismatch",
        ),
        (
            "ci-lane-garmin-123-1/metadata.md",
            "runner",
            "Linux/X64",
            "Windows/X64",
            "lane metadata runner platform mismatch",
        ),
        (
            "ci-quality-123-1/metadata.md",
            "Python",
            "Python 3.12.0",
            "CPython 3.12.0",
            "quality metadata Python identity is malformed",
        ),
        (
            "ci-quality-123-1/metadata.md",
            "uv",
            "uv 0.12.0 (x86_64-unknown-linux-gnu)",
            "uv latest",
            "quality metadata uv identity is malformed",
        ),
        (
            "ci-lane-garmin-123-1/metadata.md",
            "Python",
            "Python 3.12.0",
            "Python 3.12.1",
            "lane metadata environment mismatch quality",
        ),
        (
            "ci-lane-garmin-123-1/metadata.md",
            "uv",
            "uv 0.12.0 (x86_64-unknown-linux-gnu)",
            "uv 0.12.1 (x86_64-unknown-linux-gnu)",
            "lane metadata environment mismatch quality",
        ),
    ),
)
def test_final_gate_rejects_wrong_or_incoherent_environment_metadata(
    tmp_path, relative_path, field, original, replacement, match
):
    artifacts, manifest, head_sha, tree_sha, lock_sha = _complete_gate_fixture(tmp_path)
    metadata_path = artifacts / relative_path
    metadata = metadata_path.read_text(encoding="utf-8")
    original_line = f"- {field}: `{original}`"
    assert original_line in metadata
    metadata_path.write_text(
        metadata.replace(original_line, f"- {field}: `{replacement}`"),
        encoding="utf-8",
    )

    with pytest.raises(ContractError, match=match):
        validate_gate_artifacts(
            artifacts,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest.sha256,
            manifest=manifest,
            lock_sha256=lock_sha,
            workflow_identity=_push_identity(),
            expected_platform="linux",
        )


def test_final_gate_validation_is_byte_for_byte_read_only(tmp_path):
    artifacts, manifest, head_sha, tree_sha, lock_sha = _complete_gate_fixture(tmp_path)
    before = {
        path.relative_to(artifacts): path.read_bytes()
        for path in artifacts.rglob("*")
        if path.is_file()
    }

    validate_gate_artifacts(
        artifacts,
        head_sha=head_sha,
        tree_sha=tree_sha,
        manifest_sha256=manifest.sha256,
        manifest=manifest,
        lock_sha256=lock_sha,
        workflow_identity=_push_identity(),
        expected_platform="linux",
    )

    after = {
        path.relative_to(artifacts): path.read_bytes()
        for path in artifacts.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_allowed_skip_requires_exact_legal_setup_skip_structure():
    nodeid = "tests/test_a.py::test_linux_only"
    allowed = ({"nodeid": nodeid, "platform": "linux", "reason": "Windows DPAPI regression"},)
    valid = _valid_lane_payload(nodeid=nodeid)
    valid["cases"][0]["phases"] = [
        {
            "when": "setup",
            "outcome": "skipped",
            "reason": "Windows DPAPI regression",
            "wasxfail": "",
        },
        {"when": "teardown", "outcome": "passed", "reason": "", "wasxfail": ""},
    ]

    assert validate_lane_payload(valid, _expected(), allowed_skips=allowed) == {
        "passed": 0,
        "skipped": 1,
        "failed": 0,
        "errors": 0,
    }

    contradictory = deepcopy(valid)
    contradictory["cases"][0]["phases"].insert(
        1, {"when": "call", "outcome": "passed", "reason": "", "wasxfail": ""}
    )
    with pytest.raises(ContractError, match="illegal phase outcome structure"):
        validate_lane_payload(contradictory, _expected(), allowed_skips=allowed)


@pytest.mark.parametrize(
    "phases",
    (
        [
            {
                "when": "setup",
                "outcome": "skipped",
                "reason": "Windows DPAPI regression",
                "wasxfail": "",
            },
            {"when": "teardown", "outcome": "failed", "reason": "boom", "wasxfail": ""},
        ],
        [
            {
                "when": "setup",
                "outcome": "skipped",
                "reason": "Windows DPAPI regression",
                "wasxfail": "",
            },
            {"when": "setup", "outcome": "passed", "reason": "", "wasxfail": ""},
            {"when": "teardown", "outcome": "passed", "reason": "", "wasxfail": ""},
        ],
        [
            {
                "when": "setup",
                "outcome": "skipped",
                "reason": "Windows DPAPI regression",
                "wasxfail": "",
            },
        ],
        [
            {
                "when": "setup",
                "outcome": "skipped",
                "reason": "Windows DPAPI regression",
                "wasxfail": "expected",
            },
            {"when": "teardown", "outcome": "passed", "reason": "", "wasxfail": ""},
        ],
    ),
)
def test_allowed_skip_rejects_failure_duplicate_missing_and_xfail(phases):
    nodeid = "tests/test_a.py::test_linux_only"
    payload = _valid_lane_payload(nodeid=nodeid)
    payload["cases"][0]["phases"] = phases
    allowed = ({"nodeid": nodeid, "platform": "linux", "reason": "Windows DPAPI regression"},)

    with pytest.raises(ContractError):
        validate_lane_payload(payload, _expected(), allowed_skips=allowed)


@pytest.mark.parametrize(
    ("relative_path", "replacement", "match"),
    (
        ("ci-quality-123-1/metadata.md", None, "missing quality report: metadata.md"),
        ("ci-quality-123-1/metadata.md", "", "metadata.*empty"),
        ("ci-quality-123-1/metadata.md", "not metadata\n", "metadata.*malformed"),
        (
            "ci-quality-123-1/metadata.md",
            "# CI quality identity\n- checked-out HEAD: `wrong`\n",
            "metadata.*mismatch",
        ),
        ("ci-quality-123-1/git-status.txt", "", "git status.*empty"),
        ("ci-quality-123-1/git-status.txt", "## clean-ish\n", "git status.*malformed"),
        (
            "ci-quality-123-1/git-status.txt",
            f"# branch.oid {'f' * 40}\n# branch.head task/synthetic\n",
            "git status.*HEAD",
        ),
        ("ci-quality-123-1/uv-lock.sha256", "", "lock digest.*empty"),
        ("ci-quality-123-1/uv-lock.sha256", "not-a-digest\n", "lock digest.*malformed"),
        (
            "ci-quality-123-1/uv-lock.sha256",
            f"{'f' * 64}  uv.lock\n",
            "lock digest mismatch",
        ),
        ("ci-lane-garmin-123-1/metadata.md", "", "lane metadata.*empty"),
        ("ci-lane-garmin-123-1/metadata.md", "not metadata\n", "lane metadata.*malformed"),
        (
            "ci-lane-garmin-123-1/metadata.md",
            "# CI lane identity\n- selection SHA-256: `wrong`\n",
            "lane metadata.*mismatch",
        ),
        ("ci-lane-garmin-123-1/git-status.txt", "", "git status.*empty"),
        ("ci-lane-garmin-123-1/git-status.txt", "## clean-ish\n", "git status.*malformed"),
        (
            "ci-lane-garmin-123-1/git-status.txt",
            f"# branch.oid {'f' * 40}\n# branch.head task/synthetic\n",
            "git status.*HEAD",
        ),
        ("ci-lane-garmin-123-1/uv-lock.sha256", "", "lock digest.*empty"),
        ("ci-lane-garmin-123-1/uv-lock.sha256", "not-a-digest\n", "lock digest.*malformed"),
        (
            "ci-lane-garmin-123-1/uv-lock.sha256",
            f"{'f' * 64}  uv.lock\n",
            "lock digest mismatch",
        ),
        ("ci-lane-garmin-123-1/command.txt", None, "missing lane garmin report: command.txt"),
        ("ci-lane-garmin-123-1/command.txt", "", "command.*empty"),
        ("ci-lane-garmin-123-1/command.txt", "python -m nope\n", "command.*pytest"),
        (
            "ci-lane-garmin-123-1/command.txt",
            "/venv/bin/python -m pytest tests/test_wrong.py\n",
            "command.*selection",
        ),
    ),
)
def test_final_gate_rejects_missing_empty_malformed_or_wrong_retained_identity(
    tmp_path, relative_path, replacement, match
):
    artifacts, manifest, head_sha, tree_sha, lock_sha = _complete_gate_fixture(tmp_path)
    target = artifacts / relative_path
    if replacement is None:
        target.unlink()
    else:
        target.write_text(replacement, encoding="utf-8")

    with pytest.raises(ContractError, match=match):
        validate_gate_artifacts(
            artifacts,
            head_sha=head_sha,
            tree_sha=tree_sha,
            manifest_sha256=manifest.sha256,
            manifest=manifest,
            lock_sha256=lock_sha,
            workflow_identity=_push_identity(),
            expected_platform="linux",
        )
