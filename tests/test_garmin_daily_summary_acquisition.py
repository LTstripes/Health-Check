"""Future-only acquisition proof through real persistence/readers, synthetic data."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from healthcheck.config import Settings
from healthcheck.db.engine import (
    _alembic_config,
    create_session_factory,
    create_sqlite_engine,
    migrate_database,
)
from healthcheck.db.models import (
    GarminDailySummaryAcquisitionReceipt as Receipt,
)
from healthcheck.db.models import (
    GarminPayloadObservation,
    SyncRun,
    SyncStreamState,
)
from healthcheck.db.repositories import repositories_for
from healthcheck.garmin import completed_steps_read as reader
from healthcheck.garmin import sync
from healthcheck.garmin.backfill import GarminHistoricalBackfill
from healthcheck.garmin.completed_steps_read import read_completed_steps_window
from healthcheck.garmin.daily_summary_acquisition import RECEIPT_VERSION
from healthcheck.garmin.observed_steps import SavedDailyStepsRepository
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.runtime import prepare_runtime
from test_garmin_completed_steps import ABSENT, BOUNDARY, DAY, NOW
from test_garmin_completed_steps import acquire as legacy_acquire
from test_garmin_incremental_sync import _steps_client
from test_garmin_observed_steps import saved_database as saved_database


@contextmanager
def database(root):
    paths = prepare_runtime(Settings(data_dir=root))
    engine = create_sqlite_engine(paths)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            yield session, ContentAddressedGarminPayloadStore(root / "artifacts")
    finally:
        engine.dispose()


def fetch(root, count=17, *, at=BOUNDARY, partial=True, days=1, payload=None):
    if payload is None:
        payload = {"calendarDate": DAY.isoformat()}
        if count is not ABSENT:
            payload["totalSteps"] = count
    return sync.GarminIncrementalSync(
        Settings(data_dir=root),
        client=_steps_client(
            payload,
            errors={"get_hrv_data": ConnectionError("synthetic other surface")}
            if partial
            else None,
        ),
        clock=lambda: at,
    ).run(as_of=DAY, trailing_window_days=days)


def read(session, store, source_id=None, *, start=DAY, end=DAY, now=NOW):
    return read_completed_steps_window(
        session,
        payload_store=store,
        source_id=source_id,
        start_date=start,
        end_date=end,
        evaluated_at=now,
    )


@pytest.mark.parametrize(
    "count,state,value",
    [
        (17, "value", 17),
        (0, "value", 0),
        (None, "null", None),
        (ABSENT, "missing", None),
        (True, "invalid", None),
    ],
)
def test_actual_partial_run_has_exact_receipt_and_keeps_field_states(tmp_path, count, state, value):
    root = tmp_path / "synthetic-runtime"
    report = fetch(root, count)
    assert report.status is sync.GarminSyncStatus.PARTIAL
    with database(root) as (session, store):
        observation = session.scalar(
            select(GarminPayloadObservation).where(
                GarminPayloadObservation.sync_run_id == report.sync_run_id,
                GarminPayloadObservation.source_filename == "daily_summary.json",
            )
        )
        receipt = session.get(Receipt, observation.id)
        assert receipt.contract_version == RECEIPT_VERSION
        assert receipt.surface == "daily_summary" and receipt.method == "get_user_summary"
        assert receipt.requested_date == receipt.original_calendar_date == DAY
        cell = read(session, store).cells[0]
        assert (cell.state, cell.value) == (state, value)
        assert cell.evidence[0].observation_id == receipt.observation_id
        assert cell.evidence[0].sync_run_id == report.sync_run_id
        assert cell.evidence[0].acquisition_proof == "daily_summary_receipt"
        assert cell.evidence[0].acquisition_receipt_version == RECEIPT_VERSION
        assert cell.latest_received_at == BOUNDARY
        assert cell.coverage == cell.finality == cell.timezone == "unknown"


def test_legacy_partial_is_not_certified_by_another_sources_receipt(tmp_path):
    root = tmp_path / "synthetic-runtime"
    fetch(root)
    with database(root) as (session, store):
        other = legacy_acquire(session, store, 99, status="partial", account="other-account")
        assert (
            read(session, store, other.source.id).cells[0].reason == "latest_acquisition_unproven"
        )
        assert session.get(Receipt, other.observation.id) is None
        assert read(session, store).reason == "source_selection_required"


@pytest.mark.parametrize("status", ["running", "failed"])
def test_receipt_never_promotes_nonterminal_or_failed_run(tmp_path, status):
    root = tmp_path / "synthetic-runtime"
    report = fetch(root)
    with database(root) as (session, store):
        run = session.get(SyncRun, report.sync_run_id)
        run.status = status
        run.completed_at = None if status == "running" else run.completed_at
        session.commit()
        assert read(session, store).cells[0].reason == "latest_acquisition_unproven"


@pytest.mark.parametrize("delta,expected", [(-1, None), (0, 17), (1, 17)])
def test_receipt_uses_observation_moscow_boundary_not_request_utc_midnight(
    tmp_path, delta, expected
):
    root = tmp_path / "synthetic-runtime"
    fetch(root, at=BOUNDARY + timedelta(microseconds=delta))
    with database(root) as (session, store):
        source_id = session.scalar(
            select(GarminPayloadObservation.garmin_source_id).where(
                GarminPayloadObservation.source_filename == "daily_summary.json",
            )
        )
        cell = read(session, store, source_id).cells[0]
        assert cell.value == expected
        assert cell.completion_boundary_utc == BOUNDARY


def test_new_run_can_reacquire_same_original_after_boundary(tmp_path):
    root = tmp_path / "synthetic-runtime"
    first = fetch(root, at=BOUNDARY - timedelta(hours=1))
    second = fetch(root, at=BOUNDARY + timedelta(hours=1))
    with database(root) as (session, store):
        observations = list(
            session.scalars(
                select(GarminPayloadObservation).where(
                    GarminPayloadObservation.source_filename == "daily_summary.json",
                )
            )
        )
        assert len(observations) == 2
        assert len({item.garmin_raw_payload_id for item in observations}) == 1
        assert {item.sync_run_id for item in observations} == {
            first.sync_run_id,
            second.sync_run_id,
        }
        assert session.scalar(select(func.count(Receipt.observation_id))) == 2
        cell = read(session, store).cells[0]
        assert cell.value == 17 and cell.latest_received_at == BOUNDARY + timedelta(hours=1)


def test_mismatched_returned_day_mints_no_partial_proof(tmp_path):
    root = tmp_path / "synthetic-runtime"
    previous = DAY - timedelta(days=1)
    fetch(root, days=2, payload={"calendarDate": previous.isoformat(), "totalSteps": 3})
    with database(root) as (session, store):
        rows = list(
            session.scalars(
                select(GarminPayloadObservation).where(
                    GarminPayloadObservation.source_filename == "daily_summary.json",
                )
            )
        )
        assert len(rows) == 2
        by_requested = {
            item.source_window_start_utc.date(): session.get(Receipt, item.id) for item in rows
        }
        assert by_requested[previous] is not None
        assert by_requested[DAY] is None
        cell = read(session, store, start=previous).cells[0]
        # Equal observed times: a latest unproven competitor is never removed by the join.
        assert cell.state == "ambiguous" and cell.value is None


@pytest.mark.parametrize("corruption", ["version", "day", "method", "surface", "typed_date"])
def test_present_corrupt_receipt_cannot_fall_back_to_legacy_success(saved_database, corruption):
    session, store = saved_database
    saved = legacy_acquire(session, store)
    fields = dict(
        observation_id=saved.observation.id,
        contract_version=RECEIPT_VERSION,
        surface="daily_summary",
        method="get_user_summary",
        requested_date=DAY.isoformat(),
        original_calendar_date=DAY.isoformat(),
    )
    if corruption == "version":
        fields["contract_version"] = "unknown-receipt-version"
    elif corruption == "day":
        fields["requested_date"] = fields["original_calendar_date"] = (
            DAY + timedelta(days=1)
        ).isoformat()
    elif corruption in {"method", "surface"}:
        fields[corruption] = "other"
    else:
        fields["requested_date"] = fields["original_calendar_date"] = "not-a-date"
    # A deliberately corrupt synthetic database; normal CHECKs reject these rows.
    session.connection().exec_driver_sql("PRAGMA ignore_check_constraints=ON")
    session.execute(
        text("""INSERT INTO garmin_daily_summary_acquisition_receipts
        (observation_id,contract_version,surface,method,requested_date,original_calendar_date)
        VALUES (:observation_id,:contract_version,:surface,:method,
                :requested_date,:original_calendar_date)
    """),
        fields,
    )
    session.connection().exec_driver_sql("PRAGMA ignore_check_constraints=OFF")
    session.commit()
    result = read(session, store, saved.source.id)
    assert result.cells[0].value is None
    assert result.search_complete == (corruption != "typed_date")
    assert result.cells[0].reason == (
        "acquisition_receipt_unreadable"
        if corruption == "typed_date"
        else "latest_acquisition_unproven"
    )


def test_additive_migration_preserves_old_partial_and_creates_no_receipts(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "synthetic-runtime"))
    config = _alembic_config(paths)
    command.upgrade(config, "0015_candidate_metadata_origins")
    engine = create_sqlite_engine(paths)
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            store = ContentAddressedGarminPayloadStore(paths.root / "artifacts")
            saved = legacy_acquire(session, store, status="partial")
            identity = (saved.observation.id, saved.observation.observation_key)
        command.upgrade(config, "head")
        with factory() as session:
            assert session.scalar(select(func.count(Receipt.observation_id))) == 0
            observation = session.get(GarminPayloadObservation, identity[0])
            assert observation.observation_key == identity[1]
            assert read(session, store, observation.garmin_source_id).cells[0].value is None
        inspector = inspect(engine)
        assert inspector.get_pk_constraint(Receipt.__tablename__)["constrained_columns"] == [
            "observation_id"
        ]
        foreign = inspector.get_foreign_keys(Receipt.__tablename__)
        assert len(foreign) == 1 and foreign[0]["referred_table"] == "garmin_payload_observations"
        assert foreign[0]["options"]["ondelete"] == "RESTRICT"
        assert {c["name"] for c in inspector.get_columns(Receipt.__tablename__)} == set(
            Receipt.__table__.columns.keys()
        )
        with engine.connect() as connection:
            assert not list(connection.exec_driver_sql("PRAGMA foreign_key_check"))
        command.downgrade(config, "0015_candidate_metadata_origins")
        assert Receipt.__tablename__ not in inspect(engine).get_table_names()
        command.upgrade(config, "head")
    finally:
        engine.dispose()


@pytest.mark.parametrize("action", ["update", "delete", "duplicate", "foreign", "method", "day"])
def test_receipt_schema_rejects_mutation_and_invalid_identity(tmp_path, action):
    root = tmp_path / "synthetic-runtime"
    fetch(root)
    with database(root) as (session, _store):
        receipt = session.scalar(select(Receipt))
        fields = {
            column.name: getattr(receipt, column.name) for column in Receipt.__table__.columns
        }
        if action in {"method", "day"}:
            old = legacy_acquire(session, _store, 9, account="other-account")
            fields["observation_id"] = old.observation.id
            if action == "method":
                fields["method"] = "other"
            else:
                fields["requested_date"] = DAY + timedelta(days=1)
        with pytest.raises(IntegrityError), session.begin_nested():
            if action == "update":
                session.execute(
                    text(f"UPDATE {Receipt.__tablename__} SET contract_version='changed'")
                )
            elif action == "delete":
                session.delete(receipt)
                session.flush()
            else:
                if action == "foreign":
                    fields["observation_id"] = "missing-observation"
                session.execute(Receipt.__table__.insert().values(**fields))
        session.rollback()


@contextmanager
def active_run(root):
    settings = Settings(data_dir=root)
    paths = prepare_runtime(settings)
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            provenance = repositories_for(session)
            provider = provenance.providers.get_or_create("garmin_connect", "Garmin", "wearable")
            run = provenance.sync.create_run(
                provider_id=provider.id,
                stream_code="garmin_incremental",
                requested_start=datetime(DAY.year, DAY.month, DAY.day, tzinfo=UTC),
                requested_end=datetime(DAY.year, DAY.month, DAY.day, tzinfo=UTC)
                + timedelta(days=1),
            )
            session.commit()
            provider_id, run_id = provider.id, run.id
        yield (
            settings,
            factory,
            ContentAddressedGarminPayloadStore(root / "artifacts"),
            provider_id,
            run_id,
        )
    finally:
        engine.dispose()


def attempt(settings, factory, store, provider_id, run_id, at, payload):
    surface = sync.PRODUCTION_SYNC_SURFACES[0]
    return sync.GarminIncrementalSync(
        settings,
        client=_steps_client(payload),
        clock=lambda: at,
    )._sync_surface(
        factory,
        store,
        provider_id=provider_id,
        sync_run_id=run_id,
        surface=surface,
        day=DAY,
        window_start=DAY,
        window_end=DAY,
        trailing_window_days=1,
        budget=sync._SyncBudget(),
    )


@pytest.mark.parametrize("legacy_without_receipt", [False, True])
def test_same_key_replay_preserves_chronology_and_cannot_add_old_proof(
    tmp_path, legacy_without_receipt
):
    root = tmp_path / "synthetic-runtime"
    payload = {"calendarDate": DAY.isoformat(), "totalSteps": 17}
    before, after = BOUNDARY - timedelta(hours=1), BOUNDARY + timedelta(hours=1)
    with active_run(root) as (settings, factory, store, provider_id, run_id):
        if legacy_without_receipt:
            surface = sync.PRODUCTION_SYNC_SURFACES[0]
            identity = sync._source_identity_for(payload)
            normalized = sync.normalize_garmin_payload(
                sync._normalize_provider_payload(surface, payload, day=DAY),
                stream=surface.stream,
                source_identity=identity,
            )
            normalized = sync._prepare_normalization_result(surface, payload, normalized, day=DAY)
            with factory() as session:
                GarminPersistenceRepository(session, payload_store=store).persist_result(
                    normalized,
                    payload=sync._payload_bytes(payload),
                    sync_run_id=run_id,
                    source_filename="daily_summary.json",
                    received_at=before,
                    source_window_start_utc=sync._day_bounds(DAY)[0],
                    source_window_end_utc=sync._day_bounds(DAY)[1],
                )
                session.commit()
        else:
            assert (
                attempt(settings, factory, store, provider_id, run_id, before, payload).status
                is sync.GarminSyncStatus.SUCCEEDED
            )
        replay = attempt(settings, factory, store, provider_id, run_id, after, payload)
        assert replay.replayed
        with factory() as session:
            repositories_for(session).sync.finish_run(run_id, status="partial")
            session.commit()
            observations = list(session.scalars(select(GarminPayloadObservation)))
            assert len(observations) == 1
            assert observations[0].received_at.replace(tzinfo=UTC) == before
            assert session.scalar(select(func.count(Receipt.observation_id))) == (
                0 if legacy_without_receipt else 1
            )
            cell = read(session, store, observations[0].garmin_source_id).cells[0]
            assert cell.value is None and cell.reason == "no_post_boundary_acquisition"


@pytest.mark.parametrize("failure", ["callback", "receipt", "checkpoint", "commit"])
def test_attempt_rolls_back_receipt_and_success_rows_but_preserves_previous_attempt(
    tmp_path,
    monkeypatch,
    failure,
):
    root = tmp_path / "synthetic-runtime"
    original_record = sync.record_daily_summary_acquisition
    original_project = SavedDailyStepsRepository.project_saved_summary
    original_checkpoint = sync.GarminIncrementalSync._write_checkpoint
    original_commit = Session.commit

    def record(session, outcome, **kwargs):
        result = original_record(session, outcome, **kwargs)
        if kwargs["requested_date"] == DAY:
            if failure == "receipt":
                raise RuntimeError("synthetic receipt failure")
            session.info["receipt-fail-commit"] = failure == "commit"
        return result

    def project(repository, *args, **kwargs):
        result = original_project(repository, *args, **kwargs)
        if result.calendar_date == DAY and failure == "callback":
            raise RuntimeError("synthetic callback failure")
        return result

    def checkpoint(ingester, session, **kwargs):
        result = original_checkpoint(ingester, session, **kwargs)
        if (
            kwargs["day"] == DAY
            and kwargs["surface"].code == "daily_summary"
            and kwargs["acquisition_source_id"] is not None
            and failure == "checkpoint"
        ):
            raise RuntimeError("synthetic success-checkpoint failure")
        return result

    def commit(session):
        if session.info.get("receipt-fail-commit"):
            raise RuntimeError("synthetic commit failure")
        return original_commit(session)

    monkeypatch.setattr(sync, "record_daily_summary_acquisition", record)
    monkeypatch.setattr(SavedDailyStepsRepository, "project_saved_summary", project)
    monkeypatch.setattr(sync.GarminIncrementalSync, "_write_checkpoint", checkpoint)
    monkeypatch.setattr(Session, "commit", commit)
    report = fetch(
        root, partial=False, days=2, payload=lambda day: {"calendarDate": day, "totalSteps": 17}
    )
    assert report.status is sync.GarminSyncStatus.PARTIAL
    with database(root) as (session, store):
        observations = list(
            session.scalars(
                select(GarminPayloadObservation).where(
                    GarminPayloadObservation.source_filename == "daily_summary.json",
                )
            )
        )
        assert len(observations) == 1
        assert session.scalar(select(func.count(Receipt.observation_id))) == 1
        assert session.get(Receipt, observations[0].id) is not None
        previous = DAY - timedelta(days=1)
        cells = read(session, store, observations[0].garmin_source_id, start=previous).cells
        assert cells[0].value == 17 and cells[1].value is None
        state = session.scalar(
            select(SyncStreamState).where(SyncStreamState.stream_code == "daily_summary")
        )
        assert state.cursor == previous.isoformat()
        assert session.get(SyncRun, report.sync_run_id).completed_at is not None
        # The separate existing failure checkpoint is allowed; success rows are not.
        failed = [
            item
            for item in report.attempts
            if item.surface == "daily_summary" and item.day == DAY.isoformat()
        ]
        assert len(failed) == 1 and failed[0].status is sync.GarminSyncStatus.FAILED


@pytest.mark.parametrize(
    "cap,reason",
    [
        ("MAX_PROVENANCE", "provenance_limit_exceeded"),
        ("MAX_CANDIDATES", "candidate_limit_exceeded"),
        ("MAX_ARTIFACTS", "artifact_limit_exceeded"),
    ],
)
@pytest.mark.parametrize("count", [1, 2, 3])
def test_receipt_outer_join_preserves_cap_minus_exact_plus_one(
    tmp_path, monkeypatch, cap, reason, count
):
    monkeypatch.setattr(reader, cap, 2)
    with active_run(tmp_path / "synthetic-runtime") as (settings, factory, store, provider, run):
        for index in range(count):
            result = attempt(
                settings,
                factory,
                store,
                provider,
                run,
                BOUNDARY,
                {"calendarDate": DAY.isoformat(), "totalSteps": 17, "extra": index},
            )
            assert result.status is sync.GarminSyncStatus.SUCCEEDED
        with factory() as session:
            repositories_for(session).sync.finish_run(run, status="partial")
            session.commit()
            assert session.scalar(select(func.count(Receipt.observation_id))) == count
            result = read(session, store)
            assert result.search_complete == (count <= 2)
            assert result.provenance_examined == count
            if count > 2:
                assert result.reason == reason and result.cells[0].value is None
            else:
                assert result.cells[0].value == 17
                assert len(result.cells[0].evidence) == count


@pytest.mark.parametrize(
    "latest,state,value",
    [
        (3, "value", 3),
        (0, "value", 0),
        (ABSENT, "missing", None),
        (None, "null", None),
        (True, "invalid", None),
    ],
)
def test_latest_receipt_preserves_lower_and_unknown_states(tmp_path, latest, state, value):
    with active_run(tmp_path / "synthetic-runtime") as (settings, factory, store, provider, run):
        for count, at in [(100, BOUNDARY), (latest, BOUNDARY + timedelta(hours=1))]:
            payload = {"calendarDate": DAY.isoformat()}
            if count is not ABSENT:
                payload["totalSteps"] = count
            assert (
                attempt(settings, factory, store, provider, run, at, payload).status
                is sync.GarminSyncStatus.SUCCEEDED
            )
        with factory() as session:
            repositories_for(session).sync.finish_run(run, status="partial")
            session.commit()
            cell = read(session, store).cells[0]
            assert (cell.state, cell.value) == (state, value)
            assert len(cell.evidence) == 2
            assert all(item.acquisition_proven for item in cell.evidence)


@pytest.mark.parametrize("mismatch", ["missing_start", "reversed", "short_end", "provider"])
def test_mint_rejects_run_window_or_provider_mismatch_atomically(tmp_path, mismatch):
    with active_run(tmp_path / "synthetic-runtime") as (settings, factory, store, provider, run):
        with factory() as session:
            row = session.get(SyncRun, run)
            if mismatch == "missing_start":
                row.requested_start = None
            elif mismatch == "reversed":
                row.requested_start = row.requested_end
            elif mismatch == "short_end":
                row.requested_end -= timedelta(microseconds=1)
            else:
                other = repositories_for(session).providers.get_or_create(
                    "other", "Other", "wearable"
                )
                row.provider_id = other.id
            session.commit()
        result = attempt(
            settings,
            factory,
            store,
            provider,
            run,
            BOUNDARY,
            {"calendarDate": DAY.isoformat(), "totalSteps": 17},
        )
        assert result.status is sync.GarminSyncStatus.FAILED
        with factory() as session:
            assert session.scalar(select(func.count(Receipt.observation_id))) == 0
            assert session.scalar(select(func.count(GarminPayloadObservation.id))) == 0


def test_future_historical_fetch_receipt_does_not_activate_steps_projection(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("historical acquisition cannot activate the normal Steps callback")

    monkeypatch.setattr(SavedDailyStepsRepository, "project_saved_summary", forbidden)
    root = tmp_path / "synthetic-runtime"
    report = GarminHistoricalBackfill(
        Settings(data_dir=root),
        client=_steps_client({"calendarDate": DAY.isoformat(), "totalSteps": 17}),
        clock=lambda: BOUNDARY,
    ).run(start=DAY, end=DAY, streams=["daily_summary"])
    assert report.status is sync.GarminSyncStatus.SUCCEEDED
    with database(root) as (session, store):
        assert session.scalar(select(func.count(Receipt.observation_id))) == 1
        cell = read(session, store).cells[0]
        assert cell.value == 17 and cell.evidence[0].acquisition_proof == "daily_summary_receipt"


# Opt-in reacquisition uses real persistence/reader boundaries and generated data.
REPAIR_CLOCK = NOW + timedelta(days=10)


def _repair_payload(day, value=10001):
    payload = {"calendarDate": day, "userActivitySummary": {"totalKilocalories": 42}}
    if value is not ABSENT:
        payload["totalSteps"] = value
    return payload


def _repair_seed(root, *, days=1, status="partial"):
    from healthcheck.garmin.normalization import garmin_source_identity, normalize_garmin_payload

    surface = next(x for x in sync.PRODUCTION_SYNC_SURFACES if x.code == "daily_summary")
    migrate_database(prepare_runtime(Settings(data_dir=root)))
    identity = garmin_source_identity(source_kind="provider")
    writer = GarminHistoricalBackfill(Settings(data_dir=root)).ingest
    ids = []
    # Generic pre-receipt persistence creates a real legacy spine. No receipt is
    # inserted/deleted and no immutable trigger is disabled to manufacture it.
    with database(root) as (session, store):
        provenance = repositories_for(session)
        provider = provenance.providers.get_or_create(
            "garmin_connect", "Garmin Connect", "wearable"
        )
        run = provenance.sync.create_run(
            provider_id=provider.id,
            stream_code="garmin_historical",
            requested_start=sync._day_bounds(DAY)[0],
            requested_end=sync._day_bounds(DAY + timedelta(days=days - 1))[1],
        )
        for i in range(days):
            day = DAY + timedelta(days=i)
            payload = _repair_payload(day.isoformat())
            normalized = normalize_garmin_payload(
                sync._normalize_provider_payload(surface, payload, day=day),
                stream=surface.stream,
                source_identity=identity,
            )
            normalized = sync._prepare_normalization_result(surface, payload, normalized, day=day)
            outcome = GarminPersistenceRepository(session, payload_store=store).persist_result(
                normalized,
                payload=sync._payload_bytes(payload),
                stream_code=surface.stream,
                source_identity=identity,
                received_at=NOW,
                source_window_start_utc=sync._day_bounds(day)[0],
                source_window_end_utc=sync._day_bounds(day)[1],
                sync_run_id=run.id,
                source_filename="daily_summary.json",
                collection_scope=sync._collection_scope(
                    surface,
                    day=day,
                    window_start=day,
                    window_end=day,
                    fetch_complete=True,
                    coverage_status="present",
                ),
            )
            writer._write_checkpoint(
                session,
                provider_id=provider.id,
                acquisition_source_id=outcome.source.acquisition_source_id,
                surface=surface,
                day=day,
                window_start=day,
                window_end=day,
                trailing_window_days=7,
                coverage_status="present",
                observed_count=len(outcome.records),
                succeeded=True,
                diagnostic="valid",
            )
            source_id = outcome.source.id
            ids.append(outcome.observation.id)
        provenance.sync.finish_run(
            run.id,
            status=status,
            error_category="request_budget_exhausted",
            diagnostic_reason="request_budget_exhausted",
        )
        run_id = run.id
        session.commit()
    return source_id, run_id, ids


def _repair_run(root, source_id, client, *, days=1, at=REPAIR_CLOCK, **kwargs):
    operation = GarminHistoricalBackfill(
        Settings(data_dir=root), client=client, clock=lambda: at, **kwargs
    )
    return operation.run(
        start=DAY,
        end=DAY + timedelta(days=days - 1),
        streams=["daily_summary"],
        reacquire_unproven_daily_summary=True,
        garmin_source_id=source_id,
    )


def _repair_counts(session):
    from healthcheck.db.models import (
        GarminRawPayload,
        GarminRecordMetric,
        GarminSourceRecord,
        RawArtifact,
    )

    return {
        m.__tablename__: session.scalar(select(func.count()).select_from(m))
        for m in (
            GarminRawPayload,
            RawArtifact,
            GarminSourceRecord,
            GarminRecordMetric,
            GarminPayloadObservation,
            Receipt,
        )
    }


def test_reacquire_legacy_present_current_same_bytes_and_resume(tmp_path):
    root = tmp_path / "synthetic-runtime"
    source, old_run, old_ids = _repair_seed(root)
    default_client = _steps_client(_repair_payload)
    for reprocess in (False, True):
        default = GarminHistoricalBackfill(
            Settings(data_dir=root), client=default_client, clock=lambda: REPAIR_CLOCK
        ).run(start=DAY, end=DAY, streams=["daily_summary"], reprocess=reprocess)
        assert default.request_count == 0 and default.skipped_complete_count == 1
    assert not default_client.calls
    with database(root) as (s, store):
        before = _repair_counts(s)
        assert before["garmin_record_metrics"] > 0
        assert read(s, store, source).cells[0].reason == "latest_acquisition_unproven"
    client = _steps_client(_repair_payload)
    result = _repair_run(root, source, client)
    assert result.status is sync.GarminSyncStatus.SUCCEEDED and result.request_count == 1
    assert [c[0] for c in client.calls] == ["get_user_summary"]
    assert source not in result.to_json()
    with database(root) as (s, store):
        after = _repair_counts(s)
        for table in (
            "garmin_raw_payloads",
            "raw_artifacts",
            "garmin_source_records",
            "garmin_record_metrics",
        ):
            assert after[table] == before[table]
        assert after["garmin_payload_observations"] == before["garmin_payload_observations"] + 1
        assert after["garmin_daily_summary_acquisition_receipts"] == 1
        assert s.get(SyncRun, old_run).status == "partial" and s.get(Receipt, old_ids[0]) is None
        cell = read(s, store, source, now=REPAIR_CLOCK + timedelta(seconds=1)).cells[0]
        assert cell.state == "value" and cell.value == 10001
        assert cell.latest_received_at == REPAIR_CLOCK

    def forbidden_auth():
        raise AssertionError("proven resume must not even load auth")

    resumed = _repair_run(
        root, source, None, at=REPAIR_CLOCK + timedelta(seconds=2), auth_loader=forbidden_auth
    )
    assert resumed.status is sync.GarminSyncStatus.SUCCEEDED
    assert resumed.request_count == 0 and resumed.skipped_complete_count == 1
    with database(root) as (s, _):
        assert _repair_counts(s) == after


@pytest.mark.parametrize(
    "value,state",
    [
        (0, "value"),
        (None, "null"),
        (ABSENT, "missing"),
        (True, "invalid"),
        ("10001", "invalid"),
        (-1, "invalid"),
    ],
)
def test_reacquire_keeps_field_states_and_skips_proven_nonnumeric(tmp_path, value, state):
    root = tmp_path / "synthetic-runtime"
    source, old_run, _ = _repair_seed(root)
    client = _steps_client(lambda day: _repair_payload(day, value))
    result = _repair_run(root, source, client)
    assert result.request_count == 1
    with database(root) as (s, store):
        cell = read(s, store, source, now=REPAIR_CLOCK + timedelta(seconds=1)).cells[0]
        assert cell.state == state and cell.value == (0 if state == "value" else None)
        latest = [e for e in cell.evidence if e.received_at == cell.latest_received_at]
        assert latest and all(e.acquisition_proven for e in latest)
        assert s.get(SyncRun, old_run).status == "partial"
    resumed_client = _steps_client(lambda _: (_ for _ in ()).throw(AssertionError("extra call")))
    resumed = _repair_run(root, source, resumed_client, at=REPAIR_CLOCK + timedelta(seconds=2))
    assert resumed.request_count == 0 and resumed.skipped_complete_count == 1


def test_reacquire_budget_partial_receipts_resume_only_remaining_days(tmp_path):
    root = tmp_path / "synthetic-runtime"
    source, _, _ = _repair_seed(root, days=3)
    first = _repair_run(
        root, source, _steps_client(_repair_payload), days=3, max_provider_requests=2
    )
    assert first.status is sync.GarminSyncStatus.PARTIAL
    assert first.request_count == 2 and first.abort_reason == "request_budget_exhausted"
    with database(root) as (s, store):
        cells = read(
            s, store, source, end=DAY + timedelta(days=2), now=REPAIR_CLOCK + timedelta(seconds=1)
        ).cells
        assert [c.state for c in cells] == ["value", "value", "unavailable"]
        assert s.get(SyncRun, first.sync_run_id).status == "partial"
    client = _steps_client(_repair_payload)
    second = _repair_run(root, source, client, days=3, at=REPAIR_CLOCK + timedelta(minutes=1))
    assert second.request_count == 1 and second.skipped_complete_count == 2
    assert [c[1][0] for c in client.calls] == [(DAY + timedelta(days=2)).isoformat()]


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"calendarDate": "2099-02-01", "totalSteps": 21},
        {"calendarDate": DAY.isoformat(), "totalSteps": 21, "device": {"model": "Vivoactive 5"}},
        [],
        None,
    ],
)
def test_reacquire_bad_returned_binding_stops_before_other_days(tmp_path, bad_payload):
    root = tmp_path / "synthetic-runtime"
    source, _, _ = _repair_seed(root, days=3)
    client = _steps_client(lambda _: bad_payload)
    result = _repair_run(root, source, client, days=3)
    assert result.status is sync.GarminSyncStatus.FAILED and result.request_count == 1
    assert result.attempts[0].failure_stage == "acquisition_binding"
    assert len(client.calls) == 1
    with database(root) as (s, _):
        assert s.scalar(select(func.count()).select_from(Receipt)) == 0
        assert s.scalar(select(func.count()).select_from(GarminPayloadObservation)) == 3


def test_reacquire_broken_original_fails_closed_before_auth(tmp_path):
    from healthcheck.db.models import RawArtifact

    root = tmp_path / "synthetic-runtime"
    source, _, ids = _repair_seed(root)
    with database(root) as (s, _):
        obs = s.get(GarminPayloadObservation, ids[0])
        artifact = s.get(RawArtifact, obs.raw_artifact_id)
        (root / "artifacts" / artifact.relative_storage_path).write_bytes(b"synthetic corruption")

    def forbidden_auth():
        raise AssertionError("proof search must precede auth")

    result = _repair_run(root, source, None, auth_loader=forbidden_auth)
    assert result.request_count == 0 and result.abort_reason.startswith(
        "reacquisition_proof_search_incomplete"
    )


def test_reacquire_proof_budget_is_not_reset_or_raised(tmp_path, monkeypatch):
    root = tmp_path / "synthetic-runtime"
    source, _, _ = _repair_seed(root)
    monkeypatch.setattr(reader, "MAX_PROVENANCE", 0)
    client = _steps_client(_repair_payload)
    result = _repair_run(root, source, client)
    assert result.abort_reason == "reacquisition_proof_search_incomplete:provenance_limit_exceeded"
    assert not client.calls


def test_reacquire_latest_tie_fails_closed_without_older_fallback(tmp_path):
    from healthcheck.garmin.normalization import garmin_source_identity

    root = tmp_path / "synthetic-runtime"
    source, _, _ = _repair_seed(root)
    assert _repair_run(root, source, _steps_client(_repair_payload)).request_count == 1
    with database(root) as (s, store):
        legacy_acquire(
            s,
            store,
            21,
            at=REPAIR_CLOCK,
            account=garmin_source_identity(source_kind="provider").source_instance_id,
            status="partial",
        )
    client = _steps_client(_repair_payload)
    result = _repair_run(root, source, client, at=REPAIR_CLOCK + timedelta(seconds=1))
    assert result.abort_reason == "reacquisition_latest_acquisition_ambiguous" and not client.calls


def test_reacquire_unknown_source_and_current_dates_do_not_fetch(tmp_path):
    root = tmp_path / "synthetic-runtime"
    source, _, _ = _repair_seed(root)
    client = _steps_client(_repair_payload)
    unknown = _repair_run(root, "00000000-0000-0000-0000-000000000000", client)
    assert unknown.abort_reason == "reacquisition_source_binding_invalid" and not client.calls
    future = _repair_run(root, source, client, at=BOUNDARY - timedelta(hours=1))
    assert future.abort_reason == "reacquisition_dates_not_completed" and not client.calls


@pytest.mark.parametrize("error_kind", ["auth", "http401", "http403", "mfa", "rate", "timeout"])
def test_reacquire_errors_stop_without_mass_retry(tmp_path, error_kind):
    from requests import HTTPError, Response

    from test_garmin_incremental_sync import AuthenticationError

    rate = Response()
    rate.status_code = 429

    class MFAError(Exception):
        pass

    unauthorized, forbidden = Response(), Response()
    unauthorized.status_code, forbidden.status_code = 401, 403
    errors = {
        "http401": HTTPError("synthetic unauthorized", response=unauthorized),
        "http403": HTTPError("synthetic forbidden", response=forbidden),
        "mfa": MFAError("synthetic mfa"),
        "auth": AuthenticationError("synthetic auth"),
        "rate": HTTPError("synthetic rate", response=rate),
        "timeout": TimeoutError("synthetic timeout"),
    }
    root = tmp_path / "synthetic-runtime"
    source, _, _ = _repair_seed(root, days=3)
    client = _steps_client(_repair_payload, errors={"get_user_summary": errors[error_kind]})
    result = _repair_run(root, source, client, days=3)
    assert result.request_count == 1 and len(client.calls) == 1 and result.abort_reason
    expected = {
        "auth": "authentication_failed",
        "http401": "authentication_failed",
        "http403": "authentication_failed",
        "mfa": "mfa_failed",
        "rate": "rate_limited",
        "timeout": "provider_unavailable",
    }
    assert result.attempts[0].error.error_code == expected[error_kind]
    if error_kind in {"auth", "http401", "http403", "mfa"}:
        assert result.status is sync.GarminSyncStatus.REAUTH_REQUIRED
    with database(root) as (s, _):
        assert s.scalar(select(func.count()).select_from(Receipt)) == 0


def test_reacquire_cli_dry_run_and_rejected_combinations(tmp_path, monkeypatch, capsys):
    from healthcheck import cli

    def forbidden(*args, **kwargs):
        raise AssertionError("invalid/dry request must not load auth")

    monkeypatch.setattr(cli, "GarminAuthService", forbidden)
    root = tmp_path / "not-created"
    base = [
        "garmin-backfill",
        "--data-dir",
        str(root),
        "--start",
        DAY.isoformat(),
        "--end",
        DAY.isoformat(),
        "--stream",
        "daily_summary",
        "--reacquire-unproven-daily-summary",
        "--garmin-source-id",
        "synthetic-source",
    ]
    assert cli.main([*base, "--dry-run"]) == 0
    planned = __import__("json").loads(capsys.readouterr().out)
    assert planned["backfill"]["reacquire_unproven_daily_summary"] and not root.exists()
    for extra in (
        ["--reprocess"],
        ["--stream", "heart_rate"],
        ["--end", (DAY + timedelta(days=14)).isoformat()],
    ):
        assert cli.main([*base, *extra]) == 2
        capsys.readouterr()
    assert cli.main(["garmin-sync", "--reacquire-unproven-daily-summary"]) == 2
    assert not root.exists()


def test_reacquire_seven_day_canary_real_pipeline_no_steps_projection(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("historical repair must not activate observed Steps projection")

    monkeypatch.setattr(SavedDailyStepsRepository, "project_saved_summary", forbidden)
    root = tmp_path / "synthetic-runtime"
    source, old_run, old_ids = _repair_seed(root, days=7)
    client = _steps_client(_repair_payload)
    result = _repair_run(root, source, client, days=7)
    assert result.status is sync.GarminSyncStatus.SUCCEEDED and result.request_count == 7
    assert [call[1][0] for call in client.calls] == [
        (DAY + timedelta(days=i)).isoformat() for i in range(7)
    ]
    with database(root) as (s, store):
        window = read(
            s, store, source, end=DAY + timedelta(days=6), now=REPAIR_CLOCK + timedelta(seconds=1)
        )
        assert window.search_complete and len(window.cells) == 7
        assert all(c.state == "value" and c.value == 10001 for c in window.cells)
        assert s.scalar(select(func.count()).select_from(Receipt)) == 7
        assert s.get(SyncRun, old_run).status == "partial"
        assert all(s.get(Receipt, oid) is None for oid in old_ids)
    resumed = _repair_run(
        root, source, _steps_client(_repair_payload), days=7, at=REPAIR_CLOCK + timedelta(minutes=1)
    )
    assert resumed.request_count == 0 and resumed.skipped_complete_count == 7


def test_reacquire_accepts_existing_legacy_succeeded_proof(tmp_path):
    root = tmp_path / "synthetic-runtime"
    source, _, _ = _repair_seed(root, status="succeeded")
    client = _steps_client(_repair_payload)
    result = _repair_run(root, source, client)
    assert result.status is sync.GarminSyncStatus.SUCCEEDED and result.request_count == 0
    assert not client.calls


def test_reacquire_rejects_incompatible_stored_account_before_auth(tmp_path):
    root = tmp_path / "synthetic-runtime"
    _repair_seed(root)
    with database(root) as (s, store):
        other = legacy_acquire(s, store, 21, account="synthetic-other-account", status="partial")
        source = other.source.id

    def forbidden_auth():
        raise AssertionError("incompatible source cannot authenticate/fetch")

    result = _repair_run(root, source, None, auth_loader=forbidden_auth)
    assert result.abort_reason == "reacquisition_source_binding_invalid"
    assert result.request_count == 0


def test_reacquire_cli_real_dispatch_checks_proof_before_auth(tmp_path, monkeypatch, capsys):
    import json

    from healthcheck import cli
    from healthcheck.garmin import backfill
    from healthcheck.garmin.auth import GarminAuthResult, GarminAuthStatus

    root = tmp_path / "synthetic-runtime"
    source, _, _ = _repair_seed(root)
    events = []
    client = _steps_client(_repair_payload)

    class FakeAuth:
        def __init__(self, *args, **kwargs):
            pass

        def load_existing(self):
            events.append("auth")
            return client, GarminAuthResult(status=GarminAuthStatus.AUTHENTICATED)

    original_plan = backfill.plan_daily_summary_reacquisition

    def planning(*args, **kwargs):
        events.append("proof")
        return original_plan(*args, **kwargs)

    monkeypatch.setattr(backfill, "plan_daily_summary_reacquisition", planning)
    monkeypatch.setattr(cli, "GarminAuthService", FakeAuth)
    monkeypatch.setattr(
        cli,
        "GarminHistoricalBackfill",
        lambda settings, **kwargs: GarminHistoricalBackfill(
            settings, clock=lambda: REPAIR_CLOCK, **kwargs
        ),
    )
    assert (
        cli.main(
            [
                "garmin-backfill",
                "--data-dir",
                str(root),
                "--start",
                DAY.isoformat(),
                "--end",
                DAY.isoformat(),
                "--stream",
                "daily_summary",
                "--reacquire-unproven-daily-summary",
                "--garmin-source-id",
                source,
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["backfill"]["request_count"] == 1 and events == ["proof", "auth"]
    assert source not in json.dumps(payload)


def test_reacquire_lock_preserves_single_writer(tmp_path):
    from threading import Event, Thread

    from healthcheck.external_runtime_lock import (
        ExternalRuntimeOperationBusyError,
        ExternalRuntimeOperationLock,
    )
    from healthcheck.runtime import resolve_runtime_paths

    root = tmp_path / "synthetic-runtime"
    source, _, _ = _repair_seed(root)
    paths = resolve_runtime_paths(Settings(data_dir=root))
    acquired, release = Event(), Event()
    errors = []

    def competing_writer():
        try:
            with ExternalRuntimeOperationLock(paths):
                acquired.set()
                assert release.wait(10)
        except BaseException as exc:
            errors.append(exc)

    holder = Thread(target=competing_writer)
    holder.start()
    client = _steps_client(_repair_payload)
    try:
        assert acquired.wait(5)
        with pytest.raises(ExternalRuntimeOperationBusyError):
            _repair_run(root, source, client)
        assert client.calls == []
    finally:
        release.set()
        holder.join(5)
    assert not holder.is_alive() and errors == []


def test_reacquire_lower_correction_wins_without_recertifying_old_run(tmp_path):
    root = tmp_path / "synthetic-runtime"
    source, old_run, old_ids = _repair_seed(root)
    client = _steps_client(lambda day: _repair_payload(day, 7))
    result = _repair_run(root, source, client)
    assert result.request_count == 1
    with database(root) as (session, store):
        cell = read(session, store, source, now=REPAIR_CLOCK + timedelta(seconds=1)).cells[0]
        assert cell.state == "value" and cell.value == 7
        assert cell.latest_received_at == REPAIR_CLOCK
        assert session.get(SyncRun, old_run).status == "partial"
        assert session.get(Receipt, old_ids[0]) is None


def test_reacquire_uses_one_proof_snapshot_across_chunks(tmp_path, monkeypatch):
    from healthcheck.garmin import backfill

    root = tmp_path / "synthetic-runtime"
    source, _, _ = _repair_seed(root, days=3)
    original_plan = backfill.plan_daily_summary_reacquisition
    plans = []

    def planning(*args, **kwargs):
        plans.append((kwargs["start"], kwargs["end"]))
        return original_plan(*args, **kwargs)

    monkeypatch.setattr(backfill, "plan_daily_summary_reacquisition", planning)
    client = _steps_client(_repair_payload)
    result = GarminHistoricalBackfill(
        Settings(data_dir=root), client=client, clock=lambda: REPAIR_CLOCK
    ).run(
        start=DAY,
        end=DAY + timedelta(days=2),
        streams=["daily_summary"],
        chunk_days=1,
        reacquire_unproven_daily_summary=True,
        garmin_source_id=source,
    )
    assert result.status is sync.GarminSyncStatus.SUCCEEDED and result.request_count == 3
    assert len(result.chunks) == 3 and plans == [(DAY, DAY + timedelta(days=2))]
    with database(root) as (session, store):
        cells = read(
            session,
            store,
            source,
            end=DAY + timedelta(days=2),
            now=REPAIR_CLOCK + timedelta(seconds=1),
        ).cells
        assert [c.state for c in cells] == ["value"] * 3


@pytest.mark.parametrize(
    "mismatch", ["run_provider", "event", "receipt_day", "receipt_version", "missing_run"]
)
def test_reacquire_malformed_spine_or_receipt_blocks_before_auth(tmp_path, mismatch):
    from healthcheck.db.models import IngestEvent
    from test_garmin_completed_steps import append_unproven

    root = tmp_path / "synthetic-runtime"
    source, old_run, old_ids = _repair_seed(root)
    with database(root) as (session, store):
        observation = session.get(GarminPayloadObservation, old_ids[0])
        if mismatch == "run_provider":
            other = repositories_for(session).providers.get_or_create(
                "synthetic-other", "Synthetic Other", "wearable"
            )
            session.get(SyncRun, old_run).provider_id = other.id
        elif mismatch == "event":
            session.get(IngestEvent, observation.ingest_event_id).status = "failed"
        elif mismatch == "missing_run":
            append_unproven(
                session,
                observation,
                sync_run_id=None,
                received_at=REPAIR_CLOCK - timedelta(seconds=1),
            )
        else:
            # Insert a schema-valid but semantically invalid synthetic receipt;
            # never disable append-only triggers or mutate an existing receipt.
            day = DAY + timedelta(days=1) if mismatch == "receipt_day" else DAY
            session.add(
                Receipt(
                    observation_id=observation.id,
                    contract_version="synthetic-unsupported"
                    if mismatch == "receipt_version"
                    else RECEIPT_VERSION,
                    surface="daily_summary",
                    method="get_user_summary",
                    requested_date=day,
                    original_calendar_date=day,
                )
            )
        session.commit()
        window = read(session, store, source, now=REPAIR_CLOCK)
        assert window.search_complete
        assert any(
            not e.acquisition_proven and e.reason != "acquisition_success_unproven"
            for e in window.cells[0].evidence
        )
        before = _repair_counts(session)

    def forbidden_auth():
        raise AssertionError("malformed proof must block before auth/fetch")

    result = _repair_run(root, source, None, auth_loader=forbidden_auth)
    assert result.request_count == 0
    assert result.abort_reason == "reacquisition_acquisition_metadata_invalid"
    with database(root) as (session, _):
        assert _repair_counts(session) == before
        assert session.get(SyncRun, old_run).status == "partial"


@pytest.mark.parametrize("status", ["partial", "failed", "running"])
def test_reacquire_clean_unproven_run_remains_reacquirable(tmp_path, status):
    root = tmp_path / "synthetic-runtime"
    source, old_run, old_ids = _repair_seed(root, status=status)
    if status == "running":
        with database(root) as (session, _):
            session.get(SyncRun, old_run).completed_at = None
            session.commit()
    result = _repair_run(root, source, _steps_client(_repair_payload))
    assert result.status is sync.GarminSyncStatus.SUCCEEDED and result.request_count == 1
    with database(root) as (session, store):
        assert session.get(SyncRun, old_run).status == status
        assert session.get(Receipt, old_ids[0]) is None
        cell = read(session, store, source, now=REPAIR_CLOCK + timedelta(seconds=1)).cells[0]
        assert cell.state == "value" and cell.latest_received_at == REPAIR_CLOCK


@pytest.mark.parametrize("status", ["failed", "running", "partial_unfinished"])
@pytest.mark.parametrize("receipt_kind", ["valid", "wrong_day", "unsupported_version"])
def test_reacquire_unproven_existing_receipt_always_blocks_before_auth(
    tmp_path, status, receipt_kind
):
    root = tmp_path / "synthetic-runtime"
    run_status = "partial" if status == "partial_unfinished" else status
    source, old_run, old_ids = _repair_seed(root, status=run_status)
    with database(root) as (session, store):
        if status in {"running", "partial_unfinished"}:
            session.get(SyncRun, old_run).completed_at = None
        day = DAY + timedelta(days=1) if receipt_kind == "wrong_day" else DAY
        session.add(
            Receipt(
                observation_id=old_ids[0],
                contract_version="synthetic-unsupported"
                if receipt_kind == "unsupported_version"
                else RECEIPT_VERSION,
                surface="daily_summary",
                method="get_user_summary",
                requested_date=day,
                original_calendar_date=day,
            )
        )
        session.commit()
        cell = read(session, store, source, now=REPAIR_CLOCK).cells[0]
        assert cell.evidence[0].reason == "acquisition_success_unproven"
        assert cell.evidence[0].acquisition_receipt_version is not None
        before = _repair_counts(session)

    def forbidden_auth():
        raise AssertionError("unproven existing receipt requires separate diagnosis")

    result = _repair_run(root, source, None, auth_loader=forbidden_auth)
    assert result.request_count == 0
    assert result.abort_reason == "reacquisition_acquisition_metadata_invalid"
    with database(root) as (session, _):
        assert _repair_counts(session) == before
        assert session.get(SyncRun, old_run).status == run_status
