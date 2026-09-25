"""Synthetic policy and persisted-read regressions for the frozen v1 contract."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from healthcheck.db.models import (
    AcquisitionSource,
    Base,
    CoverageInterval,
    GarminSource,
    GarminSourceRecord,
    GarminTrainingAcquisition,
    GarminTrainingObservationRecord,
    GoogleSource,
    GoogleSourceRecord,
    MeasurementSession,
    Provider,
    ScalarMeasurement,
    SyncRun,
    SyncStreamState,
)
from healthcheck.source_freshness import (
    POLICY_VERSION,
    SCOPE_BY_KEY,
    SCOPES,
    Facts,
    aggregate,
    evaluate_scope,
)
from healthcheck.source_freshness_consumer import read_consumer_freshness_projection
from healthcheck.source_freshness_read import read_facts
from healthcheck.web.source_freshness import router

NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)
DAY = date(2026, 9, 25)


def result(key: str, facts: Facts, version: str = POLICY_VERSION) -> dict[str, object]:
    return evaluate_scope(SCOPE_BY_KEY[key], facts, evaluated_at_utc=NOW,
                          evaluation_local_date=DAY, policy_version=version)


def daily(*, evidence_hours: float, success_hours: float = 1, **overrides: object) -> Facts:
    args = dict(last_attempt_at_utc=NOW - timedelta(hours=success_hours),
                last_success_at_utc=NOW - timedelta(hours=success_hours),
                evidence_at_utc=NOW - timedelta(hours=evidence_hours), observed_once=True)
    args.update(overrides)
    return Facts(**args)


@pytest.mark.parametrize(("age", "state", "reason"), [
    (36, "fresh", "evidence_current"),
    (36.01, "quiet", "evidence_within_grace"),
    (72, "quiet", "evidence_within_grace"),
    (72.01, "stale", "expected_evidence_absent"),
])
def test_daily_due_and_grace_boundaries(age: float, state: str, reason: str) -> None:
    row = result("garmin:sleep", daily(evidence_hours=age))
    assert (row["state"], row["reason_code"]) == (state, reason)
    assert row["policy_basis"] == {"cadence_hours": 24, "due_hours": 36,
                                   "grace_hours": 72, "refresh_overdue_hours": 48}


def test_shared_consumer_projection_reuses_core_and_removes_fact_details(monkeypatch) -> None:
    import healthcheck.source_freshness_consumer as consumer

    facts_by_key = {}
    for scope in SCOPES:
        if scope.key == "garmin:sleep":
            facts_by_key[scope.key] = Facts(
                last_attempt_at_utc=NOW - timedelta(hours=49),
                last_success_at_utc=NOW - timedelta(hours=49),
                evidence_at_utc=NOW - timedelta(hours=73),
                observed_once=True,
            )
        elif scope.family == "weight":
            facts_by_key[scope.key] = Facts(confirmed_weight=True, observed_once=True)
        elif scope.family == "activity":
            facts_by_key[scope.key] = Facts(
                last_attempt_at_utc=NOW - timedelta(hours=1),
                last_success_at_utc=NOW - timedelta(hours=1),
                coverage="complete",
                activity_count=0,
            )
        else:
            facts_by_key[scope.key] = daily(evidence_hours=1)

    calls = []

    def fake_read_facts(_session, scope, **kwargs):
        calls.append((scope.key, kwargs["evaluation_local_date"]))
        return facts_by_key[scope.key]

    monkeypatch.setattr(consumer, "read_facts", fake_read_facts)
    engine = create_engine("sqlite://")
    try:
        with Session(engine) as session:
            projection = read_consumer_freshness_projection(
                session,
                evaluated_at_utc=NOW,
                evaluation_local_date=DAY,
            )
    finally:
        engine.dispose()

    assert projection["policy_version"] == POLICY_VERSION
    assert projection["owner"] == {
        "state": "stale",
        "actionable_items": [
            {
                "scope_key": "garmin:sleep",
                "state": "stale",
                "reason_code": "refresh_overdue",
            }
        ],
    }
    assert projection["providers"]["garmin"]["state"] == "stale"
    assert projection["providers"]["google"]["state"] == "fresh"
    serialized = json.dumps(projection, sort_keys=True)
    assert NOW.isoformat() not in serialized
    assert all(
        name not in serialized
        for name in ("evaluated_at_utc", "latest_evidence", "policy_basis", "facts", "result_id")
    )
    assert len(calls) == len(SCOPES)
    assert all(day == DAY for _, day in calls)


def test_refresh_overdue_and_terminal_precedence() -> None:
    assert result("garmin:sleep", daily(evidence_hours=1, success_hours=49))["reason_code"] == (
        "refresh_overdue"
    )
    failure = daily(evidence_hours=1, success_hours=2,
                    last_attempt_at_utc=NOW - timedelta(hours=1), terminal_status="failed")
    assert (result("garmin:sleep", failure)["state"],
            result("garmin:sleep", failure)["reason_code"]) == ("unavailable", "refresh_failed")
    reauth = daily(evidence_hours=1, success_hours=2,
                   last_attempt_at_utc=NOW - timedelta(hours=1),
                   terminal_status="reauth_required")
    assert result("garmin:sleep", reauth)["reason_code"] == "reauth_required"
    recovered = daily(evidence_hours=1, last_attempt_at_utc=NOW - timedelta(hours=2),
                      terminal_status="failed")
    # A newer success supersedes the older terminal failure.
    assert result("garmin:sleep", recovered)["state"] == "fresh"


def test_newer_terminal_failure_precedes_evidence_ambiguity_and_aggregate() -> None:
    failed = daily(
        evidence_hours=1, success_hours=2,
        last_attempt_at_utc=NOW - timedelta(hours=1), terminal_status="failed",
        attribution_resolved=False,
    )
    row = result("garmin:heart_rate", failed)
    assert (row["state"], row["reason_code"]) == ("unavailable", "refresh_failed")
    required = [result(f"garmin:{key}", daily(evidence_hours=1))
                for key in ("daily_summary", "sleep")]
    group = aggregate(required + [row], evaluated_at_utc=NOW,
                      evaluation_local_date=DAY)
    assert group["providers"]["garmin"]["state"] == "unavailable"


def test_terminal_clocks_remain_authoritative_only_when_valid() -> None:
    terminal = dict(
        evidence_hours=1, success_hours=2, terminal_status="required_stream_unavailable",
        chronology_issue="invalid_chronology",
    )
    valid = daily(**terminal, last_attempt_at_utc=NOW - timedelta(hours=1))
    assert (result("garmin:sleep", valid)["state"],
            result("garmin:sleep", valid)["reason_code"]) == (
        "unavailable", "required_stream_unavailable",
    )
    ambiguous_evidence = daily(
        evidence_hours=1, success_hours=2,
        last_attempt_at_utc=NOW - timedelta(hours=1),
        evidence_at_utc=NOW.replace(tzinfo=None),
        terminal_status="required_stream_unavailable",
    )
    assert result("garmin:sleep", ambiguous_evidence)["state"] == "unavailable"
    for attempt, reason in (
        (NOW.replace(tzinfo=None), "invalid_chronology"),
        (NOW + timedelta(minutes=1), "future_chronology"),
    ):
        malformed = daily(**terminal, last_attempt_at_utc=attempt)
        assert (result("garmin:sleep", malformed)["state"],
                result("garmin:sleep", malformed)["reason_code"]) == ("unknown", reason)
    recovered = daily(
        evidence_hours=1, last_attempt_at_utc=NOW - timedelta(hours=2),
        terminal_status="failed",
    )
    assert result("garmin:sleep", recovered)["state"] == "fresh"


def test_incomplete_never_observed_and_optional_aggregation() -> None:
    partial = daily(evidence_hours=1, success_hours=2,
                    last_attempt_at_utc=NOW - timedelta(hours=1), terminal_status="partial")
    assert result("garmin:sleep", partial)["reason_code"] == "acquisition_incomplete"
    assert result("garmin:sleep", Facts())["reason_code"] == "never_observed"
    optional = result("garmin:spo2", Facts())
    assert (optional["state"], optional["reason_code"]) == ("unknown", "never_observed")
    required = [result(f"garmin:{key}", daily(evidence_hours=1))
                for key in ("daily_summary", "sleep", "heart_rate")]
    optional_stale = result("garmin:stress", daily(evidence_hours=80))
    group = aggregate(required + [optional, optional_stale], evaluated_at_utc=NOW,
                      evaluation_local_date=DAY)
    assert group["providers"]["garmin"]["state"] == "fresh"


@pytest.mark.parametrize(("days", "state"), [
    (0, "fresh"), (1, "fresh"), (2, "quiet"), (3, "stale"),
])
def test_civil_date_policy(days: int, state: str) -> None:
    facts = Facts(last_attempt_at_utc=NOW, last_success_at_utc=NOW,
                  evidence_local_date=DAY - timedelta(days=days), observed_once=True)
    assert result("google:sleep", facts)["state"] == state


def test_activity_inventory_and_voluntary_weight() -> None:
    base = dict(last_attempt_at_utc=NOW, last_success_at_utc=NOW, observed_once=True)
    assert result("garmin:activities", Facts(**base, coverage="complete",
                                             activity_count=0))["reason_code"] == (
        "event_window_confirmed_empty"
    )
    assert result("garmin:activities", Facts(**base, coverage="complete",
                                             activity_count=1))["state"] == "fresh"
    assert result("garmin:activities", Facts(**base, coverage="unknown"))["reason_code"] == (
        "coverage_unknown"
    )
    assert result("garmin:activities", Facts())["reason_code"] == "coverage_unknown"
    assert result("garmin:activities", Facts(
        **base, coverage="complete", activity_count=1,
        evidence_local_date=DAY - timedelta(days=100),
    ))["state"] == "fresh"
    overdue = Facts(last_success_at_utc=NOW - timedelta(hours=49),
                    last_attempt_at_utc=NOW - timedelta(hours=49),
                    coverage="complete", activity_count=0, observed_once=True)
    assert result("garmin:activities", overdue)["reason_code"] == "refresh_overdue"
    old = Facts(evidence_local_date=DAY - timedelta(days=100), confirmed_weight=True)
    assert (result("weight", old)["state"], result("weight", old)["reason_code"]) == (
        "quiet", "voluntary_sampling"
    )
    assert result("weight", Facts())["reason_code"] == "never_observed"


def test_explicit_not_requested_invalid_chronology_and_identity() -> None:
    assert result("garmin:sleep", Facts(requested=False))["state"] == "not_requested"
    assert result("garmin:sleep", Facts(disabled=True))["reason_code"] == "disabled"
    assert result("garmin:sleep", Facts())["state"] == "unknown"
    future = daily(evidence_hours=-1)
    assert result("garmin:sleep", future)["reason_code"] == "future_chronology"
    assert result("garmin:sleep", daily(evidence_hours=1,
                                        last_success_at_utc=NOW + timedelta(minutes=1)))[
        "reason_code"] == "future_chronology"
    invalid = daily(evidence_hours=1, evidence_at_utc=NOW.replace(tzinfo=None))
    assert result("garmin:sleep", invalid)["reason_code"] == "invalid_chronology"
    same = result("garmin:sleep", daily(evidence_hours=1))
    assert same == result("garmin:sleep", daily(evidence_hours=1))
    assert same["result_id"] != result("garmin:sleep", daily(evidence_hours=1),
                                       version="source-freshness-v2")["result_id"]


def test_required_aggregate_preserves_component_reasons() -> None:
    rows = [result("garmin:daily_summary", daily(evidence_hours=1)),
            result("garmin:sleep", daily(evidence_hours=80)),
            result("garmin:heart_rate", daily(evidence_hours=1))]
    group = aggregate(rows, evaluated_at_utc=NOW, evaluation_local_date=DAY)
    garmin = group["providers"]["garmin"]
    assert garmin["state"] == "stale"
    assert garmin["actionable_reasons"] == [
        {"scope_key": "garmin:sleep", "state": "stale",
         "reason_code": "expected_evidence_absent"}
    ]
    disabled = [result(f"garmin:{key}", Facts(requested=False))
                for key in ("daily_summary", "sleep", "heart_rate")]
    assert aggregate(disabled, evaluated_at_utc=NOW,
                     evaluation_local_date=DAY)["providers"]["garmin"]["state"] == (
        "not_requested"
    )


def test_persisted_activity_coverage_and_read_only_api(tmp_path: Path) -> None:
    database = tmp_path / "synthetic.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Provider(id="synthetic-private-provider-id", code="garmin_connect",
                             display_name="Garmin", provider_kind="wearable"))
        session.add(SyncStreamState(id="checkpoint", provider_id="synthetic-private-provider-id",
                                    stream_code="activities", last_attempt_at=NOW,
                                    last_success_at=NOW, diagnostic_status="confirmed_empty"))
        session.add(CoverageInterval(
            id="coverage", provider_id="synthetic-private-provider-id", stream_code="activity",
            metric_code="activities", resolution="day", status="confirmed_empty",
            interval_start=datetime(2026, 9, 19, tzinfo=UTC),
            interval_end=datetime(2026, 9, 26, tzinfo=UTC), observed_count=0,
            calculation_rule_version="synthetic",
        ))
        session.commit()
    with Session(engine) as session:
        facts = read_facts(session, SCOPE_BY_KEY["garmin:activities"],
                           evaluation_local_date=DAY)
    assert result("garmin:activities", facts)["reason_code"] == "event_window_confirmed_empty"
    before = database.read_bytes()
    app = FastAPI()
    app.state.runtime_paths = SimpleNamespace(database=database)
    app.state.settings = SimpleNamespace(weight_cadence_days=7)
    app.include_router(router)
    response = TestClient(app).get("/api/source-freshness", params={
        "evaluated_at_utc": NOW.isoformat(), "evaluation_local_date": DAY.isoformat(),
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["policy_version"] == POLICY_VERSION
    assert next(row for row in payload["components"] if row["scope_key"] == "garmin:activities")[
        "reason_code"] == "event_window_confirmed_empty"
    assert database.read_bytes() == before
    assert "synthetic-private-provider-id" not in response.text
    assert "raw_payload" not in response.text
    engine.dispose()


def test_persisted_google_list_and_confirmed_weight_exclude_private_fields(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'facts.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Provider(id="google-provider-private-id", code="google_health",
                             display_name="Google", provider_kind="health_api"))
        session.add(AcquisitionSource(id="google-acquisition-private-id",
                                      provider_id="google-provider-private-id",
                                      input_method="provider_api"))
        session.add(GoogleSource(id="google-source-private-id",
                                 provider_id="google-provider-private-id",
                                 acquisition_source_id="google-acquisition-private-id",
                                 source_kind="data_source", provider_code="google_health",
                                 source_instance_id="private-source-instance",
                                 source_contract_version="synthetic"))
        session.add(SyncStreamState(id="google-state", provider_id="google-provider-private-id",
                                    stream_code="google:refresh:sleep:list:any",
                                    last_attempt_at=NOW, last_success_at=NOW,
                                    diagnostic_status="present"))
        session.add(GoogleSourceRecord(
            id="google-record-private-id", google_source_id="google-source-private-id",
            raw_payload_id="private-raw-id", stream_code="sleep", query_mode="list",
            record_identity_key="synthetic-record-key", idempotency_key="synthetic-key",
            temporal_precision="date", source_local_date=DAY, record_status="ok",
            normalization_contract_version="synthetic",
        ))
        session.add(MeasurementSession(
            id="weight-session-private-id", acquisition_source_id="weight-source-private-id",
            temporal_precision="date", source_local_date=DAY - timedelta(days=100),
            confirmation_status="confirmed", import_status="committed", revision_number=1,
        ))
        session.add(ScalarMeasurement(
            id="weight-measurement-private-id", measurement_session_id="weight-session-private-id",
            metric_code="weight", normalized_value=123.456, normalized_unit="kg",
            measurement_algorithm_id="synthetic-algorithm",
        ))
        session.commit()
    with Session(engine) as session:
        google = read_facts(session, SCOPE_BY_KEY["google:sleep"], evaluation_local_date=DAY)
        weight = read_facts(session, SCOPE_BY_KEY["weight"], evaluation_local_date=DAY)
    assert result("google:sleep", google)["reason_code"] == "evidence_current"
    assert result("weight", weight)["reason_code"] == "voluntary_sampling"
    assert "private" not in str(result("google:sleep", google))
    assert "123.456" not in str(result("weight", weight))
    with Session(engine) as session:
        session.add(GoogleSource(id="second-private-source",
                                 provider_id="google-provider-private-id",
                                 acquisition_source_id="google-acquisition-private-id",
                                 source_kind="data_source", provider_code="google_health",
                                 source_instance_id="another-private-instance",
                                 source_contract_version="synthetic"))
        session.add(GoogleSourceRecord(
            id="second-private-record", google_source_id="second-private-source",
            raw_payload_id="another-private-payload", stream_code="sleep", query_mode="list",
            record_identity_key="second-key", idempotency_key="second-idempotency-key",
            temporal_precision="date", source_local_date=DAY, record_status="ok",
            normalization_contract_version="synthetic",
        ))
        session.commit()
    with Session(engine) as session:
        ambiguous = read_facts(session, SCOPE_BY_KEY["google:sleep"],
                               evaluation_local_date=DAY)
    assert result("google:sleep", ambiguous)["reason_code"] == "scope_unresolved"
    engine.dispose()


def test_persisted_training_success_requires_surface_evidence(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'training.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Provider(id="garmin", code="garmin_connect", display_name="Garmin",
                             provider_kind="wearable"))
        session.add(AcquisitionSource(id="acquisition", provider_id="garmin",
                                      input_method="provider_api"))
        session.add(GarminSource(id="source", provider_id="garmin",
                                 acquisition_source_id="acquisition", source_kind="account",
                                 provider_code="garmin_connect",
                                 source_instance_id="synthetic-private-instance"))
        session.add(SyncRun(id="training-run", provider_id="garmin", stream_code="garmin_training",
                            status="succeeded", started_at=NOW - timedelta(minutes=2),
                            completed_at=NOW - timedelta(minutes=1)))
        session.add(GarminSourceRecord(
            id="record", garmin_source_id="source", raw_payload_id="private-payload",
            stream_code="daily_health", idempotency_key="synthetic-training-record",
            temporal_precision="date", source_local_date=DAY, record_status="ok",
            normalization_contract_version="synthetic",
        ))
        session.add(GarminTrainingAcquisition(observation_id="observation",
                                              surface="training_status", requested_date=DAY,
                                              response_state="value"))
        session.add(GarminTrainingObservationRecord(observation_id="observation",
                                                    record_id="record"))
        session.commit()
    with Session(engine) as session:
        status = read_facts(session, SCOPE_BY_KEY["garmin:training_status"],
                            evaluation_local_date=DAY)
        readiness = read_facts(session, SCOPE_BY_KEY["garmin:training_readiness"],
                               evaluation_local_date=DAY)
    assert result("garmin:training_status", status)["state"] == "fresh"
    assert result("garmin:training_readiness", readiness)["reason_code"] == "never_observed"
    with Session(engine) as session:
        session.add(SyncRun(id="training-failed", provider_id="garmin",
                            stream_code="garmin_training", status="failed",
                            started_at=NOW - timedelta(seconds=40),
                            completed_at=NOW - timedelta(seconds=30)))
        session.commit()
    with Session(engine) as session:
        failed = read_facts(session, SCOPE_BY_KEY["garmin:training_status"],
                            evaluation_local_date=DAY)
    assert (result("garmin:training_status", failed)["state"],
            result("garmin:training_status", failed)["reason_code"]) == (
        "unavailable", "refresh_failed",
    )
    with Session(engine) as session:
        session.add(SyncRun(id="training-recovered", provider_id="garmin",
                            stream_code="garmin_training", status="succeeded",
                            started_at=NOW - timedelta(seconds=20),
                            completed_at=NOW - timedelta(seconds=10)))
        session.commit()
    with Session(engine) as session:
        recovered = read_facts(session, SCOPE_BY_KEY["garmin:training_status"],
                               evaluation_local_date=DAY)
    assert result("garmin:training_status", recovered)["state"] == "fresh"
    with Session(engine) as session:
        session.add(SyncRun(id="training-partial", provider_id="garmin",
                            stream_code="garmin_training", status="partial",
                            started_at=NOW - timedelta(seconds=5), completed_at=NOW))
        session.commit()
    with Session(engine) as session:
        partial = read_facts(session, SCOPE_BY_KEY["garmin:training_status"],
                             evaluation_local_date=DAY)
    assert result("garmin:training_status", partial)["reason_code"] == (
        "acquisition_incomplete"
    )
    engine.dispose()


def test_persisted_google_refresh_namespace_family_and_hr_partition(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'google-refresh.db').as_posix()}")
    Base.metadata.create_all(engine)
    provider_id = "google-provider"
    family = "users/me/dataSourceFamilies/google-wearables"
    with Session(engine) as session:
        session.add(Provider(id=provider_id, code="google_health", display_name="Google",
                             provider_kind="health_api"))
        session.add(GoogleSource(id="google-source", provider_id=provider_id,
                                 acquisition_source_id="google-acquisition",
                                 source_kind="data_source", provider_code="google_health",
                                 source_instance_id="synthetic", source_contract_version="v1"))
        session.add(AcquisitionSource(id="google-acquisition", provider_id=provider_id,
                                      input_method="provider_api"))
        for key in ("google:incremental:sleep:list:any",
                    "google:refresh:sleep:list:google-wearables",
                    "google:refresh:sleep:reconcile:any",
                    "google:incremental:heart_rate:list:any"):
            session.add(SyncStreamState(id=key, provider_id=provider_id, stream_code=key,
                                        last_attempt_at=NOW, last_success_at=NOW,
                                        diagnostic_status="present"))
        for record_id, stream, mode, record_family in (
            ("family-list", "sleep", "list", family),
            ("wrong-reconcile", "sleep", "reconcile", None),
            ("heart-rate", "heart_rate", "list", None),
        ):
            session.add(GoogleSourceRecord(
                id=record_id, google_source_id="google-source", raw_payload_id=record_id,
                stream_code=stream, query_mode=mode, data_source_family=record_family,
                record_identity_key=record_id, idempotency_key=record_id,
                temporal_precision="date", source_local_date=DAY, record_status="ok",
                normalization_contract_version="synthetic",
            ))
        session.commit()
    with Session(engine) as session:
        sleep = read_facts(session, SCOPE_BY_KEY["google:sleep"], evaluation_local_date=DAY)
        wearables = read_facts(session, SCOPE_BY_KEY["google:wearables_sleep_reconcile"],
                               evaluation_local_date=DAY)
        hr = read_facts(session, SCOPE_BY_KEY["google:heart_rate"],
                        evaluation_local_date=DAY)
    assert (sleep.last_success_at_utc, sleep.observed_once) == (None, False)
    assert (wearables.last_success_at_utc, wearables.observed_once) == (None, False)
    assert hr.last_success_at_utc is None
    with Session(engine) as session:
        for key in ("google:refresh:sleep:list:any",
                    "google:refresh:sleep:reconcile:google-wearables",
                    "google:refresh:heart_rate:list:any:day:2026-09-24",
                    "google:refresh:heart_rate:list:any:day:2026-09-25"):
            # Older HR days are processed later by Owner refresh; their later
            # attempt clock must not replace the newest civil-day partition.
            older_hr_day = key.endswith("day:2026-09-24")
            session.add(SyncStreamState(
                id=key, provider_id=provider_id, stream_code=key,
                last_attempt_at=NOW if older_hr_day else NOW - timedelta(hours=1),
                last_success_at=NOW if older_hr_day else NOW - timedelta(hours=1),
                diagnostic_status="present",
            ))
        for record_id, mode, record_family in (
            ("normal-list", "list", None), ("wearables", "reconcile", family),
        ):
            session.add(GoogleSourceRecord(
                id=record_id, google_source_id="google-source", raw_payload_id=record_id,
                stream_code="sleep", query_mode=mode, data_source_family=record_family,
                record_identity_key=record_id, idempotency_key=record_id,
                temporal_precision="date", source_local_date=DAY, record_status="ok",
                normalization_contract_version="synthetic",
            ))
        session.commit()
    with Session(engine) as session:
        for key in ("google:sleep", "google:wearables_sleep_reconcile", "google:heart_rate"):
            facts = read_facts(session, SCOPE_BY_KEY[key], evaluation_local_date=DAY)
            assert result(key, facts)["state"] == "fresh"
    with Session(engine) as session:
        state = session.get(SyncStreamState,
                            "google:refresh:heart_rate:list:any:day:2026-09-25")
        state.last_attempt_at = NOW
        state.diagnostic_status = "failed"
        session.commit()
    with Session(engine) as session:
        hr = read_facts(session, SCOPE_BY_KEY["google:heart_rate"],
                        evaluation_local_date=DAY)
    assert result("google:heart_rate", hr)["reason_code"] == "refresh_failed"
    engine.dispose()


@pytest.mark.parametrize(("provider_code", "scope_key", "checkpoint", "run_stream"), [
    ("garmin_connect", "garmin:sleep", "sleep", "garmin_incremental"),
    ("google_health", "google:sleep", "google:refresh:sleep:list:any", "google_refresh"),
])
def test_persisted_provider_auth_failure_precedence(
    tmp_path: Path, provider_code: str, scope_key: str, checkpoint: str, run_stream: str,
) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'auth.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Provider(id="provider", code=provider_code, display_name="Synthetic",
                             provider_kind="wearable"))
        session.add(SyncStreamState(
            id="state", provider_id="provider", stream_code=checkpoint,
            last_attempt_at=NOW - timedelta(hours=2),
            last_success_at=NOW - timedelta(hours=2), diagnostic_status="present",
        ))
        session.add(SyncRun(id="generic-partial", provider_id="provider",
                            stream_code=run_stream, status="partial", item_count=4,
                            started_at=NOW - timedelta(hours=1),
                            completed_at=NOW - timedelta(hours=1)))
        session.commit()
    with Session(engine) as session:
        partial = read_facts(session, SCOPE_BY_KEY[scope_key], evaluation_local_date=DAY)
    assert partial.terminal_status != "failed"
    with Session(engine) as session:
        session.add(SyncRun(id="auth-failed", provider_id="provider",
                            stream_code=run_stream, status="failed", item_count=0,
                            error_category="reauth_required",
                            started_at=NOW - timedelta(minutes=31),
                            completed_at=NOW - timedelta(minutes=30)))
        session.commit()
    with Session(engine) as session:
        blocked = read_facts(session, SCOPE_BY_KEY[scope_key], evaluation_local_date=DAY)
    assert result(scope_key, blocked)["reason_code"] == "reauth_required"
    with Session(engine) as session:
        state = session.get(SyncStreamState, "state")
        state.last_attempt_at = NOW - timedelta(minutes=10)
        state.last_success_at = NOW - timedelta(minutes=10)
        session.commit()
    with Session(engine) as session:
        recovered = read_facts(session, SCOPE_BY_KEY[scope_key], evaluation_local_date=DAY)
    assert recovered.terminal_status != "reauth_required"
    assert recovered.last_success_at_utc == NOW - timedelta(minutes=10)
    with Session(engine) as session:
        session.add(SyncRun(id="surface-failed", provider_id="provider",
                            stream_code=run_stream, status="failed", item_count=2,
                            error_category="failed", started_at=NOW - timedelta(minutes=8),
                            completed_at=NOW - timedelta(minutes=7)))
        session.commit()
    with Session(engine) as session:
        narrow = read_facts(session, SCOPE_BY_KEY[scope_key], evaluation_local_date=DAY)
    assert narrow.terminal_status != "failed"
    with Session(engine) as session:
        session.add(SyncRun(id="global-failed", provider_id="provider",
                            stream_code=run_stream, status="failed", item_count=0,
                            error_category="failed", started_at=NOW - timedelta(minutes=5),
                            completed_at=NOW - timedelta(minutes=4)))
        session.commit()
    with Session(engine) as session:
        failed = read_facts(session, SCOPE_BY_KEY[scope_key], evaluation_local_date=DAY)
    assert result(scope_key, failed)["reason_code"] == "refresh_failed"
    engine.dispose()


def test_persisted_activity_sources_are_window_scoped(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'activity-sources.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Provider(id="garmin", code="garmin_connect", display_name="Garmin",
                             provider_kind="wearable"))
        for source_id in ("activity-acquisition", "training-acquisition",
                          "other-activity-acquisition"):
            session.add(AcquisitionSource(id=source_id, provider_id="garmin",
                                          input_method="provider_api"))
            session.add(GarminSource(id=source_id, provider_id="garmin",
                                     acquisition_source_id=source_id, source_kind="account",
                                     provider_code="garmin_connect",
                                     source_instance_id=source_id))
        session.add(SyncStreamState(id="activity-state", provider_id="garmin",
                                    stream_code="activities", last_attempt_at=NOW,
                                    last_success_at=NOW, diagnostic_status="present"))
        session.add(CoverageInterval(
            id="activity-coverage", provider_id="garmin",
            acquisition_source_id="activity-acquisition", stream_code="activity",
            metric_code="activities", resolution="day", status="present",
            interval_start=datetime(2026, 9, 19, tzinfo=UTC),
            interval_end=datetime(2026, 9, 26, tzinfo=UTC), observed_count=1,
            calculation_rule_version="synthetic",
        ))
        session.add(GarminSourceRecord(
            id="activity-record", garmin_source_id="activity-acquisition",
            raw_payload_id="synthetic-payload", stream_code="activity",
            idempotency_key="synthetic-activity", temporal_precision="date",
            source_local_date=DAY, record_status="ok",
            normalization_contract_version="synthetic",
        ))
        session.commit()
    with Session(engine) as session:
        one = read_facts(session, SCOPE_BY_KEY["garmin:activities"],
                         evaluation_local_date=DAY)
    assert result("garmin:activities", one)["state"] == "fresh"
    with Session(engine) as session:
        session.add(GarminSourceRecord(
            id="second-activity-record", garmin_source_id="other-activity-acquisition",
            raw_payload_id="second-synthetic-payload", stream_code="activity",
            idempotency_key="second-synthetic-activity", temporal_precision="date",
            source_local_date=DAY, record_status="ok",
            normalization_contract_version="synthetic",
        ))
        session.commit()
    with Session(engine) as session:
        competing = read_facts(session, SCOPE_BY_KEY["garmin:activities"],
                               evaluation_local_date=DAY)
    assert result("garmin:activities", competing)["reason_code"] == "scope_unresolved"
    engine.dispose()
