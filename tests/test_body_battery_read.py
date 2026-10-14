"""Synthetic #394 production persistence, weighting and fail-closed reads."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from fractions import Fraction
from uuid import uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import InvalidRequestError, OperationalError
from sqlalchemy.orm import Session

from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, migrate_database
from healthcheck.db.models import GarminRecordMetric, GarminSourceRecord
from healthcheck.garmin import body_battery_read as module
from healthcheck.garmin.body_battery_read import BodyBatteryQuery, read_body_battery_period
from healthcheck.garmin.normalization import garmin_source_identity, normalize_garmin_payload
from healthcheck.garmin.persistence import GarminCollectionScope, GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.garmin.sync import (
    PRODUCTION_SYNC_SURFACES,
    _normalize_provider_payload,
    _prepare_normalization_result,
)
from healthcheck.runtime import prepare_runtime
from healthcheck.web.overview_body_battery import read_overview_body_battery

DAY = date(2099, 1, 31)
NOW = datetime(2099, 2, 1, tzinfo=UTC)
IDENTITY = garmin_source_identity(source_kind="synthetic")
SURFACE = next(surface for surface in PRODUCTION_SYNC_SURFACES if surface.code == "body_battery")


@pytest.fixture(scope="module")
def battery_engine(tmp_path_factory):
    paths = prepare_runtime(Settings(data_dir=tmp_path_factory.mktemp("battery394")))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    yield engine, paths
    engine.dispose()


@pytest.fixture
def stored(battery_engine):
    engine, paths = battery_engine
    with Session(engine, autoflush=False) as session:
        yield session, ContentAddressedGarminPayloadStore(paths.root / "garmin")
        session.rollback()


def seed_battery(session, store, *, day=DAY, values=(80, 20), received=NOW,
                 identity=IDENTITY, stamps=None, scalar=None, complete=True):
    """Use exactly the production adapter/normalizer/persistence entry points."""
    if stamps is None:
        stamps = [datetime.combine(day, datetime.min.time(), tzinfo=UTC)
                  + timedelta(minutes=index) for index in range(len(values))]
    payload = {"calendarDate": day.isoformat(), "bodyBatteryValuesArray": [
        [stamp.isoformat() if isinstance(stamp, datetime) else stamp, value]
        for stamp, value in zip(stamps, values, strict=True)
    ]}
    if scalar is not None:
        payload["bodyBattery"] = scalar
    adapted = _normalize_provider_payload(SURFACE, payload, day=day)
    result = normalize_garmin_payload(adapted, stream="intraday", source_identity=identity)
    result = _prepare_normalization_result(SURFACE, payload, result, day=day)
    persisted = GarminPersistenceRepository(session, payload_store=store).persist_result(
        result, payload=payload, received_at=received,
        collection_scope=GarminCollectionScope(
            surface="body_battery", stream="intraday", kind="day_series",
            window_start=day, window_end=day, complete=complete,
            source_path_prefixes=("payload.bodyBatteryValuesArray",),
        ),
    )
    session.flush()
    return persisted.records


def query(stored, *, start=DAY - timedelta(days=6), end=DAY, source_id=None, **kwargs):
    session, _ = stored
    session.flush()
    source_id = source_id or session.scalar(select(GarminSourceRecord.garmin_source_id))
    return BodyBatteryQuery(start, end, source_id, NOW, **kwargs)


def read(stored, **kwargs):
    return read_body_battery_period(stored[0], query(stored, **kwargs))


def sample(stored, day=DAY):
    session, _ = stored
    return session.execute(select(GarminSourceRecord, GarminRecordMetric).join(
        GarminRecordMetric, GarminRecordMetric.record_id == GarminSourceRecord.id,
    ).where(GarminSourceRecord.source_local_date == day,
            GarminSourceRecord.source_path.like("payload.bodyBatteryValuesArray[%]"))
    .order_by(GarminSourceRecord.source_timestamp_utc)).first()


def duplicate(stored, record, metric, **changes):
    session, _ = stored
    values = {c.name: getattr(record, c.name) for c in record.__table__.columns
              if c.name not in {"id", "idempotency_key"}}
    values.update(changes)
    other = GarminSourceRecord(**values, idempotency_key=f"synthetic394-{uuid4()}")
    session.add(other)
    session.flush()
    values = {c.name: getattr(metric, c.name) for c in metric.__table__.columns
              if c.name not in {"id", "record_id"}}
    copied = GarminRecordMetric(**values, record_id=other.id)
    session.add(copied)
    session.flush()
    return other, copied


def test_daily_maxima_weight_days_not_samples_and_keep_exact_arithmetic(stored):
    seed_battery(*stored, values=(90, 20, 10, 0))
    seed_battery(*stored, day=DAY - timedelta(days=2), values=(30,))
    result = read(stored)
    assert result["mean_exact"] == {"numerator": "60", "denominator": "1", "decimal": "60"}
    assert result["eligible_day_count"] == 2 and result["missing_day_count"] == 5
    assert [point["value"] for point in result["daily_maxima"]] == [30, 90]
    assert result["latest_maximum"]["eligible_sample_count"] == 4
    assert result["acquisition_coverage_state"] == "unknown"
    assert any(item["reason"] == "legacy_or_alias_eligibility_unknown"
               for item in result["exclusions"])


@pytest.mark.parametrize("days", [1, 7, 30, 401, 1000])
def test_inclusive_windows_use_saved_dates_without_calendar_cap(stored, days):
    start = DAY - timedelta(days=days - 1)
    seed_battery(*stored, day=start, values=(10,))
    if days > 1:
        seed_battery(*stored, values=(40,))
    seed_battery(*stored, day=start - timedelta(days=1), values=(100,))
    seed_battery(*stored, day=DAY + timedelta(days=1), values=(99,))
    result = read(stored, start=start)
    assert result["requested_day_count"] == days and result["search"]["complete"]
    assert result["mean_exact"]["numerator"] == ("10" if days == 1 else "25")
    assert result["missing_day_count"] == days - (1 if days == 1 else 2)
    assert result["daily_maxima"][0]["source_local_date"] == start.isoformat()


@pytest.mark.parametrize("days,display,count", [(1, "60.12", 1), (7, "60.12", 2),
                                              (30, "37.56", 4)])
def test_overview_selected_window_and_existing_format(stored, days, display, count):
    for offset, value in [(0, 60.125), (6, 60.125), (7, 20), (29, 10), (30, 100)]:
        seed_battery(*stored, day=DAY - timedelta(days=offset), values=(value,))
    q = query(stored)
    result = read_overview_body_battery(stored[0], start=DAY - timedelta(days=days - 1), end=DAY,
        garmin_source_id=q.source_id, evaluated_at_utc=NOW)
    selected = result["selected"]
    assert selected["mean_display"] == display  # Existing format; no integer rounding.
    assert selected["eligible_day_count"] == count
    assert selected["requested_day_count"] == days
    if days in {1, 7}:
        assert selected["mean_exact"]["numerator"] == "481"
        assert selected["mean_exact"]["denominator"] == "8"


def test_source_local_date_is_not_utc_date_or_display_timezone(stored):
    stamp = datetime(2099, 1, 30, 23, tzinfo=UTC)
    seed_battery(*stored, values=(70,), stamps=(stamp,))
    point = read(stored, start=DAY)["latest_maximum"]
    assert point["source_local_date"] == DAY.isoformat()
    assert point["evidence"][0]["source_timestamp_utc"].startswith("2099-01-30T23:")


@pytest.mark.parametrize("case", ["missing", "null", "invalid", "bad_unit", "nonfinite",
    "bad_text", "invalid_record", "unknown_time", "future", "retired",
    "wrong_capability", "wrong_stream", "wrong_surface", "no_metric", "undated", "bad_local",
    "offset_local"])
def test_ineligible_samples_are_not_zero_and_have_evidence(stored, case):
    seed_battery(*stored, values=(80,))
    record, metric = sample(stored)
    if case in {"missing", "null", "invalid"}:
        metric.state, metric.value_number = case, None
    elif case == "bad_unit":
        metric.unit = "bpm"
    elif case == "nonfinite":
        metric.value_number = float("inf")
    elif case == "bad_text":
        stored[0].execute(text("UPDATE garmin_record_metrics SET value_number='bad' WHERE id=:id"),
                          {"id": metric.id})
        stored[0].expire(metric)
    elif case == "invalid_record":
        record.record_status = "invalid"
    elif case == "unknown_time":
        record.temporal_precision = "unknown"
    elif case in {"bad_local", "offset_local"}:
        record.temporal_precision = "local"
        record.local_wall_time = "bad" if case == "bad_local" else "2099-01-31T08:00:00+03:00"
        record.source_timestamp_utc = None
    elif case == "future":
        record.source_timestamp_utc = NOW + timedelta(seconds=1)
    elif case == "retired":
        record.projection_status, record.retired_at, record.retire_reason = "retired", NOW, "test"
    elif case == "wrong_capability":
        metric.capability_code = "stress"
    elif case == "wrong_stream":
        record.stream_code = "daily_health"
    elif case == "wrong_surface":
        record.surface_code = "stress"
    elif case == "no_metric":
        stored[0].delete(metric)
    elif case == "undated":
        record.source_local_date = None
    result = read(stored)
    assert result["mean_exact"] is None and result["latest_maximum"] is None
    assert result["eligible_day_count"] == 0 and result["missing_day_count"] == 7
    assert result["search"]["complete"]


def test_explicit_zero_partial_records_and_missing_sample(stored):
    seed_battery(*stored, values=(0, 60))
    record, metric = sample(stored)
    record.record_status = "partial"
    other = stored[0].scalar(select(GarminRecordMetric).where(
        GarminRecordMetric.metric_code == "body_battery", GarminRecordMetric.id != metric.id,
        GarminRecordMetric.field_path == "payload.bodyBatteryValuesArray"))
    other.state, other.value_number = "null", None
    result = read(stored)
    assert result["mean_exact"]["numerator"] == "0" and result["eligible_day_count"] == 1
    assert result["latest_maximum"]["is_zero"]
    assert result["latest_maximum"]["evidence"][0]["record_status"] == "partial"
    assert any(item["reason"] == "metric_null" for item in result["exclusions"])


@pytest.mark.parametrize("kind", ["same_instant", "missing_same_instant", "date_only",
                                 "mixed_precision", "local_same_wall"])
def test_conflicts_never_choose_uuid_ingestion_or_equal_number(stored, kind):
    seed_battery(*stored, values=(80,))
    record, metric = sample(stored)
    if kind == "date_only":
        record.temporal_precision, record.source_timestamp_utc = "date", None
    elif kind in {"mixed_precision", "local_same_wall"}:
        record.temporal_precision, record.local_wall_time = "local", "2099-01-31T08:00:00"
        record.source_timestamp_utc = None
    stored[0].flush()
    other, copied = duplicate(stored, record, metric)
    if kind == "mixed_precision":
        other.temporal_precision, other.source_timestamp_utc = "instant", NOW - timedelta(hours=1)
    if kind == "missing_same_instant":
        copied.state, copied.value_number = "missing", None
    result = read(stored)
    assert result["mean_exact"] is None and result["eligible_day_count"] == 0
    assert any(item["reason"] == "ambiguous_sample_coordinates" for item in result["exclusions"])


def test_replay_correction_and_complete_collection_retirement(stored):
    seed_battery(*stored, values=(80, 20))
    first = read(stored)
    ids = {row.id for row in stored[0].scalars(select(GarminSourceRecord))}
    seed_battery(*stored, values=(80, 20), received=NOW + timedelta(minutes=1))
    assert {row.id for row in stored[0].scalars(select(GarminSourceRecord))} == ids
    assert read(stored)["mean_exact"] == first["mean_exact"]
    seed_battery(*stored, values=(30, 20), received=NOW + timedelta(minutes=2))
    assert read(stored)["mean_exact"]["numerator"] == "30"
    seed_battery(*stored, values=(80, 20), received=NOW + timedelta(minutes=1))
    assert read(stored)["mean_exact"]["numerator"] == "30"  # Older replay cannot undo correction.
    seed_battery(*stored, values=(10,), received=NOW + timedelta(minutes=3))
    assert read(stored)["latest_maximum"]["eligible_sample_count"] == 1
    assert read(stored)["mean_exact"]["numerator"] == "10"
    assert any(row.projection_status == "retired"
               for row in stored[0].scalars(select(GarminSourceRecord)))


def test_direct_scalar_and_last_series_alias_are_not_additional_measurements(stored):
    seed_battery(*stored, values=(20, 50), scalar=99)
    point = read(stored)["latest_maximum"]
    assert point["value"] == 50 and point["eligible_sample_count"] == 2
    assert all(row["field_path"] == "payload.bodyBatteryValuesArray" for row in point["evidence"])
    for record in stored[0].scalars(select(GarminSourceRecord)):
        if record.source_path and "ValuesArray[" in record.source_path:
            record.projection_status = "retired"
            record.retired_at, record.retire_reason = NOW, "test"
    result = read(stored)
    assert result["mean_exact"] is None and result["legacy_eligibility"] == "unknown"


def test_production_duplicate_coalescing_and_conflict_guard(stored):
    stamp = datetime(2099, 1, 31, 8, tzinfo=UTC)
    seed_battery(*stored, values=(80, 80), stamps=(stamp, stamp))
    result = read(stored)
    assert result["latest_maximum"]["eligible_sample_count"] == 1
    assert result["mean_exact"]["numerator"] == "80"
    with pytest.raises(ValueError, match="conflicting duplicate identities"):
        seed_battery(*stored, values=(80, 20), stamps=(stamp, stamp))
    assert read(stored)["mean_exact"]["numerator"] == "80"


def test_different_local_times_and_single_date_only_sample(stored):
    seed_battery(*stored, values=(20, 80), stamps=("2099-01-31T08:00:00", "2099-01-31T09:00:00"))
    assert read(stored)["mean_exact"]["numerator"] == "80"
    records = list(stored[0].scalars(select(GarminSourceRecord).where(
        GarminSourceRecord.source_path.like("payload.bodyBatteryValuesArray[%]"))))
    records[0].temporal_precision, records[0].source_timestamp_utc = "date", None
    records[1].projection_status = "retired"
    records[1].retired_at, records[1].retire_reason = NOW, "test"
    assert read(stored)["latest_maximum"]["eligible_sample_count"] == 1


def test_selected_source_and_no_automatic_fallback(stored):
    records = seed_battery(*stored, values=(20,))
    source = records[0].garmin_source_id
    seed_battery(*stored, values=(100,), identity=garmin_source_identity(source_kind="provider"))
    assert read(stored, source_id=source)["mean_exact"]["numerator"] == "20"
    assert read(stored, source_id="unknown")["reason"] == "source_not_found"
    result = read_body_battery_period(stored[0], replace(query(stored), source_id=None))
    assert result["reason"] == "source_not_selected" and result["mean_exact"] is None


@pytest.mark.parametrize("caps", [{"max_candidate_records": 2}, {"max_records_per_day": 1}])
def test_work_caps_never_publish_partial_mean_or_denominator(stored, caps):
    seed_battery(*stored, day=DAY - timedelta(days=1), values=(20,))
    seed_battery(*stored, values=(80, 10))
    result = read(stored, **caps)
    assert result["state"] == "search_incomplete" and not result["search"]["complete"]
    for field in ("mean_exact", "mean_value", "eligible_day_count", "missing_day_count",
                  "latest_maximum"):
        assert result[field] is None
    assert result["daily_maxima"] == []


def test_read_failure_and_no_writes_or_pending_writer_state(stored, monkeypatch):
    seed_battery(*stored)
    seed_battery(*stored, day=DAY - timedelta(days=1))
    statements = []
    def listener(_c, _cur, sql, *_a):
        statements.append(sql)
    event.listen(stored[0].bind, "before_cursor_execute", listener)
    try:
        result = read(stored)
    finally:
        event.remove(stored[0].bind, "before_cursor_execute", listener)
    assert result["search"]["complete"]
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
                   for sql in statements)
    record, _ = sample(stored)
    record.record_status = "partial"
    with pytest.raises(InvalidRequestError, match="pending"):
        read_body_battery_period(
            stored[0], BodyBatteryQuery(DAY, DAY, record.garmin_source_id, NOW))
    stored[0].flush()
    project = module._project_day
    projected = []
    def fail(*args):
        if projected:
            raise OperationalError("synthetic", {}, Exception("synthetic"))
        projected.append(args[0])
        return project(*args)
    monkeypatch.setattr(module, "_project_day", fail)
    failed = read(stored)
    assert failed["reason"] == "saved_value_read_failed" and failed["mean_exact"] is None
    assert projected and failed["daily_maxima"] == [] and failed["eligible_day_count"] is None


def test_caps_allow_exact_boundary_but_detect_the_next_record(stored):
    seed_battery(*stored, values=(80,))  # One typed sample plus its scalar alias.
    assert read(stored, max_candidate_records=2, max_records_per_day=2)["search"]["complete"]
    seed_battery(*stored, day=DAY - timedelta(days=1), values=(20,))
    result = read(stored, max_candidate_records=2, max_records_per_day=2)
    assert result["reason"] == "period_record_cap" and result["mean_exact"] is None


def test_fractional_daily_maxima_preserve_exact_sum(stored):
    for index, value in enumerate((60.1, 60.2, 60.3)):
        seed_battery(*stored, day=DAY - timedelta(days=index), values=(value, 0))
    result = read(stored)
    mean = Fraction(301, 5)
    assert result["mean_exact"]["numerator"] == str(mean.numerator)
    assert result["mean_exact"]["denominator"] == str(mean.denominator)


@pytest.mark.parametrize("value", [-10.5, 101, 1_000_000])
def test_production_finite_contract_has_no_invented_product_range(stored, value):
    seed_battery(*stored, values=(value, value - 1))
    record, metric = sample(stored)
    assert metric.state == "value" and metric.value_number == value
    result = read(stored)
    assert result["latest_maximum"]["value"] == value
    assert result["latest_maximum"]["eligible_sample_count"] == 2
    assert result["latest_maximum"]["evidence"][0]["record_id"] == record.id
    assert result["eligible_day_count"] == 1 and result["missing_day_count"] == 6
    mean = Fraction(str(value))
    assert result["mean_exact"]["numerator"] == str(mean.numerator)
    assert result["mean_exact"]["denominator"] == str(mean.denominator)
    dto = read_overview_body_battery(stored[0], start=DAY, end=DAY,
        garmin_source_id=record.garmin_source_id, evaluated_at_utc=NOW)["selected"]
    assert dto["mean_display"] == str(value)


@pytest.mark.parametrize("evaluation_hour,eligible", [(18, False), (20, True)])
def test_source_calendar_ahead_of_utc_host_uses_only_actual_utc_chronology(
    stored, evaluation_hour, eligible,
):
    source_day = date(2099, 2, 1)
    local_stamp = datetime(2099, 2, 1, 0, tzinfo=timezone(timedelta(hours=5)))
    records = seed_battery(*stored, day=source_day, values=(80,), stamps=(local_stamp,))
    q = replace(query(stored, start=source_day, end=source_day),
                evaluated_at_utc=datetime(2099, 1, 31, evaluation_hour, tzinfo=UTC))
    result = read_body_battery_period(stored[0], q)
    assert result["search"]["complete"]
    assert result["eligible_day_count"] == int(eligible)
    if eligible:
        point = result["latest_maximum"]
        assert point["source_local_date"] == "2099-02-01"
        assert point["value"] == 80
        assert point["evidence"][0]["source_timestamp_utc"] == "2099-01-31T19:00:00+00:00"
        assert result["mean_exact"]["numerator"] == "80"
        assert result["mean_exact"]["denominator"] == "1"
        assert result["missing_day_count"] == 0
        dto = read_overview_body_battery(stored[0], start=source_day, end=source_day,
            garmin_source_id=records[0].garmin_source_id,
            evaluated_at_utc=q.evaluated_at_utc)["selected"]
        assert dto["mean_display"] == "80" and dto["eligible_day_count"] == 1
    else:
        assert result["mean_exact"] is None
        assert any(item["reason"] == "future_chronology" for item in result["exclusions"])


def test_date_only_preserves_source_date_without_invented_utc_or_host_day_guard(stored):
    source_day = date(2099, 2, 1)
    seed_battery(*stored, day=source_day, values=(80,))
    record, _ = sample(stored, source_day)
    record.temporal_precision, record.source_timestamp_utc = "date", None
    record.local_wall_time = record.source_local_timestamp = None
    record.source_utc_offset_minutes = None
    record.source_local_field = record.source_utc_field = None
    q = replace(query(stored, start=source_day, end=source_day),
                evaluated_at_utc=datetime(2099, 1, 31, 20, tzinfo=UTC))
    result = read_body_battery_period(stored[0], q)
    assert result["eligible_day_count"] == 1 and result["mean_exact"]["numerator"] == "80"
    point = result["latest_maximum"]
    assert point["source_local_date"] == "2099-02-01"
    assert point["evidence"][0]["temporal_precision"] == "date"
    assert point["evidence"][0]["source_timestamp_utc"] is None


def test_future_utc_sample_does_not_replace_already_measured_source_day_maximum(stored):
    source_day = date(2099, 2, 1)
    seed_battery(*stored, day=source_day, values=(80, 100), stamps=(
        datetime(2099, 1, 31, 19, tzinfo=UTC), datetime(2099, 1, 31, 21, tzinfo=UTC),
    ))
    q = replace(query(stored, start=source_day, end=source_day),
                evaluated_at_utc=datetime(2099, 1, 31, 20, tzinfo=UTC))
    result = read_body_battery_period(stored[0], q)
    assert result["latest_maximum"]["value"] == 80
    assert result["latest_maximum"]["source_local_date"] == "2099-02-01"
    assert result["latest_maximum"]["eligible_sample_count"] == 1
    assert result["mean_exact"]["numerator"] == "80" and result["eligible_day_count"] == 1
    assert any(item["reason"] == "future_chronology" for item in result["exclusions"])
