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
    import json

    import uvicorn

    from healthcheck.config import Settings
    from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
    from healthcheck.garmin.normalization import normalize_garmin_payload
    from healthcheck.garmin.persistence import GarminPersistenceRepository
    from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
    from healthcheck.google.contracts import GoogleSourceIdentity, GoogleSourceKind
    from healthcheck.runtime import prepare_runtime
    from healthcheck.web.ui_app import create_ui_app
    from test_google_daily_vitals import seed_google_daily_vitals
    from test_sleep_metrics import (
        GARMIN_SLEEP_FIXTURE,
        _google_sleep_payload,
        _persist_google,
        _stage,
    )
    from test_sleep_source_view import _persist_account_garmin, _persist_identity

    settings = Settings(data_dir=runtime, ui_port=args.port)
    paths = prepare_runtime(settings)
    if not args.unavailable:
        migrate_database(paths)
    if not args.empty and not args.unavailable:
        seed_google_daily_vitals(paths)
        engine = create_sqlite_engine(paths)
        try:
            with session_scope(engine) as session:
                _persist_account_garmin(session, paths)

                def persist_garmin_night(day, *, seconds, score):
                    wake = date(2099, 1, day)
                    previous = wake - timedelta(days=1)
                    payload = json.loads(GARMIN_SLEEP_FIXTURE.read_text(encoding="utf-8"))
                    payload["device"] = {"attributed": False}
                    dto = payload["payload"]["dailySleepDTO"]
                    dto["calendarDate"] = wake.isoformat()
                    dto["sleepTimeSeconds"] = seconds
                    dto["sleepScores"]["overall"]["value"] = score
                    for level in payload["payload"]["levels"]:
                        for field in ("startTimeGMT", "endTimeGMT"):
                            level[field] = (
                                level[field]
                                .replace("2099-01-01", "{previous}")
                                .replace("2099-01-02", "{wake}")
                                .replace("{previous}", previous.isoformat())
                                .replace("{wake}", wake.isoformat())
                            )
                    GarminPersistenceRepository(
                        session,
                        payload_store=ContentAddressedGarminPayloadStore(
                            paths.root / "garmin-artifacts"
                        ),
                    ).persist_result(
                        normalize_garmin_payload(payload), payload=json.dumps(payload).encode()
                    )

                # Garmin nights 2/3/5/8 leave a visible 6-7 gap for the timeline.
                persist_garmin_night(3, seconds=27000, score=74)
                persist_garmin_night(5, seconds=32400, score=88)
                persist_garmin_night(8, seconds=25200, score=65)

                def persist_day(day, *, name="night", sleep_type="STAGES", status="SUCCEEDED",
                                main=True, nap=False, zero=False, summary_only=False,
                                account_source=None):
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
                    if nap is None:
                        sleep["metadata"].pop("nap")
                    if zero:
                        sleep["summary"]["minutesAsleep"] = "0"
                    if account_source:
                        source = payload["dataPoints"][0]["dataSource"]
                        source["platform"] = "health_connect"
                        source["device"].update(
                            manufacturer="Synthetic", displayName="Synthetic Account Watch"
                        )
                        _persist_identity(session, paths, payload, GoogleSourceIdentity(
                            source_kind=GoogleSourceKind.DATA_SOURCE,
                            source_instance_id=f"users/me/dataSources/{account_source}",
                            platform="health_connect",
                        ))
                    else:
                        _persist_google(session, paths, payload=payload)

                persist_day(2)
                persist_day(4, name="first")
                persist_day(4, name="second")
                persist_day(5, sleep_type="CLASSIC")
                persist_day(6, summary_only=True)
                persist_day(7, zero=True)
                persist_day(8, main=None)
                persist_day(9, nap=True)
                persist_day(10, main=False, nap=None, account_source="synthetic-account")
                persist_day(11, main="unknown", nap="unknown")
                persist_day(12, name="first", account_source="synthetic-source-a")
                persist_day(12, name="second", account_source="synthetic-source-b")
        finally:
            engine.dispose()
    app, _ = create_ui_app(settings)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
