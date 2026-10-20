"""Strict bounded transcription contract. Raw strings are never inferred or converted."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

MAX_PDF = 10 * 1024 * 1024
MAX_DRAFT = 256 * 1024
Text = Annotated[str, Field(max_length=2000, pattern=r"^[^\x00]*$")]
Short = Annotated[str, Field(max_length=255, pattern=r"^[^\x00]*$")]
Key = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._:-]+$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
DecimalText = Annotated[str, Field(max_length=100, pattern=r"^[+-]?[0-9]+(?:\.[0-9]+)?$")]


class LabError(ValueError):
    """Safe reason code suitable for the local UI."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ReportDate(Strict):
    value: Annotated[str, Field(max_length=40)]
    precision: Literal["date", "minute", "second"]

    @model_validator(mode="after")
    def valid(self):
        try:
            if self.precision == "date":
                if date.fromisoformat(self.value).isoformat() != self.value:
                    raise ValueError
            else:
                # Preserve printed local clock/offset verbatim, without inventing a zone.
                import re

                clock = r"[0-9]{2}:[0-9]{2}" + (r":[0-9]{2}" if self.precision == "second" else "")
                if not re.fullmatch(
                    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T" + clock + r"(?:Z|[+-][0-9]{2}:[0-9]{2})?",
                    self.value,
                ):
                    raise ValueError
                datetime.fromisoformat(self.value)
        except ValueError as exc:
            raise ValueError("invalid explicit date precision") from exc
        return self


class Provenance(Strict):
    transcription: Literal["manual", "assistant"]
    page: Annotated[int, Field(ge=1, le=1000)] | None
    support: Text | None


RowField = Literal[
    "label_raw",
    "result_raw",
    "unit_raw",
    "reference_raw",
    "flag_raw",
    "value_kind",
    "decimal",
    "comparator",
    "qualitative",
    "method_raw",
    "equipment_kit_notes",
    "specimen_raw",
    "specimen_date",
    "uncertainty",
]
ReportField = Literal[
    "patient_link",
    "report_link",
    "source_match",
    "clinic_source",
    "performing_lab",
    "report_label",
    "result_date",
    "printed_date",
    "specimen_date",
    "incomplete",
    "uncertainty",
]


class LabRow(Strict):
    row_id: Key
    label_raw: Annotated[str, Field(min_length=1, max_length=255, pattern=r"^[^\x00]*$")]
    result_raw: Annotated[str, Field(min_length=1, max_length=2000, pattern=r"^[^\x00]*$")]
    unit_raw: Short | None
    reference_raw: Text | None
    flag_raw: Short | None
    value_kind: Literal["numeric", "qualitative", "unparsed"]
    decimal: DecimalText | None
    comparator: Literal["=", "<", ">", "<=", ">=", "≤", "≥"] | None
    qualitative: Text | None
    method_raw: Short | None
    equipment_kit_notes: Text | None
    specimen_raw: Short | None
    specimen_date: ReportDate | None
    provenance: Provenance
    field_provenance: Annotated[dict[RowField, Provenance], Field(max_length=14)] = Field(
        default_factory=dict
    )
    uncertainty: Text | None

    @model_validator(mode="after")
    def typed_value(self):
        if self.value_kind == "numeric":
            if self.decimal is None or self.qualitative is not None:
                raise ValueError("numeric requires exact decimal and no qualitative value")
        elif self.decimal is not None or self.comparator is not None:
            raise ValueError("non-numeric must not carry decimal/comparator")
        if self.value_kind == "qualitative" and not self.qualitative:
            raise ValueError("qualitative value required")
        if self.value_kind == "unparsed" and self.qualitative is not None:
            raise ValueError("unparsed has raw result only")
        return self


class Draft(Strict):
    schema_version: Literal["lab-draft-v1"]
    pdf_sha256: Digest
    scope: Literal["single_report_single_patient"]
    patient_link: Literal["unresolved", "resolved"]
    report_link: Literal["unresolved", "resolved"]
    source_match: Literal["unverified", "owner_verified"]
    clinic_source: Short | None
    performing_lab: Short | None
    report_label: Short | None
    result_date: ReportDate | None
    printed_date: ReportDate | None
    specimen_date: ReportDate | None
    provenance: Provenance
    field_provenance: Annotated[dict[ReportField, Provenance], Field(max_length=11)] = Field(
        default_factory=dict
    )
    incomplete: bool
    uncertainty: Text | None
    rows: Annotated[list[LabRow], Field(min_length=1, max_length=200)]

    @model_validator(mode="after")
    def unique_rows(self):
        if len({r.row_id for r in self.rows}) != len(self.rows):
            raise ValueError("duplicate row ids")
        return self


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def encode(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LabError("duplicate_json_key")
        result[key] = value
    return result


def parse_draft(content: bytes) -> Draft:
    if not isinstance(content, bytes) or not 1 <= len(content) <= MAX_DRAFT:
        raise LabError("draft_size")
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=_object)
        return Draft.model_validate(value)
    except (UnicodeError, ValueError, RecursionError, ValidationError) as exc:
        raise LabError("invalid_draft") from exc


def check_pdf(content: bytes) -> None:
    # Opaque local attachment: no rendering, JS, URLs, OCR or document execution.
    # Signature/envelope check only; it is not proof all PDF content is valid.
    if not isinstance(content, bytes) or not 12 <= len(content) <= MAX_PDF:
        raise LabError("pdf_size")
    if not content.startswith((b"%PDF-1.", b"%PDF-2.0")) or not content.rstrip().endswith(b"%%EOF"):
        raise LabError("invalid_pdf_envelope")
