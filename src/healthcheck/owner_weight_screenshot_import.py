"""Owner-only Xiaomi Home screenshot import through the R01 photo workflow."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.config import Settings
from healthcheck.db.engine import create_sqlite_engine, session_scope
from healthcheck.db.models import ImportCandidate
from healthcheck.ingestion.photo.errors import PhotoImportError
from healthcheck.ingestion.photo.extractor import (
    DEFAULT_SCHEMA_VERSION,
    ExtractionFailure,
    ExtractionRequest,
    ExtractionResult,
    ImageMeasurementExtractor,
)
from healthcheck.ingestion.photo.normalize import NormalizedField
from healthcheck.ingestion.photo.provenance import (
    WEIGHT_ALGORITHM_CODE,
    XIAOMI_HOME_COMPOSITION_ALGORITHM,
    XIAOMI_HOME_PROVIDER,
    XIAOMI_S400_DEVICE,
)
from healthcheck.ingestion.photo.service import (
    MAX_PHOTO_BYTES,
    PhotoImportService,
    PhotoUpload,
    candidate_core_evidence_fingerprint,
    candidate_evidence_fingerprint,
    extraction_core_evidence_fingerprint,
    extraction_evidence_fingerprint,
    normalize_extraction_result,
)
from healthcheck.ingestion.photo.vision import (
    MAX_PROVIDER_RESPONSE_BYTES,
    OwnerAssistedStructuredExtractor,
    build_photo_extractor,
)
from healthcheck.owner_refresh import OwnerRefreshRuntimeError, require_established_runtime
from healthcheck.runtime import RuntimePaths

OWNER_WEIGHT_SCREENSHOT_IMPORT_VERSION = "owner-weight-screenshot-import-v1"
MAX_EXTRACTION_JSON_BYTES = MAX_PROVIDER_RESPONSE_BYTES
_XIAOMI_PHOTO_METRICS = frozenset(
    {"weight", "body_fat_pct", "muscle_mass", "water_pct", "bone_mass", "bone_pct"}
)


@dataclass(frozen=True, slots=True)
class OwnerWeightScreenshotImportResult:
    status: str
    reason_code: str
    candidate_count: int = 0
    measurement_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": OWNER_WEIGHT_SCREENSHOT_IMPORT_VERSION,
            "operation": "owner-weight-screenshot-import",
            "status": self.status,
            "reason_code": self.reason_code,
            "candidate_count": self.candidate_count,
            "measurement_count": self.measurement_count,
            "privacy": {
                "raw_values_emitted": False,
                "private_identifiers_emitted": False,
                "tokens_emitted": False,
                "health_timestamps_emitted": False,
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=True, sort_keys=True)

    @property
    def exit_code(self) -> int:
        if self.status in {"IMPORTED", "DUPLICATE"}:
            return 0
        if self.status == "NEEDS_REVIEW":
            return 3
        return 1


def import_owner_weight_screenshot(
    settings: Settings,
    image_path: str | Path | None,
    *,
    extraction_json_path: str | Path | None = None,
    extractor: ImageMeasurementExtractor | None = None,
    owner_attested_date: str | Path | date | None = None,
) -> OwnerWeightScreenshotImportResult:
    """Import one image and auto-confirm only a single complete, evidenced set.

    The import transaction commits before the auto-confirm decision. Ambiguous
    candidates therefore remain in the R01 review queue without creating a
    measurement or changing canonical selection.
    """

    engine: Engine | None = None
    prevalidated: ExtractionResult | None = None
    normalized_evidence: tuple[tuple[str, NormalizedField], ...] | None = None
    try:
        if image_path is None:
            return _result("FAILED", "missing_image")
        attested_date = _parsed_owner_attested_date(owner_attested_date)
        if attested_date is None and owner_attested_date is not None:
            return _result("FAILED", "attested_date_invalid")
        if attested_date is not None and extraction_json_path is None:
            # Vision routes never accept Owner attestation; attestation must
            # accompany an explicit current-request sidecar.
            return _result("FAILED", "attestation_not_accepted")
        paths = require_established_runtime(settings)
        image = _read_image(image_path)
        if image is None:
            return _result("FAILED", "image_unreadable")
        if len(image) > MAX_PHOTO_BYTES:
            return _result("FAILED", "image_too_large")

        from healthcheck.ingestion.photo.store import detect_media_type

        try:
            media_type = detect_media_type(image)
        except PhotoImportError:
            return _result("FAILED", "unsupported_image")
        if media_type not in {"image/png", "image/jpeg"}:
            return _result("FAILED", "unsupported_image")

        if extraction_json_path is not None:
            if extractor is not None:
                return _result("FAILED", "conflicting_extraction_inputs")
            payload, payload_error = _read_extraction_json(extraction_json_path)
            if payload_error is not None or payload is None:
                return _result("FAILED", payload_error or "extraction_json_invalid")
            configured_extractor = OwnerAssistedStructuredExtractor(
                payload,
                configured_provider_code=XIAOMI_HOME_PROVIDER,
                configured_physical_device_code=XIAOMI_S400_DEVICE,
                configured_source_application="Xiaomi Home",
            )
            try:
                prevalidated = configured_extractor.extract(
                    ExtractionRequest(
                        artifact_id="owner-assisted-preflight",
                        content_hash=sha256(image).hexdigest(),
                        media_type=media_type,
                        schema_version=DEFAULT_SCHEMA_VERSION,
                        provider_code=XIAOMI_HOME_PROVIDER,
                        physical_device_code=XIAOMI_S400_DEVICE,
                        source_application="Xiaomi Home",
                    ),
                    image,
                )
                normalized_evidence = normalize_extraction_result(prevalidated)
            except ExtractionFailure:
                return _result("FAILED", "extraction_json_invalid")
            if attested_date is not None and not _attested_date_only_evidence(
                prevalidated, normalized_evidence
            ):
                return _result("FAILED", "attested_date_invalid")
            if _owner_profile_conflicts(prevalidated):
                return _result("NEEDS_REVIEW", "provenance_ambiguous")
        else:
            configured_extractor = extractor or _owner_extractor(settings)
        engine = create_sqlite_engine(paths)
        with session_scope(engine) as session:
            service = PhotoImportService(session, paths, configured_extractor)
            try:
                batch = service.import_photos(
                    [PhotoUpload(filename=None, content=image)],
                    provider_code=XIAOMI_HOME_PROVIDER,
                    is_owner_workflow=True,
                    owner_attested_date=attested_date,
                )
            except PhotoImportError as exc:
                if exc.code in {"attested_date_invalid", "attestation_not_accepted"}:
                    return _result("FAILED", exc.code)
                raise
        if len(batch.items) != 1:
            return _result("FAILED", "import_failed")
        item = batch.items[0]
        if item.status == "failed":
            return _result("FAILED", "extraction_failed")

        if item.status == "duplicate":
            return _duplicate_result(
                engine,
                paths,
                configured_extractor,
                item,
                expected_extraction=prevalidated,
                expected_evidence=normalized_evidence,
                owner_attested_date=attested_date,
            )
        if item.duplicate_artifact:
            # The bytes are already known but the extractor produced a new
            # candidate set. Preserve it for review; never auto-confirm a new
            # interpretation of previously seen content.
            return _result("NEEDS_REVIEW", "content_seen_new_extraction", len(item.candidate_ids))
        if item.status != "pending-confirmation" or not item.candidate_ids:
            return _result("FAILED", "extraction_failed")

        try:
            with session_scope(engine) as session:
                service = PhotoImportService(session, paths, configured_extractor)
                event, event_candidates = service.get_event(item.ingest_event_id or "")
                selected_ids = set(item.candidate_ids)
                candidates = [
                    candidate for candidate in event_candidates if candidate.id in selected_ids
                ]
                reason = _auto_confirm_block_reason(service, event, candidates, selected_ids)
                if reason is not None:
                    return _result("NEEDS_REVIEW", reason, len(candidates))
                confirmed = service.confirm(item.candidate_ids, actor="owner")
                confirmation_result = _result(
                    "IMPORTED", "auto_confirmed", len(candidates), len(confirmed)
                )
        except PhotoImportError as exc:
            if exc.code == "persistence_error":
                return _result("FAILED", "confirmation_failed", len(item.candidate_ids))
            return _result("NEEDS_REVIEW", "confirmation_rejected", len(item.candidate_ids))
        return confirmation_result
    except OwnerRefreshRuntimeError:
        return _result("FAILED", "runtime_unavailable")
    except (OSError, PhotoImportError, SQLAlchemyError, ValueError, TypeError):
        return _result("FAILED", "import_failed")
    except Exception:
        # Provider and adapter exception text can contain private request
        # details. Return a fixed structural error and never echo it.
        return _result("FAILED", "import_failed")
    finally:
        if engine is not None:
            engine.dispose()


def _owner_extractor(settings: Settings) -> ImageMeasurementExtractor:
    owner_settings = settings.model_copy(
        update={
            "photo_vision_provider_code": XIAOMI_HOME_PROVIDER,
            "photo_vision_physical_device_code": XIAOMI_S400_DEVICE,
            "photo_vision_source_application": "Xiaomi Home",
        }
    )
    return build_photo_extractor(owner_settings)


def _read_extraction_json(
    extraction_json_path: str | Path,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        path = Path(extraction_json_path)
        if not path.is_file():
            return None, "extraction_json_unreadable"
        with path.open("rb") as stream:
            raw = stream.read(MAX_EXTRACTION_JSON_BYTES + 1)
    except (OSError, TypeError, ValueError):
        return None, "extraction_json_unreadable"
    if len(raw) > MAX_EXTRACTION_JSON_BYTES:
        return None, "extraction_json_too_large"
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "extraction_json_invalid"
    if not isinstance(payload, dict):
        return None, "extraction_json_invalid"
    return payload, None


def _owner_profile_conflicts(result: ExtractionResult) -> bool:
    return (
        result.provider_code != XIAOMI_HOME_PROVIDER
        or result.physical_device_code != XIAOMI_S400_DEVICE
        or result.source_application != "Xiaomi Home"
    )


def _attested_date_only_evidence(
    extracted: ExtractionResult,
    prepared: tuple[tuple[str, NormalizedField], ...],
) -> bool:
    """Return whether sidecar evidence is date-only for an attested request."""

    if extracted.source_timezone is not None or extracted.source_utc_offset_minutes is not None:
        return False
    for _, normalized in prepared:
        if (
            normalized.source_timestamp is not None
            or normalized.source_timezone is not None
            or normalized.source_utc_offset_minutes is not None
            or normalized.temporal_precision not in (None, "date")
        ):
            return False
    return True


def _parsed_owner_attested_date(value: str | Path | date | None) -> date | None:
    """Parse an explicit current-request Owner-attested date without inference."""

    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return None
    if isinstance(value, Path):
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if len(text) != 10 or text[4] != "-" or text[7] != "-":
            return None
        return date.fromisoformat(text)
    except ValueError:
        return None


def _read_image(image_path: str | Path) -> bytes | None:
    try:
        path = Path(image_path)
        if not path.is_file():
            return None
        with path.open("rb") as stream:
            return stream.read(MAX_PHOTO_BYTES + 1)
    except (OSError, TypeError, ValueError):
        return None


def _duplicate_result(
    engine: Engine,
    paths: RuntimePaths,
    extractor: ImageMeasurementExtractor,
    item: Any,
    *,
    expected_extraction: ExtractionResult | None = None,
    expected_evidence: tuple[tuple[str, NormalizedField], ...] | None = None,
    owner_attested_date: date | None = None,
) -> OwnerWeightScreenshotImportResult:
    if not item.candidate_ids:
        return _result("NEEDS_REVIEW", "duplicate_candidates_missing")
    with session_scope(engine) as session:
        service = PhotoImportService(session, paths, extractor)
        _batch, _events, candidates = service.get_batch(item.ingest_batch_id or "")
        by_id = {candidate.id: candidate for candidate in candidates}
        selected = [
            by_id[candidate_id]
            for candidate_id in item.candidate_ids
            if candidate_id in by_id
        ]
        if len(selected) != len(item.candidate_ids):
            return _result("NEEDS_REVIEW", "duplicate_candidates_missing", len(selected))
        if expected_extraction is not None and expected_evidence is not None:
            if not _same_extraction_evidence(
                selected,
                expected_extraction,
                expected_evidence,
                owner_attested_date=owner_attested_date,
            ):
                return _staged_correction_result(
                    service,
                    selected,
                    expected_extraction,
                    expected_evidence,
                    owner_attested_date=owner_attested_date,
                )
        views = [service.candidate_view(candidate) for candidate in selected]
        if any(candidate.user_decision == "pending" for candidate in selected):
            return _result("NEEDS_REVIEW", "duplicate_unresolved", len(selected))
        if any(
            candidate.user_decision == "confirmed" and view["scalar_measurement_id"] is None
            for candidate, view in zip(selected, views, strict=True)
        ):
            return _result("NEEDS_REVIEW", "duplicate_unresolved", len(selected))
        return _result("DUPLICATE", "duplicate_content", len(selected))


def _same_extraction_evidence(
    candidates: list[ImportCandidate],
    extracted: ExtractionResult,
    normalized_evidence: tuple[tuple[str, NormalizedField], ...],
    *,
    owner_attested_date: date | None = None,
) -> bool:
    from healthcheck.ingestion.photo.metadata_origins import (
        candidate_set_is_fully_legacy,
    )

    if candidate_set_is_fully_legacy(
        [candidate.metadata_origins_json for candidate in candidates]
    ):
        # D1 legacy wildcard: unchanged core evidence stays DUPLICATE with
        # zero provenance rewrite.
        return candidate_core_evidence_fingerprint(
            candidates
        ) == extraction_core_evidence_fingerprint(
            extracted, normalized_evidence, owner_attested_date=owner_attested_date
        )
    return candidate_evidence_fingerprint(
        candidates
    ) == extraction_evidence_fingerprint(
        extracted,
        normalized_evidence,
        is_owner_workflow=True,
        owner_attested_date=owner_attested_date,
    )


def _staged_correction_result(
    service: PhotoImportService,
    selected: list[ImportCandidate],
    extracted: ExtractionResult,
    normalized_evidence: tuple[tuple[str, NormalizedField], ...],
    *,
    owner_attested_date: date | None = None,
) -> OwnerWeightScreenshotImportResult:
    """Persist and classify a changed interpretation of already-known content.

    The changed sidecar is staged as its own pending candidate set.  It is
    never confirmed here: the Owner must explicitly review it.  An exact
    replay of a staged set resolves to the same set, so no duplicate evidence
    rows are created and a terminal decision stays terminal.
    """

    event_ids = {candidate.ingest_event_id for candidate in selected}
    if len(event_ids) != 1:
        return _result("NEEDS_REVIEW", "candidate_set_incomplete", len(selected))
    try:
        staged = service.stage_correction(
            selected[0].ingest_event_id,
            extracted,
            is_owner_workflow=True,
            owner_attested_date=owner_attested_date,
        )
    except PhotoImportError as exc:
        if exc.code == "persistence_error":
            return _result("FAILED", "correction_failed", len(selected))
        return _result("NEEDS_REVIEW", "content_seen_new_extraction", len(selected))
    correction = staged.candidates
    if not correction:
        return _result("NEEDS_REVIEW", "content_seen_new_extraction", len(selected))
    if candidate_evidence_fingerprint(correction) != extraction_evidence_fingerprint(
        extracted,
        normalized_evidence,
        is_owner_workflow=True,
        owner_attested_date=owner_attested_date,
    ):
        # Never classify or decide on a candidate set that does not carry
        # exactly the incoming sidecar evidence.
        return _result("NEEDS_REVIEW", "content_seen_new_extraction", len(correction))
    views = [service.candidate_view(candidate) for candidate in correction]
    if any(candidate.user_decision == "pending" for candidate in correction):
        return _result("NEEDS_REVIEW", "content_seen_new_extraction", len(correction))
    if any(
        candidate.user_decision == "confirmed" and view["scalar_measurement_id"] is None
        for candidate, view in zip(correction, views, strict=True)
    ):
        return _result("NEEDS_REVIEW", "duplicate_unresolved", len(correction))
    return _result("DUPLICATE", "duplicate_content", len(correction))


def _auto_confirm_block_reason(
    service: PhotoImportService,
    event: Any,
    candidates: list[Any],
    selected_ids: set[str],
) -> str | None:
    if (
        event.raw_artifact_id is None
        or not candidates
        or {item.id for item in candidates} != selected_ids
    ):
        return "candidate_set_incomplete"
    if len({candidate.candidate_set_key for candidate in candidates}) != 1:
        return "ambiguous_candidate_sets"
    if len({candidate.measurement_group_key for candidate in candidates}) != 1:
        return "ambiguous_groups"
    if any(candidate.user_decision != "pending" for candidate in candidates):
        return "candidate_not_pending"

    views = [service.candidate_view(candidate) for candidate in candidates]
    metric_codes = [candidate.metric_code for candidate in candidates]
    if len(set(metric_codes)) != len(metric_codes):
        return "duplicate_metrics"
    if "weight" not in metric_codes:
        return "weight_missing"
    if any(metric not in _XIAOMI_PHOTO_METRICS for metric in metric_codes):
        return "unsupported_metric"

    for candidate, view in zip(candidates, views, strict=True):
        if view["warnings"]:
            return "candidate_warnings"
        if candidate.proposed_value is None or not math.isfinite(candidate.proposed_value):
            return "value_missing_or_invalid"
        if candidate.proposed_unit is None:
            return "unit_missing"
        if candidate.proposed_source_local_date is None:
            return "source_date_missing"
        if candidate.temporal_precision not in {"date", "instant", "minute"}:
            return "temporal_precision_ambiguous"
        if (
            candidate.temporal_precision in {"instant", "minute"}
            and candidate.proposed_source_timestamp is None
        ):
            return "source_timestamp_missing"
        if (
            candidate.temporal_precision == "date"
            and candidate.proposed_source_timestamp is not None
        ):
            return "temporal_precision_ambiguous"
        try:
            from healthcheck.ingestion.photo.normalize import normalize_confirmed_value

            normalize_confirmed_value(
                candidate.metric_code,
                candidate.proposed_value,
                candidate.proposed_unit,
            )
        except (TypeError, ValueError):
            return "unit_unsupported"

        provenance = view["provenance"]
        if (
            provenance["provider_code"] != XIAOMI_HOME_PROVIDER
            or provenance["device_code"] != XIAOMI_S400_DEVICE
            or provenance["input_method"] != "photo_import"
            or provenance["source_application"] != "Xiaomi Home"
        ):
            return "provenance_ambiguous"
        expected_algorithm = (
            WEIGHT_ALGORITHM_CODE
            if candidate.metric_code == "weight"
            else XIAOMI_HOME_COMPOSITION_ALGORITHM
        )
        if candidate.algorithm_code not in {None, expected_algorithm} or provenance[
            "compatibility_group"
        ] not in {None, expected_algorithm}:
            return "algorithm_identity_conflict"
        existing_algorithm = service.repos.measurement_algorithms.get_by_code_version(
            expected_algorithm, candidate.algorithm_version or "unknown"
        )
        if existing_algorithm is not None and (
            existing_algorithm.compatibility_group != expected_algorithm
            or existing_algorithm.producer != "xiaomi"
            or existing_algorithm.metric_family
            != ("weight" if candidate.metric_code == "weight" else "body_composition")
        ):
            return "algorithm_identity_conflict"
    return None


def _result(
    status: str,
    reason_code: str,
    candidate_count: int = 0,
    measurement_count: int = 0,
) -> OwnerWeightScreenshotImportResult:
    return OwnerWeightScreenshotImportResult(
        status=status,
        reason_code=reason_code,
        candidate_count=candidate_count,
        measurement_count=measurement_count,
    )
