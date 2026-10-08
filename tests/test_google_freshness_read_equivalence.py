"""Synthetic B2 equivalence, indexed-plan and bounded work evidence for #295."""

from __future__ import annotations

import json
import random
import runpy
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event, insert, text
from sqlalchemy.orm import Session

from healthcheck import source_freshness_read as reader
from healthcheck.collection_policy import (
    COLLECTION_POLICY_CONTRACT_VERSION,
    COLLECTION_POLICY_PROVENANCE,
    CollectionPolicyResolution,
    CollectionPolicySnapshot,
    CollectionPolicyStatus,
)
from healthcheck.config import Settings
from healthcheck.db.models import (
    Base,
    GoogleSource,
    GoogleSourceRecord,
    Provider,
    SyncRun,
    SyncStreamState,
)
from healthcheck.google.contracts import FAMILY_GOOGLE_WEARABLES
from healthcheck.source_freshness import SCOPES, evaluate_scope
from healthcheck.source_freshness_consumer import read_consumer_freshness_projection
from healthcheck.web import period_brief_query
from healthcheck.web.pages import _brief_source_status
from healthcheck.web.read_snapshot import ensure_read_snapshot

REFERENCE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/google_freshness_read_reference.py")
)["google_evidence_reference"]
DAY = date(2099, 1, 15)
NOW = datetime(2099, 1, 15, 12, tzinfo=UTC)
GOOGLE_SCOPES = tuple(scope for scope in SCOPES if scope.provider == "google")


def context(scope):
    code = scope.key.split(":", 1)[1]
    if code == "wearables_sleep_reconcile":
        return "sleep", "reconcile", FAMILY_GOOGLE_WEARABLES
    return code, "list", None


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            Provider(id="p", code="google_health", display_name="Synthetic", provider_kind="api"),
            Provider(id="foreign", code="other", display_name="Other", provider_kind="other"),
        ])
        session.add_all([
            GoogleSource(
                id=source, provider_id=provider, acquisition_source_id="synthetic-unused",
                source_kind="data_source", provider_code="google_health",
                source_instance_id=source, source_contract_version="synthetic-295",
            )
            for source, provider in (("s1", "p"), ("s2", "p"), ("other", "foreign"))
        ])
        session.commit()
        yield session
    engine.dispose()


def record_values(rid, *, source="s1", day=DAY, precision="date", stamp=None,
                  status="ok", projection="current", stream="sleep", mode="list", family=None):
    return dict(
        id=rid, google_source_id=source, raw_payload_id="synthetic-unused",
        stream_code=stream, query_mode=mode, data_source_family=family,
        record_identity_key=rid, idempotency_key=rid,
        temporal_precision=precision, source_local_date=day, source_timestamp_utc=stamp,
        local_wall_time="synthetic-unresolved" if precision == "local" else None,
        record_status=status, projection_status=projection,
        retired_at=NOW if projection == "retired" else None,
        normalization_contract_version="synthetic-295",
    )


def record(session, rid, **kwargs):
    session.add(GoogleSourceRecord(**record_values(rid, **kwargs)))


def facts_and_results(session, **disposition):
    facts = [reader.read_facts(session, scope, evaluation_local_date=DAY, **disposition)
             for scope in GOOGLE_SCOPES]
    results = [evaluate_scope(scope, row, evaluated_at_utc=NOW, evaluation_local_date=DAY)
               for scope, row in zip(GOOGLE_SCOPES, facts, strict=True)]
    return facts, results


def assert_equivalent(session):
    ensure_read_snapshot(session)
    actual = facts_and_results(session)
    projection = read_consumer_freshness_projection(
        session, evaluated_at_utc=NOW, evaluation_local_date=DAY,
    )
    with patch.object(reader, "_google_evidence_query", REFERENCE):
        assert actual == facts_and_results(session)
        assert projection == read_consumer_freshness_projection(
            session, evaluated_at_utc=NOW, evaluation_local_date=DAY,
        )
    return actual


@pytest.mark.parametrize("scope", GOOGLE_SCOPES, ids=lambda scope: scope.key)
@pytest.mark.parametrize("kind", [
    "none", "date", "instant", "multiple_records", "multiple_latest_sources",
    "older_source", "mixed_precision", "older_invalid", "latest_invalid",
    "undated_invalid_ignored", "undated_instants", "undated_tied_sources",
    "undated_invalid_poison", "only_undated_invalid", "undated_date",
    "only_undated_invalid_sources",
    "excluded_future", "future_chronology",
])
def test_google_exact_latest_slice(session, scope, kind):
    stream, mode, family = context(scope)

    def add(rid, **kwargs):
        record(session, rid, stream=stream, mode=mode, family=family, **kwargs)

    if kind in {"only_undated_invalid", "only_undated_invalid_sources"}:
        add("invalid", day=None, precision="unknown")
        if kind == "only_undated_invalid_sources":
            add("second-invalid", source="s2", day=None, precision="local")
    elif kind == "undated_date":
        add("invalid", day=None)
    elif kind.startswith("undated_") and kind != "undated_invalid_ignored":
        add("latest", day=None, precision="instant", stamp=NOW - timedelta(hours=1))
        add("older", day=None, precision="instant", stamp=NOW - timedelta(hours=2), source="s2")
        if kind == "undated_tied_sources":
            add("tied", day=None, precision="instant", stamp=NOW - timedelta(hours=1), source="s2")
        elif kind == "undated_invalid_poison":
            add("invalid", day=None, precision="unknown", stamp=NOW - timedelta(days=10))
    elif kind != "none":
        add("accepted", day=DAY + timedelta(days=1) if kind == "future_chronology" else DAY)
        if kind in {"instant", "mixed_precision"}:
            if kind == "instant":
                session.get(GoogleSourceRecord, "accepted").temporal_precision = "instant"
                session.get(GoogleSourceRecord, "accepted").source_timestamp_utc = NOW
            else:
                add("instant", precision="instant", stamp=NOW)
        elif kind == "multiple_records":
            add("same-source")
        elif kind == "multiple_latest_sources":
            add("second-source", source="s2")
        elif kind == "older_source":
            add("older", source="s2", day=DAY - timedelta(days=1))
        elif kind in {"older_invalid", "latest_invalid"}:
            add("invalid", precision="local",
                day=DAY - timedelta(days=1) if kind == "older_invalid" else DAY)
        elif kind == "undated_invalid_ignored":
            add("invalid", day=None, precision="unknown")
        elif kind == "excluded_future":
            for rid, overrides in (
                ("foreign", dict(source="other")), ("partial", dict(status="partial")),
                ("invalid", dict(status="invalid")), ("empty", dict(status="empty")),
                ("retired", dict(projection="retired")),
            ):
                add(rid, day=DAY + timedelta(days=1), **overrides)
            # Correct source but wrong stream, list/reconcile or family is ineligible.
            for rid, wrong in (
                ("stream", dict(stream="hrv" if stream != "hrv" else "sleep")),
                ("mode", dict(mode="list" if mode == "reconcile" else "reconcile")),
                ("family", dict(family=None if family else FAMILY_GOOGLE_WEARABLES)),
                ("rollup", dict(mode="rollUp")),
            ):
                args = dict(stream=stream, mode=mode, family=family)
                args.update(wrong)
                record(session, rid, day=DAY + timedelta(days=1), **args)
    session.commit()
    facts, _ = assert_equivalent(session)
    value = facts[GOOGLE_SCOPES.index(scope)]
    if kind == "none":
        assert value.observed_once is False
    elif kind in {"multiple_latest_sources", "undated_tied_sources"}:
        assert value.attribution_resolved is False
    elif kind == "mixed_precision":
        assert value.chronology_issue == "chronology_unresolved"
        assert value.evidence_at_utc == NOW and value.evidence_local_date == DAY
    elif kind in {"latest_invalid", "only_undated_invalid", "only_undated_invalid_sources",
                  "undated_date",
                  "undated_invalid_poison"}:
        assert value.chronology_issue == "invalid_chronology"
        if kind == "only_undated_invalid_sources":
            assert value.attribution_resolved is True  # No timestamp slice, just as pre-B2.
    elif kind == "undated_instants":
        assert value.evidence_at_utc == NOW - timedelta(hours=1)
        assert value.evidence_local_date is None and value.attribution_resolved is True
    elif kind not in {"instant", "future_chronology"}:
        assert (value.evidence_at_utc, value.evidence_local_date, value.chronology_issue,
                value.attribution_resolved, value.observed_once) == (None, DAY, None, True, True)


def test_randomized_google_contexts_and_chronology(session):
    rng = random.Random(295)
    for i in range(600):
        precision = rng.choice(("date", "instant", "local", "unknown"))
        stream, mode, family = context(rng.choice(GOOGLE_SCOPES))
        record(session, str(i), source=rng.choice(("s1", "s2", "other")),
               day=rng.choice((None, DAY, DAY - timedelta(days=2), DAY + timedelta(days=1))),
               precision=precision, stamp=NOW - timedelta(hours=rng.randrange(80)),
               status=rng.choice(("ok", "partial", "invalid", "empty")),
               projection=rng.choice(("current", "retired")),
               stream=stream, mode=mode, family=family)
    session.commit()
    assert_equivalent(session)
    for provider in ("p", "foreign", "absent"):
        for scope in GOOGLE_SCOPES:
            args = (session, provider, *context(scope))
            assert reader._google_evidence_query(*args) == REFERENCE(*args)


@pytest.mark.parametrize("precision", ["instant", "minute", "unexpected"])
def test_malformed_synthetic_timestamp_preserves_old_facts(session, precision):
    # Exercise damaged persisted chronology outside today's ingest constraints.
    # This affects only this in-memory synthetic connection, never schema/ingest.
    session.execute(text("PRAGMA ignore_check_constraints=ON"))
    record(session, "missing-stamp", precision=precision)
    session.commit()
    facts, _ = assert_equivalent(session)
    if precision in {"instant", "minute"}:
        assert facts[0].chronology_issue == "invalid_chronology"
    session.execute(text("PRAGMA ignore_check_constraints=OFF"))


@pytest.mark.parametrize("terminal", [None, "partial", "failed", "reauth_required"])
@pytest.mark.parametrize("age_days", [0, 2, 4])
def test_checkpoints_policy_and_packet_equivalence(session, tmp_path, terminal, age_days):
    for scope in GOOGLE_SCOPES:
        stream, mode, family = context(scope)
        record(session, scope.key, day=DAY - timedelta(days=age_days),
               stream=stream, mode=mode, family=family)
        family_key = "google-wearables" if family else "any"
        code = f"google:refresh:{stream}:{mode}:{family_key}"
        session.add(SyncStreamState(id=scope.key, provider_id="p", stream_code=code,
                                   last_attempt_at=NOW - timedelta(hours=2),
                                   last_success_at=NOW - timedelta(hours=2),
                                   diagnostic_status="present"))
    # Exact explicit day checkpoint beats undated fallback; future/malformed keys do not.
    for suffix, status in ((DAY.isoformat(), terminal or "present"),
                           ((DAY + timedelta(days=1)).isoformat(), "failed"),
                           ("malformed", "failed")):
        session.add(SyncStreamState(
            id=suffix, provider_id="p",
            stream_code=f"google:refresh:heart_rate:list:any:day:{suffix}",
            last_attempt_at=NOW - timedelta(hours=1), last_success_at=NOW - timedelta(hours=2),
            diagnostic_status=status,
        ))
    if terminal in {"failed", "reauth_required"}:
        session.add(SyncRun(id="terminal", provider_id="p", stream_code="google_refresh",
                            status="failed", error_category=terminal, item_count=0,
                            started_at=NOW - timedelta(minutes=2),
                            completed_at=NOW - timedelta(minutes=1)))
    session.commit()
    assert_equivalent(session)
    for disposition in (dict(requested=False), dict(disabled=True)):
        current = facts_and_results(session, **disposition)
        with patch.object(reader, "_google_evidence_query", REFERENCE):
            assert current == facts_and_results(session, **disposition)
        assert all(row["state"] == "not_requested" for row in current[1])
        assert all(row.observed_once for row in current[0])
    policy = CollectionPolicyResolution(
        status=CollectionPolicyStatus.VALID,
        snapshot=CollectionPolicySnapshot(
            contract_version=COLLECTION_POLICY_CONTRACT_VERSION,
            provenance=COLLECTION_POLICY_PROVENANCE, revision=1, updated_at_utc=NOW,
            disabled_streams=("google:heart_rate",), content_sha256="0" * 64,
        ),
    )
    current = read_consumer_freshness_projection(
        session, evaluated_at_utc=NOW, evaluation_local_date=DAY, collection_policy=policy,
    )
    with patch.object(reader, "_google_evidence_query", REFERENCE):
        assert current == read_consumer_freshness_projection(
            session, evaluated_at_utc=NOW, evaluation_local_date=DAY, collection_policy=policy,
        )
    assert current["not_requested_required"][0]["reason_code"] == "disabled"

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    settings = Settings(data_dir=tmp_path / "synthetic-runtime")
    with patch.object(period_brief_query, "datetime", FixedClock):
        service = period_brief_query.PeriodBriefService(session, settings)
        for days in (7, 30):
            args = dict(start_date=DAY - timedelta(days=days - 1), end_date=DAY, thin_display=True)
            current = service.build_with_render(**args)
            with patch.object(reader, "_google_evidence_query", REFERENCE):
                previous = service.build_with_render(**args)
            assert current == previous  # Full packet/hash, display and rendered text.
            source_status = _brief_source_status(current["display"])
            assert source_status is not None and "Google:" in source_status
            assert source_status == _brief_source_status(previous["display"])


def capture_plans(session, callback):
    statements = []
    engine = session.get_bind()

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if "google_source_records" in statement:
            statements.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = callback()
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    plans = [[row[3] for row in session.connection().exec_driver_sql(
        "EXPLAIN QUERY PLAN " + statement, parameters,
    )] for statement, parameters in statements]
    return result, plans


@pytest.mark.parametrize("undated", [False, True])
def test_indexed_google_plan_including_fallback(session, undated):
    record(session, "instant", day=None if undated else DAY,
           precision="instant", stamp=NOW)
    session.commit()
    scope = GOOGLE_SCOPES[0]
    def callback():
        return reader._google_evidence_query(session, "p", *context(scope))
    actual, plans = capture_plans(session, callback)
    with patch.object(reader, "_google_evidence_query", REFERENCE):
        expected, old_plans = capture_plans(session, callback)
    assert actual == expected
    assert any("SCAN google_source_records" in detail for plan in old_plans for detail in plan)
    assert all("SCAN google_source_records" not in detail for plan in plans for detail in plan)
    for plan in plans:
        assert any("SEARCH google_source_records USING INDEX ix_google_source_records_" in detail
                   for detail in plan)
    print(json.dumps(dict(
        undated_fallback=undated,
        before_google_full_scans=sum("SCAN google_source_records" in detail
                                     for plan in old_plans for detail in plan),
        after_google_record_plan=sorted({detail.split(" (")[0]
                                        for plan in plans for detail in plan
                                        if "google_source_records" in detail}),
    )))


def test_bounded_large_synthetic_freshness_work(session):
    # Same latest-day shape; add dense historical records under two sources, all
    # ten contexts, plus a foreign provider. No payloads or health values needed.
    for start in range(0, 100_000, 2000):
        rows = []
        for i in range(start, start + 2000):
            stream, mode, family = context(GOOGLE_SCOPES[i % len(GOOGLE_SCOPES)])
            rows.append(record_values(
                str(i), source=("s1", "s2", "other")[(i // 10) % 3],
                day=DAY - timedelta(days=(i // 30) % 730),
                precision="instant", stamp=NOW - timedelta(days=(i // 30) % 730),
                stream=stream, mode=mode, family=family,
            ))
        session.execute(insert(GoogleSourceRecord), rows)
    session.commit()
    ensure_read_snapshot(session)
    connection = session.connection().connection.driver_connection

    def measure():
        ticks = 0

        def progress():
            nonlocal ticks
            ticks += 1
            return 0

        connection.set_progress_handler(progress, 1000)
        started = perf_counter()
        try:
            value = read_consumer_freshness_projection(
                session, evaluated_at_utc=NOW, evaluation_local_date=DAY,
            )
        finally:
            elapsed = perf_counter() - started
            connection.set_progress_handler(None, 0)
        return value, elapsed, ticks * 1000

    with patch.object(reader, "_google_evidence_query", REFERENCE):
        old, old_seconds, old_steps = measure()
    current, seconds, steps = measure()
    assert current == old
    assert steps < old_steps / 4  # Deterministic work bound; no flaky timing assertion.
    _, plans = capture_plans(session, lambda: read_consumer_freshness_projection(
        session, evaluated_at_utc=NOW, evaluation_local_date=DAY,
    ))
    assert len(plans) == 20
    assert all("SCAN google_source_records" not in detail for plan in plans for detail in plan)
    print(json.dumps(dict(synthetic_records=100_000, before_seconds=old_seconds,
                          after_seconds=seconds, before_vm_steps=old_steps, after_vm_steps=steps,
                          google_evidence_executes=len(plans), google_full_scans=0)))
