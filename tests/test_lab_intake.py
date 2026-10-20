"""Synthetic-only v1 laboratory intake integrity and local desktop contracts."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from healthcheck.config import Settings
from healthcheck.db.engine import (
    _alembic_config,
    create_sqlite_engine,
    migrate_database,
    session_scope,
)
from healthcheck.db.models import RawArtifact
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.labs.models import (
    LabHead,
    LabInterpretation,
    LabOperation,
    LabReport,
    LabResult,
    LabRevision,
)
from healthcheck.labs.schema import MAX_DRAFT, MAX_PDF, LabError, encode, parse_draft, sha
from healthcheck.labs.service import LabConflict, LabService, artifact_bytes
from healthcheck.profile_backup import (
    ProfileBackupError,
    create_backup,
    restore_backup,
    verify_backup,
)
from healthcheck.runtime import prepare_runtime
from healthcheck.web.labs import correction_fields
from healthcheck.web.ui_app import create_ui_app

BASE = "http://127.0.0.1:8120"
PROVENANCE = {"transcription": "assistant", "page": None, "support": None}


def synthetic_pdf(label="SYNTHETIC LAB ONLY"):
    """Small valid one-page PDF, generated in memory; no personal source fixture."""
    stream = f"BT /F1 12 Tf 20 100 Td ({label}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    content = b"%PDF-1.4\n"
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(content))
        content += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(content)
    content += b"xref\n0 6\n0000000000 65535 f \n"
    content += b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets)
    return content + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()


PDF = synthetic_pdf()


def draft(pdf=PDF):
    row = dict(
        row_id="r1",
        label_raw="Synthetic Marker",
        result_raw="< 0,0100",
        unit_raw=None,
        reference_raw=None,
        flag_raw=None,
        value_kind="numeric",
        decimal="0.0100",
        comparator="<",
        qualitative=None,
        method_raw=None,
        equipment_kit_notes="Synthetic kit",
        specimen_raw=None,
        specimen_date=None,
        provenance=copy.deepcopy(PROVENANCE),
        uncertainty="Unit not printed",
    )
    qualitative = {
        **copy.deepcopy(row),
        "row_id": "r2",
        "label_raw": "Synthetic qualitative",
        "result_raw": "Negative",
        "value_kind": "qualitative",
        "decimal": None,
        "comparator": None,
        "qualitative": "Negative",
        "uncertainty": None,
    }
    unparsed = {
        **copy.deepcopy(qualitative),
        "row_id": "r3",
        "result_raw": "see note α",
        "value_kind": "unparsed",
        "qualitative": None,
    }
    return dict(
        schema_version="lab-draft-v1",
        pdf_sha256=sha(pdf),
        scope="single_report_single_patient",
        patient_link="resolved",
        report_link="resolved",
        source_match="unverified",
        clinic_source="Synthetic Clinic",
        performing_lab="Synthetic Lab",
        report_label="Synthetic report",
        result_date={"value": "2099-01-02", "precision": "date"},
        printed_date={"value": "2099-01-03T11:12", "precision": "minute"},
        specimen_date=None,
        provenance=copy.deepcopy(PROVENANCE),
        incomplete=False,
        uncertainty=None,
        rows=[row, qualitative, unparsed],
    )


def raw(value):
    return encode(value).encode()


@pytest.fixture
def runtime(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "profile"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    yield LabService(engine, paths.root), paths
    engine.dispose()


def count(service, model):
    with session_scope(service.engine) as session:
        return session.scalar(select(func.count()).select_from(model))


def staged(service, value=None, operation="stage"):
    return service.stage(PDF, raw(value or draft()), operation)


def confirm(
    service, receipt, operation="confirm", selected=None, partial=False, head=None, kind="confirm"
):
    return service.decide(
        receipt["interpretation_id"],
        selected or ["r1", "r2", "r3"],
        expected_head=head,
        partial=partial,
        operation_id=operation,
        kind=kind,
    )


def test_stage_byte_hash_identity_and_typed_acceptance(runtime):
    service, paths = runtime
    source = b"  " + raw(draft()) + b"\n"
    receipt = service.stage(PDF, source, "stage")
    assert receipt == service.stage(PDF, source, "stage")
    assert receipt["draft_sha256"] == sha(source)
    assert count(service, LabResult) == 0
    duplicate = service.stage(PDF, source, "duplicate")
    assert duplicate["report_id"] == receipt["report_id"]
    assert duplicate["interpretation_id"] == receipt["interpretation_id"]
    accepted = confirm(service, receipt)
    assert confirm(service, receipt) == accepted
    assert service.original(receipt["report_id"]) == PDF
    with session_scope(service.engine) as session:
        numeric = session.get(LabResult, (accepted["revision_id"], "r1"))
        assert (numeric.decimal, numeric.comparator, numeric.unit_raw, numeric.reference_raw) == (
            "0.0100",
            "<",
            None,
            None,
        )
        snapshot = json.loads(session.get(LabRevision, accepted["revision_id"]).snapshot_json)
        assert snapshot["source_match"] == "unverified"
        assert snapshot["specimen_date"] is None
        assert snapshot["rows"][0]["method_raw"] is None
        assert snapshot["clinic_source"] != snapshot["performing_lab"]
        assert snapshot["printed_date"] != snapshot["result_date"]
        artifact = session.scalar(
            select(RawArtifact).where(RawArtifact.content_hash == sha(source))
        )
        assert (paths.root / "artifacts" / artifact.relative_storage_path).read_bytes() == source
    assert count(service, LabReport) == 1
    assert count(service, LabRevision) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(schema_version="lab-draft-v2"),
        lambda d: d.update(scope="mixed_patients"),
        lambda d: d.update(extra="not allowed"),
        lambda d: d["rows"][0].update(decimal=0.01),
        lambda d: d["rows"][0].update(decimal="NaN"),
        lambda d: d["rows"][0].update(decimal="1e10"),
        lambda d: d["rows"][0]["provenance"].update(confidence=1.0),
        lambda d: d["rows"][0]["provenance"].update(page=True),
        lambda d: d["rows"][0].update(label_raw="x" * 256),
        lambda d: d["rows"].append(copy.deepcopy(d["rows"][0])),
        lambda d: d.update(result_date={"value": "2099-01-02T12:00", "precision": "date"}),
    ],
)
def test_bounded_strict_schema(runtime, mutation):
    service, _ = runtime
    value = draft()
    mutation(value)
    with pytest.raises(LabError):
        staged(service, value)
    assert count(service, LabReport) == 0
    assert count(service, RawArtifact) == 0


def test_schema_mismatch_invalid_envelope_bounds_and_duplicate_keys(runtime):
    service, _ = runtime
    for pdf, data in [
        (b"not PDF", raw(draft())),
        (PDF + b"x" * MAX_PDF, raw(draft())),
        (PDF, b"x" * (MAX_DRAFT + 1)),
        (synthetic_pdf("other"), raw(draft())),
        (PDF, b'{"schema_version":"lab-draft-v1","schema_version":"lab-draft-v1"}'),
    ]:
        with pytest.raises(LabError):
            service.stage(pdf, data, "bad")
    assert count(service, RawArtifact) == 0


def test_unknown_linkage_blocks_and_does_not_claim_source_verification(runtime):
    service, _ = runtime
    value = draft()
    value["patient_link"] = "unresolved"
    item = staged(service, value)
    with pytest.raises(LabError, match="unresolved"):
        confirm(service, item)
    assert count(service, LabRevision) == 0


def test_partial_terminal_and_full_snapshot_revise(runtime):
    service, _ = runtime
    item = staged(service)
    with pytest.raises(LabError, match="partial_required"):
        confirm(service, item, selected=["r1"])
    first = confirm(service, item, selected=["r1"], partial=True)
    with pytest.raises(LabConflict):
        confirm(service, item, operation="append", head=first["revision_id"], kind="revise")
    value = draft()
    value["rows"][0]["decimal"] = "0.0200"
    value["rows"][0]["result_raw"] = "< 0,0200"
    value["rows"] = value["rows"][:2]
    second_draft = staged(service, value, "correction")
    assert second_draft["report_id"] == item["report_id"]
    with pytest.raises(LabError, match="full_snapshot"):
        confirm(
            service,
            second_draft,
            operation="bad-subset",
            selected=["r1"],
            head=first["revision_id"],
            kind="revise",
        )
    revised = confirm(
        service,
        second_draft,
        operation="revise",
        selected=["r1", "r2"],
        head=first["revision_id"],
        kind="revise",
    )
    assert revised["diff"] == {"retained": [], "changed": ["r1"], "removed": [], "added": ["r2"]}
    third = draft()
    third["rows"] = [third["rows"][1]]
    fresh = staged(service, third, "third")
    final = confirm(
        service,
        fresh,
        operation="third-confirm",
        selected=["r2"],
        head=revised["revision_id"],
        kind="revise",
    )
    assert final["diff"] == {"retained": ["r2"], "changed": [], "removed": ["r1"], "added": []}
    assert count(service, LabRevision) == 3
    assert count(service, LabReport) == 1


def test_operation_reuse_conflicts_different_pdf_not_merged(runtime):
    service, _ = runtime
    first = staged(service)
    value = draft()
    value["report_label"] = "changed"
    with pytest.raises(LabConflict, match="payload_changed"):
        staged(service, value)
    accepted = confirm(service, first)
    with pytest.raises(LabConflict, match="payload_changed"):
        confirm(service, first, selected=["r1"], partial=True)
    other = synthetic_pdf("OTHER SYNTHETIC REPORT")
    item = service.stage(other, raw(draft(other)), "other")
    assert item["report_id"] != first["report_id"]
    assert service.reports()["reports"]
    assert accepted["revision_id"]


def test_racing_confirm_and_stale_revise_are_atomic(runtime):
    service, _ = runtime
    item = staged(service)

    def attempt(index):
        try:
            return confirm(service, item, operation=f"race-{index}")
        except LabConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [1, 2]))
    assert sum(r is not None for r in results) == 1
    assert count(service, LabRevision) == 1
    assert count(service, LabResult) == 3
    assert count(service, LabOperation) == 2  # staging + winner, no loser receipt
    changed = draft()
    changed["uncertainty"] = "fresh"
    next_draft = staged(service, changed, "fresh")
    with pytest.raises(LabConflict, match="stale_head"):
        confirm(service, next_draft, operation="stale", kind="revise", head="old")
    assert count(service, LabRevision) == 1


def test_corruption_blocks_review_acceptance_download_and_backup(runtime, tmp_path):
    service, paths = runtime
    item = staged(service)
    with session_scope(service.engine) as session:
        report = session.get(LabReport, item["report_id"])
        artifact = session.get(RawArtifact, report.pdf_artifact_id)
        path = paths.root / "artifacts" / artifact.relative_storage_path
    path.write_bytes(b"corrupted")
    for action in [
        lambda: service.original(item["report_id"]),
        lambda: service.review(item["interpretation_id"]),
        lambda: confirm(service, item),
    ]:
        with pytest.raises(LabError, match="corrupt"):
            action()
    with pytest.raises(ProfileBackupError, match="closure"):
        create_backup(paths.root, tmp_path / "corrupt.zip")
    assert count(service, LabRevision) == 0


def test_backup_restore_hash_reference_closure_and_immutable_history(runtime, tmp_path):
    service, paths = runtime
    item = staged(service)
    receipt = confirm(service, item)
    archive = tmp_path / "backup.zip"
    create_backup(paths.root, archive)
    verify_backup(archive)
    target = tmp_path / "restored"
    restore_backup(archive, target)
    restored_paths = prepare_runtime(Settings(data_dir=target))
    restored_engine = create_sqlite_engine(restored_paths)
    restored = LabService(restored_engine, target)
    assert restored.original(item["report_id"]) == PDF
    assert confirm(restored, item) == receipt
    assert restored.reports() == service.reports()
    restored_engine.dispose()
    for table in [
        "lab_reports",
        "lab_interpretations",
        "lab_revisions",
        "lab_results",
        "lab_operations",
    ]:
        with pytest.raises(Exception, match="append-only"):
            with service.engine.begin() as connection:
                connection.execute(text(f"DELETE FROM {table}"))
    with service.engine.connect() as connection:
        assert not connection.exec_driver_sql("PRAGMA foreign_key_check").all()


def test_download_path_metadata_rejected(runtime):
    service, paths = runtime
    staged(service)
    artifact = RawArtifact(
        content_hash=sha(PDF), byte_size=len(PDF), relative_storage_path="payloads/not-a-lab.pdf"
    )
    with pytest.raises(LabError, match="metadata"):
        artifact_bytes(paths.root, artifact, extension="pdf")


def test_desktop_ui_upload_correction_confirm_download_and_origin(runtime):
    service, paths = runtime
    app, _ = create_ui_app(
        Settings(data_dir=paths.root), photo_extractor=FakeImageMeasurementExtractor()
    )
    with TestClient(app, base_url=BASE) as client:
        assert client.get("/labs").status_code == 200
        forbidden = client.post("/labs/stage", headers={"Origin": "https://attacker.invalid"})
        assert forbidden.status_code == 403
        response = client.post(
            "/labs/stage",
            files={
                "pdf": ("../../not-used.pdf", PDF, "application/pdf"),
                "draft": ("synthetic.json", raw(draft()), "application/json"),
            },
            data={"operation_id": "ui-stage"},
            headers={"Origin": BASE},
        )
        assert response.status_code == 200
        assert "Synthetic Marker" in response.text and "unverified" in response.text
        item = service.reports()["reports"][0]
        interpretation_id = item["interpretations"][0]
        fields = correction_fields(copy.deepcopy(draft()))
        fields = {k: "" if v is None else str(v) for k, v in fields.items()}
        fields["operation_id"] = "ui-correct"
        fields["rows.0.result_raw"] = "< 0,0300"
        fields["rows.0.decimal"] = "0.0300"
        correction = client.post(
            f"/labs/review/{interpretation_id}/correct", data=fields, headers={"Origin": BASE}
        )
        assert correction.status_code == 200, correction.text
        changed_id = str(correction.url).split("/")[-1]
        assert changed_id != interpretation_id
        corrected_draft = service.review(changed_id)["draft"]
        assert corrected_draft["rows"][0]["provenance"]["transcription"] == "assistant"
        assert corrected_draft["rows"][0]["field_provenance"] == {
            "result_raw": {"transcription": "manual", "page": None, "support": None},
            "decimal": {"transcription": "manual", "page": None, "support": None},
        }
        assert corrected_draft["rows"][1]["field_provenance"] == {}
        assert count(service, LabResult) == 0
        result = client.post(
            f"/labs/review/{changed_id}/decide",
            data={
                "operation_id": "ui-confirm",
                "expected_head": "",
                "kind": "confirm",
                "ack": "yes",
                "selected": ["r1", "r2", "r3"],
            },
            headers={"Origin": BASE},
        )
        assert result.status_code == 200, result.text
        assert count(service, LabResult) == 3
        download = client.get(f"/labs/{item['report_id']}/original")
        assert download.content == PDF
        assert download.headers["content-disposition"].startswith("attachment;")
        assert download.headers["x-content-type-options"] == "nosniff"
        assert download.headers["cache-control"] == "no-store"
        assert "0,0300" in client.get("/labs").text
        assert client.get("/labs/schema").json()["additionalProperties"] is False


def test_fault_after_revision_insert_rolls_back_rows_receipt_and_head(runtime, monkeypatch):
    import healthcheck.labs.service as module

    service, _ = runtime
    item = staged(service)

    def fail(*args):
        raise RuntimeError("synthetic receipt failure")

    monkeypatch.setattr(module, "_receipt", fail)
    with pytest.raises(RuntimeError, match="synthetic"):
        confirm(service, item)
    assert count(service, LabRevision) == 0
    assert count(service, LabResult) == 0
    assert count(service, LabOperation) == 1
    with session_scope(service.engine) as session:
        assert session.get(LabHead, item["report_id"]).revision_id is None


def test_racing_stage_deduplicates_and_revise_uses_current_head(runtime):
    service, _ = runtime
    with ThreadPoolExecutor(max_workers=2) as pool:
        items = list(pool.map(lambda n: staged(service, operation=f"stage-{n}"), [1, 2]))
    assert items[0]["interpretation_id"] == items[1]["interpretation_id"]
    assert count(service, LabReport) == count(service, LabInterpretation) == 1
    first = confirm(service, items[0])
    next_items = []
    for n in [1, 2]:
        value = draft()
        value["uncertainty"] = f"Synthetic change {n}"
        next_items.append(staged(service, value, f"next-{n}"))

    def revise(n):
        try:
            return confirm(
                service,
                next_items[n],
                operation=f"revise-{n}",
                head=first["revision_id"],
                kind="revise",
            )
        except LabConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(revise, [0, 1]))
    assert sum(x is not None for x in outcomes) == 1
    assert count(service, LabRevision) == 2
    assert count(service, LabResult) == 6


def test_missing_original_in_self_consistent_zip_is_rejected(runtime, tmp_path):
    service, paths = runtime
    staged(service)
    archive = tmp_path / "valid.zip"
    create_backup(paths.root, archive)
    target = tmp_path / "missing-original.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(target, "w") as destination:
        manifest = json.loads(source.read("manifest.json"))
        removed = next(i["path"] for i in manifest["files"] if i["path"].endswith(".pdf"))
        manifest["files"] = [i for i in manifest["files"] if i["path"] != removed]
        for name in source.namelist():
            if name == "profile/" + removed:
                continue
            destination.writestr(
                name, raw(manifest) if name == "manifest.json" else source.read(name)
            )
    with pytest.raises(ProfileBackupError, match="closure"):
        verify_backup(target)


def test_artifact_junction_or_symlink_never_escapes_profile(runtime, tmp_path):
    service, paths = runtime
    outside = tmp_path / "outside"
    outside.mkdir()
    link = paths.root / "artifacts" / "labs"
    if os.name == "nt":
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "New-Item -ItemType Junction -Path $env:HC348_LINK "
                "-Target $env:HC348_TARGET -ErrorAction Stop | Out-Null",
            ],
            check=True,
            capture_output=True,
            env={**os.environ, "HC348_LINK": str(link), "HC348_TARGET": str(outside)},
        )
    else:
        link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(LabError, match="artifact_path"):
        staged(service)
    assert not list(outside.iterdir())
    assert count(service, LabReport) == 0


def test_additive_migration_roundtrip_and_populated_downgrade_guard(runtime):
    service, paths = runtime
    command.downgrade(_alembic_config(paths), "0016_garmin_daily_summary_receipts")
    migrate_database(paths)
    item = staged(service)
    accepted = confirm(service, item)
    with pytest.raises(RuntimeError, match="refuses to discard"):
        command.downgrade(_alembic_config(paths), "0016_garmin_daily_summary_receipts")
    assert confirm(service, item) == accepted
    assert service.original(item["report_id"]) == PDF


def test_incomplete_full_subset_requires_explicit_partial(runtime):
    service, _ = runtime
    value = draft()
    value["incomplete"] = True
    item = staged(service, value)
    with pytest.raises(LabError, match="partial_required"):
        confirm(service, item)
    assert confirm(service, item, partial=True)["partial"]


def test_backup_rejects_well_formed_draft_attached_to_another_pdf(runtime, tmp_path):
    from uuid import uuid4

    service, paths = runtime
    first = staged(service)
    other_pdf = synthetic_pdf("ANOTHER SYNTHETIC REPORT")
    second = service.stage(other_pdf, raw(draft(other_pdf)), "second")
    with session_scope(service.engine) as session:
        source = session.get(LabInterpretation, first["interpretation_id"])
        session.add(
            LabInterpretation(
                id=str(uuid4()),
                report_id=second["report_id"],
                draft_artifact_id=source.draft_artifact_id,
                parent_id=None,
            )
        )
    with pytest.raises(ProfileBackupError, match="binding closure"):
        create_backup(paths.root, tmp_path / "misbound.zip")


@pytest.mark.parametrize(
    "value,precision",
    [("2099-02-30", "date"), ("2099-01-01T25:00", "minute"), ("2099-01-01T01:02:03", "minute")],
)
def test_date_precision_never_inferred(value, precision):
    content = draft()
    content["specimen_date"] = {"value": value, "precision": precision}
    with pytest.raises(LabError):
        parse_draft(raw(content))
