"""Synthetic exact-tree delegation, complete PR gate, and mutable API races."""

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
sys.path.remove(str(ROOT / "scripts"))

REPO = "Synthetic/Health-Check"
BRANCH = "task/246-ci-event-dedup"


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def candidate(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "synthetic@example.invalid")
    git(root, "config", "user.name", "Synthetic")
    git(root, "config", "core.autocrlf", "false")
    (root / "code.py").write_text("before\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "base")
    base = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "-b", BRANCH)
    (root / "code.py").write_text("after\n")
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
    assert record["pr_checkout"]["required_mode"] == "full"
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
    api = FakeAPI(root, record)
    return root, push, api


class FakeAPI:
    def __init__(self, root, record):
        self.record = record
        identity = record["pr_checkout"]["identity"]
        head, base, merge = [identity[key] for key in ("PR_HEAD_SHA", "PR_BASE_SHA", "GITHUB_SHA")]
        self.pr = {
            "number": 246,
            "state": "open",
            "merged": False,
            "mergeable": True,
            "head": {"sha": head, "ref": BRANCH, "repo": {"full_name": REPO}},
            "base": {"sha": base, "ref": "main", "repo": {"full_name": REPO}},
            "merge_commit_sha": merge,
        }
        self.refs = {f"heads/{BRANCH}": head, "heads/main": base, "pull/246/merge": merge}
        self.commits = {
            value: {
                "sha": value,
                "tree": {"sha": git(root, "rev-parse", f"{value}^{{tree}}")},
                "parents": [
                    {"sha": p} for p in git(root, "show", "-s", "--format=%P", value).split()
                ],
            }
            for value in (base, head, merge)
        }
        self.run = {
            "id": 123,
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "event": "pull_request",
            "path": ".github/workflows/ci.yml",
            "head_branch": BRANCH,
            "head_sha": head,
        }
        self.jobs = [
            {
                "name": name,
                "run_id": 123,
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "skipped" if name == "docs" else "success",
            }
            for name in (
                "classify",
                "docs",
                "quality",
                "test (garmin)",
                "test (core-sleep)",
                "test (app-ingest)",
                "windows-smoke",
                "checks",
            )
        ]
        self.artifacts = [{"id": 7, "name": "event-decision-123-1", "expired": False}]
        self.prs = [self.pr]
        self.calls = 0
        self.mutate = None

    def get(self, path):
        self.calls += 1
        if self.mutate:
            self.mutate(self, path)
        if path.startswith("pulls?"):
            value = self.prs
        elif path == "pulls/246":
            value = self.pr
        elif path.startswith("git/ref/"):
            value = {"object": {"sha": self.refs[path.removeprefix("git/ref/")]}}
        elif path.startswith("git/commits/"):
            value = self.commits[path.removeprefix("git/commits/")]
        elif path.startswith("actions/workflows/"):
            value = {"total_count": 1, "workflow_runs": [self.run]}
        elif "/jobs?" in path:
            value = {"total_count": len(self.jobs), "jobs": self.jobs}
        elif "/artifacts?" in path:
            value = {"total_count": len(self.artifacts), "artifacts": self.artifacts}
        else:
            raise AssertionError(path)
        return copy.deepcopy(value)

    def decision(self, artifact_id):
        assert artifact_id == 7
        return copy.deepcopy(self.record)


def test_equal_tree_keeps_distinct_commit_identities(candidate):
    root, identity, api = candidate
    record = ROUTE.route(root, identity, REPO, api)
    assert record["delegated"] is True
    assert record["pr"]["head"] != record["pr"]["merge"]
    assert record["pr"]["head_tree"] == record["pr"]["merge_tree"]
    assert record["pr_run"]["run_id"] == 123
    assert record["pr_run"]["attempt"] == 1


@pytest.mark.parametrize(
    "case",
    [
        "no-pr",
        "many-prs",
        "closed",
        "merged",
        "foreign-head",
        "foreign-base",
        "wrong-branch",
        "stale-head",
        "base-moved",
        "merge-ref-moved",
        "missing-merge",
        "unknown-mergeable",
        "different-tree",
        "wrong-parents",
        "lookup-failure",
        "foreign-run",
        "stale-run",
        "run-failed",
        "run-cancelled",
        "missing-job",
        "windows-failed",
        "janitor-job-failed",
        "checks-skipped",
        "docs-only",
        "expired",
        "missing-artifact",
        "foreign-checkout",
        "foreign-tree",
        "foreign-attempt",
        "wrong-job-attempt",
        "dirty",
        "stale-checkout",
        "wrong-repository",
        "superseded",
        "PR-race",
        "base-race",
        "merge-race",
        "attempt-race",
        "timeout",
    ],
)
def test_uncertainty_keeps_task_push_full(candidate, case):
    root, identity, api = candidate
    proof = api.record["pr_checkout"]
    if case == "no-pr":
        api.prs = []
    elif case == "many-prs":
        api.prs *= 2
    elif case in {"closed", "merged", "unknown-mergeable"}:
        api.pr[{"closed": "state", "merged": "merged", "unknown-mergeable": "mergeable"}[case]] = {
            "closed": "closed",
            "merged": True,
            "unknown-mergeable": None,
        }[case]
    elif case in {"foreign-head", "foreign-base"}:
        api.pr[case.split("-")[1]]["repo"]["full_name"] = "Foreign/Health-Check"
    elif case == "wrong-branch":
        api.pr["head"]["ref"] = "task/other"
    elif case == "stale-head":
        api.pr["head"]["sha"] = "a" * 40
    elif case == "base-moved":
        api.refs["heads/main"] = "a" * 40
    elif case == "merge-ref-moved":
        api.refs["pull/246/merge"] = "a" * 40
    elif case == "missing-merge":
        api.pr["merge_commit_sha"] = None
    elif case == "different-tree":
        api.commits[api.pr["merge_commit_sha"]]["tree"]["sha"] = "a" * 40
    elif case == "wrong-parents":
        api.commits[api.pr["merge_commit_sha"]]["parents"].reverse()
    elif case == "lookup-failure":

        def fail(*_):
            raise subprocess.CalledProcessError(1, "gh")

        api.get = fail
    elif case in {"foreign-run", "stale-run", "run-failed", "run-cancelled"}:
        api.run[
            {
                "foreign-run": "event",
                "stale-run": "head_sha",
                "run-failed": "conclusion",
                "run-cancelled": "conclusion",
            }[case]
        ] = {
            "foreign-run": "push",
            "stale-run": "a" * 40,
            "run-failed": "failure",
            "run-cancelled": "cancelled",
        }[case]
    elif case == "missing-job":
        api.jobs.pop()
    elif case in {"windows-failed", "janitor-job-failed", "checks-skipped", "wrong-job-attempt"}:
        api.jobs[-2 if "failed" in case else -1][
            "run_attempt" if case == "wrong-job-attempt" else "conclusion"
        ] = (
            2
            if case == "wrong-job-attempt"
            else "skipped"
            if case == "checks-skipped"
            else "failure"
        )
    elif case == "docs-only":
        proof["required_mode"] = "docs"
    elif case == "expired":
        api.artifacts[0]["expired"] = True
    elif case == "missing-artifact":
        api.artifacts.clear()
    elif case in {"foreign-checkout", "foreign-attempt"}:
        proof["identity"]["GITHUB_SHA" if case == "foreign-checkout" else "GITHUB_RUN_ATTEMPT"] = (
            "2"
        )
    elif case == "foreign-tree":
        proof["merge_tree"] = "a" * 40
    elif case == "dirty":
        (root / "code.py").write_text("dirty\n")
    elif case == "stale-checkout":
        identity["GITHUB_SHA"] = api.pr["base"]["sha"]
    elif case == "wrong-repository":
        api.record["repository"] = "Foreign/Health-Check"
    elif case in {"superseded", "PR-race", "base-race", "merge-race", "attempt-race"}:

        def mutate(fake, path):
            if fake.calls > 10:
                if case == "superseded":
                    fake.run["id"] = 789
                elif case == "attempt-race":
                    fake.run["run_attempt"] = 2
                elif case == "PR-race":
                    fake.pr["state"] = "closed"
                elif case == "base-race":
                    fake.refs["heads/main"] = "a" * 40
                else:
                    fake.refs["pull/246/merge"] = "a" * 40

        api.mutate = mutate
    elif case == "timeout":
        api.run.update(status="in_progress", conclusion=None)
    record = ROUTE.route(root, identity, REPO, api, wait_seconds=0)
    assert record["delegated"] is False
    assert record["reason"] == "unproven-keep-full"


def test_wait_observes_one_exact_attempt_without_rerunning(candidate):
    root, identity, api = candidate
    api.run.update(status="in_progress", conclusion=None)

    def finish(_):
        api.run.update(status="completed", conclusion="success")

    record = ROUTE.route(root, identity, REPO, api, sleep=finish)
    assert record["delegated"] is True


@pytest.mark.parametrize("change", ["missing-run", "wrong-PR", "wrong-target", "failed-wait"])
def test_missing_wrong_or_failed_corresponding_run_keeps_full(candidate, change):
    root, identity, api = candidate
    if change == "missing-run":
        original = api.get

        def missing(path):
            if path.startswith("actions/workflows/"):
                return {"total_count": 0, "workflow_runs": []}
            return original(path)

        api.get = missing
    elif change == "wrong-PR":
        api.prs = [copy.deepcopy(api.pr)]
        api.pr["number"] = 247
    elif change == "wrong-target":
        api.pr["base"]["ref"] = "integration/release"
    else:
        api.run.update(status="in_progress", conclusion=None)

    def failed(_):
        api.run.update(status="completed", conclusion="failure")

    assert ROUTE.route(root, identity, REPO, api, sleep=failed)["delegated"] is False


@pytest.mark.parametrize(
    "event,ref",
    [
        ("push", "refs/heads/main"),
        ("push", "refs/heads/integration/release"),
        ("push", "refs/heads/other"),
        ("push", "refs/tags/task/test"),
        ("pull_request", "refs/pull/1/merge"),
        ("pull_request_target", "refs/heads/main"),
    ],
)
def test_other_events_never_lookup_or_delegate(candidate, event, ref):
    root, identity, api = candidate
    identity.update(GITHUB_EVENT_NAME=event, GITHUB_REF=ref)
    assert ROUTE.route(root, identity, REPO, api)["delegated"] is False
    assert api.calls == 0


def test_pr_record_proves_actual_checkout_and_full_docs_mode_separately(candidate):
    root, _, api = candidate
    identity = api.record["pr_checkout"]["identity"]
    assert "pr_checkout" not in ROUTE.route(root, identity, REPO)  # task checkout, not merge
    git(root, "checkout", identity["GITHUB_SHA"])
    observed = ROUTE.route(root, identity, REPO)
    assert observed["pr_checkout"] == api.record["pr_checkout"]
    assert observed["delegated"] is False
    assert json.dumps(observed)
