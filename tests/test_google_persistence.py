"""Offline R04 Google Health persistence, migration, and identity contract tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from alembic import command
from sqlalchemy import func, inspect, select, text

from healthcheck.config import Settings
from healthcheck.db.engine import (
    _alembic_config,
    create_session_factory,
    create_sqlite_engine,
    database_readiness,
    migrate_database,
)
from healthcheck.db.models import (
    GarminRawPayload,
    GarminSource,
    GarminSourceRecord,
    GooglePayloadObservation,
    GoogleRawPayload,
    GoogleRecordMetric,
    GoogleSleepRecord,
    GoogleSource,
    GoogleSourceRecord,
    PhysicalDevice,
    RawArtifact,
)
from healthcheck.google.contracts import (
    FAMILY_ALL_SOURCES,
    FAMILY_GOOGLE_SOURCES,
    FAMILY_GOOGLE_WEARABLES,
    GoogleMetricDTO,
    GoogleMetricState,
    GoogleQueryContext,
    GoogleQueryMode,
    GoogleRecordDTO,
    GoogleSourceIdentity,
    GoogleSourceKind,
    GoogleStream,
    GoogleTemporalDTO,
    GoogleTemporalPrecision,
)
from healthcheck.google.normalization import normalize_google_payload
from healthcheck.google.persistence import GooglePersistenceRepository
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from healthcheck.runtime import prepare_runtime

HEAD = "0013_garmin_training_evidence"
PRE_R04 = "0008_garmin_observation_reconciliation_version"
GOOGLE_TABLES = {
    "google_sources",
    "google_raw_payloads",
    "google_payload_observations",
    "google_source_records",
    "google_sleep_records",
    "google_record_metrics",
    "google_record_intervals",
    "google_sleep_intervals",
    "google_sleep_field_states",
    "google_record_source_evidence",
    "google_normalization_attempts",
}
FITBIT_DATASOURCE = (
    "users/me/dataSources/raw:com.google.heart_rate.bpm:com.fitbit.Fitbit:ABC123"
)


@pytest.fixture
def persistence_database(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            yield paths, session, ContentAddressedGooglePayloadStore(paths.root / "artifacts")
    finally:
        engine.dispose()


def _repo(session, store):
    return GooglePersistenceRepository(session, payload_store=store)


def _fitbit_identity(**overrides) -> GoogleSourceIdentity:
    values = {
        "source_kind": GoogleSourceKind.DATA_SOURCE,
        "source_instance_id": FITBIT_DATASOURCE,
        "data_source_name": FITBIT_DATASOURCE,
        "data_source_id": "raw:com.google.heart_rate.bpm:com.fitbit.Fitbit:ABC123",
        "platform": "fitbit",
        "recording_method": "automatic",
        "device_attributed": True,
        "device_code": "fitbit_air",
        "device_manufacturer": "Fitbit",
        "device_model": "Fitbit Air",
        "device_uid": "ABC123",
    }
    values.update(overrides)
    return GoogleSourceIdentity(**values)


def _family_identity(family: str = FAMILY_GOOGLE_WEARABLES) -> GoogleSourceIdentity:
    return GoogleSourceIdentity(
        source_kind=GoogleSourceKind.FAMILY_AGGREGATE,
        source_instance_id=family,
    )


def _query(mode, family=None) -> GoogleQueryContext:
    return GoogleQueryContext(query_mode=mode, data_source_family=family)


def _hr_record(*, idempotency="hr:2099-01-02", value_number=72.0, value_text=None, state=None):
    metric_state = state or GoogleMetricState.VALUE
    return GoogleRecordDTO(
        stream=GoogleStream.HEART_RATE,
        idempotency_key=idempotency,
        external_record_id=idempotency,
        temporal=GoogleTemporalDTO(
            precision=GoogleTemporalPrecision.INSTANT,
            local_date=date(2099, 1, 2),
            measured_at_utc=datetime(2099, 1, 2, 8, 0, tzinfo=UTC),
            source_utc_offset_minutes=180,
            source_timezone="Europe/Moscow",
        ),
        metrics=(
            GoogleMetricDTO(
                metric_code="heart_rate_bpm",
                field_path="$.heartRate",
                state=metric_state,
                value_number=value_number if metric_state is GoogleMetricState.VALUE else None,
                value_text=value_text if metric_state is GoogleMetricState.VALUE else None,
                unit="bpm",
            ),
        ),
    )


def _sleep_record():
    return GoogleRecordDTO(
        stream=GoogleStream.SLEEP,
        idempotency_key="sleep:2099-01-02",
        external_record_id="sleep-1",
        wake_date=date(2099, 1, 2),
        temporal=GoogleTemporalDTO(
            precision=GoogleTemporalPrecision.DATE,
            local_date=date(2099, 1, 2),
        ),
        metrics=(
            GoogleMetricDTO(
                metric_code="sleep_duration_seconds",
                field_path="$.duration",
                state=GoogleMetricState.VALUE,
                value_number=28800,
                unit="s",
            ),
        ),
    )


def test_fresh_database_upgrades_to_head(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    migrate_database(paths)
    readiness = database_readiness(paths)
    assert readiness["migration_revision"] == HEAD
    assert readiness["foreign_keys"] == 1
    engine = create_sqlite_engine(paths)
    try:
        tables = set(inspect(engine).get_table_names())
        assert GOOGLE_TABLES <= tables
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
            assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []
    finally:
        engine.dispose()


def test_populated_pre_r04_database_upgrades_preserving_r01_r03(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    config = _alembic_config(paths)
    command.upgrade(config, PRE_R04)
    assert database_readiness(paths)["migration_revision"] == PRE_R04

    engine = create_sqlite_engine(paths)
    content_hash = "b" * 64
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO providers (id, code, display_name, provider_kind, created_at)
                    VALUES ('prov-g', 'garmin_connect', 'Garmin Connect', 'wearable',
                            CURRENT_TIMESTAMP)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO acquisition_sources (
                        id, provider_id, input_method, source_instance_id, created_at
                    )
                    VALUES ('acq-g', 'prov-g', 'provider_api', 'synthetic-src-86',
                            CURRENT_TIMESTAMP)
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
                        'gs-86', 'prov-g', 'acq-g', 'synthetic', 'garmin_connect',
                        'synthetic-src-86', 0, CURRENT_TIMESTAMP
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
                        'ra-86', :hash, 'garmin_payload', 'application/json', 2,
                        'garmin/bb/seed.json', CURRENT_TIMESTAMP
                    )
                    """
                ),
                {"hash": content_hash},
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
                        'grp-86', 'gs-86', 'ra-86', 'daily_health', :hash, 'json',
                        'r02-garmin-normalization-contract-v1', 'ok', 1,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """
                ),
                {"hash": content_hash},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO garmin_source_records (
                        id, garmin_source_id, raw_payload_id, stream_code, idempotency_key,
                        temporal_precision, record_status, normalization_contract_version,
                        created_at, last_seen_at, updated_at
                    )
                    VALUES (
                        'gsr-86', 'gs-86', 'grp-86', 'daily_health', 'daily:2099-01-01',
                        'date', 'ok', 'r02-garmin-normalization-contract-v1',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            snapshot = {
                "providers": conn.execute(
                    text("SELECT id, code FROM providers ORDER BY 1")
                ).fetchall(),
                "garmin_sources": conn.execute(
                    text("SELECT id, source_instance_id FROM garmin_sources ORDER BY 1")
                ).fetchall(),
                "garmin_payloads": conn.execute(
                    text("SELECT id, content_hash FROM garmin_raw_payloads ORDER BY 1")
                ).fetchall(),
                "garmin_records": conn.execute(
                    text("SELECT id, idempotency_key FROM garmin_source_records ORDER BY 1")
                ).fetchall(),
                "raw_artifacts": conn.execute(
                    text("SELECT id, content_hash FROM raw_artifacts ORDER BY 1")
                ).fetchall(),
            }
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    readiness = database_readiness(paths)
    assert readiness["migration_revision"] == HEAD
    assert readiness["foreign_keys"] == 1

    engine = create_sqlite_engine(paths)
    try:
        tables = set(inspect(engine).get_table_names())
        assert GOOGLE_TABLES <= tables
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
            assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []
            assert (
                conn.execute(text("SELECT id, code FROM providers ORDER BY 1")).fetchall()
                == snapshot["providers"]
            )
            assert (
                conn.execute(
                    text("SELECT id, source_instance_id FROM garmin_sources ORDER BY 1")
                ).fetchall()
                == snapshot["garmin_sources"]
            )
            assert (
                conn.execute(
                    text("SELECT id, content_hash FROM garmin_raw_payloads ORDER BY 1")
                ).fetchall()
                == snapshot["garmin_payloads"]
            )
            assert (
                conn.execute(
                    text("SELECT id, idempotency_key FROM garmin_source_records ORDER BY 1")
                ).fetchall()
                == snapshot["garmin_records"]
            )
            assert (
                conn.execute(
                    text("SELECT id, content_hash FROM raw_artifacts ORDER BY 1")
                ).fetchall()
                == snapshot["raw_artifacts"]
            )
            assert conn.execute(text("SELECT COUNT(*) FROM google_sources")).scalar() == 0
    finally:
        engine.dispose()


def test_populated_0009_google_shell_upgrades_to_0010_without_loss(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    config = _alembic_config(paths)
    command.upgrade(config, "0009_google_persistence_contract")
    engine = create_sqlite_engine(paths)
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            outcome = _repo(
                session,
                ContentAddressedGooglePayloadStore(paths.root / "artifacts"),
            ).persist_observation(
                identity=_fitbit_identity(),
                query=_query(GoogleQueryMode.LIST),
                stream=GoogleStream.HEART_RATE,
                payload={"dataPoints": []},
                records=(),
                create_ingest_event=False,
                received_at=datetime(2099, 1, 2, tzinfo=UTC),
            )
            session.commit()
            source_id = outcome.source.id
            raw_payload_id = outcome.raw_payload.id
            observation_id = outcome.observation.id
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = create_sqlite_engine(paths)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT id FROM google_sources")).scalar() == source_id
            assert (
                conn.execute(text("SELECT id FROM google_raw_payloads")).scalar()
                == raw_payload_id
            )
            assert (
                conn.execute(text("SELECT id FROM google_payload_observations")).scalar()
                == observation_id
            )
            assert conn.execute(text("SELECT COUNT(*) FROM google_record_intervals")).scalar() == 0
            assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []
    finally:
        engine.dispose()


def test_identical_bytes_in_different_windows_share_artifact_not_observation(
    persistence_database,
):
    _paths, session, store = persistence_database
    repo = _repo(session, store)
    payload = {"heartRate": [{"value": "72"}]}
    first = repo.persist_observation(
        identity=_fitbit_identity(),
        query=_query(GoogleQueryMode.LIST),
        stream=GoogleStream.HEART_RATE,
        payload=payload,
        records=(_hr_record(),),
        source_window_start_utc=datetime(2099, 1, 1, tzinfo=UTC),
        source_window_end_utc=datetime(2099, 1, 2, tzinfo=UTC),
        sync_run_id=None,
        source_filename="window-1.json",
        received_at=datetime(2099, 1, 2, 12, tzinfo=UTC),
    )
    session.flush()
    second = repo.persist_observation(
        identity=_fitbit_identity(),
        query=_query(GoogleQueryMode.LIST),
        stream=GoogleStream.HEART_RATE,
        payload=payload,
        records=(_hr_record(),),
        source_window_start_utc=datetime(2099, 1, 2, tzinfo=UTC),
        source_window_end_utc=datetime(2099, 1, 3, tzinfo=UTC),
        source_filename="window-2.json",
        received_at=datetime(2099, 1, 3, 12, tzinfo=UTC),
    )
    session.commit()

    assert first.source.id == second.source.id
    assert first.raw_payload.id == second.raw_payload.id
    assert first.observation.id != second.observation.id
    assert session.scalar(select(func.count(GoogleRawPayload.id))) == 1
    assert session.scalar(select(func.count(RawArtifact.id))) == 1
    assert session.scalar(select(func.count(GooglePayloadObservation.id))) == 2
    assert first.observation.source_filename == "window-1.json"
    assert second.observation.source_filename == "window-2.json"


def test_exact_observation_retry_converges_idempotently(persistence_database):
    _paths, session, store = persistence_database
    repo = _repo(session, store)
    kwargs = {
        "identity": _fitbit_identity(),
        "query": _query(GoogleQueryMode.LIST),
        "stream": GoogleStream.HEART_RATE,
        "payload": {"heartRate": [{"value": "72"}]},
        "records": (_hr_record(),),
        "source_window_start_utc": datetime(2099, 1, 1, tzinfo=UTC),
        "source_window_end_utc": datetime(2099, 1, 2, tzinfo=UTC),
        "source_filename": "retry.json",
        "received_at": datetime(2099, 1, 2, 12, tzinfo=UTC),
    }
    first = repo.persist_observation(**kwargs)
    session.flush()
    retry = repo.persist_observation(**kwargs)
    session.commit()

    assert retry.replayed is True
    assert retry.observation.id == first.observation.id
    assert retry.raw_payload.id == first.raw_payload.id
    assert session.scalar(select(func.count(GooglePayloadObservation.id))) == 1
    assert session.scalar(select(func.count(GoogleSourceRecord.id))) == 1


def test_list_reconcile_rollup_family_cannot_collide_in_observation_identity(
    persistence_database,
):
    _paths, session, store = persistence_database
    repo = _repo(session, store)
    payload = {"heartRate": [{"value": "72"}]}
    identity = _fitbit_identity()
    window = {
        "source_window_start_utc": datetime(2099, 1, 1, tzinfo=UTC),
        "source_window_end_utc": datetime(2099, 1, 2, tzinfo=UTC),
    }
    contexts = (
        _query(GoogleQueryMode.LIST),
        _query(GoogleQueryMode.RECONCILE, FAMILY_GOOGLE_WEARABLES),
        _query(GoogleQueryMode.ROLL_UP, FAMILY_GOOGLE_WEARABLES),
        _query(GoogleQueryMode.DAILY_ROLL_UP, FAMILY_GOOGLE_WEARABLES),
        _query(GoogleQueryMode.LIST, FAMILY_ALL_SOURCES),
    )
    outcomes = [
        repo.persist_observation(
            identity=identity,
            query=context,
            stream=GoogleStream.HEART_RATE,
            payload=payload,
            records=(_hr_record(),),
            **window,
        )
        for context in contexts
    ]
    session.commit()

    keys = [item.observation.observation_key for item in outcomes]
    assert len(set(keys)) == len(keys)
    assert {item.source.id for item in outcomes} == {outcomes[0].source.id}
    assert session.scalar(select(func.count(GooglePayloadObservation.id))) == 5
    assert session.scalar(select(func.count(GoogleSource.id))) == 1


def test_same_datasource_through_query_modes_is_one_google_source(persistence_database):
    _paths, session, store = persistence_database
    repo = _repo(session, store)
    identity = _fitbit_identity()
    for mode, family in (
        (GoogleQueryMode.LIST, None),
        (GoogleQueryMode.RECONCILE, FAMILY_GOOGLE_WEARABLES),
        (GoogleQueryMode.ROLL_UP, FAMILY_GOOGLE_WEARABLES),
    ):
        repo.persist_observation(
            identity=identity,
            query=_query(mode, family),
            stream=GoogleStream.HEART_RATE,
            payload={"mode": mode.value},
            records=(_hr_record(),),
        )
    session.commit()
    assert session.scalar(select(func.count(GoogleSource.id))) == 1
    source = session.scalar(select(GoogleSource))
    assert source.source_instance_id == FITBIT_DATASOURCE
    assert source.source_kind == "data_source"


def test_google_wearables_without_device_metadata_stays_unattributed(persistence_database):
    _paths, session, store = persistence_database
    repo = _repo(session, store)
    outcome = repo.persist_observation(
        identity=_family_identity(),
        query=_query(GoogleQueryMode.ROLL_UP, FAMILY_GOOGLE_WEARABLES),
        stream=GoogleStream.HEART_RATE,
        payload={"family": "google-wearables"},
        records=(_hr_record(idempotency="family-hr"),),
    )
    session.commit()

    source = session.get(GoogleSource, outcome.source.id)
    assert source.source_kind == "family_aggregate"
    assert source.device_attributed is False
    assert source.physical_device_id is None
    assert source.device_code is None
    assert source.device_model is None
    assert session.scalar(select(func.count(PhysicalDevice.id))) == 0
    with pytest.raises(ValueError, match="cannot claim device attribution"):
        GoogleSourceIdentity(
            source_kind=GoogleSourceKind.FAMILY_AGGREGATE,
            source_instance_id=FAMILY_GOOGLE_WEARABLES,
            device_attributed=True,
            device_code="fitbit_air",
            device_model="Fitbit Air",
        )


def test_explicit_source_metadata_links_physical_device_without_inventing_fields(
    persistence_database,
):
    _paths, session, store = persistence_database
    repo = _repo(session, store)
    outcome = repo.persist_observation(
        identity=_fitbit_identity(),
        query=_query(GoogleQueryMode.LIST),
        stream=GoogleStream.HEART_RATE,
        payload={"device": "explicit"},
        records=(_hr_record(),),
    )
    session.commit()

    source = session.get(GoogleSource, outcome.source.id)
    assert source.device_attributed is True
    device = session.get(PhysicalDevice, source.physical_device_id)
    assert device is not None
    assert device.code == "fitbit_air"
    assert device.manufacturer == "Fitbit"
    assert device.model == "Fitbit Air"
    assert device.instance_identifier == "ABC123"
    with pytest.raises(ValueError, match="cannot carry invented device fields"):
        GoogleSourceIdentity(
            source_kind=GoogleSourceKind.DATA_SOURCE,
            source_instance_id=FITBIT_DATASOURCE,
            device_attributed=False,
            device_model="Fitbit Air",
        )


def test_family_aggregates_and_source_specific_list_are_separately_addressable(
    persistence_database,
):
    _paths, session, store = persistence_database
    repo = _repo(session, store)
    payload = {"heartRate": [{"value": "72"}]}
    listed = repo.persist_observation(
        identity=_fitbit_identity(),
        query=_query(GoogleQueryMode.LIST),
        stream=GoogleStream.HEART_RATE,
        payload=payload,
        records=(_hr_record(),),
    )
    family_record = normalize_google_payload(
        {
            "rollupDataPoints": [
                {
                    "startTime": "2099-01-02T05:00:00Z",
                    "endTime": "2099-01-02T06:00:00Z",
                    "heartRate": {"beatsPerMinuteAvg": "72"},
                }
            ]
        },
        stream=GoogleStream.HEART_RATE,
        query=_query(GoogleQueryMode.ROLL_UP, FAMILY_GOOGLE_WEARABLES),
    ).records
    family = repo.persist_observation(
        identity=_family_identity(),
        query=_query(GoogleQueryMode.ROLL_UP, FAMILY_GOOGLE_WEARABLES),
        stream=GoogleStream.HEART_RATE,
        payload=payload,
        records=family_record,
    )
    other_family = repo.persist_observation(
        identity=_family_identity(FAMILY_GOOGLE_SOURCES),
        query=_query(GoogleQueryMode.RECONCILE, FAMILY_GOOGLE_SOURCES),
        stream=GoogleStream.HEART_RATE,
        payload=payload,
        records=(_hr_record(idempotency="google-sources-hr"),),
    )
    session.commit()

    source_ids = {listed.source.id, family.source.id, other_family.source.id}
    assert len(source_ids) == 3
    assert listed.observation.id != family.observation.id
    assert session.scalar(select(func.count(GoogleSourceRecord.id))) == 3
    assert session.scalar(select(func.count(RawArtifact.id))) == 1
    assert session.scalar(select(func.count(GoogleRawPayload.id))) == 3


def test_metric_states_preserve_numeric_zero_as_explicit_value(persistence_database):
    _paths, session, store = persistence_database
    repo = _repo(session, store)
    cases = (
        ("zero", GoogleMetricState.VALUE, 0.0, None),
        ("missing", GoogleMetricState.MISSING, None, None),
        ("null", GoogleMetricState.NULL, None, None),
        ("invalid", GoogleMetricState.INVALID, None, None),
    )
    for label, state, number, text_value in cases:
        repo.persist_observation(
            identity=_fitbit_identity(source_instance_id=f"{FITBIT_DATASOURCE}:{label}"),
            query=_query(GoogleQueryMode.LIST),
            stream=GoogleStream.HEART_RATE,
            payload={"label": label},
            records=(
                _hr_record(
                    idempotency=f"hr:{label}",
                    value_number=number,
                    value_text=text_value,
                    state=state,
                ),
            ),
        )
    session.commit()

    stored = {
        item.metric_code + item.record_id: item
        for item in session.scalars(select(GoogleRecordMetric))
    }
    by_state = {item.state: item for item in session.scalars(select(GoogleRecordMetric))}
    assert by_state["value"].value_number == 0.0
    assert by_state["missing"].value_number is None
    assert by_state["null"].value_number is None
    assert by_state["invalid"].value_number is None
    assert len(stored) == 4


def test_string_encoded_provider_numerics_are_retained_without_coercion(persistence_database):
    _paths, session, store = persistence_database
    repo = _repo(session, store)
    outcome = repo.persist_observation(
        identity=_fitbit_identity(),
        query=_query(GoogleQueryMode.LIST),
        stream=GoogleStream.HEART_RATE,
        payload={"heartRate": [{"value": "072"}]},
        records=(_hr_record(value_number=None, value_text="072"),),
    )
    session.commit()

    metric = session.scalar(
        select(GoogleRecordMetric).where(GoogleRecordMetric.record_id == outcome.records[0].id)
    )
    assert metric.state == "value"
    assert metric.value_text == "072"
    assert metric.value_number is None


def test_google_persist_does_not_write_garmin_or_r03_tables(persistence_database):
    _paths, session, store = persistence_database
    before = {
        "garmin_sources": session.scalar(select(func.count(GarminSource.id))),
        "garmin_payloads": session.scalar(select(func.count(GarminRawPayload.id))),
        "garmin_records": session.scalar(select(func.count(GarminSourceRecord.id))),
    }
    _repo(session, store).persist_observation(
        identity=_fitbit_identity(),
        query=_query(GoogleQueryMode.LIST),
        stream=GoogleStream.SLEEP,
        payload={"sleep": []},
        records=(_sleep_record(),),
    )
    session.commit()
    assert session.scalar(select(func.count(GarminSource.id))) == before["garmin_sources"]
    assert session.scalar(select(func.count(GarminRawPayload.id))) == before["garmin_payloads"]
    assert session.scalar(select(func.count(GarminSourceRecord.id))) == before["garmin_records"]
    assert session.scalar(select(func.count(GoogleSleepRecord.record_id))) == 1


def test_foreign_key_check_clean_after_google_persist(persistence_database):
    paths, session, store = persistence_database
    _repo(session, store).persist_observation(
        identity=_fitbit_identity(),
        query=_query(GoogleQueryMode.LIST),
        stream=GoogleStream.HEART_RATE,
        payload={"ok": True},
        records=(_hr_record(),),
    )
    session.commit()
    engine = create_sqlite_engine(paths)
    try:
        with engine.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
            assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []
    finally:
        engine.dispose()


def test_raw_and_observation_rows_are_append_only(persistence_database):
    _paths, session, store = persistence_database
    outcome = _repo(session, store).persist_observation(
        identity=_fitbit_identity(),
        query=_query(GoogleQueryMode.LIST),
        stream=GoogleStream.HEART_RATE,
        payload={"ok": True},
        records=(_hr_record(),),
    )
    session.commit()
    raw_payload = session.get(GoogleRawPayload, outcome.raw_payload.id)
    observation = session.get(GooglePayloadObservation, outcome.observation.id)
    source = session.get(GoogleSource, outcome.source.id)
    with pytest.raises(Exception):
        with session.begin_nested():
            raw_payload.parse_status = "invalid"
            session.flush()
    with pytest.raises(Exception):
        with session.begin_nested():
            session.delete(source)
            session.flush()
    with pytest.raises(Exception):
        with session.begin_nested():
            observation.source_filename = "changed.json"
            session.flush()
    session.rollback()
    session.refresh(raw_payload)
    session.refresh(observation)
    assert raw_payload.parse_status == "ok"
    assert observation.source_filename is None


def test_sleep_record_preserves_wake_date_and_local_offset(persistence_database):
    _paths, session, store = persistence_database
    outcome = _repo(session, store).persist_observation(
        identity=_fitbit_identity(),
        query=_query(GoogleQueryMode.LIST),
        stream=GoogleStream.SLEEP,
        payload={"sleep": [{"wake": "2099-01-02"}]},
        records=(_sleep_record(),),
    )
    session.commit()
    typed = session.get(GoogleSleepRecord, outcome.records[0].id)
    assert typed is not None
    assert typed.wake_date == date(2099, 1, 2)
    record = session.get(GoogleSourceRecord, outcome.records[0].id)
    assert record.temporal_precision == "date"
    assert record.source_timestamp_utc is None
    assert record.query_mode == "list"
