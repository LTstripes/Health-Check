"""Per-candidate metadata-origin provenance for Owner-attested imports (#240).

Every post-0015 ``ImportCandidate`` persists one complete canonical four-key map
in ``metadata_origins_json``.  Database NULL is reserved exclusively for
pre-0015 legacy rows and is observed as "origin not recorded"; there is no
backfill, default, or history rewrite.

Keys are sealed to exactly:
``provider_code``, ``physical_device_code``, ``source_application``,
``source_local_date``.

States are sealed to ``visible | owner_attested | workflow_profile | unknown``,
with ``source_local_date`` never ``workflow_profile``.  No clock, EXIF,
filename, memory, prior-chat, or default inference is permitted.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

ORIGIN_VISIBLE = "visible"
ORIGIN_OWNER_ATTESTED = "owner_attested"
ORIGIN_WORKFLOW_PROFILE = "workflow_profile"
ORIGIN_UNKNOWN = "unknown"

METADATA_ORIGIN_KEYS: tuple[str, ...] = (
    "provider_code",
    "physical_device_code",
    "source_application",
    "source_local_date",
)

ALLOWED_ORIGINS: frozenset[str] = frozenset(
    {
        ORIGIN_VISIBLE,
        ORIGIN_OWNER_ATTESTED,
        ORIGIN_WORKFLOW_PROFILE,
        ORIGIN_UNKNOWN,
    }
)

DATE_ALLOWED_ORIGINS: frozenset[str] = frozenset(
    {
        ORIGIN_VISIBLE,
        ORIGIN_OWNER_ATTESTED,
        ORIGIN_UNKNOWN,
    }
)

LEGACY_ORIGIN_DISPLAY = "origin not recorded"


def validate_metadata_origins(value: Mapping[str, Any]) -> dict[str, str]:
    """Validate a complete canonical four-key origin map."""
    if not isinstance(value, Mapping):
        raise ValueError("metadata origins must be an object")
    keys = set(value)
    expected = set(METADATA_ORIGIN_KEYS)
    if keys != expected:
        raise ValueError("metadata origins must contain exactly the four canonical keys")
    result: dict[str, str] = {}
    for key in METADATA_ORIGIN_KEYS:
        origin = value[key]
        if not isinstance(origin, str) or origin not in ALLOWED_ORIGINS:
            raise ValueError(f"metadata origin for {key!r} is not an allowed state")
        if key == "source_local_date" and origin not in DATE_ALLOWED_ORIGINS:
            raise ValueError("source_local_date origin can never be workflow_profile")
        result[key] = origin
    return result


def canonical_metadata_origins_json(value: Mapping[str, Any]) -> str:
    """Serialize a validated origin map in canonical sorted form."""
    validated = validate_metadata_origins(value)
    return json.dumps(validated, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def parse_metadata_origins_json(value: str | None) -> dict[str, str] | None:
    """Parse stored origins; None (legacy) stays None without rewrite."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("metadata origins JSON must be text or NULL")
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("persisted metadata origins are malformed") from exc
    return validate_metadata_origins(decoded)


def is_legacy_origins(value: str | None) -> bool:
    """Return whether a stored column value is the legacy NULL state."""
    return value is None


def candidate_set_is_fully_legacy(origins_values: Sequence[str | None]) -> bool:
    """Return whether every candidate in a set is legacy NULL (D1 wildcard)."""
    if not origins_values:
        return False
    return all(value is None for value in origins_values)


def build_owner_metadata_origins(
    *,
    provider_code: str | None,
    physical_device_code: str | None,
    source_application: str | None,
    normalized_local_date: date | None,
    attested_local_date: date | None,
    provider_code_from_payload: bool | None = None,
    physical_device_code_from_payload: bool | None = None,
    source_application_from_payload: bool | None = None,
) -> dict[str, str]:
    """Build origins for the fixed authorized Owner screenshot workflow.

    An explicit non-null fixed triple in the sidecar payload is ``visible``.
    Only an omitted/null fixed triple filled by the authorized workflow is
    ``workflow_profile``.  Foreign explicit values are ``visible``.  Missing
    values are ``unknown``.  The date is never ``workflow_profile``.
    """

    # Import here to avoid a hard import cycle at module load for tooling.
    from healthcheck.ingestion.photo.provenance import (
        XIAOMI_HOME_PROVIDER,
        XIAOMI_S400_DEVICE,
    )

    provider_origin = _owner_triple_origin(
        value=provider_code,
        expected=XIAOMI_HOME_PROVIDER,
        from_payload=provider_code_from_payload,
    )
    device_origin = _owner_triple_origin(
        value=physical_device_code,
        expected=XIAOMI_S400_DEVICE,
        from_payload=physical_device_code_from_payload,
    )
    app_origin = _owner_triple_origin(
        value=source_application,
        expected="Xiaomi Home",
        from_payload=source_application_from_payload,
    )

    if attested_local_date is not None:
        date_origin = ORIGIN_OWNER_ATTESTED
    elif normalized_local_date is not None:
        date_origin = ORIGIN_VISIBLE
    else:
        date_origin = ORIGIN_UNKNOWN

    return validate_metadata_origins(
        {
            "provider_code": provider_origin,
            "physical_device_code": device_origin,
            "source_application": app_origin,
            "source_local_date": date_origin,
        }
    )


def _owner_triple_origin(
    *, value: str | None, expected: str, from_payload: bool | None
) -> str:
    if from_payload is True:
        return ORIGIN_VISIBLE if value else ORIGIN_UNKNOWN
    if from_payload is False:
        if value and value == expected:
            return ORIGIN_WORKFLOW_PROFILE
        return ORIGIN_VISIBLE if value else ORIGIN_UNKNOWN
    # Untracked extractor (backward compat): value-based fallback.
    if value and value == expected:
        return ORIGIN_WORKFLOW_PROFILE
    return ORIGIN_VISIBLE if value else ORIGIN_UNKNOWN


def build_provider_metadata_origins(
    *,
    provider_code: str | None,
    physical_device_code: str | None,
    source_application: str | None,
    normalized_local_date: date | None,
    provider_code_from_payload: bool | None = None,
    physical_device_code_from_payload: bool | None = None,
    source_application_from_payload: bool | None = None,
) -> dict[str, str]:
    """Build origins for generic provider vision routes.

    Provider routes never accept Owner attestation and never emit
    workflow_profile.  Payload facts are ``visible``; request/config
    fallbacks are ``unknown``.
    """

    def _provider_origin(value: str | None, from_payload: bool | None) -> str:
        if from_payload is True:
            return ORIGIN_VISIBLE if value else ORIGIN_UNKNOWN
        if from_payload is False:
            return ORIGIN_UNKNOWN
        return ORIGIN_VISIBLE if value else ORIGIN_UNKNOWN

    return validate_metadata_origins(
        {
            "provider_code": _provider_origin(provider_code, provider_code_from_payload),
            "physical_device_code": _provider_origin(
                physical_device_code, physical_device_code_from_payload
            ),
            "source_application": _provider_origin(
                source_application, source_application_from_payload
            ),
            "source_local_date": (
                ORIGIN_VISIBLE if normalized_local_date is not None else ORIGIN_UNKNOWN
            ),
        }
    )


__all__ = [
    "ALLOWED_ORIGINS",
    "DATE_ALLOWED_ORIGINS",
    "LEGACY_ORIGIN_DISPLAY",
    "METADATA_ORIGIN_KEYS",
    "ORIGIN_OWNER_ATTESTED",
    "ORIGIN_UNKNOWN",
    "ORIGIN_VISIBLE",
    "ORIGIN_WORKFLOW_PROFILE",
    "build_owner_metadata_origins",
    "build_provider_metadata_origins",
    "candidate_set_is_fully_legacy",
    "canonical_metadata_origins_json",
    "is_legacy_origins",
    "parse_metadata_origins_json",
    "validate_metadata_origins",
]
