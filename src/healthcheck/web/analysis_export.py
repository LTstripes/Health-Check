"""Local UI adapter for the existing bounded combined evidence packet."""

from collections import Counter
from datetime import UTC, date, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from healthcheck.chat_evidence import EvidenceError, _read_session
from healthcheck.combined_evidence import (
    CombinedEvidenceRequest,
    encode_combined_evidence,
    read_combined_evidence,
    render_combined_evidence,
)
from healthcheck.db.models import GarminSource, GoogleSource

router = APIRouter()
NO_STORE = {"Cache-Control": "no-store"}


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    end_date: date
    days: int = Field(strict=True)
    garmin_source_id: str = Field(min_length=1, max_length=36)
    google_hrv_source_id: str | None = Field(default=None, min_length=1, max_length=36)
    steps_view: str = "observed"


def _error(code: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"code": code}, status_code=status, headers=NO_STORE)


def _source_label(row) -> str:
    provider = "Garmin Connect" if row.provider_code == "garmin_connect" else "Google"
    device = row.device_model if row.device_attributed else "источник"
    return f"{provider} · {device} · {row.id[:8]}"


@router.get("/api/analysis-export/sources")
def sources(request: Request) -> JSONResponse:
    """Bounded saved inventory only; never choose between competing sources."""
    try:
        with _read_session(request.app.state.runtime_paths.root) as session:
            rows = []
            for model in (GarminSource, GoogleSource):
                found = list(session.scalars(select(model).order_by(model.id).limit(33)))
                if len(found) > 32:
                    return _error("source_inventory_exceeds_limit")
                rows.extend(found)
            result = [
                {"id": row.id, "provider": row.provider_code,
                 "label": _source_label(row)}
                for row in rows if row.provider_code in {"garmin_connect", "google_health"}
            ]
        return JSONResponse({"sources": result}, headers=NO_STORE)
    except Exception:
        return _error("export_sources_unavailable", 503)


def _disclosures(value: dict) -> dict:
    """Show reader metadata without daily rows, comments or a second analytics layer."""
    result = {}
    for key, item in value.items():
        if key == "effective_completed_range" and isinstance(item, dict):
            result[key] = {bound: item[bound] for bound in ("start_date", "end_date")}
        elif isinstance(item, dict):
            nested = _disclosures(item)
            if nested:
                result[key] = nested
        elif key == "cells" and isinstance(item, list):
            result["cell_state_counts"] = dict(Counter(cell["state"] for cell in item))
        elif (key in {"missing_dates", "observed_dates", "dates_without_eligible_snapshot"}
              and isinstance(item, list)):
            result[key + "_count"] = len(item)
        elif (key in {"state", "status", "availability", "window_state", "origin_state",
                      "reason", "search_complete", "complete", "has_more",
                      "truncated", "warnings", "acquisition_coverage_state", "display_zone"}
              or key.endswith(("_day_count", "_count"))):
            result[key] = item
    return result


@router.post("/api/analysis-export")
def generate(request: Request, selection: ExportRequest) -> JSONResponse:
    clock = datetime.now(UTC)
    source = selection.garmin_source_id
    try:
        query = CombinedEvidenceRequest(
            end_date=selection.end_date, days=selection.days,
            activity_garmin_source_id=source, sleep_garmin_source_id=source,
            sleep_google_auto_select=True, projection="compact", include_context=True,
            stress_garmin_source_id=source, body_battery_garmin_source_id=source,
            hrv_garmin_source_id=source, hrv_google_source_id=selection.google_hrv_source_id,
            rhr_garmin_source_id=source, rhr_google_auto_select=True,
            steps_garmin_source_id=source, include_weight=True, steps_view=selection.steps_view,
        )
        packet = read_combined_evidence(
            profile=request.app.state.runtime_paths.root, profile_kind="durable_owner_runtime",
            request=query, evaluated_at_utc=clock,
            evaluation_local_date=clock.astimezone().date(),
        )
        # Both serializers must succeed before either result is released. No prefix,
        # server-side file/cache, output cap increase, or second database read.
        machine = encode_combined_evidence(packet)
        readable = render_combined_evidence(packet)
        return JSONResponse({
            "json": machine, "text": readable,
            "filename": f"health-analysis-{selection.end_date}-{selection.days}d-"
                        f"{packet['envelope_hash'][:12]}",
            "range": packet["request"]["effective_range"],
            "disclosures": {name: _disclosures(section)
                            for name, section in packet["sections"].items()},
        }, headers=NO_STORE)
    except EvidenceError as exc:
        # EvidenceError contains only the reader's stable, privacy-safe code.
        return _error(str(exc))
    except Exception:
        return _error("export_unavailable", 503)
