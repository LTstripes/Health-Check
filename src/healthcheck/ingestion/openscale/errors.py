"""Typed openScale webhook failures with sanitized, value-free messages."""

from __future__ import annotations


class OpenScaleIngestError(Exception):
    """Application-level ingest failure that is safe to return to the client."""

    def __init__(self, code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


__all__ = ["OpenScaleIngestError"]
