"""Explicit one-page Steps observations; never automatic sync or day coverage."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.exc import SQLAlchemyError

from healthcheck.config import Settings
from healthcheck.db.models import GooglePayloadStatus
from healthcheck.db.repositories import repositories_for
from healthcheck.google.auth import (
    GoogleAuthService,
    GoogleHttpTransport,
    GoogleOAuthError,
    UrllibGoogleHttpTransport,
)
from healthcheck.google.contracts import (
    FAMILY_GOOGLE_WEARABLES,
    GOOGLE_PROVIDER_CODE,
    GoogleQueryContext,
    GoogleQueryMode,
    GoogleSourceIdentity,
    GoogleSourceKind,
    GoogleStream,
    decode_count_sum_metric,
)
from healthcheck.google.identity import parse_steps_civil_endpoint
from healthcheck.google.normalization import (
    GoogleNormalizationDiagnostic,
    GoogleNormalizationResult,
    normalize_google_payload,
)
from healthcheck.google.persistence import google_persistence_for
from healthcheck.google.sync import _google_execution_resources

ACQUISITION_CONTRACT = "google-steps-acquisition-v1"
ACQUISITION_NORMALIZATION = "google-steps-acquisition-normalization-v1"
CONTEXT_CODE = "steps_acquisition_context"
STEPS_PATH = "/v4/users/me/dataTypes/steps/dataPoints:dailyRollUp"
STEPS_URL = "https://health.googleapis.com" + STEPS_PATH
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_REQUESTS = 3
RETRY_HTTP = frozenset({429, 500, 502, 503, 504})
QUERY = GoogleQueryContext(GoogleQueryMode.DAILY_ROLL_UP, FAMILY_GOOGLE_WEARABLES)
IDENTITY = GoogleSourceIdentity(GoogleSourceKind.FAMILY_AGGREGATE, FAMILY_GOOGLE_WEARABLES)


def _civil(day: date) -> dict:
    return {"date": {"year": day.year, "month": day.month, "day": day.day}}


@dataclass(frozen=True, slots=True)
class StepsPlan:
    day: date

    def __post_init__(self) -> None:
        if type(self.day) is not date or self.day == date.max:
            raise ValueError("one bounded civil date required")

    @classmethod
    def build(cls, day: str, family: str) -> StepsPlan:
        if family not in {"google-wearables", FAMILY_GOOGLE_WEARABLES}:
            raise ValueError("explicit google-wearables family required")
        if not isinstance(day, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day):
            raise ValueError("one explicit civil date required")
        parsed = date.fromisoformat(day)
        if parsed == date.max:
            raise ValueError("exclusive end must be representable")
        return cls(parsed)

    def body(self) -> dict:
        return {
            "range": {"start": _civil(self.day), "end": _civil(self.day + timedelta(days=1))},
            "windowSizeDays": 1,
            "pageSize": 1,
            "dataSourceFamily": FAMILY_GOOGLE_WEARABLES,
        }

    def context(self, requests: int) -> dict:
        return {
            "code": CONTEXT_CODE,
            "contract": ACQUISITION_CONTRACT,
            "method": "POST",
            "path": STEPS_PATH,
            "request": self.body(),
            "request_count": requests,
            "coverage": "unknown",
            "pagination": "unknown",
        }

    def preview(self) -> dict:
        return _report("planned", "explicit_apply_required", 0)


def validate_context(context: object) -> StepsPlan:
    """Reconstruct a request from immutable allowlisted provenance, never defaults."""
    if not isinstance(context, Mapping):
        raise ValueError("Steps acquisition context missing")
    try:
        request = context["request"]
        start = request["range"]["start"]["date"]
        day = date(start["year"], start["month"], start["day"])
        plan = StepsPlan.build(day.isoformat(), FAMILY_GOOGLE_WEARABLES)
        count = context["request_count"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Steps acquisition context invalid") from exc
    if (
        type(count) is not int
        or not 1 <= count <= MAX_REQUESTS
        or json.dumps(context, sort_keys=True, allow_nan=False)
        != json.dumps(plan.context(count), sort_keys=True, allow_nan=False)
    ):
        raise ValueError("Steps acquisition context invalid")
    return plan


def replay_context(diagnostics_json: str | None) -> dict:
    """Acquired observations cannot fall back to the offline-only contract."""
    try:
        values = json.loads(diagnostics_json or "null", object_pairs_hook=_unique_keys)
        if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
            raise ValueError("Steps acquisition diagnostics invalid")
        contexts = [value for value in values if value.get("code") == CONTEXT_CODE]
        if len(contexts) != 1:
            raise ValueError("Steps acquisition context missing or duplicate")
        validate_context(contexts[0])
        return contexts[0]
    except (ValueError, TypeError) as exc:
        raise ValueError("Steps acquisition replay requires valid immutable context") from exc


def _unique_keys(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("duplicate JSON key")
    return value


def normalize_acquired_steps(
    content: bytes,
    *,
    context: Mapping,
    query: GoogleQueryContext = QUERY,
    identity: GoogleSourceIdentity = IDENTITY,
    normalization_contract_version: str | None = None,
) -> GoogleNormalizationResult:
    plan = validate_context(context)
    if query != QUERY or identity.source_instance_id != FAMILY_GOOGLE_WEARABLES:
        raise ValueError("Steps acquisition source mismatch")
    result = normalize_google_payload(
        content,
        stream=GoogleStream.STEPS,
        query=query,
        source_identity=identity,
        source_contract_version=ACQUISITION_CONTRACT,
        normalization_contract_version=normalization_contract_version or ACQUISITION_NORMALIZATION,
        max_records=1,
    )
    mismatch = False
    for record in result.records:
        interval = record.interval
        try:
            start = parse_steps_civil_endpoint(json.loads(interval.start.raw_civil_json))[2]
            end = parse_steps_civil_endpoint(json.loads(interval.end.raw_civil_json))[2]
            expected = plan.body()["range"]
            mismatch |= (
                start != parse_steps_civil_endpoint(expected["start"])[2]
                or end != parse_steps_civil_endpoint(expected["end"])[2]
            )
        except (AttributeError, ValueError, TypeError):
            mismatch = True
    if len(content) > MAX_RESPONSE_BYTES or mismatch:
        return replace(
            result,
            status=GooglePayloadStatus.INVALID,
            records=(),
            diagnostics=(
                *result.diagnostics,
                GoogleNormalizationDiagnostic(
                    "steps_request_mismatch", "Steps response does not match the bounded request"
                ),
            ),
        )
    # An envelope failure never leaves a usable prefix.
    if result.status is GooglePayloadStatus.INVALID:
        return replace(result, records=())
    return result


def _report(status: str, reason: str, requests: int, **counts) -> dict:
    return {
        "contract_version": ACQUISITION_CONTRACT,
        "status": status,
        "reason": reason,
        "request_count": requests,
        "window_days": 1,
        "source_family": "google-wearables",
        "coverage": "unknown",
        "pagination": "unknown",
        "evidence_kind": "observed_interval",
        "limits": {
            "max_requests": MAX_REQUESTS,
            "max_response_bytes": MAX_RESPONSE_BYTES,
            "page_size": 1,
            "timeout_seconds": 30,
        },
        **counts,
    }


def acquire_steps(
    settings: Settings,
    plan: StepsPlan,
    *,
    auth_service: GoogleAuthService,
    transport: GoogleHttpTransport | None = None,
    sleeper=time.sleep,
    clock=lambda: datetime.now(UTC),
) -> dict:
    """Explicit apply only; cached grant preflight precedes runtime/DB/network."""
    # Validate direct callers too, before accessing credentials.
    StepsPlan.build(plan.day.isoformat(), FAMILY_GOOGLE_WEARABLES)
    token, auth = auth_service.load_steps_access_token()
    if not token or not auth.ok:
        return _report("blocked", "steps_grant_required", 0)
    http = transport or UrllibGoogleHttpTransport(max_response_bytes=MAX_RESPONSE_BYTES)
    response = None
    for attempt in range(MAX_REQUESTS):
        count = attempt + 1
        try:
            response = http.request(
                "POST",
                STEPS_URL,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                json_body=plan.body(),
                timeout=30.0,
            )
        except (OSError, GoogleOAuthError) as exc:
            # Never copy transport/provider text into diagnostics.
            if isinstance(exc, GoogleOAuthError) and exc.error_code != "provider_unavailable":
                return _report("failed", "transport_rejected", count)
            if count == MAX_REQUESTS:
                return _report("failed", "provider_unavailable", count)
        else:
            if response.status not in RETRY_HTTP:
                break
            if count == MAX_REQUESTS:
                return _report("failed", "retry_exhausted", count, http_status=response.status)
        sleeper((0.25, 0.5)[attempt])
    assert response is not None
    if not 200 <= response.status < 300:
        return _report(
            "blocked" if response.status in {401, 403} else "failed",
            "provider_rejected",
            count,
            http_status=response.status,
        )
    if not isinstance(response.body, bytes) or len(response.body) > MAX_RESPONSE_BYTES:
        return _report("failed", "response_limit", count)
    received_at = clock()
    context = plan.context(count)
    result = normalize_acquired_steps(response.body, context=context)
    try:
        with _google_execution_resources(settings) as resources, resources.factory() as session:
            repos = repositories_for(session)
            provider = repos.providers.get_or_create(
                GOOGLE_PROVIDER_CODE, "Google Health", "health_api"
            )
            run = repos.sync.create_run(provider_id=provider.id, stream_code=ACQUISITION_CONTRACT)
            repo = google_persistence_for(session, payload_store=resources.store)
            outcome = repo.persist_result(
                result,
                payload=response.body,
                received_at=received_at,
                sync_run_id=run.id,
                observation_diagnostics=(context,),
            )
            invalid = result.status in {GooglePayloadStatus.INVALID, GooglePayloadStatus.PARTIAL}
            repos.sync.finish_run(
                run.id,
                status="partial" if invalid else "succeeded",
                received_count=len(result.records),
                accepted_count=len(outcome.records),
                diagnostic_reason="observed_only_coverage_unknown",
            )
            session.commit()
    except (OSError, ValueError, SQLAlchemyError):
        return _report("failed", "persistence_failed", count)
    states: dict[str, int] = {}
    for record in result.records:
        state = decode_count_sum_metric(record.metrics[0]).state.value
        states[state] = states.get(state, 0) + 1
    return _report(
        "rejected" if invalid else "observed",
        "response_invalid" if invalid else "observed_only",
        count,
        record_count=len(result.records),
        metric_states=states,
    )
