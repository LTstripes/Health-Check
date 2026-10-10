"""Real compound readers versus a deterministic, separate SQLite WAL writer."""

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError

from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.models import ImportCandidate, Provider
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.ingestion.photo.service import PhotoImportService, PhotoUpload
from healthcheck.ingestion.photo.synthetic import encode_synthetic_png, weigh_in_payload
from healthcheck.runtime import prepare_runtime
from healthcheck.web.period_brief_query import PeriodBriefService
from healthcheck.web.query import WeightQueryService
from healthcheck.web.read_snapshot import ensure_read_snapshot

DAY = date(2099, 1, 7)
PERIOD = {"start_date": DAY, "end_date": DAY}


@pytest.fixture
def pending_import(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    extractor = FakeImageMeasurementExtractor()
    try:
        with session_scope(engine) as session:
            imported = PhotoImportService(session, paths, extractor).import_photos(
                [
                    PhotoUpload(
                        "synthetic.png",
                        encode_synthetic_png(
                            weigh_in_payload(source_local_date=DAY, weight_kg=80.0)
                        ),
                    )
                ]
            )
            candidate_ids = imported.items[0].candidate_ids
        commits = []

        def confirm():
            # A second physical connection commits while the reader is still open.
            # No sleeps, scheduler timing, network or mocked query results.
            with session_scope(engine) as writer:
                PhotoImportService(writer, paths, extractor).confirm(candidate_ids)
            commits.append(True)

        yield engine, settings, confirm, commits
    finally:
        engine.dispose()


@pytest.mark.parametrize("method", ["series", "summary", "dashboard"])
def test_weight_snapshot_across_canonical_commit(pending_import, monkeypatch, method):
    engine, settings, confirm, commits = pending_import
    with session_scope(engine) as reader:
        service = WeightQueryService(reader, settings)
        original = service._current_records

        def read_then_confirm(**kwargs):
            records = original(**kwargs)
            confirm()
            return records

        monkeypatch.setattr(service, "_current_records", read_then_confirm)
        payload = getattr(service, method)(**PERIOD)
        assert commits == [True]  # Writer committed before the compound read completed.
        # Only two atomic states exist: no weight/no canonical, or weight/canonical.
        assert payload["current"]["value_kg"] is None
        assert payload["canonical"]["available"] is False
        assert payload["canonical"]["selection_count"] == 0
    with session_scope(engine) as reader:
        after = getattr(WeightQueryService(reader, settings), method)(**PERIOD)
        assert after["current"]["value_kg"] == 80.0
        assert after["canonical"]["selection_count"] == 1


@pytest.mark.parametrize("method", ["brief", "dashboard"])
def test_outer_snapshot_across_import_confirmation(pending_import, monkeypatch, method):
    engine, settings, confirm, commits = pending_import
    with session_scope(engine) as reader:
        if method == "brief":
            service = PeriodBriefService(reader, settings)
            weight = service.weight
            boundary = "summary"
        else:
            service = weight = WeightQueryService(reader, settings)
            boundary = "_payload"
        original = getattr(weight, boundary)

        def read_then_confirm(**kwargs):
            result = original(**kwargs)
            confirm()
            return result

        monkeypatch.setattr(weight, boundary, read_then_confirm)
        if method == "brief":
            packet = service.build(**PERIOD)
            facts = packet["sections"]["weight"]["summary_facts"]
            assert next(f["value"] for f in facts if f["code"] == "weight_observation_count") == 0
            queue = packet["sections"]["data_quality"]["import_queue"]
        else:
            packet = service.dashboard(**PERIOD)
            assert packet["current"]["value_kg"] is None
            queue = packet["imports"]
        assert commits == [True]
        assert queue["pending_candidate_count"] == 1
        assert queue["confirmed_candidate_count"] == 0
    with session_scope(engine) as reader:
        queue = WeightQueryService(reader, settings).import_queue_summary()
        assert queue["pending_candidate_count"] == 0
        assert queue["confirmed_candidate_count"] == 1


def test_import_queue_snapshot_between_batches_and_candidates(pending_import, monkeypatch):
    engine, settings, confirm, commits = pending_import
    with session_scope(engine) as reader:
        service = WeightQueryService(reader, settings)
        original = service.repos.ingest_batches.list_recent

        def read_then_confirm(**kwargs):
            batches = original(**kwargs)
            confirm()
            return batches

        monkeypatch.setattr(service.repos.ingest_batches, "list_recent", read_then_confirm)
        queue = service.import_queue_summary()
        assert commits == [True]
        assert queue["pending_candidate_count"] == 1
        assert queue["confirmed_candidate_count"] == 0


def test_new_snapshot_expires_entities_from_previous_transaction(pending_import):
    engine, settings, confirm, _commits = pending_import
    with session_scope(engine) as reader:
        cached = reader.scalar(select(ImportCandidate))
        assert cached.user_decision == "pending"
        # SQLAlchemy's non-expiring factory retains this entity after commit.
        reader.commit()
        confirm()
        assert cached.user_decision == "pending"
        queue = WeightQueryService(reader, settings).import_queue_summary()
        assert queue["confirmed_candidate_count"] == 1
        assert cached.user_decision == "confirmed"


def test_existing_physical_transaction_is_reused_until_caller_ends_it(pending_import):
    engine, settings, confirm, commits = pending_import
    with session_scope(engine) as reader:
        connection = reader.connection()
        connection.exec_driver_sql("BEGIN")
        cached = reader.scalar(select(ImportCandidate))  # Establish the caller's snapshot.
        confirm()
        service = WeightQueryService(reader, settings)
        assert service.import_queue_summary()["pending_candidate_count"] == 1
        assert service.dashboard(**PERIOD)["canonical"]["available"] is False
        assert cached.user_decision == "pending"
        assert commits == [True]
        assert connection.connection.driver_connection.in_transaction
        reader.rollback()
        assert service.import_queue_summary()["confirmed_candidate_count"] == 1


@pytest.mark.parametrize("commit_before_begin", [False, True])
@pytest.mark.parametrize("method", ["queue", "dashboard", "brief"])
def test_caller_snapshot_expires_pre_begin_cached_candidate(
    pending_import, commit_before_begin, method
):
    engine, settings, confirm, commits = pending_import
    with session_scope(engine) as reader:
        cached = reader.scalar(select(ImportCandidate))
        candidate_id = cached.id
        assert cached.user_decision == "pending"
        if commit_before_begin:
            reader.commit()  # expire_on_commit=False retains the old entity.
        connection = reader.connection()
        assert not connection.connection.driver_connection.in_transaction
        confirm()
        assert commits == [True]
        connection.exec_driver_sql("BEGIN")
        # Establish and inspect the caller's physical snapshot without refreshing ORM state.
        assert (
            connection.exec_driver_sql(
                "SELECT user_decision FROM import_candidates WHERE id = ?", (candidate_id,)
            ).scalar_one()
            == "confirmed"
        )
        assert cached.user_decision == "pending"
        transaction = reader.get_transaction()

        if method == "brief":
            packet = PeriodBriefService(reader, settings).build(**PERIOD)
            queue = packet["sections"]["data_quality"]["import_queue"]
        elif method == "dashboard":
            queue = WeightQueryService(reader, settings).dashboard(**PERIOD)["imports"]
        else:
            queue = WeightQueryService(reader, settings).import_queue_summary()

        assert queue["pending_candidate_count"] == 0
        assert queue["confirmed_candidate_count"] == 1
        assert cached.user_decision == "confirmed"
        assert reader.get_transaction() is transaction
        assert connection.connection.driver_connection.in_transaction


def test_read_does_not_commit_or_rollback_callers_flushed_write(pending_import):
    engine, settings, _confirm, _commits = pending_import
    with session_scope(engine) as reader:
        provider = Provider(
            code="synthetic-snapshot", display_name="Synthetic", provider_kind="device_vendor"
        )
        reader.add(provider)
        reader.flush()
        service = WeightQueryService(reader, settings)
        assert service.import_queue_summary()["pending_candidate_count"] == 1
        assert reader.get(Provider, provider.id) is provider
        with session_scope(engine) as observer:
            assert observer.get(Provider, provider.id) is None
        reader.rollback()
    with session_scope(engine) as observer:
        assert (
            observer.scalar(select(Provider).where(Provider.code == "synthetic-snapshot")) is None
        )


def test_new_snapshot_does_not_discard_pending_changes(pending_import):
    engine, _settings, _confirm, _commits = pending_import
    with session_scope(engine) as reader:
        cached = reader.scalar(select(ImportCandidate))
        cached.user_decision = "rejected"
        with pytest.raises(InvalidRequestError, match="pending session changes"):
            ensure_read_snapshot(reader)
        assert cached in reader.dirty
        assert cached.user_decision == "rejected"
        reader.rollback()


@pytest.mark.parametrize("physical_transaction", [False, True])
@pytest.mark.parametrize("pending_state", ["new", "dirty", "deleted"])
def test_snapshot_entry_preserves_pending_caller_state(
    pending_import, physical_transaction, pending_state
):
    engine, settings, _confirm, _commits = pending_import
    with session_scope(engine) as reader:
        cached = reader.scalar(select(ImportCandidate))
        connection = reader.connection()
        if physical_transaction:
            connection.exec_driver_sql("BEGIN")
        transaction = reader.get_transaction()
        if pending_state == "new":
            changed = Provider(
                code="synthetic-pending", display_name="Synthetic", provider_kind="device_vendor"
            )
            reader.add(changed)
        elif pending_state == "dirty":
            changed = cached
            cached.user_decision = "rejected"
        else:
            changed = cached
            reader.delete(cached)

        with pytest.raises(InvalidRequestError, match="pending session changes"):
            WeightQueryService(reader, settings).import_queue_summary()

        assert changed in getattr(reader, pending_state)
        assert cached.user_decision == ("rejected" if pending_state == "dirty" else "pending")
        assert reader.get_transaction() is transaction
        assert connection.connection.driver_connection.in_transaction is physical_transaction
        # Only the caller may decide to discard its pending changes.
        reader.rollback()


def test_failed_compound_read_releases_snapshot_and_session_can_be_reused(
    pending_import, monkeypatch
):
    engine, settings, confirm, _commits = pending_import
    with pytest.raises(RuntimeError, match="synthetic read failure"):
        with session_scope(engine) as reader:
            service = PeriodBriefService(reader, settings)

            def fail(**kwargs):
                assert reader.connection().connection.driver_connection.in_transaction
                raise RuntimeError("synthetic read failure")

            monkeypatch.setattr(service.sleep, "report", fail)
            service.build(**PERIOD)
    assert not reader.in_transaction()
    confirm()
    with session_scope(engine) as reader:
        assert WeightQueryService(reader, settings).summary(**PERIOD)["current"]["value_kg"] == 80.0


def test_295_brief_and_reused_charts_share_snapshot_across_writer_commit(
    pending_import, monkeypatch,
):
    from healthcheck.web.overview_charts import read_overview_charts

    engine, settings, confirm, commits = pending_import
    with session_scope(engine) as reader:
        service = PeriodBriefService(reader, settings)
        original = service.weight.summary

        def read_then_confirm(**kwargs):
            result = original(**kwargs)
            confirm()
            return result

        monkeypatch.setattr(service.weight, "summary", read_then_confirm)
        result, inputs = service.build_with_chart_inputs(**PERIOD)
        charts = read_overview_charts(
            reader, settings, packet=result["packet"], selected_id=inputs.selected_id,
            brief_inputs=inputs,
        )
        assert commits == [True]
        assert charts["weight_current"]["value_kg"] is None
        assert charts["weight"]["points"] == []
        assert result["packet"]["sections"]["data_quality"]["import_queue"][
            "pending_candidate_count"] == 1
    with session_scope(engine) as reader:
        result, inputs = PeriodBriefService(reader, settings).build_with_chart_inputs(**PERIOD)
        charts = read_overview_charts(
            reader, settings, packet=result["packet"], selected_id=inputs.selected_id,
            brief_inputs=inputs,
        )
        assert charts["weight_current"]["value_kg"] == 80.0
        assert len(charts["weight"]["points"]) == 1
