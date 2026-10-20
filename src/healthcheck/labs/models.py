"""Typed lab entities registered with the shared persistence metadata."""

from healthcheck.db.models import (
    LabHead,
    LabInterpretation,
    LabOperation,
    LabReport,
    LabResult,
    LabRevision,
)

__all__ = ["LabHead", "LabInterpretation", "LabOperation", "LabReport", "LabResult", "LabRevision"]
