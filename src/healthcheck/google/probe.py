"""Bounded Google Health capability probe with sanitized structural evidence only.

Does not persist google_* ingestion tables and never emits health values,
precise routine timestamps, point IDs, user IDs, tokens, or payload dumps.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Any
from urllib.parse import urlencode

from healthcheck.google.auth import (
    ALLOWED_SCOPES,
    SCOPE_METRICS,
    SCOPE_SETTINGS,
    SCOPE_SLEEP,
    GoogleAuthResult,
    GoogleAuthService,
    GoogleHttpResponse,
    GoogleHttpTransport,
    GoogleSafeError,
    classify_google_oauth_error,
)

PROBE_CONTRACT_VERSION = "r04-google-capability-spike-v1"
GOOGLE_PROVIDER_CODE = "google_health"
GOOGLE_API_ROOT = "https://health.googleapis.com/v4"
MAX_PROVIDER_REQUESTS = 16
MAX_PROBE_WINDOW_DAYS = 2
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Allowlisted structural field names only (never values).
_STRUCTURAL_KEYS = frozenset(
    {
        "dataPoints",
        "nextPageToken",
        "dataSource",
        "platform",
        "device",
        "recordingMethod",
        "dataSourceFamily",
        "name",
        "dataType",
        "pairedDevices",
        "manufacturer",
        "model",
        "type",
        "id",
    }
)

_SENSITIVE_KEY_EXACT = frozenset(
    {
        "access_token",
        "refresh_token",
        "client_secret",
        "client_id",
        "authorization",
        "cookie",
        "password",
        "secret",
        "bearer",
        "id_token",
    }
)
_SENSITIVE_KEY_FRAGMENTS = (
    "client_secret",
    "access_token",
    "refresh_token",
    "authorization",
    "password",
)


class GoogleProbeStatus(StrEnum):
    SUCCEEDED = "succeeded"
    EMPTY = "empty"
    FAILED = "failed"
    NOT_RUN = "not_run"
    SCOPE_REQUIRED = "scope_required"
    REAUTH_REQUIRED = "reauth_required"
    BUDGET_EXCEEDED = "budget_exceeded"


class GoogleRecordType(StrEnum):
    """Google Health filter record-type families used by the capability probe."""

    IDENTITY = "identity"
    PAIRED_DEVICES = "paired_devices"
    SLEEP_SESSION = "sleep_session"
    SAMPLE = "sample"
    DAILY = "daily"


@dataclass(frozen=True, slots=True)
class GoogleSurfaceSpec:
    code: str
    data_type: str
    operation: str  # list | identity | paired_devices
    required_scope: str
    display_name: str
    record_type: GoogleRecordType


SURFACE_SPECS: tuple[GoogleSurfaceSpec, ...] = (
    GoogleSurfaceSpec(
        "identity", "", "identity", SCOPE_METRICS, "Identity", GoogleRecordType.IDENTITY
    ),
    # users.pairedDevices.list requires settings.readonly; R04 does not request it.
    GoogleSurfaceSpec(
        "paired_devices",
        "",
        "paired_devices",
        SCOPE_SETTINGS,
        "Paired devices",
        GoogleRecordType.PAIRED_DEVICES,
    ),
    GoogleSurfaceSpec(
        "sleep", "sleep", "list", SCOPE_SLEEP, "Sleep", GoogleRecordType.SLEEP_SESSION
    ),
    GoogleSurfaceSpec(
        "heart_rate", "heart-rate", "list", SCOPE_METRICS, "Heart rate", GoogleRecordType.SAMPLE
    ),
    GoogleSurfaceSpec(
        "heart_rate_variability",
        "heart-rate-variability",
        "list",
        SCOPE_METRICS,
        "Heart rate variability",
        GoogleRecordType.SAMPLE,
    ),
    GoogleSurfaceSpec(
        "daily_heart_rate_variability",
        "daily-heart-rate-variability",
        "list",
        SCOPE_METRICS,
        "Daily heart rate variability",
        GoogleRecordType.DAILY,
    ),
    GoogleSurfaceSpec(
        "daily_resting_heart_rate",
        "daily-resting-heart-rate",
        "list",
        SCOPE_METRICS,
        "Daily resting heart rate",
        GoogleRecordType.DAILY,
    ),
    GoogleSurfaceSpec(
        "oxygen_saturation",
        "oxygen-saturation",
        "list",
        SCOPE_METRICS,
        "Oxygen saturation",
        GoogleRecordType.SAMPLE,
    ),
    GoogleSurfaceSpec(
        "daily_oxygen_saturation",
        "daily-oxygen-saturation",
        "list",
        SCOPE_METRICS,
        "Daily oxygen saturation",
        GoogleRecordType.DAILY,
    ),
    GoogleSurfaceSpec(
        "respiratory_rate_sleep_summary",
        "respiratory-rate-sleep-summary",
        "list",
        SCOPE_METRICS,
        "Respiratory rate sleep summary",
        GoogleRecordType.SAMPLE,
    ),
    GoogleSurfaceSpec(
        "daily_respiratory_rate",
        "daily-respiratory-rate",
        "list",
        SCOPE_METRICS,
        "Daily respiratory rate",
        GoogleRecordType.DAILY,
    ),
)


def validate_probe_window(values: Sequence[str] | None) -> tuple[str, str]:
    """Accept one day or an inclusive start/end spanning at most MAX_PROBE_WINDOW_DAYS."""

    if not values:
        raise ValueError("capability probe requires one or two dates")
    if len(values) > 2:
        raise ValueError("capability probe accepts at most two dates")
    parsed: list[date] = []
    for raw in values:
        if not isinstance(raw, str) or not _DATE_RE.fullmatch(raw):
            raise ValueError("capability probe dates must use YYYY-MM-DD")
        parsed.append(date.fromisoformat(raw))
    start = min(parsed)
    end = max(parsed)
    span = (end - start).days + 1
    if span > MAX_PROBE_WINDOW_DAYS:
        raise ValueError(f"capability probe window must be <= {MAX_PROBE_WINDOW_DAYS} days")
    # Exclusive upper bound for Google Health filters.
    exclusive_end = end + timedelta(days=1)
    return start.isoformat(), exclusive_end.isoformat()


def data_type_filter_identity(data_type: str) -> str:
    """Convert kebab-case URL data type to snake_case filter identity."""

    if not data_type or "/" in data_type or " " in data_type:
        raise ValueError("data type for filter identity is invalid")
    return data_type.replace("-", "_")


def build_data_point_filter(
    spec: GoogleSurfaceSpec,
    *,
    window_start: str,
    window_end_exclusive: str,
) -> str:
    """Build an inclusive-lower / exclusive-upper civil filter for one surface.

    Paths use kebab-case data types; filter identifiers use snake_case.
    """

    if spec.operation != "list" or not spec.data_type:
        raise ValueError("data-point filters are only defined for list surfaces")
    identity = data_type_filter_identity(spec.data_type)
    if spec.record_type is GoogleRecordType.SLEEP_SESSION:
        field = f"{identity}.interval.civil_end_time"
    elif spec.record_type is GoogleRecordType.SAMPLE:
        field = f"{identity}.sample_time.civil_time"
    elif spec.record_type is GoogleRecordType.DAILY:
        field = f"{identity}.date"
    else:
        raise ValueError(f"no list filter mapping for record type {spec.record_type}")
    return (
        f'{field} >= "{window_start}" AND '
        f'{field} < "{window_end_exclusive}"'
    )


def _is_sensitive_key(key: str) -> bool:
    lowered = key.casefold()
    if lowered in _SENSITIVE_KEY_EXACT:
        return True
    if lowered == "nextpagetoken":
        return False
    return any(fragment in lowered for fragment in _SENSITIVE_KEY_FRAGMENTS)


def summarize_structural_evidence(payload: Any, *, limit: int = 40) -> dict[str, Any]:
    """Return allowlisted structural evidence only; never owner health values."""

    field_names: set[str] = set()
    type_counts: dict[str, int] = {}
    string_encoded_numeric_fields = 0
    null_fields = 0
    missing_inferred_zero = False
    has_next_page_token = False
    data_point_count_state = "absent"
    platform_field_present = False
    device_field_present = False
    source_family_field_present = False

    def note_type(label: str) -> None:
        type_counts[label] = type_counts.get(label, 0) + 1

    def walk(value: Any, path: str = "") -> None:
        nonlocal string_encoded_numeric_fields, null_fields, has_next_page_token
        nonlocal data_point_count_state, platform_field_present, device_field_present
        nonlocal source_family_field_present
        if len(field_names) >= limit and not isinstance(value, (Mapping, list, tuple)):
            return
        if value is None:
            null_fields += 1
            note_type("null")
            return
        if isinstance(value, bool):
            note_type("bool")
            return
        if isinstance(value, int):
            note_type("int")
            return
        if isinstance(value, float):
            note_type("float")
            return
        if isinstance(value, str):
            note_type("string")
            # Detect string-encoded numerics without retaining the value.
            stripped = value.strip()
            if stripped and (
                stripped.isdigit()
                or (
                    stripped.replace(".", "", 1).isdigit()
                    and stripped.count(".") <= 1
                )
            ):
                string_encoded_numeric_fields += 1
            return
        if isinstance(value, Mapping):
            note_type("object")
            for key, child in value.items():
                if not isinstance(key, str):
                    continue
                if _is_sensitive_key(key):
                    continue
                key_l = key
                if key_l in _STRUCTURAL_KEYS or key_l in {
                    "dataPoints",
                    "nextPageToken",
                    "dataSource",
                    "platform",
                    "device",
                    "pairedDevices",
                }:
                    field_names.add(key_l)
                if key_l == "nextPageToken" and child not in (None, ""):
                    has_next_page_token = True
                if key_l == "dataPoints" and isinstance(child, list):
                    data_point_count_state = "empty" if len(child) == 0 else "non_empty"
                if key_l == "platform":
                    platform_field_present = True
                if key_l == "device":
                    device_field_present = True
                if key_l == "dataSourceFamily":
                    source_family_field_present = True
                # Never recurse into arrays of samples beyond structure flags.
                if key_l == "dataPoints" and isinstance(child, list):
                    if child:
                        first = child[0]
                        if isinstance(first, Mapping):
                            for nested_key, nested_val in first.items():
                                if not isinstance(nested_key, str) or _is_sensitive_key(nested_key):
                                    continue
                                if nested_key in _STRUCTURAL_KEYS or nested_key in {
                                    "dataSource",
                                    "name",
                                    "dataType",
                                }:
                                    field_names.add(nested_key)
                                if nested_key == "dataSource" and isinstance(nested_val, Mapping):
                                    if "platform" in nested_val:
                                        platform_field_present = True
                                        field_names.add("platform")
                                    if "device" in nested_val:
                                        device_field_present = True
                                        field_names.add("device")
                                # Count string-encoded numerics without retaining values.
                                stack = [nested_val]
                                while stack:
                                    current = stack.pop()
                                    if isinstance(current, str):
                                        stripped = current.strip()
                                        if stripped and (
                                            stripped.isdigit()
                                            or (
                                                stripped.replace(".", "", 1).isdigit()
                                                and stripped.count(".") <= 1
                                            )
                                        ):
                                            string_encoded_numeric_fields += 1
                                    elif isinstance(current, Mapping):
                                        stack.extend(current.values())
                                    elif isinstance(current, list):
                                        stack.extend(current[:3])
                    continue
                walk(child, f"{path}.{key_l}" if path else key_l)
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            note_type("array")
            if value:
                walk(value[0], path)
            return
        note_type(type(value).__name__)

    walk(payload)
    # Explicitly do not infer zero from absent fields.
    if data_point_count_state == "absent":
        missing_inferred_zero = False

    return {
        "field_names": sorted(field_names)[:limit],
        "type_counts": dict(sorted(type_counts.items())),
        "string_encoded_numeric_fields": string_encoded_numeric_fields,
        "null_fields": null_fields,
        "missing_inferred_zero": missing_inferred_zero,
        "has_next_page_token": has_next_page_token,
        "data_point_count_state": data_point_count_state,
        "platform_field_present": platform_field_present,
        "device_field_present": device_field_present,
        "source_family_field_present": source_family_field_present,
        "list_ordering_assumed": False,
    }


@dataclass(frozen=True, slots=True)
class GoogleCapabilityObservation:
    code: str
    display_name: str
    data_type: str
    operation: str
    required_scope: str
    scope_granted: bool | None
    request_succeeded: bool | None
    status: GoogleProbeStatus
    evidence: dict[str, Any]
    error: GoogleSafeError | None = None
    not_run_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "display_name": self.display_name,
            "data_type": self.data_type or None,
            "operation": self.operation,
            "required_scope": self.required_scope,
            "scope_granted": self.scope_granted,
            "request_succeeded": self.request_succeeded,
            "status": self.status.value,
            "evidence": self.evidence,
            "error": self.error.as_dict() if self.error else None,
            "not_run_reason": self.not_run_reason,
        }


@dataclass(frozen=True, slots=True)
class GoogleCapabilityReport:
    auth: GoogleAuthResult
    window_start: str
    window_end_exclusive: str
    request_count: int
    capabilities: tuple[GoogleCapabilityObservation, ...]
    abort_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": PROBE_CONTRACT_VERSION,
            "source": {"provider_code": GOOGLE_PROVIDER_CODE},
            "auth": self.auth.as_dict(),
            "probe": {
                "window_start": self.window_start,
                "window_end_exclusive": self.window_end_exclusive,
                "request_count": self.request_count,
                "max_provider_requests": MAX_PROVIDER_REQUESTS,
                "max_window_days": MAX_PROBE_WINDOW_DAYS,
                "abort_reason": self.abort_reason,
                "raw_payloads_retained": False,
                "database_writes": False,
                "list_ordering_assumed": False,
            },
            "privacy": {
                "raw_values_emitted": False,
                "private_identifiers_emitted": False,
                "tokens_emitted": False,
                "health_timestamps_emitted": False,
                "string_encoded_numerics_logged_as_values": False,
            },
            "capabilities": [item.as_dict() for item in self.capabilities],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=True, indent=2, sort_keys=True) + "\n"


class GoogleCapabilityProbe:
    """Owner-invoked bounded probe over fake or live injectable transport."""

    def __init__(
        self,
        auth_service: GoogleAuthService,
        *,
        transport: GoogleHttpTransport | None = None,
    ) -> None:
        self.auth_service = auth_service
        self.transport = transport or auth_service.transport
        self._request_count = 0

    def run(
        self,
        dates: Sequence[str],
        *,
        auth_result: GoogleAuthResult | None = None,
        granted_scopes: frozenset[str] | None = None,
    ) -> GoogleCapabilityReport:
        window_start, window_end = validate_probe_window(dates)
        auth = auth_result or self.auth_service.token_health()
        if not auth.ok:
            return self._not_run_report(auth, window_start, window_end, reason="auth_not_ready")

        access_token, live_auth = self.auth_service.load_access_token(refresh_if_needed=False)
        if not access_token or not live_auth.ok:
            return self._not_run_report(
                live_auth,
                window_start,
                window_end,
                reason="access_token_unavailable",
            )
        auth = live_auth

        scopes = granted_scopes
        if scopes is None:
            try:
                tokens = self.auth_service._read_tokens()
                scopes = tokens.granted_scopes()
            except Exception:
                scopes = ALLOWED_SCOPES

        observations: list[GoogleCapabilityObservation] = []
        abort_reason: str | None = None
        for spec in SURFACE_SPECS:
            scope_ok = spec.required_scope in scopes
            if not scope_ok:
                # Missing-scope surfaces (e.g. paired_devices needing settings.readonly)
                # stay explicit scope_required and never become generic reauth_required.
                observations.append(
                    GoogleCapabilityObservation(
                        code=spec.code,
                        display_name=spec.display_name,
                        data_type=spec.data_type,
                        operation=spec.operation,
                        required_scope=spec.required_scope,
                        scope_granted=False,
                        request_succeeded=None,
                        status=GoogleProbeStatus.SCOPE_REQUIRED,
                        evidence={},
                        not_run_reason="scope_required",
                    )
                )
                continue
            if self._request_count >= MAX_PROVIDER_REQUESTS:
                abort_reason = "request_ceiling"
                observations.append(
                    GoogleCapabilityObservation(
                        code=spec.code,
                        display_name=spec.display_name,
                        data_type=spec.data_type,
                        operation=spec.operation,
                        required_scope=spec.required_scope,
                        scope_granted=True,
                        request_succeeded=None,
                        status=GoogleProbeStatus.BUDGET_EXCEEDED,
                        evidence={},
                        not_run_reason="request_ceiling",
                    )
                )
                continue
            observation = self._probe_surface(
                spec,
                access_token=access_token,
                window_start=window_start,
                window_end=window_end,
            )
            observations.append(observation)
            if observation.status is GoogleProbeStatus.REAUTH_REQUIRED:
                abort_reason = "reauth_required"
                break

        return GoogleCapabilityReport(
            auth=auth,
            window_start=window_start,
            window_end_exclusive=window_end,
            request_count=self._request_count,
            capabilities=tuple(observations),
            abort_reason=abort_reason,
        )

    def _not_run_report(
        self,
        auth: GoogleAuthResult,
        window_start: str,
        window_end: str,
        *,
        reason: str,
    ) -> GoogleCapabilityReport:
        observations = tuple(
            GoogleCapabilityObservation(
                code=spec.code,
                display_name=spec.display_name,
                data_type=spec.data_type,
                operation=spec.operation,
                required_scope=spec.required_scope,
                scope_granted=None,
                request_succeeded=None,
                status=GoogleProbeStatus.NOT_RUN,
                evidence={},
                not_run_reason=reason,
            )
            for spec in SURFACE_SPECS
        )
        return GoogleCapabilityReport(
            auth=auth,
            window_start=window_start,
            window_end_exclusive=window_end,
            request_count=0,
            capabilities=observations,
            abort_reason=reason,
        )

    def _probe_surface(
        self,
        spec: GoogleSurfaceSpec,
        *,
        access_token: str,
        window_start: str,
        window_end: str,
    ) -> GoogleCapabilityObservation:
        try:
            response = self._request_surface(
                spec,
                access_token=access_token,
                window_start=window_start,
                window_end=window_end,
            )
        except Exception as exc:
            error = classify_google_oauth_error(exc)
            status = (
                GoogleProbeStatus.REAUTH_REQUIRED
                if error.error_code in {"invalid_grant", "authentication_failed"}
                else GoogleProbeStatus.FAILED
            )
            return GoogleCapabilityObservation(
                code=spec.code,
                display_name=spec.display_name,
                data_type=spec.data_type,
                operation=spec.operation,
                required_scope=spec.required_scope,
                scope_granted=True,
                request_succeeded=False,
                status=status,
                evidence={},
                error=error,
            )

        if response.status in {401, 403}:
            return GoogleCapabilityObservation(
                code=spec.code,
                display_name=spec.display_name,
                data_type=spec.data_type,
                operation=spec.operation,
                required_scope=spec.required_scope,
                scope_granted=True,
                request_succeeded=False,
                status=GoogleProbeStatus.REAUTH_REQUIRED,
                evidence={},
                error=GoogleSafeError("authentication", "authentication_failed", response.status),
            )
        if response.status >= 400:
            return GoogleCapabilityObservation(
                code=spec.code,
                display_name=spec.display_name,
                data_type=spec.data_type,
                operation=spec.operation,
                required_scope=spec.required_scope,
                scope_granted=True,
                request_succeeded=False,
                status=GoogleProbeStatus.FAILED,
                evidence={},
                error=GoogleSafeError("provider", "provider_error", response.status),
            )
        try:
            payload = response.json()
        except Exception:
            return GoogleCapabilityObservation(
                code=spec.code,
                display_name=spec.display_name,
                data_type=spec.data_type,
                operation=spec.operation,
                required_scope=spec.required_scope,
                scope_granted=True,
                request_succeeded=False,
                status=GoogleProbeStatus.FAILED,
                evidence={},
                error=GoogleSafeError("provider", "response_invalid", response.status),
            )
        evidence = summarize_structural_evidence(payload)
        empty = evidence.get("data_point_count_state") == "empty" or (
            spec.operation in {"identity", "paired_devices"}
            and not evidence.get("field_names")
        )
        if spec.operation == "paired_devices":
            empty = evidence.get("data_point_count_state") in {"empty", "absent"} and (
                not evidence.get("device_field_present")
            )
        if empty and spec.operation == "list":
            status = GoogleProbeStatus.EMPTY
        else:
            status = GoogleProbeStatus.SUCCEEDED
        if spec.operation == "list" and evidence.get("data_point_count_state") == "empty":
            status = GoogleProbeStatus.EMPTY
        elif spec.operation == "list" and evidence.get("data_point_count_state") == "non_empty":
            status = GoogleProbeStatus.SUCCEEDED
        elif spec.operation == "list" and evidence.get("data_point_count_state") == "absent":
            # Absent is not inferred as zero/empty health; report succeeded structural read.
            status = GoogleProbeStatus.SUCCEEDED
        return GoogleCapabilityObservation(
            code=spec.code,
            display_name=spec.display_name,
            data_type=spec.data_type,
            operation=spec.operation,
            required_scope=spec.required_scope,
            scope_granted=True,
            request_succeeded=True,
            status=status,
            evidence=evidence,
        )

    def _request_surface(
        self,
        spec: GoogleSurfaceSpec,
        *,
        access_token: str,
        window_start: str,
        window_end: str,
    ) -> GoogleHttpResponse:
        if self._request_count >= MAX_PROVIDER_REQUESTS:
            raise RuntimeError("request ceiling")
        self._request_count += 1
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        if spec.operation == "identity":
            # users.getIdentity — not GET /users/me.
            url = f"{GOOGLE_API_ROOT}/users/me/identity"
            return self.transport.request("GET", url, headers=headers)
        if spec.operation == "paired_devices":
            # Only reachable when settings.readonly is granted; R04 does not request it.
            url = f"{GOOGLE_API_ROOT}/users/me/pairedDevices"
            return self.transport.request("GET", url, headers=headers)
        filter_value = build_data_point_filter(
            spec,
            window_start=window_start,
            window_end_exclusive=window_end,
        )
        query = urlencode({"filter": filter_value, "pageSize": "25"})
        url = (
            f"{GOOGLE_API_ROOT}/users/me/dataTypes/{spec.data_type}/dataPoints?{query}"
        )
        return self.transport.request("GET", url, headers=headers)


__all__ = [
    "GOOGLE_PROVIDER_CODE",
    "MAX_PROBE_WINDOW_DAYS",
    "MAX_PROVIDER_REQUESTS",
    "PROBE_CONTRACT_VERSION",
    "SURFACE_SPECS",
    "GoogleCapabilityObservation",
    "GoogleCapabilityProbe",
    "GoogleCapabilityReport",
    "GoogleProbeStatus",
    "GoogleRecordType",
    "GoogleSurfaceSpec",
    "build_data_point_filter",
    "data_type_filter_identity",
    "summarize_structural_evidence",
    "validate_probe_window",
]
