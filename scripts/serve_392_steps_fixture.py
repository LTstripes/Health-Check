"""Synthetic loopback Statistics fixture for #392; no providers or credentials."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    profile = args.profile.absolute()
    if profile.exists() or profile.is_relative_to(root) or not profile.name.startswith("hc392-"):
        parser.error("fresh external hc392-* synthetic profile required")
    os.environ["HEALTHCHECK_DATA_DIR"] = str(profile)
    os.environ["HEALTHCHECK_INGEST_ENABLED"] = "false"
    sys.path.insert(0, str(root / "tests"))
    import uvicorn

    from healthcheck.config import Settings
    from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
    from healthcheck.google.contracts import FAMILY_ALL_SOURCES, INT64_MAX
    from healthcheck.google.storage import ContentAddressedGooglePayloadStore
    from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
    from healthcheck.runtime import prepare_runtime
    from healthcheck.web.ui_app import create_ui_app
    from test_google_steps_countsum import MISSING, civil, payload, persist

    settings = Settings(data_dir=profile, ui_port=args.port, ingest_enabled=False)
    paths = prepare_runtime(settings)
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    with create_session_factory(engine)() as session:
        bundle = (paths, session, ContentAddressedGooglePayloadStore(paths.root / "artifacts"))
        for index, value in enumerate([str(INT64_MAX), "0", MISSING, None, "1.5", "9"]):
            raw = payload(value, start=civil(2 + index), end=civil(3 + index))
            _, got = persist(bundle, raw, epoch=index)
            selected = got.source.id
        persist(bundle, payload("10", start=civil(7), end=civil(8)), epoch=5)
        _, other = persist(bundle, payload("88"), family=FAMILY_ALL_SOURCES)
        alternate = other.source.id
    engine.dispose()
    receipt = dict(
        pid=os.getpid(),
        source=str(root),
        profile=str(profile),
        port=args.port,
        sha=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        diff_sha256=__import__("hashlib")
        .sha256(subprocess.check_output(["git", "diff", "HEAD"], cwd=root))
        .hexdigest(),
        selected=selected,
        alternate=alternate,
        synthetic=True,
    )
    (profile / "browser-binding.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    app, _ = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())
    print(json.dumps(receipt), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
