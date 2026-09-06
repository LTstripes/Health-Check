"""Direct troubleshooting and Windows-launcher commands."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

import uvicorn

from healthcheck.config import Settings
from healthcheck.db.engine import migrate_database
from healthcheck.demo import DemoSeedError, seed_demo
from healthcheck.garmin.auth import GarminAuthService
from healthcheck.garmin.probe import GarminCapabilityProbe, validate_probe_dates
from healthcheck.garmin.redaction import redact_garmin_payload, validate_external_export_paths
from healthcheck.garmin.sync import GarminIncrementalSync, GarminSyncStatus
from healthcheck.ingestion.openscale.binding import evaluate_ingest_binding
from healthcheck.logging import configure_logging, log_event
from healthcheck.profile_backup import (
    ProfileBackupError,
    create_backup,
    restore_profile,
    verify_backup,
)
from healthcheck.runtime import prepare_runtime
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
            "garmin-redact",
            "garmin-sync",
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
    parser.add_argument("--trailing-window-days", type=int)
    parser.add_argument("--input")
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
            f"verify-backup: OK; {result.file_count} files; "
            f"classification={result.classification}"
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

    settings = _settings(args)
    if args.command == "garmin-auth":
        return _run_garmin_auth(args, settings)
    if args.command == "garmin-capabilities":
        return _run_garmin_capabilities(args, settings)
    if args.command == "garmin-sync":
        return _run_garmin_sync(args, settings)
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


def _run_garmin_sync(args: argparse.Namespace, settings: Settings) -> int:
    try:
        if args.dates is not None and len(args.dates) != 1:
            raise ValueError("garmin-sync accepts exactly one --date")
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


if __name__ == "__main__":
    raise SystemExit(main())
