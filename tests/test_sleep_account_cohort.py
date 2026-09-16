"""Issue #122: synthetic persisted account observations, never device agreement."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from healthcheck.analytics.sleep_agreement import PersistedSleepAgreementService
from healthcheck.analytics.sleep_agreement_report import SleepAgreementReportService
from healthcheck.analytics.sleep_metrics import read_persisted_sleep_metric_projection
from healthcheck.analytics.sleep_pairing import SleepPairingQuery, read_persisted_sleep_pairing
from healthcheck.config import Settings
from healthcheck.db.models import (
    AgreementRun,
    GarminSleepRecord,
    GarminSource,
    GarminSourceRecord,
    GoogleRecordMetric,
    GoogleRecordSourceEvidence,
    GoogleSourceRecord,
)
from healthcheck.garmin.normalization import normalize_garmin_payload
from healthcheck.garmin.persistence import GarminPersistenceRepository
from healthcheck.garmin.storage import ContentAddressedGarminPayloadStore
from healthcheck.google.contracts import (
    FAMILY_ALL_SOURCES,
    FAMILY_GOOGLE_SOURCES,
    FAMILY_GOOGLE_WEARABLES,
)
from healthcheck.ingestion.photo.fake import FakeImageMeasurementExtractor
from healthcheck.web.ui_app import create_ui_app
from test_sleep_pairing import (
    GARMIN_SLEEP_FIXTURE,
    _google_identity,
    _google_payload,
    _persist_google,
)
from test_sleep_pairing import (
    pairing_database as pairing_database,
)

COHORT = "account_wearables_sleep_observations_v1"
PAIRING_VERSION = "r05-account-wearables-sleep-pairing-v1"
START = date(2099, 1, 2)
ROLE_VALUES = {"null": None, "invalid": "unknown", "false": False, "true": True}


def _garmin(session, paths, wake=START, *, attributed=False, seconds=28800):
    payload = json.loads(GARMIN_SLEEP_FIXTURE.read_text(encoding="utf-8"))
    payload["fixture_id"] = f"synthetic-account-sleep-{wake}"
    if not attributed:
        payload["device"] = {"attributed": False}
    payload["payload"]["dailySleepDTO"]["calendarDate"] = wake.isoformat()
    payload["payload"]["dailySleepDTO"]["sleepTimeSeconds"] = seconds
    payload["payload"].pop("levels")
    return GarminPersistenceRepository(
        session,
        payload_store=ContentAddressedGarminPayloadStore(paths.root / "garmin-artifacts"),
    ).persist_result(normalize_garmin_payload(payload), payload=json.dumps(payload).encode())


def _google(
    session,
    paths,
    wake=START,
    *,
    name=None,
    main="missing",
    nap="missing",
    family=FAMILY_GOOGLE_WEARABLES,
    source=None,
    minutes="410",
    manual="missing",
):
    payload = _google_payload(name=name or f"synthetic-account-night-{wake}", data_source=False)
    sleep = payload["dataPoints"][0]["sleep"]
    sleep["metadata"].pop("manuallyEdited")
    if manual != "missing":
        sleep["metadata"]["manuallyEdited"] = ROLE_VALUES[manual]
    for key, state in (("main", main), ("nap", nap)):
        sleep["metadata"].pop(key)
        if state != "missing":
            sleep["metadata"][key] = ROLE_VALUES[state]
    sleep["summary"]["minutesAsleep"] = minutes
    interval = sleep["interval"]
    interval["startTime"] = f"{wake - timedelta(days=1)}T22:00:00Z"
    interval["endTime"] = f"{wake}T05:00:00Z"
    interval["civilStartTime"]["date"] = wake.isoformat()
    interval["civilEndTime"]["date"] = wake.isoformat()
    sleep["updateTime"] = f"{wake}T08:04:00Z"
    identity = (
        _google_identity(family=family)
        if source is None
        else _google_identity(source_instance_id=source)
    )
    return _persist_google(session, paths, identity=identity, payload=payload, family=family)


def _read(session):
    return read_persisted_sleep_pairing(session, SleepPairingQuery(cohort=COHORT))


@pytest.mark.parametrize("main", ["missing", "null", "invalid", "false", "true"])
@pytest.mark.parametrize("nap", ["missing", "null", "invalid", "false", "true"])
def test_account_role_states_are_preserved_and_explicit_naps_excluded(
    pairing_database,
    main,
    nap,
):
    session, paths = pairing_database
    _garmin(session, paths)
    _google(session, paths, main=main, nap=nap)
    session.commit()
    before = [
        (row.metric_code, row.state, row.value_text)
        for row in session.scalars(
            select(GoogleRecordMetric).order_by(GoogleRecordMetric.metric_code)
        )
    ]
    result = _read(session)
    assert read_persisted_sleep_pairing(session).pairs == ()
    if nap == "true":
        assert result.pairs == ()
        assert "google_nap_only" in {item.reason for item in result.exclusions}
    else:
        (pair,) = result.pairs
        assert pair.cohort == COHORT
        assert pair.source_class == "google_wearables_family"
        assert pair.garmin_source_eligibility.source_class == "garmin_account"
        assert pair.garmin_source_eligibility.basis["device_attributed"] is False
        assert pair.garmin_source_eligibility.basis["device_code"] is None
        assert pair.google_main_state == ("value" if main in {"true", "false"} else main)
        assert pair.google_nap_state == ("value" if nap == "false" else nap)
        assert pair.google_manually_edited is None
        uncertainty = pair.as_dict()["uncertainty"]
        assert uncertainty["source_device_attribution_uncertain"] is True
        assert uncertainty["google_session_role_uncertain"] is not (
            main == "true" and nap == "false"
        )
        expected_main = ROLE_VALUES[main] if main in {"true", "false"} else None
        assert uncertainty["google_main_value"] is expected_main
        assert uncertainty["google_nap_value"] is (False if nap == "false" else None)
        assert uncertainty["selection_rule"] == PAIRING_VERSION
        assert uncertainty["canonical_eligible"] is False
    after = [
        (row.metric_code, row.state, row.value_text)
        for row in session.scalars(
            select(GoogleRecordMetric).order_by(GoogleRecordMetric.metric_code)
        )
    ]
    assert before == after
    assert session.scalar(select(GarminSource)).device_attributed is False


@pytest.mark.parametrize("cohort", ["device_pair", "family_pair", "all"])
def test_uncertain_role_never_enters_legacy_cohorts(pairing_database, cohort):
    session, paths = pairing_database
    _garmin(session, paths, attributed=True)
    _google(session, paths)
    session.commit()
    legacy = read_persisted_sleep_pairing(session, SleepPairingQuery(cohort=cohort))
    assert legacy.pairs == ()
    assert legacy.as_dict()["contract_version"] == "r05-01-sleep-pairing-v1"
    assert len(_read(session).pairs) == 1
    assert (
        legacy.as_dict()
        == read_persisted_sleep_pairing(session, SleepPairingQuery(cohort=cohort)).as_dict()
    )


@pytest.mark.parametrize(
    "second_main,second_nap,expected",
    [
        ("missing", "missing", None),
        ("true", "false", "explicit"),
        ("missing", "true", "uncertain"),
    ],
)
def test_account_candidate_selection_never_uses_latest_or_longest(
    pairing_database,
    second_main,
    second_nap,
    expected,
):
    session, paths = pairing_database
    _garmin(session, paths)
    first = _google(session, paths, name="uncertain", minutes="300")
    second = _google(session, paths, name="explicit", main=second_main, nap=second_nap)
    session.commit()
    result = _read(session)
    if expected is None:
        assert result.pairs == ()
        assert "ambiguous_google_main" in {item.reason for item in result.exclusions}
    else:
        (pair,) = result.pairs
        assert pair.google_record_id == (second if expected == "explicit" else first).records[0].id
        assert pair.as_dict()["uncertainty"]["google_session_role_uncertain"] is (
            expected == "uncertain"
        )
        if expected == "explicit":
            assert "google_explicit_main_preferred" in {item.reason for item in result.exclusions}


def test_account_multiple_explicit_mains_and_garmin_records_fail_closed(pairing_database):
    session, paths = pairing_database
    _garmin(session, paths)
    _google(session, paths, name="main-a", main="true", nap="false")
    _google(session, paths, name="main-b", main="true", nap="false")
    assert "ambiguous_google_main" in {item.reason for item in _read(session).exclusions}
    _garmin(session, paths, attributed=True)
    assert "ambiguous_garmin_main" in {item.reason for item in _read(session).exclusions}
    assert _read(session).pairs == ()


def test_account_competing_sources_fail_even_with_one_explicit_main(pairing_database):
    session, paths = pairing_database
    _garmin(session, paths)
    _google(session, paths)
    _google(
        session,
        paths,
        family=None,
        source="users/me/dataSources/synthetic-watch",
        name="other-source",
        main="true",
        nap="false",
    )
    result = _read(session)
    assert result.pairs == ()
    assert "ambiguous_google_source" in {item.reason for item in result.exclusions}


@pytest.mark.parametrize(
    "family,source,allowed",
    [
        (None, "users/me/dataSources/synthetic-watch", True),
        (None, "unattributed", False),
        (FAMILY_ALL_SOURCES, None, False),
        (FAMILY_GOOGLE_SOURCES, None, False),
    ],
)
def test_account_requires_identified_google_source_or_wearables_family(
    pairing_database,
    family,
    source,
    allowed,
):
    session, paths = pairing_database
    _garmin(session, paths)
    _google(session, paths, family=family, source=source)
    assert bool(_read(session).pairs) is allowed


@pytest.mark.parametrize(
    "projection_status,record_status",
    [
        ("retired", "partial"),
        ("current", "invalid"),
    ],
)
def test_account_ignores_noncurrent_and_invalid_records(
    pairing_database,
    projection_status,
    record_status,
):
    session, paths = pairing_database
    _garmin(session, paths)
    google = _google(session, paths)
    record = session.get(GoogleSourceRecord, google.records[0].id)
    record.projection_status = projection_status
    record.record_status = record_status
    if projection_status == "retired":
        record.retired_at = datetime(2099, 1, 3, tzinfo=UTC)
    session.flush()
    assert _read(session).pairs == ()


@pytest.mark.parametrize("count", [13, 14, 42, 49])
def test_account_persisted_report_reuses_statistics_but_never_strong_gate(pairing_database, count):
    session, paths = pairing_database
    for index in range(count):
        wake = START + timedelta(days=index)
        _garmin(session, paths, wake)
        _google(session, paths, wake)
    query = SleepPairingQuery(
        cohort=COHORT, start_date=START, end_date=START + timedelta(days=count - 1)
    )
    projection = read_persisted_sleep_metric_projection(session, query)
    assert len(projection.pairs) == count
    service = PersistedSleepAgreementService(session)
    persisted = service.persist(projection, scope_key="synthetic:account-observations")
    session.commit()
    assert persisted.run.pairing_version == PAIRING_VERSION
    assert service.persist(projection, scope_key="synthetic:account-observations").created is False
    report_service = SleepAgreementReportService(session)
    report = report_service.report(cohort=COHORT, run_id=persisted.id)
    (duration,) = [
        item for item in report["groups"] if item["metric_code"] == "sleep_duration_asleep_seconds"
    ]
    assert duration["n"] == count
    assert duration["source_attribution"]["cohort_label"] == (
        "Uncertain Garmin account / Google source or family observations"
    )
    assert "not Garmin-vs-Fitbit/device agreement" in duration["uncertainty_notice"]
    assert duration["progress"]["gate"]["canonical_proposal_eligible"] is False
    assert duration["progress"]["gate"]["provisional"] == "exploratory_only_cohort"
    if count < 14:
        assert duration["accepted_statistics"] is None
    else:
        stats = duration["accepted_statistics"]
        assert stats["strong_gate_eligible_n"] == 0
        assert stats["bias"] == -4200
        assert stats["gate"]["canonical_switch_applied"] is False
    detail = report_service.night_detail(persisted.id, wake_date=START)
    (night,) = detail["nights"]
    assert night["uncertainty"]["google_session_role_uncertain"] is True
    assert night["google_main_state"] == night["google_nap_state"] == "missing"
    frozen_snapshot = persisted.run.input_snapshot_json
    # Historical replay reads frozen evidence even after current role fields change.
    for metric in session.scalars(
        select(GoogleRecordMetric).where(GoogleRecordMetric.metric_code == "sleep_metadata_nap")
    ):
        metric.state, metric.value_text = "value", "true"
    session.commit()
    replay = service.replay(persisted.id)
    assert (
        replay.snapshot["projection"]["pairing"]["pairs"][0]["uncertainty"]
        == (night["uncertainty"])
    )
    assert persisted.run.input_snapshot_json == frozen_snapshot
    assert report_service.night_detail(persisted.id, wake_date=START) == detail
    if count == 14:
        app, _ = create_ui_app(
            Settings(data_dir=paths.root), photo_extractor=FakeImageMeasurementExtractor()
        )
        with TestClient(app) as client:
            response = client.get("/api/agreement/report", params={"cohort": COHORT})
            assert response.status_code == 200
            assert response.json()["mode"] == "exploratory"
            page = client.get("/agreement")
            assert COHORT in page.text
            assert "not Garmin-vs-Fitbit/device agreement" in page.text


@pytest.mark.parametrize("minutes,seconds,expected", [("0", 0, 0), (None, 0, None)])
def test_account_metric_zero_and_null_remain_distinct(pairing_database, minutes, seconds, expected):
    session, paths = pairing_database
    _garmin(session, paths, seconds=seconds)
    _google(session, paths, minutes=minutes)
    projection = read_persisted_sleep_metric_projection(session, SleepPairingQuery(cohort=COHORT))
    (duration,) = [
        item for item in projection.metrics if item.metric_code == "sleep_duration_asleep_seconds"
    ]
    assert duration.difference == expected
    assert duration.google.state == ("null" if minutes is None else "value")


def test_account_projection_freezes_consistent_source_eligibility(pairing_database):
    session, paths = pairing_database
    _garmin(session, paths)
    _google(session, paths, family=None, source="users/me/dataSources/synthetic-watch")
    projection = read_persisted_sleep_metric_projection(session, SleepPairingQuery(cohort=COHORT))
    (duration,) = [
        item for item in projection.metrics if item.metric_code == "sleep_duration_asleep_seconds"
    ]
    for side in (duration.garmin, duration.google):
        eligibility = side.evidence.attribution["source_eligibility"]
        assert eligibility["cohort"] == COHORT
        assert eligibility["eligible"] is True
    assert duration.garmin.evidence.attribution["device_attributed"] is False
    (stages,) = [
        item for item in projection.metrics if item.metric_code == "sleep_stage_light_seconds"
    ]
    assert not stages.comparable
    assert stages.difference is None


@pytest.mark.parametrize("manual", ["missing", "null", "invalid", "true", "false"])
def test_account_preserves_manual_edit_state(pairing_database, manual):
    session, paths = pairing_database
    _garmin(session, paths)
    _google(session, paths, manual=manual)
    (pair,) = _read(session).pairs
    assert pair.google_manually_edited is (
        ROLE_VALUES[manual] if manual in {"true", "false"} else None
    )
    assert pair.uncertainty["google_manually_edited_state"] == (
        "value" if manual in {"true", "false"} else manual
    )


@pytest.mark.parametrize("defect", ["invalid_record", "missing_wake_date", "retired_record"])
def test_account_invalid_garmin_or_date_never_pairs(pairing_database, defect):
    session, paths = pairing_database
    outcome = _garmin(session, paths)
    _google(session, paths)
    record = session.get(GarminSourceRecord, outcome.records[0].id)
    if defect == "invalid_record":
        record.record_status = "invalid"
    elif defect == "missing_wake_date":
        session.get(GarminSleepRecord, record.id).wake_date = None
    else:
        record.projection_status = "retired"
        record.retired_at = datetime(2099, 1, 3, tzinfo=UTC)
    session.flush()
    assert _read(session).pairs == ()


@pytest.mark.parametrize("evidence_json", ["[]", '{"state":"invalid","fields":[]}'])
def test_account_invalid_google_attribution_is_not_reinterpreted(pairing_database, evidence_json):
    session, paths = pairing_database
    _garmin(session, paths)
    google = _google(session, paths, family=None, source="users/me/dataSources/synthetic-watch")
    session.get(GoogleRecordSourceEvidence, google.records[0].id).evidence_json = evidence_json
    session.flush()
    result = _read(session)
    assert result.pairs == ()
    assert "google_record_source_evidence_invalid" in {item.reason for item in result.exclusions}


def test_new_and_legacy_versions_coexist_without_relabeling_history(pairing_database):
    session, paths = pairing_database
    _garmin(session, paths, attributed=True)
    _persist_google(
        session, paths, identity=_google_identity(), payload=_google_payload(name="legacy-explicit")
    )
    legacy = read_persisted_sleep_metric_projection(session)
    service = PersistedSleepAgreementService(session)
    old = service.persist(legacy, scope_key="synthetic:coexist")
    session.commit()
    old_snapshot = old.run.input_snapshot_json
    new = read_persisted_sleep_metric_projection(session, SleepPairingQuery(cohort=COHORT))
    count_before = session.scalar(select(func.count()).select_from(AgreementRun))
    with pytest.raises(ValueError, match="versioned pairing rule"):
        service.persist(new, scope_key="synthetic:coexist", pairing_version=old.run.pairing_version)
    assert session.scalar(select(func.count()).select_from(AgreementRun)) == count_before
    account = service.persist(new, scope_key="synthetic:coexist")
    assert account.run.pairing_version == PAIRING_VERSION
    assert account.run.input_snapshot_hash != old.run.input_snapshot_hash
    assert old.run.input_snapshot_json == old_snapshot
    assert "uncertainty" not in legacy.pairs[0].as_dict()
    assert read_persisted_sleep_metric_projection(session).as_dict() == legacy.as_dict()
    assert service.persist(legacy, scope_key="synthetic:coexist").id == old.id
