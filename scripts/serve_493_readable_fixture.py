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
from datetime import UTC, datetime
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

    from healthcheck.config import Settings
    from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
    from healthcheck.db.models import GarminSource
    from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
    from healthcheck.runtime import prepare_runtime
    from healthcheck.web.ui_app import create_ui_app
    from test_activity_owner_ui import seed_activity, seed_activity_comparison_tennis
    from test_period_brief_ui import seed_overview_a_plus
    from test_sleep_timeline_ui import _seed_nights, _seed_normal_google

    settings = Settings(data_dir=runtime, ui_port=args.port, ingest_enabled=False)
    paths = prepare_runtime(settings)
    migrate_database(paths)
    if not args.empty:
        seed_activity(paths)
        seed_activity_comparison_tennis(paths)
        _seed_nights(paths)
        _seed_normal_google(paths)
        seed_overview_a_plus(paths)
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
