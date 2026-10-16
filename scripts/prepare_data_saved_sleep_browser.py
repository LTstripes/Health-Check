"""Capture production Data HTML/DTOs from disposable synthetic sleep fixtures."""

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

import healthcheck.saved_sleep as saved_sleep  # noqa: E402
from healthcheck.db.engine import create_sqlite_engine, session_scope  # noqa: E402
from healthcheck.db.models import (  # noqa: E402
    GarminRecordMetric,
    GarminSourceRecord,
    GoogleSleepRecord,
    GoogleSource,
    GoogleSourceRecord,
)
from healthcheck.google.contracts import GoogleSourceIdentity, GoogleSourceKind  # noqa: E402
from healthcheck.ingestion.photo.vision import UnconfiguredImageMeasurementExtractor  # noqa: E402
from test_dashboard_ui import _ui  # noqa: E402
from test_sleep_metrics import _google_sleep_payload, _persist_garmin, _persist_google  # noqa: E402
from test_sleep_source_view import _persist_identity  # noqa: E402

PARAMS = {"evaluated_at_utc": "2099-01-05T23:00:00Z", "evaluation_local_date": "2099-01-05"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    output = parser.parse_args().output.resolve()
    repo = Path(__file__).resolve().parents[1]
    if output.exists() or output == repo or repo in output.parents:
        parser.error("output must be a new synthetic directory outside the checkout")
    output.mkdir(parents=True)
    app, _, paths = _ui(output)
    app.state.photo_extractor = UnconfiguredImageMeasurementExtractor()
    engine = create_sqlite_engine(paths)

    def capture(client, name, **params):
        response = client.get("/api/imports/saved-sleep", params={**PARAMS, **params})
        response.raise_for_status()
        (output / f"{name}.json").write_text(
            json.dumps(response.json(), indent=2), encoding="utf-8",
        )

    try:
        with session_scope(engine) as session:
            _persist_garmin(session, paths)
            _persist_google(session, paths, payload=_google_sleep_payload(name="older-google"))
            session.scalar(select(GoogleSleepRecord)).wake_date = date(2099, 1, 1)
        with TestClient(app, base_url="http://127.0.0.1:8120") as client:
            (output / "imports.html").write_text(client.get("/imports").text, encoding="utf-8")
            for endpoint, name in (("/api/imports/saved-rhr", "saved-rhr"),
                                   ("/api/source-freshness", "freshness")):
                response = client.get(endpoint, params=PARAMS)
                response.raise_for_status()
                (output / f"{name}.json").write_text(json.dumps(response.json()), encoding="utf-8")
            capture(client, "saved")
            with session_scope(engine) as session:
                for name in ("newer-main-one", "newer-main-two"):
                    _persist_google(session, paths, payload=_google_sleep_payload(name=name))
            capture(client, "conflict")
            old_cap = saved_sleep.MAX_RECORDS
            try:
                saved_sleep.MAX_RECORDS = 1
                capture(client, "cap")
            finally:
                saved_sleep.MAX_RECORDS = old_cap
            with session_scope(engine) as session:
                for record in session.scalars(select(GoogleSourceRecord)):
                    record.projection_status, record.retire_reason = "retired", "synthetic-fixture"
                    record.retired_at = datetime(2099, 1, 5, tzinfo=UTC)
                for row in session.scalars(select(GarminRecordMetric).where(
                    GarminRecordMetric.metric_code == "sleep_duration_seconds",
                )):
                    row.value_number = 0
                session.scalar(select(GarminSourceRecord)).record_status = "partial"
                payload = _google_sleep_payload(name="uncertain-zero")
                payload["dataPoints"][0]["sleep"]["metadata"].pop("main")
                payload["dataPoints"][0]["sleep"]["summary"]["minutesAsleep"] = "0"
                _persist_google(session, paths, payload=payload)
                session.flush()
                for row in session.scalars(select(GoogleSourceRecord).where(
                    GoogleSourceRecord.projection_status == "current",
                )):
                    row.record_status = "partial"
            capture(client, "zero")
            with session_scope(engine) as session:
                _persist_identity(
                    session, paths, _google_sleep_payload(name="second-source"),
                    GoogleSourceIdentity(
                        source_kind=GoogleSourceKind.DATA_SOURCE,
                        source_instance_id="users/me/dataSources/second-synthetic-watch",
                        platform="fitbit",
                    ),
                )
                first = session.scalar(select(GoogleSource).order_by(GoogleSource.id)).id
            capture(client, "ambiguous")
            capture(client, "selected", google_source_id=first)
    finally:
        engine.dispose()
    print(output)


if __name__ == "__main__":
    main()
