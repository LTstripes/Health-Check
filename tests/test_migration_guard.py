"""Offline Alembic ancestry regressions for issue #96."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from healthcheck.db.migration_guard import (
    ACCEPTED_MIGRATION_CHAIN,
    ACCEPTED_MIGRATION_HEAD,
    MIGRATION_SCRIPT_LOCATION,
    MigrationAncestryError,
    validate_migration_ancestry,
)


def _synthetic_migrations(tmp_path: Path) -> Path:
    location = tmp_path / "migrations"
    shutil.copytree(MIGRATION_SCRIPT_LOCATION, location)
    return location


def _write_revision(location: Path, name: str, revision: str, down_revision: str) -> None:
    (location / "versions" / name).write_text(
        "from alembic import op\n"
        f"revision = {revision!r}\n"
        f"down_revision = {down_revision!r}\n"
        "branch_labels = None\n"
        "depends_on = None\n"
        "\n"
        "def upgrade():\n"
        "    pass\n"
        "\n"
        "def downgrade():\n"
        "    pass\n",
        encoding="utf-8",
    )


def test_current_accepted_chain_passes() -> None:
    validate_migration_ancestry()
    assert ACCEPTED_MIGRATION_CHAIN[-1][0] == ACCEPTED_MIGRATION_HEAD


def test_linear_forward_extension_from_accepted_head_passes(tmp_path: Path) -> None:
    location = _synthetic_migrations(tmp_path)
    _write_revision(
        location,
        "0011_r05_synthetic.py",
        "0011_r05_synthetic",
        ACCEPTED_MIGRATION_HEAD,
    )

    validate_migration_ancestry(location)


def test_multiple_heads_fail_without_mutating_repository_migrations(tmp_path: Path) -> None:
    location = _synthetic_migrations(tmp_path)
    _write_revision(
        location,
        "0011_synthetic_branch.py",
        "0011_synthetic_branch",
        "0009_google_persistence_contract",
    )

    with pytest.raises(MigrationAncestryError, match="exactly one Alembic head"):
        validate_migration_ancestry(location)


def test_reparented_historical_revision_fails(tmp_path: Path) -> None:
    location = _synthetic_migrations(tmp_path)
    migration = location / "versions" / "0009_google_persistence_contract.py"
    migration.write_text(
        migration.read_text(encoding="utf-8").replace(
            'down_revision = "0008_garmin_observation_reconciliation_version"',
            'down_revision = "0007_garmin_collection_reconciliation"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(MigrationAncestryError, match="accepted revision .*changed down_revision"):
        validate_migration_ancestry(location)


def test_inserted_behind_applied_head_fails(tmp_path: Path) -> None:
    location = _synthetic_migrations(tmp_path)
    _write_revision(
        location,
        "0011_inserted_behind_applied_head.py",
        "0011_inserted_behind_applied_head",
        "0009_google_persistence_contract",
    )

    with pytest.raises(MigrationAncestryError, match="behind accepted head"):
        validate_migration_ancestry(location)


def test_accepted_revision_deletion_fails(tmp_path: Path) -> None:
    location = _synthetic_migrations(tmp_path)
    (location / "versions" / "0008_garmin_observation_reconciliation_version.py").unlink()

    with pytest.raises(MigrationAncestryError, match="unable to load migration ancestry"):
        validate_migration_ancestry(location)


def test_accepted_revision_id_change_fails(tmp_path: Path) -> None:
    location = _synthetic_migrations(tmp_path)
    migration = location / "versions" / "0008_garmin_observation_reconciliation_version.py"
    migration.write_text(
        migration.read_text(encoding="utf-8").replace(
            'revision = "0008_garmin_observation_reconciliation_version"',
            'revision = "0008_renamed_revision"',
        ),
        encoding="utf-8",
    )
    downstream = location / "versions" / "0009_google_persistence_contract.py"
    downstream.write_text(
        downstream.read_text(encoding="utf-8").replace(
            'down_revision = "0008_garmin_observation_reconciliation_version"',
            'down_revision = "0008_renamed_revision"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(MigrationAncestryError, match="missing or renamed"):
        validate_migration_ancestry(location)
