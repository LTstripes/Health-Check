from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, migrate_database, session_scope
from healthcheck.db.models import CanonicalSelection, ImportCandidate, MeasurementSession
from healthcheck.ingestion.photo.extractor import ExtractionFailure, ExtractionRequest
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.ingestion.photo.service import PhotoImportService, PhotoUpload
from healthcheck.ingestion.photo.vision import (
    OpenAICompatibleVisionExtractor,
    UnconfiguredImageMeasurementExtractor,
    VisionHttpResponse,
    build_photo_extractor,
)
from healthcheck.logging import configure_logging
from healthcheck.runtime import prepare_runtime
from healthcheck.web.ui_app import create_ui_app

ORDINARY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
SECRET_MARKER = "provider-secret-synthetic-77"


def _payload(
    *,
    unit: str = "kg",
    timestamp: str | None = None,
    precision: str = "date",
    value: float = 80.4,
) -> dict:
    return {
        "schema_version": "r01-photo-v1",
        "provider_code": "xiaomi_home",
        "physical_device_code": "xiaomi_s400",
        "source_application": "Xiaomi Home",
        "source_application_version": None,
        "source_timezone": None,
        "source_utc_offset_minutes": None,
        "groups": [
            {
                "key": "weigh-in-2026-09-05",
                "source_local_date": "2026-09-05",
                "source_timestamp": timestamp,
                "temporal_precision": precision,
                "fields": [
                    {
                        "metric_code": "weight",
                        "value": value,
                        "unit": unit,
                        "source_text": "80.4 kg",
                        "confidence": None,
                        "source_local_date": None,
                        "source_timestamp": None,
                        "temporal_precision": None,
                        "evidence_region": None,
                        "algorithm_code": None,
                        "algorithm_version": None,
                    }
                ],
            }
        ],
    }


def _response(payload: dict, *, status_code: int = 200, model: str = "vision-model-v1"):
    envelope = {
        "id": "chatcmpl-synthetic",
        "model": model,
        "choices": [{"message": {"content": json.dumps(payload)}}],
    }
    return VisionHttpResponse(status_code, json.dumps(envelope).encode("utf-8"))


def _extractor(
    transport: Callable[[str, dict[str, str], bytes, float], VisionHttpResponse],
    **kwargs,
) -> OpenAICompatibleVisionExtractor:
    return OpenAICompatibleVisionExtractor(
        base_url="https://vision.example.invalid/v1",
        model_name="vision-model",
        api_key=SECRET_MARKER,
        transport=transport,
        **kwargs,
    )


def _service_env(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "runtime")
    paths = prepare_runtime(settings)
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    return settings, paths, engine


def _count(session, model) -> int:
    return int(session.scalar(select(func.count(model.id))) or 0)


def test_factory_never_selects_synthetic_fake_by_default(tmp_path):
    settings = Settings(data_dir=tmp_path / "runtime")
    selected = build_photo_extractor(settings)

    assert isinstance(selected, UnconfiguredImageMeasurementExtractor)
    assert not isinstance(selected, FakeImageMeasurementExtractor)
    with pytest.raises(ExtractionFailure) as failure:
        selected.extract(
            ExtractionRequest("artifact", "hash", "image/png"),
            ORDINARY_PNG,
        )
    assert failure.value.code == "extractor_not_configured"
    assert SECRET_MARKER not in failure.value.message


def test_configured_runtime_uses_real_adapter_and_calls_provider_only_on_import(
    tmp_path, monkeypatch
):
    settings = Settings(
        data_dir=tmp_path / "runtime",
        photo_vision_base_url="https://vision.example.invalid/v1",
        photo_vision_model="vision-model",
        photo_vision_api_key=SECRET_MARKER,
        photo_vision_provider_code="xiaomi_home",
        photo_vision_physical_device_code="xiaomi_s400",
        photo_vision_source_application="Xiaomi Home",
        photo_vision_source_application_version="9.0-synthetic-profile",
    )
    paths = prepare_runtime(settings)
    migrate_database(paths)
    calls: list[tuple[str, dict[str, str], bytes, float]] = []

    def transport(url, headers, body, timeout):
        calls.append((url, dict(headers), body, timeout))
        return _response(_payload())

    monkeypatch.setattr(
        "healthcheck.ingestion.photo.vision._default_transport",
        transport,
    )
    app, _ = create_ui_app(settings)
    assert isinstance(app.state.photo_extractor, OpenAICompatibleVisionExtractor)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/imports").status_code == 200
        assert calls == []
        uploaded = client.post(
            "/api/imports/photos",
            files=[("files", ("ordinary.png", ORDINARY_PNG, "image/png"))],
        )
        assert uploaded.status_code == 200, uploaded.text
        body = uploaded.json()
        assert SECRET_MARKER not in uploaded.text
        assert body["status"] == "pending-confirmation"
        assert body["items"][0]["candidate_ids"]
        assert body["items"][0]["diagnostic_code"] is None
        assert len(calls) == 1

        request_json = json.loads(calls[0][2])
        assert SECRET_MARKER not in calls[0][2].decode("utf-8")
        assert calls[0][0] == "https://vision.example.invalid/v1/chat/completions"
        assert calls[0][1]["Authorization"] == f"Bearer {SECRET_MARKER}"
        assert request_json["response_format"]["type"] == "json_schema"
        image_part = request_json["messages"][1]["content"][1]
        assert image_part["image_url"]["url"].startswith("data:image/png;base64,")

        detail = client.get(f"/api/imports/{body['id']}").json()
        candidate = detail["candidates"][0]
        assert candidate["user_decision"] == "pending"
        assert candidate["extractor_name"] == "healthcheck-openai-compatible-vision"
        assert candidate["model_name"] == "vision-model"
        assert candidate["model_version"] == "vision-model-v1"
        assert candidate["prompt_version"] == "r01-xiaomi-s400-v1"
        assert candidate["schema_version"] == "r01-photo-v1"
        assert candidate["provenance"]["source_application_version"] == "9.0-synthetic-profile"
        assert candidate["proposed_source_timestamp"] is None
        assert candidate["temporal_precision"] == "date"
        assert candidate["confidence"] is None

    verification_engine = create_sqlite_engine(paths)
    try:
        with session_scope(verification_engine) as session:
            assert _count(session, MeasurementSession) == 0
            assert _count(session, CanonicalSelection) == 0
    finally:
        verification_engine.dispose()


def test_real_success_is_confirmed_only_after_explicit_owner_action(tmp_path):
    settings, paths, engine = _service_env(tmp_path)

    def transport(url, headers, body, timeout):
        del url, headers, body, timeout
        return _response(_payload())

    extractor = _extractor(transport)
    try:
        with session_scope(engine) as session:
            service = PhotoImportService(session, paths, extractor)
            imported = service.import_photos([PhotoUpload("ordinary.png", ORDINARY_PNG)])
            candidate_ids = imported.items[0].candidate_ids
            assert imported.batch.status == "pending-confirmation"
            assert candidate_ids
            assert _count(session, MeasurementSession) == 0
            assert _count(session, CanonicalSelection) == 0
            confirmed = service.confirm(candidate_ids)
            assert confirmed
        with session_scope(engine) as session:
            assert _count(session, MeasurementSession) == 1
            assert _count(session, CanonicalSelection) > 0
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (_payload(unit="stones"), "extractor_invalid_payload"),
        (
            _payload(timestamp="2026-09-05T00:00:00Z", precision="date"),
            "extractor_invalid_payload",
        ),
        (
            _payload(timestamp="2026-09-05T10:00:00", precision="instant"),
            "extractor_invalid_payload",
        ),
    ],
)
def test_structured_response_rejects_unsafe_units_and_temporal_repairs(payload, expected_code):
    def transport(url, headers, body, timeout):
        del url, headers, body, timeout
        return _response(payload)

    with pytest.raises(ExtractionFailure) as failure:
        _extractor(transport).extract(
            ExtractionRequest("artifact", "hash", "image/png"),
            ORDINARY_PNG,
        )
    assert failure.value.code == expected_code
    assert "midnight" not in failure.value.message.lower()


def test_structured_response_requires_explicit_nullable_fields():
    payload = _payload()
    del payload["groups"][0]["fields"][0]["confidence"]

    def transport(url, headers, body, timeout):
        del url, headers, body, timeout
        return _response(payload)

    with pytest.raises(ExtractionFailure) as failure:
        _extractor(transport).extract(
            ExtractionRequest("artifact", "hash", "image/png"),
            ORDINARY_PNG,
        )
    assert failure.value.code == "extractor_invalid_payload"


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (VisionHttpResponse(200, SECRET_MARKER.encode("utf-8")), "extractor_malformed_response"),
        (VisionHttpResponse(502, SECRET_MARKER.encode("utf-8")), "extractor_provider_error"),
    ],
)
def test_malformed_and_provider_responses_never_echo_secret(response, expected_code):
    def transport(url, headers, body, timeout):
        del url, headers, body, timeout
        return response

    with pytest.raises(ExtractionFailure) as failure:
        _extractor(transport).extract(
            ExtractionRequest("artifact", "hash", "image/png"),
            ORDINARY_PNG,
        )
    assert failure.value.code == expected_code
    assert SECRET_MARKER not in str(failure.value)
    if expected_code == "extractor_malformed_response":
        assert failure.value.__cause__ is None


def test_network_failure_is_typed_without_provider_exception_details():
    def transport(url, headers, body, timeout):
        del url, headers, body, timeout
        raise RuntimeError(SECRET_MARKER)

    with pytest.raises(ExtractionFailure) as failure:
        _extractor(transport).extract(
            ExtractionRequest("artifact", "hash", "image/png"),
            ORDINARY_PNG,
        )
    assert failure.value.code == "extractor_network_error"
    assert SECRET_MARKER not in str(failure.value)
    assert failure.value.__cause__ is None


def test_unconfigured_api_preserves_artifact_and_has_no_fake_or_confirmed_data(tmp_path):
    settings, paths, engine = _service_env(tmp_path)
    app, _ = create_ui_app(settings)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/imports/photos",
                files=[("files", ("ordinary.png", ORDINARY_PNG, "image/png"))],
            )
            assert response.status_code == 200
            item = response.json()["items"][0]
            assert item["status"] == "failed"
            assert item["diagnostic_code"] == "extractor_not_configured"
            assert item["diagnostic_reason"] == "extractor_not_configured"
            assert item["candidate_ids"] == []
            assert "provider-secret" not in response.text
        assert list(paths.photos.rglob("*.png"))
        with session_scope(engine) as session:
            assert _count(session, ImportCandidate) == 0
            assert _count(session, MeasurementSession) == 0
    finally:
        engine.dispose()


def test_provider_failure_is_sanitized_and_artifact_replays_successfully(tmp_path):
    settings, paths, engine = _service_env(tmp_path)
    responses = iter(
        [
            VisionHttpResponse(503, SECRET_MARKER.encode("utf-8")),
            _response(_payload()),
        ]
    )

    def transport(url, headers, body, timeout):
        del url, headers, body, timeout
        return next(responses)

    extractor = _extractor(transport)
    log_path = configure_logging(paths.logs)
    try:
        with session_scope(engine) as session:
            service = PhotoImportService(session, paths, extractor)
            failed = service.import_photos([PhotoUpload("ordinary.png", ORDINARY_PNG)])
            item = failed.items[0]
            assert item.status == "failed"
            assert item.diagnostic_code == "extractor_provider_error"
            assert item.diagnostic_reason == "extractor_provider_error"
            replayed = service.reprocess_event(item.ingest_event_id)
            assert replayed.failed is False
            assert replayed.candidates
        assert SECRET_MARKER not in log_path.read_text(encoding="utf-8")
        assert SECRET_MARKER not in (paths.photos.parent / item.relative_storage_path).read_text(
            encoding="utf-8", errors="ignore"
        )
    finally:
        engine.dispose()
