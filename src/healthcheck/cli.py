"""Direct troubleshooting and Windows-launcher commands."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import uvicorn
from sqlalchemy.exc import SQLAlchemyError

from healthcheck.analytics.sleep_agreement import PersistedSleepAgreementService
from healthcheck.analytics.sleep_agreement_report import SleepAgreementReportService
from healthcheck.analytics.sleep_metrics import read_persisted_sleep_metric_projection
from healthcheck.analytics.sleep_pairing import (
    ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS,
    SleepPairingQuery,
)
from healthcheck.config import Settings
from healthcheck.context import (
    ContextConflictError,
    ContextRevisionView,
    ContextService,
    ContextValidationError,
    parse_date_only,
    parse_interval,
    parse_timestamp,
)
from healthcheck.db.engine import (
    create_session_factory,
    create_sqlite_engine,
    migrate_database,
    session_scope,
)
from healthcheck.demo import DemoSeedError, seed_demo
from healthcheck.external_runtime_lock import (
    ExternalRuntimeOperationBusyError,
    ExternalRuntimeOperationLock,
    ExternalRuntimeOperationLockError,
)
from healthcheck.garmin.auth import GarminAuthService
from healthcheck.garmin.backfill import GarminHistoricalBackfill, plan_garmin_historical_backfill
from healthcheck.garmin.probe import GarminCapabilityProbe, validate_probe_dates
from healthcheck.garmin.redaction import redact_garmin_payload, validate_external_export_paths
from healthcheck.garmin.reprocess import (
    MAX_REPROCESS_OBSERVATIONS,
    GarminCollectionReprocessor,
)
from healthcheck.garmin.sync import GarminIncrementalSync, GarminSyncStatus
from healthcheck.garmin.training import (
    TRAINING_CONTRACT_VERSION,
    GarminTrainingSync,
    validate_training_window,
)
from healthcheck.garmin.training_probe import (
    TRAINING_PROBE_CONTRACT_VERSION,
    GarminTrainingPhaseAProbe,
    validate_training_probe_request,
)
from healthcheck.google.auth import GoogleAuthService
from healthcheck.google.backfill import (
    GoogleHistoricalBackfill,
    plan_google_historical_backfill,
)
from healthcheck.google.diagnostics import diagnose_latest_invalid_google_envelope
from healthcheck.google.probe import GoogleCapabilityProbe, validate_probe_window
from healthcheck.google.sync import (
    GoogleHealthSync,
    GoogleRunKind,
    GoogleSyncStatus,
    run_google_refresh,
)
from healthcheck.ingestion.openscale.binding import evaluate_ingest_binding
from healthcheck.logging import configure_logging, log_event
from healthcheck.owner_refresh import (
    OwnerRefreshBusyError,
    OwnerRefreshRuntimeError,
    OwnerRefreshStatus,
    require_established_runtime,
    run_owner_refresh,
)
from healthcheck.profile_backup import (
    ProfileBackupError,
    create_backup,
    restore_profile,
    verify_backup,
)
from healthcheck.runtime import prepare_runtime, resolve_runtime_paths
from healthcheck.sync_run_recovery import (
    SyncRunRecoveryRuntimeError,
    recover_stale_sync_runs,
)
from healthcheck.uat import format_smoke_results, run_smoke, smoke_exit_code
from healthcheck.web.ingest_app import create_ingest_app
from healthcheck.web.ui_app import create_ui_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="healthcheck")
    parser.add_argument(
        "command",
        choices=(
            "prepare-runtime",
            "migrate",
            "serve",
            "seed-demo",
            "smoke",
            "backup-profile",
            "verify-backup",
            "restore-profile",
            "garmin-auth",
            "garmin-capabilities",
            "garmin-training-phase-a",
            "garmin-training-sync",
            "garmin-redact",
            "garmin-sync",
            "garmin-backfill",
            "garmin-reprocess",
            "google-auth",
            "google-capabilities",
            "google-sync",
            "google-backfill",
            "google-refresh",
            "owner-refresh",
            "sync-run-recovery",
            "google-diagnose-terminal",
            "period-brief",
            "sleep-agreement-build",
            "context-add",
            "context-list",
            "context-revise",
        ),
    )
    parser.add_argument("--app", choices=("ui", "ingest"), default="ui")
    parser.add_argument("--data-dir")
    parser.add_argument("--port", type=int)
    parser.add_argument("--host")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--ui-url", default="http://127.0.0.1:8120")
    parser.add_argument("--ingest-url")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--output", help="output path")
    parser.add_argument("--backup", help="backup archive path")
    parser.add_argument("--target-dir", help="explicit restore target profile")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--force-reauth", action="store_true")
    parser.add_argument("--is-cn", action="store_true")
    parser.add_argument("--date", action="append", dest="dates")
    parser.add_argument("--max-range", action="append", nargs=2, dest="max_ranges")
    parser.add_argument("--max-date")
    parser.add_argument("--activity-start")
    parser.add_argument("--activity-end")
    parser.add_argument("--activity-id", action="append", dest="activity_ids")
    parser.add_argument("--repeat-date")
    parser.add_argument("--trailing-window-days", type=int)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--stream", action="append", dest="streams")
    parser.add_argument("--chunk-days", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--cutoff")
    parser.add_argument("--reprocess", action="store_true")
    parser.add_argument("--max-observations", type=int)
    parser.add_argument("--input")
    parser.add_argument("--family")
    parser.add_argument("--query-mode")
    parser.add_argument(
        "--cohort",
        default=ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS,
        help="sleep pairing cohort (default: account_wearables_sleep_observations_v1)",
    )
    parser.add_argument("--timestamp")
    parser.add_argument("--timezone")
    parser.add_argument("--text")
    parser.add_argument("--tag", action="append", dest="tags")
    parser.add_argument("--source", choices=("cli", "manual"), default="cli")
    parser.add_argument("--event-id")
    parser.add_argument("--operation-id")
    parser.add_argument("--from", dest="from_date")
    parser.add_argument("--to", dest="to_date")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--clear-tags", action="store_true")
    return parser


def _settings(args: argparse.Namespace) -> Settings:
    values = {}
    if args.data_dir is not None:
        values["data_dir"] = args.data_dir
    if args.port is not None:
        values["ui_port" if args.app == "ui" else "ingest_port"] = args.port
    if args.host is not None:
        values["ingest_host"] = args.host
    return Settings(**values)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "smoke":
        if args.timeout <= 0:
            print("smoke: --timeout must be positive", file=sys.stderr)
            return 2
        results = run_smoke(
            ui_url=args.ui_url,
            ingest_url=args.ingest_url,
            timeout=args.timeout,
        )
        print(format_smoke_results(results))
        return smoke_exit_code(results)

    if args.command == "backup-profile":
        if not args.output:
            print("backup-profile: --output is required", file=sys.stderr)
            return 2
        try:
            result = create_backup(Settings(data_dir=args.data_dir).data_dir, args.output)
        except (ProfileBackupError, OSError) as exc:
            print(f"backup-profile: ERROR: {exc}", file=sys.stderr)
            return 2
        print(
            f"backup-profile: verified archive created; {result.file_count} files; "
            f"classification={result.classification}"
        )
        return 0

    if args.command == "verify-backup":
        if not args.backup:
            print("verify-backup: --backup is required", file=sys.stderr)
            return 2
        try:
            result = verify_backup(args.backup)
        except (ProfileBackupError, OSError) as exc:
            print(f"verify-backup: ERROR: {exc}", file=sys.stderr)
            return 2
        print(
            f"verify-backup: OK; {result.file_count} files; classification={result.classification}"
        )
        return 0

    if args.command == "restore-profile":
        if not args.backup or not args.target_dir:
            print("restore-profile: --backup and --target-dir are required", file=sys.stderr)
            return 2
        try:
            result = restore_profile(args.backup, args.target_dir, replace=args.replace)
        except (ProfileBackupError, OSError) as exc:
            print(f"restore-profile: ERROR: {exc}", file=sys.stderr)
            return 2
        action = "replaced" if result.replaced else "restored"
        print(
            f"restore-profile: {action}; {result.file_count} files; "
            f"classification={result.classification}"
        )
        return 0

    if args.command == "garmin-redact":
        return _run_garmin_redact(args)
    if args.command == "period-brief":
        return _run_period_brief(args)
    if args.command == "sleep-agreement-build":
        return _run_sleep_agreement_build(args, _settings(args))
    if args.command in {"context-add", "context-list", "context-revise"}:
        return _run_context(args, _settings(args))

    settings = _settings(args)
    if args.command == "garmin-auth":
        return _run_garmin_auth(args, settings)
    if args.command == "garmin-capabilities":
        return _run_garmin_capabilities(args, settings)
    if args.command == "garmin-training-phase-a":
        return _run_garmin_training_phase_a(args, settings)
    if args.command == "garmin-training-sync":
        return _run_garmin_training_sync(args, settings)
    if args.command == "google-auth":
        return _run_google_auth(args, settings)
    if args.command == "google-capabilities":
        return _run_google_capabilities(args, settings)
    if args.command == "google-sync":
        return _run_google_sync(args, settings)
    if args.command == "google-backfill":
        return _run_google_backfill(args, settings)
    if args.command == "google-refresh":
        return _run_google_refresh(args, settings)
    if args.command == "owner-refresh":
        return _run_owner_refresh(args, settings)
    if args.command == "sync-run-recovery":
        return _run_sync_run_recovery(args, settings)
    if args.command == "google-diagnose-terminal":
        return _run_google_diagnose_terminal(args, settings)
    if args.command == "garmin-sync":
        return _run_garmin_sync(args, settings)
    if args.command == "garmin-backfill":
        return _run_garmin_backfill(args, settings)
    if args.command == "garmin-reprocess":
        return _run_garmin_reprocess(args, settings)
    if args.command == "seed-demo":
        try:
            result = seed_demo(settings, reset=args.reset)
        except (DemoSeedError, ValueError) as exc:
            print(f"seed-demo: ERROR: {exc}", file=sys.stderr)
            return 2
        action = "created" if result.created else "already ready"
        reset_note = " after explicit reset" if result.reset else ""
        print(
            f"seed-demo: {action}{reset_note}; synthetic data only; "
            f"{result.weigh_in_count} weigh-ins, {result.candidate_count} candidates"
        )
        return 0

    paths = prepare_runtime(settings)

    if args.command == "prepare-runtime":
        print(paths.root)
        return 0

    configure_logging(paths.logs, settings.log_level)
    if args.command == "migrate":
        migrate_database(paths)
        log_event("runtime_migration_ready", operation="migrate", status="ok")
        return 0

    if args.app == "ui":
        app, _ = create_ui_app(settings)
        host = "127.0.0.1"
        port = settings.ui_port
        service = "loopback-ui"
    else:
        decision = evaluate_ingest_binding(
            settings.ingest_host,
            trusted_private_lan_http=settings.trusted_private_lan_http,
        )
        if not decision.allowed:
            log_event(
                "ingest_bind_rejected",
                operation="serve",
                service="ingest",
                status="error",
                reason=decision.reason_code,
            )
            print(decision.message, file=sys.stderr)
            return 1
        if decision.requires_plain_http_warning:
            log_event(
                "ingest_plain_http_warning",
                operation="serve",
                service="ingest",
                status="ok",
                reason=decision.reason_code,
            )
            print(decision.message, file=sys.stderr)
        app, _ = create_ingest_app(settings)
        host = settings.ingest_host
        port = settings.ingest_port
        service = "ingest"
    log_event("runtime_starting", operation="serve", service=service, status="ok")
    uvicorn.run(app, host=host, port=port, log_config=None)
    return 0


def _context_temporal_from_args(args: argparse.Namespace, *, optional: bool = False):
    dates = tuple(args.dates or ())
    has_interval = args.start is not None or args.end is not None
    selected = int(bool(dates)) + int(args.timestamp is not None) + int(has_interval)
    if selected == 0 and optional:
        if args.timezone is not None:
            raise ContextValidationError("--timezone requires a timestamp or interval")
        return None
    if selected != 1:
        raise ContextValidationError(
            "choose exactly one temporal form: --date, --timestamp, or --start with --end"
        )
    if dates:
        if len(dates) != 1:
            raise ContextValidationError("context capture accepts exactly one --date")
        if args.timezone is not None:
            raise ContextValidationError("date-only context must not specify a timezone")
        return parse_date_only(dates[0])
    if args.timestamp is not None:
        return parse_timestamp(args.timestamp, timezone_name=args.timezone)
    if args.start is None or args.end is None:
        raise ContextValidationError("interval context requires both --start and --end")
    return parse_interval(args.start, args.end, timezone_name=args.timezone)


def _context_date(value: str | None, option_name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ContextValidationError(f"{option_name} must use a valid YYYY-MM-DD date") from exc


def _context_payload(view: ContextRevisionView, *, include_text: bool) -> dict[str, object]:
    temporal = view.temporal
    payload: dict[str, object] = {
        "event_id": view.event_id,
        "revision_id": view.revision_id,
        "revision_number": view.revision_number,
        "operation_id": view.operation_id,
        "is_current": view.is_current,
        "capture_source": view.capture_source,
        "temporal": {
            "kind": temporal.kind,
            "start_precision": temporal.start_precision,
            "start_local_date": temporal.start_local_date.isoformat(),
            "start_source_timestamp": temporal.start_source_timestamp,
            "start_utc_offset_minutes": temporal.start_utc_offset_minutes,
            "start_timezone": temporal.start_timezone,
            "end_precision": temporal.end_precision,
            "end_local_date": (
                temporal.end_local_date.isoformat() if temporal.end_local_date else None
            ),
            "end_source_timestamp": temporal.end_source_timestamp,
            "end_utc_offset_minutes": temporal.end_utc_offset_minutes,
            "end_timezone": temporal.end_timezone,
        },
        "tags": [
            {
                "name": tag.name,
                "status": tag.status,
                "provenance_source": tag.provenance_source,
            }
            for tag in view.tags
        ],
        "created_at": view.created_at.isoformat(),
    }
    if include_text:
        payload["text"] = view.original_text
    return payload


def _run_context(args: argparse.Namespace, settings: Settings) -> int:
    command_name = args.command
    try:
        paths = resolve_runtime_paths(settings)
        if not paths.database.is_file():
            raise ContextValidationError(
                "profile database is unavailable; run healthcheck migrate first"
            )
        engine = create_sqlite_engine(paths)
        try:
            with session_scope(engine) as session:
                service = ContextService(session)
                if command_name == "context-add":
                    if args.text is None:
                        raise ContextValidationError("context-add requires --text")
                    view = service.add(
                        text=args.text,
                        temporal=_context_temporal_from_args(args),
                        capture_source=args.source,
                        tags=tuple(args.tags or ()),
                        event_id=args.event_id,
                        operation_id=args.operation_id,
                    )
                    output: object = _context_payload(view, include_text=False)
                elif command_name == "context-revise":
                    if args.event_id is None:
                        raise ContextValidationError("context-revise requires --event-id")
                    if args.clear_tags and args.tags:
                        raise ContextValidationError("use either --tag or --clear-tags, not both")
                    temporal = _context_temporal_from_args(args, optional=True)
                    tag_update = (
                        ()
                        if args.clear_tags
                        else (tuple(args.tags) if args.tags is not None else None)
                    )
                    if args.text is None and temporal is None and tag_update is None:
                        raise ContextValidationError(
                            "context-revise requires a text, time, or tag change"
                        )
                    view = service.revise(
                        args.event_id,
                        text=args.text,
                        temporal=temporal,
                        capture_source=args.source,
                        tags=tag_update,
                        operation_id=args.operation_id,
                    )
                    output = _context_payload(view, include_text=False)
                else:
                    views = service.list(
                        from_date=_context_date(args.from_date, "--from"),
                        to_date=_context_date(args.to_date, "--to"),
                        limit=args.limit,
                        history=args.history,
                    )
                    output = {
                        "count": len(views),
                        "history": args.history,
                        "events": [
                            _context_payload(view, include_text=True) for view in views
                        ],
                    }
        finally:
            engine.dispose()
    except (ContextValidationError, ContextConflictError) as exc:
        print(f"{command_name}: ERROR: {exc}", file=sys.stderr)
        return 2
    except (SQLAlchemyError, OSError):
        print(
            f"{command_name}: ERROR: context storage operation failed; verify migration readiness",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


def _run_google_auth(args: argparse.Namespace, settings: Settings) -> int:
    try:
        result = GoogleAuthService(settings).bootstrap(force_reauth=args.force_reauth)
    except (OSError, ValueError):
        print(
            json.dumps(
                {
                    "contract_version": "r04-google-web-oauth-v1",
                    "status": "failed",
                    "token_health": "unknown",
                    "session_reused": False,
                    "force_reauth": bool(args.force_reauth),
                    "storage": "rejected",
                    "client_type": "web_application",
                    "error": {
                        "error_class": "storage",
                        "error_code": "unsafe_storage_path",
                        "http_status": None,
                    },
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result.as_dict(), ensure_ascii=True, sort_keys=True))
    return 0 if result.ok else 1


def _run_google_capabilities(args: argparse.Namespace, settings: Settings) -> int:
    try:
        validate_probe_window(args.dates)
        service = GoogleAuthService(settings)
        auth_result = service.token_health()
        report = GoogleCapabilityProbe(service).run(args.dates, auth_result=auth_result)
    except (OSError, ValueError):
        print(
            json.dumps(
                {
                    "contract_version": "r04-google-capability-spike-v1",
                    "error": {
                        "error_class": "input",
                        "error_code": "invalid_probe_request",
                        "http_status": None,
                    },
                    "privacy": {
                        "raw_values_emitted": False,
                        "private_identifiers_emitted": False,
                        "tokens_emitted": False,
                        "health_timestamps_emitted": False,
                        "string_encoded_numerics_logged_as_values": False,
                    },
                },
                sort_keys=True,
            )
        )
        return 2
    print(report.to_json(), end="")
    return 0 if report.auth.ok else 1


def _google_error_payload(contract_version: str, error_code: str) -> dict[str, object]:
    return {
        "contract_version": contract_version,
        "error": {
            "error_class": "input",
            "error_code": error_code,
            "http_status": None,
        },
        "privacy": {
            "raw_values_emitted": False,
            "private_identifiers_emitted": False,
            "tokens_emitted": False,
            "health_timestamps_emitted": False,
            "page_tokens_emitted": False,
            "string_encoded_numerics_logged_as_values": False,
        },
    }


def _external_runtime_operation_error_payload(
    contract_version: str,
    operation: str,
    error_code: str,
) -> dict[str, object]:
    return {
        "contract_version": contract_version,
        "operation": operation,
        "status": "blocked",
        "error": {
            "error_class": "runtime",
            "error_code": error_code,
            "http_status": None,
        },
        "privacy": {
            "raw_values_emitted": False,
            "private_identifiers_emitted": False,
            "tokens_emitted": False,
            "health_timestamps_emitted": False,
            "page_tokens_emitted": False,
        },
    }


def _report_external_runtime_operation_error(
    exc: ExternalRuntimeOperationBusyError | ExternalRuntimeOperationLockError,
    *,
    contract_version: str,
    operation: str,
) -> int:
    busy = isinstance(exc, ExternalRuntimeOperationBusyError)
    payload = _external_runtime_operation_error_payload(
        contract_version,
        operation,
        "external_runtime_operation_active" if busy else "runtime_lock_unavailable",
    )
    print(json.dumps(payload, sort_keys=True))
    return 1 if busy else 2


def _run_sync_run_recovery(args: argparse.Namespace, settings: Settings) -> int:
    try:
        if args.apply == args.dry_run:
            raise ValueError("choose exactly one of --dry-run or --apply")
        report = recover_stale_sync_runs(
            settings,
            cutoff=args.cutoff,
            apply=args.apply,
        )
    except ExternalRuntimeOperationBusyError:
        payload = _external_runtime_operation_error_payload(
            "healthcheck-sync-run-recovery-v1",
            "sync-run-recovery",
            "external_runtime_operation_active",
        )
        print(json.dumps(payload, sort_keys=True))
        return 1
    except ExternalRuntimeOperationLockError:
        payload = _external_runtime_operation_error_payload(
            "healthcheck-sync-run-recovery-v1",
            "sync-run-recovery",
            "runtime_lock_unavailable",
        )
        print(json.dumps(payload, sort_keys=True))
        return 2
    except SyncRunRecoveryRuntimeError as exc:
        payload = _external_runtime_operation_error_payload(
            "healthcheck-sync-run-recovery-v1",
            "sync-run-recovery",
            exc.error_code,
        )
        print(json.dumps(payload, sort_keys=True))
        return 2
    except (OSError, SQLAlchemyError, ValueError):
        payload = _external_runtime_operation_error_payload(
            "healthcheck-sync-run-recovery-v1",
            "sync-run-recovery",
            "invalid_recovery_request",
        )
        print(json.dumps(payload, sort_keys=True))
        return 2
    print(report.to_json(), end="")
    return 0


def _google_cli_exit(status: GoogleSyncStatus) -> int:
    if status is GoogleSyncStatus.SUCCEEDED:
        return 0
    return 1


def _run_google_sync(args: argparse.Namespace, settings: Settings) -> int:
    try:
        if args.trailing_window_days is not None:
            raise ValueError("google-sync does not use a trailing window")
        if args.reprocess:
            raise ValueError("google-sync does not use --reprocess")
        if args.max_observations is not None:
            raise ValueError("google-sync does not use --max-observations")
        if args.dry_run:
            raise ValueError("google-sync does not use --dry-run")
        if args.dates and (args.start or args.end):
            raise ValueError("google-sync accepts --date or --start/--end, not both")
        if args.dates is not None and len(args.dates) != 1:
            raise ValueError("google-sync accepts exactly one --date")
        service = GoogleAuthService(settings)
        report = GoogleHealthSync(
            settings,
            auth_service=service,
            run_kind=GoogleRunKind.INCREMENTAL,
        ).run(
            as_of=args.dates[0] if args.dates else None,
            start=args.start,
            end=args.end,
            streams=args.streams,
            query_mode=args.query_mode,
            data_source_family=args.family,
        )
    except (ExternalRuntimeOperationBusyError, ExternalRuntimeOperationLockError) as exc:
        return _report_external_runtime_operation_error(
            exc,
            contract_version="r04-google-sync-coverage-v1",
            operation="google-sync",
        )
    except (OSError, ValueError):
        print(
            json.dumps(
                _google_error_payload("r04-google-sync-coverage-v1", "invalid_sync_request"),
                sort_keys=True,
            )
        )
        return 2
    print(report.to_json(), end="")
    return _google_cli_exit(report.status)


def _run_google_backfill(args: argparse.Namespace, settings: Settings) -> int:
    try:
        if args.dates:
            raise ValueError("google-backfill uses --start and --end, not --date")
        if args.trailing_window_days is not None:
            raise ValueError("google-backfill does not use a trailing window")
        if args.max_observations is not None:
            raise ValueError("google-backfill does not use --max-observations")
        if args.reprocess:
            raise ValueError("google-backfill does not use --reprocess")
        if args.dry_run:
            report = plan_google_historical_backfill(
                start=args.start,
                end=args.end,
                streams=args.streams,
                chunk_days=args.chunk_days,
                query_mode=args.query_mode,
                data_source_family=args.family,
            )
        else:
            service = GoogleAuthService(settings)
            report = GoogleHistoricalBackfill(
                settings,
                auth_service=service,
            ).run(
                start=args.start,
                end=args.end,
                streams=args.streams,
                chunk_days=args.chunk_days,
                query_mode=args.query_mode,
                data_source_family=args.family,
            )
    except (ExternalRuntimeOperationBusyError, ExternalRuntimeOperationLockError) as exc:
        return _report_external_runtime_operation_error(
            exc,
            contract_version="r04-google-historical-backfill-v1",
            operation="google-backfill",
        )
    except (OSError, ValueError):
        print(
            json.dumps(
                _google_error_payload(
                    "r04-google-historical-backfill-v1", "invalid_backfill_request"
                ),
                sort_keys=True,
            )
        )
        return 2
    print(report.to_json(), end="")
    if report.dry_run:
        return 0
    return _google_cli_exit(report.status)


def _run_google_refresh(args: argparse.Namespace, settings: Settings) -> int:
    try:
        if args.dates:
            raise ValueError("google-refresh uses --start and --end, not --date")
        if args.trailing_window_days is not None:
            raise ValueError("google-refresh does not use a trailing window")
        if args.max_observations is not None:
            raise ValueError("google-refresh does not use --max-observations")
        if args.reprocess:
            raise ValueError("google-refresh does not use --reprocess")
        if args.dry_run:
            raise ValueError("google-refresh does not use --dry-run")
        service = GoogleAuthService(settings)
        report = run_google_refresh(
            settings,
            start=args.start,
            end=args.end,
            auth_service=service,
            streams=args.streams,
            query_mode=args.query_mode,
            data_source_family=args.family,
        )
    except (ExternalRuntimeOperationBusyError, ExternalRuntimeOperationLockError) as exc:
        return _report_external_runtime_operation_error(
            exc,
            contract_version="r04-google-sync-coverage-v1",
            operation="google-refresh",
        )
    except (OSError, ValueError):
        print(
            json.dumps(
                _google_error_payload("r04-google-sync-coverage-v1", "invalid_refresh_request"),
                sort_keys=True,
            )
        )
        return 2
    print(report.to_json(), end="")
    return _google_cli_exit(report.status)


def _run_google_diagnose_terminal(args: argparse.Namespace, settings: Settings) -> int:
    stream = "heart_rate"
    try:
        if args.streams and args.streams != [stream]:
            raise ValueError("google-diagnose-terminal only supports --stream heart_rate")
        paths = prepare_runtime(settings)
        engine = create_sqlite_engine(paths)
        try:
            factory = create_session_factory(engine)
            with factory() as session:
                from healthcheck.google.storage import ContentAddressedGooglePayloadStore

                diagnosis = diagnose_latest_invalid_google_envelope(
                    session,
                    payload_store=ContentAddressedGooglePayloadStore(paths.root / "artifacts"),
                    stream=stream,
                )
        finally:
            engine.dispose()
    except (OSError, SQLAlchemyError, ValueError):
        print(
            json.dumps(
                {
                    "contract_version": "r04-google-terminal-envelope-diagnostic-v1",
                    "status": "unavailable",
                    "stream": stream,
                    "query_mode": None,
                    "diagnosis": {
                        "stage": "unavailable",
                        "diagnostic_code": "diagnostic_unavailable",
                        "envelope_field": None,
                        "collection_presence": "unknown",
                        "collection_type": "unknown",
                        "next_page_token_type": "unknown",
                        "top_level_type": "unknown",
                    },
                    "privacy": {
                        "raw_values_emitted": False,
                        "private_identifiers_emitted": False,
                        "tokens_emitted": False,
                        "health_timestamps_emitted": False,
                        "page_tokens_emitted": False,
                        "string_encoded_numerics_logged_as_values": False,
                    },
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 2
    print(diagnosis.to_json(), end="")
    return 0 if diagnosis.status == "diagnosed" else 1


def _run_owner_refresh(args: argparse.Namespace, settings: Settings) -> int:
    try:
        if args.dates is not None and len(args.dates) != 1:
            raise ValueError("owner-refresh accepts exactly one --date")
        if args.start or args.end:
            raise ValueError("owner-refresh uses --date and --trailing-window-days")
        if args.dry_run:
            raise ValueError("owner-refresh does not use --dry-run")
        if args.reprocess:
            raise ValueError("owner-refresh does not use --reprocess")
        if args.max_observations is not None:
            raise ValueError("owner-refresh does not use --max-observations")
        if args.chunk_days is not None:
            raise ValueError("owner-refresh does not use --chunk-days")
        report = run_owner_refresh(
            settings,
            as_of=args.dates[0] if args.dates else None,
            trailing_window_days=args.trailing_window_days,
            is_cn=args.is_cn,
            streams=args.streams,
            query_mode=args.query_mode,
            data_source_family=args.family,
        )
    except OwnerRefreshBusyError:
        print(
            json.dumps(
                _owner_refresh_error_payload("refresh_already_running", "runtime"),
                sort_keys=True,
            )
        )
        return 1
    except OwnerRefreshRuntimeError as exc:
        print(
            json.dumps(
                _owner_refresh_error_payload(exc.error_code, "runtime"),
                sort_keys=True,
            )
        )
        return 2
    except (OSError, ValueError):
        print(
            json.dumps(
                _owner_refresh_error_payload("invalid_refresh_request", "input"),
                sort_keys=True,
            )
        )
        return 2
    print(report.to_json(), end="")
    return 0 if report.status is OwnerRefreshStatus.SUCCEEDED else 1


def _owner_refresh_error_payload(error_code: str, error_class: str) -> dict[str, object]:
    return {
        "contract_version": "healthcheck-owner-refresh-v1",
        "operation": "owner-refresh",
        "error": {
            "error_class": error_class,
            "error_code": error_code,
            "http_status": None,
        },
        "privacy": {
            "raw_values_emitted": False,
            "private_identifiers_emitted": False,
            "tokens_emitted": False,
            "health_timestamps_emitted": False,
            "page_tokens_emitted": False,
            "string_encoded_numerics_logged_as_values": False,
        },
    }


def _run_garmin_auth(args: argparse.Namespace, settings: Settings) -> int:
    try:
        result = GarminAuthService(settings, is_cn=args.is_cn).bootstrap(
            force_reauth=args.force_reauth
        )
    except (OSError, ValueError):
        print(
            json.dumps(
                {
                    "contract_version": "r02-garmin-auth-spike-v1",
                    "status": "failed",
                    "session_reused": False,
                    "mfa": "not_attempted",
                    "storage": "rejected",
                    "error": {
                        "error_class": "storage",
                        "error_code": "unsafe_storage_path",
                        "http_status": None,
                    },
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result.as_dict(), ensure_ascii=True, sort_keys=True))
    return 0 if result.ok else 1


def _run_garmin_capabilities(args: argparse.Namespace, settings: Settings) -> int:
    try:
        dates = validate_probe_dates(args.dates)
        service = GarminAuthService(settings, is_cn=args.is_cn)
        client, auth_result = service.load_existing()
        report = GarminCapabilityProbe(client).run(dates, auth_result=auth_result)
    except (OSError, ValueError):
        print(
            json.dumps(
                {
                    "contract_version": "r02-garmin-capability-spike-v1",
                    "error": {
                        "error_class": "input",
                        "error_code": "invalid_probe_request",
                        "http_status": None,
                    },
                    "privacy": {
                        "raw_values_emitted": False,
                        "private_identifiers_emitted": False,
                        "tokens_emitted": False,
                    },
                },
                sort_keys=True,
            )
        )
        return 2
    print(report.to_json(), end="")
    return 0 if auth_result.ok else 1


def _run_garmin_training_phase_a(args: argparse.Namespace, settings: Settings) -> int:
    try:
        request = validate_training_probe_request(
            args.dates,
            args.max_ranges,
            args.max_date,
            args.activity_start,
            args.activity_end,
            args.activity_ids,
            args.repeat_date,
        )
        service = GarminAuthService(settings, is_cn=args.is_cn)
        client, auth_result = service.load_existing()
        report = GarminTrainingPhaseAProbe(client).run(request, auth_result=auth_result)
    except (OSError, ValueError):
        print(
            json.dumps(
                {
                    "contract_version": TRAINING_PROBE_CONTRACT_VERSION,
                    "operation": "garmin-training-phase-a",
                    "status": "failed",
                    "sample_incomplete": True,
                    "error": {
                        "error_class": "input",
                        "error_code": "invalid_probe_request",
                        "http_status": None,
                    },
                    "privacy": {
                        "raw_payloads_emitted": False,
                        "exact_metric_values_emitted": False,
                        "device_ids_emitted": False,
                        "activity_ids_emitted": False,
                        "dates_or_timestamps_emitted": False,
                        "dynamic_keys_emitted": False,
                    },
                },
                sort_keys=True,
            )
        )
        return 2
    print(report.to_json(), end="")
    return 0 if report.completed else 1


def _run_garmin_training_sync(args: argparse.Namespace, settings: Settings) -> int:
    try:
        validate_training_window(args.start, args.end)
        if args.dates or args.streams or args.trailing_window_days is not None:
            raise ValueError("training sync uses only --start and --end")
        paths = prepare_runtime(settings)
        with ExternalRuntimeOperationLock(paths):
            client, auth_result = GarminAuthService(settings, is_cn=args.is_cn).load_existing()
            report = GarminTrainingSync(settings, client=client, auth_result=auth_result).run(
                start=args.start, end=args.end
            )
    except (ExternalRuntimeOperationBusyError, ExternalRuntimeOperationLockError) as exc:
        return _report_external_runtime_operation_error(
            exc, contract_version=TRAINING_CONTRACT_VERSION, operation="garmin-training-sync"
        )
    except ValueError:
        report = {
            "contract_version": TRAINING_CONTRACT_VERSION,
            "status": "invalid_request",
            "raw_values_emitted": False,
            "private_identifiers_emitted": False,
        }
        print(json.dumps(report, sort_keys=True))
        return 2
    except (OSError, SQLAlchemyError):
        report = {
            "contract_version": TRAINING_CONTRACT_VERSION,
            "status": "failed",
            "raw_values_emitted": False,
            "private_identifiers_emitted": False,
        }
        print(json.dumps(report, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "succeeded" else 1


def _run_garmin_sync(args: argparse.Namespace, settings: Settings) -> int:
    try:
        if args.dates is not None and len(args.dates) != 1:
            raise ValueError("garmin-sync accepts exactly one --date")
        if args.reprocess:
            raise ValueError("garmin-sync does not use --reprocess")
        if args.max_observations is not None:
            raise ValueError("garmin-sync does not use --max-observations")
        paths = prepare_runtime(settings)
        with ExternalRuntimeOperationLock(paths):
            service = GarminAuthService(settings, is_cn=args.is_cn)
            client, auth_result = service.load_existing()
            report = GarminIncrementalSync(
                settings,
                client=client,
                auth_result=auth_result,
            ).run(
                as_of=args.dates[0] if args.dates else None,
                trailing_window_days=args.trailing_window_days,
            )
    except (ExternalRuntimeOperationBusyError, ExternalRuntimeOperationLockError) as exc:
        return _report_external_runtime_operation_error(
            exc,
            contract_version="r02-garmin-incremental-sync-v1",
            operation="garmin-sync",
        )
    except (OSError, ValueError):
        print(
            json.dumps(
                {
                    "contract_version": "r02-garmin-incremental-sync-v1",
                    "error": {
                        "error_class": "input",
                        "error_code": "invalid_sync_request",
                        "http_status": None,
                    },
                    "privacy": {
                        "raw_values_emitted": False,
                        "private_identifiers_emitted": False,
                        "tokens_emitted": False,
                    },
                },
                sort_keys=True,
            )
        )
        return 2
    print(report.to_json(), end="")
    if report.status is GarminSyncStatus.SUCCEEDED:
        return 0
    if report.status is GarminSyncStatus.REAUTH_REQUIRED:
        return 1
    return 1


def _run_garmin_backfill(args: argparse.Namespace, settings: Settings) -> int:
    try:
        if args.dates:
            raise ValueError("garmin-backfill uses --start and --end, not --date")
        if args.trailing_window_days is not None:
            raise ValueError("garmin-backfill does not use --trailing-window-days")
        if args.max_observations is not None:
            raise ValueError("garmin-backfill does not use --max-observations")
        if args.dry_run:
            report = plan_garmin_historical_backfill(
                start=args.start,
                end=args.end,
                streams=args.streams,
                chunk_days=args.chunk_days,
            )
        else:
            paths = prepare_runtime(settings)
            with ExternalRuntimeOperationLock(paths):
                service = GarminAuthService(settings, is_cn=args.is_cn)
                client, auth_result = service.load_existing()
                report = GarminHistoricalBackfill(
                    settings,
                    client=client,
                    auth_result=auth_result,
                ).run(
                    start=args.start,
                    end=args.end,
                    streams=args.streams,
                    chunk_days=args.chunk_days,
                    reprocess=args.reprocess,
                )
    except (ExternalRuntimeOperationBusyError, ExternalRuntimeOperationLockError) as exc:
        return _report_external_runtime_operation_error(
            exc,
            contract_version="r02-garmin-historical-backfill-v1",
            operation="garmin-backfill",
        )
    except (OSError, ValueError):
        print(
            json.dumps(
                {
                    "contract_version": "r02-garmin-historical-backfill-v1",
                    "error": {
                        "error_class": "input",
                        "error_code": "invalid_backfill_request",
                        "http_status": None,
                    },
                    "privacy": {
                        "raw_values_emitted": False,
                        "private_identifiers_emitted": False,
                        "tokens_emitted": False,
                    },
                },
                sort_keys=True,
            )
        )
        return 2
    print(report.to_json(), end="")
    if report.dry_run or report.status is GarminSyncStatus.SUCCEEDED:
        return 0
    if report.status is GarminSyncStatus.REAUTH_REQUIRED:
        return 1
    return 1


def _run_garmin_redact(args: argparse.Namespace) -> int:
    if not args.input or not args.output:
        print("garmin-redact: ERROR: --input and --output are required", file=sys.stderr)
        return 2
    try:
        input_path, output_path = validate_external_export_paths(args.input, args.output)
        value = json.loads(input_path.read_text(encoding="utf-8"))
        sanitized = redact_garmin_payload(value)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(sanitized, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
        print("garmin-redact: ERROR: input or output was not accepted", file=sys.stderr)
        return 2
    print("garmin-redact: sanitized shape written; raw values were not copied")
    return 0


def _run_garmin_reprocess(args: argparse.Namespace, settings: Settings) -> int:
    try:
        if args.dates:
            raise ValueError("garmin-reprocess uses --start and --end, not --date")
        if args.trailing_window_days is not None:
            raise ValueError("garmin-reprocess does not use --trailing-window-days")
        report = GarminCollectionReprocessor(
            settings,
            max_observations=args.max_observations or MAX_REPROCESS_OBSERVATIONS,
        ).run(
            start=args.start,
            end=args.end,
            streams=args.streams,
            dry_run=args.dry_run,
            max_observations=args.max_observations,
        )
    except (ExternalRuntimeOperationBusyError, ExternalRuntimeOperationLockError) as exc:
        return _report_external_runtime_operation_error(
            exc,
            contract_version="r02-garmin-collection-reprocess-v1",
            operation="garmin-reprocess",
        )
    except (OSError, ValueError):
        print(
            json.dumps(
                {
                    "contract_version": "r02-garmin-collection-reprocess-v1",
                    "error": {
                        "error_class": "input",
                        "error_code": "invalid_reprocess_request",
                        "http_status": None,
                    },
                    "privacy": {
                        "raw_values_emitted": False,
                        "private_identifiers_emitted": False,
                        "tokens_emitted": False,
                    },
                },
                sort_keys=True,
            )
        )
        return 2
    print(report.to_json(), end="")
    if report.dry_run or report.status == "succeeded":
        return 0
    return 1


def _run_period_brief(args: argparse.Namespace) -> int:
    if not args.start or not args.end:
        print("period-brief: --start and --end are required (YYYY-MM-DD)", file=sys.stderr)
        return 2
    try:
        start_date = date.fromisoformat(args.start)
        end_date = date.fromisoformat(args.end)
    except ValueError:
        print("period-brief: --start/--end must be YYYY-MM-DD", file=sys.stderr)
        return 2
    settings = _settings(args)
    paths = prepare_runtime(settings)
    configure_logging(paths.logs, settings.log_level)
    from healthcheck.web.period_brief_query import PeriodBriefService

    engine = create_sqlite_engine(paths)
    try:
        with session_scope(engine) as session:
            payload = PeriodBriefService(session, settings).build_with_render(
                start_date=start_date,
                end_date=end_date,
            )
    except ValueError as exc:
        print(f"period-brief: ERROR: {exc}", file=sys.stderr)
        return 2
    text = payload["rendered_text"]
    packet_json = json.dumps(payload["packet"], ensure_ascii=True, sort_keys=True, indent=2)
    if args.output:
        out = Path(args.output)
        out.write_text(packet_json + "\n", encoding="utf-8")
        print(f"period-brief: wrote packet to {out}")
        print(text, end="")
        return 0
    print(packet_json)
    print(text, end="")
    return 0


def _sleep_agreement_build_error_payload(error_code: str, error_class: str) -> dict[str, object]:
    return {
        "contract_version": "r05-06-sleep-agreement-build-v1",
        "operation": "sleep-agreement-build",
        "status": "failed",
        "error": {
            "error_class": error_class,
            "error_code": error_code,
            "http_status": None,
        },
        "privacy": {
            "raw_values_emitted": False,
            "private_identifiers_emitted": False,
            "tokens_emitted": False,
        },
    }


def _sleep_agreement_scope_key(query: SleepPairingQuery) -> str:
    """Build a stable, non-secret persistence identity from explicit command inputs."""

    return (
        "r05-sleep-agreement-build:"
        f"{query.cohort}:{query.start_date.isoformat()}:{query.end_date.isoformat()}"
    )


def _run_sleep_agreement_build(args: argparse.Namespace, settings: Settings) -> int:
    engine = None
    try:
        if not args.start or not args.end:
            raise ValueError("sleep-agreement-build requires --start and --end")
        start_date = date.fromisoformat(args.start)
        end_date = date.fromisoformat(args.end)
        query = SleepPairingQuery(
            start_date=start_date,
            end_date=end_date,
            cohort=args.cohort,
        )
        paths = require_established_runtime(settings)
        engine = create_sqlite_engine(paths)
        scope_key = _sleep_agreement_scope_key(query)
        with session_scope(engine) as session:
            projection = read_persisted_sleep_metric_projection(session, query)
            persisted = PersistedSleepAgreementService(session).persist(
                projection,
                scope_key=scope_key,
            )
            report = SleepAgreementReportService(session).report(
                start_date=start_date,
                end_date=end_date,
                cohort=query.cohort,
                run_id=persisted.id,
            )
            if not report.get("runs"):
                raise ValueError("sleep-agreement-build could not verify persisted report")
    except OwnerRefreshRuntimeError as exc:
        print(
            json.dumps(
                _sleep_agreement_build_error_payload(exc.error_code, "runtime"), sort_keys=True
            )
        )
        return 2
    except (OSError, SQLAlchemyError, ValueError) as exc:
        error_code = "invalid_build_request" if isinstance(exc, ValueError) else "build_unavailable"
        error_class = "input" if isinstance(exc, ValueError) else "runtime"
        print(
            json.dumps(
                _sleep_agreement_build_error_payload(error_code, error_class), sort_keys=True
            )
        )
        return 2
    finally:
        if engine is not None:
            engine.dispose()

    mode = report["mode"]
    status = (
        "succeeded"
        if mode == "exploratory"
        else "insufficient"
        if mode == "accumulating"
        else "unavailable"
    )
    payload = {
        "contract_version": "r05-06-sleep-agreement-build-v1",
        "operation": "sleep-agreement-build",
        "status": status,
        "created": persisted.created,
        "run_status": persisted.status,
        "cohort": query.cohort,
        "window": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        "pair_count": persisted.run.pair_count,
        "exclusion_count": persisted.run.exclusion_count,
        "metric_count": persisted.run.metric_count,
        "coverage_count": persisted.run.coverage_count,
        "exploratory_only": query.cohort == ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS,
        "canonical_eligible": False
        if query.cohort == ACCOUNT_WEARABLES_SLEEP_OBSERVATIONS
        else None,
        "report_verification": {
            "status": "verified",
            "contract_version": report["contract_version"],
            "mode": mode,
            "available": report["available"],
            "group_count": len(report["groups"]),
        },
        "privacy": {
            "raw_values_emitted": False,
            "private_identifiers_emitted": False,
            "tokens_emitted": False,
        },
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if status == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
