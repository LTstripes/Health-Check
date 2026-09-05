"""openScale-sync webhook contract, normalization, and ingest persistence.

Package ``__init__`` intentionally re-exports only the pure contract surface.
HTTP/persistence helpers must be imported from their submodules so
``healthcheck.config`` can safely import ``binding`` without a circular
import through the service layer.
"""

from healthcheck.ingestion.openscale.contract import (
    CONTROL_EVENTS,
    KNOWN_METRICS,
    MEASUREMENT_EVENTS,
    OPENSCALE_CONTRACT_VERSION,
    OPENSCALE_PINNED_REF,
    TOP_LEVEL_EVENTS,
    ContractFailure,
    EnvelopeResult,
    InvalidBatchItem,
    KnownMetricRule,
    NormalizedMeasurement,
    NormalizedMetric,
    ParsedDateTime,
    RawValueItem,
    UnknownItem,
    delete_fallback_identity,
    invalid_item_evidence_key,
    measurement_fingerprint,
    normalize_envelope,
    semantic_fingerprint,
    stable_record_identity,
)

__all__ = [
    "CONTROL_EVENTS",
    "KNOWN_METRICS",
    "MEASUREMENT_EVENTS",
    "OPENSCALE_CONTRACT_VERSION",
    "OPENSCALE_PINNED_REF",
    "TOP_LEVEL_EVENTS",
    "ContractFailure",
    "EnvelopeResult",
    "InvalidBatchItem",
    "KnownMetricRule",
    "NormalizedMeasurement",
    "NormalizedMetric",
    "ParsedDateTime",
    "RawValueItem",
    "UnknownItem",
    "delete_fallback_identity",
    "invalid_item_evidence_key",
    "measurement_fingerprint",
    "normalize_envelope",
    "semantic_fingerprint",
    "stable_record_identity",
]
