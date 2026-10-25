"""Actual PR checkout identity; no mutable API or cross-event success reuse."""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("ci_event_route", ROOT / "scripts/ci_event_route.py")
assert SPEC and SPEC.loader
ROUTE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ROUTE)
DOCS = sys.modules["ci_docs_gate"]
sys.path.remove(str(ROOT / "scripts"))

REPO = "Synthetic/Health-Check"
BRANCH = "task/366-pr-authoritative"


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def candidate(tmp_path):
    return make_candidate(tmp_path)


def make_candidate(tmp_path, docs=False):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "synthetic@example.invalid")
    git(root, "config", "user.name", "Synthetic")
    git(root, "config", "core.autocrlf", "false")
    (root / "code.py").write_text("before\n")
    for path in DOCS.POLICY_FILES:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / path).read_bytes())
    (root / "docs").mkdir()
    (root / "docs/PRODUCT_VISION.md").write_text("# Before\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "base")
    base = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "-b", BRANCH)
    changed = "docs/PRODUCT_VISION.md" if docs else "code.py"
    (root / changed).write_text("# After [source](../code.py)\n" if docs else "after\n")
    git(root, "commit", "-am", "head")
    head = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "main")
    git(root, "merge", "--no-ff", BRANCH, "-m", "merge")
    merge = git(root, "rev-parse", "HEAD")
    identity = dict.fromkeys(ROUTE.context(), "")
    identity.update(
        GITHUB_EVENT_NAME="pull_request",
        GITHUB_REF="refs/pull/246/merge",
        GITHUB_SHA=merge,
        GITHUB_RUN_ID="123",
        GITHUB_RUN_ATTEMPT="1",
        GITHUB_BASE_REF="main",
        PR_BASE_SHA=base,
        GITHUB_HEAD_REF=BRANCH,
        PR_HEAD_SHA=head,
    )
    record = ROUTE.route(root, identity, REPO)
    assert record["pr_checkout"]["required_mode"] == ("docs" if docs else "full")
    assert record["pr_checkout"]["head_tree"] == record["pr_checkout"]["merge_tree"]
    git(root, "checkout", BRANCH)
    push = dict(
        identity,
        GITHUB_EVENT_NAME="push",
        GITHUB_REF=f"refs/heads/{BRANCH}",
        GITHUB_SHA=head,
        GITHUB_RUN_ID="456",
        PR_HEAD_SHA="",
        PR_BASE_SHA="",
        GITHUB_BASE_REF="",
        GITHUB_HEAD_REF="",
    )
    return root, push, record


@pytest.mark.parametrize("docs", [False, True])
def test_pr_record_proves_actual_checkout_and_mode(tmp_path, docs):
    root, _, original = make_candidate(tmp_path, docs=docs)
    identity = original["pr_checkout"]["identity"]
    # A task checkout must never be represented as a PR merge checkout.
    assert "pr_checkout" not in ROUTE.route(root, identity, REPO)
    git(root, "checkout", identity["GITHUB_SHA"])
    observed = ROUTE.route(root, identity, REPO)
    assert observed["pr_checkout"] == original["pr_checkout"]
    assert observed["delegated"] is False
    assert observed["reason"] == "actual-PR-checkout"
    assert json.dumps(observed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("GITHUB_REF", "refs/heads/task/366-pr-authoritative"),
        ("GITHUB_REF", "refs/pull/1/head"),
        ("GITHUB_SHA", "0" * 40),
        ("GITHUB_SHA", "invalid"),
        ("PR_HEAD_SHA", "0" * 40),
        ("PR_BASE_SHA", "0" * 40),
        ("PR_HEAD_SHA", None),
    ],
)
def test_stale_or_malformed_pr_identity_cannot_supply_checkout_proof(candidate, field, value):
    root, _, original = candidate
    identity = copy.deepcopy(original["pr_checkout"]["identity"])
    git(root, "checkout", identity["GITHUB_SHA"])
    identity[field] = value
    observed = ROUTE.route(root, identity, REPO)
    assert "pr_checkout" not in observed
    assert observed["reason"] == "unproven-keep-full"
    assert observed["delegated"] is False


@pytest.mark.parametrize("mutation", ["dirty-tracked", "untracked", "reversed-parents"])
def test_pr_proof_rejects_dirty_checkout_and_wrong_parent_order(candidate, mutation):
    root, _, original = candidate
    identity = copy.deepcopy(original["pr_checkout"]["identity"])
    git(root, "checkout", identity["GITHUB_SHA"])
    if mutation == "dirty-tracked":
        (root / "code.py").write_text("dirty\n")
    elif mutation == "untracked":
        (root / "untracked.py").write_text("dirty\n")
    else:
        identity["PR_BASE_SHA"], identity["PR_HEAD_SHA"] = (
            identity["PR_HEAD_SHA"],
            identity["PR_BASE_SHA"],
        )
    observed = ROUTE.route(root, identity, REPO)
    assert "pr_checkout" not in observed
    assert observed["reason"] == "unproven-keep-full"


@pytest.mark.parametrize(
    "event,ref",
    [
        ("push", "refs/heads/task/366-pr-authoritative"),
        ("push", "refs/heads/main"),
        ("push", "refs/heads/integration/release"),
        ("push", "refs/heads/other"),
        ("push", "refs/tags/task/test"),
        ("pull_request_target", "refs/heads/main"),
    ],
)
def test_other_events_never_delegate_or_read_pr_evidence(candidate, monkeypatch, event, ref):
    root, identity, _ = candidate
    identity.update(GITHUB_EVENT_NAME=event, GITHUB_REF=ref)

    def unexpected(*args, **kwargs):
        pytest.fail("non-PR provenance must not inspect Git or wait for remote evidence")

    monkeypatch.setattr(ROUTE, "git", unexpected)
    monkeypatch.setattr(ROUTE.subprocess, "run", unexpected)
    observed = ROUTE.route(root, identity, REPO)
    assert observed["delegated"] is False
    assert "pr_checkout" not in observed
    assert observed["reason"] == "ordinary-gates"


def test_unprovable_docs_classification_cannot_turn_pr_into_a_skip(candidate):
    root, _, original = candidate
    identity = original["pr_checkout"]["identity"]
    git(root, "checkout", identity["GITHUB_SHA"])
    # Ordinary code changes must retain the full-mode fallback.
    observed = ROUTE.route(root, identity, REPO)
    assert observed["pr_checkout"]["required_mode"] == "full"
    assert observed["delegated"] is False


def test_base_movement_records_distinct_merge_tree_and_requires_full(docs_candidate_data):
    root, _, original = docs_candidate_data
    identity = copy.deepcopy(original["pr_checkout"]["identity"])
    git(root, "checkout", "main")
    git(root, "reset", "--hard", identity["PR_BASE_SHA"])
    (root / "code.py").write_text("new base\n")
    git(root, "commit", "-am", "base movement")
    identity["PR_BASE_SHA"] = git(root, "rev-parse", "HEAD")
    git(root, "merge", "--no-ff", BRANCH, "-m", "current merge")
    identity["GITHUB_SHA"] = git(root, "rev-parse", "HEAD")
    observed = ROUTE.route(root, identity, REPO)
    proof = observed["pr_checkout"]
    assert proof["head_tree"] != proof["merge_tree"]
    assert proof["required_mode"] == "full"
    assert proof["identity"] == identity
    assert observed["delegated"] is False


@pytest.fixture
def docs_candidate_data(tmp_path):
    return make_candidate(tmp_path, docs=True)


def test_cli_retains_event_artifact_without_github_api_or_output_contract(
    candidate, monkeypatch, tmp_path
):
    root, _, original = candidate
    identity = original["pr_checkout"]["identity"]
    git(root, "checkout", identity["GITHUB_SHA"])
    for key, value in identity.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    output = tmp_path / "event-decision-123-1"
    monkeypatch.setattr(sys, "argv", ["ci_event_route.py", "--output-dir", str(output)])
    monkeypatch.setattr(ROUTE, "__file__", str(root / "scripts/ci_event_route.py"))
    assert ROUTE.main() == 0
    record = json.loads((output / "decision.json").read_text(encoding="utf-8"))
    assert record["schema_version"] == 1
    assert record["pr_checkout"] == original["pr_checkout"]
    assert record["delegated"] is False
