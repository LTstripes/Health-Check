"""External synthetic #376 browser fixture, loopback only; no account providers."""

import json
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    runtime = Path(os.environ["HEALTHCHECK_DATA_DIR"]).resolve()
    if runtime.is_relative_to(ROOT) or not runtime.name.startswith("hc376-") or runtime.exists():
        raise ValueError("Use a fresh external hc376-* synthetic directory")
    sys.path.insert(0, str(ROOT / "tests"))
    import uvicorn
    from sqlalchemy import select

    from healthcheck.db.engine import create_sqlite_engine, session_scope
    from healthcheck.db.models import GarminRecordMetric, GarminSourceRecord, GoogleSourceRecord
    from healthcheck.garmin.normalization import garmin_source_identity, normalize_garmin_payload
    from healthcheck.garmin.persistence import GarminPersistenceRepository
    from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
    from healthcheck.web import pages
    from test_dashboard_ui import _ui
    from test_period_brief_ui import seed_overview_v2

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2099, 1, 10, 12, tzinfo=UTC).astimezone(tz)

    pages.datetime = FrozenDatetime
    port = int(os.environ.get("HEALTHCHECK_UI_PORT", "8176"))
    app, _, paths = _ui(runtime, ui_port=port)
    seed_overview_v2(paths)
    engine = create_sqlite_engine(paths)
    with session_scope(engine) as session:
        original, metric = session.execute(
            select(GarminSourceRecord, GarminRecordMetric)
            .join(GarminRecordMetric, GarminRecordMetric.record_id == GarminSourceRecord.id)
            .where(GarminRecordMetric.metric_code == "resting_heart_rate_bpm")
        ).one()
        metric.value_number = 0
        source_id = original.garmin_source_id
        repository = GarminPersistenceRepository(
            session, payload_store=ContentAddressedGarminPayloadStore(paths.root / "artifacts"),
        )
        for day, value in [(5, 58), (9, 62), (10, None)]:
            payload = {"calendarDate": f"2099-01-{day:02}", "restingHeartRate": value}
            repository.persist_result(
                normalize_garmin_payload(payload, stream="daily_health",
                                         source_identity=garmin_source_identity(
                                             source_kind="provider")),
                payload=payload, received_at=datetime(2099, 1, 10, tzinfo=UTC),
            )
        session.flush()
        conflict, conflict_metric = session.execute(
            select(GarminSourceRecord, GarminRecordMetric)
            .join(GarminRecordMetric, GarminRecordMetric.record_id == GarminSourceRecord.id)
            .where(GarminRecordMetric.metric_code == "resting_heart_rate_bpm",
                   GarminSourceRecord.source_local_date == date(2099, 1, 9))
        ).one()
        for index in range(256):
            values = {column.name: getattr(conflict, column.name)
                      for column in conflict.__table__.columns
                      if column.name not in {"id", "idempotency_key"}}
            values["source_local_date"] = date(2099, 1, 1) if index else date(2099, 1, 9)
            duplicate = GarminSourceRecord(**values, idempotency_key=f"synthetic-cap-{index}")
            session.add(duplicate)
            session.flush()
            values = {column.name: getattr(conflict_metric, column.name)
                      for column in conflict_metric.__table__.columns
                      if column.name not in {"id", "record_id"}}
            session.add(GarminRecordMetric(**values, record_id=duplicate.id))
        # 255 rows on Jan 1 plus two sentinels make an incomplete group.
        for extra in range(2):
            values = {column.name: getattr(conflict, column.name)
                      for column in conflict.__table__.columns
                      if column.name not in {"id", "idempotency_key"}}
            values["source_local_date"] = date(2099, 1, 1)
            duplicate = GarminSourceRecord(**values, idempotency_key=f"synthetic-extra-{extra}")
            session.add(duplicate)
            session.flush()
            values = {column.name: getattr(conflict_metric, column.name)
                      for column in conflict_metric.__table__.columns
                      if column.name not in {"id", "record_id"}}
            session.add(GarminRecordMetric(**values, record_id=duplicate.id))
        google_id = session.scalar(select(GoogleSourceRecord.google_source_id).where(
            GoogleSourceRecord.stream_code == "daily_resting_hr"))
    engine.dispose()
    runtime.mkdir(exist_ok=True)
    (runtime / "fixture.json").write_text(json.dumps({
        "garmin_source_id": source_id, "google_rhr_source_id": google_id,
        "evaluation_local_date": "2099-01-10",
    }), encoding="utf-8")
    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
