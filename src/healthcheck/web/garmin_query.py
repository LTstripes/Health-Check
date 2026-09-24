"""Read-only Garmin query service over accepted R03-01/02/03 analytics.

Routes stay thin. This module enumerates Garmin sources, selects exactly one
explicit source identity, and delegates all mathematics to the R03 modules.
It never syncs, reprocesses, ingests, mutates canonical data, or calls a
provider.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from healthcheck.analytics.garmin_activity_comparison import (
    ACTIVITY_COMPARISON_METRIC_CODES,
    MAX_SELECTED_ACTIVITIES,
    MIN_SELECTED_ACTIVITIES,
    GarminActivityComparisonError,
    GarminActivityComparisonQuery,
    analyze_garmin_activity_comparison,
)
from healthcheck.analytics.garmin_baselines import (
    MAX_SERIES_CALENDAR_DAYS,
    GarminScalarAnalyticsError,
    GarminSeriesQuery,
    analyze_garmin_metric_series,
)
from healthcheck.analytics.garmin_lagged_associations import (
    MAX_LAG_COUNT,
    MAX_LAG_DAYS,
    GarminLaggedAssociationError,
    GarminLaggedAssociationQuery,
    analyze_garmin_lagged_associations,
    metric_eligible_for_lagged_association,
)
from healthcheck.config import Settings
from healthcheck.db.models import GarminProjectionStatus, GarminSource, GarminSourceRecord
from healthcheck.db.repositories import restore_stored_utc
from healthcheck.garmin.analytic_contract import (
    ANALYTIC_METRIC_REGISTRY,
    AnalyticInputAssemblyError,
    AnalyticMetricDefinition,
)
from healthcheck.web.garmin_training_overview import (
    DEFAULT_RECENT_ACTIVITIES,
    MAX_RECENT_ACTIVITIES,
    training_overview_for_selection,
    unavailable_training_overview,
)

# Reviewed provider-native identities only (#55 registry + #73 presentation).
PROVIDER_NATIVE_SCORE_LABELS: dict[str, dict[str, str]] = {
    "sleep_score": {
        "display_name": "Provider sleep score",
        "kind": "provider_native",
        "semantics": "sleep_session",
        "wording": (
            "Garmin/provider-native sleep score for one sleep session. "
            "Does not imply sleep duration, stages, or naps completeness. "
            "Not a custom readiness or recovery score."
        ),
    },
    "training_effect": {
        "display_name": "Provider training effect",
        "kind": "provider_native",
        "semantics": "activity_session",
        "wording": (
            "Garmin/provider-native activity-session training effect. "
            "Not daily readiness, recovery, or a custom score."
        ),
    },
    "acute_training_load": {
        "display_name": "Provider acute training load",
        "kind": "provider_native",
        "semantics": "activity_session",
        "wording": (
            "Garmin/provider-native activity-session load. "
            "Not daily readiness, recovery, or a custom score."
        ),
    },
}

_COLLECTION_VALUED = frozenset({"sleep_stages"})
_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "authorization",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "session_token",
        "password",
        "secret",
        "cookie",
        "cookies",
        "api_key",
        "private_key",
        "configuration_snapshot",
        "raw_payload",
        "payload_body",
        "payload_bytes",
        "gps",
        "fit",
        "route",
        "routes",
        "map",
        "email",
        "telegram",
    }
)

ASSOCIATION_WORDING = (
    "Exploratory association only. No p-values, significance, best-lag ranking, "
    "causal, predictive, medical, or coaching claims."
)
ACTIVITY_WORDING = (
    "Descriptive activity-session comparison only. Same/different activity type and "
    "comparable/not-comparable coverage are preserved. Deltas are not better/worse "
    "coaching labels."
)
DASHBOARD_DISCLAIMER = (
    "Local loopback Garmin analytics. Presentation consumes accepted R03 results. "
    "No custom readiness/recovery score, diagnosis, or causal claims."
)
DEFAULT_SCALAR_METRIC = "stress_daily_average"
DEFAULT_WINDOW_DAYS = 28


class GarminQueryError(ValueError):
    """Deterministic sanitized client error for the Garmin query/dashboard layer."""

    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _metric_presentation(definition: AnalyticMetricDefinition) -> dict[str, Any]:
    native = PROVIDER_NATIVE_SCORE_LABELS.get(definition.metric_code)
    return {
        **definition.as_dict(),
        "display_name": native["display_name"] if native else definition.metric_code,
        "presentation_kind": native["kind"] if native else "reviewed_metric",
        "presentation_semantics": native["semantics"] if native else definition.window,
        "presentation_wording": native["wording"] if native else definition.description,
        "provider_native": native is not None,
    }



_TRAINING_PRESENTATION_FORBIDDEN = frozenset(
    {
        "record_id",
        "external_record_id",
        "idempotency_key",
        "provider_device_id",
        "provider_device_key",
        "requested_dates",
        "activityRecorderDeviceId",
        "raw_payload",
        "payload_body",
        "payload_bytes",
        "content_hash",
        "result_hash",
    }
)


def _strip_training_presentation_leaks(value: Any) -> Any:
    """Owner Training overview must not expose technical/provider identifiers."""

    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if key in _TRAINING_PRESENTATION_FORBIDDEN:
                continue
            cleaned[key] = _strip_training_presentation_leaks(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_training_presentation_leaks(item) for item in value]
    if isinstance(value, tuple):
        return [_strip_training_presentation_leaks(item) for item in value]
    return value


def _sanitize(value: Any) -> Any:
    """Drop secret/raw-payload shaped keys; keep hashes/ids and analytic values."""

    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in _FORBIDDEN_PAYLOAD_KEYS or any(
                marker in lowered
                for marker in ("token", "password", "secret", "authorization", "cookie")
            ):
                continue
            cleaned[key] = _sanitize(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    return value


def _map_domain_error(exc: Exception) -> GarminQueryError:
    if isinstance(exc, GarminQueryError):
        return exc
    if isinstance(
        exc,
        (
            GarminScalarAnalyticsError,
            GarminActivityComparisonError,
            GarminLaggedAssociationError,
        ),
    ):
        return GarminQueryError(exc.reason_code, str(exc), status_code=400)
    if isinstance(exc, AnalyticInputAssemblyError):
        return GarminQueryError(
            "analytic_input_assembly_failed",
            "analytic input could not be assembled from persisted evidence",
            status_code=400,
        )
    if isinstance(exc, ValueError):
        return GarminQueryError(
            "invalid_request",
            "request could not be processed",
            status_code=400,
        )
    return GarminQueryError("internal_error", "request failed", status_code=500)


class GarminQueryService:
    """Narrow application service over storage-backed R03 analytics."""

    def __init__(self, session: Session, settings: Settings | None = None):
        self.session = session
        self.settings = settings or Settings()

    def list_sources(self) -> list[dict[str, Any]]:
        rows = list(
            self.session.scalars(
                select(GarminSource).order_by(
                    GarminSource.provider_code.asc(),
                    GarminSource.source_instance_id.asc(),
                    GarminSource.id.asc(),
                )
            )
        )
        return [self._source_payload(row) for row in rows]

    def resolve_source(self, garmin_source_id: str | None = None) -> dict[str, Any]:
        sources = self.list_sources()
        explicit = (garmin_source_id or "").strip() or None
        if not sources:
            return {
                "status": "no_data",
                "reason": "no_garmin_sources",
                "selected_source_id": None,
                "sources": [],
            }
        if explicit is not None:
            match = next((item for item in sources if item["id"] == explicit), None)
            if match is None:
                raise GarminQueryError(
                    "unknown_garmin_source_id",
                    "garmin_source_id does not match a persisted Garmin source",
                )
            return {
                "status": "selected",
                "reason": None,
                "selected_source_id": match["id"],
                "sources": sources,
                "selected_source": match,
            }
        if len(sources) == 1:
            only = sources[0]
            return {
                "status": "selected",
                "reason": None,
                "selected_source_id": only["id"],
                "sources": sources,
                "selected_source": only,
            }
        return {
            "status": "require_selection",
            "reason": "multiple_garmin_sources",
            "selected_source_id": None,
            "sources": sources,
        }

    def list_scalar_metrics(self) -> list[dict[str, Any]]:
        return [
            _metric_presentation(definition)
            for code, definition in ANALYTIC_METRIC_REGISTRY.items()
            if code not in _COLLECTION_VALUED
        ]

    def list_lag_eligible_metrics(self) -> list[dict[str, Any]]:
        metrics: list[dict[str, Any]] = []
        for code, definition in ANALYTIC_METRIC_REGISTRY.items():
            eligible, _reason = metric_eligible_for_lagged_association(code)
            if eligible:
                metrics.append(_metric_presentation(definition))
        return metrics

    def list_activity_comparison_metrics(self) -> list[dict[str, Any]]:
        return [
            _metric_presentation(ANALYTIC_METRIC_REGISTRY[code])
            for code in ACTIVITY_COMPARISON_METRIC_CODES
            if code in ANALYTIC_METRIC_REGISTRY
        ]

    def native_score_labels(self) -> dict[str, dict[str, str]]:
        return {
            code: dict(label) for code, label in sorted(PROVIDER_NATIVE_SCORE_LABELS.items())
        }

    def list_activities(
        self,
        *,
        garmin_source_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        source_id = self._require_source_id(garmin_source_id)
        capped = max(1, min(int(limit), 100))
        rows = list(
            self.session.scalars(
                select(GarminSourceRecord)
                .where(
                    GarminSourceRecord.garmin_source_id == source_id,
                    GarminSourceRecord.stream_code == "activity",
                    GarminSourceRecord.projection_status
                    == GarminProjectionStatus.CURRENT.value,
                )
                .order_by(
                    GarminSourceRecord.source_local_date.desc(),
                    GarminSourceRecord.id.asc(),
                )
                .limit(capped)
            )
        )
        return [self._activity_summary(row) for row in rows]

    def scalar_series(
        self,
        *,
        garmin_source_id: str,
        metric_code: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        source_id = self._require_source_id(garmin_source_id)
        query = GarminSeriesQuery(
            metric_code=metric_code,
            start_date=start_date,
            end_date=end_date,
            garmin_source_id=source_id,
        )
        try:
            result = analyze_garmin_metric_series(self.session, query)
        except Exception as exc:  # noqa: BLE001 - mapped to sanitized client errors
            raise _map_domain_error(exc) from exc
        return self._present_scalar_result(result.as_dict())

    def activity_comparison(
        self,
        *,
        garmin_source_id: str,
        activity_record_ids: Sequence[str],
        reference_activity_id: str,
        metric_codes: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        source_id = self._require_source_id(garmin_source_id)
        query = GarminActivityComparisonQuery(
            garmin_source_id=source_id,
            activity_record_ids=tuple(activity_record_ids),
            reference_activity_id=reference_activity_id,
            metric_codes=(
                tuple(metric_codes)
                if metric_codes is not None
                else ACTIVITY_COMPARISON_METRIC_CODES
            ),
        )
        try:
            result = analyze_garmin_activity_comparison(self.session, query)
        except Exception as exc:  # noqa: BLE001
            raise _map_domain_error(exc) from exc
        return self._present_activity_result(result.as_dict())

    def lagged_association(
        self,
        *,
        garmin_source_id: str,
        x_metric_code: str,
        y_metric_code: str,
        start_date: date,
        end_date: date,
        lag_days: Sequence[int],
    ) -> dict[str, Any]:
        source_id = self._require_source_id(garmin_source_id)
        query = GarminLaggedAssociationQuery(
            garmin_source_id=source_id,
            x_metric_code=x_metric_code,
            y_metric_code=y_metric_code,
            start_date=start_date,
            end_date=end_date,
            lag_days=tuple(lag_days),
        )
        try:
            result = analyze_garmin_lagged_associations(self.session, query)
        except Exception as exc:  # noqa: BLE001
            raise _map_domain_error(exc) from exc
        return self._present_lag_result(result.as_dict())


    def training_overview(
        self,
        *,
        garmin_source_id: str | None = None,
        activity_limit: int = DEFAULT_RECENT_ACTIVITIES,
    ) -> dict[str, Any]:
        """Deterministic Training & recovery overview for explicit source selection."""

        limit = int(activity_limit)
        if not 1 <= limit <= MAX_RECENT_ACTIVITIES:
            raise GarminQueryError(
                "invalid_activity_limit",
                "activity_limit must be between 1 and 10",
            )
        selection = self.resolve_source(garmin_source_id)
        return _sanitize(
            _strip_training_presentation_leaks(
                training_overview_for_selection(
                    self.session,
                    source_selection=selection,
                    activity_limit=limit,
                )
            )
        )

    def dashboard(
        self,
        *,
        garmin_source_id: str | None = None,
        metric_code: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, Any]:
        selection = self.resolve_source(garmin_source_id)
        end = end_date or date.today()
        start = start_date or (end - timedelta(days=DEFAULT_WINDOW_DAYS - 1))
        metric = (metric_code or DEFAULT_SCALAR_METRIC).strip()
        payload: dict[str, Any] = {
            "source_selection": selection,
            "scalar_metrics": self.list_scalar_metrics(),
            "lag_eligible_metrics": self.list_lag_eligible_metrics(),
            "activity_comparison_metrics": self.list_activity_comparison_metrics(),
            "native_score_labels": self.native_score_labels(),
            "defaults": {
                "metric_code": metric,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "lag_days": [0, 1, 7],
                "max_series_calendar_days": MAX_SERIES_CALENDAR_DAYS,
                "max_lag_days": MAX_LAG_DAYS,
                "max_lag_count": MAX_LAG_COUNT,
                "min_selected_activities": MIN_SELECTED_ACTIVITIES,
                "max_selected_activities": MAX_SELECTED_ACTIVITIES,
                "recent_training_activities": DEFAULT_RECENT_ACTIVITIES,
                "max_recent_training_activities": MAX_RECENT_ACTIVITIES,
            },
            "wording": {
                "association": ASSOCIATION_WORDING,
                "activity": ACTIVITY_WORDING,
                "disclaimer": DASHBOARD_DISCLAIMER,
            },
            "series": None,
            "activities": [],
            "training_overview": _strip_training_presentation_leaks(
                training_overview_for_selection(
                    self.session,
                    source_selection=selection,
                    activity_limit=DEFAULT_RECENT_ACTIVITIES,
                )
            ),
            "unavailable_reason": selection.get("reason"),
        }
        if selection["status"] != "selected":
            return _sanitize(payload)

        selected_id = selection["selected_source_id"]
        assert selected_id is not None
        payload["activities"] = self.list_activities(garmin_source_id=selected_id)
        try:
            payload["series"] = self.scalar_series(
                garmin_source_id=selected_id,
                metric_code=metric,
                start_date=start,
                end_date=end,
            )
            payload["unavailable_reason"] = None
        except GarminQueryError as exc:
            payload["series"] = None
            payload["unavailable_reason"] = exc.code
            payload["series_error"] = {"code": exc.code, "message": exc.message}
        return _sanitize(payload)

    def empty_dashboard(self, *, reason: str = "no_data") -> dict[str, Any]:
        return unavailable_dashboard_payload(reason=reason)

    def _require_source_id(self, garmin_source_id: str) -> str:
        source_id = (garmin_source_id or "").strip()
        if not source_id:
            raise GarminQueryError(
                "missing_garmin_source_id",
                "garmin_source_id is required",
            )
        row = self.session.get(GarminSource, source_id)
        if row is None:
            raise GarminQueryError(
                "unknown_garmin_source_id",
                "garmin_source_id does not match a persisted Garmin source",
            )
        return row.id

    def _source_payload(self, row: GarminSource) -> dict[str, Any]:
        return {
            "id": row.id,
            "provider_code": row.provider_code,
            "source_kind": row.source_kind,
            "source_instance_id": row.source_instance_id,
            "device_attributed": bool(row.device_attributed),
            "device_code": row.device_code,
            "device_model": row.device_model,
        }

    def _activity_summary(self, row: GarminSourceRecord) -> dict[str, Any]:
        timestamp = restore_stored_utc(row.source_timestamp_utc)
        return {
            "record_id": row.id,
            "external_record_id": row.external_record_id,
            "activity_type": row.activity_type,
            "idempotency_key": row.idempotency_key,
            "stream_code": row.stream_code,
            "projection_status": row.projection_status,
            "source_local_date": (
                row.source_local_date.isoformat() if row.source_local_date is not None else None
            ),
            "temporal_precision": row.temporal_precision,
            "measured_at_utc": timestamp.isoformat() if timestamp is not None else None,
            "local_wall_time": row.local_wall_time,
            # Never invent UTC for local-only stamps.
            "zone_hint": (
                "utc"
                if timestamp is not None
                else ("local" if row.local_wall_time or row.source_local_date else "unknown")
            ),
        }

    def _present_scalar_result(self, body: dict[str, Any]) -> dict[str, Any]:
        metric = body.get("metric_definition") or {}
        code = metric.get("metric_code")
        presentation = PROVIDER_NATIVE_SCORE_LABELS.get(code or "")
        enriched = dict(body)
        if presentation:
            enriched["metric_presentation"] = {
                "display_name": presentation["display_name"],
                "kind": presentation["kind"],
                "semantics": presentation["semantics"],
                "wording": presentation["wording"],
                "provider_native": True,
            }
        else:
            enriched["metric_presentation"] = {
                "display_name": code,
                "kind": "reviewed_metric",
                "semantics": metric.get("window"),
                "wording": metric.get("description"),
                "provider_native": False,
            }
        enriched["garmin_source_id"] = (body.get("query") or {}).get("garmin_source_id")
        return _sanitize(enriched)

    def _present_activity_result(self, body: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(body)
        enriched["wording"] = ACTIVITY_WORDING
        enriched["native_score_labels"] = {
            code: PROVIDER_NATIVE_SCORE_LABELS[code]
            for code in ("training_effect", "acute_training_load")
            if code in PROVIDER_NATIVE_SCORE_LABELS
        }
        enriched["garmin_source_id"] = (body.get("query") or {}).get("garmin_source_id")
        return _sanitize(enriched)

    def _present_lag_result(self, body: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(body)
        enriched["wording"] = ASSOCIATION_WORDING
        enriched["garmin_source_id"] = (body.get("query") or {}).get("garmin_source_id")
        for banned in ("p_value", "significance", "best_lag", "causal", "prediction"):
            enriched.pop(banned, None)
        return _sanitize(enriched)



def unavailable_dashboard_payload(*, reason: str = "no_data") -> dict[str, Any]:
    """Honest no-data / DB-unavailable dashboard payload without a live session."""

    return _sanitize(
        {
            "source_selection": {
                "status": "no_data",
                "reason": reason,
                "selected_source_id": None,
                "sources": [],
            },
            "scalar_metrics": [
                _metric_presentation(definition)
                for code, definition in ANALYTIC_METRIC_REGISTRY.items()
                if code not in _COLLECTION_VALUED
            ],
            "lag_eligible_metrics": [
                _metric_presentation(definition)
                for code, definition in ANALYTIC_METRIC_REGISTRY.items()
                if metric_eligible_for_lagged_association(code)[0]
            ],
            "activity_comparison_metrics": [
                _metric_presentation(ANALYTIC_METRIC_REGISTRY[code])
                for code in ACTIVITY_COMPARISON_METRIC_CODES
                if code in ANALYTIC_METRIC_REGISTRY
            ],
            "native_score_labels": {
                code: dict(label)
                for code, label in sorted(PROVIDER_NATIVE_SCORE_LABELS.items())
            },
            "defaults": {
                "metric_code": DEFAULT_SCALAR_METRIC,
                "start_date": None,
                "end_date": None,
                "lag_days": [0, 1, 7],
                "max_series_calendar_days": MAX_SERIES_CALENDAR_DAYS,
                "max_lag_days": MAX_LAG_DAYS,
                "max_lag_count": MAX_LAG_COUNT,
                "min_selected_activities": MIN_SELECTED_ACTIVITIES,
                "max_selected_activities": MAX_SELECTED_ACTIVITIES,
                "recent_training_activities": DEFAULT_RECENT_ACTIVITIES,
                "max_recent_training_activities": MAX_RECENT_ACTIVITIES,
            },
            "wording": {
                "association": ASSOCIATION_WORDING,
                "activity": ACTIVITY_WORDING,
                "disclaimer": DASHBOARD_DISCLAIMER,
            },
            "series": None,
            "activities": [],
            "training_overview": _strip_training_presentation_leaks(
                unavailable_training_overview(reason=reason)
            ),
            "unavailable_reason": reason,
        }
    )


__all__ = [
    "ACTIVITY_WORDING",
    "ASSOCIATION_WORDING",
    "DASHBOARD_DISCLAIMER",
    "DEFAULT_SCALAR_METRIC",
    "PROVIDER_NATIVE_SCORE_LABELS",
    "GarminQueryError",
    "GarminQueryService",
    "unavailable_dashboard_payload",
]
