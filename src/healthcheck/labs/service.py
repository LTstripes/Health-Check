"""One transaction boundary for local lab staging and terminal decisions."""

from __future__ import annotations

import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine, select, text, update

from healthcheck.db.engine import session_scope
from healthcheck.db.models import RawArtifact
from healthcheck.labs.models import (
    LabHead,
    LabInterpretation,
    LabOperation,
    LabReport,
    LabResult,
    LabRevision,
)
from healthcheck.labs.schema import (
    MAX_DRAFT,
    MAX_PDF,
    LabError,
    check_pdf,
    encode,
    parse_draft,
    sha,
)
from healthcheck.logging import log_event


class LabConflict(LabError):
    """A stale head, terminal interpretation or reused operation conflicts."""


def _id() -> str:
    return str(uuid4())


def _safe(root: Path, relative: str) -> Path:
    if not re.fullmatch(r"labs/[a-f0-9]{2}/[a-f0-9]{64}\.(pdf|json)", relative):
        raise LabError("artifact_path")
    target = root / "artifacts" / relative
    # Reject symlinks, Windows junctions/reparse points, including profile root.
    for path in (root, root / "artifacts", *target.relative_to(root).parents):
        candidate = path if path.is_absolute() else root / path
        if candidate.exists() or candidate.is_symlink():
            info = candidate.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise LabError("artifact_path")
    if target.exists():
        info = target.lstat()
        if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise LabError("artifact_path")
    return target


def artifact_bytes(root: Path, artifact: RawArtifact, *, extension: str) -> bytes:
    bound = MAX_PDF if extension == "pdf" else MAX_DRAFT
    expected = f"labs/{artifact.content_hash[:2]}/{artifact.content_hash}.{extension}"
    if artifact.relative_storage_path != expected or not 1 <= artifact.byte_size <= bound:
        raise LabError("artifact_metadata")
    try:
        target = _safe(root, expected)
        with target.open("rb") as handle:
            content = handle.read(bound + 1)
        if len(content) != artifact.byte_size or sha(content) != artifact.content_hash:
            raise LabError("artifact_corrupt")
        return content
    except OSError as exc:
        raise LabError("artifact_unavailable") from exc


def _store(session, root: Path, content: bytes, extension: str) -> RawArtifact:
    digest = sha(content)
    artifact = session.scalar(select(RawArtifact).where(RawArtifact.content_hash == digest))
    if artifact is not None:
        if artifact_bytes(root, artifact, extension=extension) != content:
            raise LabError("artifact_corrupt")
        return artifact
    relative = f"labs/{digest[:2]}/{digest}.{extension}"
    path = _safe(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    _safe(root, relative)
    if path.exists():
        with path.open("rb") as handle:
            if handle.read(len(content) + 1) != content:
                raise LabError("artifact_corrupt")
    else:
        temporary = path.with_name(f".{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    artifact = RawArtifact(
        id=_id(),
        content_hash=digest,
        kind="lab_original" if extension == "pdf" else "lab_draft",
        media_type="application/pdf" if extension == "pdf" else "application/json",
        byte_size=len(content),
        relative_storage_path=relative,
        source_filename=None,
    )
    session.add(artifact)
    session.flush()
    return artifact


def _fingerprint(value) -> str:
    return sha(encode(value).encode("utf-8"))


def _replay(session, operation_id, payload):
    if not isinstance(operation_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}", operation_id
    ):
        raise LabError("invalid_operation")
    prior = session.get(LabOperation, operation_id)
    fingerprint = _fingerprint(payload)
    if prior:
        if prior.fingerprint != fingerprint:
            raise LabConflict("operation_payload_changed")
        return json.loads(prior.receipt_json)
    return None


def _receipt(session, operation_id, payload, receipt):
    session.add(
        LabOperation(
            operation_id=operation_id,
            fingerprint=_fingerprint(payload),
            receipt_json=encode(receipt),
            created_at=datetime.now(UTC),
        )
    )
    session.flush()
    return receipt


def _interpretation(session, root, interpretation_id):
    interpretation = session.get(LabInterpretation, interpretation_id)
    if interpretation is None:
        raise LabError("interpretation_not_found")
    report = session.get(LabReport, interpretation.report_id)
    pdf = session.get(RawArtifact, report.pdf_artifact_id)
    check_pdf(artifact_bytes(root, pdf, extension="pdf"))
    artifact = session.get(RawArtifact, interpretation.draft_artifact_id)
    raw = artifact_bytes(root, artifact, extension="json")
    draft = parse_draft(raw)
    if draft.pdf_sha256 != pdf.content_hash:
        raise LabError("pdf_draft_mismatch")
    return interpretation, draft, raw


def snapshot_diff(previous: dict | None, snapshot: dict) -> dict[str, list[str]]:
    old = {r["row_id"]: r for r in (previous or {}).get("rows", [])}
    new = {r["row_id"]: r for r in snapshot["rows"]}
    return {
        "retained": sorted(k for k in old.keys() & new.keys() if old[k] == new[k]),
        "changed": sorted(k for k in old.keys() & new.keys() if old[k] != new[k]),
        "removed": sorted(old.keys() - new.keys()),
        "added": sorted(new.keys() - old.keys()),
    }


class LabService:
    def __init__(self, engine: Engine, root: Path):
        self.engine, self.root = engine, Path(root)

    def stage(self, pdf: bytes, draft_bytes: bytes, operation_id: str, *, parent_id=None):
        check_pdf(pdf)
        draft = parse_draft(draft_bytes)
        if draft.pdf_sha256 != sha(pdf):
            raise LabError("pdf_draft_mismatch")
        payload = ["stage", sha(pdf), sha(draft_bytes), parent_id]
        with session_scope(self.engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            prior = _replay(session, operation_id, payload)
            if prior:
                return prior
            original = _store(session, self.root, pdf, "pdf")
            artifact = _store(session, self.root, draft_bytes, "json")
            report = session.scalar(
                select(LabReport).where(LabReport.pdf_artifact_id == original.id)
            )
            if report is None:
                report = LabReport(id=_id(), pdf_artifact_id=original.id)
                session.add(report)
                session.flush()
                session.add(LabHead(report_id=report.id, revision_id=None))
                session.flush()
            if parent_id:
                parent, _, _ = _interpretation(session, self.root, parent_id)
                if parent.report_id != report.id:
                    raise LabError("parent_report_mismatch")
            interpretation = session.scalar(
                select(LabInterpretation).where(
                    LabInterpretation.report_id == report.id,
                    LabInterpretation.draft_artifact_id == artifact.id,
                )
            )
            if interpretation is None:
                interpretation = LabInterpretation(
                    id=_id(),
                    report_id=report.id,
                    draft_artifact_id=artifact.id,
                    parent_id=parent_id,
                )
                session.add(interpretation)
                session.flush()
            receipt = _receipt(
                session,
                operation_id,
                payload,
                {
                    "kind": "staged",
                    "report_id": report.id,
                    "interpretation_id": interpretation.id,
                    "pdf_sha256": sha(pdf),
                    "draft_sha256": sha(draft_bytes),
                },
            )
        log_event("lab_intake", operation="stage", status="ok")
        return receipt

    def review(self, interpretation_id):
        with session_scope(self.engine) as session:
            session.execute(text("BEGIN"))
            interpretation, draft, raw = _interpretation(session, self.root, interpretation_id)
            head = session.get(LabHead, interpretation.report_id)
            revision = session.get(LabRevision, head.revision_id) if head.revision_id else None
            consumed = session.scalar(
                select(LabRevision.id).where(LabRevision.interpretation_id == interpretation_id)
            )
            previous = json.loads(revision.snapshot_json) if revision else None
            return {
                "report_id": interpretation.report_id,
                "interpretation_id": interpretation.id,
                "draft": draft.model_dump(),
                "draft_text": raw.decode("utf-8"),
                "expected_head": head.revision_id,
                "consumed": consumed,
                "previous": previous,
                "diff": snapshot_diff(previous, draft.model_dump()),
            }

    def original(self, report_id):
        with session_scope(self.engine) as session:
            session.execute(text("BEGIN"))
            report = session.get(LabReport, report_id)
            if not report:
                raise LabError("report_not_found")
            return artifact_bytes(
                self.root, session.get(RawArtifact, report.pdf_artifact_id), extension="pdf"
            )

    def decide(
        self,
        interpretation_id: str,
        selected: list[str],
        *,
        expected_head: str | None,
        partial: bool,
        operation_id: str,
        kind: str,
    ):
        if (
            kind not in {"confirm", "revise"}
            or type(partial) is not bool
            or not isinstance(selected, list)
            or (expected_head is not None and not isinstance(expected_head, str))
        ):
            raise LabError("invalid_decision")
        if (
            not selected
            or len(selected) > 200
            or any(not isinstance(k, str) for k in selected)
            or len(set(selected)) != len(selected)
        ):
            raise LabError("invalid_subset")
        payload = [kind, interpretation_id, sorted(selected), expected_head, partial]
        with session_scope(self.engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            prior = _replay(session, operation_id, payload)
            if prior:
                return prior
            interpretation, draft, _ = _interpretation(session, self.root, interpretation_id)
            head = session.get(LabHead, interpretation.report_id)
            if head.revision_id != expected_head:
                raise LabConflict("stale_head")
            if (
                kind == "confirm"
                and expected_head is not None
                or kind == "revise"
                and expected_head is None
            ):
                raise LabConflict("use_revise_for_existing_report")
            if session.scalar(
                select(LabRevision.id).where(LabRevision.interpretation_id == interpretation_id)
            ):
                raise LabConflict("interpretation_terminal")
            if draft.patient_link != "resolved" or draft.report_link != "resolved":
                raise LabError("unresolved_patient_or_report")
            keys = {r.row_id for r in draft.rows}
            if not set(selected) <= keys:
                raise LabError("unknown_rows")
            if kind == "revise" and set(selected) != keys:
                raise LabError("revise_requires_full_snapshot")
            if (draft.incomplete or set(selected) != keys) and not partial:
                raise LabError("partial_required")
            snapshot = draft.model_dump()
            snapshot["rows"] = [r for r in snapshot["rows"] if r["row_id"] in selected]
            previous = session.get(LabRevision, expected_head) if expected_head else None
            diff = snapshot_diff(json.loads(previous.snapshot_json) if previous else None, snapshot)
            revision = LabRevision(
                id=_id(),
                report_id=interpretation.report_id,
                interpretation_id=interpretation_id,
                previous_id=expected_head,
                partial=partial,
                snapshot_json=encode(snapshot),
            )
            session.add(revision)
            session.flush()
            for row in snapshot["rows"]:
                typed = {
                    k: row[k]
                    for k in (
                        "row_id",
                        "label_raw",
                        "result_raw",
                        "unit_raw",
                        "reference_raw",
                        "value_kind",
                        "decimal",
                        "comparator",
                        "qualitative",
                    )
                }
                session.add(LabResult(revision_id=revision.id, **typed, detail_json=encode(row)))
            result = session.execute(
                update(LabHead)
                .where(
                    LabHead.report_id == interpretation.report_id,
                    LabHead.revision_id == expected_head,
                )
                .values(revision_id=revision.id)
            )
            if result.rowcount != 1:
                raise LabConflict("stale_head")
            receipt = _receipt(
                session,
                operation_id,
                payload,
                {
                    "kind": kind,
                    "report_id": interpretation.report_id,
                    "interpretation_id": interpretation_id,
                    "revision_id": revision.id,
                    "previous_id": expected_head,
                    "partial": partial,
                    "selected": sorted(selected),
                    "diff": diff,
                },
            )
        log_event("lab_intake", operation=kind, status="ok")
        return receipt

    def reports(self):
        with session_scope(self.engine) as session:
            session.execute(text("BEGIN"))
            reports = session.scalars(select(LabReport).order_by(LabReport.id).limit(201)).all()
            result = []
            for report in reports[:200]:
                head = session.get(LabHead, report.id)
                revision = session.get(LabRevision, head.revision_id) if head.revision_id else None
                drafts = session.scalars(
                    select(LabInterpretation)
                    .where(LabInterpretation.report_id == report.id)
                    .limit(201)
                ).all()
                result.append(
                    {
                        "report_id": report.id,
                        "revision_id": head.revision_id,
                        "partial": revision.partial if revision else None,
                        "snapshot": json.loads(revision.snapshot_json) if revision else None,
                        "interpretations": [i.id for i in drafts[:200]],
                        "more_drafts": len(drafts) > 200,
                    }
                )
            return {"reports": result, "more": len(reports) > 200}
