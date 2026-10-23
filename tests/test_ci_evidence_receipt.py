"""Synthetic producer/consumer checks; never contacts GitHub or runtime."""

import copy
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ci_evidence_receipt as receipt


@pytest.fixture
def case(tmp_path, monkeypatch):
    root = tmp_path / "retained"
    root.mkdir()
    head, tree = "a" * 40, "b" * 40
    options = dict(
        repository="org/repo",
        run_id=42,
        attempt=2,
        event="push",
        head=head,
        base="",
        checkout=head,
        tree=tree,
        parents=["c" * 40],
        branch="main",
        pr=None,
        workflow_identity=dict(
            event_name="push",
            ref="refs/heads/main",
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
    context = dict(options=options, repo_root=tmp_path)
    for key in ("manifest_path", "lock_path", "adapter_path"):
        context[key] = tmp_path / key
        context[key].write_text("synthetic")
    metadata = dict(
        run=dict(
            id=42,
            run_attempt=2,
            status="completed",
            conclusion="success",
            repository=dict(full_name="org/repo"),
            head_repository=dict(full_name="org/repo"),
            head_sha=head,
            event="push",
            head_branch="main",
        ),
        jobs=dict(
            total_count=8,
            jobs=[
                dict(
                    id=i,
                    name=name,
                    conclusion=result,
                    run_id=42,
                    run_attempt=2,
                    head_sha=head,
                    status="completed",
                )
                for i, (name, result) in enumerate(options["expected_jobs"].items())
            ],
        ),
        artifacts=dict(total_count=5, artifacts=[]),
        commit=dict(sha=head, tree=dict(sha=tree), parents=[dict(sha="c" * 40)]),
    )
    downloads = 0
    for i, name in enumerate(
        ("quality", "windows-smoke", "lane-garmin", "lane-core-sleep", "lane-app-ingest")
    ):
        name = f"ci-{name}-42-2"
        extracted = root / "artifacts" / name
        extracted.mkdir(parents=True)
        (extracted / "report").write_bytes(b"synthetic official evidence")
        archive = root / (name + ".zip")
        with zipfile.ZipFile(archive, "w") as stream:
            stream.write(extracted / "report", "report")
        downloads += 1
        metadata["artifacts"]["artifacts"].append(
            dict(
                id=i,
                name=name,
                expired=False,
                digest="sha256:" + receipt.digest(archive.read_bytes()),
                size_in_bytes=archive.stat().st_size,
                workflow_run=dict(id=42, head_sha=head),
            )
        )
    calls = []
    for module, name in (
        (receipt.lanes, "validate_manifest"),
        (receipt.lanes, "validate_attempt_artifacts"),
        (receipt.lanes, "validate_gate_job_results"),
        (receipt.lanes, "validate_gate_artifacts"),
        (receipt.windows, "validate_windows_smoke_artifact"),
    ):

        def fake(*args, _name=name, **kwargs):
            calls.append(_name)
            return SimpleNamespace(sha256="d" * 64)

        monkeypatch.setattr(module, name, fake)
    target = tmp_path / "receipt.json"

    def refresh():
        return copy.deepcopy(metadata)

    pin = receipt.cold_verify(target, root, context, refresh)
    return SimpleNamespace(
        root=root,
        target=target,
        context=context,
        metadata=metadata,
        refresh=refresh,
        pin=pin,
        calls=calls,
        downloads=downloads,
    )


def warm(case, **kwargs):
    return receipt.warm_reuse(
        case.target,
        case.root,
        case.context,
        case.refresh,
        trusted_sha256=kwargs.get("pin", case.pin),
    )


def test_cold_then_warm_no_downloads_or_validators(case):
    assert len(case.calls) == 5 and case.downloads == 5
    assert warm(case)["schema"] == receipt.SCHEMA
    assert warm(case)["schema"] == receipt.SCHEMA
    assert len(case.calls) == 5 and case.downloads == 5
    with pytest.raises(receipt.ReceiptError, match="already exists"):
        receipt.cold_verify(case.target, case.root, case.context, case.refresh)
    assert len(case.calls) == 5


@pytest.mark.parametrize("pin", ["", None, "f" * 64])
def test_trusted_pin_required(case, pin):
    with pytest.raises(receipt.ReceiptError, match="SHA256"):
        warm(case, pin=pin)


@pytest.mark.parametrize("change", ["extra", "missing", "tamper", "case", "unsafe"])
def test_retained_integrity(case, change):
    path = next((case.root / "artifacts").rglob("report"))
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
        data["jobs"]["jobs"][0]["run_attempt"] = 1
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
        data["commit"]["parents"] = []
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
    with pytest.raises(receipt.ReceiptError, match="configuration or verifier"):
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


def test_cold_official_failure_never_publishes(case, monkeypatch):
    case.target.unlink()

    def reject(*args, **kwargs):
        raise receipt.lanes.ContractError("official rejection")

    monkeypatch.setattr(receipt.lanes, "validate_gate_artifacts", reject)
    with pytest.raises(receipt.lanes.ContractError, match="official rejection"):
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
    with pytest.raises(receipt.ReceiptError, match="configuration or verifier"):
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
    data["run"].update(event="pull_request", head_branch="feature")
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
