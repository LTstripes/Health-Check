"""Synthetic byte preservation, replay, interruption and on-disk size checks."""

import hashlib
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime

import pytest
from alembic import command
from scripts.google_projection_dry_run import measure
from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError

from healthcheck.config import Settings
from healthcheck.db.engine import (
    _alembic_config,
    create_session_factory,
    create_sqlite_engine,
    migrate_database,
)
from healthcheck.db.models import GoogleNormalizationAttempt, GooglePayloadObservation
from healthcheck.db.repositories import canonical_json
from healthcheck.google.contracts import (
    GoogleQueryContext,
    GoogleQueryMode,
    GoogleSourceIdentity,
    GoogleSourceKind,
    GoogleStream,
)
from healthcheck.google.normalization import normalize_google_payload
from healthcheck.google.persistence import GooglePersistenceRepository
from healthcheck.google.projection_storage import ERROR, compress_projection, read_projection
from healthcheck.google.replay import _observation_record_names, replay_google_observations
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from healthcheck.runtime import prepare_runtime

HEAD = "0023_google_projection_compression"
OLD = "0022_google_freshness_lookup"
TABLE = "google_normalization_attempts"


def encoded(projection):
    fingerprint = hashlib.sha256(projection.encode("utf-8")).hexdigest()
    return dict(compress_projection(projection, fingerprint), projection_fingerprint=fingerprint)


@pytest.mark.parametrize("size", [0, 1, 2, 31, 255, 1024, 65537, 12 * 1024 * 1024])
def test_round_trip(size):
    value = ("\u0436\U0001f4ca\x00\r\nabc" * (size // 8 + 1))[:size]
    fields = encoded(value)
    assert fields["projection_size"] == len(value.encode("utf-8"))
    assert read_projection(fields) == value
    assert read_projection({"projection_json": value,
                            "projection_fingerprint": fields["projection_fingerprint"]}) == value


@pytest.mark.parametrize("mutation", [
    {"projection_blob": b"broken"}, {"projection_size": 1},
    {"projection_size": -1}, {"projection_size": True},
    {"projection_sha256": "0" * 64}, {"projection_fingerprint": "0" * 64},
    {"projection_codec": "unknown"}, {"projection_json": "different"},
    {"projection_blob": None},
])
def test_fixed_integrity_error(mutation):
    fields = encoded("a projection") | mutation
    with pytest.raises(ValueError, match=f"^{ERROR}$"):
        read_projection(fields)


@pytest.mark.parametrize("mutation", [lambda b: b[:-1], lambda b: b + b"tail"])
def test_incomplete_or_trailing_zlib_fails(mutation):
    fields = encoded("projection")
    fields["projection_blob"] = mutation(fields["projection_blob"])
    with pytest.raises(ValueError, match=f"^{ERROR}$"):
        read_projection(fields)


def test_writer_rejects_fingerprint_not_matching_bytes():
    with pytest.raises(ValueError, match=f"^{ERROR}$"):
        compress_projection("projection", "0" * 64)


@pytest.fixture
def database(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    store = ContentAddressedGooglePayloadStore(paths.root / "artifacts")
    try:
        yield paths, engine, store
    finally:
        engine.dispose()


def seed(database, count=241):
    paths, engine, store = database
    identity = GoogleSourceIdentity(
        source_kind=GoogleSourceKind.DATA_SOURCE,
        source_instance_id="users/me/dataSources/synthetic-projection",
    )
    payload = {"dataPoints": [{"name": "synthetic-point", "heartRate": {
        "sampleTime": {"physicalTime": "2099-01-02T05:00:00Z", "utcOffset": "0s"},
        "beatsPerMinute": "72",
    }}]}
    result = normalize_google_payload(
        payload, stream=GoogleStream.HEART_RATE,
        query=GoogleQueryContext(GoogleQueryMode.LIST), source_identity=identity,
    )
    assert result.status.value == "ok" and len(result.records) == 1
    with create_session_factory(engine)() as session:
        outcome = GooglePersistenceRepository(session, payload_store=store).persist_result(
            result, payload=payload, received_at=datetime(2099, 1, 3, tzinfo=UTC),
        )
        attempt = outcome.normalization_attempt
        assert attempt.projection_json is None
        assert attempt.projection_blob and attempt.projection_codec == "zlib-1"
        assert read_projection(attempt) == canonical_json(result.as_dict())
        # Production writer retries compare the verified body, not NULL legacy text.
        repeated = GooglePersistenceRepository(session, payload_store=store).persist_result(
            result, payload=payload, received_at=datetime(2099, 1, 3, tzinfo=UTC),
        )
        assert repeated.normalization_attempt.id == attempt.id
        original = dict(session.execute(select(GoogleNormalizationAttempt.__table__)).mappings()
                        .one())
        # Large repetitive unknown fields model full historical DTOs. Membership
        # and fingerprint are still literal and internally consistent for every row.
        for index in range(1, count):
            projection = canonical_json(result.as_dict() | {
                "synthetic_unknown": "abc\u0436\n" * 16000, "index": index,
            })
            fields = compress_projection(projection, hashlib.sha256(
                projection.encode("utf-8")
            ).hexdigest())
            session.execute(insert(GoogleNormalizationAttempt).values(original | fields | {
                "id": f"synthetic-attempt-{index:04}",
                "attempt_key": f"synthetic-attempt-key-{index:032}",
                "projection_fingerprint": fields["projection_sha256"],
            }))
        session.commit()
        return outcome.observation.id


def bodies(paths):
    with closing(sqlite3.connect(paths.database)) as connection:
        connection.row_factory = sqlite3.Row
        return {row["id"]: read_projection(dict(row)).encode("utf-8") for row in
                connection.execute(f"SELECT * FROM {TABLE} ORDER BY id")}


def ownership(database, observation_id):
    _, engine, _ = database
    with create_session_factory(engine)() as session:
        observation = session.get(GooglePayloadObservation, observation_id)
        return _observation_record_names(session, observation)


def replay(database, observation_id):
    _, engine, store = database
    with create_session_factory(engine)() as session:
        outcomes = replay_google_observations(
            session, payload_store=store, observation_ids=[observation_id],
        )
        signature = [(outcome.observation.id, tuple(record.id for record in outcome.records),
                      outcome.inserted_count, outcome.updated_count, outcome.replayed)
                     for outcome in outcomes]
        session.commit()
        return signature


def test_migration_round_trip_replay_size_and_dry_run(database):
    paths, engine, _ = database
    observation_id = seed(database)
    expected = bodies(paths)
    # Exercise production replay against legacy text before the migration, with
    # the additive nullable columns present so the current ORM can read it.
    with engine.begin() as connection:
        trigger = connection.scalar(text(
            "SELECT sql FROM sqlite_master WHERE name="
            "'immutable_google_normalization_attempts_update'"
        ))
        connection.exec_driver_sql("DROP TRIGGER immutable_google_normalization_attempts_update")
        for attempt_id, body in expected.items():
            connection.execute(text(
                f"UPDATE {TABLE} SET projection_json=:body, projection_blob=NULL, "
                "projection_codec=NULL, projection_size=NULL, projection_sha256=NULL WHERE id=:id"
            ), {"id": attempt_id, "body": body.decode("utf-8")})
        connection.exec_driver_sql(trigger)
    baseline_ownership = ownership(database, observation_id)
    assert baseline_ownership == frozenset({"synthetic-point"})
    baseline_replay = replay(database, observation_id)
    engine.dispose()
    command.downgrade(_alembic_config(paths), OLD)
    with closing(sqlite3.connect(paths.database)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        connection.execute("VACUUM")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        legacy = dict(connection.execute(f"SELECT id, projection_json FROM {TABLE}"))
        assert {key: value.encode("utf-8") for key, value in legacy.items()} == expected
    before = paths.database.stat().st_size
    before_bytes = paths.database.read_bytes()
    measurement = measure(paths.database, 48)
    assert measurement["verified"] == 48 and measurement["failed"] == 0
    assert measurement["compressed_to_uncompressed"] < 0.1
    assert paths.database.read_bytes() == before_bytes
    migrate_database(paths)
    assert bodies(paths) == expected
    assert ownership(database, observation_id) == baseline_ownership
    assert replay(database, observation_id) == baseline_replay
    with engine.connect() as connection:
        assert connection.scalar(text(f"SELECT count(*) FROM {TABLE}")) == 241
        assert connection.scalar(text(f"SELECT count(*) FROM {TABLE} "
                                      "WHERE projection_json IS NOT NULL")) == 0
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
        with pytest.raises(IntegrityError, match="append-only"):
            connection.exec_driver_sql(f"UPDATE {TABLE} SET record_count=0")
        connection.rollback()
        with pytest.raises(IntegrityError, match="append-only"):
            connection.exec_driver_sql(f"DELETE FROM {TABLE}")
    engine.dispose()
    with closing(sqlite3.connect(paths.database)) as connection:
        connection.execute("VACUUM")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    after = paths.database.stat().st_size
    assert after / before < 0.2
    # Retained in focused pytest -rP output for the task report.
    print(f"Synthetic DB bytes: before={before} after={after} ratio={after / before:.6f}")
    assert measure(paths.database, 48)["verified"] == 48
    command.downgrade(_alembic_config(paths), OLD)
    with closing(sqlite3.connect(paths.database)) as connection:
        restored = dict(connection.execute(f"SELECT id, projection_json FROM {TABLE}"))
        assert {key: value.encode("utf-8") for key, value in restored.items()} == expected


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_interrupted_migration_resumes_verified_batches(database, monkeypatch, direction):
    paths, engine, _ = database
    seed(database, count=61)
    expected = bodies(paths)
    engine.dispose()
    if direction == "upgrade":
        command.downgrade(_alembic_config(paths), OLD)
    def interrupt(converted, verified):
        raise RuntimeError("synthetic interruption")

    # Alembic imports its own revision module. Patch the shared logger callback
    # on all loaded revision copies through ScriptDirectory's cached revision map.
    from alembic.script import ScriptDirectory
    script = ScriptDirectory.from_config(_alembic_config(paths))
    revision = script.get_revision(HEAD).module
    progress = revision._progress
    monkeypatch.setattr(revision, "_progress", interrupt)
    monkeypatch.setattr(ScriptDirectory, "from_config", lambda config: script)
    migrate = command.upgrade if direction == "upgrade" else command.downgrade
    target = HEAD if direction == "upgrade" else OLD
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        migrate(_alembic_config(paths), target)
    shadow = "_gproj_0023_compress" if direction == "upgrade" else "_gproj_0023_restore"
    with closing(sqlite3.connect(paths.database)) as connection:
        assert connection.execute(f"SELECT count(*) FROM {shadow}").fetchone() == (16,)
        assert connection.execute(f"SELECT count(*) FROM {TABLE}").fetchone() == (61,)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            OLD if direction == "upgrade" else HEAD,
        )
    resumed = []

    def observe_resume(converted, verified):
        resumed.append((converted, verified))
        progress(converted, verified)

    monkeypatch.setattr(revision, "_progress", observe_resume)
    migrate(_alembic_config(paths), target)
    assert resumed[0] == (0, 16)  # Already committed rows verified and skipped.
    assert resumed[-1] == (45, 16)
    assert bodies(paths) == expected
    with closing(sqlite3.connect(paths.database)) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            target,
        )


@pytest.mark.parametrize("failure", ["swap", "corrupt_source", "corrupt_resume"])
def test_migration_failure_preserves_source_and_revision(database, monkeypatch, failure):
    from alembic.script import ScriptDirectory

    paths, engine, _ = database
    seed(database, count=35)
    expected = bodies(paths)
    engine.dispose()
    command.downgrade(_alembic_config(paths), OLD)
    script = ScriptDirectory.from_config(_alembic_config(paths))
    revision = script.get_revision(HEAD).module
    monkeypatch.setattr(ScriptDirectory, "from_config", lambda config: script)
    upgrade, progress = revision.upgrade, revision._progress
    if failure == "swap":
        def interrupt_after_swap():
            upgrade()
            raise RuntimeError("synthetic failure before stamp")

        monkeypatch.setattr(revision, "upgrade", interrupt_after_swap)
        with pytest.raises(RuntimeError, match="synthetic failure before stamp"):
            command.upgrade(_alembic_config(paths), HEAD)
        monkeypatch.setattr(revision, "upgrade", upgrade)
    elif failure == "corrupt_source":
        with closing(sqlite3.connect(paths.database)) as connection:
            connection.execute("DROP TRIGGER immutable_google_normalization_attempts_update")
            connection.execute(f"UPDATE {TABLE} SET projection_fingerprint=?", ("0" * 64,))
            connection.commit()
        with pytest.raises(ValueError, match=f"^{ERROR}$"):
            command.upgrade(_alembic_config(paths), HEAD)
    else:
        def interrupt(converted, verified):
            raise RuntimeError("synthetic interruption")

        monkeypatch.setattr(revision, "_progress", interrupt)
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            command.upgrade(_alembic_config(paths), HEAD)
        with closing(sqlite3.connect(paths.database)) as connection:
            connection.execute("UPDATE _gproj_0023_compress SET projection_blob=x'00'")
            connection.commit()
        monkeypatch.setattr(revision, "_progress", progress)
        with pytest.raises(ValueError, match=f"^{ERROR}$"):
            command.upgrade(_alembic_config(paths), HEAD)
    with closing(sqlite3.connect(paths.database)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (OLD,)
        legacy = dict(connection.execute(f"SELECT id, projection_json FROM {TABLE}"))
        assert {key: value.encode("utf-8") for key, value in legacy.items()} == expected
    if failure == "swap":
        command.upgrade(_alembic_config(paths), HEAD)
        assert bodies(paths) == expected


def test_dry_run_cli_does_not_write_or_disclose_bodies(tmp_path):
    database = tmp_path / "copy.db"
    value = "synthetic private body"
    fingerprint = hashlib.sha256(value.encode()).hexdigest()
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(f"CREATE TABLE {TABLE} "
                           "(id TEXT, projection_json TEXT, projection_fingerprint TEXT)")
        connection.execute(f"INSERT INTO {TABLE} VALUES ('1', ?, ?)", (value, fingerprint))
        connection.commit()
    before = database.read_bytes()
    result = subprocess.run([
        sys.executable, "scripts/google_projection_dry_run.py", "--db-copy", str(database),
        "--samples", "1",
    ], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["verified"] == 1
    assert value not in result.stdout + result.stderr
    assert database.read_bytes() == before
    assert not list(tmp_path.glob("copy.db-*"))
    (tmp_path / "copy.db-wal").write_bytes(b"outstanding WAL")
    with pytest.raises(ValueError, match="closed checkpointed DB copy required"):
        measure(database, 1)
