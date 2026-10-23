"""Local, pinned reuse of exact CI evidence. No downloading or implicit retries.

The trusted operator adapter supplies fresh, fully paginated GitHub API objects
via ``refresh_metadata``; artifact-provided JSON is never an authenticated source.
The adapter must fetch the current run and its exact-attempt jobs, all artifacts,
checkout commit and current PR. No callback may download or run validators.
Receipts belong outside the retained evidence directory; their SHA256 must be
conveyed independently by a trusted producer. A receipt is not a signature.
"""

from __future__ import annotations

import hashlib
import json
import marshal
import os
import re
import stat
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import ci_test_lanes as lanes
import ci_windows_smoke as windows

SCHEMA = "healthcheck.exact-ci-receipt/v1"


class ReceiptError(ValueError):
    """Reuse is unavailable; the caller must decide what to do next."""


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ReceiptError(reason)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def safe_path(path: Path) -> None:
    require(".." not in path.parts, "unsafe parent path")
    for part in (path.absolute(), *path.absolute().parents):
        info = part.lstat()
        require(not stat.S_ISLNK(info.st_mode), "symlink path")
        require(not getattr(info, "st_file_attributes", 0) & 0x400, "reparse path")


def inventory(root: Path) -> dict[str, str]:
    safe_path(root)
    require(root.is_dir(), "evidence root is not a directory")
    result: dict[str, str] = {}
    seen: set[str] = set()

    def walk_error(error: OSError) -> None:
        raise ReceiptError("retained inventory unreadable") from error

    for parent, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        for name in sorted(dirs + files):
            path = Path(parent) / name
            relative = path.relative_to(root).as_posix()
            require(
                not any(c in name for c in '\\:<>|?*"')
                and not any(ord(c) < 32 for c in name)
                and name not in (".", ".."),
                "unsafe retained path",
            )
            require(name == name.rstrip(" ."), "unsafe retained path")
            require(
                not re.match(r"(?i)^(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\.|$)", name),
                "unsafe retained path",
            )
            require(relative.casefold() not in seen, "case-colliding retained path")
            seen.add(relative.casefold())
            safe_path(path)
            require(path.is_dir() or path.is_file(), "nonregular retained path")
            result[relative + ("/" if path.is_dir() else "")] = (
                "directory" if path.is_dir() else digest(path.read_bytes())
            )
    require(bool(result), "empty retained evidence")
    return result


def binding(context: dict[str, Any]) -> dict[str, Any]:
    """Bind actual loaded modules, external adapter, options and canonical inputs."""
    required = {
        "repository",
        "run_id",
        "attempt",
        "event",
        "head",
        "base",
        "checkout",
        "tree",
        "parents",
        "branch",
        "workflow_identity",
        "expected_jobs",
        "pr",
    }
    options = context["options"]
    require(set(options) == required, "incomplete or unknown options")
    require(options["event"] in ("push", "pull_request"), "unsupported event")
    for key in ("head", "checkout", "tree"):
        require(bool(re.fullmatch(r"[0-9a-f]{40}", options[key])), "invalid Git identity")
    require(
        options["expected_jobs"]
        == {
            "classify": "success",
            "docs": "skipped",
            "quality": "success",
            "windows-smoke": "success",
            "test (garmin)": "success",
            "test (core-sleep)": "success",
            "test (app-ingest)": "success",
            "checks": "success",
        },
        "mandatory code-mode job set changed",
    )
    paths = {
        "manifest": Path(context["manifest_path"]),
        "lock": Path(context["lock_path"]),
        "lanes": Path(lanes.__file__),
        "windows": Path(windows.__file__),
        "receipt_tool": Path(__file__),
        "adapter": Path(context["adapter_path"]),
    }
    files = {}
    for name, path in paths.items():
        safe_path(path)
        files[name] = {"path": str(path.absolute()), "sha256": digest(path.read_bytes())}
    loaded = {}
    for module in (lanes, windows):
        loaded[module.__name__] = {
            name: digest(marshal.dumps(value.__code__))
            for name, value in vars(module).items()
            if callable(value) and hasattr(value, "__code__")
        }
    return json.loads(
        encoded(
            {
                "options": options,
                "files": files,
                "loaded": loaded,
                "repo_root": str(Path(context["repo_root"]).absolute()),
            }
        )
    )


def metadata_identity(metadata: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    """Project immutable identities, deliberately excluding URLs/timestamps/display text."""
    run, jobs, artifacts = metadata["run"], metadata["jobs"], metadata["artifacts"]
    run_id, attempt = int(options["run_id"]), int(options["attempt"])
    require(run["id"] == run_id and run["run_attempt"] == attempt, "superseded run attempt")
    require(run["status"] == "completed" and run["conclusion"] == "success", "unsuccessful run")
    require(run["repository"]["full_name"] == options["repository"], "foreign repository")
    require(run["head_repository"]["full_name"] == options["repository"], "foreign head repository")
    require(
        (run["head_sha"], run["event"], run["head_branch"])
        == (options["head"], options["event"], options["branch"]),
        "run identity changed",
    )
    require(jobs["total_count"] == len(jobs["jobs"]), "incomplete jobs pagination")
    actual = {}
    stable_jobs = []
    for job in jobs["jobs"]:
        require(job["name"] not in actual, "duplicate job")
        require(job["run_id"] == run_id and job["run_attempt"] == attempt, "mixed job attempt")
        require(job["head_sha"] == options["head"] and job["status"] == "completed", "job identity")
        actual[job["name"]] = job["conclusion"]
        stable_jobs.append(
            {k: job[k] for k in ("id", "name", "run_id", "run_attempt", "head_sha", "conclusion")}
        )
    require(actual == options["expected_jobs"], "mandatory jobs unsuccessful or incomplete")
    require(
        artifacts["total_count"] == len(artifacts["artifacts"]), "incomplete artifact pagination"
    )
    expected_names = {
        f"ci-{name}-{run_id}-{attempt}"
        for name in (
            "quality",
            "windows-smoke",
            "lane-garmin",
            "lane-core-sleep",
            "lane-app-ingest",
        )
    }
    stable_artifacts = []
    seen_ids = set()
    for item in artifacts["artifacts"]:
        require(item["id"] not in seen_ids, "duplicate artifact ID")
        seen_ids.add(item["id"])
        require(item["expired"] is False, "expired artifact")
        require(
            re.fullmatch(r"sha256:[0-9a-f]{64}", item["digest"]) is not None,
            "missing GitHub ZIP digest",
        )
        workflow = item["workflow_run"]
        require(
            workflow["id"] == run_id and workflow["head_sha"] == options["head"],
            "foreign artifact run",
        )
        stable_artifacts.append({k: item[k] for k in ("id", "name", "digest", "size_in_bytes")})
    require(
        {a["name"] for a in stable_artifacts} == expected_names
        and len(stable_artifacts) == len(expected_names),
        "foreign/missing/mixed artifacts",
    )
    commit = metadata["commit"]
    require(
        commit["sha"] == options["checkout"] and commit["tree"]["sha"] == options["tree"],
        "checkout/tree changed",
    )
    require([p["sha"] for p in commit["parents"]] == options["parents"], "checkout parents changed")
    identity = options["workflow_identity"]
    if options["event"] == "pull_request":
        pr = metadata["pr"]
        require(pr["number"] == options["pr"] and pr["state"] == "open", "superseded PR")
        require(
            pr["head"]["sha"] == options["head"] and pr["base"]["sha"] == options["base"],
            "superseded PR head/base",
        )
        require(
            pr["base"]["repo"]["full_name"] == options["repository"]
            and pr["head"]["repo"]["full_name"] == options["repository"],
            "foreign PR",
        )
        require(pr["merge_commit_sha"] == options["checkout"], "superseded PR checkout")
        require(options["parents"] == [options["base"], options["head"]], "PR parents")
        expected_identity = dict(
            event_name="pull_request",
            ref=f"refs/pull/{pr['number']}/merge",
            pr_base_ref=pr["base"]["ref"],
            pr_base_sha=options["base"],
            pr_head_ref=pr["head"]["ref"],
            pr_head_sha=options["head"],
        )
    else:
        require(
            options["checkout"] == options["head"]
            and options["pr"] is None
            and options["base"] == "",
            "push identity",
        )
        expected_identity = dict(
            event_name="push",
            ref=f"refs/heads/{options['branch']}",
            pr_base_ref="",
            pr_base_sha="",
            pr_head_ref="",
            pr_head_sha="",
        )
    require(identity == expected_identity, "workflow identity changed")
    return {
        "run": {k: run[k] for k in ("id", "run_attempt", "head_sha", "event", "head_branch")},
        "jobs": sorted(stable_jobs, key=lambda x: x["id"]),
        "artifacts": sorted(stable_artifacts, key=lambda x: x["id"]),
        "checkout": options["checkout"],
        "tree": options["tree"],
        "parents": options["parents"],
        "workflow_identity": expected_identity,
    }


def fresh(
    refresh_metadata: Callable[[], dict[str, Any]], options: dict[str, Any]
) -> dict[str, Any]:
    try:
        return metadata_identity(refresh_metadata(), options)
    except ReceiptError:
        raise
    except Exception as exc:
        raise ReceiptError("fresh GitHub metadata unavailable or incomplete") from exc


def verify_zips(root: Path, metadata: dict[str, Any]) -> None:
    for artifact in metadata["artifacts"]:
        path = root / (artifact["name"] + ".zip")
        raw = path.read_bytes()
        require("sha256:" + digest(raw) == artifact["digest"], "GitHub ZIP digest mismatch")
        extracted = root / "artifacts" / artifact["name"]
        members = set()
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                name = item.filename.rstrip("/")
                parts = name.split("/")
                require(
                    all(p not in ("", ".", "..") for p in parts)
                    and not any(c in name for c in "\\:"),
                    "unsafe ZIP path",
                )
                require(name.casefold() not in members, "duplicate/colliding ZIP member")
                members.add(name.casefold())
                require(stat.S_IFMT(item.external_attr >> 16) != stat.S_IFLNK, "ZIP symlink")
                target = extracted.joinpath(*parts)
                if not item.is_dir():
                    require(
                        target.read_bytes() == archive.read(item), "ZIP/extracted bytes mismatch"
                    )
        retained = {
            p.relative_to(extracted).as_posix().casefold()
            for p in extracted.rglob("*")
            if p.is_file()
        }
        zipped = {i.filename.casefold() for i in archive.infolist() if not i.is_dir()}
        require(retained == zipped, "extra/missing extracted bytes")


def cold_verify(
    receipt_path: Path,
    evidence_root: Path,
    context: dict[str, Any],
    refresh_metadata: Callable[[], dict[str, Any]],
) -> str:
    """Validate retained ZIPs and official evidence, then atomically publish once."""
    require(not receipt_path.exists(), "receipt already exists")
    safe_path(receipt_path.parent)
    require(
        not receipt_path.absolute().is_relative_to(evidence_root.absolute()),
        "receipt must be outside evidence root",
    )
    bound = binding(context)
    before = inventory(evidence_root)
    metadata = fresh(refresh_metadata, bound["options"])
    verify_zips(evidence_root, metadata)
    options = bound["options"]
    manifest = lanes.validate_manifest(Path(context["manifest_path"]), Path(context["repo_root"]))
    artifacts = evidence_root / "artifacts"
    lanes.validate_attempt_artifacts(
        artifacts, run_id=str(options["run_id"]), attempt=str(options["attempt"])
    )
    lanes.validate_gate_job_results(quality_result="success", test_result="success")
    lanes.validate_gate_artifacts(
        artifacts,
        head_sha=options["checkout"],
        tree_sha=options["tree"],
        manifest_sha256=manifest.sha256,
        workflow_identity=lanes.ExpectedWorkflowIdentity(**options["workflow_identity"]),
        expected_platform="linux",
        manifest=manifest,
        lock_sha256=bound["files"]["lock"]["sha256"],
    )
    windows.validate_windows_smoke_artifact(
        artifacts,
        job_result="success",
        head_sha=options["checkout"],
        tree_sha=options["tree"],
        workflow_identity=windows.ExpectedWorkflowIdentity(**options["workflow_identity"]),
    )
    require(
        binding(context) == bound and inventory(evidence_root) == before,
        "inputs changed during validation",
    )
    require(fresh(refresh_metadata, options) == metadata, "metadata changed during validation")
    raw = encoded({"schema": SCHEMA, "binding": bound, "metadata": metadata, "inventory": before})
    fd, temporary = tempfile.mkstemp(prefix=".ci-receipt-", dir=receipt_path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, receipt_path)  # Atomic publish; existing destination never replaced.
    finally:
        os.unlink(temporary)
    return digest(raw)


def warm_reuse(
    receipt_path: Path,
    evidence_root: Path,
    context: dict[str, Any],
    refresh_metadata: Callable[[], dict[str, Any]],
    *,
    trusted_sha256: str,
) -> dict[str, Any]:
    """No official content validators or downloads; uncertainty rejects reuse."""
    require(
        isinstance(trusted_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", trusted_sha256) is not None,
        "trusted receipt SHA256 required",
    )
    safe_path(receipt_path)
    raw = receipt_path.read_bytes()
    require(digest(raw) == trusted_sha256, "trusted receipt SHA256 mismatch")
    receipt = json.loads(raw)
    require(
        set(receipt) == {"schema", "binding", "metadata", "inventory"}
        and receipt["schema"] == SCHEMA,
        "unsupported/incomplete receipt; legacy receipts rejected",
    )
    bound = binding(context)
    require(receipt["binding"] == bound, "configuration or verifier changed")
    require(receipt["inventory"] == inventory(evidence_root), "retained evidence changed")
    require(
        receipt["metadata"] == fresh(refresh_metadata, bound["options"]), "GitHub identity changed"
    )
    require(
        binding(context) == bound and receipt["inventory"] == inventory(evidence_root),
        "inputs changed during reuse",
    )
    return receipt
