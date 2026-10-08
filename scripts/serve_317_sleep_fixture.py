"""Loopback #317 fixture over production persistence; external synthetic data only."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--empty", action="store_true")
    mode.add_argument("--unavailable", action="store_true")
    args = parser.parse_args()
    runtime = Path(os.environ["HEALTHCHECK_DATA_DIR"]).resolve()
    if runtime.is_relative_to(ROOT) or not runtime.name.startswith("hc317-") or runtime.exists():
        parser.error("runtime must be a fresh external hc317-* synthetic directory")
    os.environ["HEALTHCHECK_UI_PORT"] = str(args.port)
    sys.path.insert(0, str(ROOT / "tests"))
    import uvicorn

    from healthcheck.config import Settings
    from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
    from healthcheck.runtime import prepare_runtime
    from healthcheck.web.ui_app import create_ui_app
    from test_google_daily_vitals import seed_google_daily_vitals
    from test_sleep_metrics import _google_sleep_payload, _persist_garmin, _persist_google, _stage

    settings = Settings(data_dir=runtime, ui_port=args.port)
    paths = prepare_runtime(settings)
    if not args.unavailable:
        migrate_database(paths)
    if not args.empty and not args.unavailable:
        seed_google_daily_vitals(paths)
        engine = create_sqlite_engine(paths)
        try:
            with session_scope(engine) as session:
                _persist_garmin(session, paths)

                def persist_day(day, *, name="night", sleep_type="STAGES", status="SUCCEEDED",
                                main=True, nap=False, zero=False, summary_only=False):
                    wake = date(2099, 1, day)
                    previous = wake - timedelta(days=1)
                    payload = _google_sleep_payload(
                        name=f"synthetic-{day}-{name}", sleep_type=sleep_type, stages_status=status,
                        stages=[] if summary_only else [
                            _stage(f"{previous}T22:00:00Z", f"{previous}T23:00:00Z", "LIGHT"),
                            _stage(f"{previous}T23:00:00Z", f"{wake}T00:00:00Z", "DEEP"),
                        ],
                        summary_stages=[{"type": "LIGHT", "minutes": "60", "count": "1"}],
                    )
                    sleep = payload["dataPoints"][0]["sleep"]
                    interval = sleep["interval"]
                    interval["startTime"], interval["endTime"] = (
                        f"{previous}T22:00:00Z", f"{wake}T05:00:00Z"
                    )
                    for key in ("civilStartTime", "civilEndTime"):
                        interval[key]["date"] = str(wake)
                    sleep["metadata"].update(main=main, nap=nap)
                    if main is None:
                        sleep["metadata"].pop("main")
                    if zero:
                        sleep["summary"]["minutesAsleep"] = "0"
                    _persist_google(session, paths, payload=payload)

                persist_day(2)
                persist_day(4, name="first")
                persist_day(4, name="second")
                persist_day(5, sleep_type="CLASSIC")
                persist_day(6, summary_only=True)
                persist_day(7, zero=True)
                persist_day(8, main=None)
                persist_day(9, nap=True)
        finally:
            engine.dispose()
    app, _ = create_ui_app(settings)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
