"""Synthetic #376 production-entry regressions; no provider or Owner data."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import InvalidRequestError, OperationalError
from sqlalchemy.orm import Session

from healthcheck import saved_values as module
from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, migrate_database
from healthcheck.db.models import (
    GarminRecordMetric,
    GoogleRecordMetric,
    GoogleSourceRecord,
    SyncStreamState,
)
from healthcheck.garmin.normalization import garmin_source_identity, normalize_garmin_payload
from healthcheck.garmin.persistence import (
    GarminCollectionScope,
    GarminPersistenceRepository,
    GarminSourceRepository,
)
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.google.contracts import GoogleQueryContext, GoogleQueryMode
from healthcheck.google.persistence import GooglePersistenceRepository, GoogleSourceRepository
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from healthcheck.runtime import prepare_runtime
from healthcheck.saved_values import (
    GARMIN_RHR,
    GOOGLE_RHR,
    CollectionProof,
    SavedValueQuery,
    read_saved_rhr,
)
from test_google_daily_vitals import _daily_record, _family_identity, _fitbit_identity, _persist

DAY = date(2099, 1, 3)
NOW = datetime(2099, 1, 3, 23, tzinfo=UTC)
GARMIN_IDENTITY = garmin_source_identity(source_kind="synthetic")


@pytest.fixture(scope="module")
def saved_engine(tmp_path_factory):
    paths = prepare_runtime(Settings(data_dir=tmp_path_factory.mktemp("saved376") / "runtime"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    with Session(engine) as session:
        GarminSourceRepository(session).get_or_create(GARMIN_IDENTITY)
        GoogleSourceRepository(session).get_or_create(_fitbit_identity())
        session.commit()
    yield engine, paths
    engine.dispose()


@pytest.fixture(params=["garmin_connect", "google_health"])
def stored(saved_engine, request):
    engine, paths = saved_engine
    with Session(engine, autoflush=False) as session:
        provider = request.param
        if provider == "garmin_connect":
            source = GarminSourceRepository(session).get_by_identity(
                provider_code=provider,
                source_instance_id=GARMIN_IDENTITY.source_instance_id,
            )
            store = ContentAddressedGarminPayloadStore(paths.root / "garmin")
            metric = GARMIN_RHR
        else:
            source = GoogleSourceRepository(session).get_by_identity(
                provider_code=provider,
                source_instance_id=_fitbit_identity().source_instance_id,
            )
            store = ContentAddressedGooglePayloadStore(paths.root / "google")
            metric = GOOGLE_RHR
        yield session, store, source, metric
        session.rollback()


def _query(stored, **kwargs):
    _session, _store, source, metric = stored
    values = dict(
        provider_code=source.provider_code,
        metric_code=metric,
        source_id=source.id,
        requested_start_date=DAY,
        requested_end_date=DAY,
        evaluated_at_utc=NOW,
        evaluation_local_date=DAY,
        mode="default_latest",
    )
    values.update(kwargs)
    return SavedValueQuery(**values)


def _seed(stored, *, day=DAY, value=61, external="synthetic-daily"):
    session, store, source, metric_code = stored
    if source.provider_code == "google_health":
        result = _persist(
            session,
            store,
            _daily_record(
                metric_code=metric_code,
                local_date=day,
                value=value,
                external_record_id=external,
            ),
        )
        record = result.records[0]
        metric = session.scalar(
            select(GoogleRecordMetric).where(
                GoogleRecordMetric.record_id == record.id,
                GoogleRecordMetric.metric_code == metric_code,
            )
        )
    else:
        payload = {"calendarDate": day.isoformat(), "restingHeartRate": value}
        result = GarminPersistenceRepository(session, payload_store=store).persist_result(
            normalize_garmin_payload(
                payload, stream="daily_health", source_identity=GARMIN_IDENTITY
            ),
            payload=payload,
            received_at=NOW,
        )
        record = result.records[0]
        metric = session.scalar(
            select(GarminRecordMetric).where(
                GarminRecordMetric.record_id == record.id,
                GarminRecordMetric.metric_code == metric_code,
            )
        )
    assert (
        record.garmin_source_id == source.id
        if source.provider_code == "garmin_connect"
        else (record.google_source_id == source.id)
    )
    session.flush()
    return record, metric


def _read(stored, **kwargs):
    session = stored[0]
    session.flush()
    return read_saved_rhr(session, _query(stored, **kwargs))


def _copy(stored, record, metric, **changes):
    session = stored[0]
    # Persisted synthetic duplicate; production reader must never resolve it by ID.
    values = {
        column.name: getattr(record, column.name)
        for column in record.__table__.columns
        if column.name not in {"id", "idempotency_key"}
    }
    values.update(changes)
    if isinstance(record, GoogleSourceRecord):
        values["record_identity_key"] = f"synthetic-distinct-point-{record.id}"
    duplicate = type(record)(**values, idempotency_key=f"synthetic-copy-{record.id}")
    session.add(duplicate)
    session.flush()
    values = {
        column.name: getattr(metric, column.name)
        for column in metric.__table__.columns
        if column.name not in {"id", "record_id"}
    }
    session.add(type(metric)(**values, record_id=duplicate.id))
    session.flush()
    return duplicate


def test_exact_keeps_date_precision_identity_units_zero_and_unknown_context(stored):
    record, metric = _seed(stored, value=0)
    result = _read(stored)
    assert result.state == "exact"
    assert result.source_identity.source_id == stored[2].id
    assert result.observation.value == 0 and result.observation.is_zero
    assert result.observation.unit == "bpm"
    assert result.observation.source_local_date == DAY
    assert result.observation.temporal_precision == "date"
    assert result.observation.source_timestamp_utc is None
    assert result.observation.observation_age_days == 0
    assert (result.observation.record_id, result.observation.metric_row_id) == (
        record.id,
        metric.id,
    )
    body = result.as_dict()
    assert body["observation"]["source_local_date"] == DAY.isoformat()
    assert body["origin_state"] == "unknown" and body["snapshot_as_of"] is None
    assert body["acquisition_coverage_state"] == "unknown"
    assert body["age_policy"] == "not_configured"


def test_sparse_previous_observation_does_not_enumerate_calendar_days(stored):
    old = date(2017, 6, 1)
    _seed(stored, day=old)
    result = _read(stored)
    assert result.state == "last_eligible"
    assert result.observation.source_local_date == old
    assert result.observation.observation_age_days == (DAY - old).days
    assert result.search.groups_examined == 1
    assert result.query.requested_start_date == DAY


@pytest.mark.parametrize("window", [(DAY, DAY), (DAY - timedelta(days=1), DAY)])
def test_explicit_date_and_period_never_shift_to_old_evidence(stored, window):
    _seed(stored, day=DAY - timedelta(days=5))
    result = _read(
        stored, mode="explicit_period", requested_start_date=window[0], requested_end_date=window[1]
    )
    assert result.state == "no_eligible_in_search" and result.observation is None
    assert result.observed_in_persisted_history is True
    assert (result.search.start_date, result.search.end_date) == window
    assert result.search.complete and not result.search.history_exhausted


def test_unproven_empty_history_is_not_never_collected(stored):
    result = _read(stored)
    assert result.state == "no_eligible_in_search"
    assert result.observed_in_persisted_history is False
    assert result.collection_evidence_ref is None


def test_never_collected_needs_explicit_exact_scope_proof(stored):
    session, _, source, code = stored
    proof = CollectionProof(source.provider_code, source.id, code, "synthetic-trusted-inventory-v1")
    result = read_saved_rhr(session, _query(stored), never_collected=proof)
    assert result.state == "never_collected"
    assert result.collection_evidence_ref == proof.evidence_ref
    with pytest.raises(ValueError, match="exact selected identity"):
        read_saved_rhr(session, _query(stored), never_collected=replace(proof, source_id="other"))
    _seed(stored, day=DAY - timedelta(days=1000))
    session.flush()
    result = read_saved_rhr(session, _query(stored, history_start_date=DAY), never_collected=proof)
    assert result.state == "no_eligible_in_search" and result.observed_in_persisted_history


@pytest.mark.parametrize("state", ["missing", "null", "invalid"])
def test_newer_field_exclusions_do_not_become_zero_or_today(stored, state):
    _seed(stored, day=DAY - timedelta(days=1), value=60)
    record, metric = _seed(stored)
    metric.state, metric.value_number = state, None
    result = _read(stored)
    assert result.state == "last_eligible"
    assert result.observation.value == 60 and result.observation.observation_age_days == 1
    assert result.newer_exclusions[0].source_local_date == DAY
    assert state in result.newer_exclusions[0].metric_states
    assert record.id in result.newer_exclusions[0].record_ids


def test_work_cap_is_incomplete_not_no_value_or_never_collected(stored):
    _seed(stored, day=DAY - timedelta(days=2))
    for day in [DAY - timedelta(days=1), DAY]:
        _, metric = _seed(stored, day=day)
        metric.state, metric.value_number = "null", None
    result = _read(stored, max_date_groups=1)
    assert result.state == "search_incomplete" and result.observation is None
    assert result.search.groups_examined == 1 and not result.search.complete
    assert result.reason == "search_work_cap"


def test_conflicting_group_is_never_cut_to_a_winner(stored):
    record, metric = _seed(stored)
    _copy(stored, record, metric)
    result = _read(stored, max_candidate_records=1)
    assert result.state == "search_incomplete" and result.observation is None
    assert result.reason == "candidate_group_cap"
    assert result.search.incomplete_group_date == DAY
    assert result.search.groups_examined == 0
    assert result.search.records_examined == 2  # cap + one overflow sentinel
    result = _read(stored)
    assert result.state == "ambiguous" and result.observation is None
    assert result.newer_exclusions[0].candidate_count == 2
    assert len(result.newer_exclusions[0].record_ids) == 2


def test_complete_newer_conflict_is_kept_when_an_older_value_is_available(stored):
    _seed(stored, day=DAY - timedelta(days=1))
    record, metric = _seed(stored)
    _copy(stored, record, metric)
    result = _read(stored)
    assert result.state == "last_eligible"
    assert result.observation.source_local_date == DAY - timedelta(days=1)
    assert result.newer_exclusions[0].reason == "ambiguous_same_date_records"


def test_current_correction_and_retirement_do_not_resurrect_prior_projection(stored):
    original, metric = _seed(stored, value=61)
    before = _read(stored)
    metric.value_number = 59
    corrected = _read(stored)
    assert before.observation.value == 61 and corrected.observation.value == 59
    _seed(stored, day=DAY - timedelta(days=1), value=58)
    original.projection_status, original.retired_at = "retired", NOW
    original.retire_reason = "synthetic-correction"
    result = _read(stored)
    assert result.state == "last_eligible" and result.observation.value == 58
    assert result.observation.record_id != original.id


def test_real_correction_through_accepted_persistence_keeps_frozen_dto(stored):
    session, store, source, metric_code = stored

    def persist(value, at):
        if source.provider_code == "google_health":
            record = _daily_record(metric_code=metric_code, local_date=DAY, value=value)
            GooglePersistenceRepository(session, payload_store=store).persist_observation(
                identity=_fitbit_identity(),
                query=GoogleQueryContext(query_mode=GoogleQueryMode.LIST),
                stream=record.stream,
                payload={"synthetic": value},
                records=(record,),
                received_at=at,
            )
        else:
            payload = {"calendarDate": DAY.isoformat(), "restingHeartRate": value}
            GarminPersistenceRepository(session, payload_store=store).persist_result(
                normalize_garmin_payload(
                    payload, stream="daily_health", source_identity=GARMIN_IDENTITY
                ),
                payload=payload,
                received_at=at,
                collection_scope=GarminCollectionScope(
                    surface="daily_summary",
                    stream="daily_health",
                    kind="day_singleton",
                    window_start=DAY,
                    window_end=DAY,
                    complete=True,
                ),
            )
        session.flush()

    persist(61, NOW - timedelta(hours=2))
    original = _read(stored)
    persist(59, NOW - timedelta(hours=1))
    corrected = _read(stored)
    assert original.observation.value == 61
    assert corrected.state == "exact" and corrected.observation.value == 59
    assert original.observation.raw_payload_id != corrected.observation.raw_payload_id


@pytest.mark.parametrize("stored", ["google_health", "garmin_connect"], indirect=True)
def test_separate_sources_cannot_pool_or_auto_choose_newest(stored):
    session, _, source, _ = stored
    _seed(stored)
    if source.provider_code == "google_health":
        other = GoogleSourceRepository(session).get_or_create(_family_identity())
    else:
        other = GarminSourceRepository(session).get_or_create(
            replace(GARMIN_IDENTITY, source_instance_id="synthetic-other-garmin")
        )
    session.flush()
    result = _read(stored, source_id=None)
    assert result.state == "ambiguous" and result.observation is None
    assert {identity.source_id for identity in result.available_sources} == {source.id, other.id}
    assert _read(stored).source_identity.source_id == source.id


@pytest.mark.parametrize("stored", ["google_health"], indirect=True)
def test_source_inventory_over_cap_has_no_truncated_choice(stored, monkeypatch):
    session = stored[0]
    GoogleSourceRepository(session).get_or_create(_family_identity())
    session.flush()
    monkeypatch.setattr(module, "MAX_SOURCE_IDENTITIES", 1)
    result = _read(stored, source_id=None)
    assert result.state == "search_incomplete"
    assert result.available_sources == () and result.source_identity is None


def test_unknown_selected_source_is_unavailable_without_fallback(stored):
    _seed(stored)
    result = _read(stored, source_id="synthetic-unknown")
    assert result.state == "unavailable" and result.reason == "source_not_found"
    assert result.observation is None


def test_partial_value_and_provider_reauth_keep_age_separate(stored):
    session, _, source, _ = stored
    record, _ = _seed(stored, day=DAY - timedelta(days=2))
    record.record_status = "partial"
    code = (
        "resting_heart_rate"
        if source.provider_code == "garmin_connect"
        else ("google:refresh:daily_resting_hr:list:any")
    )
    session.add(
        SyncStreamState(
            provider_id=source.provider_id,
            stream_code=code,
            last_attempt_at=NOW,
            last_success_at=NOW - timedelta(days=3),
            diagnostic_status="reauth_required",
        )
    )
    result = _read(stored)
    assert result.state == "last_eligible" and result.observation.record_status == "partial"
    assert result.observation.observation_age_days == 2
    assert result.refresh.terminal_status == "reauth_required"
    assert result.refresh.last_successful_refresh_utc == NOW - timedelta(days=3)
    assert result.refresh.freshness_state == "unknown"  # no re-evaluated policy from old value


def test_future_chronology_never_receives_age_zero(stored):
    _seed(stored)
    result = _read(stored, evaluation_local_date=DAY - timedelta(days=1))
    assert result.observation is None
    assert result.newer_exclusions[0].reason == "future_chronology"


def test_reader_rejects_pending_changes_and_emits_only_reads(stored):
    session = stored[0]
    record, metric = _seed(stored)
    metric.value_number = 77
    with pytest.raises(InvalidRequestError, match="pending"):
        read_saved_rhr(session, _query(stored))
    session.flush()
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(session.bind, "before_cursor_execute", capture)
    try:
        result = read_saved_rhr(session, _query(stored))
    finally:
        event.remove(session.bind, "before_cursor_execute", capture)
    assert result.observation.value == 77
    assert not session.new and not session.dirty and not session.deleted
    assert all(
        statement.lstrip().upper().startswith(("SELECT", "BEGIN")) for statement in statements
    )
    assert result.observation.record_id == record.id
    # RHR candidate probes use existing source/stream/date indexes, no new schema.
    model, conditions = module._record_scope(_query(stored), stored[2].id)
    statement = (
        select(model.source_local_date)
        .where(
            *conditions,
            model.projection_status == "current",
            model.source_local_date <= DAY,
        )
        .order_by(model.source_local_date.desc())
        .limit(1)
    )
    sql = str(statement.compile(session.bind, compile_kwargs={"literal_binds": True}))
    plan = session.execute(text("EXPLAIN QUERY PLAN " + sql)).all()
    assert any("source_records_stream_date" in str(row) for row in plan)


def test_read_failure_is_unavailable_not_empty_history(stored, monkeypatch):
    def fail(*args, **kwargs):
        raise OperationalError("SELECT synthetic", {}, RuntimeError("synthetic unavailable"))

    monkeypatch.setattr(stored[0], "get", fail)
    result = read_saved_rhr(stored[0], _query(stored))
    assert result.state == "unavailable" and result.reason == "saved_value_read_failed"
    assert not result.search.complete and result.observed_in_persisted_history is None


def test_query_validation_does_not_silently_reinterpret_modes_or_caps(stored):
    with pytest.raises(ValueError, match="observation card"):
        _read(stored, requested_start_date=DAY - timedelta(days=1))
    with pytest.raises(ValueError, match="explicit period"):
        _read(stored, mode="explicit_period", history_start_date=DAY)
    with pytest.raises(ValueError, match="work cap"):
        _read(stored, max_candidate_records=True)
    with pytest.raises(ValueError, match="metric identity"):
        _read(stored, metric_code="sleep_duration_seconds")
    with pytest.raises(ValueError, match="timezone-aware"):
        _read(stored, evaluated_at_utc=NOW.replace(tzinfo=None))


def test_wrong_unit_is_an_exclusion_and_never_a_value(stored):
    _record, metric = _seed(stored)
    metric.unit = "ms"
    result = _read(stored)
    assert result.state == "no_eligible_in_search"
    assert result.observation is None
    assert result.newer_exclusions[0].reason == "metric_unit_mismatch"


@pytest.mark.parametrize("stored", ["google_health"], indirect=True)
def test_google_valid_target_survives_invalid_sibling_record_status(stored):
    record, _metric = _seed(stored)
    record.record_status = "invalid"
    result = _read(stored)
    assert result.state == "exact"
    assert result.observation.record_status == "invalid" and result.observation.value == 61


def test_newest_complete_group_resolves_without_scanning_old_history(stored):
    _seed(stored, day=DAY - timedelta(days=1000))
    _seed(stored)
    result = _read(stored, max_candidate_records=1, max_date_groups=1)
    assert result.state == "exact" and result.search.complete
    assert result.search.records_examined == 1 and not result.search.history_exhausted


def test_compound_reader_keeps_one_physical_snapshot_across_concurrent_correction(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "snapshot376"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    code = "google:refresh:daily_resting_hr:list:any"
    try:
        with Session(engine) as session:
            source = GoogleSourceRepository(session).get_or_create(_fitbit_identity())
            stored = (
                session,
                ContentAddressedGooglePayloadStore(paths.root / "google"),
                source,
                GOOGLE_RHR,
            )
            _record, metric = _seed(stored)
            session.add(
                SyncStreamState(
                    provider_id=source.provider_id,
                    stream_code=code,
                    last_attempt_at=NOW - timedelta(hours=1),
                    last_success_at=NOW - timedelta(hours=1),
                    diagnostic_status="present",
                )
            )
            query = _query(stored)
            metric_id, provider_id = metric.id, source.provider_id
            session.commit()
        updated = False

        def change_after_source_read(conn, cursor, statement, parameters, context, executemany):
            nonlocal updated
            if (
                not updated
                and statement.lstrip().upper().startswith("SELECT")
                and ("FROM google_sources" in statement)
            ):
                updated = True
                with Session(engine) as writer:
                    writer.get(GoogleRecordMetric, metric_id).value_number = 99
                    checkpoint = writer.scalar(
                        select(SyncStreamState).where(
                            SyncStreamState.provider_id == provider_id,
                            SyncStreamState.stream_code == code,
                        )
                    )
                    checkpoint.last_attempt_at = NOW
                    checkpoint.diagnostic_status = "reauth_required"
                    writer.commit()

        event.listen(engine, "after_cursor_execute", change_after_source_read)
        try:
            with Session(engine, autoflush=False) as reader:
                old = read_saved_rhr(reader, query)
        finally:
            event.remove(engine, "after_cursor_execute", change_after_source_read)
        assert updated
        assert old.observation.value == 61 and old.refresh.terminal_status == "succeeded"
        with Session(engine, autoflush=False) as reader:
            current = read_saved_rhr(reader, query)
        assert (
            current.observation.value == 99 and current.refresh.terminal_status == "reauth_required"
        )
    finally:
        engine.dispose()


@pytest.mark.parametrize("stored", ["google_health"], indirect=True)
def test_undated_records_cannot_prove_never_collected_or_fake_an_exact_date(stored):
    record, _metric = _seed(stored)
    record.source_local_date = None
    session, _store, source, metric_code = stored
    session.flush()
    result = read_saved_rhr(
        session,
        _query(stored),
        never_collected=CollectionProof(
            source.provider_code, source.id, metric_code, "synthetic-contradicted-inventory"
        ),
    )
    assert result.state == "no_eligible_in_search" and result.observation is None
    assert result.observed_in_persisted_history
    exclusion = result.newer_exclusions[0]
    assert exclusion.source_local_date is None
    assert exclusion.candidate_count is None and exclusion.record_ids == ()
