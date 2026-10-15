"""Loopback-only #357 fixture using ordinary synthetic saved acquisitions."""

import ctypes
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    runtime = Path(os.environ["HEALTHCHECK_DATA_DIR"]).resolve()
    if runtime.is_relative_to(ROOT) or not runtime.name.startswith("hc357-") or runtime.exists():
        raise ValueError("Use a fresh external hc357-* synthetic directory")
    sys.path.insert(0, str(ROOT / "tests"))
    import uvicorn

    from healthcheck.config import Settings
    from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
    from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
    from healthcheck.runtime import prepare_runtime
    from healthcheck.web import pages, period_brief_query
    from test_stress_baseline import NOW, D, acquire

    paths = prepare_runtime(Settings(data_dir=runtime))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    sources = {}
    with create_session_factory(engine)() as session:
        database = (
            paths,
            engine,
            session,
            ContentAddressedGarminPayloadStore(paths.root / "artifacts"),
        )
        for name, n, current in (
            ("above", 21, 2),
            ("equal", 21, 1),
            ("zero", 21, 0),
            ("insufficient", 20, 2),
            ("missing", 21, None),
            ("early", 21, 2),
        ):
            for i in range(n):
                saved = acquire(
                    database,
                    D - timedelta(days=28 - i),
                    n if i == n - 1 else 0,
                    zone=None,
                    account=name,
                )
            if current is not None:
                saved = acquire(
                    database,
                    D,
                    current,
                    zone=None,
                    account=name,
                    at=datetime.combine(D, datetime.min.time(), UTC) if name == "early" else None,
                )
            sources[name] = saved.source.id
    engine.dispose()

    class SyntheticDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2099, 2, 1, tzinfo=UTC).astimezone(tz)

    pages.datetime = period_brief_query.datetime = SyntheticDatetime
    real_period = pages._brief_period

    def synthetic_period(*, preset, start_date, end_date):
        if start_date is None and end_date is None and (preset or "30") in {"7", "30", "90"}:
            key = preset or "30"
            return D - timedelta(days=int(key) - 1), D, key
        return real_period(preset=preset, start_date=start_date, end_date=end_date)

    pages._brief_period = synthetic_period
    # Import only after the explicit external runtime exists; no provider refresh.
    from healthcheck.web.ui_app import create_ui_app

    port = int(os.environ.get("HEALTHCHECK_UI_PORT", "8157"))
    app, _ = create_ui_app(Settings(data_dir=runtime, ui_port=port))
    process_start = None
    if os.name == "nt":
        from ctypes import wintypes

        creation, exit_time, kernel, user = (wintypes.FILETIME() for _ in range(4))
        api = ctypes.windll.kernel32
        api.GetCurrentProcess.restype = wintypes.HANDLE
        api.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        if not api.GetProcessTimes(
            api.GetCurrentProcess(),
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            raise OSError("GetProcessTimes failed")
        ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        process_start = datetime.fromtimestamp(
            (ticks - 116444736000000000) / 10000000, UTC
        ).isoformat()
    files = [
        "src/healthcheck/web/pages.py",
        "src/healthcheck/web/overview_stress.py",
        "src/healthcheck/web/templates/overview_values.html",
        "src/healthcheck/web/templates/overview_stress.html",
        "src/healthcheck/web/static/overview.css",
    ]
    identity = {
        "sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "pid": os.getpid(),
        "process_start_utc": process_start,
        "executable": sys.executable,
        "profile": str(runtime),
        "synthetic": True,
        "endpoint": f"http://127.0.0.1:{port}",
        "evaluation_clock": NOW.isoformat(),
        "selected_date": D.isoformat(),
        "sources": sources,
        "loaded_files_sha256": {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files
        },
    }
    (runtime / "fixture-identity.json").write_text(
        json.dumps(identity, indent=2) + "\n", encoding="utf-8"
    )
    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
