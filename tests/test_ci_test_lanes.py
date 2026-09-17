import importlib.util
import json
import sys
from collections import Counter
from copy import deepcopy
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
) -> str:
    lines = [f"# CI {kind} identity"]
    if lane is not None:
        lines.append(f"- lane: `{lane}`")
    lines.extend(
        (
            "- event: `push`",
            "- ref: `refs/heads/task/synthetic`",
            f"- event SHA: `{head_sha}`",
            f"- checked-out HEAD: `{head_sha}`",
            f"- checked-out tree: `{tree_sha}`",
            "- PR base ref/SHA: `` / ``",
            "- PR head ref/SHA: `` / ``",
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
            "- uv: `uv 0.12.0`",
            "- runner: `Linux/X64`",
        )
    )
    return "\n".join(lines) + "\n"


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


def _complete_gate_fixture(tmp_path: Path) -> tuple[Path, object, str, str, str]:
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
    platform = sys.platform
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
        (lane_dir / "summary.md").write_text("synthetic summary\n", encoding="utf-8")
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
    )

    assert result["quality"]["reference_nodeids"] == [
        "tests/test_a.py::test_synthetic",
        "tests/test_b.py::test_synthetic",
        "tests/test_c.py::test_synthetic",
    ]


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
        )
