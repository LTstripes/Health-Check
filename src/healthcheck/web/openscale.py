"""HTTP route for the ingest-only openScale-sync webhook."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Engine

from healthcheck.db.engine import create_sqlite_engine, session_scope
from healthcheck.ingestion.openscale.errors import OpenScaleIngestError
from healthcheck.ingestion.openscale.service import OpenScaleWebhookService
from healthcheck.logging import log_event

router = APIRouter()


def _engine(request: Request) -> Engine:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        engine = create_sqlite_engine(request.app.state.runtime_paths)
        request.app.state.engine = engine
    return engine


@router.post("/api/ingest/openscale")
async def ingest_openscale(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    paths = request.app.state.runtime_paths
    body = await request.body()
    authorization = request.headers.get("authorization")
    media_type = request.headers.get("content-type")
    try:
        with session_scope(_engine(request)) as session:
            result = OpenScaleWebhookService(session, paths, settings).ingest(
                body=body,
                authorization_header=authorization,
                media_type=media_type,
            )
    except OpenScaleIngestError as exc:
        log_event(
            "openscale_ingest_error",
            operation="openscale_ingest",
            status="error",
            reason=exc.code,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )
    return JSONResponse(
        status_code=200,
        content={
            "status": "accepted",
            "event": result.event,
            "batch_id": result.batch_id,
            "acknowledged": result.acknowledged,
            "items": [
                {
                    "status": item.status,
                    "ingest_event_id": item.event_id,
                    "measurement_session_id": item.session_id,
                    "session_id": item.session_id,
                    "diagnostic_code": item.reason_code,
                    "duplicate_of_event_id": item.duplicate_of_event_id,
                    "batch_index": item.batch_index,
                }
                for item in result.items
            ],
        },
    )


__all__ = ["router"]
