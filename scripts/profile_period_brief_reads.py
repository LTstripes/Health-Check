"""Synthetic-only, same-process baseline/candidate harness for issue #283.

Run with an explicit NEW external --runtime directory. No provider calls.
Frozen baseline query bodies are the only substitutions; all downstream
assembly, snapshots, analytics and packet hashing use the production services.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sqlite3
import statistics
import sys
from collections import defaultdict
from contextlib import ExitStack, contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from sqlalchemy import event, func, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

from scripts import period_brief_read_reference as reference  # noqa: E402

from healthcheck import source_freshness_read as freshness  # noqa: E402
from healthcheck.analytics import garmin_baselines as baselines  # noqa: E402
from healthcheck.analytics.sleep_agreement import PersistedSleepAgreementService  # noqa: E402
from healthcheck.analytics.sleep_agreement_report import SleepAgreementReportService  # noqa: E402
from healthcheck.analytics.sleep_metrics import read_persisted_sleep_metric_projection  # noqa: E402
from healthcheck.analytics.sleep_pairing import SleepPairingQuery  # noqa: E402
from healthcheck.config import Settings  # noqa: E402
from healthcheck.db.engine import (  # noqa: E402
    create_session_factory,
    create_sqlite_engine,
    migrate_database,
)
from healthcheck.db.models import (  # noqa: E402
    CoverageInterval,
    GarminRawPayload,
    GarminRecordMetric,
    GarminSource,
    GarminSourceRecord,
    SyncRun,
)
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore  # noqa: E402
from healthcheck.runtime import prepare_runtime  # noqa: E402
from healthcheck.web.period_brief_query import PeriodBriefService  # noqa: E402
from test_garmin_baselines_trends import _persist, _stress_payload  # noqa: E402
from test_sleep_account_cohort import COHORT, _garmin, _google  # noqa: E402

START = date(2099, 1, 2)
END = date(2099, 1, 29)
EVALUATED = datetime(2099, 1, 30, 12, tzinfo=UTC)
BASE_SHA = "9eb5b82221c99d96e7681f26c4f41e637186fe47"


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return EVALUATED.astimezone(tz)


def seed(paths, engine, *, records: int, intervals: int, runs: int):
    """Real normalized/published evidence plus bulk, FK-valid historical noise."""
    factory = create_session_factory(engine)
    with factory() as session:
        store = ContentAddressedGarminPayloadStore(paths.root / "garmin-artifacts")
        for offset in range(28):
            wake = START + timedelta(days=offset)
            _garmin(session, paths, wake)
            _google(session, paths, wake)
            payload = _stress_payload(wake.isoformat(), avg=20 + offset % 7)
            payload["device"] = {"attributed": False}
            _persist(session, store, payload)
        session.flush()
        projection = read_persisted_sleep_metric_projection(
            session, SleepPairingQuery(cohort=COHORT, start_date=START, end_date=END)
        )
        assert len(projection.pairs) == 28
        PersistedSleepAgreementService(session).persist(projection, scope_key="synthetic:283")
        session.commit()
        source = session.scalar(select(GarminSource))
        raw = session.scalar(
            select(GarminRawPayload).where(
                GarminRawPayload.garmin_source_id == source.id,
                GarminRawPayload.stream_code == "intraday",
            )
        )
        assert raw is not None
        source_id, provider_id, raw_id = source.id, source.provider_id, raw.id

    surfaces = ("heart_rate", "stress", "body_battery", "spo2", "respiration")
    # Shared schema/indexes; no ANALYZE or new indexes in either arm.
    with engine.begin() as connection:
        for left in range(0, records, 5000):
            rows, metrics = [], []
            for i in range(left, min(left + 5000, records)):
                day = END - timedelta(days=(i // 5) % 400)
                rid = f"synthetic-r-{i:09d}"
                rows.append(
                    dict(
                        id=rid,
                        garmin_source_id=source_id,
                        raw_payload_id=raw_id,
                        stream_code="intraday",
                        surface_code=surfaces[i % 5],
                        idempotency_key=rid,
                        temporal_precision="instant",
                        source_local_date=day,
                        source_timestamp_utc=datetime.combine(day, datetime.min.time(), UTC)
                        + timedelta(seconds=i % 86400),
                        record_status="ok",
                        normalization_contract_version="synthetic-283",
                        unknown_fields_json=json.dumps({"synthetic_padding": "x" * 200}),
                    )
                )
                metrics.append(
                    dict(
                        id=f"synthetic-m-{i:09d}",
                        record_id=rid,
                        capability_code="stress",
                        metric_code="stress_sample",
                        field_path="synthetic",
                        state="value",
                        value_number=40,
                        unit="score",
                        source_device_attributed=False,
                    )
                )
            connection.execute(GarminSourceRecord.__table__.insert(), rows)
            connection.execute(GarminRecordMetric.__table__.insert(), metrics)
        for left in range(0, intervals, 5000):
            rows = []
            for i in range(left, min(left + 5000, intervals)):
                # Many years of history, with exact inclusive date boundaries.
                stamp = datetime(2099, 1, 29, tzinfo=UTC) - timedelta(days=i % 10000)
                rows.append(
                    dict(
                        id=f"synthetic-c-{i:09d}",
                        provider_id=provider_id,
                        stream_code="intraday",
                        metric_code=surfaces[i % 5],
                        interval_start=stamp,
                        interval_end=stamp + timedelta(days=1),
                        resolution="day",
                        status=("present", "unknown", "unavailable")[i % 3],
                        observed_count=1,
                        expected_count=None,
                        calculation_rule_version="synthetic-283",
                    )
                )
            connection.execute(CoverageInterval.__table__.insert(), rows)
        rows = []
        for i in range(runs):
            stamp = EVALUATED - timedelta(hours=i)
            rows.append(
                dict(
                    id=f"synthetic-run-{i:09d}",
                    provider_id=provider_id,
                    stream_code="garmin_incremental",
                    status=("succeeded", "partial", "failed")[i % 3],
                    started_at=stamp,
                    completed_at=stamp + timedelta(minutes=1),
                    item_count=1,
                )
            )
        if rows:
            connection.execute(SyncRun.__table__.insert(), rows)
    return source_id, provider_id


@contextmanager
def query_arm(arm):
    with ExitStack() as stack:
        if arm == "before":
            stack.enter_context(
                patch.object(
                    freshness,
                    "_garmin_series_evidence_query",
                    reference._garmin_series_evidence_query,
                )
            )
            stack.enter_context(
                patch.object(
                    SleepAgreementReportService,
                    "_source_data_quality",
                    reference._source_data_quality,
                )
            )
            stack.enter_context(
                patch.object(baselines, "_candidate_statement", reference._candidate_statement)
            )
        stack.enter_context(patch("healthcheck.web.period_brief_query.datetime", FixedClock))
        yield


def measure(engine, settings, source_id, provider_id, arm, *, capture_plans=False):
    phase_times, sql_times, sql_counts = defaultdict(float), defaultdict(float), defaultdict(int)
    captures = {}
    phase = "other"
    sql_started = 0.0

    def before_sql(_conn, _cursor, statement, parameters, _context, _many):
        nonlocal sql_started
        sql_started = perf_counter()
        if capture_plans and phase != "other" and statement.lstrip().startswith("SELECT"):
            captures.setdefault((phase, statement), parameters)

    def after_sql(_conn, _cursor, _statement, _parameters, _context, _many):
        sql_times[phase] += perf_counter() - sql_started
        sql_counts[phase] += 1

    def timed(name, function):
        def call(*args, **kwargs):
            nonlocal phase
            previous, phase = phase, name
            started = perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                phase_times[name] += perf_counter() - started
                phase = previous

        return call

    event.listen(engine, "before_cursor_execute", before_sql)
    event.listen(engine, "after_cursor_execute", after_sql)
    try:
        with query_arm(arm), ExitStack() as stack:
            for target, attribute, name in (
                (freshness, "_garmin_series_evidence_query", "freshness"),
                (SleepAgreementReportService, "_source_data_quality", "quality"),
                (baselines, "compute_garmin_scalar_series", "baseline"),
            ):
                stack.enter_context(
                    patch.object(target, attribute, timed(name, getattr(target, attribute)))
                )
            with create_session_factory(engine)() as session:
                started = perf_counter()
                packet = PeriodBriefService(session, settings).build(
                    start_date=START, end_date=END, garmin_source_id=source_id
                )
                total = perf_counter() - started
                # Direct candidate read excludes downstream assembly from timing.
                started = perf_counter()
                rows = session.execute(
                    baselines._candidate_statement(
                        baselines.GarminSeriesQuery("stress_daily_average", START, END, source_id)
                    ).limit(baselines.MAX_SERIES_SELECTED_POINTS + 1)
                ).all()
                candidate_time = perf_counter() - started
                ids = [(metric.id, record.id) for metric, record in rows]
    finally:
        event.remove(engine, "before_cursor_execute", before_sql)
        event.remove(engine, "after_cursor_execute", after_sql)

    plans = []
    if capture_plans:
        with engine.connect() as connection:
            for (name, statement), params in captures.items():
                # Candidate selection and the two other hot-path queries only;
                # analytic provenance lookups remain unchanged.
                if name == "baseline" and "JOIN garmin_source_records" not in statement:
                    continue
                plan = connection.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, params).all()
                plans.append(
                    dict(
                        phase=name,
                        sql=statement,
                        parameters=params,
                        plan=[list(row) for row in plan],
                    )
                )
    return dict(
        arm=arm,
        total_seconds=total,
        phase_seconds=dict(phase_times),
        sql_execute_seconds=dict(sql_times),
        sql_counts=dict(sql_counts),
        baseline_candidate_seconds=candidate_time,
        candidate_ids=ids,
        packet=packet,
        plans=plans,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--records", type=int, default=2_000_000)
    parser.add_argument("--intervals", type=int, default=200_000)
    parser.add_argument("--runs", type=int, default=5_000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    if runtime.is_relative_to(ROOT) or not runtime.name.startswith("hc-283-synthetic-"):
        parser.error("runtime must be an external hc-283-synthetic-* directory")
    if args.repeats < 3 or min(args.records, args.intervals, args.runs) < 0:
        parser.error("at least three samples and nonnegative row counts required")
    settings = Settings(data_dir=runtime)
    paths = prepare_runtime(settings)
    if args.reuse:
        manifest = json.loads((runtime / "synthetic-manifest.json").read_text())
        if manifest["generator_sha256"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
            parser.error("reuse requires this exact synthetic generator")
        source_id, provider_id = manifest["source_id"], manifest["provider_id"]
        engine = create_sqlite_engine(paths)
    else:
        if paths.database.exists():
            parser.error("refusing to seed an existing database")
        migrate_database(paths)
        engine = create_sqlite_engine(paths)
        print("Seeding synthetic profile", flush=True)
        source_id, provider_id = seed(
            paths, engine, records=args.records, intervals=args.intervals, runs=args.runs
        )
        manifest = dict(
            generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            source_id=source_id,
            provider_id=provider_id,
        )
        (runtime / "synthetic-manifest.json").write_text(json.dumps(manifest))
    try:
        with engine.connect() as connection:
            counts = {
                model.__tablename__: connection.scalar(select(func.count()).select_from(model))
                for model in (GarminSourceRecord, GarminRecordMetric, CoverageInterval, SyncRun)
            }
            schema = connection.exec_driver_sql(
                "SELECT type, name, sql FROM sqlite_master "
                "WHERE sql IS NOT NULL ORDER BY type, name"
            ).all()
        schema_hash = hashlib.sha256(json.dumps([list(row) for row in schema]).encode()).hexdigest()
        warmups = []
        for arm in ("before", "after"):
            sample = measure(engine, settings, source_id, provider_id, arm)
            warmups.append(sample["total_seconds"])
            print(f"Warmup {arm}: {sample['total_seconds']:.3f}s", flush=True)
        samples = []
        expected_packet, expected_ids = None, None
        for repeat in range(args.repeats):
            for arm in ("before", "after") if repeat % 2 == 0 else ("after", "before"):
                sample = measure(
                    engine, settings, source_id, provider_id, arm, capture_plans=repeat == 0
                )
                if expected_packet is None:
                    expected_packet, expected_ids = sample["packet"], sample["candidate_ids"]
                assert sample.pop("packet") == expected_packet, "packet fields/hash changed"
                assert sample.pop("candidate_ids") == expected_ids, "baseline candidates changed"
                samples.append(sample)
                print(
                    f"Sample {repeat + 1} {arm}: {sample['total_seconds']:.3f}s "
                    f"phases={sample['phase_seconds']}",
                    flush=True,
                )
        medians = {}
        for arm in ("before", "after"):
            selected = [row for row in samples if row["arm"] == arm]
            medians[arm] = dict(
                total_seconds=statistics.median(row["total_seconds"] for row in selected),
                phase_seconds={
                    name: statistics.median(row["phase_seconds"][name] for row in selected)
                    for name in ("freshness", "quality", "baseline")
                },
                baseline_candidate_seconds=statistics.median(
                    row["baseline_candidate_seconds"] for row in selected
                ),
            )
        result = dict(
            baseline_sha=BASE_SHA,
            python=platform.python_version(),
            sqlite=sqlite3.sqlite_version,
            counts=counts,
            database_bytes=paths.database.stat().st_size,
            schema_sha256=schema_hash,
            period=[START.isoformat(), END.isoformat()],
            evaluated_at=EVALUATED.isoformat(),
            generator_sha256=manifest["generator_sha256"],
            warmups_seconds=warmups,
            repeats=args.repeats,
            medians=medians,
            samples=samples,
            equivalence=dict(
                full_packet_equal=True,
                baseline_candidate_ids_equal=True,
                packet_result_hash=expected_packet["result_hash"],
            ),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, default=str) + "\n")
        print(json.dumps(medians, indent=2), flush=True)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
