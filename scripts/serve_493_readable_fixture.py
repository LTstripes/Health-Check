"""#493 disposable synthetic persistence fixture, production UI on loopback only.

No private profile or provider integration. A frozen clock makes synthetic 2099
history eligible for the completed-day Overview; no health computation is mocked.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--empty", action="store_true")
    args = parser.parse_args()
    runtime = Path(os.environ["HEALTHCHECK_DATA_DIR"]).resolve()
    if runtime.is_relative_to(ROOT) or not runtime.name.startswith("hc493-") or runtime.exists():
        parser.error("runtime must be a fresh external hc493-* synthetic directory")
    os.environ["HEALTHCHECK_UI_PORT"] = str(args.port)
    sys.path.insert(0, str(ROOT / "tests"))

    import uvicorn
    from sqlalchemy import select

    from healthcheck.analytics.sleep_source_view import read_source_sleep_night
    from healthcheck.config import Settings
    from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
    from healthcheck.db.models import GarminSource
    from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
    from healthcheck.runtime import prepare_runtime
    from healthcheck.web.ui_app import create_ui_app
    from test_activity_owner_ui import seed_activity, seed_activity_comparison_tennis
    from test_period_brief_ui import seed_overview_a_plus
    from test_sleep_metrics import _google_sleep_payload, _persist_google, _stage
    from test_sleep_timeline_ui import _seed_nights, _seed_normal_google

    settings = Settings(data_dir=runtime, ui_port=args.port, ingest_enabled=False)
    paths = prepare_runtime(settings)
    migrate_database(paths)
    if not args.empty:
        seed_activity(paths)
        _seed_nights(paths)
        _seed_normal_google(paths)
        seed_overview_a_plus(paths)
        seed_activity_comparison_tennis(paths)
    selected_source_id = None
    if not args.empty:
        engine = create_sqlite_engine(paths)
        try:
            with session_scope(engine) as session:
                # Explicit fixture identity, not a new production auto-selection rule.
                sources = session.scalars(select(GarminSource).where(
                    GarminSource.source_kind == "provider")).all()
                assert len(sources) == 1
                selected_source_id = sources[0].id
                stages = []
                for start, end, kind in (
                    ("2026-10-24T20:00:00Z", "2026-10-24T21:00:00Z", "AWAKE"),
                    ("2026-10-24T21:00:00Z", "2026-10-25T00:00:00Z", "LIGHT"),
                    ("2026-10-25T00:00:00Z", "2026-10-25T02:00:00Z", "DEEP"),
                    ("2026-10-25T02:00:00Z", "2026-10-25T03:50:00Z", "REM"),
                    ("2026-10-25T03:50:00Z", "2026-10-25T06:00:00Z", "AWAKE"),
                ):
                    stage = _stage(start, end, kind)
                    for endpoint, stamp in (("start", start), ("end", end)):
                        stage[endpoint + "UtcOffset"] = (
                            "7200s" if stamp < "2026-10-25T01:00:00Z" else "3600s")
                    stages.append(stage)
                payload = _google_sleep_payload(
                    name="493-independent-dst", stages=stages, stages_status="SUCCEEDED")
                sleep = payload["dataPoints"][0]["sleep"]
                sleep["interval"] = {
                    "startTime": "2026-10-24T20:00:00Z", "startUtcOffset": "7200s",
                    "endTime": "2026-10-25T06:00:00Z", "endUtcOffset": "3600s",
                    "civilStartTime": {"date": "2026-10-24", "time": "22:00:00"},
                    "civilEndTime": {"date": "2026-10-25", "time": "07:00:00"},
                }
                sleep["summary"].update(minutesInSleepPeriod="600", minutesAsleep="410",
                                        minutesAwake="190", minutesToFallAsleep="60",
                                        minutesAfterWakeUp="130")
                sleep["updateTime"] = "2026-10-25T08:00:00Z"
                _persist_google(session, paths, payload=payload)
                packet = read_source_sleep_night(session, provider="google",
                                                 wake_date=date(2026, 10, 25))
                assert len(packet["sources"]) == 1
                metrics = packet["sources"][0]["summary"]["metrics"]
                assert metrics["sleep_start_at"]["eligible"]
                assert metrics["sleep_end_at"]["eligible"]
                assert metrics["sleep_duration_asleep_seconds"]["value"] == 24600
        finally:
            engine.dispose()
    app, _ = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())

    class FixtureDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2099, 1, 10, 12, tzinfo=UTC).astimezone(tz)

    manifest = {
        "fixture": "493-readable-synthetic-v1", "empty": args.empty,
        "sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "pid": os.getpid(), "port": args.port, "runtime": str(runtime),
        "clock": "pages.datetime.now=2099-01-10T12:00Z; presentation fixture only",
        "provider_calls": False, "private_data": False,
        "explicit_synthetic_garmin_source_id": selected_source_id,
    }
    (runtime / "synthetic-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    with patch("healthcheck.web.pages.datetime", FixtureDatetime):
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
