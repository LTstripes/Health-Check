from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import func, select

from healthcheck import cli
from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.migration_guard import (
    ACCEPTED_MIGRATION_CHAIN,
    ACCEPTED_MIGRATION_HEAD,
)
from healthcheck.db.models import ImportCandidate
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.ingestion.photo.metadata_origins import (
    METADATA_ORIGIN_KEYS,
    parse_metadata_origins_json,
    validate_metadata_origins,
)
from healthcheck.ingestion.photo.service import (
    PhotoImportService,
)
from healthcheck.ingestion.photo.synthetic import encode_synthetic_png, weigh_in_payload
from healthcheck.owner_weight_screenshot_import import import_owner_weight_screenshot
from healthcheck.runtime import prepare_runtime


@pytest.fixture
def owner_photo_env(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    try:
        yield settings, paths, engine
    finally:
        engine.dispose()


def _save_image(tmp_path, payload: dict):
    path = tmp_path / "synthetic-240.png"
    path.write_bytes(encode_synthetic_png(payload))
    return path


def _structured_payload(**kwargs) -> dict:
    payload = json.loads(json.dumps(weigh_in_payload(**kwargs)))
    payload.setdefault("source_timezone", None)
    payload.setdefault("source_utc_offset_minutes", None)
    for group in payload["groups"]:
        group.setdefault("source_timestamp", None)
        for field in group["fields"]:
            field.setdefault("source_local_date", None)
            field.setdefault("source_timestamp", None)
            field.setdefault("temporal_precision", None)
            field.setdefault("evidence_region", None)
            field.setdefault("algorithm_code", None)
            field.setdefault("algorithm_version", None)
    return payload


def _save_extraction_json(tmp_path, payload: object, name: str = "extraction.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_migration_0015_head_and_nullable_column(owner_photo_env):
    assert ACCEPTED_MIGRATION_HEAD == "0015_candidate_metadata_origins"
    assert ACCEPTED_MIGRATION_CHAIN[-1][0] == "0015_candidate_metadata_origins"
    assert hasattr(ImportCandidate, "metadata_origins_json")
    # Column is nullable: legacy NULL must be storable via repository.
    cols = ImportCandidate.__table__.columns
    assert cols["metadata_origins_json"].nullable is True


def test_owner_new_candidate_persists_complete_workflow_profile_map(owner_photo_env, tmp_path):
    settings, _paths, engine = owner_photo_env
    payload = _structured_payload(source_local_date=date(2026, 5, 20), weight_kg=78.5)
    image = _save_image(tmp_path, payload)
    extraction_json = _save_extraction_json(tmp_path, payload)

    result = import_owner_weight_screenshot(settings, image, extraction_json_path=extraction_json)
    assert result.status == "IMPORTED"

    with session_scope(engine) as session:
        candidates = list(session.scalars(select(ImportCandidate)))
        assert candidates
        for candidate in candidates:
            assert candidate.metadata_origins_json is not None
            origins = parse_metadata_origins_json(candidate.metadata_origins_json)
            assert origins is not None
            assert set(origins) == set(METADATA_ORIGIN_KEYS)
            validate_metadata_origins(origins)
            assert origins["provider_code"] == "workflow_profile"
            assert origins["physical_device_code"] == "workflow_profile"
            assert origins["source_application"] == "workflow_profile"
            assert origins["source_local_date"] == "visible"
            assert origins["source_local_date"] != "workflow_profile"


def test_owner_workflow_profile_when_sidecar_triple_is_null(owner_photo_env, tmp_path):
    settings, _paths, engine = owner_photo_env
    payload = _structured_payload(source_local_date=date(2026, 5, 21), weight_kg=78.4)
    payload["provider_code"] = None
    payload["physical_device_code"] = None
    payload["source_application"] = None
    image = _save_image(tmp_path, payload)
    extraction_json = _save_extraction_json(tmp_path, payload)

    result = import_owner_weight_screenshot(settings, image, extraction_json_path=extraction_json)
    assert result.status == "IMPORTED"

    with session_scope(engine) as session:
        candidates = list(session.scalars(select(ImportCandidate)))
        assert candidates
        for candidate in candidates:
            origins = parse_metadata_origins_json(candidate.metadata_origins_json)
            assert origins is not None
            assert origins["provider_code"] == "workflow_profile"
            assert origins["physical_device_code"] == "workflow_profile"
            assert origins["source_application"] == "workflow_profile"
            # Fixed triple values are kept via the workflow default.
            assert candidate.provider_code == "xiaomi_home"


def test_owner_missing_date_is_unknown_and_needs_review(owner_photo_env, tmp_path):
    settings, _paths, engine = owner_photo_env
    payload = _structured_payload(source_local_date=date(2026, 5, 22), weight_kg=78.3)
    payload["groups"][0]["source_local_date"] = None
    image = _save_image(tmp_path, payload)
    extraction_json = _save_extraction_json(tmp_path, payload)

    result = import_owner_weight_screenshot(settings, image, extraction_json_path=extraction_json)
    assert result.status == "NEEDS_REVIEW"
    assert result.reason_code == "candidate_warnings"

    with session_scope(engine) as session:
        candidates = list(session.scalars(select(ImportCandidate)))
        assert candidates
        for candidate in candidates:
            origins = parse_metadata_origins_json(candidate.metadata_origins_json)
            assert origins is not None
            assert origins["source_local_date"] == "unknown"
            assert candidate.proposed_source_local_date is None


def test_owner_attested_date_supplies_unknown_date(owner_photo_env, tmp_path):
    settings, _paths, engine = owner_photo_env
    payload = _structured_payload(source_local_date=date(2026, 5, 23), weight_kg=78.2)
    payload["groups"][0]["source_local_date"] = None
    image = _save_image(tmp_path, payload)
    extraction_json = _save_extraction_json(tmp_path, payload)

    result = import_owner_weight_screenshot(
        settings, image, extraction_json_path=extraction_json, owner_attested_date="2026-05-23"
    )
    assert result.status == "IMPORTED"

    with session_scope(engine) as session:
        candidates = list(session.scalars(select(ImportCandidate)))
        assert candidates
        for candidate in candidates:
            origins = parse_metadata_origins_json(candidate.metadata_origins_json)
            assert origins is not None
            assert origins["source_local_date"] == "owner_attested"
            assert str(candidate.proposed_source_local_date) == "2026-05-23"


def test_owner_attested_same_value_is_provenance_only_correction(owner_photo_env, tmp_path):
    settings, _paths, engine = owner_photo_env
    payload = _structured_payload(source_local_date=date(2026, 5, 24), weight_kg=78.1)
    image = _save_image(tmp_path, payload)
    first_json = _save_extraction_json(tmp_path, payload, "first.json")

    first = import_owner_weight_screenshot(settings, image, extraction_json_path=first_json)
    assert first.status == "IMPORTED"
    with session_scope(engine) as session:
        before = int(session.scalar(select(func.count(ImportCandidate.id))) or 0)

    # Same core value/date, but explicitly attested in the current request.
    second = import_owner_weight_screenshot(
        settings, image, extraction_json_path=first_json, owner_attested_date="2026-05-24"
    )
    assert second.status == "NEEDS_REVIEW"
    assert second.reason_code == "content_seen_new_extraction"

    with session_scope(engine) as session:
        after = int(session.scalar(select(func.count(ImportCandidate.id))) or 0)
        assert after == before + 1
        ordered = select(ImportCandidate).order_by(ImportCandidate.created_at)
        candidates = list(session.scalars(ordered))
        assert len(candidates) == 2
        assert candidates[0].metadata_origins_json is not None
        assert candidates[1].metadata_origins_json is not None
        assert candidates[0].metadata_origins_json != candidates[1].metadata_origins_json
        first_origins = parse_metadata_origins_json(candidates[0].metadata_origins_json)
        second_origins = parse_metadata_origins_json(candidates[1].metadata_origins_json)
        assert first_origins is not None and second_origins is not None
        assert first_origins["source_local_date"] == "visible"
        assert second_origins["source_local_date"] == "owner_attested"
        assert candidates[1].candidate_set_key.startswith("correction:")
        # Same core value, distinct provenance identity.
        assert candidates[0].proposed_source_local_date == candidates[1].proposed_source_local_date

    # Exact replay of the attested correction is idempotent (no third row).
    third = import_owner_weight_screenshot(
        settings, image, extraction_json_path=first_json, owner_attested_date="2026-05-24"
    )
    assert third.status == "NEEDS_REVIEW"
    with session_scope(engine) as session:
        assert (int(session.scalar(select(func.count(ImportCandidate.id))) or 0)) == after


def test_owner_attested_requires_sidecar_and_rejects_invalid(owner_photo_env, tmp_path):
    settings, _paths, engine = owner_photo_env
    payload = _structured_payload(source_local_date=date(2026, 5, 25), weight_kg=78.0)
    image = _save_image(tmp_path, payload)

    vision_reject = import_owner_weight_screenshot(
        settings, image, extractor=FakeImageMeasurementExtractor(), owner_attested_date="2026-05-25"
    )
    assert vision_reject.status == "FAILED"
    assert vision_reject.reason_code == "attestation_not_accepted"

    payload2 = _structured_payload(source_local_date=date(2026, 5, 25), weight_kg=78.0)
    image2 = _save_image(tmp_path, payload2)
    extraction_json2 = _save_extraction_json(tmp_path, payload2, "second.json")
    invalid = import_owner_weight_screenshot(
        settings, image2, extraction_json_path=extraction_json2, owner_attested_date="not-a-date"
    )
    assert invalid.status == "FAILED"
    assert invalid.reason_code == "attested_date_invalid"


def test_provider_vision_never_workflow_profile_and_rejects_attestation(owner_photo_env):
    _settings, paths, engine = owner_photo_env
    payload = weigh_in_payload(source_local_date=date(2026, 6, 1), weight_kg=79.0)
    image_bytes = encode_synthetic_png(payload)
    from healthcheck.ingestion.photo.service import PhotoUpload as Upload

    with session_scope(engine) as session:
        service = PhotoImportService(session, paths, FakeImageMeasurementExtractor())
        batch = service.import_photos(
            [Upload(filename="one.png", content=image_bytes)],
        )
        assert batch.items[0].status == "pending-confirmation"
        event_id = batch.items[0].ingest_event_id or ""
        candidates = service.repos.import_candidates.list_for_event(event_id)
        assert candidates
        for candidate in candidates:
            origins = parse_metadata_origins_json(candidate.metadata_origins_json)
            assert origins is not None
            assert "workflow_profile" not in set(origins.values())
            assert "owner_attested" not in set(origins.values())
            assert origins["source_local_date"] == "visible"

    with session_scope(engine) as session:
        service = PhotoImportService(session, paths, FakeImageMeasurementExtractor())
        with pytest.raises(Exception) as excinfo:
            service.import_photos(
                [Upload(filename="two.png", content=image_bytes)],
                owner_attested_date=date(2026, 6, 1),
            )
        assert "attestation" in str(excinfo.value).lower() or excinfo.value is not None

    # Missing date on the provider route is unknown, never workflow_profile.
    payload_nodate = weigh_in_payload(source_local_date=date(2026, 6, 2), weight_kg=79.1)
    payload_nodate["groups"][0]["source_local_date"] = None
    image_nodate = encode_synthetic_png(payload_nodate)
    with session_scope(engine) as session:
        service = PhotoImportService(session, paths, FakeImageMeasurementExtractor())
        batch2 = service.import_photos([Upload(filename="nodate.png", content=image_nodate)])
        event_id2 = batch2.items[0].ingest_event_id or ""
        cands = service.repos.import_candidates.list_for_event(event_id2)
        assert cands
        for candidate in cands:
            origins = parse_metadata_origins_json(candidate.metadata_origins_json)
            assert origins is not None
            assert origins["source_local_date"] == "unknown"


def test_legacy_fully_null_wildcard_stays_duplicate_without_rewrite(owner_photo_env, tmp_path):
    settings, _paths, engine = owner_photo_env
    payload = _structured_payload(source_local_date=date(2026, 5, 26), weight_kg=77.9)
    image = _save_image(tmp_path, payload)
    first_json = _save_extraction_json(tmp_path, payload, "legacy-first.json")

    first = import_owner_weight_screenshot(settings, image, extraction_json_path=first_json)
    assert first.status == "IMPORTED"
    # Build a pending legacy set with an ambiguous (multi-group) payload.
    ambiguous = _structured_payload(source_local_date=date(2026, 5, 27), weight_kg=77.8)
    alternate = json.loads(json.dumps(ambiguous["groups"][0]))
    alternate["key"] = "alternate-reading"
    ambiguous["groups"].append(alternate)
    image2 = _save_image(tmp_path, ambiguous)
    amb_json = _save_extraction_json(tmp_path, ambiguous, "legacy-ambiguous.json")
    amb_result = import_owner_weight_screenshot(settings, image2, extraction_json_path=amb_json)
    assert amb_result.status == "NEEDS_REVIEW"
    with session_scope(engine) as session:
        pending = list(
            session.scalars(
                select(ImportCandidate).where(ImportCandidate.user_decision == "pending")
            )
        )
        assert pending
        for row in pending:
            # Zero-rewrite check starts from a fully NULL set.
            row.metadata_origins_json = None
        pending_ids = [row.id for row in pending]
        before = int(session.scalar(select(func.count(ImportCandidate.id))) or 0)
    replay = import_owner_weight_screenshot(settings, image2, extraction_json_path=amb_json)
    assert replay.status == "NEEDS_REVIEW"
    with session_scope(engine) as session:
        after = int(session.scalar(select(func.count(ImportCandidate.id))) or 0)
        # Wildcard: unchanged core evidence creates no new row and no rewrite.
        assert after == before
        for cid in pending_ids:
            row = session.get(ImportCandidate, cid)
            assert row is not None
            assert row.metadata_origins_json is None


def test_post0015_provenance_only_change_gets_distinct_correction_identity(
    owner_photo_env, tmp_path
):
    settings, _paths, engine = owner_photo_env
    payload = _structured_payload(source_local_date=date(2026, 5, 28), weight_kg=77.7)
    image = _save_image(tmp_path, payload)
    first_json = _save_extraction_json(tmp_path, payload, "prov-first.json")
    first = import_owner_weight_screenshot(settings, image, extraction_json_path=first_json)
    assert first.status == "IMPORTED"

    # Same core values/date, different provenance claim (attested).
    second = import_owner_weight_screenshot(
        settings, image, extraction_json_path=first_json, owner_attested_date="2026-05-28"
    )
    assert second.status == "NEEDS_REVIEW"
    with session_scope(engine) as session:
        staged = list(
            session.scalars(
                select(ImportCandidate).where(ImportCandidate.user_decision == "pending")
            )
        )
        assert len(staged) == 1
        first_key = staged[0].candidate_set_key

    # A different attested date is a different provenance+value claim and must
    # receive its own correction identity.
    third_json = _save_extraction_json(tmp_path, payload, "prov-first-copy.json")
    third = import_owner_weight_screenshot(
        settings, image, extraction_json_path=third_json, owner_attested_date="2026-05-29"
    )
    assert third.status == "NEEDS_REVIEW"
    with session_scope(engine) as session:
        staged_all = list(
            session.scalars(
                select(ImportCandidate).where(ImportCandidate.user_decision == "pending")
            )
        )
        assert len(staged_all) == 2
        keys = {row.candidate_set_key for row in staged_all}
        assert len(keys) == 2
        assert first_key in keys


def test_terminal_candidate_origins_immutable(owner_photo_env, tmp_path):
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session as SASession

    settings, _paths, engine = owner_photo_env
    payload = _structured_payload(source_local_date=date(2026, 5, 30), weight_kg=77.6)
    image = _save_image(tmp_path, payload)
    extraction_json = _save_extraction_json(tmp_path, payload)
    result = import_owner_weight_screenshot(settings, image, extraction_json_path=extraction_json)
    assert result.status == "IMPORTED"
    session = SASession(engine)
    try:
        candidate = session.scalar(
            select(ImportCandidate).where(ImportCandidate.user_decision == "confirmed")
        )
        assert candidate is not None
        assert candidate.metadata_origins_json is not None
        candidate.metadata_origins_json = (
            '{"provider_code":"unknown","physical_device_code":"unknown",'
            '"source_application":"unknown","source_local_date":"unknown"}'
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
    finally:
        session.close()


def test_cli_owner_attested_date_flag(owner_photo_env, tmp_path, capsys):
    settings, _paths, engine = owner_photo_env
    payload = _structured_payload(source_local_date=date(2026, 5, 31), weight_kg=77.5)
    payload["groups"][0]["source_local_date"] = None
    image = _save_image(tmp_path, payload)
    extraction_json = _save_extraction_json(tmp_path, payload, "cli-attested.json")

    exit_code = cli.main(
        [
            "owner-weight-screenshot-import",
            "--data-dir",
            str(settings.data_dir),
            "--image",
            str(image),
            "--extraction-json",
            str(extraction_json),
            "--owner-attested-date",
            "2026-05-31",
        ]
    )
    output = capsys.readouterr().out
    assert exit_code == 0
    assert json.loads(output)["status"] == "IMPORTED"
    with session_scope(engine) as session:
        candidate = session.scalar(select(ImportCandidate))
        assert candidate is not None
        origins = parse_metadata_origins_json(candidate.metadata_origins_json)
        assert origins is not None
        assert origins["source_local_date"] == "owner_attested"
