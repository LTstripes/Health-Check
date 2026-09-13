"""Regressions for issue #76: FK-safe populated 0006 → 0008 migration repair."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from healthcheck.config import Settings
from healthcheck.db.engine import (
    _alembic_config,
    create_sqlite_engine,
    database_readiness,
    migrate_database,
)
from healthcheck.runtime import prepare_runtime

HEAD = "0010_google_typed_normalization"
REV_0006 = "0006_garmin_payload_observation_provenance"
PRE_RECONCILIATION_VERSION = "r02-garmin-pre-collection-reconciliation"
CONTENT_HASH = "a" * 64
TEMP_SOURCE_RECORDS = "_alembic_tmp_garmin_source_records"

EXPECTED_0007_COLUMNS = {
    "surface_code",
    "collection_key",
    "projection_status",
    "projection_observed_at",
    "retired_at",
    "retire_reason",
    "reconciliation_contract_version",
}


def _upgrade(paths, revision: str) -> None:
    command.upgrade(_alembic_config(paths), revision)


def _seed_populated_0006(paths) -> dict[str, object]:
    """Insert representative Garmin parent + typed-child rows at exact 0006 schema."""

    engine = create_sqlite_engine(paths)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO providers (
                        id, code, display_name, provider_kind, created_at
                    )
                    VALUES (
                        'prov-1', 'garmin_connect', 'Garmin Connect',
                        'wearable', CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO acquisition_sources (
                        id, provider_id, input_method, source_instance_id, created_at
                    )
                    VALUES (
                        'acq-1', 'prov-1', 'provider_api',
                        'synthetic-src-76', CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO garmin_sources (
                        id, provider_id, acquisition_source_id, source_kind, provider_code,
                        source_instance_id, device_attributed, created_at
                    )
                    VALUES (
                        'gs-1', 'prov-1', 'acq-1', 'synthetic', 'garmin_connect',
                        'synthetic-src-76', 0, CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO raw_artifacts (
                        id, content_hash, kind, media_type, byte_size,
                        relative_storage_path, received_at
                    )
                    VALUES (
                        'ra-1', :hash, 'garmin_payload', 'application/json', 2,
                        'garmin/aa/seed.json', CURRENT_TIMESTAMP
                    )
                    """
                ),
                {"hash": CONTENT_HASH},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO garmin_raw_payloads (
                        id, garmin_source_id, raw_artifact_id, stream_code, content_hash,
                        payload_format, normalization_contract_version, parse_status,
                        record_count, received_at, created_at
                    )
                    VALUES (
                        'grp-1', 'gs-1', 'ra-1', 'daily_health', :hash, 'json',
                        'r02-garmin-normalization-contract-v1', 'ok', 5,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """
                ),
                {"hash": CONTENT_HASH},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO garmin_payload_observations (
                        id, garmin_raw_payload_id, raw_artifact_id, garmin_source_id,
                        observation_key, stream_code, payload_format,
                        normalization_contract_version, parse_status, record_count,
                        received_at, created_at
                    )
                    VALUES (
                        'obs-1', 'grp-1', 'ra-1', 'gs-1',
                        'garmin-observation-v1:seed-76-aaaaaaaaaa', 'daily_health', 'json',
                        'r02-garmin-normalization-contract-v1', 'ok', 5,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO sync_stream_state (
                        id, provider_id, acquisition_source_id, stream_code,
                        cursor, diagnostic_status, updated_at
                    )
                    VALUES (
                        'sss-1', 'prov-1', 'acq-1', 'daily_health',
                        'cursor-76', 'ok', CURRENT_TIMESTAMP
                    )
                    """
                )
            )

            record_specs = [
                ("gsr-daily", "daily_health", "daily:2099-01-01", "date", "2099-01-01", None, None),
                ("gsr-sleep", "sleep", "sleep:2099-01-02", "date", "2099-01-02", None, None),
                (
                    "gsr-activity",
                    "activity",
                    "activity:ext-1",
                    "instant",
                    None,
                    "running",
                    "2099-01-03T10:00:00+00:00",
                ),
                (
                    "gsr-intraday",
                    "intraday",
                    "intraday:2099-01-01:0",
                    "date",
                    "2099-01-01",
                    None,
                    None,
                ),
                ("gsr-fit", "original_fit", "fit:ext-1", "unknown", None, None, None),
            ]
            for record_id, stream, idem, precision, local_date, activity, ts in record_specs:
                conn.execute(
                    text(
                        """
                        INSERT INTO garmin_source_records (
                            id, garmin_source_id, raw_payload_id, stream_code, idempotency_key,
                            external_record_id, activity_type, temporal_precision,
                            source_local_date, source_timestamp_utc, record_status,
                            normalization_contract_version,
                            created_at, last_seen_at, updated_at
                        )
                        VALUES (
                            :id, 'gs-1', 'grp-1', :stream, :idem,
                            :external, :activity, :precision,
                            :local_date, :ts, 'ok',
                            'r02-garmin-normalization-contract-v1',
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                        )
                        """
                    ),
                    {
                        "id": record_id,
                        "stream": stream,
                        "idem": idem,
                        "external": idem,
                        "activity": activity,
                        "precision": precision,
                        "local_date": local_date,
                        "ts": ts,
                    },
                )

            conn.execute(
                text(
                    "INSERT INTO garmin_daily_records (record_id, calendar_date) "
                    "VALUES ('gsr-daily', '2099-01-01')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO garmin_sleep_records (record_id, wake_date) "
                    "VALUES ('gsr-sleep', '2099-01-02')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO garmin_activity_records (record_id, activity_type) "
                    "VALUES ('gsr-activity', 'running')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO garmin_intraday_records (record_id, sample_date, sample_sequence) "
                    "VALUES ('gsr-intraday', '2099-01-01', 0)"
                )
            )
            conn.execute(text("INSERT INTO garmin_fit_records (record_id) VALUES ('gsr-fit')"))
            conn.execute(
                text(
                    """
                    INSERT INTO garmin_record_metrics (
                        id, record_id, capability_code, metric_code, field_path, state,
                        value_number, unit, source_device_attributed
                    )
                    VALUES (
                        'metric-1', 'gsr-daily', 'daily_steps', 'steps', '$.steps', 'value',
                        1234.0, 'count', 0
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO garmin_sleep_stage_intervals (
                        id, sleep_record_id, ordinal, start_precision, end_precision,
                        start_local_date, end_local_date, activity_level,
                        start_temporal_json, end_temporal_json
                    )
                    VALUES (
                        'stage-1', 'gsr-sleep', 0, 'date', 'date',
                        '2099-01-01', '2099-01-02', 'deep',
                        '{}', '{}'
                    )
                    """
                )
            )

            snapshot = {
                "source_records": conn.execute(
                    text(
                        "SELECT id, stream_code, idempotency_key, record_status "
                        "FROM garmin_source_records ORDER BY id"
                    )
                ).fetchall(),
                "daily": conn.execute(
                    text("SELECT record_id, calendar_date FROM garmin_daily_records ORDER BY 1")
                ).fetchall(),
                "sleep": conn.execute(
                    text("SELECT record_id, wake_date FROM garmin_sleep_records ORDER BY 1")
                ).fetchall(),
                "activity": conn.execute(
                    text("SELECT record_id, activity_type FROM garmin_activity_records ORDER BY 1")
                ).fetchall(),
                "intraday": conn.execute(
                    text(
                        "SELECT record_id, sample_date, sample_sequence "
                        "FROM garmin_intraday_records ORDER BY 1"
                    )
                ).fetchall(),
                "fit": conn.execute(
                    text("SELECT record_id FROM garmin_fit_records ORDER BY 1")
                ).fetchall(),
                "metrics": conn.execute(
                    text(
                        "SELECT id, record_id, metric_code, state, value_number "
                        "FROM garmin_record_metrics ORDER BY 1"
                    )
                ).fetchall(),
                "stages": conn.execute(
                    text(
                        "SELECT id, sleep_record_id, ordinal, activity_level "
                        "FROM garmin_sleep_stage_intervals ORDER BY 1"
                    )
                ).fetchall(),
                "observations": conn.execute(
                    text(
                        "SELECT id, observation_key, record_count "
                        "FROM garmin_payload_observations ORDER BY 1"
                    )
                ).fetchall(),
                "checkpoints": conn.execute(
                    text(
                        "SELECT id, stream_code, cursor FROM sync_stream_state ORDER BY 1"
                    )
                ).fetchall(),
            }
    finally:
        engine.dispose()
    return snapshot


def _assert_head_integrity(paths, snapshot: dict[str, object]) -> None:
    readiness = database_readiness(paths)
    assert readiness["migration_revision"] == HEAD
    assert readiness["foreign_keys"] == 1
    assert readiness["ready"] is True

    engine = create_sqlite_engine(paths)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
            assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []
            assert (
                conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD
            )
            assert (
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM sqlite_master "
                        "WHERE type='table' AND name LIKE '_alembic_tmp_%'"
                    )
                ).scalar()
                == 0
            )

            columns = {col["name"] for col in inspect(conn).get_columns("garmin_source_records")}
            assert EXPECTED_0007_COLUMNS.issubset(columns)

            indexes = {idx["name"] for idx in inspect(conn).get_indexes("garmin_source_records")}
            assert "ix_garmin_source_records_collection" in indexes
            assert "ix_garmin_source_records_surface_date" in indexes

            create_sql = conn.execute(
                text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='table' AND name='garmin_source_records'"
                )
            ).scalar()
            assert create_sql is not None
            assert "projection_status_allowed" in create_sql
            assert "projection_retirement_consistency" in create_sql

            rows = conn.execute(
                text(
                    """
                    SELECT projection_status, retired_at, retire_reason,
                           reconciliation_contract_version
                    FROM garmin_source_records
                    ORDER BY id
                    """
                )
            ).fetchall()
            assert rows
            for projection_status, retired_at, retire_reason, version in rows:
                assert projection_status == "current"
                assert retired_at is None
                assert retire_reason is None
                assert version == PRE_RECONCILIATION_VERSION

            obs_versions = conn.execute(
                text(
                    "SELECT reconciliation_contract_version FROM garmin_payload_observations"
                )
            ).fetchall()
            assert obs_versions
            assert {row[0] for row in obs_versions} == {PRE_RECONCILIATION_VERSION}

            assert (
                conn.execute(
                    text(
                        "SELECT id, stream_code, idempotency_key, record_status "
                        "FROM garmin_source_records ORDER BY id"
                    )
                ).fetchall()
                == snapshot["source_records"]
            )
            assert (
                conn.execute(
                    text("SELECT record_id, calendar_date FROM garmin_daily_records ORDER BY 1")
                ).fetchall()
                == snapshot["daily"]
            )
            assert (
                conn.execute(
                    text("SELECT record_id, wake_date FROM garmin_sleep_records ORDER BY 1")
                ).fetchall()
                == snapshot["sleep"]
            )
            assert (
                conn.execute(
                    text(
                        "SELECT record_id, activity_type FROM garmin_activity_records ORDER BY 1"
                    )
                ).fetchall()
                == snapshot["activity"]
            )
            assert (
                conn.execute(
                    text(
                        "SELECT record_id, sample_date, sample_sequence "
                        "FROM garmin_intraday_records ORDER BY 1"
                    )
                ).fetchall()
                == snapshot["intraday"]
            )
            assert (
                conn.execute(text("SELECT record_id FROM garmin_fit_records ORDER BY 1")).fetchall()
                == snapshot["fit"]
            )
            assert (
                conn.execute(
                    text(
                        "SELECT id, record_id, metric_code, state, value_number "
                        "FROM garmin_record_metrics ORDER BY 1"
                    )
                ).fetchall()
                == snapshot["metrics"]
            )
            assert (
                conn.execute(
                    text(
                        "SELECT id, sleep_record_id, ordinal, activity_level "
                        "FROM garmin_sleep_stage_intervals ORDER BY 1"
                    )
                ).fetchall()
                == snapshot["stages"]
            )
            assert (
                conn.execute(
                    text(
                        "SELECT id, observation_key, record_count "
                        "FROM garmin_payload_observations ORDER BY 1"
                    )
                ).fetchall()
                == snapshot["observations"]
            )
            assert (
                conn.execute(
                    text("SELECT id, stream_code, cursor FROM sync_stream_state ORDER BY 1")
                ).fetchall()
                == snapshot["checkpoints"]
            )
    finally:
        engine.dispose()


def test_fresh_database_migrates_to_head(tmp_path: Path) -> None:
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    migrate_database(paths)
    assert database_readiness(paths)["migration_revision"] == HEAD
    engine = create_sqlite_engine(paths)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
            assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []
    finally:
        engine.dispose()


def test_populated_0006_upgrades_to_head_preserving_identities(tmp_path: Path) -> None:
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    _upgrade(paths, REV_0006)
    assert database_readiness(paths)["migration_revision"] == REV_0006
    snapshot = _seed_populated_0006(paths)

    migrate_database(paths)
    _assert_head_integrity(paths, snapshot)


def test_empty_alembic_temp_from_failed_0007_recovers_to_head(tmp_path: Path) -> None:
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    _upgrade(paths, REV_0006)
    snapshot = _seed_populated_0006(paths)

    # Simulate the owner-observed failed batch: stamp stays at 0006, business
    # rows intact, empty Alembic temp with the post-0007 column set remains.
    engine = create_engine(
        f"sqlite:///{paths.database.resolve().as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.execute(
                text(
                    f"""
                    CREATE TABLE {TEMP_SOURCE_RECORDS} (
                        id VARCHAR(36) NOT NULL,
                        garmin_source_id VARCHAR(36) NOT NULL,
                        raw_payload_id VARCHAR(36) NOT NULL,
                        ingest_event_id VARCHAR(36),
                        stream_code VARCHAR(40) NOT NULL,
                        idempotency_key VARCHAR(128) NOT NULL,
                        external_record_id VARCHAR(255),
                        record_index INTEGER,
                        activity_type VARCHAR(120),
                        source_path VARCHAR(255),
                        temporal_precision VARCHAR(20) NOT NULL,
                        source_local_date DATE,
                        source_timestamp_utc DATETIME,
                        local_wall_time VARCHAR(100),
                        source_local_timestamp VARCHAR(100),
                        source_utc_offset_minutes INTEGER,
                        source_timezone VARCHAR(100),
                        source_field VARCHAR(255),
                        source_local_field VARCHAR(255),
                        source_utc_field VARCHAR(255),
                        record_status VARCHAR(20) NOT NULL,
                        normalization_contract_version VARCHAR(120) NOT NULL,
                        diagnostics_json TEXT,
                        unknown_fields_json TEXT,
                        created_at DATETIME NOT NULL,
                        last_seen_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL,
                        surface_code VARCHAR(40),
                        collection_key VARCHAR(128),
                        projection_status VARCHAR(20) DEFAULT 'current' NOT NULL,
                        projection_observed_at DATETIME,
                        retired_at DATETIME,
                        retire_reason VARCHAR(80),
                        reconciliation_contract_version VARCHAR(120)
                            DEFAULT '{PRE_RECONCILIATION_VERSION}' NOT NULL,
                        PRIMARY KEY (id)
                    )
                    """
                )
            )
            assert (
                conn.execute(text(f"SELECT COUNT(*) FROM {TEMP_SOURCE_RECORDS}")).scalar() == 0
            )
            assert (
                conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == REV_0006
            )
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    finally:
        engine.dispose()

    migrate_database(paths)
    _assert_head_integrity(paths, snapshot)


def test_non_empty_alembic_temp_fails_closed(tmp_path: Path) -> None:
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    _upgrade(paths, REV_0006)
    snapshot = _seed_populated_0006(paths)

    engine = create_engine(
        f"sqlite:///{paths.database.resolve().as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.execute(
                text(
                    f"""
                    CREATE TABLE {TEMP_SOURCE_RECORDS} (
                        id VARCHAR(36) NOT NULL,
                        garmin_source_id VARCHAR(36) NOT NULL,
                        raw_payload_id VARCHAR(36) NOT NULL,
                        stream_code VARCHAR(40) NOT NULL,
                        idempotency_key VARCHAR(128) NOT NULL,
                        temporal_precision VARCHAR(20) NOT NULL,
                        record_status VARCHAR(20) NOT NULL,
                        normalization_contract_version VARCHAR(120) NOT NULL,
                        PRIMARY KEY (id)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    f"""
                    INSERT INTO {TEMP_SOURCE_RECORDS} (
                        id, garmin_source_id, raw_payload_id, stream_code, idempotency_key,
                        temporal_precision, record_status, normalization_contract_version
                    )
                    VALUES (
                        'temp-row', 'gs-1', 'grp-1', 'daily_health', 'temp-key',
                        'date', 'ok', 'r02-garmin-normalization-contract-v1'
                    )
                    """
                )
            )
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="refusing to clean non-empty"):
        migrate_database(paths)

    engine = create_sqlite_engine(paths)
    try:
        with engine.connect() as conn:
            assert (
                conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == REV_0006
            )
            assert (
                conn.execute(
                    text(
                        "SELECT id, stream_code, idempotency_key, record_status "
                        "FROM garmin_source_records ORDER BY id"
                    )
                ).fetchall()
                == snapshot["source_records"]
            )
            assert (
                conn.execute(
                    text(
                        "SELECT 1 FROM sqlite_master "
                        "WHERE type='table' AND name=:name"
                    ),
                    {"name": TEMP_SOURCE_RECORDS},
                ).first()
                is not None
            )
    finally:
        engine.dispose()


def test_fk_corruption_fails_closed_without_deleting_rows(tmp_path: Path) -> None:
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    _upgrade(paths, REV_0006)
    snapshot = _seed_populated_0006(paths)

    engine = create_engine(
        f"sqlite:///{paths.database.resolve().as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.execute(
                text(
                    "INSERT INTO garmin_daily_records (record_id, calendar_date) "
                    "VALUES ('missing-parent', '2099-06-01')"
                )
            )
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            assert conn.execute(text("PRAGMA foreign_key_check")).fetchall()
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="foreign_key_check"):
        migrate_database(paths)

    engine = create_sqlite_engine(paths)
    try:
        with engine.connect() as conn:
            # Fail closed: orphan row must still exist (not deleted/reparented).
            assert (
                conn.execute(
                    text(
                        "SELECT record_id FROM garmin_daily_records "
                        "WHERE record_id = 'missing-parent'"
                    )
                ).scalar()
                == "missing-parent"
            )
            assert (
                conn.execute(
                    text(
                        "SELECT id, stream_code, idempotency_key, record_status "
                        "FROM garmin_source_records ORDER BY id"
                    )
                ).fetchall()
                == snapshot["source_records"]
            )
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
    finally:
        engine.dispose()
