"""Serve #294 browser checks on a fresh explicit external synthetic runtime only."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    root = args.runtime.resolve()
    repo = Path(__file__).resolve().parents[1]
    if root.is_relative_to(repo) or not root.name.startswith("hc294-context-") or root.exists():
        parser.error("runtime must be a fresh external hc294-context-* directory")
    if not 1024 <= args.port <= 65535:
        parser.error("explicit nonprivileged port required")
    # Set before importing the default UI composition; never resolve a private profile.
    os.environ["HEALTHCHECK_DATA_DIR"] = str(root)
    os.environ["HEALTHCHECK_UI_PORT"] = str(args.port)
    import uvicorn

    from healthcheck.config import Settings
    from healthcheck.db.engine import migrate_database
    from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
    from healthcheck.runtime import prepare_runtime
    from healthcheck.web.ui_app import create_ui_app

    settings = Settings(data_dir=root, ui_port=args.port)
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
