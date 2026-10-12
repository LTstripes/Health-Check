"""Fresh loopback-only synthetic runtime for #379/#378 presentation verification."""

import argparse
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    runtime = args.runtime.resolve()
    if (runtime.exists() or runtime.is_relative_to(repo)
            or not runtime.name.startswith("hc-format-")):
        parser.error("fresh external hc-format-* synthetic runtime required")
    os.environ["HEALTHCHECK_DATA_DIR"] = str(runtime)
    os.environ["HEALTHCHECK_UI_PORT"] = str(args.port)
    sys.path.insert(0, str(repo / "tests"))
    import uvicorn
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from healthcheck.config import Settings
    from healthcheck.context import ContextService, parse_date_only, parse_interval, parse_timestamp
    from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
    from healthcheck.db.models import GarminSourceRecord
    from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
    from healthcheck.runtime import prepare_runtime
    from healthcheck.web.ui_app import create_ui_app
    from test_garmin_observed_steps import ABSENT, materialize
    from test_period_summary import _activity

    settings = Settings(data_dir=runtime, ui_port=args.port)
    paths = prepare_runtime(settings)
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    with session_scope(engine) as session:
        for index, (kind, duration, distance) in enumerate([
            ("tennis", 3901.5, 12345.6), ("tennis_v2", 0.001, 0.001),
            ("cycling", 0, 0), ("tennis", None, None),
        ]):
            outcome = _activity(session, paths, kind=kind, duration=duration,
                                distance=distance, suffix=str(index))
            source_id = outcome.source.id
        steps_outcome, _ = materialize(session, paths_store(paths), date(2099, 1, 2), 17)
        steps_source_id = steps_outcome.source.id
        materialize(session, paths_store(paths), date(2099, 1, 3), 0)
        materialize(session, paths_store(paths), date(2099, 1, 4), ABSENT)
        service = ContextService(session)
        comments = []
        for temporal in [
            parse_date_only("2099-01-02"),
            parse_timestamp("2099-01-02T00:15+14:00", timezone_name="Pacific/Kiritimati"),
            parse_timestamp("2099-01-02T19:30:10.123400+03:00", timezone_name="Europe/Moscow"),
            parse_interval("2026-03-08T01:30-05:00", "2026-03-08T03:30-04:00"),
        ]:
            note = service.add(text="Синтетический комментарий: формат даты и точность.",
                               temporal=temporal)
            service.revise(note.event_id, text="Синтетическое исправление; время сохранено точно.")
            comments.append(note.event_id)
        records = list(session.scalars(select(GarminSourceRecord).where(
            GarminSourceRecord.garmin_source_id == source_id,
            GarminSourceRecord.stream_code == "activity",
        )))
        record_ids = [r.id for r in records]
    engine.dispose()
    candidate = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True).strip():
        raise RuntimeError("browser evidence requires a clean committed candidate")
    identity = {"candidate": candidate, "checkout": str(repo), "pid": os.getpid(),
                "python": sys.executable, "port": args.port, "source_id": source_id,
                "steps_source_id": steps_source_id,
                "records": record_ids, "comments": comments,
                "start": "2099-01-02", "end": "2099-01-08", "runtime": str(runtime)}
    args.identity.write_text(json.dumps(identity, indent=2), encoding="utf-8")
    app, _ = create_ui_app(settings, photo_extractor=FakeImageMeasurementExtractor())
    with TestClient(app, base_url=f"http://127.0.0.1:{args.port}",
                    headers={"Origin": f"http://127.0.0.1:{args.port}"}) as client:
        seed_format_weight(client)
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


def paths_store(paths):
    from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
    return ContentAddressedGarminPayloadStore(paths.root / "steps-artifacts")


def seed_format_weight(client):
    from healthcheck.ingestion.photo.synthetic import encode_synthetic_png, weigh_in_payload
    from test_dashboard_ui import _confirm_all_pending

    for index, value in enumerate([74.8, 74.6, 74.7, 74.4, 74.2]):
        day = date.today() - timedelta(days=7 - index)
        png = encode_synthetic_png(weigh_in_payload(
            source_local_date=day, weight_kg=value, body_fat_pct=24.4,
        ))
        response = client.post("/api/imports/photos",
                               files=[("files", (f"format-{index}.png", png, "image/png"))])
        assert response.status_code == 200
        _confirm_all_pending(client, response.json()["id"])


if __name__ == "__main__":
    main()
