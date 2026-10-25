"""Explicit bounded exercise acquisition using the existing Google HTTP boundary.

No new transport, consent flow, scheduler, migration or historical sync engine.
Partial runs restart from the first page; provider identities/revisions make the
saved projections repeat-safe. Query exhaustion never means complete history.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.db.engine import create_session_factory, create_sqlite_engine
from healthcheck.db.migration_guard import ACCEPTED_MIGRATION_HEAD
from healthcheck.db.models import GoogleSourceRecord
from healthcheck.db.repositories import canonical_json, repositories_for
from healthcheck.external_runtime_lock import ExternalRuntimeOperationLock
from healthcheck.google.auth import GoogleOAuthError, UrllibGoogleHttpTransport
from healthcheck.google.contracts import GOOGLE_PROVIDER_CODE, GooglePayloadStatus
from healthcheck.google.exercise import (
    ACQUISITION_CONTRACT,
    CONTRACT,
    MAX_PAGE_BYTES,
    MAX_PAGE_RECORDS,
    QUERY,
    _unique_keys,
    normalize_exercise_payload,
)
from healthcheck.google.normalization import GoogleNormalizationDiagnostic
from healthcheck.google.persistence import GooglePersistenceRepository
from healthcheck.google.sync import query_level_source_identity, source_identity_from_point
from healthcheck.runtime import resolve_runtime_paths

PATH = "/v4/users/me/dataTypes/exercise/dataPoints"
URL = "https://health.googleapis.com" + PATH
MAX_DAYS = 14
MAX_PAGES = 4
MAX_ATTEMPTS = 3
MAX_REQUESTS = MAX_PAGES * MAX_ATTEMPTS
MAX_TOKEN_BYTES = 8192
CONTEXT_CODE = "exercise_acquisition_context"


@dataclass(frozen=True, slots=True)
class ExerciseImportPlan:
    start: date
    end: date

    def __post_init__(self):
        if (
            type(self.start) is not date
            or type(self.end) is not date
            or self.end == date.max
            or not 0 <= (self.end - self.start).days < MAX_DAYS
        ):
            raise ValueError("exercise requires 1-14 explicit civil dates")

    @classmethod
    def build(cls, start, end, family):
        if family not in {"google-wearables", QUERY.data_source_family}:
            raise ValueError("explicit google-wearables family required")
        if not isinstance(start, str) or not isinstance(end, str):
            raise ValueError("explicit exercise window required")
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if first.isoformat() != start or last.isoformat() != end:
            raise ValueError("exercise dates must be canonical")
        return cls(first, last)

    def params(self):
        return {
            "filter": f'exercise.interval.civil_start_time >= "{self.start}" AND '
            f'exercise.interval.civil_start_time < "{self.end + timedelta(days=1)}"',
            "pageSize": str(MAX_PAGE_RECORDS),
            "dataSourceFamily": QUERY.data_source_family,
        }

    def context(self, page_index, request_count):
        return {
            "code": CONTEXT_CODE,
            "contract": ACQUISITION_CONTRACT,
            "method": "GET",
            "path": PATH,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "request": self.params(),
            "page_index": page_index,
            "request_count": request_count,
            "coverage": "unknown",
            "finality": "unknown",
        }

    def preview(self):
        return _report(self, "planned", "explicit_apply_required", 0, 0)


def validate_context(context):
    try:
        plan = ExerciseImportPlan.build(context["start"], context["end"], QUERY.data_source_family)
        page_index, count = context["page_index"], context["request_count"]
        if (
            type(page_index) is not int
            or not 1 <= page_index <= MAX_PAGES
            or type(count) is not int
            or not page_index <= count <= page_index * MAX_ATTEMPTS
            or canonical_json(context) != canonical_json(plan.context(page_index, count))
        ):
            raise ValueError("exercise acquisition context invalid")
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise ValueError("exercise acquisition context invalid") from exc
    return plan


def replay_context(diagnostics_json):
    try:
        values = json.loads(diagnostics_json, object_pairs_hook=_unique_keys)
        if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
            raise ValueError("exercise context invalid")
        contexts = [v for v in values if v.get("code") == CONTEXT_CODE]
        if len(contexts) != 1:
            raise ValueError("exercise context missing or duplicate")
        validate_context(contexts[0])
        return contexts[0]
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("exercise acquisition replay requires immutable context") from exc


def _page_results(content, context):
    plan = validate_context(context)
    fallback = query_level_source_identity(QUERY)
    identities = {fallback.source_instance_id: fallback}
    bad_cursor = False
    try:
        page = json.loads(content, object_pairs_hook=_unique_keys)
        points = page.get("dataPoints", [])
        cursor = page.get("nextPageToken", "")
        bad_cursor = isinstance(cursor, str) and len(cursor.encode("utf-8")) > MAX_TOKEN_BYTES
        if isinstance(points, list) and 0 < len(points) <= MAX_PAGE_RECORDS:
            identities = {}
            for point in points:
                identity = source_identity_from_point(point, QUERY)
                identities[identity.source_instance_id] = identity
    except (ValueError, TypeError, AttributeError, RecursionError):
        pass
    results = tuple(
        normalize_exercise_payload(content, source_identity=identities[k])
        for k in sorted(identities)
    )
    mismatch = (
        bad_cursor
        or any(result.status is GooglePayloadStatus.INVALID for result in results)
        or any(
            record.temporal.local_date is None
            or not plan.start <= record.temporal.local_date <= plan.end
            for result in results
            for record in result.records
        )
    )
    if mismatch:
        return tuple(
            replace(
                r,
                status=GooglePayloadStatus.INVALID,
                records=(),
                source_contract_version=ACQUISITION_CONTRACT,
                diagnostics=(
                    GoogleNormalizationDiagnostic(
                        "exercise_request_mismatch",
                        "Exercise page cannot satisfy the bounded request",
                    ),
                ),
            )
            for r in results
        )
    return tuple(replace(r, source_contract_version=ACQUISITION_CONTRACT) for r in results)


def normalize_acquired_exercise(
    content, *, context, identity, query=QUERY, normalization_contract_version=None
):
    if query != QUERY or normalization_contract_version not in {None, CONTRACT}:
        raise ValueError("unsupported exercise acquisition replay partition")
    results = _page_results(content, context)
    for result in results:
        if result.source_identity.source_instance_id == identity.source_instance_id:
            return replace(result, source_identity=identity)
    raise ValueError("exercise acquisition replay source mismatch")


def _report(plan, status, reason, request_count, page_count, *, query_exhausted=False, **counts):
    return {
        "contract_version": ACQUISITION_CONTRACT,
        "status": status,
        "reason": reason,
        "request_count": request_count,
        "page_count": page_count,
        "window_days": (plan.end - plan.start).days + 1,
        "source_family": "google-wearables",
        "query_exhausted": query_exhausted,
        "coverage": "unknown",
        "finality": "unknown",
        "provider_history_complete": False,
        "restart": "first_page",
        "limits": {
            "max_pages": MAX_PAGES,
            "max_requests": MAX_REQUESTS,
            "max_page_bytes": MAX_PAGE_BYTES,
            "page_size": MAX_PAGE_RECORDS,
            "timeout_seconds": 30,
        },
        **counts,
    }


def _validate_profile(paths):
    if not paths.root.is_dir() or not paths.config.is_file() or not paths.database.is_file():
        return False
    # Read-only metadata preflight; no prepare_runtime, PRAGMA mutation or migration.
    with closing(sqlite3.connect(paths.database.as_uri() + "?mode=ro", uri=True)) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        journal = connection.execute("PRAGMA journal_mode").fetchone()[0]
    return revision == [(ACCEPTED_MIGRATION_HEAD,)] and journal == "wal"


def acquire_exercise(
    settings,
    plan,
    *,
    auth_service,
    transport=None,
    sleeper=time.sleep,
    clock=lambda: datetime.now(UTC),
):
    """Owner-invoked command only; no consent, default stream or schedule change."""
    ExerciseImportPlan(plan.start, plan.end)
    paths = resolve_runtime_paths(settings)
    if not paths.root.is_dir() or not paths.config.is_file() or not paths.database.is_file():
        return _report(plan, "blocked", "established_profile_required", 0, 0)
    # Existing strict three-scope cached-only path; never starts browser consent.
    token, auth = auth_service.load_steps_access_token()
    if not token or not auth.ok:
        return _report(plan, "blocked", "activity_grant_required", 0, 0)
    with ExternalRuntimeOperationLock(paths, allow_reentrant=False):
        try:
            if not _validate_profile(paths):
                return _report(plan, "blocked", "current_schema_required", 0, 0)
        except (OSError, sqlite3.Error):
            return _report(plan, "blocked", "profile_unavailable", 0, 0)
        http = transport or auth_service.transport
        if isinstance(http, UrllibGoogleHttpTransport) and (
            http.max_response_bytes is None or http.max_response_bytes > MAX_PAGE_BYTES
        ):
            return _report(plan, "blocked", "bounded_transport_required", 0, 0)
        token, auth = auth_service.load_steps_access_token(refresh_if_needed=True)
        if not token or not auth.ok:
            return _report(plan, "blocked", "startup_auth_failed", 0, 0)
        result = _import_locked(settings, plan, token, http, sleeper, clock)
        return {
            **result,
            "auth_refresh_attempted": auth.refresh_attempted,
            "auth_refresh_succeeded": auth.refresh_succeeded,
        }


def _import_locked(settings, plan, token, http, sleeper, clock):
    from healthcheck.google.storage import ContentAddressedGooglePayloadStore

    engine = create_sqlite_engine(resolve_runtime_paths(settings))
    factory = create_session_factory(engine)
    store = ContentAddressedGooglePayloadStore(resolve_runtime_paths(settings).root / "artifacts")
    count = pages = observed = inserted = updated = partial_records = 0
    run_id = None
    final_report = None
    involved_ids = set()

    def report(reason, *, exhausted=False, blocked=False):
        nonlocal final_report
        try:
            with factory() as session:
                states = list(
                    session.execute(
                        select(
                            GoogleSourceRecord.record_status, GoogleSourceRecord.projection_status
                        ).where(GoogleSourceRecord.id.in_(involved_ids))
                    )
                )
            usable = sum(
                state in {"ok", "partial"} and projection == "current"
                for state, projection in states
            )
            unavailable = len(states) - usable
            if len(states) != len(involved_ids):
                usable = unavailable = None
        except SQLAlchemyError:
            usable = unavailable = None
        status = (
            "observed" if exhausted else "partial" if pages else "blocked" if blocked else "failed"
        )
        if exhausted and (unavailable is None or unavailable > 0):
            status = "partial"
            reason = "query_exhausted_current_unavailable"
        final_report = _report(
            plan,
            status,
            reason,
            count,
            pages,
            query_exhausted=exhausted,
            observed_count=observed,
            inserted_count=inserted,
            updated_count=updated,
            partial_record_count=partial_records,
            current_record_count=len(involved_ids),
            current_usable_count=usable,
            current_unavailable_count=unavailable,
        )
        return final_report

    try:
        with factory() as session:
            repos = repositories_for(session)
            provider = repos.providers.get_or_create(
                GOOGLE_PROVIDER_CODE, "Google Health", "health_api"
            )
            run = repos.sync.create_run(provider_id=provider.id, stream_code=ACQUISITION_CONTRACT)
            run_id = run.id
            session.commit()
        next_token, seen = None, set()
        for page_index in range(1, MAX_PAGES + 1):
            params = plan.params()
            if next_token is not None:
                params["pageToken"] = next_token
            for attempt in range(MAX_ATTEMPTS):
                if count >= MAX_REQUESTS:
                    return report("request_limit")
                count += 1
                try:
                    response = http.request(
                        "GET",
                        URL + "?" + urlencode(params),
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                        timeout=30.0,
                    )
                except (OSError, GoogleOAuthError) as exc:
                    if (
                        isinstance(exc, GoogleOAuthError)
                        and exc.error_code != "provider_unavailable"
                    ):
                        return report("transport_rejected")
                    if attempt + 1 == MAX_ATTEMPTS:
                        return report("provider_unavailable")
                else:
                    if response.status not in {500, 502, 503, 504}:
                        break
                    if attempt + 1 == MAX_ATTEMPTS:
                        return report("retry_exhausted")
                sleeper((0.25, 0.5)[attempt])
            if response.status in {401, 403}:
                return report("provider_rejected", blocked=True)
            if response.status == 429:
                return report("rate_limited")
            if response.status != 200:
                return report("provider_failed")
            content = response.body
            if not isinstance(content, bytes) or len(content) > MAX_PAGE_BYTES:
                return report("response_limit")
            context = plan.context(page_index, count)
            results = _page_results(content, context)
            invalid = any(r.status is GooglePayloadStatus.INVALID for r in results)
            with factory() as session:
                repo = GooglePersistenceRepository(session, payload_store=store)
                outcomes = [
                    repo.persist_result(
                        r,
                        payload=content,
                        received_at=clock(),
                        sync_run_id=run_id,
                        observation_diagnostics=(context,),
                    )
                    for r in results
                ]
                session.commit()
            if invalid:
                return report("response_invalid")
            involved_ids.update(row.id for outcome in outcomes for row in outcome.records)
            pages += 1
            observed += sum(len(r.records) for r in results)
            inserted += sum(o.inserted_count for o in outcomes)
            updated += sum(o.updated_count for o in outcomes)
            partial_records += sum(
                r.status is GooglePayloadStatus.PARTIAL
                for result in results
                for r in result.records
            )
            page = json.loads(content, object_pairs_hook=_unique_keys)
            next_token = page.get("nextPageToken", "")
            if not next_token:
                return report("query_exhausted_coverage_unknown", exhausted=True)
            if len(next_token.encode("utf-8")) > MAX_TOKEN_BYTES:
                return report("continuation_limit")
            if next_token in seen:
                return report("continuation_cycle")
            seen.add(next_token)
        return report("page_limit")
    except KeyboardInterrupt:
        return report("interrupted")
    except (OSError, ValueError, SQLAlchemyError, RecursionError):
        return report("persistence_failed")
    except Exception:
        # No arbitrary exception/provider text or authenticated URL reaches CLI.
        return report("request_failed")
    finally:
        # Completion is an attempt audit, never a coverage/cursor checkpoint.
        try:
            if run_id is not None:
                with factory() as session:
                    repositories_for(session).sync.finish_run(
                        run_id,
                        status="succeeded"
                        if final_report and final_report["status"] == "observed"
                        else "partial"
                        if pages
                        else "failed",
                        received_count=observed,
                        accepted_count=final_report["current_usable_count"]
                        if final_report
                        else None,
                        diagnostic_reason="exercise_observations_coverage_unknown",
                    )
                    session.commit()
        except Exception:
            if final_report is not None:
                final_report.update(
                    status="partial" if pages else "failed",
                    reason="attempt_audit_failed",
                    query_exhausted=False,
                )
        finally:
            engine.dispose()
