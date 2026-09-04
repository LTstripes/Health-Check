"""Direct troubleshooting and Windows-launcher commands."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

import uvicorn

from healthcheck.config import Settings
from healthcheck.db.engine import migrate_database
from healthcheck.demo import DemoSeedError, seed_demo
from healthcheck.ingestion.openscale.binding import evaluate_ingest_binding
from healthcheck.logging import configure_logging, log_event
from healthcheck.runtime import prepare_runtime
from healthcheck.uat import format_smoke_results, run_smoke, smoke_exit_code
from healthcheck.web.ingest_app import create_ingest_app
from healthcheck.web.ui_app import create_ui_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="healthcheck")
    parser.add_argument(
        "command", choices=("prepare-runtime", "migrate", "serve", "seed-demo", "smoke")
    )
    parser.add_argument("--app", choices=("ui", "ingest"), default="ui")
    parser.add_argument("--data-dir")
    parser.add_argument("--port", type=int)
    parser.add_argument("--host")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--ui-url", default="http://127.0.0.1:8000")
    parser.add_argument("--ingest-url")
    parser.add_argument("--timeout", type=float, default=3.0)
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

    settings = _settings(args)
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


if __name__ == "__main__":
    raise SystemExit(main())
