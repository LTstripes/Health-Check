"""Read-only /brief profiler. No migrations, lifespan startup or provider calls.

Example: uv run --locked python scripts/profile_brief.py --data-dir COPY --period 30
Use --generate-synthetic only with a NEW directory under system TEMP.
"""

from __future__ import annotations

import argparse
import cProfile
import json
import math
import re
import sys
from contextlib import ExitStack
from datetime import UTC, date, datetime, timedelta
from functools import wraps
from pathlib import Path
from statistics import median
from tempfile import gettempdir
from time import perf_counter

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, insert, select

from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine
from healthcheck.db.models import GoogleSourceRecord
from healthcheck.demo import seed_demo
from healthcheck.runtime import resolve_runtime_paths
from healthcheck.web.pages import period_brief_page
from healthcheck.web.ui_app import create_ui_app


def normalize_sql(statement):
    """Keep statement shapes, never bound values or SQL string/number literals."""
    statement = re.sub(
        r"'(?:''|[^'])*'|--[^\n]*|/\*.*?\*/",
        lambda match: "?" if match[0].startswith("'") else " ", statement, flags=re.S,
    )
    statement = re.sub(r"\b\d+(?:\.\d+)?\b", "?", statement)
    statement = re.sub(r"\?(?:\s*,\s*\?)+", "?, ...", statement)
    return " ".join(statement.split())


def readonly_engine(database):
    if not database.is_file():
        raise ValueError("existing profile database required")
    # as_uri quotes spaces, #, % and ? in Windows/POSIX paths.
    engine = create_engine(
        f"sqlite+pysqlite:///{database.resolve().as_uri()}?mode=ro&uri=true",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def protect(connection, record):
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA foreign_keys=ON")

    return engine


def generate_synthetic(root, *, records=1_000_000):
    root = root.resolve()
    if (not root.is_relative_to(Path(gettempdir()).resolve())
            or root == Path(gettempdir()).resolve() or root.exists()):
        raise ValueError("synthetic generation requires a new child directory under TEMP")
    settings = Settings(data_dir=root)
    seed_demo(settings)
    engine = create_sqlite_engine(resolve_runtime_paths(settings))
    try:
        with create_session_factory(engine)() as session:
            template = session.scalar(select(GoogleSourceRecord))
            common = dict(
                google_source_id=template.google_source_id, raw_payload_id=template.raw_payload_id,
                query_mode="list", temporal_precision="instant", record_status="ok",
                projection_status="current", normalization_contract_version="synthetic-profiling",
            )
            # Three high-frequency streams distributed over 365 historical days;
            # seed-demo supplies real projection shapes, gaps and separate Garmin.
            streams = ("heart_rate", "spo2", "hrv")
            for start in range(0, records, 5000):
                rows = []
                for index in range(start, min(start + 5000, records)):
                    stamp = datetime(2025, 10, 11, tzinfo=UTC) + timedelta(
                        seconds=index * (365 * 86400 / records))
                    identity = f"synthetic-profile-{index}"
                    rows.append(dict(
                        common, id=identity, record_identity_key=identity, idempotency_key=identity,
                        stream_code=streams[index % len(streams)],
                        source_timestamp_utc=stamp, source_local_date=stamp.date(),
                    ))
                session.execute(insert(GoogleSourceRecord), rows)
            session.commit()
    finally:
        engine.dispose()


def parse_timing(header):
    result = {}
    for metric in header.split(", "):
        name, _, attributes = metric.partition(";")
        if attributes.startswith("dur="):
            result[name] = float(attributes[4:])
        elif attributes.startswith('desc="'):
            result[name] = int(attributes[6:-1])
    return result


def summary(samples):
    return {"median_ms": median(samples),
            "p95_ms": sorted(samples)[math.ceil(len(samples) * .95) - 1]}


def validate_output(root, output):
    if output is not None and output.resolve().is_relative_to(root.resolve()):
        raise ValueError("profiler output must be outside the input profile")


def profile(root, *, period=30, source=None, google_source=None, end=None,
            repeats=20, cprofile=None):
    validate_output(root, cprofile)
    if repeats < 1:
        raise ValueError("at least one warm repeat required")
    settings = Settings(data_dir=root, brief_timing_log=False, ui_mode="loopback",
                        ui_host="127.0.0.1", ui_port=8120,
                        photo_vision_base_url=None, photo_vision_api_key=None)
    paths = resolve_runtime_paths(settings)
    engine = readonly_engine(paths.database)
    with ExitStack() as cleanup:
        cleanup.callback(engine.dispose)
        app, _ = create_ui_app(settings)
        app.state.engine = engine
        cpu = cProfile.Profile() if cprofile else None
        if cpu is not None:
            @wraps(period_brief_page)
            def profiled(*args, **kwargs):
                # Run cProfile in the sync route's worker thread, including rendering.
                return cpu.runcall(period_brief_page, *args, **kwargs)

            app.add_api_route("/brief", profiled, methods=["GET"])
            app.router.routes.insert(0, app.router.routes.pop())
        grouped = {}
        current = None

        def before(conn, cursor, statement, parameters, context, many):
            context._brief_started = perf_counter()

        def after(conn, cursor, statement, parameters, context, many):
            nonlocal current
            elapsed = (perf_counter() - context._brief_started) * 1000
            key = normalize_sql(statement)
            item = grouped.setdefault(key, {"calls": 0, "milliseconds": 0,
                                            "statement": statement, "parameters": parameters})
            item["calls"] += 1
            item["milliseconds"] += elapsed
            current["sql_count"] += 1
            current["sql_ms"] += elapsed

        event.listen(engine, "before_cursor_execute", before)
        event.listen(engine, "after_cursor_execute", after)
        params = {"preset": str(period)}
        if end is not None:
            params = {"start_date": (end - timedelta(days=period - 1)).isoformat(),
                      "end_date": end.isoformat()}
        if source is not None:
            params["garmin_source_id"] = source
        if google_source is not None:
            params["google_rhr_source_id"] = google_source
        samples = []
        try:
            # Do not enter TestClient's migration-capable lifespan. Only GET runs.
            client = TestClient(app, base_url="http://127.0.0.1:8120")
            try:
                for _ in range(repeats + 1):
                    current = {"sql_count": 0, "sql_ms": 0}
                    started = perf_counter()
                    response = client.get("/brief", params=params)
                    current["milliseconds"] = (perf_counter() - started) * 1000
                    if response.status_code != 200:
                        raise ValueError(f"brief request failed: HTTP {response.status_code}")
                    current["blocks"] = parse_timing(response.headers["Server-Timing"])
                    samples.append(current)
            finally:
                client.close()
        finally:
            event.remove(engine, "before_cursor_execute", before)
            event.remove(engine, "after_cursor_execute", after)
            if cpu is not None:
                cpu.dump_stats(str(cprofile))
        sql = []
        with engine.connect() as connection:
            for rank, (shape, item) in enumerate(sorted(
                grouped.items(), key=lambda pair: -pair[1]["milliseconds"],
            )):
                row = {"sql": shape, "calls": item["calls"],
                       "milliseconds": item["milliseconds"]}
                if rank < 10 and item["statement"].lstrip().upper().startswith("SELECT"):
                    plan = connection.exec_driver_sql(
                        "EXPLAIN QUERY PLAN " + item["statement"], item["parameters"],
                    ).all()
                    row["plan"] = [normalize_sql(part[3]) for part in plan]
                sql.append(row)
        warm = samples[1:]
        return {
            "period_days": period, "warm_repeats": repeats,
            "cold_definition": "first request, new engine/app; OS disk cache not flushed",
            "sql_definition": "cursor execution only; fetch/ORM work included in block wall time",
            "cold": samples[0], "warm": summary([s["milliseconds"] for s in warm]),
            "warm_blocks": {name: summary([s["blocks"][name] for s in warm])
                            for name in samples[0]["blocks"] if not name.endswith("_queries")},
            "samples": samples, "sql": sql,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--period", choices=(7, 30, 90), type=int, default=30)
    parser.add_argument("--source", help="explicit Garmin source ID (omitted from output)")
    parser.add_argument("--google-source", help="explicit Google RHR source ID")
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--cprofile", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--generate-synthetic", action="store_true")
    args = parser.parse_args()
    try:
        validate_output(args.data_dir, args.output)
        validate_output(args.data_dir, args.cprofile)
        if args.generate_synthetic:
            generate_synthetic(args.data_dir)
        result = profile(args.data_dir, period=args.period, source=args.source,
                         google_source=args.google_source, end=args.end_date,
                         cprofile=args.cprofile)
        rendered = json.dumps(result, indent=2)
        if args.output:
            args.output.write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
    except Exception as exc:
        # SQLAlchemy exceptions can contain parameters. Never print their text
        # or tracebacks when the coordinator profiles a private restored copy.
        print(f"profiling failed ({type(exc).__name__})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
