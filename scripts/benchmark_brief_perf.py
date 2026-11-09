"""Offline #572 route benchmark; all profiles and output must be in system TEMP.

Run with uv run --locked python scripts/benchmark_brief_perf.py ROOT LABEL.
The first invocation builds deterministic synthetic profiles; later runs reuse them.
"""

from __future__ import annotations

import json
import runpy
import sys
from contextlib import ExitStack
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import median
from tempfile import gettempdir
from time import perf_counter
from unittest.mock import patch

from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import event, func, insert, select

from healthcheck.analytics.sleep_agreement import PersistedSleepAgreementService
from healthcheck.analytics.sleep_metrics import read_persisted_sleep_metric_projection
from healthcheck.analytics.sleep_pairing import SleepPairingQuery
from healthcheck.config import Settings
from healthcheck.db.engine import (
    _alembic_config,
    create_session_factory,
    create_sqlite_engine,
    migrate_database,
)
from healthcheck.db.models import AgreementMetricResult, GoogleSourceRecord
from healthcheck.demo import seed_demo
from healthcheck.runtime import resolve_runtime_paths
from healthcheck.web.ui_app import create_ui_app


def build_large(settings):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    from test_sleep_account_cohort import COHORT, _garmin, _google

    seed_demo(settings)
    paths = resolve_runtime_paths(settings)
    engine = create_sqlite_engine(paths)
    with create_session_factory(engine)() as session:
        for offset in range(300):
            day = date(2025, 1, 1) + timedelta(days=offset)
            _garmin(session, paths, day)
            _google(session, paths, day)
        session.commit()
        projection = read_persisted_sleep_metric_projection(
            session, SleepPairingQuery(cohort=COHORT,
                                      start_date=date(2025, 1, 1),
                                      end_date=date(2025, 10, 27)),
        )
        PersistedSleepAgreementService(session).persist(
            projection, scope_key="synthetic:572:large",
        )
        session.commit()
        template = session.scalar(select(GoogleSourceRecord))
        common = dict(
            google_source_id=template.google_source_id, raw_payload_id=template.raw_payload_id,
            stream_code="heart_rate", query_mode="list", data_source_family=None,
            temporal_precision="instant", record_status="ok", projection_status="current",
            normalization_contract_version="synthetic-572",
        )
        for batch in range(30):
            rows = []
            for offset in range(10000):
                index = batch * 10000 + offset
                stamp = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(minutes=index)
                rid = f"synthetic-572-hr-{index}"
                rows.append(dict(common, id=rid, record_identity_key=rid, idempotency_key=rid,
                                 source_timestamp_utc=stamp, source_local_date=stamp.date()))
            session.execute(insert(GoogleSourceRecord), rows)
        session.commit()
        print("large metrics:", session.scalar(select(func.count()).select_from(
            AgreementMetricResult)), flush=True)
    engine.dispose()


def measure(settings, *, baseline=False):
    paths = resolve_runtime_paths(settings)
    migrate_database(paths)
    if baseline:
        command.downgrade(_alembic_config(paths), "0021_garmin_observation_lookup")
    app, _ = create_ui_app(settings)
    engine = create_sqlite_engine(paths)
    app.state.engine = engine
    statements = []
    plans = []

    @event.listens_for(engine, "before_cursor_execute")
    def trace(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        if ("garmin_source_records" in statement or "google_source_records" in statement
                ) and "max(" in statement.lower() and len(plans) < 30:
            plan = connection.connection.driver_connection.execute(
                "EXPLAIN QUERY PLAN " + statement, parameters,
            ).fetchall()
            plans.append({"sql": statement, "plan": plan})

    samples = []
    with ExitStack() as stack:
        if baseline:
            reference = runpy.run_path(str(
                Path(__file__).with_name("google_freshness_read_reference.py")
            ))["_evidence_query"]
            stack.enter_context(patch(
                "healthcheck.db.repositories.validated_runs", return_value=None,
            ))
            stack.enter_context(patch(
                "healthcheck.source_freshness_read._evidence_query", reference,
            ))
        client = stack.enter_context(TestClient(app, base_url="http://127.0.0.1:8120"))
        for _ in range(6):
            statements.clear()
            start = perf_counter()
            response = client.get("/brief?start_date=2025-10-01&end_date=2025-10-27")
            elapsed = perf_counter() - start
            assert response.status_code == 200, response.text[:1000]
            samples.append({"seconds": elapsed, "sql_count": len(statements)})
    engine.dispose()
    return {"samples": samples, "warm_median_seconds": median(
        sample["seconds"] for sample in samples[1:]), "plans": plans}


def main():
    root, label = Path(sys.argv[1]).resolve(), sys.argv[2]
    if not root.is_relative_to(Path(gettempdir()).resolve()):
        raise ValueError("benchmark root must be under system TEMP")
    root.mkdir(parents=True, exist_ok=True)
    output = {}
    for profile in ("demo", "large"):
        settings = Settings(data_dir=root / profile)
        marker = root / f"{profile}.ready"
        if not marker.exists():
            if profile == "demo":
                seed_demo(settings)
            else:
                build_large(settings)
            marker.write_text("synthetic #572\n", encoding="utf-8")
        output[profile] = measure(settings, baseline=label == "before")
        print(profile, output[profile]["samples"], flush=True)
    (root / f"{label}.json").write_text(json.dumps(output, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
