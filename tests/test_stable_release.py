"""Synthetic release trees and real disposable UI/MCP HTTP subprocesses only."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from scripts.stable_release import consumers
from scripts.stable_release import release as tool

NOW = datetime.now(UTC)
TOKEN = "synthetic-gateway-credential-never-persist-123456"


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return path


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def release_case(tmp_path, monkeypatch):
    # The task always passes an external --basetemp. Never silently create a profile in Git.
    assert not tmp_path.resolve().is_relative_to(Path(__file__).resolve().parents[1])
    monkeypatch.setenv("HEALTHCHECK_MCP_GATEWAY_TOKEN", TOKEN)
    repo = tmp_path / "repository"
    repo.mkdir()
    tool.git(repo, "init", "--initial-branch=main")
    tool.git(repo, "config", "user.name", "Synthetic release test")
    tool.git(repo, "config", "user.email", "synthetic@example.invalid")
    tool.git(repo, "config", "commit.gpgsign", "false")
    (repo / ".gitignore").write_text(".venv/\n")
    (repo / "page.py").write_text("old = True\n")
    tool.git(repo, "add", ".")
    tool.git(repo, "commit", "-m", "synthetic old")
    old_sha = tool.git(repo, "rev-parse", "HEAD")
    (repo / "page.py").write_text("new = True\n")
    tool.git(repo, "add", ".")
    tool.git(repo, "commit", "-m", "synthetic target")
    new_sha = tool.git(repo, "rev-parse", "HEAD")
    tool.git(repo, "update-ref", "refs/remotes/origin/main", new_sha)
    releases = tmp_path / "releases"
    releases.mkdir()
    old_code, new_code = [releases / ("stable-code-" + sha[:8]) for sha in (old_sha, new_sha)]
    for code, sha in ((old_code, old_sha), (new_code, new_sha)):
        tool.command(["git", "clone", "--quiet", "--no-hardlinks", str(repo), str(code)])
        tool.git(code, "checkout", "--detach", sha)
        executable = code / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        executable.parent.mkdir(parents=True)
        executable.touch()
    profile = tmp_path / "synthetic-profile"
    profile.mkdir()
    with sqlite3.connect(profile / "healthcheck.db") as db:
        db.execute("CREATE TABLE alembic_version (version_num TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('r1')")
    monkeypatch.setenv("HEALTHCHECK_DATA_DIR", str(profile))
    ops = tmp_path / "ops"
    ops.mkdir()
    ui_port, mcp_port = free_port(), free_port()
    while mcp_port == ui_port:
        mcp_port = free_port()
    ui_paths = []
    mcp_paths = []
    heads = {str(old_code): "r1", str(new_code): "r1"}
    for code, sha, name in ((old_code, old_sha, "old"), (new_code, new_sha, "new")):
        ui_paths.append(write_json(ops / (name + "-ui.json"), {
            "code": str(code), "sha": sha, "profile": str(profile), "port": ui_port,
            "schema": "r1", "head_file": str(code / ".git/HEAD"), "runner_version": 1,
            "run_id": name, "receipt": name + "-ready.json", "stop_file": name + ".stop"}))
        mcp_paths.append(write_json(ops / (name + "-mcp.json"), {
            "profile": str(profile), "schema_heads": ["r1"], "code_id": "synthetic",
            "synthetic_sha": sha}))
    pointer = write_json(ops / "active-code.private.json", {
        "code": str(old_code), "sha": old_sha, "schema": "r1", "profile": str(profile),
        "ui_binding": str(ui_paths[0]), "ui_start_script": str(ops / "old-start.ps1"),
        "previous_version": "synthetic-previous", "rollback_directory": "synthetic-previous",
        "previous_active_binding": "synthetic-previous"})
    recovery_file = tmp_path / "verified-synthetic.zip"
    recovery_file.write_bytes(b"synthetic previously verified backup")
    recovery = write_json(ops / "recovery.json", {
        "status": "PASS", "verified": True, "profile": str(profile),
        "path": str(recovery_file), "utc": (NOW - timedelta(days=7)).isoformat(),
        "sha256": tool.digest(recovery_file.read_bytes()), "schema": "r1"})
    ci = write_json(ops / "ci.json", {
        "status": "PASS", "sha": new_sha, "run_id": "123/attempts/1",
        "jobs": dict.fromkeys(("quality", "test", "windows-smoke", "checks"), "success")})
    consumers = []
    for role in sorted(tool.CONSUMERS):
        if role == "active-pointer":
            path = pointer
        elif role == "weekly-recipe":
            path = ops / "invocation-recipe.txt"
            path.write_text(f"Python: {old_code}\nBinding: {mcp_paths[0]}\n", encoding="utf-8")
        elif role.endswith("handoff"):
            path = write_json(ops / (role + ".json"), {"code": str(old_code), "sha": old_sha})
        else:
            path = ops / (role + ".ps1")
            path.write_bytes(f"# {old_code}\r\n# {old_sha}\r\n# r1\r\n".encode())
        entry = {"role": role, "path": str(path)}
        if role == "weekly-recipe":
            entry["replacements"] = [[str(mcp_paths[0]), str(mcp_paths[1])]]
        consumers.append(entry)
    config = {"repository": str(repo), "releases_root": str(releases), "profile": str(profile),
              "active_pointer": str(pointer), "ci_receipt": str(ci),
              "recovery_receipt": str(recovery), "rehearsal_receipt": str(ops / "rehearsal.json"),
              "ui_binding": str(ui_paths[1]), "mcp_binding": str(mcp_paths[1]),
              "old_mcp_binding": str(mcp_paths[0]), "consumers": consumers,
              "ui_port": ui_port, "mcp_port": mcp_port, "timeout_seconds": 2, "known_page": "/"}
    config["autostart_mutex"] = "Local\\HealthCheckReleaseSynthetic-" + tmp_path.name + str(ui_port)
    config_path = write_json(ops / "config.json", config)

    def fake_probe(code, selected_profile, action, *args):
        assert str(selected_profile) == str(profile)
        if action == "head":
            return heads[str(code)]
        if action == "current":
            with sqlite3.connect((profile / "healthcheck.db").as_uri() + "?mode=ro",
                                 uri=True) as db:
                return db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert action == "binding"
        binding = tool.read_json(args[0])
        tool.require(binding["schema_heads"] == [heads[str(code)]], "test_mcp_binding_mismatch")
        return {"status": "PASS"}

    monkeypatch.setattr(tool, "probe", fake_probe)
    return {"root": tmp_path, "config": config, "config_path": config_path,
            "old_sha": old_sha, "new_sha": new_sha, "old_code": old_code, "new_code": new_code,
            "ui_paths": ui_paths, "mcp_paths": mcp_paths, "heads": heads,
            "manifest_path": ops / "manifest.json", "pointer": pointer}


def prepare(case, strict=False):
    write_json(case["config_path"], case["config"])
    return tool.prepare(case["config_path"], case["new_sha"], "123/attempts/1",
                        case["manifest_path"], strict)


AUTOSTART_STUB = r'''
[CmdletBinding()]
param([string]$OpsRoot, [switch]$DryRun, [int[]]$DryRunOccupiedPorts=@())
$ErrorActionPreference='Stop'
if (-not $DryRun -or $DryRunOccupiedPorts.Count -ne 2 -or
    $DryRunOccupiedPorts -notcontains 8120 -or $DryRunOccupiedPorts -notcontains 8787) {
    throw 'FAIL: unsafe dry-run arguments'
}
$a=Get-Content -LiteralPath (Join-Path $OpsRoot 'maintenance/active-code.private.json') -Raw |
    ConvertFrom-Json
$b=Get-Content -LiteralPath $a.ui_binding -Raw | ConvertFrom-Json
$allowed=@((Split-Path -Parent $a.ui_binding),(Join-Path $a.code 'scripts/stable_release'))
if ($allowed -notcontains (Split-Path -Parent $a.ui_start_script) -or
    -not (Test-Path -LiteralPath $a.ui_start_script) -or $b.code -ne $a.code -or
    $b.sha -ne $a.sha) {
    Write-Output 'FAIL: release StartStable missing/misbound'; exit 8
}
$recipePath=Join-Path $OpsRoot 'assistant-weekly-read-488/invocation-recipe.txt'
$recipe=Get-Content -LiteralPath $recipePath -Raw
$match=[regex]::Match($recipe,'(?m)^Binding:\s*(.+?)\s*$')
if (-not $match.Success -or $match.Groups[1].Value.Trim() -ne $a.mcp_binding) {
    throw 'FAIL: recipe binding mismatch'
}
Write-Output 'PASS: pointer, UI start script and recipe checked; no services started'
'''


@pytest.fixture
def autostart_case(release_case, monkeypatch):
    case = release_case
    ops = case["pointer"].parent
    pointer = ops / "maintenance" / "active-code.private.json"
    pointer.parent.mkdir()
    case["pointer"].rename(pointer)
    case["pointer"] = pointer
    case["config"]["active_pointer"] = str(pointer)
    for entry in case["config"]["consumers"]:
        if entry["role"] == "active-pointer":
            entry["path"] = str(pointer)
        if entry["role"] == "weekly-recipe":
            recipe = ops / "assistant-weekly-read-488" / "invocation-recipe.txt"
            recipe.parent.mkdir()
            Path(entry["path"]).rename(recipe)
            entry["path"] = str(recipe)
    # Installed tooling beside the binding is one valid wrapper layout.
    for name in ("release.py", "probe.py", "ui_server.py", "StartStable.ps1", "consumers.py"):
        shutil.copyfile(tool.HERE / name, ops / name)
    monkeypatch.setattr(tool, "HERE", ops)
    script = case["root"] / "synthetic autostart's.ps1"
    script.write_text(AUTOSTART_STUB, encoding="utf-8")
    case["config"].update(autostart_dry_run_script=str(script),
                          powershell_executable="synthetic-powershell")
    case["ops"] = ops
    return case


def mock_autostart(case, monkeypatch, response=None):
    """Exercise staging/receipts on hosts unable to execute an unsigned .ps1."""
    original = subprocess.run
    calls = []

    def run(args, **kwargs):
        if args[0] != "synthetic-powershell":
            return original(args, **kwargs)
        assert args[1:4] == ["-NoProfile", "-NonInteractive", "-Command"]
        assert "ExecutionPolicy" not in args[-1]
        script = case["config"]["autostart_dry_run_script"].replace("'", "''")
        assert f"& '{script}' -OpsRoot " in args[-1]
        assert args[-1].endswith("-DryRun -DryRunOccupiedPorts 8120,8787")
        match = re.search(r"-OpsRoot '((?:[^']|'')*)' -DryRun", args[-1])
        ops = Path(match[1].replace("''", "'"))
        calls.append(ops)
        pointer = tool.read_json(ops / "maintenance" / "active-code.private.json")
        assert pointer["sha"] == case["new_sha"]
        binding = tool.read_json(pointer["ui_binding"])
        assert binding["code"] == pointer["code"] and binding["sha"] == pointer["sha"]
        recipe = (ops / "assistant-weekly-read-488" / "invocation-recipe.txt").read_text()
        assert f"Binding: {case['mcp_paths'][1]}" in recipe
        if response is not None:
            return response(args, ops)
        start = Path(pointer["ui_start_script"])
        allowed = (Path(pointer["ui_binding"]).parent,
                   Path(pointer["code"]) / "scripts/stable_release")
        valid = start.parent in allowed and start.is_file()
        return subprocess.CompletedProcess(args, 0 if valid else 8,
                                           b"PASS: checked" if valid else b"FAIL: misbound", b"")

    monkeypatch.setattr(subprocess, "run", run)
    return calls


@pytest.mark.parametrize("misbound", [False, True])
def test_prepare_checks_proposed_autostart_without_live_writes(autostart_case, monkeypatch,
                                                             misbound):
    case = autostart_case
    if misbound:
        elsewhere = case["root"] / "unrelated-tooling"
        shutil.copytree(tool.HERE, elsewhere)
        monkeypatch.setattr(tool, "HERE", elsewhere)
    calls = mock_autostart(case, monkeypatch)
    write_json(case["config_path"], case["config"])
    before = {p: p.read_bytes() for p in case["ops"].rglob("*") if p.is_file()}
    if misbound:
        with pytest.raises(tool.Refused, match="^autostart_dry_run_failed$"):
            prepare(case)
        assert not case["manifest_path"].exists()
    else:
        assert prepare(case)["autostart_dry_run"]["status"] == "PASS"
    result = tool.read_json(case["manifest_path"].parent / "preflight.json")
    assert result["status"] == ("FAIL" if misbound else "PASS")
    output = result["autostart_dry_run"]["stdout"]
    assert ("FAIL: misbound" if misbound else "PASS: checked") in output
    assert len(calls) == 1 and calls[0] != case["ops"] and not calls[0].exists()
    assert all(p.read_bytes() == data for p, data in before.items())
    added = {p for p in case["ops"].rglob("*") if p.is_file()} - before.keys()
    assert added == ({case["manifest_path"].parent / "preflight.json"} |
                     (set() if misbound else {case["manifest_path"]}))


@pytest.mark.parametrize(("returncode", "stdout", "stderr"), [
    (0, b"FAIL: invalid pointer", b""), (0, b"", b"FAIL: invalid binding"),
    (9, b"script refused", b"diagnostic"),
    (0, b"SKIP: autostart already running", b""),
])
def test_autostart_failure_output_is_receipted(autostart_case, monkeypatch,
                                              returncode, stdout, stderr):
    calls = mock_autostart(autostart_case, monkeypatch, lambda args, ops:
                           subprocess.CompletedProcess(args, returncode, stdout, stderr))
    with pytest.raises(tool.Refused, match="^autostart_dry_run_failed$"):
        prepare(autostart_case)
    result = tool.read_json(autostart_case["manifest_path"].parent / "preflight.json")
    assert result["autostart_dry_run"] == {
        "status": "FAIL", "reason": "autostart_dry_run_failed", "returncode": returncode,
        "stdout": stdout.decode(), "stderr": stderr.decode()}
    assert not calls[0].exists()


@pytest.mark.parametrize("failure", ["timeout", "unavailable"])
def test_autostart_launch_failures_clean_up_and_preserve_output(autostart_case, monkeypatch,
                                                              failure):
    def response(args, ops):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, 120, output=b"partial output", stderr=b"waiting")
        raise FileNotFoundError("synthetic engine unavailable")

    calls = mock_autostart(autostart_case, monkeypatch, response)
    with pytest.raises(tool.Refused, match="^autostart_dry_run_failed$"):
        prepare(autostart_case)
    result = tool.read_json(autostart_case["manifest_path"].parent / "preflight.json")
    check = result["autostart_dry_run"]
    expected = "timeout" if failure == "timeout" else "launch_or_staging_unavailable"
    assert check["detail"] == expected
    assert check["stdout"] == ("partial output" if failure == "timeout" else "")
    assert not calls[0].exists()


def test_autostart_captures_output_without_gateway_token(autostart_case, monkeypatch):
    mock_autostart(autostart_case, monkeypatch, lambda args, ops:
                   subprocess.CompletedProcess(args, 0, TOKEN.encode(), TOKEN.encode()))
    manifest = prepare(autostart_case)
    assert manifest["autostart_dry_run"]["stdout"] == "[REDACTED]"
    assert manifest["autostart_dry_run"]["stderr"] == "[REDACTED]"
    for name in ("manifest.json", "preflight.json"):
        assert TOKEN.encode() not in (autostart_case["manifest_path"].parent / name).read_bytes()


def test_autostart_stages_pointer_reading_recipe(autostart_case, monkeypatch):
    case = autostart_case
    entry = next(e for e in case["config"]["consumers"] if e["role"] == "weekly-recipe")
    entry.update(mode="pointer-reading")
    del entry["replacements"]
    Path(entry["path"]).write_text(f"Binding: {case['mcp_paths'][1]}\n")
    calls = mock_autostart(case, monkeypatch)
    manifest = prepare(case)
    assert all(e["role"] != "weekly-recipe" for e in manifest["consumers"])
    assert manifest["autostart_dry_run"]["status"] == "PASS"
    assert not calls[0].exists()


def test_autostart_key_absent_is_recorded_as_skipped(release_case, runtime):
    manifest = prepare(release_case)
    expected = {"status": "SKIP", "reason": "autostart_dry_run_not_configured"}
    assert manifest["autostart_dry_run"] == expected
    assert tool.read_json(release_case["manifest_path"].parent / "preflight.json")[
        "autostart_dry_run"] == expected
    assert tool.activate(release_case["manifest_path"], runtime)["autostart_dry_run"] == expected


@pytest.mark.parametrize("fail_live", [False, True])
def test_activation_checks_live_autostart_after_unlock_as_warning(autostart_case, runtime,
                                                                monkeypatch, fail_live):
    case = autostart_case
    held = []
    original_lock = tool.autostart_lock

    @tool.contextlib.contextmanager
    def lock(*args):
        with original_lock(*args):
            held.append(True)
            try:
                yield
            finally:
                held.pop()

    def response(args, ops):
        assert not held
        failed = fail_live and ops == case["ops"]
        output = b"FAIL: live binding" if failed else b"PASS"
        return subprocess.CompletedProcess(args, 0, output, b"")

    monkeypatch.setattr(tool, "autostart_lock", lock)
    calls = mock_autostart(case, monkeypatch, response)
    prepare(case)
    receipt = tool.activate(case["manifest_path"], runtime)
    assert receipt["status"] == "PASS" and "rollback" not in receipt
    assert receipt["autostart_dry_run"]["status"] == ("WARN" if fail_live else "PASS")
    assert receipt == tool.read_json(case["manifest_path"].parent / "activation.json")
    assert len(calls) == 2 and calls[-1] == case["ops"] and not calls[0].exists()
    assert tool.read_json(case["pointer"])["sha"] == case["new_sha"]
    runtime.smoke(tool.read_json(case["manifest_path"])["new"])


def test_activation_rejects_changed_autostart_script(autostart_case, runtime, monkeypatch):
    mock_autostart(autostart_case, monkeypatch)
    prepare(autostart_case)
    Path(autostart_case["config"]["autostart_dry_run_script"]).write_text("# changed wrapper\n")
    with pytest.raises(tool.Refused, match="manifest_reality_mismatch"):
        tool.activate(autostart_case["manifest_path"], runtime)
    assert tool.read_json(autostart_case["pointer"])["sha"] == autostart_case["old_sha"]


@pytest.mark.parametrize("engine", ["powershell.exe", "pwsh"])
@pytest.mark.parametrize("misbound", [False, True])
def test_real_powershell_autostart_stub(autostart_case, monkeypatch, engine, misbound):
    executable = shutil.which(engine)
    if executable is None:
        pytest.skip(engine + " unavailable")
    policy = tool.command([executable, "-NoProfile", "-NonInteractive", "-Command",
                           "Get-ExecutionPolicy"])
    if policy in ("Restricted", "AllSigned"):
        pytest.skip(engine + " execution policy " + policy + " disallows unsigned synthetic .ps1")
    case = autostart_case
    case["config"]["powershell_executable"] = executable
    if misbound:
        elsewhere = case["root"] / "unrelated-tooling"
        shutil.copytree(tool.HERE, elsewhere)
        monkeypatch.setattr(tool, "HERE", elsewhere)
        with pytest.raises(tool.Refused, match="^autostart_dry_run_failed$"):
            prepare(case)
    else:
        assert prepare(case)["autostart_dry_run"]["status"] == "PASS"


def test_restricted_powershell_refusal_is_receipted(autostart_case):
    executable = shutil.which("powershell.exe")
    if executable is None:
        pytest.skip("powershell.exe unavailable")
    policy = tool.command([executable, "-NoProfile", "-NonInteractive", "-Command",
                           "Get-ExecutionPolicy"])
    if policy != "Restricted":
        pytest.skip("Restricted execution policy required for refusal check")
    case = autostart_case
    case["config"]["powershell_executable"] = executable
    with pytest.raises(tool.Refused, match="^autostart_dry_run_failed$"):
        prepare(case)
    result = tool.read_json(case["manifest_path"].parent / "preflight.json")["autostart_dry_run"]
    assert result["status"] == "FAIL" and result["returncode"] != 0 and result["stderr"]
    assert not case["manifest_path"].exists()


@pytest.mark.parametrize(("paths", "current", "head", "strict", "expected"), [
    (["src/healthcheck/db/migrations/versions/0023.py"], "r1", "r1", False, "strict"),
    (["src/healthcheck/db/models.py"], "r1", "r1", False, "strict"),
    (["src/healthcheck/web/ui_app.py"], "r1", "r2", False, "strict"),
    (["src/healthcheck/web/ui_app.py"], "r1", "r1", False, "code-only"),
    ([], "r1", "r1", True, "strict"),
])
def test_route_classification(paths, current, head, strict, expected):
    assert tool.classify(paths, current, head, strict)[0] == expected


@pytest.mark.parametrize("days", [7, 9])
def test_recovery_age(release_case, days):
    case = release_case
    receipt = tool.read_json(case["config"]["recovery_receipt"])
    receipt["utc"] = (NOW - timedelta(days=days)).isoformat()
    write_json(Path(case["config"]["recovery_receipt"]), receipt)
    if days == 9:
        with pytest.raises(tool.Refused, match="recovery_point_expired"):
            prepare(case)
        assert not case["manifest_path"].exists()
    else:
        before = case["pointer"].read_bytes()
        result = prepare(case)
        assert result["route"] == "code-only"
        assert case["pointer"].read_bytes() == before
        assert not (case["manifest_path"].parent / "activation.json").exists()


@pytest.mark.parametrize("field", ["new_sha", "profile", "route", "target_head", "old_sha"])
def test_preflight_rejects_manifest_drift(release_case, field):
    manifest = prepare(release_case)
    manifest[field] = "another-value"
    with pytest.raises(tool.Refused):
        tool.preflight(manifest, release_case["config"])


def test_exact_ci_and_main_ancestry(release_case):
    case = release_case
    ci = tool.read_json(case["config"]["ci_receipt"])
    ci["jobs"]["windows-smoke"] = "failure"
    write_json(Path(case["config"]["ci_receipt"]), ci)
    with pytest.raises(tool.Refused, match="exact_ci_jobs"):
        prepare(case)
    ci["jobs"]["windows-smoke"] = "success"
    ci["sha"] = case["old_sha"]
    write_json(Path(case["config"]["ci_receipt"]), ci)
    with pytest.raises(tool.Refused, match="exact_ci_receipt"):
        prepare(case)
    ci["sha"] = case["new_sha"]
    write_json(Path(case["config"]["ci_receipt"]), ci)
    tool.git(case["config"]["repository"], "update-ref", "refs/remotes/origin/main",
             case["old_sha"])
    with pytest.raises(tool.Refused, match="command_failed"):
        prepare(case)


def make_strict(case, head="r2"):
    case["heads"][str(case["new_code"])] = head
    for path in (case["ui_paths"][1], case["mcp_paths"][1]):
        binding = tool.read_json(path)
        binding["schema" if path == case["ui_paths"][1] else "schema_heads"] = (
            head if path == case["ui_paths"][1] else [head])
        write_json(path, binding)
    rp = tool.read_json(case["config"]["recovery_receipt"])
    rp.update(utc=NOW.isoformat(), candidate_sha=case["new_sha"])
    write_json(Path(case["config"]["recovery_receipt"]), rp)
    write_json(Path(case["config"]["rehearsal_receipt"]), {
        "status": "PASS", "candidate_sha": case["new_sha"], "profile": case["config"]["profile"],
        "from_schema": "r1", "to_schema": head, "utc": NOW.isoformat(),
        "recovery_sha256": rp["sha256"]})


def test_strict_requires_fresh_recovery_and_linked_rehearsal(release_case):
    case = release_case
    with pytest.raises(tool.Refused, match="expired"):
        prepare(case, strict=True)
    make_strict(case)
    rehearsal = Path(case["config"]["rehearsal_receipt"])
    value = tool.read_json(rehearsal)
    value["candidate_sha"] = case["old_sha"]
    write_json(rehearsal, value)
    with pytest.raises(tool.Refused, match="rehearsal_mismatch"):
        prepare(case)


def test_atomic_replace_keeps_original_bytes(tmp_path):
    pointer = tmp_path / "active.json"
    before = b'{ "sha": "old", "extra": 1 }\r\n'
    pointer.write_bytes(before)
    previous = tmp_path / "previous.json"
    tool.atomic_pointer(pointer, {"sha": "new"}, previous)
    assert previous.read_bytes() == before
    assert tool.read_json(pointer) == {"sha": "new"}
    assert not list(tmp_path.glob("*.tmp"))
    with pytest.raises(tool.Refused, match="previous_pointer_already_exists"):
        tool.atomic_pointer(pointer, {"sha": "other"}, previous)
    assert tool.read_json(pointer) == {"sha": "new"}


def test_consumer_drift_never_overwrites_unknown_bytes(tmp_path):
    path = tmp_path / "consumer.txt"
    path.write_bytes(b"changed independently")
    writes = []
    with pytest.raises(tool.Refused, match="consumer_drift"):
        tool.write_preserved({"path": str(path)}, b"new", tool.digest(b"expected old"),
                             lambda: writes.append(True))
    assert path.read_bytes() == b"changed independently" and writes == []


FAKE_SERVER = r'''
import json,os,sys,threading,time
from http.server import HTTPServer,BaseHTTPRequestHandler
from pathlib import Path
kind,path,port=sys.argv[1:]
b=json.loads(Path(path).read_text(encoding='utf-8-sig'))
if b.get('fail_start'): sys.exit(2)
identity=dict(status='ok',run_id=b.get('run_id'),sha=b.get('sha'),pid=os.getpid(),
              profile=b['profile'],code=b.get('code'))
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        options=json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if self.path!='/healthz':
            time.sleep(options.get('page_delay',0))
            if options.get('page_redirect') and self.path!='/redirect-target':
                self.send_response(302);self.send_header('Location','/redirect-target')
                self.end_headers();return
            if options.get('page_unavailable'):
                self.send_response(503);self.end_headers();return
        elif options.get('health_unavailable'):
            self.send_response(503);self.end_headers();return
        self.send_response(200);self.end_headers()
        try:
            payload=identity if self.path=='/healthz' else {'page':'ok'}
            self.wfile.write(json.dumps(payload).encode())
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError): pass
    def do_POST(self):
        if json.loads(Path(path).read_text(encoding='utf-8-sig')).get('mcp_unavailable'):
            self.send_response(503);self.end_headers();return
        expected='Bearer '+os.environ['HEALTHCHECK_MCP_GATEWAY_TOKEN']
        if self.headers.get('Authorization') != expected:
            self.send_response(401);self.end_headers();return
        self.rfile.read(int(self.headers['Content-Length']))
        self.send_response(200);self.end_headers()
        self.wfile.write(json.dumps({'jsonrpc':'2.0','id':1,'result':{'serverInfo':{
            'name':'health-check-evidence'}}}).encode())
server=HTTPServer(('127.0.0.1',int(port)),Handler)
threading.Timer(120, lambda: os._exit(0)).start()
if kind=='ui': (Path(path).parent/b['receipt']).write_text(json.dumps(identity))
server.serve_forever()
'''


class SyntheticProcesses:
    def __init__(self, config):
        self.config = config
        self.launched = []

    def inventory(self):
        processes, listeners = [], []
        for child, record, kind in self.launched:
            if child.poll() is not None:
                continue
            processes.append(record)
            port = self.config[kind + "_port"]
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    listeners.append({"LocalPort": port, "OwningProcess": child.pid})
        return {"processes": processes, "listeners": listeners}

    def terminate(self, record):
        for child, actual, _ in self.launched:
            if actual == record and child.poll() is None:
                child.terminate()
                child.wait(timeout=3)


class SyntheticRuntime(tool.Runtime):
    def __init__(self, case):
        super().__init__(case["config"], SyntheticProcesses(case["config"]))
        self.script = case["root"] / "fake_server.py"
        self.script.write_text(FAKE_SERVER)
        self.migrations = 0
        self.migration_fails = False
        self.fail_after_first_stop = False

    def launch(self, args, release, kind, env):
        child = super().launch([sys._base_executable, "-B", str(self.script), kind,
                                release[kind + "_binding"], str(self.config[kind + "_port"])],
                               release, kind, env)
        record = {"ProcessId": child.pid, "ExecutablePath": tool.python(release["code"]),
                  "created": datetime.now(UTC).isoformat(),
                  "CommandLine": subprocess.list2cmdline(args)}
        self.processes.launched.append((child, record, kind))
        return child

    def stop(self, release):
        super().stop(release)
        if self.fail_after_first_stop:
            raise tool.Refused("synthetic_failure_after_stop")

    def migrate(self, release):
        self.migrations += 1
        with sqlite3.connect(Path(self.config["profile"]) / "healthcheck.db") as db:
            db.execute("UPDATE alembic_version SET version_num='r2'")
        if self.migration_fails:
            raise tool.Refused("synthetic_partial_migration")


@pytest.fixture
def runtime(release_case):
    runtime = SyntheticRuntime(release_case)
    old = tool.read_json(release_case["pointer"])
    old["mcp_binding"] = release_case["config"]["old_mcp_binding"]
    try:
        runtime.start(old)
        runtime.smoke(old)
        # Existing services are not newly started candidate processes.
        runtime.children.clear()
        runtime.started_releases.clear()
        yield runtime
    finally:
        for child, _, _ in runtime.processes.launched:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=3)


@pytest.mark.parametrize("failure", ["none", "after-stop", "new-ui"])
def test_code_only_activation_and_rollback(release_case, runtime, failure):
    case = release_case
    original = {entry["path"]: Path(entry["path"]).read_bytes()
                for entry in case["config"]["consumers"]}
    if failure == "new-ui":
        b = tool.read_json(case["ui_paths"][1])
        b["fail_start"] = True
        write_json(case["ui_paths"][1], b)
    runtime.fail_after_first_stop = failure == "after-stop"
    manifest = prepare(case)
    if failure == "none":
        receipt = tool.activate(case["manifest_path"], runtime)
        assert receipt["status"] == "PASS"
        assert tool.read_json(case["pointer"])["sha"] == case["new_sha"]
        previous = case["manifest_path"].parent / "active-code.previous.json"
        assert previous.read_bytes() == original[str(case["pointer"])]
        for entry in manifest["consumers"]:
            assert Path(entry["path"]).read_bytes() == entry["after"].encode()
    else:
        with pytest.raises(tool.Refused):
            tool.activate(case["manifest_path"], runtime)
        receipt = tool.read_json(case["manifest_path"].parent / "activation.json")
        assert receipt["status"] == "FAIL" and receipt["rollback"] == "PASS"
        for path, before in original.items():
            assert Path(path).read_bytes() == before
        restored = dict(manifest["old"], ui_binding=receipt["rollback_ui_binding"])
        runtime.smoke(restored)
    assert runtime.migrations == 0
    for path in case["root"].rglob("*"):
        if path.is_file():
            assert TOKEN.encode() not in path.read_bytes(), path
    with pytest.raises(tool.Refused, match="activation_already_attempted"):
        tool.activate(case["manifest_path"], runtime)


@pytest.mark.parametrize("during_migration", [False, True])
def test_strict_failure_leaves_services_stopped(release_case, runtime, during_migration):
    case = release_case
    make_strict(case)
    if not during_migration:
        b = tool.read_json(case["ui_paths"][1])
        b["fail_start"] = True
        write_json(case["ui_paths"][1], b)
    runtime.migration_fails = during_migration
    prepare(case)
    with pytest.raises(tool.Refused, match="owner_recovery_required"):
        tool.activate(case["manifest_path"], runtime)
    receipt = tool.read_json(case["manifest_path"].parent / "activation.json")
    assert receipt["status"] == "FAIL" and "rollback" not in receipt
    assert runtime.migrations == 1
    assert all(child.poll() is not None for child, _, _ in runtime.processes.launched)
    assert tool.probe(case["new_code"], case["config"]["profile"], "current") == "r2"


def test_activation_refuses_changed_profile_before_stop(release_case, runtime):
    case = release_case
    prepare(case)
    with sqlite3.connect(Path(case["config"]["profile"]) / "healthcheck.db") as db:
        db.execute("UPDATE alembic_version SET version_num='unexpected'")
    with pytest.raises(tool.Refused):
        tool.activate(case["manifest_path"], runtime)
    assert all(child.poll() is None for child, _, _ in runtime.processes.launched)
    receipt = tool.read_json(case["manifest_path"].parent / "activation.json")
    assert receipt["status"] == "FAIL"
    assert [s["stage"] for s in receipt["stages"]] == ["preflight"]


def test_actual_autostart_binding_is_separate_from_pointer_template(release_case, runtime):
    case = release_case
    pointer = tool.read_json(case["pointer"])
    old = dict(pointer, mcp_binding=case["config"]["old_mcp_binding"])
    runtime.stop(old)
    actual = runtime.start(old, fresh=True)
    runtime.smoke(actual)
    runtime.children.clear()
    runtime.started_releases.clear()
    case["config"]["old_ui_binding"] = actual["ui_binding"]
    manifest = prepare(case)
    assert manifest["old"]["ui_binding"] != pointer["ui_binding"]
    assert manifest["rollback_target"]["ui_binding"] == pointer["ui_binding"]
    assert tool.activate(case["manifest_path"], runtime)["status"] == "PASS"


def test_refuses_token_bearing_input(tmp_path, monkeypatch):
    monkeypatch.setenv("HEALTHCHECK_MCP_GATEWAY_TOKEN", TOKEN)
    with pytest.raises(tool.Refused, match="credential_in_input"):
        tool.create_json(tmp_path / "manifest.json", {"secret": TOKEN})


def test_real_read_only_alembic_probe(tmp_path):
    code = Path(__file__).resolve().parents[1]
    profile = tmp_path / "synthetic-probe"
    profile.mkdir()
    db_path = profile / "healthcheck.db"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE alembic_version (version_num TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('synthetic_read_only')")
    before = db_path.read_bytes()
    assert tool.probe(code, profile, "current") == "synthetic_read_only"
    assert db_path.read_bytes() == before
    assert not db_path.with_name("healthcheck.db-wal").exists()
    assert tool.probe(code, profile, "head").startswith("0023_")


@pytest.mark.parametrize("engine", ["powershell.exe", "pwsh"])
def test_powershell_wrapper_parses_in_available_engines(engine):
    import shutil

    executable = shutil.which(engine)
    if executable is None:
        pytest.skip(engine + " unavailable")
    script = str(tool.HERE / "StartStable.ps1").replace("'", "''")
    code = ("$t=$null;$e=$null;[System.Management.Automation.Language.Parser]::"
            f"ParseFile('{script}',[ref]$t,[ref]$e)|Out-Null;if($e.Count){{exit 1}}")
    tool.command([executable, "-NoProfile", "-NonInteractive", "-Command", code])


def test_schema_rewrite_preserves_revision_substrings_in_paths(release_case):
    case = release_case
    make_strict(case)
    entry = next(e for e in case["config"]["consumers"] if e["role"] == "weekly-backup")
    Path(entry["path"]).write_bytes(b"schema = 'r1'\npath = 'folder1/backup'\n")
    manifest = prepare(case)
    prepared = next(e for e in manifest["consumers"] if e["role"] == "weekly-backup")
    assert prepared["after"] == "schema = 'r2'\npath = 'folder1/backup'\n"


@pytest.mark.parametrize("drift", ["config", "binding", "consumer"])
def test_activation_preflight_rejects_input_drift(release_case, drift):
    case = release_case
    manifest = prepare(case)
    if drift == "config":
        case["config"]["known_page"] = "/other-page"
        write_json(case["config_path"], case["config"])
    elif drift == "binding":
        binding = tool.read_json(case["ui_paths"][1])
        binding["run_id"] = "another-run"
        write_json(case["ui_paths"][1], binding)
    else:
        entry = next(e for e in case["config"]["consumers"] if e["role"] == "owner-refresh")
        Path(entry["path"]).write_text("# changed consumer\n")
    with pytest.raises(tool.Refused):
        tool.preflight(manifest, tool.read_json(case["config_path"]))


def test_process_identity_and_busy_writer_refusals(release_case, runtime):
    old = tool.read_json(release_case["pointer"])
    old["mcp_binding"] = release_case["config"]["old_mcp_binding"]
    _, record, _ = runtime.processes.launched[1]
    before = record["CommandLine"]
    record["CommandLine"] = before.replace(old["mcp_binding"], "unrelated-binding")
    with pytest.raises(tool.Refused, match="service_binding_not_loaded"):
        runtime.stop(old)
    assert all(child.poll() is None for child, _, _ in runtime.processes.launched)
    record["CommandLine"] = "python -m healthcheck.cli owner-refresh"
    with pytest.raises(tool.Refused, match="writer_active"):
        runtime.idle()
    record["CommandLine"] = before


def test_real_ui_runner_and_mcp_binding_probe(tmp_path, monkeypatch):
    """Exercise the versioned launcher against the actual app and installed venv."""
    from dataclasses import asdict

    from healthcheck import assistant_period_read as assistant

    code = Path(__file__).resolve().parents[1]
    profile = tmp_path / "synthetic-live-ui"
    monkeypatch.setenv("HEALTHCHECK_DATA_DIR", str(profile))
    monkeypatch.setenv("HEALTHCHECK_MCP_GATEWAY_TOKEN", TOKEN)
    tool.command([sys.executable, "-I", "-B", "-m", "healthcheck.cli", "migrate",
                  "--data-dir", str(profile)])
    head = tool.probe(code, profile, "head")
    binding = assistant.OperatorBinding(
        profile=profile.resolve(), profile_kind="synthetic",
        database_id=assistant.database_identity(profile), code_id=assistant.code_identity(),
        runtime_id=assistant.runtime_identity(), schema_heads=(head,), evaluation_zone="UTC",
        sources=assistant.SourceBindings(activity_garmin_source_id="synthetic-garmin",
                                         sleep_garmin_source_id="synthetic-garmin"))
    serialized = asdict(binding)
    serialized["profile"] = str(profile)
    mcp_path = write_json(tmp_path / "assistant.json", serialized)
    assert tool.probe(code, profile, "binding", mcp_path) == {"status": "PASS"}
    serialized["code_id"] = "0" * 64
    write_json(mcp_path, serialized)
    with pytest.raises(tool.Refused, match="command_failed"):
        tool.probe(code, profile, "binding", mcp_path)
    sha = tool.git(code, "rev-parse", "HEAD")
    port = free_port()
    ui = write_json(tmp_path / "ui.json", {
        "code": str(code), "sha": sha, "profile": str(profile), "port": port,
        "schema": head, "head_file": str(code / ".git/HEAD"), "runner_version": 1,
        "run_id": "synthetic-real-ui", "receipt": "ready.json", "stop_file": "ui.stop"})
    runtime = tool.Runtime({"profile": str(profile)})
    try:
        output = tool.command([sys.executable, "-I", "-B", str(tool.HERE / "ui_server.py"),
                               "--launch", str(ui)])
        assert "BOUND_UI_READY synthetic-real-ui" in output
        health = json.loads(runtime.request(port, "/healthz"))
        assert health["sha"] == sha and health["run_id"] == "synthetic-real-ui"
        assert health["profile"] == str(profile)
        assert runtime.request(port, "/")
        assert tool.probe(code, profile, "current") == head
    finally:
        (tmp_path / "ui.stop").write_text("synthetic-real-ui")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", port)) != 0:
                    break
            time.sleep(.1)
        else:
            pytest.fail("synthetic UI did not stop")
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert TOKEN.encode() not in path.read_bytes()


@pytest.fixture
def pointer_case(release_case):
    case = release_case
    pointer = tool.read_json(case['pointer'])
    pointer['mcp_binding'] = case['config']['old_mcp_binding']
    write_json(case['pointer'], pointer)
    case['config']['google_hr_flag'] = str(case['root'] / 'google-hr.enabled')
    case['config']['weekly_backup_script'] = str(case['root'] / 'backup.py')
    return case


def test_resolver_accepts_bom_pointer_once(pointer_case, monkeypatch):
    case = pointer_case
    case['pointer'].write_bytes(b'\xef\xbb\xbf' + case['pointer'].read_bytes())
    reads = []
    original = tool.read_json

    def read(path):
        if Path(path) == case['pointer']:
            reads.append(path)
        return original(path)

    monkeypatch.setattr(tool, 'read_json', read)
    active = consumers.resolve_active(case['config'])
    assert active['python'] == tool.python(case['old_code'])
    assert active['sha'] == case['old_sha']
    assert active['ui_binding'] == str(case['ui_paths'][0])
    assert active['mcp_binding'] == str(case['mcp_paths'][0])
    assert len(reads) == 1


@pytest.mark.parametrize('fault', [
    'sha', 'short-sha', 'outside', 'missing-venv', 'profile', 'partial', 'corrupt',
    'missing', 'array', 'ui', 'mcp', 'token', 'venv-outside',
])
def test_resolver_fails_closed(pointer_case, monkeypatch, capsys, fault):
    case = pointer_case
    pointer = tool.read_json(case['pointer'])
    if fault == 'sha':
        pointer['sha'] = '0' * 40
    elif fault == 'short-sha':
        pointer['sha'] = case['old_sha'][:8]
    elif fault == 'outside':
        pointer['code'] = case['config']['repository']
    elif fault == 'missing-venv':
        Path(tool.python(case['old_code'])).unlink()
    elif fault == 'profile':
        pointer['profile'] = str(case['root'])
    elif fault == 'ui':
        ui = tool.read_json(case['ui_paths'][0])
        ui['sha'] = case['new_sha']
        write_json(case['ui_paths'][0], ui)
    elif fault == 'mcp':
        binding = tool.read_json(case['mcp_paths'][0])
        binding['profile'] = str(case['root'])
        write_json(case['mcp_paths'][0], binding)
    elif fault == 'token':
        pointer['secret'] = TOKEN
    elif fault == 'venv-outside':
        monkeypatch.setattr(tool, 'python', lambda code: str(case['root'] / 'python.exe'))
    write_json(case['pointer'], pointer)
    if fault in ('partial', 'corrupt'):
        case['pointer'].write_bytes(b'{"code":' if fault == 'partial' else b'\xffinvalid')
    if fault == 'missing':
        case['pointer'].unlink()
    if fault == 'array':
        write_json(case['pointer'], [])
    write_json(case['config_path'], case['config'])
    calls = []
    monkeypatch.setattr(consumers, 'run_work', lambda *a, **kw: calls.append(a))
    assert consumers.main(['run-owner-refresh', '--config', str(case['config_path'])]) == 2
    assert calls == []
    captured = capsys.readouterr()
    assert captured.err == 'active_pointer_invalid\n'
    assert captured.out == ''


@pytest.mark.parametrize('action', ['run-owner-refresh', 'run-weekly-backup'])
def test_work_pins_interpreter_and_snapshot_when_pointer_flips(pointer_case, monkeypatch,
                                                               capfd, action):
    case = pointer_case
    backup = Path(case['config']['weekly_backup_script'])
    backup.write_text('# synthetic backup', encoding='utf-8')
    Path(case['config']['google_hr_flag']).touch()
    write_json(case['config_path'], case['config'])
    calls = []
    real_run = consumers.subprocess.run

    def run(args, **kwargs):
        if args[0] == 'git':
            return real_run(args, **kwargs)
        calls.append((args, kwargs))
        pointer = tool.read_json(case['pointer'])
        pointer.update(code=str(case['new_code']), sha=case['new_sha'])
        write_json(case['pointer'], pointer)
        assert kwargs['env']['HEALTHCHECK_RELEASE_SHA'] == case['old_sha']
        assert kwargs['env']['HEALTHCHECK_RELEASE_CODE'] == str(case['old_code'])
        return subprocess.CompletedProcess(args, 17, b'synthetic output\n', b'')

    monkeypatch.setattr(consumers.subprocess, 'run', run)
    assert consumers.main([action, '--config', str(case['config_path'])]) == 17
    args, kwargs = calls[0]
    assert len(calls) == 1
    assert args[:3] == [tool.python(case['old_code']), '-I', '-B']
    assert kwargs['cwd'] == str(case['old_code'])
    assert kwargs['env']['HEALTHCHECK_DATA_DIR'] == case['config']['profile']
    assert 'timeout' not in kwargs
    if action == 'run-owner-refresh':
        assert args[3:6] == ['-m', 'healthcheck.cli', 'owner-refresh']
        assert args[-2:] == ['--stream', 'heart_rate']
        logs = list((Path(case['config']['profile']) / 'logs').glob('owner-refresh-*.log'))
        assert len(logs) == 1 and logs[0].read_bytes() == b'synthetic output\n'
    else:
        assert args[3:] == [str(backup), '--no-restore-rehearsal']
    assert capfd.readouterr().out == 'synthetic output\n'


def test_work_never_persists_or_emits_gateway_token(pointer_case, monkeypatch, capfd):
    active = consumers.resolve_active(pointer_case['config'])
    monkeypatch.setattr(consumers.subprocess, 'run', lambda *a, **kw:
                        subprocess.CompletedProcess(a, 0, b'safe stdout', TOKEN.encode()))
    log = pointer_case['root'] / 'must-not-exist.log'
    with pytest.raises(tool.Refused, match='credential_in_input'):
        consumers.run_work(active, ['synthetic'], log=log)
    assert not log.exists()
    assert capfd.readouterr() == ('', '')


def test_owner_refresh_preserves_default_streams_without_hr_toggle(pointer_case, monkeypatch):
    active = consumers.resolve_active(pointer_case['config'])
    calls = []
    monkeypatch.setattr(consumers, 'run_work', lambda a, args, **kw: calls.append(args) or 0)
    assert consumers.run_owner_refresh(active, pointer_case['config']) == 0
    assert 'heart_rate' not in calls[0]
    assert calls[0].count('--stream') == len(consumers.STREAMS)


@pytest.mark.parametrize('failure', [False, True])
def test_migrated_activation_writes_and_restores_pointer_only(pointer_case, runtime,
                                                              monkeypatch, failure):
    case = pointer_case
    for entry in case['config']['consumers']:
        if entry['role'] != 'active-pointer':
            entry['mode'] = 'pointer-reading'
            entry.pop('replacements', None)
    if failure:
        ui = tool.read_json(case['ui_paths'][1])
        ui['fail_start'] = True
        write_json(case['ui_paths'][1], ui)
    original = {e['path']: Path(e['path']).read_bytes() for e in case['config']['consumers']}
    manifest = prepare(case)
    assert [e['role'] for e in manifest['consumers']] == ['active-pointer']
    assert manifest['proposed_pointer']['mcp_binding'] == case['config']['mcp_binding']
    writes = []
    monkeypatch.setattr(tool, 'write_preserved', lambda *a, **kw: writes.append(a))
    if failure:
        with pytest.raises(tool.Refused):
            tool.activate(case['manifest_path'], runtime)
        assert {p: Path(p).read_bytes() for p in original} == original
        receipt = tool.read_json(case['manifest_path'].parent / 'activation.json')
        assert receipt['rollback'] == 'PASS'
        assert 'restore_pointer' in [s['stage'] for s in receipt['stages']]
    else:
        assert tool.activate(case['manifest_path'], runtime)['status'] == 'PASS'
        assert tool.read_json(case['pointer'])['mcp_binding'] == str(case['mcp_paths'][1])
        for path, before in original.items():
            if path != str(case['pointer']):
                assert Path(path).read_bytes() == before
    assert writes == []


def test_gradual_migration_keeps_legacy_rewrites(pointer_case):
    case = pointer_case
    entry = next(e for e in case['config']['consumers'] if e['role'] == 'owner-refresh')
    entry['mode'] = 'pointer-reading'
    # A skipped consumer may contain historical evidence; it must not enter the manifest.
    Path(entry['path']).write_bytes(TOKEN.encode())
    manifest = prepare(case)
    assert entry['role'] not in [e['role'] for e in manifest['consumers']]
    legacy = next(e for e in manifest['consumers'] if e['role'] == 'weekly-backup')
    assert case['new_sha'] in legacy['after'] and case['old_sha'] in legacy['before']
    assert TOKEN.encode() not in case['manifest_path'].read_bytes()


@pytest.mark.parametrize('role,mode,replacements', [
    ('owner-refresh', 'typo', []),
    ('active-pointer', 'pointer-reading', []),
    ('owner-refresh', 'pointer-reading', [['old', 'new']]),
])
def test_consumer_migration_declarations_fail_closed(pointer_case, role, mode, replacements):
    entry = next(e for e in pointer_case['config']['consumers'] if e['role'] == role)
    entry.update(mode=mode, replacements=replacements)
    with pytest.raises(tool.Refused):
        prepare(pointer_case)


def test_weekly_runs_real_resolved_venv_and_keeps_release_during_flip(pointer_case, capfd):
    import venv

    case = pointer_case
    executable = Path(tool.python(case['old_code']))
    executable.unlink()
    venv.EnvBuilder(with_pip=False, symlinks=False).create(case['old_code'] / '.venv')
    script = Path(case['config']['weekly_backup_script'])
    script.write_text(
        'import json,os,sys\nfrom pathlib import Path\n'
        f'p=Path({str(case["pointer"])!r})\n'
        'before=json.loads(p.read_text(encoding="utf-8-sig"))\n'
        f'before.update(code={str(case["new_code"])!r}, sha={case["new_sha"]!r})\n'
        'p.write_text(json.dumps(before),encoding="utf-8")\n'
        'print(json.dumps(dict(python=sys.executable,code=os.environ["HEALTHCHECK_RELEASE_CODE"],'
        'sha=os.environ["HEALTHCHECK_RELEASE_SHA"],profile=os.environ["HEALTHCHECK_DATA_DIR"],'
        'args=sys.argv[1:])))\n', encoding='utf-8')
    active = consumers.resolve_active(case['config'])
    assert consumers.run_weekly_backup(active, case['config']) == 0
    actual = json.loads(capfd.readouterr().out)
    assert Path(actual['python']) == executable
    assert actual['code'] == str(case['old_code'])
    assert actual['sha'] == case['old_sha']
    assert actual['profile'] == case['config']['profile']
    assert actual['args'] == ['--no-restore-rehearsal']
    assert tool.read_json(case['pointer'])['sha'] == case['new_sha']


@pytest.mark.parametrize('engine', ['powershell.exe', 'pwsh'])
def test_pointer_migration_commands_parse_in_available_engines(tmp_path, engine):
    import re
    import shutil

    executable = shutil.which(engine)
    if executable is None:
        pytest.skip(engine + ' unavailable')
    document = (tool.HERE.parents[1] / 'docs/OWNER_OPERATIONS.md').read_text(encoding='utf-8')
    plan = document.split('<a id="stable-pointer-migration">', 1)[1].split(
        '<a id="profile-backup">', 1)[0]
    blocks = re.findall(r'```powershell\n(.*?)```', plan, re.DOTALL)
    assert len(blocks) == 3
    for index, block in enumerate(blocks):
        script = tmp_path / f'migration-{index}.ps1'
        script.write_text(block, encoding='utf-8')
        quoted = str(script).replace("'", "''")
        code = ("$t=$null;$e=$null;[System.Management.Automation.Language.Parser]::"
                f"ParseFile('{quoted}',[ref]$t,[ref]$e)|Out-Null;"
                'if($e.Count){$e|ForEach-Object{[Console]::Error.WriteLine($_)};exit 1}')
        tool.command([executable, '-NoProfile', '-NonInteractive', '-Command', code])


def test_legacy_json_rewrite_reads_bom_and_publishes_without_bom(pointer_case):
    case = pointer_case
    entry = next(e for e in case['config']['consumers'] if e['role'] == 'period-handoff')
    path = Path(entry['path'])
    before = b'\xef\xbb\xbf' + path.read_bytes()
    path.write_bytes(before)
    manifest = prepare(case)
    prepared = next(e for e in manifest['consumers'] if e['role'] == 'period-handoff')
    assert prepared['before'].encode() == before
    assert not prepared['after'].encode().startswith(b'\xef\xbb\xbf')
    assert json.loads(prepared['after'])['sha'] == case['new_sha']


def test_prepare_rejects_mcp_pointer_config_disagreement(pointer_case):
    case = pointer_case
    pointer = tool.read_json(case['pointer'])
    pointer['mcp_binding'] = str(case['mcp_paths'][1])
    write_json(case['pointer'], pointer)
    with pytest.raises(tool.Refused, match='installed_mcp_pointer_mismatch'):
        prepare(case)


def test_weekly_duplicate_mutex_never_launches_child(pointer_case, monkeypatch, capsys):
    from contextlib import contextmanager

    case = pointer_case
    active = consumers.resolve_active(case['config'])
    Path(case['config']['weekly_backup_script']).touch()

    @contextmanager
    def busy(*args):
        raise tool.Refused('autostart_busy')
        yield

    monkeypatch.setattr(tool, 'autostart_lock', busy)
    monkeypatch.setattr(consumers, 'run_work', lambda *a, **kw: pytest.fail('launched backup'))
    assert consumers.run_weekly_backup(active, case['config']) == 0
    assert capsys.readouterr().out == 'SKIP: existing Health data-only backup\n'


@pytest.mark.parametrize("option,value,timeout,expected", [
    ("page_delay", 2.2, 4, None),
    ("page_delay", 1, .1, "known_page_timeout"),
    ("page_redirect", True, 1, "known_page_redirect"),
    ("page_unavailable", True, 1, "known_page_unavailable"),
    ("health_unavailable", True, 1, "ui_health_unavailable"),
    ("mcp_unavailable", True, 1, "mcp_unavailable"),
])
def test_smoke_step_failures_and_page_timeout(release_case, runtime, option, value,
                                               timeout, expected):
    case = release_case
    kind = "mcp" if option == "mcp_unavailable" else "ui"
    path = case["mcp_paths"][0] if kind == "mcp" else case["ui_paths"][0]
    binding = tool.read_json(path)
    binding[option] = value
    write_json(path, binding)
    runtime.config["known_page_timeout_seconds"] = timeout
    # One attempt for failure cases; success proves pages can exceed the short 2 s timeout.
    runtime.config["timeout_seconds"] = .05 if expected else 5
    old = tool.read_json(case["pointer"])
    old["mcp_binding"] = case["config"]["old_mcp_binding"]
    if expected:
        with pytest.raises(tool.Refused, match="^service_smoke_timeout:" + expected + "$"):
            runtime.smoke(old)
    else:
        runtime.smoke(old)
