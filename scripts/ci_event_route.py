"""Exact-tree task-push delegation; a delegated push is never a candidate gate."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import time
import zipfile
from pathlib import Path

from ci_docs_gate import classify, context, git, write_json


class Unproven(ValueError):
    pass


def require(condition: bool) -> None:
    if not condition:
        raise Unproven("unproven PR delegation")


def sha(value: object) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None)
    return value


class GitHub:
    def __init__(self, repository: str):
        require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is not None)
        self.prefix = f"repos/{repository}"

    def raw(self, path: str) -> bytes:
        # gh handles authenticated API redirects without logging token/response bodies.
        return subprocess.run(
            ["gh", "api", f"{self.prefix}/{path}"],
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout

    def get(self, path: str):
        return json.loads(self.raw(path))

    def decision(self, artifact_id: int) -> dict:
        archive = self.raw(f"actions/artifacts/{artifact_id}/zip")
        require(len(archive) <= 65536)
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            require(zipped.namelist() == ["decision.json"])
            info = zipped.getinfo("decision.json")
            require(info.file_size <= 16384)
            return json.loads(zipped.read(info))


def pr_checkout(root: Path, identity: dict) -> dict:
    """Record actual checkout, independently of the API's workflow-run head_sha."""
    require(identity["GITHUB_EVENT_NAME"] == "pull_request")
    require(re.fullmatch(r"refs/pull/[1-9][0-9]*/merge", identity["GITHUB_REF"]) is not None)
    base, head, merge = [sha(identity[key]) for key in ("PR_BASE_SHA", "PR_HEAD_SHA", "GITHUB_SHA")]
    require(git(root, "rev-parse", "HEAD").decode().strip() == merge)
    require(git(root, "show", "-s", "--format=%P", merge).decode().split() == [base, head])
    require(not git(root, "status", "--porcelain", "--untracked-files=normal"))
    trees = [
        git(root, "rev-parse", f"{commit}^{{tree}}").decode().strip()
        for commit in (base, head, merge)
    ]
    return {
        "identity": identity,
        "base_tree": trees[0],
        "head_tree": trees[1],
        "merge_tree": trees[2],
        "required_mode": classify(root, identity)["mode"],
    }


def snapshot(api, repository: str, branch: str, head: str) -> dict:
    prs = api.get(f"pulls?state=open&head={repository.split('/')[0]}:{branch}&per_page=2")
    require(isinstance(prs, list) and len(prs) == 1)
    number = prs[0]["number"]
    require(type(number) is int and number > 0)
    pr = api.get(f"pulls/{number}")
    require(pr["number"] == number and pr["state"] == "open" and not pr["merged"])
    require(pr["head"]["repo"]["full_name"] == repository)
    require(pr["base"]["repo"]["full_name"] == repository)
    require(pr["head"]["ref"] == branch and pr["head"]["sha"] == head)
    # Integration-target PRs remain on their ordinary independent gates.
    require(pr["base"]["ref"] == "main" and pr["mergeable"] is True)
    base, merge = sha(pr["base"]["sha"]), sha(pr["merge_commit_sha"])
    require(api.get(f"git/ref/heads/{branch}")["object"]["sha"] == head)
    require(api.get("git/ref/heads/main")["object"]["sha"] == base)
    require(api.get(f"git/ref/pull/{number}/merge")["object"]["sha"] == merge)
    commits = [api.get(f"git/commits/{value}") for value in (base, head, merge)]
    require([item["sha"] for item in commits] == [base, head, merge])
    require([item["sha"] for item in commits[2]["parents"]] == [base, head])
    trees = [sha(item["tree"]["sha"]) for item in commits]
    require(trees[1] == trees[2])
    return {
        "number": number,
        "base": base,
        "head": head,
        "merge": merge,
        "base_tree": trees[0],
        "head_tree": trees[1],
        "merge_tree": trees[2],
    }


def current_run(api, candidate: dict, branch: str) -> dict:
    # Select the newest PR run, never fall back to an older green run.
    result = api.get(f"actions/workflows/ci.yml/runs?event=pull_request&branch={branch}&per_page=2")
    require(result["total_count"] > 0 and bool(result["workflow_runs"]))
    run = result["workflow_runs"][0]
    require(run["event"] == "pull_request" and run["path"] == ".github/workflows/ci.yml")
    require(run["head_branch"] == branch and run["head_sha"] == candidate["head"])
    require(type(run["id"]) is int and run["id"] > 0)
    require(type(run["run_attempt"]) is int and run["run_attempt"] > 0)
    require(run["status"] in {"queued", "in_progress", "completed"})
    require(run["conclusion"] is None or run["conclusion"] == "success")
    return {key: run[key] for key in ("id", "run_attempt", "status", "conclusion")}


def verify_pr_run(api, candidate: dict, run: dict, repository: str, branch: str) -> dict:
    require(run["status"] == "completed" and run["conclusion"] == "success")
    run_id, attempt = run["id"], run["run_attempt"]
    jobs = api.get(f"actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100")
    require(jobs["total_count"] == 8 and len(jobs["jobs"]) == 8)
    expected = {
        "classify",
        "quality",
        "test (garmin)",
        "test (core-sleep)",
        "test (app-ingest)",
        "windows-smoke",
        "checks",
    }
    observed = jobs["jobs"]
    require({job["name"] for job in observed} == expected | {"docs"})
    require(
        all(
            job["run_id"] == run_id
            and job["run_attempt"] == attempt
            and job["status"] == "completed"
            for job in observed
        )
    )
    require(
        all(
            job["conclusion"] == ("skipped" if job["name"] == "docs" else "success")
            for job in observed
        )
    )
    artifacts = api.get(f"actions/runs/{run_id}/artifacts?per_page=100")
    require(artifacts["total_count"] == len(artifacts["artifacts"]) < 100)
    matches = [
        item
        for item in artifacts["artifacts"]
        if item["name"] == f"event-decision-{run_id}-{attempt}"
    ]
    require(len(matches) == 1 and not matches[0]["expired"])
    record = api.decision(matches[0]["id"])
    require(record["schema_version"] == 1 and record["delegated"] is False)
    proof = record["pr_checkout"]
    identity = proof["identity"]
    require(record["repository"] == repository and proof["required_mode"] == "full")
    require(
        identity
        == {
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_REF": f"refs/pull/{candidate['number']}/merge",
            "GITHUB_SHA": candidate["merge"],
            "GITHUB_RUN_ID": str(run_id),
            "GITHUB_RUN_ATTEMPT": str(attempt),
            "GITHUB_BASE_REF": "main",
            "PR_BASE_SHA": candidate["base"],
            "GITHUB_HEAD_REF": branch,
            "PR_HEAD_SHA": candidate["head"],
        }
    )
    require(all(proof[key] == candidate[key] for key in ("base_tree", "head_tree", "merge_tree")))
    return {"run_id": run_id, "attempt": attempt, "checkout": proof}


def delegate(
    root: Path,
    identity: dict,
    repository: str,
    api,
    *,
    wait_seconds=420,
    monotonic=time.monotonic,
    sleep=time.sleep,
) -> dict:
    head = sha(identity["GITHUB_SHA"])
    require(git(root, "rev-parse", "HEAD").decode().strip() == head)
    require(not git(root, "status", "--porcelain", "--untracked-files=normal"))
    branch = identity["GITHUB_REF"].removeprefix("refs/heads/")
    require(re.fullmatch(r"task/[A-Za-z0-9_./-]+", branch) is not None)
    candidate = snapshot(api, repository, branch, head)
    require(candidate["head_tree"] == git(root, "rev-parse", "HEAD^{tree}").decode().strip())
    run = current_run(api, candidate, branch)
    run_identity = (run["id"], run["run_attempt"])
    deadline = monotonic() + wait_seconds
    while run["status"] != "completed":
        require(monotonic() < deadline)
        sleep(min(15, max(0, deadline - monotonic())))
        require(snapshot(api, repository, branch, head) == candidate)
        run = current_run(api, candidate, branch)
        require((run["id"], run["run_attempt"]) == run_identity)
    proof = verify_pr_run(api, candidate, run, repository, branch)
    # Close head/base/PR/merge/run races across the evidence read.
    require(snapshot(api, repository, branch, head) == candidate)
    require(current_run(api, candidate, branch) == run)
    return {"pr": candidate, "pr_run": proof}


def route(root: Path, identity: dict, repository: str, api=None, **wait) -> dict:
    record = {
        "schema_version": 1,
        "repository": repository,
        "identity": identity,
        "delegated": False,
        "reason": "non-task-push",
    }
    try:
        if identity["GITHUB_EVENT_NAME"] == "pull_request":
            record["pr_checkout"] = pr_checkout(root, identity)
        elif identity["GITHUB_EVENT_NAME"] == "push" and re.fullmatch(
            r"refs/heads/task/[A-Za-z0-9_./-]+", identity["GITHUB_REF"]
        ):
            proof = delegate(root, identity, repository, api or GitHub(repository), **wait)
            record.update(delegated=True, reason="exact-tree-complete-PR", **proof)
    except (
        Unproven,
        KeyError,
        TypeError,
        ValueError,
        OSError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ):
        record["reason"] = "unproven-keep-full"
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    record = route(
        Path(__file__).resolve().parents[1], context(), os.environ.get("GITHUB_REPOSITORY", "")
    )
    write_json(args.output_dir / "decision.json", record)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"delegated={str(record['delegated']).lower()}\n")
    message = (
        "task push delegated; NOT a complete candidate gate"
        if record["delegated"]
        else "ordinary gates"
    )
    print(f"CI event route: {message}")
    if record["delegated"]:
        proof = record["pr_run"]
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
            summary.write(
                f"Task push delegated to PR #{record['pr']['number']}, "
                f"run {proof['run_id']} attempt {proof['attempt']}. "
                "This push is NOT a complete candidate gate; checks is skipped.\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
