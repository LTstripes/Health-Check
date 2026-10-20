"""Loopback-only desktop adapter over the shared lab intake service."""

from __future__ import annotations

import json
from copy import deepcopy
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from healthcheck.labs.schema import MAX_DRAFT, MAX_PDF, Draft, LabError, encode
from healthcheck.labs.service import LabConflict, LabService
from healthcheck.web.common import request_engine
from healthcheck.web.pages import templates

router = APIRouter()
MAX_FORM = MAX_PDF + MAX_DRAFT + 64 * 1024


def service(request):
    return LabService(request_engine(request), request.app.state.runtime_paths.root)


def render(request, *, status=200, **context):
    if context.get("review"):
        context["fields"] = correction_fields(deepcopy(context["review"]["draft"]))
    response = templates.TemplateResponse(
        request,
        "labs.html",
        {"page": "labs", "operation_id": str(uuid4()), **context},
        status_code=status,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


async def form_data(request, *, upload=False):
    content = bytearray()
    limit = MAX_FORM if upload else 2 * MAX_DRAFT
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > limit:
            raise LabError("request_size")
    request._body = bytes(content)
    try:
        return await request.form(
            max_files=2 if upload else 0, max_fields=8000, max_part_size=2 * MAX_DRAFT
        )
    except Exception as exc:
        raise LabError("invalid_form") from exc


def failure(request, exc, *, review=None, correction=None):
    return render(
        request,
        status=409 if isinstance(exc, LabConflict) else 422,
        error=str(exc),
        review=review,
        correction=correction,
    )


@router.get("/labs")
def labs_list(request: Request):
    return render(request, listing=service(request).reports())


@router.post("/labs/stage")
async def labs_stage(request: Request):
    try:
        form = await form_data(request, upload=True)
        if set(form) != {"pdf", "draft", "operation_id"} or any(
            len(form.getlist(k)) != 1 for k in form
        ):
            raise LabError("invalid_form")
        pdf, draft = form["pdf"], form["draft"]
        # Starlette UploadFile is the runtime form object (FastAPI subclasses it).
        if not hasattr(pdf, "read") or not hasattr(draft, "read"):
            raise LabError("two_files_required")
        try:
            pdf_bytes, draft_bytes = await pdf.read(MAX_PDF + 1), await draft.read(MAX_DRAFT + 1)
        finally:
            await pdf.close()
            await draft.close()
        receipt = service(request).stage(pdf_bytes, draft_bytes, form["operation_id"])
        return RedirectResponse(f"/labs/review/{receipt['interpretation_id']}", status_code=303)
    except LabError as exc:
        return failure(request, exc)


@router.get("/labs/review/{interpretation_id}")
def labs_review(request: Request, interpretation_id: str):
    try:
        return render(request, review=service(request).review(interpretation_id))
    except LabError as exc:
        return failure(request, exc)


@router.get("/labs/{report_id}/original")
def labs_original(request: Request, report_id: str):
    try:
        content = service(request).original(report_id)
        return Response(
            content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": 'attachment; filename="laboratory-original.pdf"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "sandbox; default-src 'none'",
            },
        )
    except LabError as exc:
        return failure(request, exc)


@router.post("/labs/review/{interpretation_id}/correct")
async def labs_correct(request: Request, interpretation_id: str):
    review = None
    try:
        review = service(request).review(interpretation_id)
        form = await form_data(request)
        if any(len(form.getlist(k)) != 1 for k in form):
            raise LabError("invalid_form")
        draft = review["draft"]
        # Every edited leaf is an explicit visible input. Unchanged nulls remain null.
        fields = correction_fields(draft)
        if set(form) != {"operation_id", *fields}:
            raise LabError("invalid_form")
        for key, original in fields.items():
            value = form[key]
            if not isinstance(value, str):
                raise LabError("invalid_form")
            if value == ("" if original is None else str(original)):
                continue
            parts = key.split(".")
            obj = draft
            for part in parts[:-1]:
                obj = obj[int(part)] if isinstance(obj, list) else obj[part]
            leaf = parts[-1]
            if leaf == "incomplete":
                if value not in {"True", "False"}:
                    raise LabError("invalid_form")
                obj[leaf] = value == "True"
            elif leaf == "page":
                obj[leaf] = int(value) if value else None
            else:
                obj[leaf] = value if value else None
            # This UI is an explicit owner correction. Preserve original origins
            # for untouched leaves; never attribute the changed value to assistant.
            target = draft["rows"][int(parts[1])] if parts[0] == "rows" else draft
            field = parts[2] if parts[0] == "rows" else parts[0]
            if field != "provenance":
                target.setdefault("field_provenance", {})[field] = {
                    "transcription": "manual",
                    "page": None,
                    "support": None,
                }
        # Date pairs are exposed as value + precision; blank pair means unknown.
        for obj in [draft, *draft["rows"]]:
            for key in ("result_date", "printed_date", "specimen_date"):
                if (
                    key in obj
                    and isinstance(obj[key], dict)
                    and not obj[key]["value"]
                    and not obj[key]["precision"]
                ):
                    obj[key] = None
        Draft.model_validate(draft)
        pdf = service(request).original(review["report_id"])
        receipt = service(request).stage(
            pdf, encode(draft).encode("utf-8"), form["operation_id"], parent_id=interpretation_id
        )
        return RedirectResponse(f"/labs/review/{receipt['interpretation_id']}", status_code=303)
    except (LabError, ValueError, TypeError) as exc:
        safe = exc if isinstance(exc, LabError) else LabError("invalid_correction")
        return failure(request, safe, review=review)


def correction_fields(draft):
    """Explicit editable leaves, including unknown date values, never hidden JSON."""
    result = {}

    def visit(obj, path=""):
        if isinstance(obj, dict):
            for key, value in list(obj.items()):
                if key in {"schema_version", "pdf_sha256", "scope", "row_id", "field_provenance"}:
                    continue
                if key.endswith("_date") and value is None:
                    obj[key] = value = {"value": None, "precision": None}
                visit(value, f"{path}.{key}" if path else key)
        elif isinstance(obj, list):
            for index, value in enumerate(obj):
                visit(value, f"{path}.{index}")
        else:
            result[path] = obj

    visit(draft)
    return result


@router.post("/labs/review/{interpretation_id}/decide")
async def labs_decide(request: Request, interpretation_id: str):
    review = None
    try:
        review = service(request).review(interpretation_id)
        form = await form_data(request)
        if set(form) - {"operation_id", "expected_head", "kind", "partial", "selected", "ack"}:
            raise LabError("invalid_form")
        if any(len(form.getlist(k)) != 1 for k in form if k != "selected"):
            raise LabError("invalid_form")
        if form.get("ack") != "yes" or form.get("partial", "no") not in {"yes", "no"}:
            raise LabError("explicit_confirmation_required")
        receipt = service(request).decide(
            interpretation_id,
            form.getlist("selected"),
            expected_head=form.get("expected_head") or None,
            partial=form.get("partial") == "yes",
            operation_id=form.get("operation_id"),
            kind=form.get("kind"),
        )
        return render(request, receipt=receipt, listing=service(request).reports())
    except LabError as exc:
        return failure(request, exc, review=review)


@router.get("/labs/schema")
def labs_schema():
    return Response(
        json.dumps(Draft.model_json_schema()),
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )
