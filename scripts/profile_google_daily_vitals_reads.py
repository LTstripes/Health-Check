"""Bounded synthetic-only #295 scan/seek comparison; never calls a provider.

Run with a NEW external --runtime and --output. Seeds existing mixed daily-vitals
fixtures plus FK-valid historical noise; no new schema/index or ANALYZE. Compare
full ordered DTOs against the frozen main reader and report timing, SQL count,
approximate SQLite VM work and plans. Timings are not Owner latency evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sqlite3
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--records", type=int, default=200_000)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    if runtime.is_relative_to(ROOT) or runtime.exists() or not runtime.name.startswith("hc295-dv-"):
        parser.error("runtime must be a NEW external hc295-dv-* directory")
    if args.output.resolve().is_relative_to(ROOT):
        parser.error("output must be outside the code checkout")
    if not 0 <= args.records <= 500_000 or not 1 <= args.repeats <= 5:
        parser.error("synthetic work must be 0..500000 records and 1..5 repeats")
    os.environ["HEALTHCHECK_DATA_DIR"] = str(runtime)

    from scripts.google_daily_vitals_read_reference import read_google_daily_vitals_reference
    from sqlalchemy import event, func, select

    from healthcheck.config import Settings
    from healthcheck.db.engine import (
        create_session_factory,
        create_sqlite_engine,
        migrate_database,
    )
    from healthcheck.db.models import GoogleSource, GoogleSourceRecord
    from healthcheck.google.daily_vitals import GOOGLE_DAILY_VITALS, read_google_daily_vitals
    from healthcheck.google.storage import ContentAddressedGooglePayloadStore
    from healthcheck.runtime import prepare_runtime
    from healthcheck.web.read_snapshot import ensure_read_snapshot
    from test_google_daily_vitals import (
        HRV,
        _daily_record,
        _fitbit_identity,
        _persist,
        seed_google_daily_vitals,
    )

    paths = prepare_runtime(Settings(data_dir=runtime))
    migrate_database(paths)
    seed_google_daily_vitals(paths)
    engine = create_sqlite_engine(paths)
    factory = create_session_factory(engine)
    with factory() as session:
        store = ContentAddressedGooglePayloadStore(paths.root / "artifacts")
        for index in range(8):
            identity = f"synthetic-{index}"
            _persist(
                session,
                store,
                _daily_record(
                    metric_code=HRV,
                    local_date=date(2097, 1, 1),
                    value=40,
                    external_record_id=identity,
                ),
                identity=_fitbit_identity(
                    source_instance_id=identity,
                    data_source_id=identity,
                    data_source_name=identity,
                ),
            )
        session.commit()
        templates = []
        for source in session.scalars(select(GoogleSource).order_by(GoogleSource.id)):
            record = session.scalar(
                select(GoogleSourceRecord)
                .where(
                    GoogleSourceRecord.google_source_id == source.id,
                )
                .order_by(GoogleSourceRecord.id)
                .limit(1)
            )
            templates.append(
                {c.name: getattr(record, c.name) for c in GoogleSourceRecord.__table__.columns}
            )
    print(f"Seeding {args.records} historical records across {len(templates)} sources", flush=True)
    with engine.begin() as connection:
        for offset in range(0, args.records, 5000):
            batch = []
            for index in range(offset, min(offset + 5000, args.records)):
                row = dict(templates[index % len(templates)])
                identity = f"synthetic-295-history-{index:08d}"
                row.update(
                    id=identity,
                    record_identity_key=identity,
                    idempotency_key=identity,
                    source_local_date=date(2096, 1, 1) + timedelta(days=(index // 10) % 730),
                    projection_status="current",
                    retired_at=None,
                    retire_reason=None,
                )
                batch.append(row)
            connection.execute(GoogleSourceRecord.__table__.insert(), batch)

    captures = {}
    state = {"arm": None, "queries": 0}

    def count_sql(_conn, _cursor, statement, parameters, _context, _many):
        state["queries"] += 1
        if "FROM google_source_records" in statement:
            captures.setdefault((state["arm"], statement), parameters)

    event.listen(engine, "before_cursor_execute", count_sql)
    samples = []
    expected = {}
    try:
        with factory() as session:
            raw = session.connection().connection.driver_connection
            raw.execute("PRAGMA query_only=ON")
            ensure_read_snapshot(session)
            for days in (7, 30):
                for repetition in range(args.repeats + 1):
                    order = ("before", "after") if repetition % 2 == 0 else ("after", "before")
                    for arm in order:
                        state.update(arm=arm, queries=0)
                        vm = [0]

                        def tick():
                            vm[0] += 1000
                            return 0

                        raw.set_progress_handler(tick, 1000)
                        started = perf_counter()
                        reader = (
                            read_google_daily_vitals_reference
                            if arm == "before"
                            else read_google_daily_vitals
                        )
                        results = [
                            reader(
                                session,
                                metric_code=item.metric_code,
                                start_date=date(2099, 1, 2) - timedelta(days=days - 1),
                                end_date=date(2099, 1, 2),
                            ).as_dict()
                            for item in GOOGLE_DAILY_VITALS
                        ]
                        elapsed = perf_counter() - started
                        raw.set_progress_handler(None, 0)
                        if days not in expected:
                            expected[days] = results
                        assert results == expected[days], "ordered DTO or evidence mismatch"
                        sample = dict(
                            days=days,
                            repetition=repetition,
                            arm=arm,
                            seconds=elapsed,
                            queries=state["queries"],
                            sqlite_vm_steps_approx=vm[0],
                        )
                        samples.append(sample)
                        print(json.dumps(sample), flush=True)
    finally:
        event.remove(engine, "before_cursor_execute", count_sql)
    with engine.connect() as connection:
        plans = [
            dict(
                arm=arm,
                plan=[
                    row[3]
                    for row in connection.exec_driver_sql(
                        "EXPLAIN QUERY PLAN " + statement,
                        parameters,
                    )
                ],
            )
            for (arm, statement), parameters in captures.items()
        ]
        count = connection.scalar(select(func.count()).select_from(GoogleSourceRecord))
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    medians = {
        str(days): {
            arm: statistics.median(
                sample["seconds"]
                for sample in samples
                if sample["days"] == days and sample["arm"] == arm and sample["repetition"] > 0
            )
            for arm in ("before", "after")
        }
        for days in (7, 30)
    }
    result = dict(
        baseline="4d01fe93a49b2204bad83ea34d2685e98b3c6e13",
        python=platform.python_version(),
        sqlite=sqlite3.sqlite_version,
        records=count,
        sources=len(templates),
        database_bytes=paths.database.stat().st_size,
        generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        full_ordered_dto_equivalence=True,
        foreign_keys_valid=True,
        medians=medians,
        samples=samples,
        plans=plans,
        limitations=[
            "synthetic sparse selected window with unrelated historical noise",
            "same-process/snapshot paired samples, no cold OS-cache guarantee",
            "VM work is approximate at 1000-step granularity; instrumentation overhead",
            "reader-only, not full route or real Owner performance",
        ],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    engine.dispose()
    print(json.dumps(medians), flush=True)


if __name__ == "__main__":
    main()
