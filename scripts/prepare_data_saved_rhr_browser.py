"""Capture production Data HTML/DTOs using only disposable synthetic fixtures."""

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from healthcheck.collection_policy import set_collection_policy  # noqa: E402
from healthcheck.db.engine import create_sqlite_engine, session_scope  # noqa: E402
from healthcheck.db.models import SyncStreamState  # noqa: E402
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore  # noqa: E402
from healthcheck.google.storage import ContentAddressedGooglePayloadStore  # noqa: E402
from healthcheck.ingestion.photo.vision import UnconfiguredImageMeasurementExtractor  # noqa: E402
from test_dashboard_ui import _ui  # noqa: E402
from test_google_daily_vitals import HRV, _daily_record, _persist  # noqa: E402
from test_saved_values import (  # noqa: E402
    DAY,
    GARMIN_IDENTITY,
    NOW,
    GarminSourceRepository,
    GoogleSourceRepository,
    _fitbit_identity,
    _seed,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    repo = Path(__file__).resolve().parents[1]
    if output == repo or repo in output.parents or output.exists():
        parser.error("output must be a new disposable synthetic directory outside the checkout")
    output.mkdir(parents=True)
    app, settings, paths = _ui(output)
    app.state.photo_extractor = UnconfiguredImageMeasurementExtractor()
    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            garmin = GarminSourceRepository(session).get_or_create(GARMIN_IDENTITY)
            google = GoogleSourceRepository(session).get_or_create(_fitbit_identity())
            session.flush()
            _seed((session, ContentAddressedGarminPayloadStore(paths.root / "garmin"),
                   garmin, "resting_heart_rate_bpm"), day=DAY, value=62)
            google_stored = (session, ContentAddressedGooglePayloadStore(paths.root / "google"),
                             google, "daily_resting_heart_rate_bpm")
            record, _ = _seed(google_stored, day=DAY - timedelta(days=3), value=59)
            record.record_status = "partial"
            _, metric = _seed(google_stored, day=DAY, value=70)
            metric.state, metric.value_number = "invalid", None
            # A technical identity with another metric must not gate saved RHR.
            _persist(session, google_stored[1], _daily_record(
                metric_code=HRV, local_date=DAY, value=40,
            ), identity=_fitbit_identity(source_instance_id="synthetic-hrv-only"))
            session.add(SyncStreamState(
                provider_id=garmin.provider_id, stream_code="resting_heart_rate",
                last_attempt_at=NOW, diagnostic_status="reauth_required",
            ))
        set_collection_policy(settings, stream="google:heart_rate", state="off")
        params = {"evaluated_at_utc": NOW.isoformat(), "evaluation_local_date": DAY.isoformat()}
        with TestClient(app, base_url="http://127.0.0.1:8120") as client:
            (output / "imports.html").write_text(client.get("/imports").text, encoding="utf-8")
            for endpoint, name in (("/api/imports/saved-rhr", "saved-rhr.json"),
                                   ("/api/source-freshness", "freshness.json")):
                response = client.get(endpoint, params=params)
                response.raise_for_status()
                (output / name).write_text(json.dumps(response.json(), indent=2), encoding="utf-8")
    finally:
        engine.dispose()
    print(output)


if __name__ == "__main__":
    main()
