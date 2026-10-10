"""Synthetic Git comparisons and fail-closed current-attempt docs evidence."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("ci_docs_gate", ROOT / "scripts/ci_docs_gate.py")
assert SPEC is not None and SPEC.loader is not None
GATE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GATE
SPEC.loader.exec_module(GATE)


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def commit(root):
    git(root, "add", "--all")
    git(root, "commit", "-m", "synthetic")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "synthetic@example.invalid")
    git(root, "config", "user.name", "Synthetic")
    git(root, "config", "core.autocrlf", "false")
    git(root, "config", "core.filemode", "false")
    git(root, "config", "core.symlinks", "false")
    for path in GATE.POLICY_FILES:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / path).read_bytes())
    for path in GATE.DOC_PATHS:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text("# Synthetic prose\n", encoding="utf-8")
    for path in ("README.md", "tests/fixture.md", "src/runtime.py", "uv.lock"):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("synthetic\n", encoding="utf-8")
    base = commit(root)
    git(root, "checkout", "-b", "topic")
    return root, base


def merge(repo):
    root, base = repo
    head = commit(root)
    git(root, "checkout", "main")
    git(root, "merge", "--no-ff", "topic", "-m", "synthetic merge")
    identity = dict(
        zip(
            GATE.IDENTITY_ENV,
            (
                "pull_request",
                "refs/pull/246/merge",
                git(root, "rev-parse", "HEAD"),
                "123",
                "1",
                "main",
                base,
                "topic",
                head,
            ),
            strict=True,
        )
    )
    return root, identity


def docs_candidate(repo, text="# Synthetic updated prose\n"):
    (repo[0] / "docs/PRODUCT_VISION.md").write_text(text, encoding="utf-8")
    return merge(repo)


def evidence(tmp_path, root, identity):
    artifacts = tmp_path / "evidence"
    decision = GATE.classify(root, identity)
    assert decision["mode"] == "docs"
    GATE.write_json(artifacts / "docs-decision-123-1/decision.json", decision)
    GATE.write_json(
        artifacts / "docs-outcome-123-1/outcome.json", GATE.check_documents(root, decision)
    )
    return artifacts


def route(root, artifacts, identity, **overrides):
    kwargs = dict(
        mode="docs", classify_result="success", docs_result="success", full_results=["skipped"] * 3
    )
    kwargs.update(overrides)
    return GATE.verify_route(root, artifacts, identity, **kwargs)


def test_pure_allowed_docs_complete_merge_comparison_and_bound_outcome(repo, tmp_path):
    root, identity = docs_candidate(repo)
    decision = GATE.classify(root, identity)
    assert decision["paths"] == ["docs/PRODUCT_VISION.md"]
    assert decision["trees"][1] == decision["trees"][2]
    assert decision["diff_sha256"][0] == decision["diff_sha256"][1]
    assert route(root, evidence(tmp_path, root, identity), identity) == "docs"


def test_actual_cli_docs_example_has_terminal_verifiable_outcome(repo, tmp_path):
    root, identity = docs_candidate(repo)
    artifacts = tmp_path / "cli-evidence"
    output = tmp_path / "github-output"
    env = {**os.environ, **identity, "GITHUB_OUTPUT": str(output)}
    command = [sys.executable, str(root / "scripts/ci_docs_gate.py")]
    for action, name in (("classify", "docs-decision-123-1"), ("check", "docs-outcome-123-1")):
        result = subprocess.run(
            command + [action, "--output-dir", str(artifacts / name)],
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    assert output.read_text().strip() == "mode=docs"
    env.update(
        CI_MODE="docs",
        CLASSIFY_RESULT="success",
        DOCS_RESULT="success",
        QUALITY_RESULT="skipped",
        TEST_RESULT="skipped",
        WINDOWS_RESULT="skipped",
    )
    result = subprocess.run(
        command + ["route", "--artifacts-root", str(artifacts)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "docs"


# Exact prose paths audited for links/agent-policy consumers only. Policy/content
# and privacy review still applies even when the product test suite is skipped.
POLICY_PROSE = ("AGENTS.md", "docs/MODEL_ROUTING.md", "docs/OWNER_DATA_WORKFLOW.md")


@pytest.mark.parametrize("path", POLICY_PROSE)
def test_existing_policy_prose_has_complete_verified_docs_outcome(repo, tmp_path, path):
    (repo[0] / path).write_text("# Updated policy prose\n", encoding="utf-8")
    root, identity = merge(repo)
    decision = GATE.classify(root, identity)
    assert decision["mode"] == "docs"
    assert decision["paths"] == [path]
    assert route(root, evidence(tmp_path, root, identity), identity) == "docs"


def test_six_policy_paths_from_359_qualify_only_as_existing_prose_edits(repo, tmp_path):
    paths = (
        *POLICY_PROSE,
        "docs/ARCHITECTURE.md",
        "docs/DEVELOPMENT_PROCESS.md",
        "docs/PRODUCT_VISION.md",
    )
    for path in paths:
        (repo[0] / path).write_text("# Updated policy prose\n", encoding="utf-8")
    root, identity = merge(repo)
    decision = GATE.classify(root, identity)
    assert decision["mode"] == "docs"
    assert decision["paths"] == sorted(paths)
    assert route(root, evidence(tmp_path, root, identity), identity) == "docs"


@pytest.mark.parametrize("path", POLICY_PROSE)
@pytest.mark.parametrize("extra", ["src/runtime.py", "docs/new-policy.md", "tests/fixture.md"])
def test_policy_prose_with_code_new_prose_or_fixture_requires_full(repo, path, extra):
    (repo[0] / path).write_text("# Updated policy prose\n", encoding="utf-8")
    (repo[0] / extra).write_text("mixed change\n", encoding="utf-8")
    root, identity = merge(repo)
    assert GATE.classify(root, identity)["mode"] == "full"


@pytest.mark.parametrize("path", POLICY_PROSE)
@pytest.mark.parametrize(
    "content", [b"\0binary", b"[missing](missing.md)", b"Bearer " + b"x" * 30, b"\xffinvalid UTF-8"]
)
def test_policy_prose_retains_content_link_and_privacy_checks(repo, path, content):
    (repo[0] / path).write_bytes(content)
    root, identity = merge(repo)
    decision = GATE.classify(root, identity)
    assert decision["mode"] == "docs"
    with pytest.raises((GATE.DocsError, UnicodeError, subprocess.CalledProcessError)):
        GATE.check_documents(root, decision)


@pytest.mark.parametrize(
    "path",
    [
        "src/runtime.py",
        "tests/fixture.md",
        "README.md",
        "uv.lock",
        "pyproject.toml",
        "ci/test-lanes.json",
        "docs/new.md",
        "docs/config.json",
        ".github/workflows/ci.yml",
        "scripts/ci_docs_gate.py",
        "tests/test_fixture.py",
        "docs/agents/CODEX.md",
    ],
)
def test_mixed_unknown_fixture_build_dependency_and_policy_changes_require_full(repo, path):
    target = repo[0] / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("changed\n", encoding="utf-8")
    root, identity = docs_candidate(repo)
    assert GATE.classify(root, identity)["mode"] == "full"


@pytest.mark.parametrize("path", ("docs/PRODUCT_VISION.md", *POLICY_PROSE))
@pytest.mark.parametrize("operation", ["new", "rename", "delete", "executable", "symlink"])
def test_even_allowlisted_path_requires_existing_regular_unchanged_mode(repo, operation, path):
    root = repo[0]
    if operation == "new":
        git(root, "rm", path)
        git(root, "commit", "-m", "synthetic removal")
        base = git(root, "rev-parse", "HEAD")
        git(root, "branch", "-f", "main", base)
        repo = root, base
        (root / path).write_text("new\n")
    elif operation == "rename":
        git(root, "mv", path, "docs/ROADMAP-renamed.md")
    elif operation == "delete":
        git(root, "rm", path)
    elif operation == "executable":
        git(root, "update-index", "--chmod=+x", path)
    else:
        blob = git(root, "hash-object", "-w", "README.md")
        git(root, "update-index", "--cacheinfo", f"120000,{blob},{path}")
        git(root, "checkout-index", "--force", "--", path)
    # Preserve index-only synthetic modes; git add --all would erase the symlink mode.
    git(root, "commit", "-am", "synthetic change") if operation not in {"new", "symlink"} else (
        git(root, "add", path) if operation == "new" else None
    )
    if operation in {"new", "symlink"}:
        git(root, "commit", "-m", "synthetic change")
    head = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "main")
    git(root, "merge", "--no-ff", "topic", "-m", "synthetic merge")
    identity = dict(
        zip(
            GATE.IDENTITY_ENV,
            (
                "pull_request",
                "refs/pull/246/merge",
                git(root, "rev-parse", "HEAD"),
                "123",
                "1",
                "main",
                repo[1],
                "topic",
                head,
            ),
            strict=True,
        )
    )
    assert GATE.classify(root, identity)["mode"] == "full"


@pytest.mark.parametrize(
    "field,value",
    [
        ("PR_BASE_SHA", ""),
        ("PR_HEAD_SHA", "f" * 40),
        ("GITHUB_SHA", "a" * 40),
        ("GITHUB_RUN_ATTEMPT", ""),
        ("GITHUB_BASE_REF", ""),
        ("GITHUB_REF", "refs/heads/main"),
        ("PR_BASE_SHA", "--help"),
    ],
)
def test_missing_wrong_or_unsafe_identity_requires_full(repo, field, value):
    root, identity = docs_candidate(repo)
    identity[field] = value
    assert GATE.classify(root, identity)["mode"] == "full"


@pytest.mark.parametrize("ref", ["main", "integration/r01", "task/246-docs-pr-fast-path"])
def test_all_pushes_stay_full_even_for_allowed_docs(repo, ref):
    root, identity = docs_candidate(repo)
    identity.update(GITHUB_EVENT_NAME="push", GITHUB_REF=f"refs/heads/{ref}")
    assert GATE.classify(root, identity)["mode"] == "full"


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"incomplete",
        b":100644 100644 " + b"a" * 40 + b" " + b"b" * 40 + b" M\0docs/../docs/PRODUCT_VISION.md\0",
        b":160000 160000 " + b"a" * 40 + b" " + b"b" * 40 + b" M\0docs/ROADMAP.md\0",
    ],
)
def test_malformed_incomplete_unsafe_path_and_submodule_diff_fail_closed(repo, monkeypatch, raw):
    root, identity = docs_candidate(repo)
    original = GATE.git
    monkeypatch.setattr(
        GATE, "git", lambda root, *args: raw if args[0] == "diff" else original(root, *args)
    )
    assert GATE.classify(root, identity)["mode"] == "full"


def test_dirty_checkout_and_merge_head_tree_difference_require_full(repo):
    root, identity = docs_candidate(repo)
    (root / "unknown").write_text("untracked")
    assert GATE.classify(root, identity)["mode"] == "full"
    (root / "unknown").unlink()
    (root / "docs/ROADMAP.md").write_text("merge resolution")
    identity["GITHUB_SHA"] = commit(root)
    assert GATE.classify(root, identity)["mode"] == "full"


@pytest.mark.parametrize("mutation", ["base", "attempt", "diff", "mode", "schema", "outcome"])
def test_stale_foreign_decision_and_outcome_fail(repo, tmp_path, mutation):
    root, identity = docs_candidate(repo)
    artifacts = evidence(tmp_path, root, identity)
    path = artifacts / "docs-decision-123-1/decision.json"
    value = GATE.read_json(path)
    if mutation == "base":
        value["identity"]["PR_BASE_SHA"] = "b" * 40
    elif mutation == "attempt":
        value["identity"]["GITHUB_RUN_ATTEMPT"] = "2"
    elif mutation == "diff":
        value["diff_sha256"] = ["0" * 64] * 2
    elif mutation == "mode":
        value["mode"] = "full"
    elif mutation == "schema":
        value["schema_version"] = True
    else:
        path = artifacts / "docs-outcome-123-1/outcome.json"
        value = GATE.read_json(path)
        value["status"] = "failed"
    GATE.write_json(path, value)
    with pytest.raises(GATE.DocsError):
        route(root, artifacts, identity)


@pytest.mark.parametrize(
    "extra", ["ci-quality-123-1", "docs-outcome-123-2", "docs-decision-999-1", "unknown"]
)
def test_docs_rejects_mixed_or_foreign_artifact_sets(repo, tmp_path, extra):
    root, identity = docs_candidate(repo)
    artifacts = evidence(tmp_path, root, identity)
    (artifacts / extra).mkdir()
    with pytest.raises(GATE.DocsError):
        route(root, artifacts, identity)


@pytest.mark.parametrize(
    "name", ["docs-decision-123-1/decision.json", "docs-outcome-123-1/outcome.json"]
)
@pytest.mark.parametrize("replacement", [None, "{", "{}"])
def test_missing_malformed_incomplete_evidence_fails(repo, tmp_path, name, replacement):
    root, identity = docs_candidate(repo)
    artifacts = evidence(tmp_path, root, identity)
    path = artifacts / name
    if replacement is None:
        path.unlink()
    else:
        path.write_text(replacement)
    with pytest.raises(GATE.DocsError):
        route(root, artifacts, identity)


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", "", "unknown"])
def test_docs_requires_successful_classifier_and_document_checks(repo, tmp_path, result):
    root, identity = docs_candidate(repo)
    artifacts = evidence(tmp_path, root, identity)
    for job in ("classify_result", "docs_result"):
        with pytest.raises(GATE.DocsError):
            route(root, artifacts, identity, **{job: result})


@pytest.mark.parametrize("result", ["success", "failure", "cancelled", "", "unknown"])
@pytest.mark.parametrize("job", range(3))
def test_docs_only_allows_explicit_skip_for_each_full_job(repo, tmp_path, result, job):
    root, identity = docs_candidate(repo)
    artifacts = evidence(tmp_path, root, identity)
    results = ["skipped"] * 3
    results[job] = result
    with pytest.raises(GATE.DocsError):
        route(root, artifacts, identity, full_results=results)


@pytest.mark.parametrize(
    "text",
    ["\0binary", "# Prose\n[missing](missing.md)", "[escape](../../outside)", "Bearer " + "x" * 30],
)
def test_docs_checks_fail_for_invalid_text_links_and_credentials(repo, text):
    root, identity = docs_candidate(repo, text)
    with pytest.raises((GATE.DocsError, subprocess.CalledProcessError)):
        GATE.check_documents(root, GATE.classify(root, identity))


def test_docs_checks_local_links_without_execution_or_network(repo):
    root, identity = docs_candidate(
        repo,
        "# Prose\n[roadmap](ROADMAP.md#title)\n"
        "[web](https://example.invalid)\n```sh\nexit 1\n```\n",
    )
    assert GATE.check_documents(root, GATE.classify(root, identity))["status"] == "passed"


def test_classifier_failure_routes_to_full_but_cannot_waive_full_verifiers(repo, tmp_path):
    root, identity = docs_candidate(repo)
    artifacts = tmp_path / "empty"
    artifacts.mkdir()
    assert (
        route(
            root,
            artifacts,
            identity,
            mode="",
            classify_result="failure",
            docs_result="skipped",
            full_results=["success"] * 3,
        )
        == "full"
    )
    # Full acceptance still invokes unchanged verify-attempt/Linux/Windows verifiers.
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert '[ "$route" = full ] || exit 1' in workflow
    for command in (
        "ci_test_lanes.py verify-attempt",
        "ci_test_lanes.py gate",
        "ci_windows_smoke.py",
    ):
        assert command in workflow.split('[ "$route" = full ] || exit 1')[1]


def test_full_route_cannot_consume_docs_outcome(repo, tmp_path):
    root, identity = docs_candidate(repo)
    identity["GITHUB_EVENT_NAME"] = "push"
    artifacts = tmp_path / "full"
    GATE.write_json(artifacts / "docs-decision-123-1/decision.json", GATE.classify(root, identity))
    assert route(root, artifacts, identity, mode="full", docs_result="skipped") == "full"
    (artifacts / "docs-outcome-123-1").mkdir()
    with pytest.raises(GATE.DocsError):
        route(root, artifacts, identity, mode="full", docs_result="skipped")
