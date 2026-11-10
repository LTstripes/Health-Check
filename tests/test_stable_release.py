"""Synthetic release trees and real disposable UI/MCP HTTP subprocesses only."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
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
        self.send_response(200);self.end_headers()
        self.wfile.write(json.dumps(identity if self.path=='/healthz' else {'page':'ok'}).encode())
    def do_POST(self):
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
