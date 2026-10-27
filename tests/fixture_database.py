"""Reuse one empty migrated schema while keeping every test database independent."""

import sqlite3
from contextlib import closing
from pathlib import Path
from shutil import copyfile

import pytest

from healthcheck.config import Settings
from healthcheck.db.engine import migrate_database
from healthcheck.runtime import RuntimePaths, prepare_runtime

_DATABASE_TEMPLATE_KEY = pytest.StashKey[Path]()


def copy_migrated_database(
    paths: RuntimePaths,
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Initialize a fresh ordinary fixture; migration/upgrade tests keep real bootstrap."""
    if any(Path(f"{paths.database}{suffix}").exists() for suffix in ("", "-wal", "-shm")):
        raise FileExistsError("fixture database and sidecars must be new")
    template = request.config.stash.get(_DATABASE_TEMPLATE_KEY, None)
    if template is None:
        template_paths = prepare_runtime(
            Settings(data_dir=tmp_path_factory.mktemp("empty-schema") / "runtime")
        )
        migrate_database(template_paths)
        # The accepted Stress mechanism: copy only a checkpointed standalone DB,
        # after every connection is closed. Never put test data in this template.
        with closing(sqlite3.connect(template_paths.database)) as connection:
            assert connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone() == (0, 0, 0)
        template = template_paths.database
        request.config.stash[_DATABASE_TEMPLATE_KEY] = template
    copyfile(template, paths.database)
