"""Record actual PR checkout provenance; task pushes have no candidate gate."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

from ci_docs_gate import classify, context, git, write_json


class Unproven(ValueError):
    pass


def require(condition: bool) -> None:
    if not condition:
        raise Unproven("unproven PR checkout")


def sha(value: object) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None)
    return value


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


def route(root: Path, identity: dict, repository: str) -> dict:
    # Keep the artifact schema for existing exact-evidence consumers. No event
    # delegates to another run or inherits its success.
    record = {
        "schema_version": 1,
        "repository": repository,
        "identity": identity,
        "delegated": False,
        "reason": "ordinary-gates",
    }
    if identity.get("GITHUB_EVENT_NAME") == "pull_request":
        try:
            record["pr_checkout"] = pr_checkout(root, identity)
            record["reason"] = "actual-PR-checkout"
        except (Unproven, KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
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
    print(f"CI event provenance: {record['reason']}; no cross-event delegation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
