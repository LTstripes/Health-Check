"""Byte-exact, verified storage for immutable Google normalization projections."""

from __future__ import annotations

import hashlib
import zlib
from collections.abc import Mapping

CODEC = "zlib-1"
ERROR = "Google projection verification failed"


def _field(row, name):
    return row.get(name) if isinstance(row, Mapping) else getattr(row, name, None)


def read_projection(row) -> str:
    """The sole body accessor, including legacy text during migration/dry runs.

    A compressed body never falls back to text on a failed verification. Trailing
    bytes, truncated streams and inconsistent dual representations also fail.
    All integrity failures expose the same content-free error.
    """
    try:
        body = _field(row, "projection_blob")
        legacy = _field(row, "projection_json")
        fingerprint = _field(row, "projection_fingerprint")
        metadata = tuple(_field(row, name) for name in (
            "projection_codec", "projection_size", "projection_sha256",
        ))
        if body is None:
            if any(value is not None for value in metadata) or not isinstance(legacy, str):
                raise ValueError
            raw = legacy.encode("utf-8")
        else:
            codec, size, sha = metadata
            if (codec != CODEC or type(size) is not int or size < 0
                    or not isinstance(body, bytes) or sha != fingerprint):
                raise ValueError
            inflater = zlib.decompressobj()
            raw = inflater.decompress(body, size + 1)
            if (len(raw) != size or not inflater.eof or inflater.unused_data
                    or inflater.unconsumed_tail):
                raise ValueError
            if legacy is not None and raw != legacy.encode("utf-8"):
                raise ValueError
        if hashlib.sha256(raw).hexdigest() != fingerprint:
            raise ValueError
        return raw.decode("utf-8")
    except (ValueError, TypeError, AttributeError, OverflowError, zlib.error):
        raise ValueError(ERROR) from None


def compress_projection(projection: str, fingerprint: str) -> dict[str, object]:
    """Encode once, then verify through the same reader before persistence."""
    try:
        raw = projection.encode("utf-8")
        fields = {
            "projection_blob": zlib.compress(raw, level=1),
            "projection_codec": CODEC,
            "projection_size": len(raw),
            "projection_sha256": hashlib.sha256(raw).hexdigest(),
        }
        if read_projection(dict(fields, projection_fingerprint=fingerprint)) != projection:
            raise ValueError
        return fields
    except (ValueError, TypeError, AttributeError):
        raise ValueError(ERROR) from None
