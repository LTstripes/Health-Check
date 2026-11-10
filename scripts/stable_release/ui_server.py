"""Pinned UI runner used by activation and the existing autostart interface."""

import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import ProxyHandler, build_opener


def launch_ui(binding_path):
    """Detach with null output handles, including when autostart is transcribed."""
    binding_path = Path(binding_path).resolve()
    binding = json.loads(binding_path.read_text(encoding="utf-8-sig"))
    child = subprocess.Popen(
        [sys.executable, "-I", "-B", str(Path(__file__).resolve()), str(binding_path)],
        cwd=binding["code"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=0x08000000 if os.name == "nt" else 0)
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + 45
    try:
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise ValueError("UI startup failed")
            try:
                with opener.open(f"http://127.0.0.1:{binding['port']}/healthz", timeout=2) as resp:
                    health = json.load(resp)
                if (health.get("status") == "ok" and health.get("sha") == binding["sha"]
                        and health.get("run_id") == binding["run_id"]):
                    print("BOUND_UI_READY " + binding["run_id"])
                    return
            except (OSError, ValueError):
                pass
            time.sleep(.25)
        raise ValueError("UI readiness failed")
    except BaseException:
        # Stop only this uniquely bound run, including if it starts after timeout.
        stop = binding_path.parent / binding["stop_file"]
        with stop.open("x", encoding="utf-8") as stream:
            stream.write(binding["run_id"])
        raise


def main():
    binding_path = Path(sys.argv[1]).resolve()
    binding = json.loads(binding_path.read_text(encoding="utf-8-sig"))
    code, profile = Path(binding["code"]).resolve(), Path(binding["profile"]).resolve()
    os.environ["HEALTHCHECK_DATA_DIR"] = str(profile)
    os.environ["HEALTHCHECK_INGEST_ENABLED"] = "false"
    # The UI has no use for the separate gateway credential.
    os.environ.pop("HEALTHCHECK_MCP_GATEWAY_TOKEN", None)
    import uvicorn

    import healthcheck
    from healthcheck.config import Settings
    from healthcheck.web.ui_app import create_ui_app

    if Path(sys.prefix).resolve() != code / ".venv":
        raise ValueError("interpreter mismatch")
    if not Path(healthcheck.__file__).resolve().is_relative_to(code / "src"):
        raise ValueError("package mismatch")
    head = subprocess.check_output(["git", "-C", str(code), "rev-parse", "HEAD"],
                                   creationflags=0x08000000 if os.name == "nt" else 0)
    if head.decode().strip() != binding["sha"]:
        raise ValueError("HEAD mismatch")
    probe = Path(__file__).with_name("probe.py")
    revision = subprocess.check_output([sys.executable, "-I", "-B", str(probe), "current",
                                        str(code), str(profile)])
    if json.loads(revision) != binding["schema"]:
        raise ValueError("revision mismatch")
    receipt = binding_path.parent / binding["receipt"]
    stop = binding_path.parent / binding["stop_file"]
    if receipt.exists() or stop.exists():
        raise ValueError("fresh run binding required")
    settings = Settings(data_dir=profile, ui_port=binding["port"], ingest_enabled=False,
                        photo_vision_api_key=None, photo_vision_base_url=None,
                        photo_vision_model=None)
    app, paths = create_ui_app(settings)
    if paths.root != profile:
        raise ValueError("profile mismatch")
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/healthz"]
    identity = {"status": "ok", "run_id": binding["run_id"], "sha": binding["sha"],
                "pid": os.getpid(), "profile": str(profile), "code": str(code)}

    @app.get("/healthz")
    def healthz():
        return identity

    with receipt.open("x", encoding="utf-8") as stream:
        json.dump(dict(identity, observed_utc=datetime.now(UTC).isoformat()), stream)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=binding["port"],
                                           log_config=None, access_log=False))

    def watch():
        while not server.should_exit:
            if stop.exists() and stop.read_text(encoding="utf-8-sig").strip() == binding["run_id"]:
                server.should_exit = True
            time.sleep(.25)

    threading.Thread(target=watch, daemon=True).start()
    server.run()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--launch":
        launch_ui(sys.argv[2])
    else:
        main()
