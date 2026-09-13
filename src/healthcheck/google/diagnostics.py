"""Read-only, privacy-safe diagnostics for persisted Google Health evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    GooglePayloadObservation,
    GooglePayloadStatus,
    GoogleRawPayload,
    RawArtifact,
)
from healthcheck.google.contracts import GoogleQueryMode, GoogleStream
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from healthcheck.google.sync import classify_page_envelope_structure

GOOGLE_TERMINAL_DIAGNOSTIC_CONTRACT_VERSION = "r04-google-terminal-envelope-diagnostic-v1"

_PRIVACY = {
    "raw_values_emitted": False,
    "private_identifiers_emitted": False,
    "tokens_emitted": False,
    "health_timestamps_emitted": False,
    "page_tokens_emitted": False,
    "string_encoded_numerics_logged_as_values": False,
}


@dataclass(frozen=True, slots=True)
class GoogleTerminalEnvelopeDiagnosis:
    """Allowlisted diagnosis with no payload, identifier, or timestamp fields."""

    status: str
    stream: str
    query_mode: str | None
    stage: str
    diagnostic_code: str
    envelope_field: str | None
    collection_presence: str
    collection_type: str
    next_page_token_type: str
    top_level_type: str

    def as_dict(self) -> dict[str, object]:
        return {
            "contract_version": GOOGLE_TERMINAL_DIAGNOSTIC_CONTRACT_VERSION,
            "status": self.status,
            "stream": self.stream,
            "query_mode": self.query_mode,
            "diagnosis": {
                "stage": self.stage,
                "diagnostic_code": self.diagnostic_code,
                "envelope_field": self.envelope_field,
                "collection_presence": self.collection_presence,
                "collection_type": self.collection_type,
                "next_page_token_type": self.next_page_token_type,
                "top_level_type": self.top_level_type,
            },
            "privacy": dict(_PRIVACY),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def diagnose_latest_invalid_google_envelope(
    session: Session,
    *,
    payload_store: ContentAddressedGooglePayloadStore,
    stream: str | GoogleStream = GoogleStream.HEART_RATE,
) -> GoogleTerminalEnvelopeDiagnosis:
    """Inspect the newest persisted invalid observation without provider access."""

    stream_code = GoogleStream(stream).value
    observation = session.scalar(
        select(GooglePayloadObservation)
        .where(
            GooglePayloadObservation.stream_code == stream_code,
            GooglePayloadObservation.parse_status == GooglePayloadStatus.INVALID.value,
        )
        .order_by(GooglePayloadObservation.received_at.desc(), GooglePayloadObservation.id.desc())
        .limit(1)
    )
    if observation is None:
        return _unavailable(stream_code, "no_persisted_invalid_evidence")

    raw = session.get(GoogleRawPayload, observation.google_raw_payload_id)
    artifact = session.get(RawArtifact, raw.raw_artifact_id) if raw is not None else None
    if raw is None or artifact is None:
        return _unavailable(stream_code, "persisted_evidence_unavailable", observation.query_mode)

    try:
        content = payload_store.read(artifact.relative_storage_path)
        content_hash = hashlib.sha256(content).hexdigest()
    except (OSError, ValueError):
        return _unavailable(stream_code, "persisted_evidence_unavailable", observation.query_mode)
    if content_hash != raw.content_hash or content_hash != artifact.content_hash:
        return _unavailable(
            stream_code, "persisted_evidence_integrity_failure", observation.query_mode
        )

    try:
        decoded = json.loads(content)
    except (TypeError, UnicodeError, ValueError):
        return GoogleTerminalEnvelopeDiagnosis(
            status="diagnosed",
            stream=stream_code,
            query_mode=observation.query_mode,
            stage="response",
            diagnostic_code="persisted_terminal_non_json",
            envelope_field=None,
            collection_presence="not_applicable",
            collection_type="not_applicable",
            next_page_token_type="not_applicable",
            top_level_type="non_json",
        )

    top_level_type = _json_shape_type(decoded)
    if not isinstance(decoded, Mapping):
        return GoogleTerminalEnvelopeDiagnosis(
            status="diagnosed",
            stream=stream_code,
            query_mode=observation.query_mode,
            stage="response",
            diagnostic_code="persisted_terminal_top_level_type",
            envelope_field=None,
            collection_presence="not_applicable",
            collection_type="not_applicable",
            next_page_token_type="not_applicable",
            top_level_type=top_level_type,
        )

    try:
        structure = classify_page_envelope_structure(
            decoded, GoogleQueryMode(observation.query_mode)
        )
    except ValueError:
        return _unavailable(stream_code, "persisted_evidence_query_context_invalid", None)

    if structure.parser_kind == "invalid":
        diagnostic_code = {
            "absent": "shape_drift_page_envelope_collection_missing",
            "null": "shape_drift_page_envelope_collection_null",
        }.get(structure.collection_type, "shape_drift_page_envelope_collection_type")
        stage = "page_envelope"
    else:
        diagnostic_code = "persisted_invalid_not_page_envelope"
        stage = "not_page_envelope"
    return GoogleTerminalEnvelopeDiagnosis(
        status="diagnosed",
        stream=stream_code,
        query_mode=observation.query_mode,
        stage=stage,
        diagnostic_code=diagnostic_code,
        envelope_field=structure.envelope_field,
        collection_presence=structure.collection_presence,
        collection_type=structure.collection_type,
        next_page_token_type=structure.next_page_token_type,
        top_level_type=top_level_type,
    )


def _unavailable(
    stream: str,
    diagnostic_code: str,
    query_mode: str | None = None,
) -> GoogleTerminalEnvelopeDiagnosis:
    return GoogleTerminalEnvelopeDiagnosis(
        status="unavailable",
        stream=stream,
        query_mode=query_mode,
        stage="unavailable",
        diagnostic_code=diagnostic_code,
        envelope_field=None,
        collection_presence="unknown",
        collection_type="unknown",
        next_page_token_type="unknown",
        top_level_type="unknown",
    )


def _json_shape_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    return "other"


__all__ = [
    "GOOGLE_TERMINAL_DIAGNOSTIC_CONTRACT_VERSION",
    "GoogleTerminalEnvelopeDiagnosis",
    "diagnose_latest_invalid_google_envelope",
]
