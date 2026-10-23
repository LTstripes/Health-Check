"""Synthetic producer/consumer checks; never contacts GitHub or runtime."""

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ci_evidence_receipt as receipt


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args]).decode().strip()


@pytest.fixture
def case(tmp_path):
    from test_ci_test_lanes import _complete_gate_fixture
    from test_ci_workflow import _windows_smoke_fixture

    root = tmp_path / "retained"
    root.mkdir()
    artifacts, _, _, _, _ = _complete_gate_fixture(root)
    windows_root, _, _ = _windows_smoke_fixture(tmp_path / "windows")
    shutil.move(str(windows_root / "ci-windows-smoke-123-1"), artifacts)
    repo = root / "repo"
    source_repo = Path(__file__).resolve().parents[1]
    for relative in receipt.CANONICAL_INPUTS:
        if relative == "ci/test-lanes.json":
            continue  # Existing helper's exact three-test synthetic manifest.
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_repo / relative, target)
    git(repo, "init", "--quiet")
    git(repo, "config", "user.name", "Synthetic Receipt Test")
    git(repo, "config", "user.email", "synthetic@example.invalid")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "remote", "add", "origin", "https://github.com/org/repo.git")
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "-m", "synthetic canonical inputs")
    head, tree = git(repo, "rev-parse", "HEAD"), git(repo, "rev-parse", "HEAD^{tree}")
    lock = receipt.digest((repo / "uv.lock").read_bytes())
    branch = "task/125-ci-windows-smoke"
    options = dict(
        repository="org/repo",
        workflow_id=348658344,
        run_id=123,
        attempt=1,
        event="push",
        head=head,
        base="",
        checkout=head,
        tree=tree,
        parents=[],
        branch=branch,
        pr=None,
        workflow_identity=dict(
            event_name="push",
            ref=f"refs/heads/{branch}",
            pr_base_ref="",
            pr_base_sha="",
            pr_head_ref="",
            pr_head_sha="",
        ),
        expected_jobs={
            "classify": "success",
            "docs": "skipped",
            "quality": "success",
            "windows-smoke": "success",
            "test (garmin)": "success",
            "test (core-sleep)": "success",
            "test (app-ingest)": "success",
            "checks": "success",
        },
    )
    context = dict(
        options=options,
        repo_root=repo,
        manifest_path=repo / "ci/test-lanes.json",
        lock_path=repo / "uv.lock",
        adapter_path=tmp_path / "adapter.py",
    )
    context["adapter_path"].write_text("# trusted synthetic operator adapter")
    # Adapt existing official fixtures' identities to the real synthetic Git commit.
    for path in artifacts.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            for before, after in (
                ("a" * 40, head),
                ("b" * 40, tree),
                ("e" * 64, lock),
                ("refs/heads/task/synthetic", f"refs/heads/{branch}"),
            ):
                text = text.replace(before, after)
            path.write_bytes(text.encode("utf-8"))
    # Only retained evidence belongs in this directory; canonical checkout is separate.
    moved_repo = tmp_path / "canonical-repo"
    shutil.move(str(repo), moved_repo)
    context.update(
        repo_root=moved_repo,
        manifest_path=moved_repo / "ci/test-lanes.json",
        lock_path=moved_repo / "uv.lock",
    )
    metadata = dict(
        run=dict(
            id=123,
            run_attempt=1,
            workflow_id=348658344,
            path=receipt.WORKFLOW,
            status="completed",
            conclusion="success",
            repository=dict(full_name="org/repo"),
            head_repository=dict(full_name="org/repo"),
            head_sha=head,
            event="push",
            head_branch=branch,
        ),
        jobs=dict(
            total_count=8,
            jobs=[
                dict(
                    id=i,
                    name=name,
                    conclusion=result,
                    run_id=123,
                    run_attempt=1,
                    head_sha=head,
                    status="completed",
                )
                for i, (name, result) in enumerate(options["expected_jobs"].items())
            ],
        ),
        artifacts=dict(total_count=8, artifacts=[]),
        commit=dict(sha=head, tree=dict(sha=tree), parents=[]),
    )
    for name in ("event-decision", "docs-decision", "workspace-retirement"):
        target = artifacts / f"{name}-123-1"
        target.mkdir()
        (target / "report.json").write_text('{"synthetic":true}')
    downloads = 0
    for i, extracted in enumerate(sorted(artifacts.iterdir())):
        archive = root / (extracted.name + ".zip")
        with zipfile.ZipFile(archive, "w") as stream:
            for path in sorted(extracted.rglob("*")):
                if path.is_file():
                    stream.write(path, path.relative_to(extracted).as_posix())
        downloads += 1
        metadata["artifacts"]["artifacts"].append(
            dict(
                id=i,
                name=extracted.name,
                expired=False,
                digest="sha256:" + receipt.digest(archive.read_bytes()),
                size_in_bytes=archive.stat().st_size,
                workflow_run=dict(id=123, head_sha=head),
            )
        )
    calls = []
    # Profile real official invocations without replacing any validator implementation.
    official = {
        getattr(module, name).__code__: name
        for module, name in (
            (receipt.lanes, "validate_manifest"),
            (receipt.lanes, "validate_attempt_artifacts"),
            (receipt.lanes, "validate_gate_job_results"),
            (receipt.lanes, "validate_gate_artifacts"),
            (receipt.windows, "validate_windows_smoke_artifact"),
        )
    }

    def profile(frame, event, arg):
        if event == "call" and frame.f_code in official:
            calls.append(official[frame.f_code])

    def refresh():
        return copy.deepcopy(metadata)

    target = tmp_path / "receipt.json"
    sys.setprofile(profile)
    try:
        pin = receipt.cold_verify(target, root, context, refresh)
        yield SimpleNamespace(
            root=root,
            target=target,
            context=context,
            metadata=metadata,
            refresh=refresh,
            pin=pin,
            calls=calls,
            downloads=downloads,
        )
    finally:
        sys.setprofile(None)


def warm(case, **kwargs):
    return receipt.warm_reuse(
        case.target,
        case.root,
        case.context,
        case.refresh,
        trusted_sha256=kwargs.get("pin", case.pin),
    )


def test_cold_then_warm_no_downloads_or_validators(case):
    assert len(case.calls) == 5 and case.downloads == 8
    assert warm(case)["schema"] == receipt.SCHEMA
    assert warm(case)["schema"] == receipt.SCHEMA
    assert len(case.calls) == 5 and case.downloads == 8
    with pytest.raises(receipt.ReceiptError, match="already exists"):
        receipt.cold_verify(case.target, case.root, case.context, case.refresh)
    assert len(case.calls) == 5


@pytest.mark.parametrize("pin", ["", None, "f" * 64])
def test_trusted_pin_required(case, pin):
    with pytest.raises(receipt.ReceiptError, match="SHA256"):
        warm(case, pin=pin)


@pytest.mark.parametrize("change", ["extra", "missing", "tamper", "case", "unsafe"])
def test_retained_integrity(case, change):
    path = next((case.root / "artifacts").rglob("report.json"))
    if change == "missing":
        path.unlink()
    elif change == "tamper":
        path.write_text("changed")
    elif change == "case":
        # Case-insensitive Windows refuses distinct entries; test folded directory identity instead.
        original = receipt.inventory(case.root)
        altered = {key.upper(): value for key, value in original.items()}
        raw = json.loads(case.target.read_bytes())
        raw["inventory"] = altered
        case.target.write_bytes(receipt.encoded(raw))
        case.pin = receipt.digest(case.target.read_bytes())
    else:
        (case.root / ("extra" if change == "extra" else "bad.")).write_text("extra")
    with pytest.raises(receipt.ReceiptError):
        warm(case)
    assert len(case.calls) == 5


@pytest.mark.parametrize(
    "change",
    [
        "attempt",
        "failed",
        "job_attempt",
        "jobs_missing",
        "expired",
        "deleted",
        "foreign",
        "digest",
        "tree",
        "parents",
        "artifact_id",
    ],
)
def test_fresh_metadata_rejects(case, change):
    data = case.metadata
    if change == "attempt":
        data["run"]["run_attempt"] += 1
    elif change == "failed":
        data["jobs"]["jobs"][0]["conclusion"] = "failure"
    elif change == "job_attempt":
        data["jobs"]["jobs"][0]["run_attempt"] = 2
    elif change == "jobs_missing":
        data["jobs"]["jobs"].pop()
    elif change == "expired":
        data["artifacts"]["artifacts"][0]["expired"] = True
    elif change == "deleted":
        data["artifacts"]["artifacts"].pop()
    elif change == "foreign":
        data["artifacts"]["artifacts"][0]["workflow_run"]["id"] = 9
    elif change == "digest":
        data["artifacts"]["artifacts"][0]["digest"] = "sha256:" + "f" * 64
    elif change == "artifact_id":
        data["artifacts"]["artifacts"][0]["id"] = 99
    elif change == "tree":
        data["commit"]["tree"]["sha"] = "f" * 40
    else:
        data["commit"]["parents"] = [dict(sha="f" * 40)]
    with pytest.raises(receipt.ReceiptError):
        warm(case)
    assert len(case.calls) == 5


def test_harmless_mutable_metadata(case):
    case.metadata["run"]["updated_at"] = "later"
    case.metadata["jobs"]["jobs"][0]["html_url"] = "changed URL"
    warm(case)


def test_network_uncertainty(case):
    def offline():
        raise OSError("offline")

    with pytest.raises(receipt.ReceiptError, match="unavailable"):
        receipt.warm_reuse(case.target, case.root, case.context, offline, trusted_sha256=case.pin)


@pytest.mark.parametrize("key", ["manifest_path", "lock_path", "adapter_path"])
def test_changed_configuration_or_tool(case, key):
    case.context[key].write_text("changed")
    with pytest.raises(receipt.ReceiptError):
        warm(case)


def test_legacy_receipt_rejected(case):
    case.target.write_text('{"status":"PASS","schema_version":1}')
    case.pin = hashlib.sha256(case.target.read_bytes()).hexdigest()
    with pytest.raises(receipt.ReceiptError, match="legacy"):
        warm(case)


def test_symlink_rejected(case):
    path = case.root / "alias"
    try:
        path.symlink_to(case.context["adapter_path"])
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    with pytest.raises(receipt.ReceiptError, match="symlink|reparse"):
        warm(case)


def test_cold_official_failure_never_publishes(case):
    case.target.unlink()
    artifact = case.root / "artifacts/ci-lane-garmin-123-1"
    report = artifact / "verified.json"
    value = json.loads(report.read_bytes())
    value["counts"]["failed"] = 1
    report.write_bytes(receipt.encoded(value))
    archive = case.root / (artifact.name + ".zip")
    with zipfile.ZipFile(archive, "w") as stream:
        for path in sorted(artifact.rglob("*")):
            if path.is_file():
                stream.write(path, path.relative_to(artifact).as_posix())
    item = next(a for a in case.metadata["artifacts"]["artifacts"] if a["name"] == artifact.name)
    item["digest"] = "sha256:" + receipt.digest(archive.read_bytes())
    item["size_in_bytes"] = archive.stat().st_size
    with pytest.raises(receipt.lanes.ContractError):
        receipt.cold_verify(case.target, case.root, case.context, case.refresh)
    assert not case.target.exists()


def test_cold_zip_digest_required(case):
    case.target.unlink()
    next(case.root.glob("*.zip")).write_bytes(b"changed original ZIP")
    with pytest.raises(receipt.ReceiptError, match="ZIP digest"):
        receipt.cold_verify(case.target, case.root, case.context, case.refresh)
    assert not case.target.exists()
    assert len(case.calls) == 5


def test_changed_loaded_validator_rejected(case, monkeypatch):
    def replacement(*args, **kwargs):
        raise AssertionError("warm must not call validator")

    monkeypatch.setattr(receipt.lanes, "validate_gate_artifacts", replacement)
    with pytest.raises(receipt.ReceiptError):
        warm(case)


def test_case_collision_rejected(case, monkeypatch):
    monkeypatch.setattr(
        receipt.os,
        "walk",
        lambda *args, **kwargs: [(str(case.root), [], ["duplicate", "DUPLICATE"])],
    )
    (case.root / "duplicate").write_text("same Windows file")
    with pytest.raises(receipt.ReceiptError, match="case-colliding"):
        receipt.inventory(case.root)


def test_reparse_attribute_rejected(case, monkeypatch):
    original = Path.lstat

    def reparse(path):
        result = original(path)
        if path == case.root.absolute():
            return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
        return result

    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(receipt.ReceiptError, match="reparse"):
        warm(case)


@pytest.mark.parametrize("changed", [None, "head", "base", "merge", "state", "repo"])
def test_fresh_pr_identity(case, changed):
    options = copy.deepcopy(case.context["options"])
    options.update(
        event="pull_request",
        head="a" * 40,
        base="c" * 40,
        checkout="d" * 40,
        parents=["c" * 40, "a" * 40],
        pr=7,
        branch="feature",
    )
    options["workflow_identity"] = dict(
        event_name="pull_request",
        ref="refs/pull/7/merge",
        pr_base_ref="main",
        pr_base_sha="c" * 40,
        pr_head_ref="feature",
        pr_head_sha="a" * 40,
    )
    data = copy.deepcopy(case.metadata)
    data["run"].update(event="pull_request", head_branch="feature", head_sha="a" * 40)
    for job in data["jobs"]["jobs"]:
        job["head_sha"] = "a" * 40
    for item in data["artifacts"]["artifacts"]:
        item["workflow_run"]["head_sha"] = "a" * 40
    data["commit"].update(sha="d" * 40, parents=[dict(sha="c" * 40), dict(sha="a" * 40)])
    data["pr"] = dict(
        number=7,
        state="open",
        merge_commit_sha="d" * 40,
        head=dict(sha="a" * 40, ref="feature", repo=dict(full_name="org/repo")),
        base=dict(sha="c" * 40, ref="main", repo=dict(full_name="org/repo")),
    )
    if changed in ("head", "base"):
        data["pr"][changed]["sha"] = "f" * 40
    elif changed == "merge":
        data["pr"]["merge_commit_sha"] = "f" * 40
    elif changed == "state":
        data["pr"]["state"] = "closed"
    elif changed == "repo":
        data["pr"]["head"]["repo"]["full_name"] = "foreign/repo"
    if changed:
        with pytest.raises(receipt.ReceiptError):
            receipt.metadata_identity(data, options)
    else:
        assert receipt.metadata_identity(data, options)["checkout"] == "d" * 40


@pytest.mark.parametrize("jobs", [{}, {"checks": "success"}, {"quality": "skipped"}])
def test_caller_cannot_weaken_required_job_set(case, jobs):
    case.context["options"]["expected_jobs"] = jobs
    with pytest.raises(receipt.ReceiptError, match="mandatory code-mode"):
        warm(case)


@pytest.mark.parametrize(
    "change",
    [
        "manifest",
        "lock",
        "origin",
        "root",
        "head",
        "tree",
        "workflow",
        "config",
        "verifier",
        "summary",
    ],
)
def test_noncanonical_inputs_rejected_before_cold_validators(case, change):
    case.target.unlink()
    repo = case.context["repo_root"]
    if change in ("manifest", "lock"):
        key = "manifest_path" if change == "manifest" else "lock_path"
        alternate = case.target.parent / "foreign-input"
        alternate.write_text("foreign configuration")
        case.context[key] = alternate
    elif change == "origin":
        git(repo, "remote", "set-url", "origin", "https://github.com/foreign/repository.git")
    elif change == "root":
        case.context["repo_root"] = case.root
    elif change in ("head", "tree"):
        case.context["options"][change] = "f" * 40
    else:
        relative = {
            "workflow": receipt.WORKFLOW,
            "config": "pyproject.toml",
            "verifier": "scripts/ci_test_lanes.py",
            "summary": "scripts/ci_evidence_summary.py",
        }[change]
        (repo / relative).write_text("foreign configuration")
    with pytest.raises(receipt.ReceiptError):
        receipt.cold_verify(case.target, case.root, case.context, case.refresh)
    assert not case.target.exists()
    assert len(case.calls) == 5


@pytest.mark.parametrize(
    "field,value", [("workflow_id", 999), ("path", ".github/workflows/foreign.yml")]
)
def test_foreign_workflow_rejected_before_cold_validators(case, field, value):
    case.target.unlink()
    case.metadata["run"][field] = value
    with pytest.raises(receipt.ReceiptError, match="foreign workflow"):
        receipt.cold_verify(case.target, case.root, case.context, case.refresh)
    assert len(case.calls) == 5
    assert not case.target.exists()


def test_only_five_content_artifacts_is_incomplete(case):
    data = case.metadata
    data["artifacts"]["artifacts"] = [
        a for a in data["artifacts"]["artifacts"] if a["name"].startswith("ci-")
    ]
    data["artifacts"]["total_count"] = 5
    with pytest.raises(receipt.ReceiptError, match="foreign/missing/mixed"):
        warm(case)


def test_canonical_pr_merge_with_same_tree_as_task_head(case):
    repo, options = case.context["repo_root"], copy.deepcopy(case.context["options"])
    base = git(repo, "commit-tree", options["tree"], "-m", "synthetic base")
    merge = git(
        repo,
        "commit-tree",
        options["tree"],
        "-p",
        base,
        "-p",
        options["head"],
        "-m",
        "synthetic PR merge",
    )
    options.update(
        event="pull_request", base=base, checkout=merge, parents=[base, options["head"]], pr=7
    )
    bound = receipt.canonical_binding(case.context, options)
    assert bound["local_head"] == options["head"] != options["checkout"]
    assert len(case.calls) == 5
