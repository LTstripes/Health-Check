from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.models import (
    AcquisitionSource,
    ImportCandidate,
    ImportCandidateEdit,
    IngestEvent,
    MeasurementSession,
    ScalarMeasurement,
)
from healthcheck.ingestion.photo.errors import PhotoImportError
from healthcheck.ingestion.photo.extractor import ExtractionFailure
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.ingestion.photo.service import PhotoImportService, PhotoUpload
from healthcheck.ingestion.photo.synthetic import encode_synthetic_png, weigh_in_payload
from healthcheck.logging import configure_logging
from healthcheck.runtime import prepare_runtime
from healthcheck.web.ui_app import create_ui_app


def _service_call(engine, paths, extractor, callback):
    with session_scope(engine) as session:
        return callback(PhotoImportService(session, paths, extractor))


def _count(session, model) -> int:
    return int(session.scalar(select(func.count(model.id))) or 0)


@pytest.fixture
def photo_env(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    extractor = FakeImageMeasurementExtractor()
    try:
        yield settings, paths, engine, extractor
    finally:
        engine.dispose()


SECRET_TEXT = "WEIGHT_SECRET_77.77"


class _FailingExtractor:
    name = "failing-extractor"
    version = "9"
    model_name = "none"
    model_version = "9"
    prompt_version = None

    def extract(self, request, image_bytes):
        del request, image_bytes
        raise ExtractionFailure(
            "extractor_empty_result", "extractor returned no measurement groups"
        )


def _upload(payload, name="shot.png") -> list[PhotoUpload]:
    return [PhotoUpload(name, encode_synthetic_png(payload))]


def test_conflicting_candidate_dates_fail_atomically(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(
        source_local_date=date(2026, 1, 7), weight_kg=79.4, body_fat_pct=23.1
    )
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )

    def attempt(service: PhotoImportService):
        views = [
            service.candidate_view(service._load_candidate(item_id))
            for item_id in imported.items[0].candidate_ids
        ]
        weight = next(view for view in views if view["metric_code"] == "weight")
        fat = next(view for view in views if view["metric_code"] == "body_fat_pct")
        service.edit_pending(weight["id"], edited_source_local_date=date(2026, 2, 1))
        return service.confirm([weight["id"], fat["id"]])

    with pytest.raises(PhotoImportError, match="temporal_conflict"):
        _service_call(engine, paths, extractor, attempt)
    with session_scope(engine) as session:
        assert _count(session, MeasurementSession) == 0
        assert _count(session, ScalarMeasurement) == 0
        decisions = set(session.scalars(select(ImportCandidate.user_decision)))
        assert decisions == {"pending"}


def test_sequential_confirmation_must_match_existing_session_time(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(
        source_local_date=date(2026, 1, 7), weight_kg=79.4, body_fat_pct=23.1
    )
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )

    def first(service: PhotoImportService):
        views = [
            service.candidate_view(service._load_candidate(item_id))
            for item_id in imported.items[0].candidate_ids
        ]
        weight = next(view for view in views if view["metric_code"] == "weight")
        return service.confirm([weight["id"]])

    _service_call(engine, paths, extractor, first)

    def second(service: PhotoImportService):
        views = [
            service.candidate_view(service._load_candidate(item_id))
            for item_id in imported.items[0].candidate_ids
        ]
        fat = next(view for view in views if view["metric_code"] == "body_fat_pct")
        service.edit_pending(fat["id"], edited_source_local_date=date(2026, 3, 1))
        return service.confirm([fat["id"]])

    with pytest.raises(PhotoImportError, match="temporal_conflict"):
        _service_call(engine, paths, extractor, second)
    with session_scope(engine) as session:
        assert _count(session, MeasurementSession) == 1
        assert _count(session, ScalarMeasurement) == 1


def test_date_only_rejects_edited_timestamp(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(source_local_date=date(2026, 1, 7), weight_kg=79.4)
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    candidate_id = imported.items[0].candidate_ids[0]
    timestamp = datetime(2026, 1, 7, 8, 30, tzinfo=UTC)
    try:
        _service_call(
            engine,
            paths,
            extractor,
            lambda service: service.edit_pending(candidate_id, edited_source_timestamp=timestamp),
        )
        raise AssertionError("expected date_precision_timestamp")
    except PhotoImportError as exc:
        assert exc.code == "date_precision_timestamp"
    try:
        _service_call(
            engine,
            paths,
            extractor,
            lambda service: service.confirm(
                [candidate_id],
                edits={candidate_id: {"source_timestamp": timestamp}},
            ),
        )
        raise AssertionError("expected date_precision_timestamp")
    except PhotoImportError as exc:
        assert exc.code == "date_precision_timestamp"


def test_sqlite_reloaded_timestamp_can_be_confirmed(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(
        source_local_date=date(2026, 1, 7), weight_kg=79.4, body_fat_pct=23.1
    )
    payload["groups"][0]["temporal_precision"] = "instant"
    payload["groups"][0]["source_timestamp"] = "2026-01-07T08:30:00+00:00"
    for field in payload["groups"][0]["fields"]:
        field["temporal_precision"] = "instant"
        field["source_timestamp"] = "2026-01-07T08:30:00+00:00"
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    with session_scope(engine) as session:
        service = PhotoImportService(session, paths, extractor)
        candidate = service._load_candidate(imported.items[0].candidate_ids[0])
        session.expire(candidate)
        session.refresh(candidate)
        assert candidate.proposed_source_timestamp is not None
        confirmed = service.confirm(imported.items[0].candidate_ids)
        assert confirmed
    with session_scope(engine) as session:
        row = session.scalar(select(MeasurementSession))
        assert row.temporal_precision == "instant"
        assert row.source_timestamp_utc is not None


def test_old_candidate_replay_after_reprocess_does_not_add_revision(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(
        source_local_date=date(2026, 1, 7), weight_kg=79.4, body_fat_pct=23.1
    )
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    first_ids = imported.items[0].candidate_ids
    event_id = imported.items[0].ingest_event_id
    first = _service_call(engine, paths, extractor, lambda service: service.confirm(first_ids))
    v2 = FakeImageMeasurementExtractor(version="2", value_delta=-0.1)
    reprocessed = _service_call(
        engine, paths, v2, lambda service: service.reprocess_event(event_id)
    )
    assert reprocessed.failed is False
    second_ids = [candidate.id for candidate in reprocessed.candidates]
    _service_call(engine, paths, v2, lambda service: service.confirm(second_ids))
    replay = _service_call(engine, paths, extractor, lambda service: service.confirm(first_ids))
    assert {row["scalar_measurement_id"] for row in replay} == {
        row["scalar_measurement_id"] for row in first
    }
    with session_scope(engine) as session:
        assert _count(session, MeasurementSession) == 2
        sessions = list(session.scalars(select(MeasurementSession)))
        assert {row.revision_number for row in sessions} == {1, 2}


def test_partial_reprocess_keeps_one_active_head_per_metric(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(
        source_local_date=date(2026, 1, 7), weight_kg=79.4, body_fat_pct=23.1
    )
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    first_ids = imported.items[0].candidate_ids
    event_id = imported.items[0].ingest_event_id
    first = _service_call(engine, paths, extractor, lambda service: service.confirm(first_ids))
    v1_weight_id = next(
        row["scalar_measurement_id"] for row in first if row["metric_code"] == "weight"
    )
    v2 = FakeImageMeasurementExtractor(version="2", value_delta=-0.1)
    reprocessed = _service_call(
        engine, paths, v2, lambda service: service.reprocess_event(event_id)
    )
    v2_fat = [
        candidate.id
        for candidate in reprocessed.candidates
        if candidate.metric_code == "body_fat_pct"
    ]
    _service_call(engine, paths, v2, lambda service: service.confirm(v2_fat))
    v3 = FakeImageMeasurementExtractor(version="3", value_delta=-0.2)
    again = _service_call(engine, paths, v3, lambda service: service.reprocess_event(event_id))
    v3_weight = [
        candidate.id for candidate in again.candidates if candidate.metric_code == "weight"
    ]
    _service_call(engine, paths, v3, lambda service: service.confirm(v3_weight))
    with session_scope(engine) as session:
        from healthcheck.db.repositories import repositories_for

        repos = repositories_for(session)
        active_weight = repos.scalar_measurements.active_for_metric("weight")
        active_fat = repos.scalar_measurements.active_for_metric("body_fat_pct")
        assert len(active_weight) == 1
        assert len(active_fat) == 1
        assert active_weight[0].supersedes_measurement_id == v1_weight_id


def test_candidate_set_identity_includes_model_and_prompt(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(source_local_date=date(2026, 1, 7), weight_kg=79.4)
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    event_id = imported.items[0].ingest_event_id
    other = FakeImageMeasurementExtractor(
        version="1", model_name="other-model", prompt_version="prompt-2"
    )
    reprocessed = _service_call(
        engine, paths, other, lambda service: service.reprocess_event(event_id)
    )
    assert reprocessed.failed is False
    first_set = {
        _service_call(
            engine,
            paths,
            extractor,
            lambda service: service._load_candidate(item_id).candidate_set_key,
        )
        for item_id in imported.items[0].candidate_ids
    }
    second_set = {candidate.candidate_set_key for candidate in reprocessed.candidates}
    assert first_set.isdisjoint(second_set)
    with session_scope(engine) as session:
        assert session.scalar(select(func.count(ImportCandidate.id))) >= 2


def test_reprocess_keeps_field_algorithm_and_unknown_provider(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(
        source_local_date=date(2026, 1, 7),
        weight_kg=79.4,
        body_fat_pct=23.1,
        provider_code="mi_fitness",
    )
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    event_id = imported.items[0].ingest_event_id
    v2 = FakeImageMeasurementExtractor(
        version="2",
        provider_code="xiaomi_app_unknown",
        field_algorithms={"body_fat_pct": ("xiaomi_custom_formula", "3")},
    )
    reprocessed = _service_call(
        engine, paths, v2, lambda service: service.reprocess_event(event_id)
    )
    fat = next(
        candidate for candidate in reprocessed.candidates if candidate.metric_code == "body_fat_pct"
    )
    assert fat.provider_code == "xiaomi_app_unknown"
    assert fat.algorithm_code == "xiaomi_custom_formula"
    assert fat.algorithm_version == "3"
    confirmed = _service_call(engine, paths, v2, lambda service: service.confirm([fat.id]))
    with session_scope(engine) as session:
        from healthcheck.db.models import MeasurementAlgorithm

        measurement = session.get(ScalarMeasurement, confirmed[0]["scalar_measurement_id"])
        algorithm = session.get(MeasurementAlgorithm, measurement.measurement_algorithm_id)
        assert algorithm.code == "xiaomi_custom_formula"
        assert algorithm.version == "3"


def test_failed_extraction_does_not_leave_partial_candidates(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(
        source_local_date=date(2026, 1, 7), weight_kg=79.4, body_fat_pct=23.1
    )
    payload["groups"][0]["fields"].append(
        {
            "metric_code": "water_pct",
            "value": 50.0,
            "unit": "%",
            "source_text": SECRET_TEXT,
            "confidence": 2.0,
        }
    )
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    assert imported.items[0].status == "failed"
    with session_scope(engine) as session:
        assert _count(session, ImportCandidate) == 0
        assert _count(session, MeasurementSession) == 0


def test_failed_reprocess_diagnostics_are_durable(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(source_local_date=date(2026, 1, 7), weight_kg=79.4)
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    event_id = imported.items[0].ingest_event_id
    _service_call(
        engine,
        paths,
        extractor,
        lambda service: service.confirm(imported.items[0].candidate_ids),
    )
    result = _service_call(
        engine,
        paths,
        _FailingExtractor(),
        lambda service: service.reprocess_event(event_id),
    )
    assert result.failed is True
    assert result.attempt_event_id is not None
    with session_scope(engine) as session:
        original = session.get(IngestEvent, event_id)
        attempt = session.get(IngestEvent, result.attempt_event_id)
        assert original.status == "committed"
        assert attempt.status == "failed"
        assert attempt.duplicate_of_event_id == original.id
        assert attempt.diagnostic_code == "extractor_empty_result"
        assert _count(session, MeasurementSession) == 1


def test_invalid_persistence_does_not_log_health_values(photo_env):
    settings, paths, engine, extractor = photo_env
    log_path = configure_logging(paths.logs)
    payload = weigh_in_payload(source_local_date=date(2026, 1, 7), weight_kg=77.77)
    payload["groups"][0]["fields"][0]["source_text"] = SECRET_TEXT
    app, _ = create_ui_app(settings)
    with TestClient(app) as client:
        uploaded = client.post(
            "/api/imports/photos",
            files=[("files", ("secret.png", encode_synthetic_png(payload), "image/png"))],
        )
        assert uploaded.status_code == 200
        candidate_ids = uploaded.json()["items"][0]["candidate_ids"]

        def boom(*_args, **_kwargs):
            raise IntegrityError(
                "INSERT INTO scalar_measurements (source_text, normalized_value) VALUES (?, ?)",
                {"source_text": SECRET_TEXT, "normalized_value": 77.77},
                orig=Exception("constraint"),
            )

        with patch(
            "healthcheck.ingestion.photo.service.PhotoImportService._write_measurement",
            side_effect=boom,
        ):
            confirmed = client.post(
                "/api/import-candidates/confirm", json={"candidate_ids": candidate_ids}
            )
        assert confirmed.status_code in {400, 500}
        assert SECRET_TEXT not in confirmed.text
    text = log_path.read_text(encoding="utf-8")
    assert SECRET_TEXT not in text
    assert "77.77" not in text
    del engine
    del extractor


def test_duplicate_upload_has_durable_occurrence_in_new_batch(photo_env):
    settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(source_local_date=date(2026, 1, 7), weight_kg=79.4)
    png = encode_synthetic_png(payload)
    first = _service_call(
        engine,
        paths,
        extractor,
        lambda service: service.import_photos([PhotoUpload("one.png", png)]),
    )
    second = _service_call(
        engine,
        paths,
        extractor,
        lambda service: service.import_photos([PhotoUpload("one.png", png)]),
    )
    assert second.items[0].duplicate_artifact is True
    assert second.items[0].ingest_batch_id == second.batch.id
    assert second.items[0].ingest_event_id != first.items[0].ingest_event_id
    app, _ = create_ui_app(settings)
    with TestClient(app) as client:
        detail = client.get(f"/api/imports/{second.batch.id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["events"]
        assert body["events"][0]["duplicate_of_event_id"] == first.items[0].ingest_event_id
        assert body["events"][0]["original_batch_id"] == first.batch.id
        assert body["artifacts"]
        assert body["artifacts"][0]["id"] == first.items[0].artifact_id
        assert {candidate["id"] for candidate in body["candidates"]} == set(
            first.items[0].candidate_ids
        )
    del engine


def _instant_payload(local_date: date, timestamp_iso: str, **kwargs) -> dict:
    payload = weigh_in_payload(
        source_local_date=local_date, weight_kg=79.4, body_fat_pct=23.1, **kwargs
    )
    payload["groups"][0]["temporal_precision"] = "instant"
    payload["groups"][0]["source_timestamp"] = timestamp_iso
    for field in payload["groups"][0]["fields"]:
        field["temporal_precision"] = "instant"
        field["source_timestamp"] = timestamp_iso
    return payload


def test_consistent_instant_and_local_date_can_be_confirmed(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = _instant_payload(date(2026, 1, 7), "2026-01-07T10:00:00+00:00")
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    confirmed = _service_call(
        engine,
        paths,
        extractor,
        lambda service: service.confirm(imported.items[0].candidate_ids),
    )
    assert confirmed
    with session_scope(engine) as session:
        row = session.scalar(select(MeasurementSession))
        assert row.source_local_date == date(2026, 1, 7)
        assert row.temporal_precision == "instant"


def test_plausible_adjacent_utc_local_boundary_without_timezone(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = _instant_payload(date(2026, 1, 8), "2026-01-07T23:00:00+00:00")
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    assert imported.items[0].status == "pending-confirmation"
    _service_call(
        engine,
        paths,
        extractor,
        lambda service: service.confirm(imported.items[0].candidate_ids),
    )
    with session_scope(engine) as session:
        assert _count(session, MeasurementSession) == 1
        assert session.scalar(select(MeasurementSession)).source_local_date == date(2026, 1, 8)


def test_impossible_multi_day_mismatch_fails_atomically(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = _instant_payload(date(2026, 1, 10), "2026-01-07T10:00:00+00:00")
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    assert imported.items[0].status == "failed"
    with session_scope(engine) as session:
        assert _count(session, ImportCandidate) == 0
        assert _count(session, MeasurementSession) == 0


def test_known_offset_validates_local_date_against_instant(photo_env):
    _settings, paths, engine, _extractor = photo_env
    extractor = FakeImageMeasurementExtractor(source_utc_offset_minutes=180)
    payload = _instant_payload(date(2026, 1, 8), "2026-01-07T21:00:00+00:00")
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    _service_call(
        engine,
        paths,
        extractor,
        lambda service: service.confirm(imported.items[0].candidate_ids),
    )
    with session_scope(engine) as session:
        row = session.scalar(select(MeasurementSession))
        assert row.source_local_date == date(2026, 1, 8)
        assert row.source_utc_offset_minutes == 180


def test_known_offset_rejects_inconsistent_local_date(photo_env):
    _settings, paths, engine, _extractor = photo_env
    extractor = FakeImageMeasurementExtractor(source_utc_offset_minutes=180)
    payload = _instant_payload(date(2026, 1, 7), "2026-01-07T21:00:00+00:00")
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    assert imported.items[0].status == "failed"
    with session_scope(engine) as session:
        assert _count(session, ImportCandidate) == 0


def test_sequential_instant_confirmation_must_match_existing_session(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = _instant_payload(date(2026, 1, 7), "2026-01-07T10:00:00+00:00")
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )

    def confirm_weight(service: PhotoImportService):
        views = [
            service.candidate_view(service._load_candidate(item_id))
            for item_id in imported.items[0].candidate_ids
        ]
        weight = next(view for view in views if view["metric_code"] == "weight")
        return service.confirm([weight["id"]])

    _service_call(engine, paths, extractor, confirm_weight)

    def confirm_fat_with_other_time(service: PhotoImportService):
        views = [
            service.candidate_view(service._load_candidate(item_id))
            for item_id in imported.items[0].candidate_ids
        ]
        fat = next(view for view in views if view["metric_code"] == "body_fat_pct")
        return service.confirm(
            [fat["id"]],
            edits={
                fat["id"]: {
                    "source_timestamp": datetime(2026, 1, 7, 11, 0, tzinfo=UTC),
                    "source_local_date": date(2026, 1, 7),
                }
            },
        )

    with pytest.raises(PhotoImportError, match="temporal_conflict"):
        _service_call(engine, paths, extractor, confirm_fat_with_other_time)
    with session_scope(engine) as session:
        assert _count(session, MeasurementSession) == 1
        assert _count(session, ScalarMeasurement) == 1


def test_terminal_replay_is_noop_only_when_semantically_identical(photo_env):
    settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(source_local_date=date(2026, 1, 7), weight_kg=80.0)
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    candidate_id = imported.items[0].candidate_ids[0]
    first = _service_call(engine, paths, extractor, lambda service: service.confirm([candidate_id]))
    replay = _service_call(
        engine, paths, extractor, lambda service: service.confirm([candidate_id])
    )
    assert replay[0]["scalar_measurement_id"] == first[0]["scalar_measurement_id"]
    with session_scope(engine) as session:
        assert _count(session, MeasurementSession) == 1
        assert _count(session, ScalarMeasurement) == 1
        assert _count(session, ImportCandidateEdit) == 1
    with pytest.raises(PhotoImportError, match="terminal_candidate"):
        _service_call(
            engine,
            paths,
            extractor,
            lambda service: service.confirm(
                [candidate_id], edits={candidate_id: {"value": 81.0, "unit": "kg"}}
            ),
        )
    with session_scope(engine) as session:
        assert _count(session, MeasurementSession) == 1
        assert _count(session, ScalarMeasurement) == 1
        assert _count(session, ImportCandidateEdit) == 1
        measurement = session.scalar(select(ScalarMeasurement))
        assert measurement.normalized_value == pytest.approx(80.0)
    app, _ = create_ui_app(settings)
    with TestClient(app) as client:
        edited = client.post(
            "/api/imports/photos",
            files=[
                (
                    "files",
                    (
                        "edit.png",
                        encode_synthetic_png(
                            weigh_in_payload(source_local_date=date(2026, 2, 1), weight_kg=80.0)
                        ),
                        "image/png",
                    ),
                )
            ],
        )
        assert edited.status_code == 200
        cid = edited.json()["items"][0]["candidate_ids"][0]
        first_edit = client.post(
            "/api/import-candidates/confirm",
            json={"candidate_ids": [cid], "edits": {cid: {"value": 81.0, "unit": "kg"}}},
        )
        assert first_edit.status_code == 200
        repeat_edit = client.post(
            "/api/import-candidates/confirm",
            json={"candidate_ids": [cid], "edits": {cid: {"value": 81.0, "unit": "kg"}}},
        )
        assert repeat_edit.status_code == 200
        assert (
            repeat_edit.json()["confirmed"][0]["scalar_measurement_id"]
            == first_edit.json()["confirmed"][0]["scalar_measurement_id"]
        )
        changed = client.post(
            "/api/import-candidates/confirm",
            json={"candidate_ids": [cid], "edits": {cid: {"value": 82.0, "unit": "kg"}}},
        )
        assert changed.status_code == 409
        assert changed.json()["code"] == "terminal_candidate"


def test_changed_source_application_version_creates_new_extraction_evidence(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(
        source_local_date=date(2026, 1, 7),
        weight_kg=79.4,
        source_application_version="1.0",
    )
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    event_id = imported.items[0].ingest_event_id
    v2 = FakeImageMeasurementExtractor(source_application_version="2.0")
    reprocessed = _service_call(
        engine, paths, v2, lambda service: service.reprocess_event(event_id)
    )
    assert reprocessed.failed is False
    assert {candidate.id for candidate in reprocessed.candidates}.isdisjoint(
        imported.items[0].candidate_ids
    )


def test_changed_provider_or_device_creates_new_extraction_evidence(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(source_local_date=date(2026, 1, 7), weight_kg=79.4)
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    event_id = imported.items[0].ingest_event_id
    other_provider = FakeImageMeasurementExtractor(provider_code="xiaomi_app_unknown")
    other_device = FakeImageMeasurementExtractor(physical_device_code="xiaomi_s400_b")
    provider_result = _service_call(
        engine, paths, other_provider, lambda service: service.reprocess_event(event_id)
    )
    device_result = _service_call(
        engine, paths, other_device, lambda service: service.reprocess_event(event_id)
    )
    original_ids = set(imported.items[0].candidate_ids)
    assert {candidate.id for candidate in provider_result.candidates}.isdisjoint(original_ids)
    assert {candidate.id for candidate in device_result.candidates}.isdisjoint(original_ids)
    assert {candidate.id for candidate in provider_result.candidates}.isdisjoint(
        {candidate.id for candidate in device_result.candidates}
    )


def test_same_identity_with_contradictory_values_is_conflict(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(source_local_date=date(2026, 1, 7), weight_kg=79.4)
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    event_id = imported.items[0].ingest_event_id
    mutated = FakeImageMeasurementExtractor(value_delta=-0.5)
    result = _service_call(
        engine, paths, mutated, lambda service: service.reprocess_event(event_id)
    )
    assert result.failed is True
    assert result.error_code == "extractor_invalid_payload"


def test_same_unknown_config_reprocess_revises_same_source(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(
        source_local_date=date(2026, 1, 7),
        weight_kg=79.4,
        body_fat_pct=23.1,
        provider_code="xiaomi_app_unknown",
        source_application=None,
    )
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    event_id = imported.items[0].ingest_event_id
    first = _service_call(
        engine, paths, extractor, lambda service: service.confirm(imported.items[0].candidate_ids)
    )
    v2 = FakeImageMeasurementExtractor(version="2", provider_code="xiaomi_app_unknown")
    reprocessed = _service_call(
        engine, paths, v2, lambda service: service.reprocess_event(event_id)
    )
    assert reprocessed.ingest_event_id == event_id
    second = _service_call(
        engine,
        paths,
        v2,
        lambda service: service.confirm([candidate.id for candidate in reprocessed.candidates]),
    )
    with session_scope(engine) as session:
        sessions = list(session.scalars(select(MeasurementSession)))
        sources = {row.acquisition_source_id for row in sessions}
        assert len(sources) == 1
        assert {row.revision_number for row in sessions} == {1, 2}
        assert first[0]["measurement_session_id"] != second[0]["measurement_session_id"]


def test_reprocess_to_xiaomi_home_creates_competing_source_lineage(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(
        source_local_date=date(2026, 1, 7),
        weight_kg=79.4,
        body_fat_pct=23.1,
        provider_code="xiaomi_app_unknown",
        source_application=None,
    )
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    event_id = imported.items[0].ingest_event_id
    first = _service_call(
        engine, paths, extractor, lambda service: service.confirm(imported.items[0].candidate_ids)
    )
    home = FakeImageMeasurementExtractor(version="2", provider_code="xiaomi_home")
    reprocessed = _service_call(
        engine, paths, home, lambda service: service.reprocess_event(event_id)
    )
    assert reprocessed.ingest_event_id != event_id
    second = _service_call(
        engine,
        paths,
        home,
        lambda service: service.confirm([candidate.id for candidate in reprocessed.candidates]),
    )
    with session_scope(engine) as session:
        old_session = session.get(MeasurementSession, first[0]["measurement_session_id"])
        new_session = session.get(MeasurementSession, second[0]["measurement_session_id"])
        assert old_session.acquisition_source_id != new_session.acquisition_source_id
        assert new_session.revision_number == 1
        assert old_session.revision_number == 1
        old_event = session.get(IngestEvent, event_id)
        new_event = session.get(IngestEvent, reprocessed.ingest_event_id)
        assert new_event.duplicate_of_event_id == old_event.id
        assert new_event.acquisition_source_id == new_session.acquisition_source_id
        assert old_event.acquisition_source_id == old_session.acquisition_source_id
        assert session.get(AcquisitionSource, old_session.acquisition_source_id) is not None
        assert session.get(AcquisitionSource, new_session.acquisition_source_id) is not None
        assert session.get(ScalarMeasurement, first[0]["scalar_measurement_id"]) is not None
        assert {row.supersedes_session_id for row in (old_session, new_session)} == {None}


def test_source_application_version_change_is_new_acquisition_lineage(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(
        source_local_date=date(2026, 1, 7),
        weight_kg=79.4,
        source_application_version="1.0",
    )
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    event_id = imported.items[0].ingest_event_id
    _service_call(
        engine, paths, extractor, lambda service: service.confirm(imported.items[0].candidate_ids)
    )
    v2 = FakeImageMeasurementExtractor(source_application_version="2.0")
    reprocessed = _service_call(
        engine, paths, v2, lambda service: service.reprocess_event(event_id)
    )
    confirmed = _service_call(
        engine,
        paths,
        v2,
        lambda service: service.confirm([candidate.id for candidate in reprocessed.candidates]),
    )
    with session_scope(engine) as session:
        new_session = session.get(MeasurementSession, confirmed[0]["measurement_session_id"])
        new_event = session.get(IngestEvent, reprocessed.ingest_event_id)
        assert new_event.acquisition_source_id == new_session.acquisition_source_id
        original_event = session.get(IngestEvent, event_id)
        assert new_event.acquisition_source_id != original_event.acquisition_source_id
        assert new_session.supersedes_session_id is None


def test_physical_device_change_is_new_acquisition_lineage(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(source_local_date=date(2026, 1, 7), weight_kg=79.4)
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_upload(payload))
    )
    event_id = imported.items[0].ingest_event_id
    _service_call(
        engine, paths, extractor, lambda service: service.confirm(imported.items[0].candidate_ids)
    )
    other = FakeImageMeasurementExtractor(physical_device_code="xiaomi_s400_b")
    reprocessed = _service_call(
        engine, paths, other, lambda service: service.reprocess_event(event_id)
    )
    confirmed = _service_call(
        engine,
        paths,
        other,
        lambda service: service.confirm([candidate.id for candidate in reprocessed.candidates]),
    )
    with session_scope(engine) as session:
        new_session = session.get(MeasurementSession, confirmed[0]["measurement_session_id"])
        new_event = session.get(IngestEvent, reprocessed.ingest_event_id)
        original_event = session.get(IngestEvent, event_id)
        assert new_event.acquisition_source_id == new_session.acquisition_source_id
        assert new_event.acquisition_source_id != original_event.acquisition_source_id
        assert new_session.supersedes_session_id is None
        assert session.get(IngestEvent, event_id).status in {
            "pending-confirmation",
            "committed",
        }
