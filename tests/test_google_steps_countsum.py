"""Synthetic offline string-int64 Steps evidence; never account-backed acquisition."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from alembic import command
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from healthcheck.config import Settings
from healthcheck.db.engine import (
    _alembic_config,
    create_session_factory,
    create_sqlite_engine,
    migrate_database,
)
from healthcheck.db.models import (
    GoogleNormalizationAttempt,
    GooglePayloadObservation,
    GoogleRecordMetric,
    GoogleSourceRecord,
    SyncRun,
)
from healthcheck.google.contracts import (
    FAMILY_ALL_SOURCES,
    FAMILY_GOOGLE_SOURCES,
    FAMILY_GOOGLE_WEARABLES,
    INT64_MAX,
    STEPS_COUNT_SUM,
    GoogleMetricDTO,
    GoogleMetricState,
    GoogleQueryContext,
    GoogleQueryMode,
    GoogleSourceIdentity,
    GoogleSourceKind,
    GoogleStream,
    decode_count_sum_metric,
)
from healthcheck.google.normalization import normalize_google_payload
from healthcheck.google.persistence import GooglePersistenceRepository
from healthcheck.google.replay import replay_google_observations
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from healthcheck.google.sync import PRODUCTION_SYNC_SURFACES, parse_google_streams
from healthcheck.runtime import prepare_runtime

MISSING = object()
NOW = datetime(2099, 1, 4, tzinfo=UTC)
OLD_HEAD = "0017_lab_intake_v1"


def civil(day=2, *, nanos=0):
    return {
        "date": {"year": 2099, "month": 1, "day": day},
        "time": {"hours": 0, "minutes": 0, "seconds": 0, "nanos": nanos},
    }


def payload(value="0", *, start=None, end=None):
    point = {"civilStartTime": start or civil(), "civilEndTime": end or civil(3)}
    point["steps"] = {} if value is MISSING else {"countSum": value}
    return {"rollupDataPoints": [point]}


def normalize(raw, *, family=FAMILY_GOOGLE_WEARABLES, **kwargs):
    return normalize_google_payload(
        raw,
        stream="steps",
        query=GoogleQueryContext(GoogleQueryMode.DAILY_ROLL_UP, family),
        source_identity=GoogleSourceIdentity(GoogleSourceKind.FAMILY_AGGREGATE, family),
        **kwargs,
    )


@pytest.fixture
def database(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "synthetic-runtime"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    with create_session_factory(engine)() as session:
        yield paths, session, ContentAddressedGooglePayloadStore(paths.root / "artifacts")
    engine.dispose()


def persist(database, raw, *, epoch=0, family=FAMILY_GOOGLE_WEARABLES, sync_run_id=None, **kwargs):
    _, session, store = database
    repo = GooglePersistenceRepository(session, payload_store=store)
    result = normalize(raw, family=family, **kwargs)
    outcome = repo.persist_result(
        result, payload=raw, received_at=NOW + timedelta(hours=epoch), sync_run_id=sync_run_id
    )
    session.commit()
    return repo, outcome


@pytest.mark.parametrize("value", ["0", str(2**53 - 1), str(2**53), str(2**53 + 1), str(INT64_MAX)])
def test_exact_string_int64_normalization(value):
    result = normalize(payload(value))
    metric = result.records[0].metrics[0]
    assert result.status.value == "ok"
    assert metric.value_number is None and metric.collection_json is None
    assert metric.value_text == value
    count = decode_count_sum_metric(metric)
    assert count.state is GoogleMetricState.VALUE
    assert type(count.value) is int and count.value == int(value)


@pytest.mark.parametrize(
    "value",
    [
        str(INT64_MAX + 1),
        "-1",
        "-0",
        "+1",
        "1.0",
        "1e3",
        "01",
        " 1",
        "1 ",
        "",
        "NaN",
        "Infinity",
        "１",
        "1\n",
        "9" * 5000,
        True,
        False,
        0,
        1,
        1.5,
        [],
        {},
    ],
)
def test_invalid_counts_never_become_numeric(value):
    metric = normalize(payload(value)).records[0].metrics[0]
    assert metric.state is GoogleMetricState.INVALID
    assert decode_count_sum_metric(metric).value is None


@pytest.mark.parametrize("value,state", [(MISSING, "missing"), (None, "null"), ("0", "value")])
def test_missing_null_zero_distinct(value, state):
    metric = normalize(payload(value)).records[0].metrics[0]
    assert metric.state.value == state
    assert decode_count_sum_metric(metric).value == (0 if value == "0" else None)


@pytest.mark.parametrize(
    "container,state",
    [(MISSING, "missing"), (None, "null"), ([], "invalid"), ("1", "invalid"), (True, "invalid")],
)
def test_parent_states_are_not_zero(container, state):
    raw = payload()
    if container is MISSING:
        del raw["rollupDataPoints"][0]["steps"]
    else:
        raw["rollupDataPoints"][0]["steps"] = container
    assert normalize(raw).records[0].metrics[0].state.value == state


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"rollupDataPoints": None},
        {"rollupDataPoints": {}},
        {"rollupDataPoints": [], "nextPageToken": "x"},
    ],
)
def test_malformed_envelope_is_not_empty_success(raw):
    result = normalize(raw)
    assert result.status.value == "invalid" and not result.records


def test_empty_and_conflicting_oneof_are_not_counts():
    empty = normalize({"rollupDataPoints": []})
    assert empty.status.value == "empty" and not empty.records
    raw = payload()
    raw["rollupDataPoints"][0]["heartRate"] = {"average": 50}
    assert not normalize(raw).records


def test_generic_text_is_not_a_typed_count():
    metric = GoogleMetricDTO("some_text", "$.x", GoogleMetricState.VALUE, value_text="12")
    with pytest.raises(ValueError):
        decode_count_sum_metric(metric)
    valid = dict(
        metric_code=STEPS_COUNT_SUM,
        field_path="$.steps.countSum",
        state="value",
        unit="count",
        value_text="12",
    )
    for override in (
        {"unit": "steps"},
        {"value_number": 12.0},
        {"value_text": "1.0"},
        {"collection_json": "[]"},
        {"state": "missing"},
    ):
        with pytest.raises(ValueError):
            GoogleMetricDTO(**(valid | override))
        with pytest.raises(ValueError):
            decode_count_sum_metric(SimpleNamespace(**(valid | override)))


def test_exact_storage_readback_and_raw_civil_endpoints(database):
    _, session, store = database
    for index, value in enumerate(["0", str(2**53 - 1), str(2**53 + 1), str(INT64_MAX)]):
        raw = payload(value, start=civil(2 + index, nanos=123456789), end=civil(3 + index))
        repo, outcome = persist(database, raw, epoch=index)
        row_id = outcome.records[0].id
        session.expire_all()
        assert repo.records.count_sum_for(row_id).value == int(value)
        row = session.get(GoogleSourceRecord, row_id)
        assert row.source_timestamp_utc is None and row.source_timezone is None
        interval = repo.records.intervals_for(row_id)[0]
        assert interval.start_at_utc is None and interval.end_at_utc is None
        for prefix, field in [("start", "civilStartTime"), ("end", "civilEndTime")]:
            endpoint = json.loads(getattr(interval, f"{prefix}_temporal_json"))
            assert json.loads(endpoint["raw_civil_json"]) == raw["rollupDataPoints"][0][field]
        metric = session.scalar(
            select(GoogleRecordMetric).where(GoogleRecordMetric.record_id == row_id)
        )
        assert metric.value_text == value and metric.value_number is None
        assert (
            session.scalar(
                text("SELECT typeof(value_text) FROM google_record_metrics WHERE id=:id"),
                {"id": metric.id},
            )
            == "text"
        )
        assert outcome.normalization_attempt.projection_json
        replay = replay_google_observations(
            session, payload_store=store, observation_ids=[outcome.observation.id]
        )[0]
        assert replay.replayed
        assert replay.observation.id == outcome.observation.id
        assert repo.records.count_sum_for(row_id).value == int(value)


def test_identity_family_interval_and_response_order(database):
    raw = payload("20")
    repo, first = persist(database, raw)
    for family in (FAMILY_GOOGLE_SOURCES, FAMILY_ALL_SOURCES):
        _, other = persist(database, raw, family=family)
        assert other.source.id != first.source.id and other.records[0].id != first.records[0].id
    changed = payload("20", end=civil(4))
    _, interval = persist(database, changed)
    assert interval.records[0].id != first.records[0].id
    encoded = payload("20")
    del encoded["rollupDataPoints"][0]["civilStartTime"]["time"]
    _, encoded_outcome = persist(database, encoded)
    assert encoded_outcome.records[0].id != first.records[0].id
    combined = {"rollupDataPoints": raw["rollupDataPoints"] + changed["rollupDataPoints"]}
    _, a = persist(database, combined, epoch=1)
    reversed_raw = {"rollupDataPoints": list(reversed(combined["rollupDataPoints"]))}
    _, b = persist(database, reversed_raw, epoch=1)
    assert {r.id for r in a.records} == {r.id for r in b.records}
    assert all(repo.records.count_sum_for(r.id).value == 20 for r in b.records)


@pytest.mark.parametrize("mutation", ["missing", "null", "physical", "reversed", "bool", "unknown"])
def test_bad_civil_endpoints_retain_audit_without_projection(database, mutation):
    raw = payload("10")
    point = raw["rollupDataPoints"][0]
    if mutation == "missing":
        del point["civilEndTime"]
    elif mutation == "null":
        point["civilEndTime"] = None
    elif mutation == "physical":
        point["civilEndTime"] = "2099-01-03T00:00:00Z"
    elif mutation == "reversed":
        point["civilEndTime"] = civil(1)
    elif mutation == "bool":
        point["civilEndTime"]["date"]["day"] = True
    else:
        point["civilEndTime"]["zone"] = "UTC"
    _, outcome = persist(database, raw)
    assert not outcome.records
    assert outcome.raw_payload.id and outcome.observation.id and outcome.normalization_attempt.id


def test_corrections_are_exact_and_missing_replaces_previous(database):
    old_attempts = []
    for epoch, value in enumerate(["999", "2", "0", None, MISSING, "1.5", str(INT64_MAX)]):
        repo, outcome = persist(database, payload(value), epoch=epoch)
        old_attempts.append(outcome.normalization_attempt.projection_json)
        row_id = outcome.records[0].id
        count = repo.records.count_sum_for(row_id)
        assert count.state.value == (
            "missing"
            if value is MISSING
            else "null"
            if value is None
            else "invalid"
            if value == "1.5"
            else "value"
        )
        assert count.value == (int(value) if count.state is GoogleMetricState.VALUE else None)
    _, session, _ = database
    assert len(set(session.scalars(select(GoogleSourceRecord.id)))) == 1
    assert list(session.scalars(select(GoogleNormalizationAttempt.projection_json))) == old_attempts
    _, stale = persist(
        database,
        payload("100"),
        epoch=-1,
        normalization_contract_version="google-steps-countsum-v999",
    )
    assert repo.records.count_sum_for(row_id).value == INT64_MAX
    assert stale.updated_count == 0


def test_same_epoch_conflict_stale_replay_and_later_resolution(database):
    repo, first = persist(database, payload("1"))
    _, conflict = persist(database, payload("2"))
    row_id = first.records[0].id
    assert conflict.updated_count == 0
    with pytest.raises(ValueError, match="conflicted"):
        repo.records.count_sum_for(row_id)
    persist(
        database, payload("1"), epoch=-1, normalization_contract_version="google-steps-countsum-v2"
    )
    with pytest.raises(ValueError, match="conflicted"):
        repo.records.count_sum_for(row_id)
    _, repaired = persist(database, payload("0"), epoch=1)
    assert repaired.updated_count == 1 and repo.records.count_sum_for(row_id).value == 0


@pytest.mark.parametrize("same_run", [True, False])
def test_same_run_or_mixed_ordering_conflict_is_unavailable(database, same_run):
    _, session, store = database
    repo = GooglePersistenceRepository(session, payload_store=store)
    source = repo.sources.get_or_create(
        GoogleSourceIdentity(GoogleSourceKind.FAMILY_AGGREGATE, FAMILY_GOOGLE_WEARABLES)
    )
    run = SyncRun(
        provider_id=source.provider_id,
        stream_code="steps",
        status="succeeded",
        started_at=NOW,
        completed_at=NOW + timedelta(hours=1),
    )
    session.add(run)
    session.flush()
    _, first = persist(database, payload("1"), sync_run_id=run.id if same_run else None)
    _, second = persist(database, payload("2"), epoch=2, sync_run_id=run.id)
    assert second.updated_count == 0
    with pytest.raises(ValueError, match="conflicted"):
        repo.records.count_sum_for(first.records[0].id)
    # A receipt predating the conflicting observation cannot repair the projection.
    persist(database, payload("3"), epoch=1, sync_run_id=run.id if same_run else None)
    with pytest.raises(ValueError, match="conflicted"):
        repo.records.count_sum_for(first.records[0].id)
    persist(database, payload("4"), epoch=2, sync_run_id=run.id if same_run else None)
    with pytest.raises(ValueError, match="conflicted"):
        repo.records.count_sum_for(first.records[0].id)
    later = SyncRun(
        provider_id=source.provider_id,
        stream_code="steps",
        status="succeeded",
        started_at=NOW + timedelta(hours=3),
        completed_at=NOW + timedelta(hours=4),
    )
    session.add(later)
    session.flush()
    persist(database, payload("0"), epoch=3, sync_run_id=later.id if same_run else None)
    assert repo.records.count_sum_for(first.records[0].id).value == 0


def test_civil_nanosecond_order_has_no_float_roundtrip():
    raw = payload("1", start=civil(nanos=1), end=civil(nanos=2))
    result = normalize(raw)
    assert result.status.value == "ok"
    assert result.records[0].interval.start.local_wall_time.endswith(".000000001")
    assert result.records[0].interval.end.local_wall_time.endswith(".000000002")
    assert (
        normalize(payload("1", start=civil(nanos=2), end=civil(nanos=1))).records[0].status.value
        == "invalid"
    )


@pytest.mark.parametrize("raw", [b"{bad", b"null", b"[]", b'{"rollupDataPoints": [1]}'])
def test_malformed_bytes_never_form_a_count(raw):
    result = normalize(raw)
    assert result.status.value in {"invalid", "partial"} and not result.records


def test_duplicate_json_keys_and_unbounded_numeric_tokens_are_invalid():
    content = json.dumps(payload("1")).encode()
    duplicate = content.replace(b'"countSum": "1"', b'"countSum": "1", "countSum": "2"')
    huge_numeric = content.replace(b'"countSum": "1"', b'"countSum": ' + b"9" * 5000)
    for raw in (duplicate, huge_numeric):
        result = normalize(raw)
        assert result.status.value == "invalid" and not result.records


def test_bounded_normalization_rejects_over_limit():
    raw = {"rollupDataPoints": payload()["rollupDataPoints"] * 2}
    result = normalize(raw, max_records=1)
    assert result.status.value == "invalid" and not result.records


@pytest.mark.parametrize(
    "part,key",
    [("date", "year"), ("date", "month"), ("date", "day"), ("time", "hours"), ("time", "nanos")],
)
def test_huge_civil_integers_are_invalid_audit_evidence(part, key):
    raw = payload()
    raw["rollupDataPoints"][0]["civilEndTime"][part][key] = 10**100
    result = normalize(raw)
    assert result.records[0].status.value == "invalid"
    assert result.records[0].interval.state.value == "invalid"


def test_forged_raw_civil_dto_is_rejected_by_persistence(database):
    _, session, store = database
    raw = payload("1")
    result = normalize(raw)
    record = result.records[0]
    endpoint = replace(record.interval.start, raw_civil_json="{}")
    forged = replace(record, interval=replace(record.interval, start=endpoint))
    with pytest.raises(ValueError, match="civil date"):
        GooglePersistenceRepository(session, payload_store=store).persist_result(
            replace(result, records=(forged,)), payload=raw
        )
    session.rollback()
    assert not list(session.scalars(select(GoogleSourceRecord)))


def test_stored_metric_tamper_fails_typed_read(database):
    repo, outcome = persist(database, payload("1"))
    metric = repo.records.metrics_for(outcome.records[0].id)[0]
    metric.value_number = 1.0
    with pytest.raises(ValueError, match="alternate"):
        repo.records.count_sum_for(outcome.records[0].id)


def test_exact_replay_does_not_advance_chronology(database):
    repo, first = persist(database, payload("2"))
    _, repeated = persist(database, payload("2"), epoch=10)
    assert repeated.replayed and repeated.observation.id == first.observation.id
    assert repeated.records[0].projection_observed_at.replace(tzinfo=UTC) == NOW
    assert repo.records.count_sum_for(first.records[0].id).value == 2


def test_duplicate_conflicts_roll_back(database):
    _, session, store = database
    raw = {"rollupDataPoints": payload("1")["rollupDataPoints"] + payload("2")["rollupDataPoints"]}
    with pytest.raises(ValueError, match="conflicting duplicate"):
        GooglePersistenceRepository(session, payload_store=store).persist_result(
            normalize(raw), payload=raw
        )
    session.rollback()
    assert not list(session.scalars(select(GooglePayloadObservation)))


def test_no_acquisition_or_implicit_family_enablement():
    assert GoogleStream.STEPS not in {s.stream for s in PRODUCTION_SYNC_SURFACES}
    with pytest.raises(ValueError):
        parse_google_streams(["steps"])
    for query, identity in [
        (
            GoogleQueryContext(GoogleQueryMode.LIST, FAMILY_ALL_SOURCES),
            GoogleSourceIdentity(GoogleSourceKind.FAMILY_AGGREGATE, FAMILY_ALL_SOURCES),
        ),
        (GoogleQueryContext(GoogleQueryMode.DAILY_ROLL_UP), None),
        (
            GoogleQueryContext(GoogleQueryMode.DAILY_ROLL_UP, FAMILY_ALL_SOURCES),
            GoogleSourceIdentity(GoogleSourceKind.FAMILY_AGGREGATE, FAMILY_GOOGLE_WEARABLES),
        ),
    ]:
        with pytest.raises(ValueError):
            normalize_google_payload(
                payload(), stream="steps", query=query, source_identity=identity
            )


def test_populated_upgrade_preserves_rows_children_indexes_and_immutability(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "migration-synthetic"))
    command.upgrade(_alembic_config(paths), OLD_HEAD)
    engine = create_sqlite_engine(paths)
    store = ContentAddressedGooglePayloadStore(paths.root / "artifacts")
    family = FAMILY_GOOGLE_WEARABLES
    raw = {
        "rollupDataPoints": [
            {
                "civilStartTime": civil(),
                "civilEndTime": civil(3),
                "heartRate": {"beatsPerMinuteAvg": 72},
            }
        ]
    }
    with create_session_factory(engine)() as session:
        result = normalize_google_payload(
            raw,
            stream="heart_rate",
            query=GoogleQueryContext(GoogleQueryMode.DAILY_ROLL_UP, family),
            source_identity=GoogleSourceIdentity(GoogleSourceKind.FAMILY_AGGREGATE, family),
        )
        GooglePersistenceRepository(session, payload_store=store).persist_result(
            result, payload=raw
        )
        session.commit()
    tables = (
        "google_sources",
        "google_raw_payloads",
        "google_payload_observations",
        "google_source_records",
        "google_record_intervals",
        "google_record_metrics",
        "google_normalization_attempts",
    )

    def snapshot():
        with engine.connect() as connection:
            rows = {
                table: connection.execute(text(f"SELECT * FROM {table} ORDER BY id")).all()
                for table in tables
            }
            indexes = {table: inspect(connection).get_indexes(table) for table in tables}
        return rows, indexes

    before = snapshot()
    assert all(before[0][table] for table in tables)
    migrate_database(paths)
    migrate_database(paths)
    assert snapshot() == before
    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        assert not connection.execute(text("PRAGMA foreign_key_check")).all()
        for table in (
            "google_raw_payloads",
            "google_payload_observations",
            "google_normalization_attempts",
        ):
            for sql in (f"UPDATE {table} SET stream_code=stream_code", f"DELETE FROM {table}"):
                with pytest.raises(IntegrityError, match="append-only"):
                    connection.execute(text(sql))
                connection.rollback()
    engine.dispose()


def test_downgrade_refuses_to_discard_steps(database):
    paths, session, _ = database
    persist(database, payload("1"))
    session.close()
    with pytest.raises(RuntimeError, match="immutable Steps"):
        command.downgrade(_alembic_config(paths), OLD_HEAD)
