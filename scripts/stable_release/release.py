"""Offline release CLI. See config.example.json and OWNER_OPERATIONS.md.

No scheduler mutations, provider calls, backup creation or database restore.
Subprocess output and HTTP bodies are never persisted in diagnostics.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

HERE = Path(__file__).resolve().parent
CONSUMERS = {
    "owner-refresh", "weekly-runner", "weekly-backup", "active-pointer",
    "period-handoff", "weekly-handoff", "weekly-recipe",
}
SHA = re.compile(r"[0-9a-f]{40}")
HASH = re.compile(r"[0-9a-f]{64}")


class Refused(RuntimeError):
    """Only fixed, nonsensitive error codes cross the CLI/receipt boundary."""


def require(condition, code):
    if not condition:
        raise Refused(code)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def secret_free(data):
    token = os.environ.get("HEALTHCHECK_MCP_GATEWAY_TOKEN")
    require(not token or token.encode() not in data, "credential_in_input")
    return data


def read_json(path):
    try:
        return json.loads(secret_free(Path(path).read_bytes()).decode("utf-8-sig"))
    except (OSError, ValueError):
        raise Refused("json_unavailable_or_invalid") from None


def json_bytes(value):
    return secret_free((json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def create_json(path, value):
    data = json_bytes(value)
    with Path(path).open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def utc(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(result.utcoffset() == timedelta(0), "timestamp_not_utc")
        return result
    except (TypeError, ValueError, AttributeError):
        raise Refused("invalid_timestamp") from None


def absolute(value):
    path = Path(value)
    require(path.is_absolute() and path.resolve() == path, "absolute_canonical_path_required")
    return path


def command(args, cwd=None, env=None):
    try:
        result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, timeout=120,
                                creationflags=0x08000000 if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired):
        raise Refused("command_unavailable_or_timeout") from None
    require(result.returncode == 0, "command_failed")
    return result.stdout.decode("utf-8-sig").strip()


def git(code, *args):
    return command(["git", "-C", str(code), *args])


def python(code):
    path = Path(code) / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    require(path.is_file(), "release_venv_missing")
    return str(path)


def probe(code, profile, action, *args):
    env = dict(os.environ, HEALTHCHECK_DATA_DIR=str(profile))
    return json.loads(command([python(code), "-I", "-B", str(HERE / "probe.py"), action,
                               str(code), str(profile), *map(str, args)], cwd=code, env=env))


def classify(changed_paths, current, head, force_strict=False):
    reasons = []
    if any(p.startswith("src/healthcheck/db/migrations/")
           or p == "src/healthcheck/db/models.py" or p.startswith("src/healthcheck/db/models/")
           for p in changed_paths):
        reasons.append("migrations_or_models_changed")
    if current != head:
        reasons.append("profile_revision_differs_from_target_head")
    if force_strict:
        reasons.append("operator_requires_strict")
    return ("strict", reasons) if reasons else ("code-only", ["schema_and_models_unchanged"])


def recovery(config, route, old_schema, target, head, now):
    receipt = read_json(config["recovery_receipt"])
    required = {"path", "utc", "sha256", "schema", "profile", "status", "verified"}
    require(required <= receipt.keys(), "recovery_receipt_fields_missing")
    require(receipt["status"] == "PASS" and receipt["verified"] is True,
            "recovery_not_verified")
    require(receipt["profile"] == config["profile"] and receipt["schema"] == old_schema,
            "recovery_profile_or_schema_mismatch")
    require(HASH.fullmatch(receipt["sha256"]) is not None, "invalid_recovery_hash")
    require(absolute(receipt["path"]).is_file(), "recovery_point_inaccessible")
    # Trust the already verified regular receipt. Do not rehash a full profile ZIP.
    age = now - utc(receipt["utc"])
    limit = timedelta(days=8) if route == "code-only" else timedelta(hours=24)
    require(timedelta(0) <= age <= limit, "recovery_point_expired_or_future")
    if route == "strict":
        require(receipt.get("candidate_sha") == target, "fresh_recovery_candidate_mismatch")
        rehearsal = read_json(config["rehearsal_receipt"])
        expected = {"status": "PASS", "candidate_sha": target, "profile": config["profile"],
                    "from_schema": old_schema, "to_schema": head,
                    "recovery_sha256": receipt["sha256"]}
        require(all(rehearsal.get(k) == v for k, v in expected.items()),
                "migration_rehearsal_mismatch")
        require(timedelta(0) <= now - utc(rehearsal["utc"]) <= timedelta(hours=24),
                "migration_rehearsal_expired_or_future")
    return {k: receipt[k] for k in sorted(required | ({"candidate_sha"} & receipt.keys()))}


def check_ui(path, code, sha, profile, head, port):
    binding = read_json(path)
    expected = {"code": str(code), "sha": sha, "profile": str(profile), "port": port}
    require(all(binding.get(k) == v for k, v in expected.items()), "ui_binding_mismatch")
    require(binding.get("schema", head) == head, "ui_schema_mismatch")
    require(re.fullmatch(r"[A-Za-z0-9_-]+", binding.get("run_id", "")) is not None,
            "invalid_ui_run_id")
    for key in ("receipt", "stop_file"):
        value = binding.get(key, "")
        require(value and Path(value).name == value and value not in (".", ".."),
                "ui_output_must_be_local_filename")
    head_file = absolute(binding["head_file"])
    require(head_file == code / ".git/HEAD" and head_file.read_text().strip() == sha,
            "detached_ui_head_mismatch")
    return binding


def check_mcp(path, code, profile, head):
    binding = read_json(path)
    require(binding.get("profile") == str(profile) and binding.get("schema_heads") == [head],
            "mcp_binding_mismatch")
    probe(code, profile, "binding", path)


def prepared_consumers(config, old, new, pointer, proposed, old_schema, head):
    entries = config["consumers"]
    require(len(entries) == 7 and {e["role"] for e in entries} == CONSUMERS,
            "exactly_seven_consumers_required")
    require(len({e["path"] for e in entries}) == 7, "duplicate_consumer")
    pairs = [(old["code"].replace("\\", "\\\\"), new["code"].replace("\\", "\\\\")),
             (old["code"], new["code"]), (old["sha"], new["sha"])]
    if old_schema != head:
        # Revisions are literal values, not substrings of arbitrary paths/run IDs.
        pairs.extend((quote + old_schema + quote, quote + head + quote)
                     for quote in ("'", '"'))
    result = []
    for entry in entries:
        path = absolute(entry["path"])
        before = secret_free(path.read_bytes())
        if entry["role"] == "active-pointer":
            require(path == pointer, "pointer_consumer_mismatch")
            after = json_bytes(proposed)
        else:
            text = before.decode("utf-8-sig")
            for source, replacement in entry.get("replacements", []):
                require(source != "", "empty_rewrite")
                require(source in text, "explicit_rewrite_source_missing")
                text = text.replace(source, replacement)
            for source, replacement in pairs:
                text = text.replace(source, replacement)
            if path.suffix == ".json":
                json.loads(text)
            if entry["role"] == "weekly-recipe":
                bindings = re.findall(r"(?m)^Binding:\s*(.+?)\s*$", text)
                require(bindings == [new["mcp_binding"]], "weekly_recipe_binding_mismatch")
            after = secret_free((b"\xef\xbb\xbf" if before.startswith(b"\xef\xbb\xbf")
                                 else b"") + text.encode())
        result.append({"role": entry["role"], "path": str(path),
                       "before": before.decode("utf-8"), "before_sha256": digest(before),
                       "after": after.decode("utf-8"), "after_sha256": digest(after)})
    return result


def candidate(config, target, ci_id, force_strict=False, now=None):
    now = now or datetime.now(UTC)
    require(SHA.fullmatch(target) is not None, "full_target_sha_required")
    require(re.fullmatch(r"[1-9][0-9]*(?:/attempts/[1-9][0-9]*)?", ci_id) is not None,
            "invalid_ci_run_id")
    profile, repo = absolute(config["profile"]), absolute(config["repository"])
    for field in ("ci_receipt", "recovery_receipt", "old_mcp_binding"):
        absolute(config[field])
    require((profile / "healthcheck.db").is_file(), "existing_profile_required")
    pointer = absolute(config["active_pointer"])
    old = read_json(pointer)
    old_ui = str(absolute(config.get("old_ui_binding", old["ui_binding"])))
    require(SHA.fullmatch(old["sha"]) is not None and old["profile"] == str(profile),
            "installed_pointer_mismatch")
    require(old["sha"] != target, "target_already_installed")
    new_code = absolute(config["releases_root"]) / ("stable-code-" + target[:8])
    absolute(str(new_code))
    for code, sha in ((absolute(old["code"]), old["sha"]), (new_code, target)):
        require(not profile.is_relative_to(code) and not code.is_relative_to(profile),
                "profile_code_overlap")
        require(git(code, "rev-parse", "HEAD") == sha, "checkout_sha_mismatch")
        require(not git(code, "status", "--porcelain", "--untracked-files=normal"),
                "checkout_dirty")
        python(code)
    require(not profile.is_relative_to(repo) and not repo.is_relative_to(profile),
            "profile_repository_overlap")
    git(repo, "merge-base", "--is-ancestor", target, "origin/main")
    ci = read_json(config["ci_receipt"])
    require(ci.get("sha") == target and ci.get("run_id") == ci_id
            and ci.get("status") == "PASS", "exact_ci_receipt_mismatch")
    require(all(ci.get("jobs", {}).get(job) == "success"
                for job in ("quality", "test", "windows-smoke", "checks")),
            "exact_ci_jobs_not_green")
    changed = git(repo, "diff", "--name-only", "--no-renames", old["sha"], target).splitlines()
    current = probe(new_code, profile, "current")
    old_head = probe(old["code"], profile, "head")
    require(old_head == current and old.get("schema") == current, "installed_schema_mismatch")
    head = probe(new_code, profile, "head")
    route, reasons = classify(changed, current, head, force_strict)
    rp = recovery(config, route, current, target, head, now)
    require(1 <= config.get("ui_port", 8120) <= 65535
            and 1 <= config.get("mcp_port", 8787) <= 65535
            and config.get("ui_port", 8120) != config.get("mcp_port", 8787), "invalid_ports")
    require(0 < config.get("timeout_seconds", 45) <= 120, "invalid_timeout")
    require(config.get("known_page", "/").startswith("/")
            and not config.get("known_page", "/").startswith("//"), "invalid_known_page")
    new_ui, new_mcp = map(str, map(absolute, (config["ui_binding"], config["mcp_binding"])))
    require(new_ui != old["ui_binding"] and new_mcp != config["old_mcp_binding"],
            "fresh_bindings_required")
    check_ui(old["ui_binding"], Path(old["code"]), old["sha"], profile, current,
             config.get("ui_port", 8120))
    check_ui(old_ui, Path(old["code"]), old["sha"], profile, current,
             config.get("ui_port", 8120))
    new_binding = check_ui(new_ui, new_code, target, profile, head, config.get("ui_port", 8120))
    require(new_binding.get("runner_version") == 1, "versioned_ui_binding_required")
    require(all(not (Path(new_ui).parent / new_binding[key]).exists()
                for key in ("receipt", "stop_file")), "fresh_ui_outputs_required")
    check_mcp(config["old_mcp_binding"], Path(old["code"]), profile, current)
    check_mcp(new_mcp, new_code, profile, head)
    proposed = dict(old, code=str(new_code), sha=target, schema=head, ui_binding=new_ui,
                    ui_start_script=str(HERE / "StartStable.ps1"), previous_version=old["sha"],
                    rollback_directory=old["code"], previous_active_binding=old["ui_binding"])
    new = {"code": str(new_code), "sha": target, "ui_binding": new_ui, "mcp_binding": new_mcp}
    consumers = prepared_consumers(config, old, new, pointer, proposed, current, head)
    for entry in consumers:
        require(not any(Path(entry["path"]).is_relative_to(root)
                        for root in (Path(old["code"]), new_code, profile, repo)),
                "consumer_overlaps_profile_or_code")
        require(entry["path"] not in (config["ci_receipt"], config["recovery_receipt"],
                                     old["ui_binding"], config["old_mcp_binding"],
                                     new_ui, new_mcp),
                "consumer_overlaps_input")
    return {"format": 1, "old_sha": old["sha"], "new_sha": target, "profile": str(profile),
            "route": route, "reasons": reasons, "force_strict": force_strict,
            "current_revision": current, "target_head": head, "recovery_point": rp,
            "ci_id": ci_id, "old": dict(old, ui_binding=old_ui,
                                       mcp_binding=config["old_mcp_binding"]),
            "new": new, "rollback_target": old, "active_pointer": str(pointer),
            "proposed_pointer": proposed, "consumers": consumers,
            "tooling_sha256": {name: digest((HERE / name).read_bytes()) for name in
                               ("release.py", "probe.py", "ui_server.py", "StartStable.ps1")},
            "bindings_sha256": {p: digest(Path(p).read_bytes()) for p in
                                (old["ui_binding"], old_ui, config["old_mcp_binding"],
                                 new_ui, new_mcp)}}


def preflight(manifest, config, now=None):
    expected = candidate(config, manifest["new_sha"], manifest["ci_id"],
                         manifest["force_strict"], now)
    require(digest(Path(manifest["config"]).read_bytes()) == manifest["config_sha256"],
            "config_changed")
    require({k: v for k, v in manifest.items()
             if k not in ("config", "config_sha256", "prepared_utc")}
            == expected, "manifest_reality_mismatch")


def prepare(config_path, target, ci_id, output, force_strict=False):
    config_path = absolute(str(Path(config_path).resolve()))
    config = read_json(config_path)
    manifest = candidate(config, target, ci_id, force_strict)
    manifest.update(config=str(config_path), config_sha256=digest(config_path.read_bytes()),
                    prepared_utc=datetime.now(UTC).isoformat())
    # Serialize and parse before publication; preflight compares structured fields.
    preflight(json.loads(json_bytes(manifest)), config)
    create_json(output, manifest)
    age = (datetime.now(UTC) - utc(manifest["recovery_point"]["utc"])).total_seconds() / 86400
    print(f"{manifest['old_sha'][:8]} -> {target[:8]}; {manifest['route']}: "
          f"{', '.join(manifest['reasons'])}; recovery {age:.2f}d; preflight PASS")
    return manifest


def atomic_pointer(path, value, previous, raw=None):
    """ReplaceFileW preserves the destination ACL and keeps the original backup."""
    path, previous = Path(path), Path(previous)
    require(not previous.exists(), "previous_pointer_already_exists")
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        if raw is None:
            create_json(temp, value)
        else:
            with temp.open("xb") as stream:
                stream.write(secret_free(raw))
                stream.flush()
                os.fsync(stream.fileno())
        require(read_json(temp) == value, "pointer_temp_validation_failed")
        if os.name == "nt":
            replace = ctypes.WinDLL("kernel32", use_last_error=True).ReplaceFileW
            replace.argtypes = [ctypes.c_wchar_p] * 3 + [ctypes.c_ulong, ctypes.c_void_p,
                                                        ctypes.c_void_p]
            replace.restype = ctypes.c_int
            require(bool(replace(str(path), str(temp), str(previous), 0, None, None)),
                    "atomic_pointer_replace_failed")
        else:
            # Same-directory replacement is atomic; retain the exact previous bytes.
            with previous.open("xb") as stream:
                stream.write(path.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temp, path.stat().st_mode)
            os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def write_preserved(entry, data, expected_hash, on_write=None):
    path = Path(entry["path"])
    with path.open("r+b") as stream:
        require(digest(stream.read()) == expected_hash, "consumer_drift")
        if on_write is not None:
            on_write()
        stream.seek(0)
        stream.write(secret_free(data))
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())


@contextlib.contextmanager
def autostart_lock(path, name="Local\\HealthCheckAutostart"):
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateMutexW(None, False, name)
        require(handle, "autostart_mutex_unavailable")
        held = False
        try:
            held = kernel.WaitForSingleObject(handle, 0) in (0, 0x80)
            require(held, "autostart_busy")
            yield
        finally:
            if held:
                kernel.ReleaseMutex(handle)
            kernel.CloseHandle(handle)
    else:
        import fcntl

        with Path(path).open("a+b") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


@contextlib.contextmanager
def writer_lock(profile):
    # Same byte-range/flock protocol as ExternalRuntimeOperationLock, no imports
    # from whichever development checkout happens to invoke this operator tool.
    with (Path(profile) / ".external-runtime-operation.lock").open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class WindowsProcesses:
    def inventory(self):
        require(os.name == "nt", "windows_process_identity_required")
        script = ("$ErrorActionPreference='Stop'; "
                  "[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false); "
                  "$p=@(Get-CimInstance Win32_Process | Select-Object ProcessId,Name,"
                  "ExecutablePath,CommandLine,@{n='created';e={$_.CreationDate."
                  "ToUniversalTime().ToString('o')}}); "
                  "$l=@(Get-NetTCPConnection -State Listen | Select-Object "
                  "LocalPort,OwningProcess); @{processes=$p;listeners=$l} | "
                  "ConvertTo-Json -Depth 5 -Compress")
        return json.loads(command(["powershell.exe", "-NoProfile", "-NonInteractive",
                                   "-Command", script]))

    def terminate(self, record):
        # Hold an OS process handle while rechecking creation time and command
        # line. PID reuse between the recheck and termination cannot kill a new PID.
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x100001, False, record["ProcessId"])
        if not handle:
            require(not any(p["ProcessId"] == record["ProcessId"]
                            for p in self.inventory()["processes"]), "process_handle_unavailable")
            return
        try:
            current = next((p for p in self.inventory()["processes"]
                            if p["ProcessId"] == record["ProcessId"]), None)
            if current is None:
                return
            require(current == record, "process_identity_changed")
            require(kernel.WaitForSingleObject(handle, 0) == 0
                    or kernel.TerminateProcess(handle, 1), "service_termination_failed")
        finally:
            kernel.CloseHandle(handle)


def argv(command_line):
    if os.name != "nt":
        import shlex

        return shlex.split(command_line)
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    count = ctypes.c_int()
    values = shell.CommandLineToArgvW(command_line, ctypes.byref(count))
    require(values, "command_line_unavailable")
    try:
        return list(values[:count.value])
    finally:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(values)


class Runtime:
    def __init__(self, config, processes=None):
        self.config = config
        self.processes = processes or WindowsProcesses()
        self.children = []
        self.started_releases = []
        self.stopping = []
        self.opener = build_opener(ProxyHandler({}))

    def idle(self):
        for process in self.processes.inventory()["processes"]:
            cmd = process.get("CommandLine") or ""
            require(cmd or not re.fullmatch(r"pythonw?\.exe|uv\.exe|powershell\.exe|pwsh\.exe",
                                           process.get("Name", ""), re.IGNORECASE),
                    "writer_process_identity_unavailable")
            require(not re.search(r"owner-refresh|owner_refresh|health-data-only-backup|"
                                  r"backup-profile|run-health-weekly|garmin-sync|google-sync|"
                                  r"healthcheck\.cli[\s\"]+migrate", cmd), "writer_active")

    def identified(self, release, kind):
        inventory = self.processes.inventory()
        port = self.config.get(kind + "_port", 8120 if kind == "ui" else 8787)
        pids = {p["OwningProcess"] for p in inventory["listeners"] if p["LocalPort"] == port}
        require(len(pids) == 1, "service_listener_ambiguous")
        record = next((p for p in inventory["processes"] if p["ProcessId"] in pids), None)
        require(record and record.get("CommandLine") and record.get("ExecutablePath")
                and record.get("created"), "service_process_identity_unavailable")
        args = argv(record["CommandLine"])
        binding = release[kind + "_binding"]
        require(binding in args, "service_binding_not_loaded")
        require(args and Path(args[0]).resolve() == Path(python(release["code"])).resolve(),
                "service_interpreter_mismatch")
        if kind == "mcp":
            require("healthcheck.chat_evidence_mcp" in args and "--assistant-binding" in args
                    and args[args.index("--assistant-binding") + 1] == binding,
                    "mcp_process_identity_mismatch")
        else:
            b = read_json(binding)
            receipt = read_json(Path(binding).parent / b["receipt"])
            require(receipt.get("pid") == record["ProcessId"]
                    and receipt.get("sha") == release["sha"]
                    and receipt.get("profile") == self.config["profile"]
                    and receipt.get("code") == release["code"], "ui_receipt_mismatch")
            require(receipt.get("run_id", b["run_id"]) == b["run_id"], "ui_run_id_mismatch")
        return record

    def stop(self, release):
        # Identify both before stopping either. Never kill by port or name alone.
        self.stopping = [self.identified(release, kind) for kind in ("ui", "mcp")]
        self.finish_stop()

    def finish_stop(self):
        for record in self.stopping:
            self.processes.terminate(record)
        self.wait_stopped(self.stopping)
        self.stopping.clear()

    def wait_stopped(self, records):
        deadline = time.monotonic() + self.config.get("timeout_seconds", 45)
        while time.monotonic() < deadline:
            alive = {p["ProcessId"] for p in self.processes.inventory()["processes"]}
            if not alive.intersection(p["ProcessId"] for p in records):
                return
            time.sleep(.1)
        raise Refused("service_stop_timeout")

    def start(self, release, fresh=False):
        release = dict(release)
        if fresh:
            old = Path(release["ui_binding"])
            binding = read_json(old)
            run = "rollback-" + uuid.uuid4().hex
            binding.update(run_id=run, receipt=run + ".json", stop_file=run + ".stop")
            path = old.with_name(run + "-binding.json")
            create_json(path, binding)
            release["ui_binding"] = str(path)
        b = read_json(release["ui_binding"])
        require(not (Path(release["ui_binding"]).parent / b["receipt"]).exists(),
                "ui_startup_receipt_exists")
        env = dict(os.environ, HEALTHCHECK_DATA_DIR=self.config["profile"],
                   HEALTHCHECK_INGEST_ENABLED="false")
        occupied = {p["LocalPort"] for p in self.processes.inventory()["listeners"]}
        require(not occupied.intersection((self.config.get("ui_port", 8120),
                                           self.config.get("mcp_port", 8787))),
                "service_port_occupied")
        self.started_releases.append(release)
        commands = [
            [python(release["code"]), "-I", "-B", str(HERE / "ui_server.py"),
             release["ui_binding"]],
            [python(release["code"]), "-I", "-B", "-m", "healthcheck.chat_evidence_mcp",
             "--assistant-binding", release["mcp_binding"], "--port",
             str(self.config.get("mcp_port", 8787))],
        ]
        for kind, args in zip(("ui", "mcp"), commands, strict=True):
            child = self.launch(args, release, kind, env)
            self.children.append(child)
        return release

    def launch(self, args, release, kind, env):
        return subprocess.Popen(args, cwd=release["code"], env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                creationflags=0x08000000 if os.name == "nt" else 0)

    def cleanup_started(self):
        # A Windows venv launcher may have a separate real interpreter process.
        # Stop only processes with these fresh binding argv and interpreter.
        for release in self.started_releases:
            for record in self.processes.inventory()["processes"]:
                args = argv(record.get("CommandLine") or "")
                if (args and args[0] == python(release["code"])
                        and (release["ui_binding"] in args or release["mcp_binding"] in args)):
                    self.processes.terminate(record)
        for child in self.children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=self.config.get("timeout_seconds", 45))
        self.children.clear()
        self.started_releases.clear()

    def request(self, port, path, body=None):
        headers = {}
        if body is not None:
            token = os.environ.get("HEALTHCHECK_MCP_GATEWAY_TOKEN")
            require(token, "gateway_token_environment_missing")
            headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json",
                       "Accept": "application/json, text/event-stream"}
        request = Request(f"http://127.0.0.1:{port}{path}", data=body, headers=headers)
        with self.opener.open(request, timeout=2) as response:
            require(response.status == 200, "http_smoke_failed")
            return response.read(1024 * 1024)

    def smoke(self, release):
        deadline = time.monotonic() + self.config.get("timeout_seconds", 45)
        reason = "http_unavailable"
        while time.monotonic() < deadline:
            try:
                for kind in ("ui", "mcp"):
                    self.identified(release, kind)
                ui = self.config.get("ui_port", 8120)
                health = json.loads(self.request(ui, "/healthz"))
                require(health.get("status") == "ok", "ui_health_failed")
                binding = read_json(release["ui_binding"])
                if binding.get("runner_version") == 1:
                    require(health.get("run_id") == binding["run_id"]
                            and health.get("sha") == release["sha"], "loaded_ui_mismatch")
                self.request(ui, self.config.get("known_page", "/"))
                body = json_bytes({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                   "params": {"protocolVersion": "2025-06-18",
                                              "capabilities": {},
                                              "clientInfo": {"name": "release-smoke",
                                                             "version": "1"}}})
                response = json.loads(self.request(self.config.get("mcp_port", 8787),
                                                   "/mcp", body))
                require(response.get("result", {}).get("serverInfo", {}).get("name")
                        == "health-check-evidence", "mcp_smoke_failed")
                require(probe(release["code"], self.config["profile"], "current")
                        == probe(release["code"], self.config["profile"], "head"),
                        "smoke_revision_mismatch")
                return
            except (Refused, OSError, ValueError) as exc:
                reason = str(exc) if isinstance(exc, Refused) else "http_unavailable"
                time.sleep(.2)
        raise Refused("service_smoke_timeout:" + reason)

    def migrate(self, release):
        command([python(release["code"]), "-I", "-B", "-m", "healthcheck.cli", "migrate",
                 "--data-dir", self.config["profile"]], cwd=release["code"],
                env=dict(os.environ, HEALTHCHECK_DATA_DIR=self.config["profile"]))


def activate(manifest_path, runtime=None):
    manifest_path = Path(manifest_path).resolve()
    receipt_path = manifest_path.parent / "activation.json"
    manifest = read_json(manifest_path)
    config = read_json(manifest["config"])
    runtime = runtime or Runtime(config)
    receipt = {"status": "FAIL", "old_sha": manifest["old_sha"],
               "new_sha": manifest["new_sha"], "route": manifest["route"], "stages": [],
               "started_utc": datetime.now(UTC).isoformat()}
    attempted = False
    migration_attempted = False
    published = []
    pointer_changed = False
    previous = manifest_path.parent / "active-code.previous.json"

    def stage(name, action):
        started = time.monotonic()
        record = {"stage": name, "status": "FAIL"}
        receipt["stages"].append(record)
        try:
            result = action()
            record["status"] = "PASS"
            return result
        finally:
            record["seconds"] = round(time.monotonic() - started, 3)

    # Lock scope covers validation, stop, publication, smoke AND rollback.
    with autostart_lock(manifest_path.parent / ".activation.lock",
                        config.get("autostart_mutex", "Local\\HealthCheckAutostart")), \
            writer_lock(config["profile"]):
        require(not receipt_path.exists(), "activation_already_attempted")
        # Exclusive attempt receipt prevents ambiguous retries, including prior crashes.
        create_json(manifest_path.parent / "activation-started.json",
                    {"utc": receipt["started_utc"], "new_sha": manifest["new_sha"]})
        try:
            stage("preflight", lambda: preflight(manifest, config))
            stage("writers_idle", runtime.idle)
            require(os.environ.get("HEALTHCHECK_MCP_GATEWAY_TOKEN"),
                    "gateway_token_environment_missing")
            # Bind both identities before entering the destructive stage.
            stage("old_services", lambda: runtime.smoke(manifest["old"]))
            attempted = True
            stage("stop_old", lambda: runtime.stop(manifest["old"]))
            if manifest["route"] == "strict":
                # Even a failed migration may have committed partial SQLite DDL.
                migration_attempted = True
                stage("migrate", lambda: runtime.migrate(manifest["new"]))
            else:
                stage("revision_without_migration", lambda: require(
                    probe(manifest["new"]["code"], config["profile"], "current")
                    == manifest["target_head"], "code_only_revision_changed"))
            for entry in manifest["consumers"]:
                if entry["role"] == "active-pointer":
                    continue
                stage("consumer_" + entry["role"], lambda e=entry: write_preserved(
                    e, e["after"].encode(), e["before_sha256"], lambda: published.append(e)))
            stage("pointer", lambda: atomic_pointer(manifest["active_pointer"],
                                                    manifest["proposed_pointer"], previous))
            pointer_changed = True
            loaded = stage("start_new", lambda: runtime.start(manifest["new"]))
            stage("smoke_new", lambda: runtime.smoke(loaded))
            receipt["status"] = "PASS"
        except BaseException as exc:
            receipt["error"] = str(exc) if isinstance(exc, Refused) else "activation_stage_failed"
            if attempted:
                try:
                    stage("stop_candidate", runtime.cleanup_started)
                    stage("finish_stop_old", runtime.finish_stop)
                    if not migration_attempted:
                        for entry in reversed(published):
                            # Our failed write can be partial: restore exact original bytes.
                            stage("restore_" + entry["role"], lambda e=entry: write_preserved(
                                e, e["before"].encode(), digest(Path(e["path"]).read_bytes())))
                        if pointer_changed or previous.exists():
                            pointer_entry = next(e for e in manifest["consumers"]
                                                 if e["role"] == "active-pointer")
                            stage("restore_pointer", lambda: atomic_pointer(
                                manifest["active_pointer"], manifest["rollback_target"],
                                manifest_path.parent / "active-code.failed.json",
                                pointer_entry["before"].encode()))
                        restored = stage("restart_old", lambda: runtime.start(manifest["old"],
                                                                              fresh=True))
                        stage("smoke_rollback", lambda: runtime.smoke(restored))
                        receipt["rollback"] = "PASS"
                        receipt["rollback_ui_binding"] = restored["ui_binding"]
                    else:
                        receipt["diagnostic"] = (
                            "migration_attempted_services_stopped_owner_recovery_required")
                except BaseException:
                    receipt["rollback"] = "FAIL"
                    receipt["diagnostic"] = "services_require_owner_attention"
            receipt["finished_utc"] = datetime.now(UTC).isoformat()
            create_json(receipt_path, receipt)
            raise Refused(receipt.get("diagnostic", receipt["error"])) from None
        receipt["finished_utc"] = datetime.now(UTC).isoformat()
        create_json(receipt_path, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("sha")
    prep.add_argument("--config", type=Path, required=True)
    prep.add_argument("--ci-run-id", required=True)
    prep.add_argument("--manifest", type=Path, required=True)
    prep.add_argument("--strict", action="store_true")
    act = sub.add_parser("activate")
    act.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args.config, args.sha, args.ci_run_id, args.manifest, args.strict)
        else:
            result = activate(args.manifest)
            print("activation " + result["status"])
    except BaseException as exc:
        error = str(exc) if isinstance(exc, Refused) else "release_tool_failed"
        prefix = "preflight FAIL: " if args.command == "prepare" else "activation FAIL: "
        print(prefix + error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
