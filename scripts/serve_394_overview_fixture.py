"""Fresh external synthetic #394 profile, frozen source clock, loopback only."""

import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    runtime = Path(os.environ["HEALTHCHECK_DATA_DIR"]).resolve()
    if runtime.is_relative_to(ROOT) or not runtime.name.startswith("hc394-") or runtime.exists():
        raise ValueError("Use a fresh external hc394-* synthetic directory")
    sys.path.insert(0, str(ROOT / "tests"))
    import uvicorn

    from healthcheck.db.engine import create_sqlite_engine, session_scope
    from healthcheck.garmin.normalization import garmin_source_identity
    from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
    from healthcheck.web import pages
    from test_body_battery_read import seed_battery
    from test_dashboard_ui import _ui
    from test_period_brief_ui import seed_overview_a_plus

    class SyntheticDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2099, 1, 31, 23, tzinfo=UTC).astimezone(tz)

    pages.datetime = SyntheticDatetime
    real_period = pages._brief_period

    def synthetic_period(*, preset, start_date, end_date):
        # Inject only the fixture's "today" for existing preset controls, keeping
        # civil-date/Pydantic types and the production period parser unchanged.
        if preset is not None or start_date is None and end_date is None:
            key = preset or "30"
            if key in {"7", "30", "90"} and start_date is None and end_date is None:
                end = date(2099, 1, 31)
                start = end - timedelta(days=int(key) - 1)
                lower, upper, _ = real_period(preset=None, start_date=start.isoformat(),
                                             end_date=end.isoformat())
                return lower, upper, key
        return real_period(preset=preset, start_date=start_date, end_date=end_date)

    pages._brief_period = synthetic_period
    port = int(os.environ.get("HEALTHCHECK_UI_PORT", "8194"))
    app, _, paths = _ui(runtime, ui_port=port)
    seed_overview_a_plus(paths)
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            store = ContentAddressedGarminPayloadStore(paths.root / "garmin")
            identity = garmin_source_identity(source_kind="provider")
            for day, values in ((31, (90, 10, 20)), (29, (30,)), (25, (0,)),
                                (24, (40,)), (2, (20,))):
                seed_battery(session, store, day=date(2099, 1, day), values=values,
                             identity=identity, scalar=99 if day == 31 else None)
            # Production correction and replay, with the current maximum still 90.
            seed_battery(session, store, values=(90, 10, 20), identity=identity,
                         scalar=99, received=datetime(2099, 2, 1, tzinfo=UTC)
                         + timedelta(minutes=1))
    finally:
        engine.dispose()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    (runtime / "fixture-identity.json").write_text(json.dumps({
        "sha": sha, "pid": os.getpid(), "executable": sys.executable,
        "profile": str(paths.root), "synthetic": True, "endpoint": f"http://127.0.0.1:{port}",
        "evaluation_clock": "2099-01-31T23:00:00+00:00",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "process_start": subprocess.check_output(
            ["ps", "-p", str(os.getpid()), "-o", "lstart="], text=True).strip(),
    }, indent=2) + "\n", encoding="utf-8")
    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
