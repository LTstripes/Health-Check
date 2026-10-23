"""Synthetic exact-tree delegation, complete PR gate, and mutable API races."""

import copy
import importlib.util
import io
import json
import subprocess
import sys
import zipfile
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
    return make_candidate(tmp_path)


@pytest.fixture
def docs_candidate(tmp_path):
    return make_candidate(tmp_path, docs=True)


def make_candidate(tmp_path, docs=False):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "synthetic@example.invalid")
    git(root, "config", "user.name", "Synthetic")
    git(root, "config", "core.autocrlf", "false")
    (root / "code.py").write_text("before\n")
    for path in ROUTE.POLICY_FILES:
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
    api = FakeAPI(root, record)
    if docs:
        api.docs(root, identity)
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

    def decision(self, artifact_id, **options):
        if hasattr(self, "archives"):
            return ROUTE.GitHub.decision(self, artifact_id, **options)
        assert artifact_id == 7
        return copy.deepcopy(self.record)

    def docs(self, root, identity):
        gate = sys.modules["ci_docs_gate"]
        # Produce real Stage A records only while HEAD is the real PR merge commit.
        git(root, "checkout", identity["GITHUB_SHA"])
        decision = gate.classify(root, identity)
        assert decision["mode"] == "docs"
        outcome = gate.check_documents(root, decision)
        git(root, "checkout", BRANCH)
        expected = {
            "classify": "success",
            "docs": "success",
            "checks": "success",
            "quality": "skipped",
            "test": "skipped",
            "windows-smoke": "skipped",
        }
        self.jobs = [
            dict(id=i, name=name, conclusion=result, run_id=123, run_attempt=1, status="completed")
            for i, (name, result) in enumerate(expected.items(), start=1)
        ]
        self.artifacts = []
        self.archives = {}
        self.payloads = {}
        self.downloads = []
        for number, stem, filename, payload in (
            (7, "event-decision", "decision.json", self.record),
            (8, "docs-decision", "decision.json", decision),
            (9, "docs-outcome", "outcome.json", outcome),
        ):
            self.artifacts.append(
                dict(
                    id=number,
                    name=f"{stem}-123-1",
                    expired=False,
                    workflow_run=dict(id=123, head_sha=identity["PR_HEAD_SHA"]),
                )
            )
            self.payloads[number] = (filename, payload)
            self.pack(number)

    def pack(self, number, entries=None):
        filename, payload = self.payloads[number]
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for name, raw in entries or [(filename, ROUTE.canonical(payload).encode())]:
                archive.writestr(name, raw)
        self.archives[number] = stream.getvalue()
        item = next(a for a in self.artifacts if a["id"] == number)
        item.update(
            digest="sha256:" + ROUTE.digest(self.archives[number]),
            size_in_bytes=len(self.archives[number]),
        )

    def raw(self, path):
        number = int(path.split("/")[-2])
        self.downloads.append(number)
        return self.archives[number]


class Clock:
    def __init__(self):
        self.elapsed = 0

    def now(self):
        return self.elapsed

    def sleep(self, seconds):
        self.elapsed += seconds


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
    clock = Clock()
    record = ROUTE.route(
        root, identity, REPO, api, wait_seconds=1, monotonic=clock.now, sleep=clock.sleep
    )
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

    assert (
        ROUTE.route(
            root,
            identity,
            REPO,
            api,
            sleep=failed,
            wait_seconds=0 if change == "missing-run" else 420,
        )["delegated"]
        is False
    )


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


def test_docs_pr_delegates_from_real_stage_a_proof_without_rechecking_content(
    docs_candidate, monkeypatch
):
    root, identity, api = docs_candidate
    gate = sys.modules["ci_docs_gate"]

    def unexpected(*args, **kwargs):
        raise AssertionError("no content validator or fabricated PR checkout")

    monkeypatch.setattr(gate, "check_documents", unexpected)
    monkeypatch.setattr(ROUTE, "classify", unexpected)
    observed = ROUTE.route(root, identity, REPO, api)
    assert observed["delegated"] is True
    assert observed["pr_run"]["checkout"]["required_mode"] == "docs"
    assert observed["pr"]["head"] != observed["pr"]["merge"]
    assert git(root, "rev-parse", "HEAD") == observed["pr"]["head"]
    assert api.downloads == [7, 8, 9]
    assert len(observed["pr_run"]["docs"]["source"]["jobs"]) == 6


@pytest.mark.parametrize(
    "change",
    [
        "missing-job",
        "duplicate-job",
        "phantom-matrix",
        "classify-failed",
        "docs-failed",
        "checks-skipped",
        "quality-success",
        "test-success",
        "windows-success",
        "stale-job",
        "boolean-attempt",
        "missing-artifact",
        "duplicate-artifact",
        "expired",
        "foreign-artifact",
        "foreign-attempt",
        "missing-digest",
        "wrong-digest",
        "tampered-ZIP",
        "incomplete-artifacts",
        "incomplete-jobs",
        "decision-diff",
        "decision-policy",
        "decision-path",
        "decision-tree",
        "decision-schema",
        "outcome-document",
        "outcome-decision",
        "outcome-status",
        "outcome-check",
        "event-mode",
        "event-identity",
        "event-schema",
    ],
)
def test_docs_uncertainty_keeps_full(docs_candidate, change):
    root, identity, api = docs_candidate
    if change in ("missing-job", "duplicate-job", "phantom-matrix"):
        if change == "missing-job":
            api.jobs.pop()
        elif change == "duplicate-job":
            api.jobs[-1] = copy.deepcopy(api.jobs[0])
        else:
            api.jobs[4]["name"] = "test (garmin)"
    elif change in (
        "classify-failed",
        "docs-failed",
        "checks-skipped",
        "quality-success",
        "test-success",
        "windows-success",
    ):
        name = change.split("-")[0]
        name = "windows-smoke" if name == "windows" else name
        job = next(j for j in api.jobs if j["name"] == name)
        job["conclusion"] = (
            "failure"
            if change.endswith("failed")
            else "skipped"
            if change == "checks-skipped"
            else "success"
        )
    elif change in ("stale-job", "boolean-attempt"):
        api.jobs[0]["run_attempt"] = 2 if change == "stale-job" else True
    elif change == "missing-artifact":
        api.artifacts.pop()
    elif change == "duplicate-artifact":
        api.artifacts[-1] = copy.deepcopy(api.artifacts[1])
    elif change == "expired":
        api.artifacts[-1]["expired"] = True
    elif change == "foreign-artifact":
        api.artifacts[-1]["workflow_run"]["id"] = 999
    elif change == "foreign-attempt":
        api.artifacts[-1]["name"] = "docs-outcome-123-2"
    elif change == "missing-digest":
        api.artifacts[-1].pop("digest")
    elif change == "wrong-digest":
        api.artifacts[-1]["digest"] = "sha256:" + "0" * 64
    elif change == "tampered-ZIP":
        api.archives[9] += b"changed ZIP bytes"
    elif change in ("incomplete-artifacts", "incomplete-jobs"):
        original = api.get

        def incomplete(path):
            result = original(path)
            if ("/artifacts?" if change == "incomplete-artifacts" else "/jobs?") in path:
                result["total_count"] += 1
            return result

        api.get = incomplete
    elif change.startswith("decision-"):
        payload = api.payloads[8][1]
        if change == "decision-diff":
            payload["diff_sha256"] = ["0" * 64] * 2
        elif change == "decision-policy":
            payload["policy_sha256"][ROUTE.POLICY_FILES[0]] = "0" * 64
        elif change == "decision-path":
            payload["paths"] = ["code.py"]
        elif change == "decision-tree":
            payload["trees"][0] = "0" * 40
        else:
            payload["schema_version"] = True
        api.pack(8)
    elif change.startswith("outcome-"):
        payload = api.payloads[9][1]
        if change == "outcome-document":
            payload["documents"][0]["sha256"] = "0" * 64
        else:
            payload[
                {
                    "outcome-decision": "decision_sha256",
                    "outcome-status": "status",
                    "outcome-check": "check",
                }[change]
            ] = "foreign"
        api.pack(9)
    else:
        if change == "event-mode":
            api.record["pr_checkout"]["required_mode"] = "full"
        elif change == "event-identity":
            api.record["identity"] = dict(api.record["identity"], GITHUB_SHA="0" * 40)
        else:
            api.record["schema_version"] = True
        api.pack(7)
    observed = ROUTE.route(root, identity, REPO, api)
    assert observed["delegated"] is False
    assert observed["reason"] == "unproven-keep-full"


@pytest.mark.parametrize(
    "change",
    [
        "duplicate-entry",
        "extra-entry",
        "unsafe-name",
        "malformed",
        "non-object",
        "duplicate-key",
        "non-JSON",
        "oversize",
        "nested",
    ],
)
def test_docs_zip_is_bounded_unique_json(docs_candidate, change):
    root, identity, api = docs_candidate
    filename, payload = api.payloads[8]
    raw = ROUTE.canonical(payload).encode()
    if change == "duplicate-entry":
        with pytest.warns(UserWarning, match="Duplicate name"):
            api.pack(8, [(filename, raw), (filename, raw)])
    elif change == "extra-entry":
        api.pack(8, [(filename, raw), ("extra.json", b"{}")])
    elif change == "unsafe-name":
        api.pack(8, [("../decision.json", raw)])
    else:
        raw = {
            "malformed": b"{",
            "non-object": b"[]",
            "duplicate-key": b'{"mode":"docs",' + raw[1:],
            "non-JSON": b'{"value":NaN}',
            "oversize": b" " * 16385,
            "nested": b"[" * 1100 + b"0" + b"]" * 1100,
        }[change]
        api.pack(8, [(filename, raw)])
    assert ROUTE.route(root, identity, REPO, api)["delegated"] is False


@pytest.mark.parametrize("changed", ["job", "artifact", "PR", "base", "merge", "attempt", "run"])
def test_docs_post_read_races_keep_full(docs_candidate, changed):
    root, identity, api = docs_candidate
    original = api.raw

    def racing(path):
        raw = original(path)
        if path.endswith("/9/zip"):
            if changed == "job":
                api.jobs[0]["conclusion"] = "failure"
            elif changed == "artifact":
                api.artifacts[-1]["expired"] = True
            elif changed == "PR":
                api.pr["state"] = "closed"
            elif changed == "base":
                api.refs["heads/main"] = "0" * 40
            elif changed == "merge":
                api.refs["pull/246/merge"] = "0" * 40
            elif changed == "attempt":
                api.run["run_attempt"] = 2
            else:
                api.run["id"] += 1
        return raw

    api.raw = racing
    assert ROUTE.route(root, identity, REPO, api)["delegated"] is False


@pytest.mark.parametrize("absent", ["PR", "run"])
def test_one_initial_discovery_window_can_find_prompt_docs_pr(docs_candidate, absent):
    root, identity, api = docs_candidate
    clock = Clock()
    original = api.get

    def discovery(path):
        if clock.elapsed < 5:
            if absent == "PR" and path.startswith("pulls?"):
                return []
            if absent == "run" and path.startswith("actions/workflows/"):
                return {"total_count": 0, "workflow_runs": []}
        return original(path)

    api.get = discovery
    observed = ROUTE.route(root, identity, REPO, api, monotonic=clock.now, sleep=clock.sleep)
    assert observed["delegated"] is True
    assert clock.elapsed == 5


@pytest.mark.parametrize("issue", ["absent", "API-error", "incomplete-run"])
def test_discovery_is_only_for_absence_and_at_most_thirty_seconds(docs_candidate, issue):
    root, identity, api = docs_candidate
    clock = Clock()
    if issue == "absent":
        api.prs = []
    else:
        original = api.get

        def unavailable(path):
            if issue == "API-error":
                raise subprocess.CalledProcessError(1, "gh")
            if path.startswith("actions/workflows/"):
                return {"total_count": 1, "workflow_runs": []}
            return original(path)

        api.get = unavailable
    observed = ROUTE.route(root, identity, REPO, api, monotonic=clock.now, sleep=clock.sleep)
    assert observed["delegated"] is False
    assert clock.elapsed == (30 if issue == "absent" else 0)


def test_total_deadline_includes_docs_artifact_processing(docs_candidate):
    root, identity, api = docs_candidate
    clock = Clock()
    original = api.raw

    def late(path):
        raw = original(path)
        if path.endswith("/9/zip"):
            clock.elapsed = 421
        return raw

    api.raw = late
    observed = ROUTE.route(root, identity, REPO, api, monotonic=clock.now, sleep=clock.sleep)
    assert observed["delegated"] is False
    assert len(api.downloads) == 3


@pytest.mark.parametrize(
    "header,path",
    [
        (":100644 100644", "code.py"),
        (":100644 100755", "docs/PRODUCT_VISION.md"),
        (":120000 120000", "docs/PRODUCT_VISION.md"),
    ],
)
def test_docs_consumer_rejects_unallowlisted_or_unsafe_raw_diff(
    docs_candidate, monkeypatch, header, path
):
    root, identity, api = docs_candidate
    original = ROUTE.bounded_git
    raw = f"{header} {'a' * 40} {'b' * 40} M\0{path}\0".encode()

    def altered(root, deadline, monotonic, *args):
        return raw if args[0] == "diff" else original(root, deadline, monotonic, *args)

    monkeypatch.setattr(ROUTE, "bounded_git", altered)
    assert ROUTE.route(root, identity, REPO, api)["delegated"] is False


def test_initial_candidate_disappearing_is_not_more_discovery(docs_candidate):
    root, identity, api = docs_candidate
    clock = Clock()
    original = api.get

    def disappearance(path):
        if clock.elapsed > 0 and path.startswith("pulls?"):
            return []
        if path.startswith("actions/workflows/"):
            return {"total_count": 0, "workflow_runs": []}
        return original(path)

    api.get = disappearance
    observed = ROUTE.route(root, identity, REPO, api, monotonic=clock.now, sleep=clock.sleep)
    assert observed["delegated"] is False
    assert clock.elapsed == 5


def test_api_timeout_is_clamped_to_total_deadline(monkeypatch):
    api = ROUTE.GitHub(REPO)
    api.deadline = 10
    api.monotonic = lambda: 8.5
    timeouts = []

    def run(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        return subprocess.CompletedProcess(args, 0, stdout=b"{}")

    monkeypatch.setattr(ROUTE.subprocess, "run", run)
    assert api.raw("synthetic") == b"{}"
    assert timeouts == [1.5]
    api.monotonic = lambda: 10
    with pytest.raises(ROUTE.Unproven):
        api.raw("synthetic")
    assert timeouts == [1.5]


@pytest.mark.parametrize("discovered_at", [30, 31])
@pytest.mark.parametrize("absent", ["PR", "run"])
def test_discovery_success_at_or_after_expiry_keeps_full(docs_candidate, absent, discovered_at):
    root, identity, api = docs_candidate
    clock = Clock()
    original = api.get
    lookups = []

    def late_discovery(path):
        is_lookup = path.startswith("pulls?" if absent == "PR" else "actions/workflows/")
        if is_lookup:
            lookups.append(clock.elapsed)
            if clock.elapsed < 25:
                clock.elapsed = 25
                return [] if absent == "PR" else {"total_count": 0, "workflow_runs": []}
            clock.elapsed = discovered_at
        return original(path)

    api.get = late_discovery
    observed = ROUTE.route(root, identity, REPO, api, monotonic=clock.now, sleep=clock.sleep)
    assert observed["delegated"] is False
    assert lookups == [0]  # No lookup starts on the expired 30-second boundary.
    assert api.downloads == []


@pytest.mark.parametrize("lookup_finishes", [30, 31, 29.999])
def test_retry_lookup_must_finish_before_grace_and_restores_total_budget(
    docs_candidate, lookup_finishes
):
    root, identity, original_api = docs_candidate
    clock = Clock()

    class TimedAPI(FakeAPI, ROUTE.GitHub):
        pass

    api = TimedAPI.__new__(TimedAPI)
    api.__dict__.update(original_api.__dict__)
    original = api.get
    retry_deadlines = []
    selected = False

    def slow_lookup(path):
        nonlocal selected
        if path.startswith("actions/workflows/") and not selected:
            if clock.elapsed == 0:
                return {"total_count": 0, "workflow_runs": []}
            retry_deadlines.append(api.deadline)
            clock.elapsed = lookup_finishes
            selected = True
        return original(path)

    original_raw = api.raw
    proof_deadlines = []

    def proof_read(path):
        proof_deadlines.append(api.deadline)
        clock.elapsed = 40  # Selected-run proof may legitimately continue after grace.
        return original_raw(path)

    api.get = slow_lookup
    api.raw = proof_read
    observed = ROUTE.route(root, identity, REPO, api, monotonic=clock.now, sleep=clock.sleep)
    assert retry_deadlines == [30]
    assert api.deadline == 420
    assert observed["delegated"] is (lookup_finishes < 30)
    assert proof_deadlines == ([420, 420, 420] if lookup_finishes < 30 else [])
