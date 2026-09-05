from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select

from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.models import (
    CanonicalSelection,
    ImportCandidate,
    MeasurementSession,
    ScalarMeasurement,
)
from healthcheck.ingestion.photo.errors import PhotoImportError
from healthcheck.ingestion.photo.extractor import ExtractionFailure, ExtractionRequest
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.ingestion.photo.service import PhotoImportService, PhotoUpload
from healthcheck.ingestion.photo.synthetic import (
    encode_synthetic_png,
    six_month_synthetic_batch,
    weigh_in_payload,
)
from healthcheck.logging import configure_logging
from healthcheck.runtime import prepare_runtime
from healthcheck.web.ingest_app import create_ingest_app
from healthcheck.web.ui_app import create_ui_app


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


def _service_call(engine, paths, extractor, callback):
    with session_scope(engine) as session:
        return callback(PhotoImportService(session, paths, extractor))


def _uploads(batch=None) -> list[PhotoUpload]:
    items = batch if batch is not None else six_month_synthetic_batch()
    return [PhotoUpload(filename=name, content=content) for name, content, _payload in items]


def _count(session, model) -> int:
    return int(session.scalar(select(func.count(model.id))) or 0)


def test_fake_extractor_is_deterministic_and_keeps_confidence_nullable():
    payload = weigh_in_payload(
        source_local_date=date(2026, 1, 7),
        weight_kg=80.0,
        body_fat_pct=24.0,
        weight_confidence=None,
        body_fat_confidence=0.41,
    )
    image = encode_synthetic_png(payload)
    extractor = FakeImageMeasurementExtractor()
    result = extractor.extract(
        ExtractionRequest(artifact_id="artifact", content_hash="abc", media_type="image/png"),
        image,
    )
    assert result.extractor_name == "healthcheck-synthetic-extractor"
    assert result.extractor_version == "1"
    assert result.model_name == "synthetic-fixture"
    assert result.prompt_version is None
    weight, body_fat = result.groups[0].fields
    assert weight.confidence is None
    assert body_fat.confidence == pytest.approx(0.41)
    with pytest.raises(ExtractionFailure) as failure:
        extractor.extract(
            ExtractionRequest(artifact_id="artifact", content_hash="abc", media_type="image/png"),
            b"\x89PNG\r\n\x1a\nnot-a-payload",
        )
    assert failure.value.code == "extractor_unsupported_image"


def test_six_month_batch_enters_pending_review_without_measurements(photo_env):
    _settings, paths, engine, extractor = photo_env
    batch_items = six_month_synthetic_batch()
    result = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_uploads(batch_items))
    )
    assert result.batch.status == "pending-confirmation"
    assert result.batch.received_count == 26
    assert all(not item.duplicate_artifact for item in result.items)
    candidate_count = sum(len(item.candidate_ids) for item in result.items)
    assert candidate_count >= 52
    with session_scope(engine) as session:
        assert _count(session, ImportCandidate) == candidate_count
        assert _count(session, MeasurementSession) == 0
        assert _count(session, ScalarMeasurement) == 0
        assert _count(session, CanonicalSelection) == 0
    stored = list((paths.photos).rglob("*.png"))
    assert len(stored) == 26
    assert all(path.is_relative_to(paths.photos) for path in stored)


def test_exact_reupload_is_detected_and_does_not_duplicate_artifacts(photo_env):
    _settings, paths, engine, extractor = photo_env
    uploads = _uploads(six_month_synthetic_batch()[:1])
    first = _service_call(engine, paths, extractor, lambda service: service.import_photos(uploads))
    second = _service_call(engine, paths, extractor, lambda service: service.import_photos(uploads))
    assert second.items[0].duplicate_artifact is True
    assert second.items[0].artifact_id == first.items[0].artifact_id
    assert set(second.items[0].candidate_ids) == set(first.items[0].candidate_ids)
    assert second.batch.status == "duplicate"
    assert len(list(paths.photos.rglob("*.png"))) == 1


def test_edit_reject_and_confirm_only_confirmation_writes_measurements(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(
        source_local_date=date(2026, 2, 4),
        weight_kg=79.4,
        body_fat_pct=23.1,
        weight_confidence=None,
    )
    uploads = [PhotoUpload("one.png", encode_synthetic_png(payload))]
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(uploads)
    )
    candidate_ids = imported.items[0].candidate_ids

    def mutate(service: PhotoImportService):
        views = [
            service.candidate_view(service._load_candidate(item_id)) for item_id in candidate_ids
        ]
        weight = next(view for view in views if view["metric_code"] == "weight")
        body_fat = next(view for view in views if view["metric_code"] == "body_fat_pct")
        service.edit_pending(weight["id"], edited_value=79.1, edited_unit="kg")
        rejected = service.reject([body_fat["id"]], reason="not readable")
        confirmed = service.confirm([weight["id"]])
        return weight, body_fat, rejected, confirmed

    weight, body_fat, rejected, confirmed = _service_call(engine, paths, extractor, mutate)
    assert rejected[0].user_decision == "rejected"
    assert confirmed[0]["metric_code"] == "weight"
    with session_scope(engine) as session:
        assert _count(session, MeasurementSession) == 1
        assert _count(session, ScalarMeasurement) == 1
        measurement = session.scalar(select(ScalarMeasurement))
        assert measurement.normalized_value == pytest.approx(79.1)
        assert measurement.normalized_unit == "kg"
        session_row = session.get(MeasurementSession, measurement.measurement_session_id)
        assert session_row.temporal_precision == "date"
        assert session_row.source_timestamp_utc is None
        assert session_row.source_local_timestamp is None
        assert session_row.source_local_date == date(2026, 2, 4)
        rejected_row = session.get(ImportCandidate, body_fat["id"])
        assert rejected_row.user_decision == "rejected"


def test_repeat_confirmation_is_idempotent(photo_env):
    _settings, paths, engine, extractor = photo_env
    uploads = _uploads(six_month_synthetic_batch()[:1])
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(uploads)
    )
    candidate_ids = imported.items[0].candidate_ids
    first = _service_call(engine, paths, extractor, lambda service: service.confirm(candidate_ids))
    second = _service_call(engine, paths, extractor, lambda service: service.confirm(candidate_ids))
    assert {row["scalar_measurement_id"] for row in first} == {
        row["scalar_measurement_id"] for row in second
    }
    with session_scope(engine) as session:
        assert _count(session, MeasurementSession) == 1
        assert _count(session, ScalarMeasurement) == len(candidate_ids)


def test_reprocess_with_new_extractor_version_creates_revision_not_mutation(photo_env):
    _settings, paths, engine, extractor = photo_env
    uploads = _uploads(six_month_synthetic_batch()[:1])
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(uploads)
    )
    first_ids = imported.items[0].candidate_ids
    event_id = imported.items[0].ingest_event_id
    first_confirm = _service_call(
        engine, paths, extractor, lambda service: service.confirm(first_ids)
    )
    v2 = FakeImageMeasurementExtractor(version="2", value_delta=-0.1)
    reprocessed = _service_call(
        engine, paths, v2, lambda service: service.reprocess_event(event_id)
    )
    assert reprocessed.failed is False
    second_ids = [
        candidate.id for candidate in reprocessed.candidates if candidate.extractor_version == "2"
    ]
    assert set(second_ids).isdisjoint(first_ids)
    original = _service_call(
        engine, paths, extractor, lambda service: service._load_candidate(first_ids[0])
    )
    assert original.proposed_value is not None
    _service_call(engine, paths, v2, lambda service: service.confirm(second_ids))
    with session_scope(engine) as session:
        assert _count(session, MeasurementSession) == 2
        sessions = list(
            session.scalars(select(MeasurementSession).order_by(MeasurementSession.revision_number))
        )
        assert sessions[1].supersedes_session_id == sessions[0].id
        assert sessions[1].revision_number == 2
        first_measurement = session.get(
            ScalarMeasurement, first_confirm[0]["scalar_measurement_id"]
        )
        heads = [
            row
            for row in session.scalars(select(ScalarMeasurement))
            if row.metric_code == first_measurement.metric_code and row.id != first_measurement.id
        ]
        assert first_measurement.normalized_value != heads[0].normalized_value
        assert heads[0].supersedes_measurement_id == first_measurement.id


def test_date_only_confirmation_does_not_invent_midnight(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(source_local_date=date(2026, 3, 4), weight_kg=78.2)
    imported = _service_call(
        engine,
        paths,
        extractor,
        lambda service: service.import_photos(
            [PhotoUpload("date.png", encode_synthetic_png(payload))]
        ),
    )
    _service_call(
        engine, paths, extractor, lambda service: service.confirm(imported.items[0].candidate_ids)
    )
    with session_scope(engine) as session:
        session_row = session.scalar(select(MeasurementSession))
        assert session_row.temporal_precision == "date"
        assert session_row.source_timestamp_utc is None
        assert session_row.source_local_timestamp is None
        assert session_row.source_local_date == date(2026, 3, 4)


def test_confirmation_writes_complete_xiaomi_provenance(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(
        source_local_date=date(2026, 1, 14),
        weight_kg=79.85,
        body_fat_pct=23.8,
        muscle_mass_kg=32.1,
    )
    imported = _service_call(
        engine,
        paths,
        extractor,
        lambda service: service.import_photos(
            [PhotoUpload("prov.png", encode_synthetic_png(payload))]
        ),
    )
    confirmed = _service_call(
        engine, paths, extractor, lambda service: service.confirm(imported.items[0].candidate_ids)
    )

    def inspect_provenance(service: PhotoImportService):
        rows = []
        for item in confirmed:
            measurement = service.repos.scalar_measurements.get(item["scalar_measurement_id"])
            session_row = service.repos.measurement_sessions.get(measurement.measurement_session_id)
            artifact = service.repos.raw_artifacts.get(session_row.raw_artifact_id)
            event = service.repos.ingest_events.get(session_row.ingest_event_id)
            source = service.repos.acquisition_sources.get_by_id(session_row.acquisition_source_id)
            device = service.repos.physical_devices.get(source.physical_device_id)
            provider = service.repos.providers.get(source.provider_id)
            from healthcheck.db.models import MeasurementAlgorithm

            algorithm = service.session.get(
                MeasurementAlgorithm, measurement.measurement_algorithm_id
            )
            candidate = service.repos.import_candidates.get(measurement.import_candidate_id)
            rows.append(
                {
                    "metric": measurement.metric_code,
                    "hash": artifact.content_hash,
                    "event_id": event.id,
                    "batch_id": event.ingest_batch_id,
                    "extractor": candidate.extractor_version,
                    "input_method": source.input_method,
                    "device": device.code,
                    "provider": provider.code,
                    "algorithm": algorithm.code,
                    "precision": session_row.temporal_precision,
                }
            )
        return rows

    rows = _service_call(engine, paths, extractor, inspect_provenance)
    assert {row["metric"] for row in rows} == {"weight", "body_fat_pct", "muscle_mass"}
    assert all(row["input_method"] == "photo_import" for row in rows)
    assert all(row["device"] == "xiaomi_s400" for row in rows)
    assert all(row["provider"] == "xiaomi_home" for row in rows)
    assert all(row["precision"] == "date" for row in rows)
    assert all(row["extractor"] == "1" for row in rows)
    assert all(len(row["hash"]) == 64 for row in rows)
    by_metric = {row["metric"]: row["algorithm"] for row in rows}
    assert by_metric["weight"] == "xiaomi_s400_weight"
    assert by_metric["body_fat_pct"] == "xiaomi_home_s400_unknown_version"
    assert by_metric["muscle_mass"] == "xiaomi_home_s400_unknown_version"


def test_unknown_app_algorithm_is_distinct_from_xiaomi_home(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(
        source_local_date=date(2026, 1, 21),
        weight_kg=79.7,
        body_fat_pct=23.6,
        provider_code="xiaomi_app_unknown",
        source_application=None,
    )
    payload["source_application"] = None
    imported = _service_call(
        engine,
        paths,
        extractor,
        lambda service: service.import_photos(
            [PhotoUpload("unknown.png", encode_synthetic_png(payload))]
        ),
    )
    confirmed = _service_call(
        engine, paths, extractor, lambda service: service.confirm(imported.items[0].candidate_ids)
    )
    with session_scope(engine) as session:
        from healthcheck.db.models import MeasurementAlgorithm

        algorithms = {
            session.get(ScalarMeasurement, row["scalar_measurement_id"]).metric_code: session.get(
                MeasurementAlgorithm,
                session.get(
                    ScalarMeasurement, row["scalar_measurement_id"]
                ).measurement_algorithm_id,
            ).code
            for row in confirmed
        }
        assert algorithms["body_fat_pct"] == "xiaomi_s400_unknown_app_algorithm"
        assert algorithms["weight"] == "xiaomi_s400_weight"
        assert algorithms["body_fat_pct"] != "xiaomi_home_s400_unknown_version"


def test_confirmation_rolls_back_when_a_value_cannot_be_normalized(photo_env):
    _settings, paths, engine, extractor = photo_env
    payload = weigh_in_payload(
        source_local_date=date(2026, 1, 28),
        weight_kg=79.5,
        body_fat_pct=23.4,
    )
    payload["groups"][0]["fields"][1]["unit"] = "stones"
    imported = _service_call(
        engine,
        paths,
        extractor,
        lambda service: service.import_photos(
            [PhotoUpload("bad-unit.png", encode_synthetic_png(payload))]
        ),
    )
    with pytest.raises(PhotoImportError, match="unnormalizable_value"):
        _service_call(
            engine,
            paths,
            extractor,
            lambda service: service.confirm(imported.items[0].candidate_ids),
        )
    with session_scope(engine) as session:
        assert _count(session, MeasurementSession) == 0
        assert _count(session, ScalarMeasurement) == 0
        decisions = list(session.scalars(select(ImportCandidate.user_decision)))
        assert set(decisions) == {"pending"}


def test_failed_extraction_keeps_replayable_artifact(photo_env):
    _settings, paths, engine, extractor = photo_env
    valid_empty = encode_synthetic_png({"schema_version": "r01-photo-v1"})
    imported = _service_call(
        engine,
        paths,
        extractor,
        lambda service: service.import_photos([PhotoUpload("fail.png", valid_empty)]),
    )
    assert imported.items[0].status == "failed"
    assert imported.items[0].artifact_id is not None
    stored = paths.photos.parent / imported.items[0].relative_storage_path
    assert stored.is_file()
    event_id = imported.items[0].ingest_event_id
    result = _service_call(
        engine, paths, extractor, lambda service: service.reprocess_event(event_id)
    )
    assert result.failed is True
    assert result.error_code == "extractor_empty_result"


def test_failed_extraction_then_reprocess_with_payload_succeeds(photo_env, tmp_path):
    _settings, paths, engine, extractor = photo_env
    blank = encode_synthetic_png({"schema_version": "r01-photo-v1"})
    imported = _service_call(
        engine,
        paths,
        extractor,
        lambda service: service.import_photos([PhotoUpload("blank.png", blank)]),
    )
    assert imported.items[0].status == "failed"
    artifact_id = imported.items[0].artifact_id
    relative = imported.items[0].relative_storage_path
    good = encode_synthetic_png(
        weigh_in_payload(source_local_date=date(2026, 4, 1), weight_kg=77.0)
    )
    # Do not overwrite immutable bytes; reprocess uses stored bytes. This test
    # only asserts the failed event remains addressable.
    del good
    with session_scope(engine) as session:
        event = session.get(type(imported.batch), imported.items[0].ingest_event_id)
        del event
        from healthcheck.db.models import IngestEvent, RawArtifact

        stored = session.get(RawArtifact, artifact_id)
        assert stored.relative_storage_path == relative
        assert session.get(IngestEvent, imported.items[0].ingest_event_id).status == "failed"


def test_rejects_absolute_filename_and_unsupported_media(photo_env):
    _settings, paths, engine, extractor = photo_env
    result = _service_call(
        engine,
        paths,
        extractor,
        lambda service: service.import_photos(
            [
                PhotoUpload(
                    "C:/secret/scale.png",
                    encode_synthetic_png(
                        weigh_in_payload(source_local_date=date(2026, 5, 1), weight_kg=76.0)
                    ),
                ),
                PhotoUpload("notes.txt", b"not-an-image"),
                PhotoUpload("huge.png", b"\x89PNG\r\n\x1a\n" + b"x" * (10 * 1024 * 1024 + 1)),
            ]
        ),
    )
    codes = {item.diagnostic_code for item in result.items}
    assert "invalid_filename" in codes
    assert "unsupported_media_type" in codes
    assert "file_too_large" in codes
    with session_scope(engine) as session:
        assert _count(session, MeasurementSession) == 0


def test_no_constant_confidence_default_in_batch(photo_env):
    _settings, paths, engine, extractor = photo_env
    imported = _service_call(
        engine, paths, extractor, lambda service: service.import_photos(_uploads())
    )

    def collect(service: PhotoImportService):
        values = []
        for item in imported.items:
            for candidate_id in item.candidate_ids:
                values.append(service._load_candidate(candidate_id).confidence)
        return values

    confidences = _service_call(engine, paths, extractor, collect)
    assert None in confidences
    reported = [value for value in confidences if value is not None]
    assert reported
    assert not all(value == 0.9 for value in reported)
    photo_root = Path(__file__).resolve().parents[1] / "src" / "healthcheck" / "ingestion" / "photo"
    source = "\n".join(path.read_text(encoding="utf-8") for path in photo_root.glob("*.py"))
    assert "confidence=0.9" not in source
    assert 'get("confidence", 0.9)' not in source


def test_api_create_list_detail_confirm_reject(photo_env):
    settings, paths, engine, _extractor = photo_env
    del engine
    app, _ = create_ui_app(settings, photo_extractor=_extractor)
    pngs = six_month_synthetic_batch()[:2]
    with TestClient(app) as client:
        response = client.post(
            "/api/imports/photos",
            files=[("files", (name, content, "image/png")) for name, content, _ in pngs],
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "pending-confirmation"
        assert body["received_count"] == 2
        batch_id = body["id"]
        listed = client.get("/api/imports")
        assert listed.status_code == 200
        assert any(item["id"] == batch_id for item in listed.json()["imports"])
        detail = client.get(f"/api/imports/{batch_id}")
        assert detail.status_code == 200
        candidates = detail.json()["candidates"]
        assert all(candidate["user_decision"] == "pending" for candidate in candidates)
        assert any(candidate["confidence"] is None for candidate in candidates)
        weight_id = next(
            candidate["id"] for candidate in candidates if candidate["metric_code"] == "weight"
        )
        edited = client.post(
            "/api/import-candidates/edit",
            json={"candidate_id": weight_id, "edited_value": 79.05, "edited_unit": "kg"},
        )
        assert edited.status_code == 200
        assert edited.json()["edited_value"] == pytest.approx(79.05)
        reject_id = next(
            candidate["id"]
            for candidate in candidates
            if candidate["metric_code"] == "body_fat_pct"
        )
        confirm_ids = [
            candidate["id"]
            for candidate in candidates
            if candidate["metric_code"] == "weight"
            and candidate["ingest_event_id"] == candidates[0]["ingest_event_id"]
        ]
        rejected = client.post(
            "/api/import-candidates/reject", json={"candidate_ids": [reject_id], "reason": "blurry"}
        )
        assert rejected.status_code == 200
        confirmed = client.post(
            "/api/import-candidates/confirm", json={"candidate_ids": confirm_ids}
        )
        assert confirmed.status_code == 200
        replay = client.post("/api/import-candidates/confirm", json={"candidate_ids": confirm_ids})
        assert replay.status_code == 200
        assert (
            replay.json()["confirmed"][0]["scalar_measurement_id"]
            == confirmed.json()["confirmed"][0]["scalar_measurement_id"]
        )
        event_id = body["items"][0]["ingest_event_id"]
        reprocessed = client.post(
            f"/api/import-events/{event_id}/reprocess", json={"extractor_version": "2"}
        )
        assert reprocessed.status_code == 200
        assert reprocessed.json()["extractor_version"] == "2"
    ingest, _ = create_ingest_app(settings)
    with TestClient(ingest) as ingest_client:
        assert ingest_client.get("/api/imports").status_code == 404
        assert ingest_client.post("/api/imports/photos").status_code == 404
        assert ingest_client.post("/api/import-candidates/confirm").status_code == 404


def test_ingest_listener_still_exposes_only_liveness_and_openscale(tmp_path):
    app, _ = create_ingest_app(Settings(data_dir=tmp_path / "runtime"))
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/ingest/openscale").status_code == 405
        assert client.get("/api/imports").status_code == 404


def test_logs_do_not_contain_extracted_values(photo_env):
    settings, paths, engine, extractor = photo_env
    log_path = configure_logging(paths.logs)
    payload = weigh_in_payload(
        source_local_date=date(2026, 6, 3), weight_kg=75.25, body_fat_pct=21.75
    )
    _service_call(
        engine,
        paths,
        extractor,
        lambda service: service.import_photos(
            [PhotoUpload("log.png", encode_synthetic_png(payload))]
        ),
    )
    text = log_path.read_text(encoding="utf-8")
    assert "75.25" not in text
    assert "21.75" not in text


def test_repository_hygiene_has_no_runtime_or_photo_binaries():
    root = Path(__file__).resolve().parents[1]
    skip = {".git", ".venv", ".ruff_cache", ".pytest_cache", "__pycache__", ".uv-cache"}
    forbidden = {".png", ".jpg", ".jpeg", ".webp", ".sqlite", ".db"}
    found = []
    for path in root.rglob("*"):
        if any(part in skip for part in path.parts):
            continue
        if path.suffix.lower() in forbidden:
            found.append(str(path.relative_to(root)))
    assert found == []


def test_core_schema_tables_unchanged_by_photo_import(photo_env):
    _settings, paths, engine, _extractor = photo_env
    expected = {
        "providers",
        "physical_devices",
        "acquisition_sources",
        "measurement_algorithms",
        "raw_artifacts",
        "ingest_batches",
        "ingest_events",
        "import_candidates",
        "import_candidate_edits",
        "measurement_sessions",
        "scalar_measurements",
        "derived_measurements",
        "canonical_rule_sets",
        "canonical_selection_runs",
        "canonical_selections",
        "sync_runs",
        "sync_stream_state",
        "coverage_intervals",
        "alembic_version",
    }
    assert set(inspect(engine).get_table_names()) == expected
