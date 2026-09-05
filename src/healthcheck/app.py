"""Application composition shared by the two listener-specific ASGI apps."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from healthcheck.config import Settings
from healthcheck.runtime import RuntimePaths, prepare_runtime, resolve_runtime_paths


class HealthResponse(BaseModel):
    status: str
    service: str


def create_base_app(
    settings: Settings, *, service: str, title: str
) -> tuple[FastAPI, RuntimePaths]:
    paths = resolve_runtime_paths(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime_paths = prepare_runtime(settings)
        app.state.runtime_paths = runtime_paths
        yield

    app = FastAPI(
        title=title,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.runtime_paths = paths

    @app.get("/healthz", response_model=HealthResponse)
    def healthz() -> HealthResponse:
        return HealthResponse(status="ok", service=service)

    return app, paths
