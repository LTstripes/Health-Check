"""Loopback-only Activity fixture: four independent synthetic 0/1/5/50 sources."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    runtime = Path(os.environ["HEALTHCHECK_DATA_DIR"]).resolve()
    if runtime.is_relative_to(ROOT) or not runtime.name.startswith("hc335-") or runtime.exists():
        parser.error("runtime must be a fresh external hc335-* directory")
    os.environ["HEALTHCHECK_UI_PORT"] = str(args.port)
    sys.path.insert(0, str(ROOT / "tests"))

    import uvicorn

    from healthcheck.config import Settings
    from healthcheck.db.engine import migrate_database
    from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
    from healthcheck.runtime import prepare_runtime
    from healthcheck.web.ui_app import create_ui_app
    from test_activity_owner_ui import seed_activity_journal

    settings = Settings(data_dir=runtime, ui_port=args.port)
    paths = prepare_runtime(settings)
    migrate_database(paths)
    for count in (0, 1, 5, 50):
        seed_activity_journal(paths, count, device_model=f"Synthetic journal {count}")
    app, _ = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
