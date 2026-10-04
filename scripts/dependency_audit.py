"""Audit every registry version in uv.lock without resolving or installing project code.

Exit 0 is a completed clean audit. Advisory findings exit 1. Scanner, network,
inventory, and coverage failures exit 2. Neither failure is a pass.

The gate queries OSV. On 2026-10-03 one pip-audit PyPI JSON query of urllib3
2.7.0 and pytest 8.4.2 returned no advisories, while OSV returned the upstream
records. A later PyPI query the same day returned those records and duplicated
the pytest row. OSV stays the gate so that false clean cannot pass. The patched
pins urllib3 2.8.0 and pytest 9.0.3 were OSV-clean.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

SCANNER = "pip-audit==2.10.1"
SERVICE = "osv"
GARMIN_PIN = "54079fbca3cafaa371b5d0cd1aa9cfb0ae62c7a5"
GARMIN_SOURCE = {
    "git": "https://github.com/cyberjunky/python-garminconnect.git?rev="
    f"{GARMIN_PIN}#{GARMIN_PIN}"
}


def inventory(lock: dict) -> tuple[list[tuple[str, str]], list[dict]]:
    """Include all platforms and groups. Only the project and Garmin VCS pin are excluded."""
    packages = lock["package"]
    registry, excluded = [], []
    for package in packages:
        name, version, source = package["name"], package["version"], package["source"]
        if source == {"registry": "https://pypi.org/simple"}:
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", name) or not re.fullmatch(
                r"[a-zA-Z0-9][a-zA-Z0-9.!+_-]*", version
            ):
                raise ValueError("unsafe registry name/version")
            registry.append((name, version))
        elif name == "health-check" and source == {"editable": "."}:
            excluded.append({"name": name, "reason": "first-party editable project"})
        elif name == "garminconnect" and source == GARMIN_SOURCE:
            excluded.append({"name": name, "pin": GARMIN_PIN, "reason": "VCS code is unaudited"})
        else:
            raise ValueError(f"unsupported source for {name}; coverage needs review")
    if not registry or len(registry) != len(set(registry)):
        raise ValueError("empty or duplicate registry inventory")
    return sorted(registry), excluded


def exposure_labels(lock: dict) -> dict[str, str]:
    """Label locked packages as runtime or development-only from the project closure."""
    packages = {package["name"]: package for package in lock["package"]}
    project = packages.get("health-check")
    if project is None:
        return {}

    def walk(roots: list[str]) -> set[str]:
        seen: set[str] = set()
        stack = list(roots)
        while stack:
            name = stack.pop()
            if name in seen or name not in packages:
                continue
            seen.add(name)
            for dependency in packages[name].get("dependencies") or []:
                stack.append(dependency["name"])
        seen.discard("health-check")
        return seen

    runtime = walk([item["name"] for item in project.get("dependencies") or []])
    dev_roots: list[str] = []
    for group in (project.get("dev-dependencies") or {}).values():
        dev_roots.extend(item["name"] for item in group)
    development = walk(dev_roots)
    labels = {name: "runtime" for name in runtime}
    labels.update({name: "development" for name in development - runtime})
    return labels


def verdict(payload: dict, expected: list[tuple[str, str]], returncode: int) -> tuple[str, list]:
    """A return code alone cannot distinguish findings from scanner or network failure."""
    dependencies = payload["dependencies"]
    actual = []
    findings = []
    for dependency in dependencies:
        if "skip_reason" in dependency:
            raise ValueError("scanner skipped a registry package")
        actual.append((dependency["name"], dependency["version"]))
        vulns = dependency["vulns"]
        if not isinstance(vulns, list):
            raise ValueError("malformed vulnerability list")
        for vuln in vulns:
            if not isinstance(vuln, dict) or not isinstance(vuln.get("id"), str):
                raise ValueError("malformed advisory")
            findings.append(
                {
                    "name": dependency["name"],
                    "version": dependency["version"],
                    "id": vuln["id"],
                    "aliases": list(vuln.get("aliases") or []),
                    "fix_versions": list(vuln.get("fix_versions") or []),
                }
            )
    if Counter(actual) != Counter(expected):
        raise ValueError("scanner inventory is incomplete or mismatched")
    if returncode != (1 if findings else 0):
        raise ValueError("scanner exit status disagrees with complete advisory output")
    unique = []
    seen = set()
    for finding in findings:
        key = (finding["name"], finding["version"], finding["id"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return ("findings" if unique else "clean"), unique


def _annotate(findings: list[dict], labels: dict[str, str]) -> list[dict]:
    annotated = []
    for finding in findings:
        item = dict(finding)
        item["exposure"] = labels.get(finding["name"], "unknown")
        annotated.append(item)
    return annotated


def run_audit(root: Path, output: Path) -> int:
    # Fresh output is mandatory; never consume a previous attempt's JSON.
    output.mkdir(parents=True, exist_ok=False)
    metadata = {
        "started_at": datetime.now(UTC).isoformat(),
        "scanner": SCANNER,
        "service": SERVICE,
        "advisory_snapshot": "live OSV query at audit time; no global snapshot version",
        "coverage": "all registry versions in uv.lock, all platforms and dependency groups",
        "limits": (
            "OSV known-package advisories only. On 2026-10-03 one PyPI JSON query of "
            "the vulnerable pins was a false clean; a later same-day query returned "
            "the records and duplicated pytest. The Garmin VCS pin is unaudited. "
            "No exploit or Owner-runtime proof."
        ),
        "python": sys.version.split()[0],
        "workflow_run": {
            key: os.environ.get(key, "")
            for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA")
        },
        "status": "tool_failure",
        "findings": [],
    }
    try:
        lock_bytes = (root / "uv.lock").read_bytes()
        metadata["lock_sha256"] = hashlib.sha256(lock_bytes).hexdigest()
        metadata["pyproject_sha256"] = hashlib.sha256(
            (root / "pyproject.toml").read_bytes()
        ).hexdigest()
        lock = tomllib.loads(lock_bytes.decode("utf-8"))
        expected, excluded = inventory(lock)
        labels = exposure_labels(lock)
        metadata["excluded"] = excluded
        metadata["registry_packages"] = len(expected)
        metadata["exposure"] = {
            "runtime": sorted(name for name, label in labels.items() if label == "runtime"),
            "development": sorted(
                name for name, label in labels.items() if label == "development"
            ),
        }
        requirements = output / "requirements.txt"
        requirements.write_text(
            "".join(f"{name}=={version}\n" for name, version in expected), encoding="utf-8"
        )
        # The scanner lives in uv's tool environment, never in the project lock.
        prefix = ["uv", "tool", "run", "--from", SCANNER, "pip-audit"]
        version = subprocess.run(
            [*prefix, "--version"], capture_output=True, text=True, check=True, timeout=180
        )
        if version.stdout.strip() != "pip-audit 2.10.1":
            raise ValueError("unexpected scanner version")
        metadata["scanner_version"] = version.stdout.strip()
        command = [
            *prefix,
            "--requirement",
            str(requirements),
            "--no-deps",
            "--disable-pip",
            "--strict",
            "--vulnerability-service",
            SERVICE,
            "--progress-spinner",
            "off",
            "--format",
            "json",
            "--desc",
            "off",
            "--output",
            str(output / "advisories.json"),
            "--cache-dir",
            str(output / "http-cache"),
        ]
        metadata["command"] = command
        result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        (output / "scanner.stdout").write_text(result.stdout, encoding="utf-8")
        (output / "scanner.stderr").write_text(result.stderr, encoding="utf-8")
        metadata["scanner_exit_code"] = result.returncode
        payload = json.loads((output / "advisories.json").read_text(encoding="utf-8"))
        status, findings = verdict(payload, expected, result.returncode)
        metadata["status"] = status
        metadata["findings"] = _annotate(findings, labels)
        if lock_bytes != (root / "uv.lock").read_bytes():
            raise ValueError("lock changed during audit")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        metadata["status"] = "tool_failure"
        metadata["error"] = str(error)
    metadata["finished_at"] = datetime.now(UTC).isoformat()
    (output / "result.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"dependency audit: {metadata['status']}; evidence: {output}")
    return {"clean": 0, "findings": 1, "tool_failure": 2}[metadata["status"]]


def verify_result(path: Path) -> int:
    """Accept only a clean OSV audit that still records the unaudited Garmin pin."""
    try:
        if not path.is_file():
            raise ValueError("audit evidence is missing")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("status") != "clean":
            raise ValueError(f"audit status is {payload.get('status')}")
        if payload.get("service") != SERVICE:
            raise ValueError("audit service is not osv")
        if payload.get("scanner_exit_code") != 0 or payload.get("findings"):
            raise ValueError("clean audit evidence contradicts the scanner result")
        excluded = payload.get("excluded")
        pinned = isinstance(excluded, list) and any(
            item.get("name") == "garminconnect" and item.get("pin") == GARMIN_PIN
            for item in excluded
        )
        if not pinned:
            raise ValueError("Garmin VCS pin is missing from unaudited coverage")
        packages = payload.get("registry_packages")
        if not isinstance(packages, int) or packages < 1:
            raise ValueError("registry coverage is empty")
    except (OSError, ValueError, TypeError, json.JSONDecodeError, AttributeError) as error:
        print(f"dependency audit verify failed: {error}")
        return 2
    print(f"dependency audit verify: clean; evidence: {path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="fresh evidence directory")
    parser.add_argument(
        "--verify",
        nargs="*",
        type=Path,
        help="require exactly one clean result.json; used by the full CI gate",
    )
    args = parser.parse_args()
    if args.verify is not None and args.output_dir is not None:
        print("dependency audit: choose audit output or verify, not both", file=sys.stderr)
        return 2
    if args.verify is not None:
        if len(args.verify) != 1:
            print(
                "dependency audit verify failed: expected exactly one result.json",
                file=sys.stderr,
            )
            return 2
        return verify_result(args.verify[0])
    if args.output_dir is None:
        parser.error("--output-dir is required to audit")
    return run_audit(Path(__file__).resolve().parents[1], args.output_dir.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
