"""One existing Overview observation card over the accepted #376 reader.

The period packet and the other cards are untouched. No collection proof is
invented here: empty searches retain the reader's state and coverage stays unknown.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from healthcheck.db.models import GoogleSource
from healthcheck.saved_values import GARMIN_RHR, GOOGLE_RHR, SavedValueQuery, read_saved_rhr
from healthcheck.web.sleep_view import google_vital_source_label


def read_overview_rhr(
    session: Session, *, start: date, end: date, explicit_period: bool,
    evaluated_at_utc: datetime, evaluation_local_date: date,
    garmin_source_id: str | None, google_source_id: str | None = None,
    freshness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep exact source identity and clocks; only a declared default card seeks back."""
    mode = "explicit_period" if explicit_period else "default_latest"
    items = []
    for provider, metric, source_id, label, scope in (
        ("garmin_connect", GARMIN_RHR, garmin_source_id, "Garmin", "garmin:resting_heart_rate"),
        ("google_health", GOOGLE_RHR, google_source_id, "Google", "google:daily_resting_hr"),
    ):
        result = read_saved_rhr(session, SavedValueQuery(
            provider_code=provider, metric_code=metric, source_id=source_id,
            requested_start_date=start if explicit_period else evaluation_local_date,
            requested_end_date=end if explicit_period else evaluation_local_date,
            mode=mode, evaluated_at_utc=evaluated_at_utc,
            evaluation_local_date=evaluation_local_date,
        )).as_dict()
        source_labels = {}
        for identity in result["available_sources"]:
            if provider == "google_health":
                source_labels[identity["source_id"]] = google_vital_source_label(
                    session.get(GoogleSource, identity["source_id"])
                )
            else:
                model = identity["device_model"] if identity["device_attributed"] else None
                source_labels[identity["source_id"]] = (
                    f"Garmin Connect · {model}" if model else "Garmin Connect"
                )
        # Freshness is the existing provider-stream projection, never evidence
        # that this exact source/metric was collected or has complete coverage.
        projection = freshness or {}
        facts = (
            projection.get("owner", {}).get("actionable_items", [])
            + projection.get("optional_details", [])
            + projection.get("not_requested_required", [])
        )
        items.append({
            "label": label, "dto": result,
            "source_labels": source_labels,
            "freshness": [item for item in facts if item["scope_key"] == scope],
        })
    return {"mode": mode, "items": items, "google_source_id": google_source_id}
