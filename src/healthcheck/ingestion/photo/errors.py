"""Typed photo-import failures that can be mapped to HTTP responses."""

from __future__ import annotations


class PhotoImportError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(code)
