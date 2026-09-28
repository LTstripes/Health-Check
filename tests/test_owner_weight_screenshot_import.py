from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import func, select

from healthcheck import cli
from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.models import (
    AcquisitionSource,
    CanonicalSelection,
    ImportCandidate,
    IngestEvent,
    MeasurementAlgorithm,
    MeasurementSession,
    PhysicalDevice,
    Provider,
    RawArtifact,
    ScalarMeasurement,
)
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.ingestion.photo.synthetic import encode_synthetic_png, weigh_in_payload
from healthcheck.ingestion.photo.vision import OWNER_ASSISTED_EXTRACTOR_NAME
from healthcheck.owner_weight_screenshot_import import (
    MAX_EXTRACTION_JSON_BYTES,
    import_owner_weight_screenshot,
)
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


def _counts(engine) -> dict[str, int]:
    with session_scope(engine) as session:
        return {
            "candidates": int(session.scalar(select(func.count(ImportCandidate.id))) or 0),
            "sessions": int(session.scalar(select(func.count(MeasurementSession.id))) or 0),
            "measurements": int(session.scalar(select(func.count(ScalarMeasurement.id))) or 0),
            "canonical": int(session.scalar(select(func.count(CanonicalSelection.id))) or 0),
        }


def _save_image(tmp_path, payload: dict) -> object:
    path = tmp_path / "private-79.85-2026-01-14.png"
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


def test_clear_xiaomi_screenshot_auto_confirms_through_r01_provenance(owner_photo_env, tmp_path):
    settings, _paths, engine = owner_photo_env
    image = _save_image(
        tmp_path,
        weigh_in_payload(
            source_local_date=date(2026, 1, 14),
            weight_kg=79.85,
            body_fat_pct=23.8,
            muscle_mass_kg=32.1,
        ),
    )

    result = import_owner_weight_screenshot(
        settings, image, extractor=FakeImageMeasurementExtractor()
    )

    assert result.status == "IMPORTED"
    assert result.reason_code == "auto_confirmed"
    assert result.candidate_count == result.measurement_count == 3
    assert _counts(engine) == {"candidates": 3, "sessions": 1, "measurements": 3, "canonical": 3}
    with session_scope(engine) as session:
        source = session.scalar(select(AcquisitionSource))
        assert source is not None
        provider = session.get(Provider, source.provider_id)
        device = session.get(PhysicalDevice, source.physical_device_id)
        assert provider is not None and provider.code == "xiaomi_home"
        assert device is not None and device.code == "xiaomi_s400"
        assert source.input_method == "photo_import"
        assert source.source_application == "Xiaomi Home"
        session_row = session.scalar(select(MeasurementSession))
        assert session_row is not None and session_row.temporal_precision == "date"
        assert session_row.source_timestamp_utc is None
        assert session_row.source_local_date == date(2026, 1, 14)
        by_metric = {
            row.metric_code: row
            for row in session.scalars(select(ScalarMeasurement))
        }
        assert set(by_metric) == {"weight", "body_fat_pct", "muscle_mass"}
        weight_algorithm = session.get(
            MeasurementAlgorithm, by_metric["weight"].measurement_algorithm_id
        )
        body_fat_algorithm = session.get(
            MeasurementAlgorithm, by_metric["body_fat_pct"].measurement_algorithm_id
        )
        muscle_algorithm = session.get(
            MeasurementAlgorithm, by_metric["muscle_mass"].measurement_algorithm_id
        )
        assert weight_algorithm is not None and weight_algorithm.code == "xiaomi_s400_weight"
        assert body_fat_algorithm is not None
        assert body_fat_algorithm.code == "xiaomi_home_s400_unknown_version"
        assert muscle_algorithm is not None
        assert muscle_algorithm.code == "xiaomi_home_s400_unknown_version"
        assert {
            row.metric_code for row in session.scalars(select(CanonicalSelection))
        } == {"weight", "body_fat_pct", "muscle_mass"}


def test_replay_returns_duplicate_without_a_second_semantic_weigh_in(owner_photo_env, tmp_path):
    settings, _paths, engine = owner_photo_env
    image = _save_image(
        tmp_path,
        weigh_in_payload(source_local_date=date(2026, 2, 4), weight_kg=79.4),
    )
    extractor = FakeImageMeasurementExtractor()

    first = import_owner_weight_screenshot(settings, image, extractor=extractor)
    before_replay = _counts(engine)
    second = import_owner_weight_screenshot(settings, image, extractor=extractor)

    assert first.status == "IMPORTED"
    assert second.status == "DUPLICATE"
    assert second.reason_code == "duplicate_content"
    assert _counts(engine) == before_replay
    assert before_replay == {"candidates": 1, "sessions": 1, "measurements": 1, "canonical": 1}


def test_owner_assisted_json_imports_without_vision_provider(
    owner_photo_env, tmp_path, monkeypatch
):
    settings, _paths, engine = owner_photo_env
    payload = _structured_payload(
        source_local_date=date(2026, 5, 8),
        weight_kg=78.6,
        body_fat_pct=23.1,
    )
    image = _save_image(tmp_path, payload)
    extraction_json = _save_extraction_json(tmp_path, payload)

    def reject_provider(_settings):
        raise AssertionError("configured vision provider must not be built")

    monkeypatch.setattr(
        "healthcheck.owner_weight_screenshot_import.build_photo_extractor",
        reject_provider,
    )

    result = import_owner_weight_screenshot(
        settings,
        image,
        extraction_json_path=extraction_json,
    )

    assert result.status == "IMPORTED"
    assert result.reason_code == "auto_confirmed"
    assert _counts(engine) == {
        "candidates": 2,
        "sessions": 1,
        "measurements": 2,
        "canonical": 2,
    }
    with session_scope(engine) as session:
        candidate = session.scalar(select(ImportCandidate).order_by(ImportCandidate.metric_code))
        measurement_session = session.scalar(select(MeasurementSession))
        assert candidate is not None
        assert candidate.extractor_name == OWNER_ASSISTED_EXTRACTOR_NAME
        assert candidate.model_name is None
        assert candidate.model_version is None
        assert measurement_session is not None
        assert measurement_session.temporal_precision == "date"
        assert measurement_session.source_timestamp_utc is None


def test_owner_assisted_json_replay_is_duplicate(owner_photo_env, tmp_path):
    settings, _paths, engine = owner_photo_env
    payload = _structured_payload(
        source_local_date=date(2026, 5, 9),
        weight_kg=78.5,
    )
    image = _save_image(tmp_path, payload)
    extraction_json = _save_extraction_json(tmp_path, payload)

    first = import_owner_weight_screenshot(
        settings,
        image,
        extraction_json_path=extraction_json,
    )
    before_replay = _counts(engine)
    second = import_owner_weight_screenshot(
        settings,
        image,
        extraction_json_path=extraction_json,
    )

    assert first.status == "IMPORTED"
    assert second.status == "DUPLICATE"
    assert second.reason_code == "duplicate_content"
    assert _counts(engine) == before_replay


@pytest.mark.parametrize(
    ("payload", "expected_reason"),
    [
        ("not-json-private-78.4", "extraction_json_invalid"),
        (["not", "an", "object"], "extraction_json_invalid"),
    ],
)
def test_invalid_owner_assisted_json_fails_before_r01_write(
    owner_photo_env, tmp_path, payload, expected_reason
):
    settings, _paths, engine = owner_photo_env
    image_payload = _structured_payload(
        source_local_date=date(2026, 5, 10),
        weight_kg=78.4,
    )
    image = _save_image(tmp_path, image_payload)
    extraction_json = tmp_path / "private-78.4-extraction.json"
    if isinstance(payload, str):
        extraction_json.write_text(payload, encoding="utf-8")
    else:
        extraction_json.write_text(json.dumps(payload), encoding="utf-8")

    result = import_owner_weight_screenshot(
        settings,
        image,
        extraction_json_path=extraction_json,
    )

    assert result.status == "FAILED"
    assert result.reason_code == expected_reason
    assert "78.4" not in result.to_json()
    assert str(extraction_json) not in result.to_json()
    assert _counts(engine) == {
        "candidates": 0,
        "sessions": 0,
        "measurements": 0,
        "canonical": 0,
    }
    with session_scope(engine) as session:
        assert session.scalar(select(func.count(RawArtifact.id))) == 0
        assert session.scalar(select(func.count(IngestEvent.id))) == 0


def test_oversize_owner_assisted_json_fails_before_r01_write(owner_photo_env, tmp_path):
    settings, _paths, engine = owner_photo_env
    payload = _structured_payload(
        source_local_date=date(2026, 5, 11),
        weight_kg=78.3,
    )
    image = _save_image(tmp_path, payload)
    extraction_json = tmp_path / "oversize-private-extraction.json"
    extraction_json.write_bytes(b"{" + b" " * MAX_EXTRACTION_JSON_BYTES)

    result = import_owner_weight_screenshot(
        settings,
        image,
        extraction_json_path=extraction_json,
    )

    assert result.status == "FAILED"
    assert result.reason_code == "extraction_json_too_large"
    assert _counts(engine) == {
        "candidates": 0,
        "sessions": 0,
        "measurements": 0,
        "canonical": 0,
    }
    with session_scope(engine) as session:
        assert session.scalar(select(func.count(RawArtifact.id))) == 0


@pytest.mark.parametrize("mutation", ["missing_nullable_field", "unsupported_unit"])
def test_owner_assisted_json_uses_strict_vision_payload_parser(
    owner_photo_env, tmp_path, mutation
):
    settings, _paths, engine = owner_photo_env
    payload = _structured_payload(
        source_local_date=date(2026, 5, 11),
        weight_kg=78.3,
    )
    field = payload["groups"][0]["fields"][0]
    if mutation == "missing_nullable_field":
        del field["confidence"]
    else:
        field["unit"] = "stones"
    image = _save_image(tmp_path, payload)
    extraction_json = _save_extraction_json(tmp_path, payload)

    result = import_owner_weight_screenshot(
        settings,
        image,
        extraction_json_path=extraction_json,
    )

    assert result.status == "FAILED"
    assert result.reason_code == "extraction_json_invalid"
    assert _counts(engine) == {
        "candidates": 0,
        "sessions": 0,
        "measurements": 0,
        "canonical": 0,
    }
    with session_scope(engine) as session:
        assert session.scalar(select(func.count(RawArtifact.id))) == 0


def test_owner_assisted_multiple_groups_need_review_without_semantic_write(
    owner_photo_env, tmp_path
):
    settings, _paths, engine = owner_photo_env
    payload = _structured_payload(
        source_local_date=date(2026, 5, 12),
        weight_kg=78.2,
    )
    alternate = json.loads(json.dumps(payload["groups"][0]))
    alternate["key"] = "alternate-reading"
    payload["groups"].append(alternate)
    image = _save_image(tmp_path, payload)
    extraction_json = _save_extraction_json(tmp_path, payload)

    result = import_owner_weight_screenshot(
        settings,
        image,
        extraction_json_path=extraction_json,
    )

    assert result.status == "NEEDS_REVIEW"
    assert result.reason_code == "ambiguous_groups"
    assert _counts(engine) == {
        "candidates": 2,
        "sessions": 0,
        "measurements": 0,
        "canonical": 0,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_code", "other_provider"),
        ("physical_device_code", "other_device"),
        ("source_application", "Other App"),
    ],
)
def test_owner_assisted_profile_conflict_fails_closed_before_r01_write(
    owner_photo_env, tmp_path, field, value
):
    settings, _paths, engine = owner_photo_env
    payload = _structured_payload(
        source_local_date=date(2026, 5, 13),
        weight_kg=78.1,
    )
    payload[field] = value
    image = _save_image(tmp_path, payload)
    extraction_json = _save_extraction_json(tmp_path, payload)

    result = import_owner_weight_screenshot(
        settings,
        image,
        extraction_json_path=extraction_json,
    )

    assert result.status == "NEEDS_REVIEW"
    assert result.reason_code == "provenance_ambiguous"
    assert _counts(engine) == {
        "candidates": 0,
        "sessions": 0,
        "measurements": 0,
        "canonical": 0,
    }
    with session_scope(engine) as session:
        assert session.scalar(select(func.count(RawArtifact.id))) == 0


def test_same_content_with_a_new_extraction_set_requires_review(owner_photo_env, tmp_path):
    settings, _paths, engine = owner_photo_env
    image = _save_image(
        tmp_path,
        weigh_in_payload(source_local_date=date(2026, 2, 4), weight_kg=79.4),
    )
    first = import_owner_weight_screenshot(
        settings, image, extractor=FakeImageMeasurementExtractor(version="1")
    )

    second = import_owner_weight_screenshot(
        settings, image, extractor=FakeImageMeasurementExtractor(version="2")
    )

    assert first.status == "IMPORTED"
    assert second.status == "NEEDS_REVIEW"
    assert second.reason_code == "content_seen_new_extraction"
    assert _counts(engine) == {"candidates": 2, "sessions": 1, "measurements": 1, "canonical": 1}


def test_multiple_plausible_groups_fail_closed_with_no_semantic_write(owner_photo_env, tmp_path):
    settings, _paths, engine = owner_photo_env
    payload = weigh_in_payload(source_local_date=date(2026, 2, 4), weight_kg=79.4)
    second_group = dict(payload["groups"][0])
    second_group["key"] = "alternate-reading"
    payload["groups"].append(second_group)
    image = _save_image(tmp_path, payload)

    result = import_owner_weight_screenshot(
        settings, image, extractor=FakeImageMeasurementExtractor()
    )

    assert result.status == "NEEDS_REVIEW"
    assert result.reason_code == "ambiguous_groups"
    assert result.candidate_count == 2
    assert _counts(engine) == {"candidates": 2, "sessions": 0, "measurements": 0, "canonical": 0}


@pytest.mark.parametrize(
    "extractor_kwargs",
    [
        {"provider_code": "xiaomi_app_unknown"},
        {"physical_device_code": "unidentified_scale"},
        {"source_application": "unidentified_app"},
    ],
)
def test_unknown_app_or_device_provenance_fails_closed(
    owner_photo_env, tmp_path, extractor_kwargs
):
    settings, _paths, engine = owner_photo_env
    image = _save_image(
        tmp_path,
        weigh_in_payload(source_local_date=date(2026, 2, 4), weight_kg=79.4),
    )

    result = import_owner_weight_screenshot(
        settings,
        image,
        extractor=FakeImageMeasurementExtractor(**extractor_kwargs),
    )

    assert result.status == "NEEDS_REVIEW"
    assert result.reason_code == "provenance_ambiguous"
    assert _counts(engine) == {"candidates": 1, "sessions": 0, "measurements": 0, "canonical": 0}


def test_unsupported_composition_unit_fails_closed(owner_photo_env, tmp_path):
    settings, _paths, engine = owner_photo_env
    payload = weigh_in_payload(
        source_local_date=date(2026, 2, 4),
        weight_kg=79.4,
        extra_fields=[
            {
                "metric_code": "body_fat_pct",
                "value": 0.0,
                "unit": "stones",
                "source_text": None,
                "confidence": None,
            }
        ],
    )
    image = _save_image(tmp_path, payload)

    result = import_owner_weight_screenshot(
        settings, image, extractor=FakeImageMeasurementExtractor()
    )

    assert result.status == "NEEDS_REVIEW"
    assert result.reason_code == "candidate_warnings"
    assert _counts(engine) == {"candidates": 2, "sessions": 0, "measurements": 0, "canonical": 0}


def test_missing_weight_value_fails_closed(owner_photo_env, tmp_path):
    settings, _paths, engine = owner_photo_env
    payload = weigh_in_payload(source_local_date=date(2026, 2, 4), weight_kg=79.4)
    payload["groups"][0]["fields"][0]["value"] = None
    image = _save_image(tmp_path, payload)

    result = import_owner_weight_screenshot(
        settings, image, extractor=FakeImageMeasurementExtractor()
    )

    assert result.status == "NEEDS_REVIEW"
    assert result.reason_code == "value_missing_or_invalid"
    assert _counts(engine) == {"candidates": 1, "sessions": 0, "measurements": 0, "canonical": 0}


def test_time_precision_without_timestamp_fails_closed(owner_photo_env, tmp_path):
    settings, _paths, engine = owner_photo_env
    payload = weigh_in_payload(source_local_date=date(2026, 2, 4), weight_kg=79.4)
    payload["groups"][0]["temporal_precision"] = "instant"
    image = _save_image(tmp_path, payload)

    result = import_owner_weight_screenshot(
        settings, image, extractor=FakeImageMeasurementExtractor()
    )

    assert result.status == "NEEDS_REVIEW"
    assert result.reason_code == "source_timestamp_missing"
    assert _counts(engine) == {"candidates": 1, "sessions": 0, "measurements": 0, "canonical": 0}


def test_malformed_image_is_failed_without_echoing_filename_or_values(owner_photo_env, tmp_path):
    settings, _paths, engine = owner_photo_env
    image = tmp_path / "private-79.85-2026-01-14.png"
    image.write_bytes(b"not a png or jpeg")

    result = import_owner_weight_screenshot(
        settings, image, extractor=FakeImageMeasurementExtractor()
    )

    payload = result.as_dict()
    assert result.status == "FAILED"
    assert result.reason_code == "unsupported_image"
    serialized = result.to_json()
    assert "79.85" not in serialized
    assert str(image) not in serialized
    assert payload["privacy"] == {
        "raw_values_emitted": False,
        "private_identifiers_emitted": False,
        "tokens_emitted": False,
        "health_timestamps_emitted": False,
    }
    assert _counts(engine) == {"candidates": 0, "sessions": 0, "measurements": 0, "canonical": 0}


def test_extractor_failure_keeps_r01_artifact_and_emits_no_private_detail(
    owner_photo_env, tmp_path
):
    settings, _paths, engine = owner_photo_env
    image = tmp_path / "private-81.2-2026-04-06.jpg"
    image.write_bytes(b"\xff\xd8\xffnot-a-readable-jpeg")

    result = import_owner_weight_screenshot(
        settings, image, extractor=FakeImageMeasurementExtractor()
    )

    assert result.status == "FAILED"
    assert result.reason_code == "extraction_failed"
    assert "81.2" not in result.to_json()
    assert str(image) not in result.to_json()
    with session_scope(engine) as session:
        assert session.scalar(select(func.count(RawArtifact.id))) == 1
        event = session.scalar(select(IngestEvent))
        assert event is not None and event.status == "failed"
    assert _counts(engine) == {"candidates": 0, "sessions": 0, "measurements": 0, "canonical": 0}


def test_cli_requires_explicit_profile_and_runs_one_image(
    owner_photo_env, tmp_path, monkeypatch, capsys
):
    settings, _paths, engine = owner_photo_env
    image = _save_image(
        tmp_path,
        weigh_in_payload(source_local_date=date(2026, 3, 4), weight_kg=78.2),
    )
    monkeypatch.setattr(
        "healthcheck.owner_weight_screenshot_import.build_photo_extractor",
        lambda _settings: FakeImageMeasurementExtractor(),
    )

    exit_code = cli.main(
        [
            "owner-weight-screenshot-import",
            "--data-dir",
            str(settings.data_dir),
            "--image",
            str(image),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert json.loads(output)["status"] == "IMPORTED"
    assert str(image) not in output
    assert _counts(engine)["measurements"] == 1


def test_cli_accepts_owner_assisted_extraction_json_without_private_output(
    owner_photo_env, tmp_path, monkeypatch, capsys
):
    settings, _paths, engine = owner_photo_env
    payload = _structured_payload(
        source_local_date=date(2026, 5, 14),
        weight_kg=78.0,
    )
    image = _save_image(tmp_path, payload)
    extraction_json = _save_extraction_json(
        tmp_path,
        payload,
        name="private-78.0-extraction.json",
    )

    def reject_provider(_settings):
        raise AssertionError("configured vision provider must not be built")

    monkeypatch.setattr(
        "healthcheck.owner_weight_screenshot_import.build_photo_extractor",
        reject_provider,
    )

    exit_code = cli.main(
        [
            "owner-weight-screenshot-import",
            "--data-dir",
            str(settings.data_dir),
            "--image",
            str(image),
            "--extraction-json",
            str(extraction_json),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert json.loads(output)["status"] == "IMPORTED"
    assert "78.0" not in output
    assert str(image) not in output
    assert str(extraction_json) not in output
    assert _counts(engine)["measurements"] == 1


def test_cli_without_data_dir_fails_without_using_default_profile(tmp_path, capsys):
    image = _save_image(
        tmp_path,
        weigh_in_payload(source_local_date=date(2026, 3, 4), weight_kg=78.2),
    )

    exit_code = cli.main(["owner-weight-screenshot-import", "--image", str(image)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["status"] == "FAILED"
    assert payload["reason_code"] == "missing_data_dir"
