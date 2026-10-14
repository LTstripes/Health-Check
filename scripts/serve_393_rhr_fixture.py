"""External synthetic Overview #393 fixture, loopback only, no provider calls."""

import json
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import FunctionType

ROOT = Path(__file__).resolve().parents[1]


def main():
    runtime = Path(os.environ["HEALTHCHECK_DATA_DIR"]).resolve()
    if runtime.is_relative_to(ROOT) or not runtime.name.startswith("hc393-") or runtime.exists():
        raise ValueError("Use a fresh external hc393-* synthetic directory")
    sys.path.insert(0, str(ROOT / "tests"))
    import uvicorn
    from sqlalchemy import select

    from healthcheck.db.engine import create_sqlite_engine, session_scope
    from healthcheck.db.models import GarminRecordMetric, GarminSourceRecord, GoogleSourceRecord
    from healthcheck.garmin.normalization import garmin_source_identity, normalize_garmin_payload
    from healthcheck.garmin.persistence import GarminPersistenceRepository
    from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
    from healthcheck.web import pages, period_brief_query
    from test_dashboard_ui import _ui
    from test_period_brief_ui import seed_overview_v2

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2099, 1, 10, 12, tzinfo=UTC).astimezone(tz)

    class FrozenDate(date):
        @classmethod
        def today(cls):
            return date(2099, 1, 10)

        @classmethod
        def fromisoformat(cls, value):
            return date.fromisoformat(value)

    pages.datetime = period_brief_query.datetime = FrozenDatetime
    port = int(os.environ.get("HEALTHCHECK_UI_PORT", "8193"))
    app, _, paths = _ui(runtime, ui_port=port)
    pages._brief_period = FunctionType(
        pages._brief_period.__code__, dict(pages._brief_period.__globals__, date=FrozenDate),
    )
    seed_overview_v2(paths)
    engine = create_sqlite_engine(paths)
    with session_scope(engine) as session:
        source_id = session.scalar(select(GarminSourceRecord.garmin_source_id).where(
            GarminSourceRecord.stream_code == "daily_health"))
        repository = GarminPersistenceRepository(
            session, payload_store=ContentAddressedGarminPayloadStore(paths.root / "artifacts"),
        )
        for day, value in [("2098-12-02", 0), ("2099-01-04", 61), ("2099-01-05", 58),
                           ("2099-01-07", 63), ("2099-01-09", 62), ("2099-01-10", None),
                           ("2099-01-20", 60)]:
            if os.environ.get("HEALTHCHECK_RHR_SIGNED_FIXTURE") == "1":
                value = {"2099-01-04": -1, "2099-01-05": -2}.get(day, value)
            payload = {"calendarDate": day, "restingHeartRate": value}
            repository.persist_result(
                normalize_garmin_payload(payload, stream="daily_health",
                                         source_identity=garmin_source_identity(
                                             source_kind="provider")),
                payload=payload, received_at=datetime(2099, 1, 10, tzinfo=UTC),
            )
        session.flush()
        for day, count in [(date(2099, 1, 9), 1), (date(2099, 1, 20), 256)]:
            record, metric = session.execute(select(GarminSourceRecord, GarminRecordMetric)
                .join(GarminRecordMetric, GarminRecordMetric.record_id == GarminSourceRecord.id)
                .where(GarminRecordMetric.metric_code == "resting_heart_rate_bpm",
                       GarminSourceRecord.source_local_date == day)).one()
            for index in range(count):
                values = {c.name: getattr(record, c.name) for c in record.__table__.columns
                          if c.name not in {"id", "idempotency_key"}}
                duplicate = GarminSourceRecord(**values, idempotency_key=f"synthetic-{day}-{index}")
                session.add(duplicate)
                session.flush()
                values = {c.name: getattr(metric, c.name) for c in metric.__table__.columns
                          if c.name not in {"id", "record_id"}}
                session.add(GarminRecordMetric(**values, record_id=duplicate.id))
        google_id = session.scalar(select(GoogleSourceRecord.google_source_id).where(
            GoogleSourceRecord.stream_code == "daily_resting_hr"))
    engine.dispose()
    (runtime / "fixture.json").write_text(json.dumps({
        "garmin_source_id": source_id, "google_rhr_source_id": google_id,
        "evaluation_local_date": "2099-01-10",
    }), encoding="utf-8")
    uvicorn.run(app, host="127.0.0.1", port=port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
