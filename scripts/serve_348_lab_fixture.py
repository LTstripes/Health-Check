"""Fresh external synthetic-only local server for #348 desktop verification."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    profile = args.profile.absolute()
    if profile.exists() or profile.is_relative_to(root) or not profile.name.startswith("hc348-"):
        parser.error("a fresh external hc348-* synthetic profile is required")
    os.environ["HEALTHCHECK_DATA_DIR"] = str(profile)
    sys.path.insert(0, str(root / "tests"))
    import uvicorn

    from healthcheck.config import Settings
    from healthcheck.db.engine import migrate_database
    from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
    from healthcheck.runtime import prepare_runtime
    from healthcheck.web.ui_app import create_ui_app
    from test_lab_intake import PDF, draft, raw

    settings = Settings(data_dir=profile, ui_port=args.port)
    paths = prepare_runtime(settings)
    migrate_database(paths)
    fixture = profile.parent / (profile.name + "-inputs")
    fixture.mkdir()
    (fixture / "synthetic.pdf").write_bytes(PDF)
    (fixture / "synthetic.json").write_bytes(raw(draft()))
    receipt = {
        "pid": os.getpid(),
        "profile": str(profile),
        "source": str(root),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "port": args.port,
        "fixture": str(fixture),
        "synthetic": True,
    }
    (fixture / "server.json").write_text(json.dumps(receipt), encoding="utf-8")
    app, _ = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())
    print(json.dumps(receipt), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
