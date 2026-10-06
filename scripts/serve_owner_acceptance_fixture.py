"""Disposable, loopback-only Stage-7 fixture; never used by production.

Set HEALTHCHECK_DATA_DIR before invoking. Use a fresh external hc189s7-* root.
The populated fixture reuses focused-test seeds and an explicit synthetic
Agreement report. Page/API handlers, templates and scripts are production code.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import ExitStack
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--empty", action="store_true")
    mode.add_argument("--unavailable", action="store_true")
    mode.add_argument("--read-errors", action="store_true")
    args = parser.parse_args()
    runtime = Path(os.environ["HEALTHCHECK_DATA_DIR"]).resolve()
    if runtime.is_relative_to(ROOT) or not runtime.name.startswith("hc189s7-"):
        parser.error("runtime must be an external hc189s7-* directory")
    if runtime.exists():
        parser.error("runtime must be fresh; existing stores are never reused")

    # Environment is resolved before ui_app's module-level application import.
    os.environ["HEALTHCHECK_UI_PORT"] = str(args.port)
    sys.path.insert(0, str(ROOT / "tests"))
    import uvicorn
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import SQLAlchemyError

    from healthcheck.config import Settings
    from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
    from healthcheck.garmin.normalization import garmin_source_identity, normalize_garmin_payload
    from healthcheck.garmin.persistence import GarminPersistenceRepository
    from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
    from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
    from healthcheck.ingestion.photo.synthetic import encode_synthetic_png, weigh_in_payload
    from healthcheck.runtime import prepare_runtime
    from healthcheck.web.ui_app import create_ui_app
    from test_activity_owner_ui import seed_activity
    from test_dashboard_ui import _confirm_all_pending
    from test_google_daily_vitals import seed_google_daily_vitals
    from test_sleep_owner_ui import agreement_fixture

    settings = Settings(data_dir=runtime, ui_port=args.port, weight_goal_kg=76.0)
    paths = prepare_runtime(settings)
    if not args.unavailable:
        migrate_database(paths)
    app, _ = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())
    if not args.empty and not args.unavailable:
        seed_activity(paths)
        seed_google_daily_vitals(paths)
        engine = create_sqlite_engine(paths)
        try:
            with session_scope(engine) as session:
                payload = json.loads((ROOT / "tests/fixtures/garmin/sleep.json").read_text())[
                    "payload"
                ]
                normalized = normalize_garmin_payload(
                    payload,
                    stream="sleep",
                    source_identity=garmin_source_identity(source_kind="provider"),
                )
                GarminPersistenceRepository(
                    session, payload_store=ContentAddressedGarminPayloadStore(runtime / "artifacts")
                ).persist_result(
                    normalized, payload=payload, received_at=datetime(2099, 1, 3, tzinfo=UTC)
                )
        finally:
            engine.dispose()
        with TestClient(
            app,
            base_url=f"http://127.0.0.1:{args.port}",
            headers={"Origin": f"http://127.0.0.1:{args.port}"},
        ) as client:
            for index, confirmed in enumerate((True, False)):
                png = encode_synthetic_png(
                    weigh_in_payload(
                        source_local_date=date(2026, 3, 4 + index),
                        weight_kg=81.2,
                        body_fat_pct=24.4,
                    )
                )
                response = client.post(
                    "/api/imports/photos",
                    files=[("files", (f"synthetic-{index}.png", png, "image/png"))],
                )
                assert response.status_code == 200
                if confirmed:
                    _confirm_all_pending(client, response.json()["id"])

    (runtime / "synthetic-manifest.json").write_text(
        json.dumps(
            {
                "fixture": "owner-acceptance-stage7",
                "empty": args.empty,
                "unavailable": args.unavailable,
                "read_errors": args.read_errors,
                "agreement": "explicit test report" if not args.empty else "real empty store",
            }
        )
    )
    with ExitStack() as stack:
        if args.read_errors:
            for method in (
                "WeightQueryService.dashboard",
                "GarminQueryService.dashboard",
                "GarminQueryService.scalar_series",
                "PeriodBriefService.build_with_render",
                "SleepAgreementReportService.report",
                "PhotoImportService.list_batches",
            ):
                stack.enter_context(
                    patch(
                        "healthcheck.web.pages." + method,
                        side_effect=SQLAlchemyError("synthetic Stage-7 read failure"),
                    )
                )
        elif not args.empty and not args.unavailable:
            stack.enter_context(
                patch(
                    "healthcheck.analytics.sleep_agreement_report.SleepAgreementReportService.report",
                    return_value=agreement_fixture(),
                )
            )
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
