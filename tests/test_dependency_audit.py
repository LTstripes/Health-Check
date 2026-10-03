import importlib.util
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


audit = _load("dependency_audit", "dependency_audit.py")
_lanes = _load("ci_test_lanes_for_dependency_audit", "ci_test_lanes.py")
ContractError = _lanes.ContractError
ExpectedProvenance = _lanes.ExpectedProvenance
_selection_sha256 = _lanes._selection_sha256
validate_lane_payload = _lanes.validate_lane_payload


def _registry(name="urllib3", version="2.8.0"):
    return {"name": name, "version": version, "source": {"registry": "https://pypi.org/simple"}}


def _payload(vulns=None):
    return {
        "dependencies": [{"name": "urllib3", "version": "2.8.0", "vulns": vulns or []}],
        "fixes": [],
    }


def test_inventory_includes_registry_versions_and_exposes_vcs_coverage_limit():
    lock = {
        "package": [
            _registry(),
            _registry("pytest", "9.0.3"),
            {"name": "health-check", "version": "0.1.0", "source": {"editable": "."}},
            {
                "name": "garminconnect",
                "version": "0.3.15",
                "source": {
                    "git": "https://github.com/cyberjunky/python-garminconnect.git?rev="
                    f"{audit.GARMIN_PIN}#{audit.GARMIN_PIN}"
                },
            },
        ]
    }
    versions, excluded = audit.inventory(lock)
    assert versions == [("pytest", "9.0.3"), ("urllib3", "2.8.0")]
    assert excluded[-1] == {
        "name": "garminconnect",
        "pin": audit.GARMIN_PIN,
        "reason": "VCS code is unaudited",
    }


@pytest.mark.parametrize("source", [{"git": "other-pin"}, {"registry": "https://other.invalid"}])
def test_unknown_sources_cannot_silently_reduce_coverage(source):
    package = _registry()
    package["source"] = source
    with pytest.raises(ValueError, match="unsupported source"):
        audit.inventory({"package": [package]})


def test_findings_and_clean_are_distinct_complete_scanner_outcomes():
    expected = [("urllib3", "2.8.0")]
    assert audit.verdict(_payload(), expected, 0) == ("clean", [])
    status, findings = audit.verdict(_payload([{"id": "synthetic-advisory"}]), expected, 1)
    assert status == "findings"
    assert findings == [
        {
            "name": "urllib3",
            "version": "2.8.0",
            "id": "synthetic-advisory",
            "aliases": [],
            "fix_versions": [],
        }
    ]


def test_duplicate_advisory_ids_stay_findings_without_being_counted_twice():
    payload = _payload([{"id": "PYSEC-1", "aliases": ["GHSA-1"]}, {"id": "PYSEC-1"}])
    status, findings = audit.verdict(payload, [("urllib3", "2.8.0")], 1)
    assert status == "findings"
    assert [item["id"] for item in findings] == ["PYSEC-1"]


def test_exposure_marks_runtime_transitives_separately_from_development_tools():
    lock = {
        "package": [
            {
                "name": "health-check",
                "version": "0.1.0",
                "source": {"editable": "."},
                "dependencies": [{"name": "garminconnect"}],
                "dev-dependencies": {"dev": [{"name": "pytest"}]},
            },
            {
                "name": "garminconnect",
                "version": "0.3.15",
                "source": {"git": "pinned"},
                "dependencies": [{"name": "requests"}],
            },
            {"name": "requests", "version": "2.34.2", "dependencies": [{"name": "urllib3"}]},
            _registry(),
            _registry("pytest", "9.0.3"),
        ]
    }
    assert audit.exposure_labels(lock) == {
        "garminconnect": "runtime",
        "requests": "runtime",
        "urllib3": "runtime",
        "pytest": "development",
    }


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "skip", "version", "exit"])
def test_incomplete_scanner_or_network_failure_cannot_pass(mutation):
    payload = _payload()
    code = 0
    match = "inventory"
    if mutation == "missing":
        payload["dependencies"] = []
    elif mutation == "duplicate":
        payload["dependencies"] *= 2
    elif mutation == "skip":
        payload["dependencies"][0]["skip_reason"] = "service unavailable"
        match = "skipped"
    elif mutation == "version":
        payload["dependencies"][0]["version"] = "2.7.0"
    else:
        code, match = 1, "exit status"
    with pytest.raises(ValueError, match=match):
        audit.verdict(payload, [("urllib3", "2.8.0")], code)


@pytest.mark.parametrize("outcome", ["clean", "findings", "network", "malformed", "timeout"])
def test_entrypoint_records_evidence_and_never_reuses_old_output(tmp_path, monkeypatch, outcome):
    root = tmp_path / "repo"
    root.mkdir()
    lock_text = (
        '[[package]]\nname = "urllib3"\nversion = "2.8.0"\n'
        'source = { registry = "https://pypi.org/simple" }\n'
    )
    (root / "uv.lock").write_text(lock_text, encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    output = tmp_path / "evidence"
    commands = []

    def scanner(command, **kwargs):
        commands.append(command)
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, "pip-audit 2.10.1\n", "")
        assert "--disable-pip" in command and "--no-deps" in command
        assert "--strict" in command and "--fix" not in command
        assert "--vulnerability-service" in command and "osv" in command
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, 300)
        if outcome != "network":
            payload = _payload([{"id": "synthetic"}]) if outcome == "findings" else _payload()
            (output / "advisories.json").write_text(
                "malformed" if outcome == "malformed" else json.dumps(payload), encoding="utf-8"
            )
        return subprocess.CompletedProcess(
            command, 1 if outcome in {"findings", "network"} else 0, "", "synthetic diagnostic"
        )

    monkeypatch.setattr(audit.subprocess, "run", scanner)
    code = audit.run_audit(root, output)
    expected_code = {"clean": 0, "findings": 1}.get(outcome, 2)
    assert code == expected_code
    result = json.loads((output / "result.json").read_text(encoding="utf-8"))
    assert result["status"] == {0: "clean", 1: "findings", 2: "tool_failure"}[code]
    assert result["registry_packages"] == 1
    assert (root / "uv.lock").read_text(encoding="utf-8") == lock_text
    with pytest.raises(FileExistsError):
        audit.run_audit(root, output)
    assert len(commands) == 2


def test_verify_accepts_only_a_clean_osv_result_that_keeps_the_garmin_limit(tmp_path):
    evidence = tmp_path / "result.json"

    def write(payload):
        evidence.write_text(json.dumps(payload), encoding="utf-8")

    clean = {
        "status": "clean",
        "service": "osv",
        "scanner_exit_code": 0,
        "findings": [],
        "registry_packages": 2,
        "excluded": [
            {"name": "health-check", "reason": "first-party editable project"},
            {"name": "garminconnect", "pin": audit.GARMIN_PIN, "reason": "VCS code is unaudited"},
        ],
    }
    write(clean)
    assert audit.verify_result(evidence) == 0
    for mutation in (
        {"status": "findings"},
        {"status": "tool_failure"},
        {"service": "pypi"},
        {"scanner_exit_code": 1},
        {"findings": [{"id": "PYSEC-1"}]},
        {"excluded": [{"name": "health-check"}]},
        {"registry_packages": 0},
    ):
        write(clean | mutation)
        assert audit.verify_result(evidence) == 2
    assert audit.verify_result(tmp_path / "missing.json") == 2


def test_full_ci_audits_inside_quality_and_docs_route_returns_first():
    root = Path(__file__).parents[1]
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    quality = workflow.split("  quality:\n", 1)[1].split("  test:\n", 1)[0]
    checks = workflow.split("  checks:\n", 1)[1]
    assert "scripts/dependency_audit.py" in quality
    assert "--output-dir" in quality and "dependency-audit" in quality
    assert "continue-on-error" not in workflow and "|| true" not in workflow
    assert not (root / ".github/workflows/dependency-audit.yml").exists()
    docs_return = checks.index('if [ "$route" = docs ]; then')
    verify_at = checks.index("dependency_audit.py --verify")
    assert verify_at > docs_return
    assert "pytest and Windows were not run" in checks
    assert 'if [ "$attempt_status" -ne 0 ]' in checks
    assert '"$audit_status" -ne 0' in checks


def test_installed_pytest_preserves_real_plugin_collection_junit_and_declared_skips(tmp_path):
    source = tmp_path / "test_synthetic.py"
    source.write_text(
        "import pytest\n"
        "def test_pass():\n    assert True\n"
        "@pytest.mark.skip(reason='synthetic declared skip')\n"
        "def test_skip():\n    assert False\n",
        encoding="utf-8",
    )
    selected = (str(source),)
    expected = ExpectedProvenance(
        "core-sleep",
        sys.platform,
        "a" * 40,
        "b" * 40,
        "c" * 64,
        _selection_sha256(selected),
        selected,
    )
    inventories = []
    for mode in ("collect", "run"):
        output = tmp_path / f"{mode}.json"
        command = [
            sys.executable,
            "-m",
            "pytest",
            str(source),
            "-q",
            "-p",
            "scripts.ci_lane_plugin",
            f"--rootdir={tmp_path}",
            f"--basetemp={tmp_path / mode}",
            f"--ci-lane-evidence={output}",
            f"--ci-lane-mode={mode}",
            f"--ci-lane-name={expected.lane}",
            f"--ci-platform={expected.platform}",
            f"--ci-head-sha={expected.head_sha}",
            f"--ci-tree-sha={expected.tree_sha}",
            f"--ci-manifest-sha256={expected.manifest_sha256}",
            f"--ci-selection-sha256={expected.selection_sha256}",
            f"--ci-selected-path={source}",
        ]
        command += (
            ["--collect-only"] if mode == "collect" else [f"--junitxml={tmp_path / 'junit.xml'}"]
        )
        result = subprocess.run(
            command, cwd=Path(__file__).parents[1], capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["collection_complete"] is True
        assert payload["collection_errors"] == [] and payload["deselected_nodeids"] == []
        inventories.append(payload["collected_nodeids"])
    assert (
        inventories[0]
        == inventories[1]
        == ["test_synthetic.py::test_pass", "test_synthetic.py::test_skip"]
    )
    allowed = [
        {"nodeid": inventories[1][1], "platform": sys.platform, "reason": "synthetic declared skip"}
    ]
    assert validate_lane_payload(payload, expected, allowed_skips=allowed) == {
        "passed": 1,
        "skipped": 1,
        "failed": 0,
        "errors": 0,
    }
    with pytest.raises(ContractError, match="unexpected skip"):
        validate_lane_payload(payload, expected, allowed_skips=[])
    suite = ET.parse(tmp_path / "junit.xml").getroot().find("testsuite")
    assert suite is not None
    assert {key: suite.attrib[key] for key in ("tests", "skipped", "failures", "errors")} == {
        "tests": "2",
        "skipped": "1",
        "failures": "0",
        "errors": "0",
    }
