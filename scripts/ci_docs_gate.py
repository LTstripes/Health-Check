"""Conservative PR-only documentation routing; full CI verifiers stay authoritative."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Individually inspected prose, with no build/test/fixture/runtime consumers.
# README.md is build metadata. New files and every unlisted path require full CI.
DOC_PATHS = frozenset(
    {
        "docs/ARCHITECTURE.md",
        "docs/DEVELOPMENT_PROCESS.md",
        "docs/PRODUCT_VISION.md",
        "docs/PROJECT_WIKI.md",
        "docs/ROADMAP.md",
    }
)
POLICY_FILES = ("scripts/ci_docs_gate.py", ".github/workflows/ci.yml")
IDENTITY_ENV = (
    "GITHUB_EVENT_NAME",
    "GITHUB_REF",
    "GITHUB_SHA",
    "GITHUB_RUN_ID",
    "GITHUB_RUN_ATTEMPT",
    "GITHUB_BASE_REF",
    "PR_BASE_SHA",
    "GITHUB_HEAD_REF",
    "PR_HEAD_SHA",
)
DOC_CHECK = "utf8-prose-local-links-credential-patterns-v1"
SECRET = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\bgh[pousr]_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b|"
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}",
    re.IGNORECASE,
)


class DocsError(ValueError):
    """No verifiable docs-only outcome is available."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DocsError(message)


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), *args],
        check=True,
        capture_output=True,
    ).stdout


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical(payload) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as error:
        raise DocsError("missing or malformed docs evidence") from error
    require(isinstance(value, dict), "docs evidence must be an object")
    return value


def context() -> dict[str, str]:
    return {key: os.environ.get(key, "") for key in IDENTITY_ENV}


def changed_docs(raw: bytes) -> list[str]:
    """Consume the entire NUL-delimited raw diff, with no rename/path heuristics."""
    fields = raw.split(b"\0")
    require(fields.pop() == b"", "incomplete raw diff")
    require(bool(fields) and len(fields) % 2 == 0, "empty or malformed raw diff")
    paths = []
    for header, path_bytes in zip(fields[::2], fields[1::2], strict=True):
        require(
            re.fullmatch(rb":100644 100644 [0-9a-f]{40} [0-9a-f]{40} M", header) is not None,
            "new/deleted/renamed/unsafe-mode change",
        )
        path = path_bytes.decode("utf-8", errors="strict")
        require(path in DOC_PATHS, "path is not allowlisted prose")
        require(path not in paths, "duplicate diff path")
        paths.append(path)
    return paths


def classify(root: Path, identity: dict[str, str]) -> dict:
    decision = {"schema_version": 1, "mode": "full", "identity": identity, "reason": "event"}
    if identity["GITHUB_EVENT_NAME"] != "pull_request":
        return decision
    try:
        require(
            re.fullmatch(r"refs/pull/[1-9][0-9]*/merge", identity["GITHUB_REF"]) is not None,
            "not a PR merge ref",
        )
        for field in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
            require(
                re.fullmatch(r"[1-9][0-9]*", identity[field]) is not None, "missing run/attempt"
            )
        require(
            bool(identity["GITHUB_BASE_REF"] and identity["GITHUB_HEAD_REF"]), "missing PR refs"
        )
        base, head, checkout = (
            identity[key] for key in ("PR_BASE_SHA", "PR_HEAD_SHA", "GITHUB_SHA")
        )
        trees = []
        for sha in (base, head, checkout):
            require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None, "missing commit identity")
            require(
                git(root, "rev-parse", "--verify", f"{sha}^{{commit}}").decode().strip() == sha,
                "commit identity mismatch",
            )
            trees.append(git(root, "rev-parse", f"{sha}^{{tree}}").decode().strip())
        require(git(root, "rev-parse", "HEAD").decode().strip() == checkout, "stale checkout")
        parents = git(root, "show", "-s", "--format=%P", checkout).decode().split()
        require(parents == [base, head], "merge parents do not match event base/head")
        # Deliberately conservative: base movement/conflict resolution may require full CI.
        require(trees[1] == trees[2], "merge tree differs from PR head tree")
        require(
            not git(root, "status", "--porcelain", "--untracked-files=normal"), "checkout is dirty"
        )
        diffs = [
            git(
                root,
                "diff",
                "--raw",
                "--full-index",
                "--abbrev=40",
                "-z",
                "--no-renames",
                "--no-ext-diff",
                "--no-textconv",
                base,
                target,
                "--",
            )
            for target in (head, checkout)
        ]
        paths = changed_docs(diffs[0])
        require(changed_docs(diffs[1]) == paths and diffs[0] == diffs[1], "head/merge diffs differ")
        policy = {}
        for path in POLICY_FILES:
            contents = [git(root, "show", f"{sha}:{path}") for sha in (base, head, checkout)]
            require(contents[0] == contents[1] == contents[2], "classifier/workflow changed")
            require((root / path).read_bytes() == contents[2], "local policy differs from tree")
            policy[path] = digest(contents[2])
        decision.update(
            mode="docs",
            reason="allowlisted-prose",
            trees=trees,
            paths=paths,
            diff_sha256=[digest(raw) for raw in diffs],
            policy_sha256=policy,
        )
    except (DocsError, OSError, UnicodeError, subprocess.CalledProcessError):
        # No filenames, document contents or git stderr enter diagnostics/evidence.
        decision["reason"] = "unproven-or-non-docs-comparison"
    return decision


def check_documents(root: Path, decision: dict) -> dict:
    require(decision["mode"] == "docs", "docs checks require a docs decision")
    checkout = decision["identity"]["GITHUB_SHA"]
    checks = []
    for path in decision["paths"]:
        content = git(root, "show", f"{checkout}:{path}")
        text = content.decode("utf-8", errors="strict")
        require(bool(text.strip()) and "\0" not in text, "invalid UTF-8 prose")
        require(SECRET.search(text) is None, "credential pattern in documentation")
        # Markdown links are inspected as data; never execute code blocks or fetch URLs.
        for target in re.findall(r"\[[^\]\n]*\]\(([^\s)]+)\)", text):
            if target.startswith(("https://", "http://", "mailto:", "#")):
                continue
            target = target.split("#", 1)[0]
            require(
                not target.startswith(("/", "\\")) and ":" not in target,
                "unsafe local documentation link",
            )
            normalized = os.path.normpath(str(Path(path).parent / target)).replace("\\", "/")
            require(not normalized.startswith("../"), "local link escapes repository")
            git(root, "cat-file", "-e", f"{checkout}:{normalized}")
        checks.append({"path": path, "sha256": digest(content)})
    return {
        "schema_version": 1,
        "status": "passed",
        "check": DOC_CHECK,
        "decision_sha256": digest(canonical(decision).encode()),
        "documents": checks,
    }


def verify_route(
    root: Path,
    artifacts: Path,
    identity: dict[str, str],
    *,
    mode: str,
    classify_result: str,
    docs_result: str,
    full_results: list[str],
) -> str:
    run_id, attempt = identity["GITHUB_RUN_ID"], identity["GITHUB_RUN_ATTEMPT"]
    for value in (run_id, attempt):
        require(re.fullmatch(r"[1-9][0-9]*", value) is not None, "invalid run/attempt")
    decision_name = f"docs-decision-{run_id}-{attempt}"
    outcome_name = f"docs-outcome-{run_id}-{attempt}"
    require(artifacts.is_dir(), "missing evidence root; Re-run all jobs")
    names = {path.name for path in artifacts.iterdir()}
    if classify_result == "success":
        expected = classify(root, identity)
        saved = read_json(artifacts / decision_name / "decision.json")
        require(canonical(saved) == canonical(expected), "stale/foreign/invalid decision")
        require(mode == expected["mode"], "routing output contradicts decision")
    else:
        require(mode != "docs", "failed classifier cannot authorize docs skip")
        mode = "full"
    if mode == "docs":
        require(names == {decision_name, outcome_name}, "missing/mixed/foreign docs evidence")
        require(docs_result == "success", "docs job did not succeed")
        require(full_results == ["skipped"] * 3, "unexpected full job outcome in docs mode")
        outcome = read_json(artifacts / outcome_name / "outcome.json")
        require(
            canonical(outcome) == canonical(check_documents(root, expected)),
            "missing/failed/stale docs outcome",
        )
        return "docs"
    require(mode == "full", "unknown routing mode")
    require(docs_result == "skipped", "unexpected docs job outcome in full mode")
    # The unchanged full verifier then requires exactly its five ci-* artifacts.
    require(
        not any(name.startswith("docs-") and name != decision_name for name in names),
        "mixed docs/full evidence",
    )
    return "full"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("classify", "check", "route"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--artifacts-root", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    identity = context()
    try:
        if args.command == "classify":
            decision = classify(root, identity)
            require(args.output_dir is not None, "missing output directory")
            write_json(args.output_dir / "decision.json", decision)
            with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
                output.write(f"mode={decision['mode']}\n")
            print(f"CI route: {decision['mode']}")
        elif args.command == "check":
            decision = classify(root, identity)
            require(args.output_dir is not None, "missing output directory")
            write_json(args.output_dir / "outcome.json", check_documents(root, decision))
            print("docs checks PASS: prose, local links and credential patterns")
        else:
            require(args.artifacts_root is not None, "missing artifacts root")
            mode = verify_route(
                root,
                args.artifacts_root,
                identity,
                mode=os.environ.get("CI_MODE", ""),
                classify_result=os.environ.get("CLASSIFY_RESULT", ""),
                docs_result=os.environ.get("DOCS_RESULT", ""),
                full_results=[
                    os.environ.get(key, "")
                    for key in ("QUALITY_RESULT", "TEST_RESULT", "WINDOWS_RESULT")
                ],
            )
            print(mode)
    except (DocsError, OSError, ValueError, subprocess.CalledProcessError) as error:
        # Never print document contents or subprocess output.
        print(f"CI docs contract failure: {type(error).__name__}; Re-run all jobs", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
