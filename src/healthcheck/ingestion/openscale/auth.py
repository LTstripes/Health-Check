"""Bearer credential validation for the ingest-only openScale listener."""

from __future__ import annotations

import hmac
import secrets

from healthcheck.ingestion.openscale.errors import OpenScaleIngestError


def extract_bearer_token(authorization_header: str | None) -> str:
    """Return the bearer credential or raise a sanitized auth failure."""

    if authorization_header is None or not authorization_header.strip():
        raise OpenScaleIngestError("unauthorized", "missing authorization", status_code=401)
    scheme, _, remainder = authorization_header.strip().partition(" ")
    if scheme.lower() != "bearer" or not remainder.strip():
        raise OpenScaleIngestError("unauthorized", "invalid authorization", status_code=401)
    return remainder.strip()


def require_matching_bearer(authorization_header: str | None, configured_token: str | None) -> None:
    """Validate Authorization against the configured rotatable ingest secret.

    The configured token is independent of ``source_instance_id``.  Comparison
    is constant-time and failures never include the credential in the message.
    """

    if configured_token is None or not configured_token.strip():
        raise OpenScaleIngestError(
            "ingest_not_configured",
            "openScale ingest credential is not configured",
            status_code=503,
        )
    presented = extract_bearer_token(authorization_header)
    expected = configured_token.strip()
    presented_bytes = presented.encode("utf-8")
    expected_bytes = expected.encode("utf-8")
    # Hash both sides so unequal lengths remain constant-time comparable.
    presented_digest = hmac.new(b"healthcheck-ingest", presented_bytes, "sha256").digest()
    expected_digest = hmac.new(b"healthcheck-ingest", expected_bytes, "sha256").digest()
    if not hmac.compare_digest(presented_digest, expected_digest):
        secrets.compare_digest(presented_digest, presented_digest)
        raise OpenScaleIngestError("unauthorized", "invalid authorization", status_code=401)


__all__ = ["extract_bearer_token", "require_matching_bearer"]
