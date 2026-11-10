"""Stable operator entry points. Resolve once, then keep that release until exit.

Install this file, release.py and probe.py together in a stable Ops location.
The bootstrap Python needs only the standard library; work uses the release venv.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

if __package__:
    from . import release
else:
    # -I deliberately excludes the script directory from the import path.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import release

INVALID_POINTER = 2
FAILED_WORK = 3
STREAMS = ("sleep", "hrv", "daily_hrv", "daily_resting_hr", "spo2", "daily_spo2",
           "respiratory_rate_sleep", "daily_respiratory_rate")


def resolve_active(config):
    """Read the pointer exactly once; validate identities without profile writes."""
    try:
        root = release.absolute(config["releases_root"])
        profile = release.absolute(config["profile"])
        pointer = release.read_json(release.absolute(config["active_pointer"]))
        code = release.absolute(pointer["code"])
        sha = pointer["sha"]
        release.require(code != root and code.is_relative_to(root) and code.is_dir(),
                        "code_outside_releases_root")
        release.require(not profile.is_relative_to(root) and not root.is_relative_to(profile),
                        "profile_release_overlap")
        release.require(pointer["profile"] == str(profile) and profile.is_dir(),
                        "pointer_profile_mismatch")
        release.require(release.SHA.fullmatch(sha) is not None
                        and release.git(code, "rev-parse", "HEAD") == sha,
                        "pointer_sha_mismatch")
        python = release.absolute(release.python(code))
        release.require(python.is_relative_to(code), "python_outside_release")
        ui = release.absolute(pointer["ui_binding"])
        mcp = release.absolute(pointer["mcp_binding"])
        schema = pointer["schema"]
        release.require(isinstance(schema, str) and bool(schema), "invalid_schema")
        release.check_ui(ui, code, sha, profile, schema, config.get("ui_port", 8120))
        release.check_mcp(mcp, code, profile, schema)
        return {"code": str(code), "python": str(python), "sha": sha,
                "profile": str(profile), "schema": schema,
                "ui_binding": str(ui), "mcp_binding": str(mcp)}
    except (release.Refused, OSError, ValueError, TypeError, KeyError, AttributeError):
        raise release.Refused("active_pointer_invalid") from None


def run_work(active, arguments, *, log=None, stdout_log=None, stderr_log=None):
    """No timeout for long refreshes/backups; never persist unfiltered output."""
    env = dict(os.environ, HEALTHCHECK_DATA_DIR=active["profile"],
               HEALTHCHECK_RELEASE_CODE=active["code"], HEALTHCHECK_RELEASE_SHA=active["sha"])
    result = subprocess.run([active["python"], "-I", "-B", *arguments],
                            cwd=active["code"], env=env, capture_output=True,
                            creationflags=0x08000000 if os.name == "nt" else 0)
    # Check BOTH streams before writing either stream or creating a log.
    output = release.secret_free(result.stdout + result.stderr)
    if log is not None:
        log.parent.mkdir(exist_ok=True)
        with log.open("xb") as stream:
            stream.write(output)
    for path, data in ((stdout_log, result.stdout), (stderr_log, result.stderr)):
        if path is not None:
            path.write_bytes(data)
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    return result.returncode


def run_owner_refresh(active, config):
    arguments = ["-m", "healthcheck.cli", "owner-refresh", "--data-dir", active["profile"],
                 "--trailing-window-days", "7", "--include-google-steps", "--google-steps-catchup"]
    for stream in STREAMS:
        arguments += ["--stream", stream]
    if Path(config["google_hr_flag"]).is_file():
        arguments += ["--stream", "heart_rate"]
    run = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex
    log = Path(active["profile"]) / "logs" / ("owner-refresh-" + run + ".log")
    # owner-refresh retains its own external-runtime operation lock.
    return run_work(active, arguments, log=log)


def run_weekly_backup(active, config):
    script = release.absolute(config["weekly_backup_script"])
    release.require(script.is_file(), "weekly_backup_script_missing")
    # Preserve the installed weekly runner's nonblocking duplicate-backup guard.
    try:
        with release.autostart_lock(script.with_suffix(".lock"),
                                    "Global\\HONORHealthDataOnlyBackup"):
            return run_work(
                active, [str(script), "--no-restore-rehearsal"],
                stdout_log=script.parent / "health-weekly-latest.stdout.private.log",
                stderr_log=script.parent / "health-weekly-latest.stderr.private.log")
    except BlockingIOError:
        print("SKIP: existing Health data-only backup")
        return 0
    except release.Refused as exc:
        if str(exc) != "autostart_busy":
            raise
        print("SKIP: existing Health data-only backup")
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("resolve-active", "run-owner-refresh",
                                          "run-weekly-backup"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = release.read_json(args.config)
        active = resolve_active(config)
    except (release.Refused, OSError, ValueError, TypeError):
        print("active_pointer_invalid", file=sys.stderr)
        return INVALID_POINTER
    try:
        if args.action == "resolve-active" or args.check_only:
            # No token field is copied from config, pointer or environment.
            print(release.json_bytes(active).decode(), end="")
            return 0
        if args.action == "run-owner-refresh":
            return run_owner_refresh(active, config)
        return run_weekly_backup(active, config)
    except (release.Refused, OSError, ValueError, TypeError, KeyError):
        print("active_work_failed", file=sys.stderr)
        return FAILED_WORK


if __name__ == "__main__":
    sys.exit(main())
