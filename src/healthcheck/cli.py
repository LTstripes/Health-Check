"""Direct troubleshooting and Windows-launcher commands."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

import uvicorn

from healthcheck.config import Settings
from healthcheck.db.engine import migrate_placeholder
from healthcheck.logging import configure_logging, log_event
from healthcheck.runtime import prepare_runtime
from healthcheck.web.ingest_app import create_ingest_app
from healthcheck.web.ui_app import create_ui_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="healthcheck")
    parser.add_argument("command", choices=("prepare-runtime", "migrate", "serve"))
    parser.add_argument("--app", choices=("ui", "ingest"), default="ui")
    parser.add_argument("--data-dir")
    parser.add_argument("--port", type=int)
    parser.add_argument("--host")
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
    settings = _settings(args)
    paths = prepare_runtime(settings)

    if args.command == "prepare-runtime":
        print(paths.root)
        return 0

    configure_logging(paths.logs, settings.log_level)
    if args.command == "migrate":
        migrate_placeholder(paths)
        log_event("runtime_migration_ready", operation="migrate", status="ok")
        return 0

    if args.app == "ui":
        app, _ = create_ui_app(settings)
        host = "127.0.0.1"
        port = settings.ui_port
        service = "loopback-ui"
    else:
        app, _ = create_ingest_app(settings)
        host = settings.ingest_host
        port = settings.ingest_port
        service = "ingest"
    log_event("runtime_starting", operation="serve", service=service, status="ok")
    uvicorn.run(app, host=host, port=port, log_config=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
