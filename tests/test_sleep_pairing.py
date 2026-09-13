"""Synthetic persisted R05 pairing/source-eligibility regressions."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from healthcheck.analytics.sleep_pairing import (
    DEVICE_PAIR,
    SleepPairingQuery,
    read_persisted_sleep_pairing,
)
from healthcheck.config import Settings
from healthcheck.db.engine import create_session_factory, create_sqlite_engine, migrate_database
from healthcheck.db.models import GoogleSleepRecord, GoogleSource, GoogleSourceRecord
from healthcheck.garmin.normalization import normalize_garmin_payload
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.google.contracts import (
    FAMILY_ALL_SOURCES,
    FAMILY_GOOGLE_WEARABLES,
    GoogleQueryContext,
    GoogleQueryMode,
    GoogleSourceIdentity,
    GoogleSourceKind,
    GoogleStream,
)
from healthcheck.google.normalization import normalize_google_payload
from healthcheck.google.persistence import GooglePersistenceRepository
from healthcheck.google.storage import ContentAddressedGooglePayloadStore
from healthcheck.runtime import prepare_runtime

GARMIN_SLEEP_FIXTURE = Path(__file__).parent / "fixtures" / "garmin" / "sleep.json"
FITBIT_SOURCE = "users/me/dataSources/raw:com.google.sleep:com.fitbit.Fitbit:synthetic"


@pytest.fixture
def pairing_database(tmp_path):
    paths = prepare_runtime(Settings(data_dir=tmp_path / "runtime"))
    migrate_database(paths)
    engine = create_sqlite_engine(paths)
    try:
        with create_session_factory(engine)() as session:
            yield session, paths
    finally:
        engine.dispose()


def _persist_garmin(session, paths):
    payload = json.loads(GARMIN_SLEEP_FIXTURE.read_text(encoding="utf-8"))
    result = normalize_garmin_payload(payload)
    outcome = GarminPersistenceRepository(
        session,
        payload_store=ContentAddressedGarminPayloadStore(paths.root / "garmin-artifacts"),
    ).persist_result(result, payload=GARMIN_SLEEP_FIXTURE.read_bytes())
    return outcome


def _google_identity(
    *, family: str | None = None, source_instance_id: str = FITBIT_SOURCE
) -> GoogleSourceIdentity:
    if family is not None:
        return GoogleSourceIdentity(
            source_kind=GoogleSourceKind.FAMILY_AGGREGATE,
            source_instance_id=family,
        )
    return GoogleSourceIdentity(
        source_kind=GoogleSourceKind.DATA_SOURCE,
        source_instance_id=source_instance_id,
        platform="fitbit",
        recording_method="automatic",
    )


def _google_payload(
    *,
    name: str,
    main: bool | None = True,
    nap: bool | None = False,
    manually_edited: bool | None = False,
    data_source: bool = True,
) -> dict[str, object]:
    metadata = {
        key: value
        for key, value in {
            "main": main,
            "nap": nap,
            "manuallyEdited": manually_edited,
            "externalId": name,
        }.items()
        if value is not None
    }
    component: dict[str, object] = {
        "interval": {
            "startTime": "2099-01-01T22:00:00Z",
            "startUtcOffset": "10800s",
            "endTime": "2099-01-02T05:00:00Z",
            "endUtcOffset": "10800s",
            "civilStartTime": {"date": "2099-01-02", "time": "01:00:00", "zone": "Europe/Moscow"},
            "civilEndTime": {"date": "2099-01-02", "time": "08:00:00", "zone": "Europe/Moscow"},
        },
        "type": "STAGES",
        "stages": [],
        "outOfBedSegments": [],
        "metadata": metadata,
        "summary": {
            "minutesInSleepPeriod": "420",
            "minutesAfterWakeUp": "0",
            "minutesToFallAsleep": "10",
            "minutesAsleep": "410",
            "minutesAwake": "10",
            "stagesSummary": [],
        },
        "updateTime": "2099-01-02T08:04:00Z",
    }
    point: dict[str, object] = {"name": name, "sleep": component}
    if data_source:
        point["dataSource"] = {
            "recordingMethod": "AUTOMATIC",
            "platform": "fitbit",
            "device": {
                "formFactor": "WATCH",
                "manufacturer": "Fitbit",
                "displayName": "Fitbit Synthetic Watch",
            },
        }
    return {"dataPoints": [point]}


def _persist_google(
    session,
    paths,
    *,
    identity,
    payload,
    family=None,
    query_mode=GoogleQueryMode.LIST,
):
    query = GoogleQueryContext(
        query_mode=query_mode,
        data_source_family=family,
    )
    result = normalize_google_payload(
        payload,
        stream=GoogleStream.SLEEP,
        query=query,
        source_identity=identity,
    )
    return GooglePersistenceRepository(
        session,
        payload_store=ContentAddressedGooglePayloadStore(paths.root / "google-artifacts"),
    ).persist_result(result, payload=payload, received_at=datetime(2099, 1, 2, tzinfo=UTC))


def test_device_pair_uses_record_evidence_without_source_attributed_flag(pairing_database):
    session, paths = pairing_database
    _persist_garmin(session, paths)
    outcome = _persist_google(
        session,
        paths,
        identity=_google_identity(),
        payload=_google_payload(name="fitbit-night-1"),
    )
    session.commit()

    before = session.scalar(select(func.count()).select_from(GoogleSourceRecord))
    result = read_persisted_sleep_pairing(session)
    after = session.scalar(select(func.count()).select_from(GoogleSourceRecord))

    assert before == after == 1
    assert len(result.device_pairs) == 1
    pair = result.device_pairs[0]
    assert pair.cohort == DEVICE_PAIR
    assert pair.google_manually_edited is False
    assert pair.google_source_eligibility.basis["record_source_evidence"] is not None
    assert session.get(GoogleSourceRecord, outcome.records[0].id).projection_status == "current"


def test_device_pair_requires_explicit_fitbit_target_source(pairing_database):
    session, paths = pairing_database
    _persist_garmin(session, paths)
    _persist_google(
        session,
        paths,
        identity=_google_identity(source_instance_id="users/me/dataSources/raw:generic"),
        payload=_google_payload(name="fitbit-record-with-generic-source"),
    )
    session.commit()

    result = read_persisted_sleep_pairing(session)

    assert result.device_pairs == ()
    assert any(item.reason == "google_target_source_missing" for item in result.exclusions)


def test_family_and_all_sources_never_become_device_pairs(pairing_database):
    session, paths = pairing_database
    _persist_garmin(session, paths)
    _persist_google(
        session,
        paths,
        identity=_google_identity(family=FAMILY_GOOGLE_WEARABLES),
        payload=_google_payload(name="family-night", data_source=False),
        family=FAMILY_GOOGLE_WEARABLES,
    )
    _persist_google(
        session,
        paths,
        identity=_google_identity(family=FAMILY_ALL_SOURCES),
        payload=_google_payload(name="all-night", data_source=False),
        family=FAMILY_ALL_SOURCES,
    )
    session.commit()

    result = read_persisted_sleep_pairing(session)

    assert len(result.device_pairs) == 0
    assert len(result.family_pairs) == 1
    assert any(item.reason == "google_all_sources_excluded" for item in result.exclusions)


def test_ambiguous_google_mains_are_excluded_without_latest_selection(pairing_database):
    session, paths = pairing_database
    _persist_garmin(session, paths)
    _persist_google(
        session,
        paths,
        identity=_google_identity(),
        payload=_google_payload(name="fitbit-night-a"),
    )
    _persist_google(
        session,
        paths,
        identity=_google_identity(),
        payload=_google_payload(name="fitbit-night-b"),
    )
    session.commit()

    result = read_persisted_sleep_pairing(session)

    assert result.pairs == ()
    assert any(item.reason == "ambiguous_google_main" for item in result.exclusions)


def test_competing_eligible_fitbit_sources_fail_closed(pairing_database):
    session, paths = pairing_database
    _persist_garmin(session, paths)
    _persist_google(
        session,
        paths,
        identity=_google_identity(source_instance_id=f"{FITBIT_SOURCE}:watch-a"),
        payload=_google_payload(name="fitbit-source-a"),
    )
    _persist_google(
        session,
        paths,
        identity=_google_identity(source_instance_id=f"{FITBIT_SOURCE}:watch-b"),
        payload=_google_payload(name="fitbit-source-b"),
    )
    session.commit()

    result = read_persisted_sleep_pairing(session)

    assert result.device_pairs == ()
    assert any(item.reason == "ambiguous_fitbit_source" for item in result.exclusions)


def test_explicit_google_main_outranks_missing_main_fallback(pairing_database):
    session, paths = pairing_database
    _persist_garmin(session, paths)
    explicit = _persist_google(
        session,
        paths,
        identity=_google_identity(),
        payload=_google_payload(name="fitbit-explicit-main", main=True, nap=False),
    )
    _persist_google(
        session,
        paths,
        identity=_google_identity(),
        payload=_google_payload(name="fitbit-missing-main", main=None, nap=False),
    )
    session.commit()

    result = read_persisted_sleep_pairing(session)

    assert len(result.device_pairs) == 1
    assert result.device_pairs[0].google_record_id == explicit.records[0].id


def test_nap_and_unknown_main_states_remain_explicit(pairing_database):
    session, paths = pairing_database
    _persist_garmin(session, paths)
    _persist_google(
        session,
        paths,
        identity=_google_identity(),
        payload=_google_payload(name="fitbit-nap", main=False, nap=True),
    )
    _persist_google(
        session,
        paths,
        identity=_google_identity(),
        payload=_google_payload(name="fitbit-unknown-main", main=None, nap=None),
    )
    session.commit()

    result = read_persisted_sleep_pairing(session)

    reasons = {item.reason for item in result.exclusions}
    assert "google_nap_only" in reasons
    assert "google_nap_state_unknown" in reasons


def test_missing_wake_date_is_excluded(pairing_database):
    session, paths = pairing_database
    _persist_garmin(session, paths)
    outcome = _persist_google(
        session,
        paths,
        identity=_google_identity(),
        payload=_google_payload(name="fitbit-missing-wake-date"),
    )
    session.get(GoogleSleepRecord, outcome.records[0].id).wake_date = None
    session.commit()

    result = read_persisted_sleep_pairing(session)

    assert result.device_pairs == ()
    assert any(item.reason == "wake_date_missing" for item in result.exclusions)


def test_manually_edited_true_and_missing_states_remain_explicit(pairing_database):
    session, paths = pairing_database
    _persist_garmin(session, paths)
    _persist_google(
        session,
        paths,
        identity=_google_identity(),
        payload=_google_payload(name="fitbit-manual-edit", manually_edited=True),
    )
    session.commit()

    result = read_persisted_sleep_pairing(session)

    assert len(result.device_pairs) == 1
    assert result.device_pairs[0].google_manually_edited is True


def test_missing_manual_edit_state_is_not_coerced_to_false(pairing_database):
    session, paths = pairing_database
    _persist_garmin(session, paths)
    _persist_google(
        session,
        paths,
        identity=_google_identity(),
        payload=_google_payload(name="fitbit-missing-manual-edit", manually_edited=None),
    )
    session.commit()

    result = read_persisted_sleep_pairing(session)

    assert len(result.device_pairs) == 1
    assert result.device_pairs[0].google_manually_edited is None


def test_list_and_reconcile_share_explicit_source_identity(pairing_database):
    session, paths = pairing_database
    _persist_garmin(session, paths)
    payload = _google_payload(name="fitbit-list-reconcile")
    identity = _google_identity()
    _persist_google(
        session,
        paths,
        identity=identity,
        payload=payload,
        query_mode=GoogleQueryMode.LIST,
    )
    _persist_google(
        session,
        paths,
        identity=identity,
        payload=payload,
        query_mode=GoogleQueryMode.RECONCILE,
    )
    session.commit()

    result = read_persisted_sleep_pairing(session)

    assert session.scalar(select(func.count()).select_from(GoogleSource)) == 1
    assert session.scalar(select(func.count()).select_from(GoogleSourceRecord)) == 1
    assert len(result.device_pairs) == 1


def test_source_query_is_host_timezone_invariant(pairing_database, monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip("runtime TZ switching is unavailable on this host")

    session, paths = pairing_database
    _persist_garmin(session, paths)
    _persist_google(
        session,
        paths,
        identity=_google_identity(),
        payload=_google_payload(name="fitbit-current"),
    )
    session.commit()

    query = SleepPairingQuery(start_date=date(2099, 1, 2), end_date=date(2099, 1, 2))
    original_tz = os.environ.get("TZ")
    try:
        monkeypatch.setenv("TZ", "UTC")
        time.tzset()
        first = read_persisted_sleep_pairing(session, query)
        monkeypatch.setenv("TZ", "America/Los_Angeles")
        time.tzset()
        second = read_persisted_sleep_pairing(session, query)
    finally:
        if original_tz is None:
            monkeypatch.delenv("TZ", raising=False)
        else:
            monkeypatch.setenv("TZ", original_tz)
        time.tzset()

    assert first.as_dict() == second.as_dict()
    assert len(first.device_pairs) == 1
